"""Background research runs: one sequential worker per research, a shared semaphore across researches."""
import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from decimal import Decimal

from app.config import Settings
from app.errors import AppError, ConflictError
from app.intake.schemas import Question, _num, validate_answers
from app.repo import ACTIVE, Repository
from app.research.deps import Cancelled, ResearchDeps
from app.research.graph import run_research
from app.research.schemas import ItemResult, PartResult, ResearchSpec, RetailResult, SplitResult
from app.research.spec import build_part_spec, build_spec
from app.research.tiers import purchase_range

log = logging.getLogger("pharmasource")

RETRYABLE = {"failed", "interrupted", "cancelled"}
ResearchFn = Callable[[ResearchDeps, ResearchSpec, str], Awaitable[ItemResult]]
RetailFn = Callable[[ResearchDeps, ResearchSpec], Awaitable[RetailResult]]


def quantity_of(answers: dict) -> int:
    """Quantity in units; unit_basis (pieces per box) is only asked when quantity was given in boxes."""
    qty = _num(answers.get("quantity")) or 1
    return max(1, int(qty * (_num(answers.get("unit_basis")) or 1)))


def _log_task_error(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        log.error("background task failed", exc_info=task.exception())


class RunService:
    def __init__(self, settings: Settings, repo: Repository,
                 make_deps: Callable[[str, asyncio.Event], ResearchDeps],
                 research_fn: ResearchFn = run_research, grace_seconds: float = 30.0,
                 retail_fn: RetailFn | None = None):
        self.settings, self.repo, self.make_deps, self.research_fn = settings, repo, make_deps, research_fn
        self.retail_fn = retail_fn  # item mode only, beside the research; None skips it
        self.timeout = settings.item_timeout_seconds + grace_seconds
        self.sem = asyncio.Semaphore(settings.research_concurrency)
        self.tasks: dict[str, asyncio.Task] = {}  # research_id -> worker
        self.queues: dict[str, deque[tuple[str, ResearchSpec]]] = {}
        self.running: dict[str, asyncio.Event] = {}  # run_id -> cancel event
        self.split_tasks: dict[str, asyncio.Task] = {}  # run_id -> split task

    def _queue_run(self, item: dict) -> tuple[str, ResearchSpec]:
        answers = item["answers"]
        spec = build_spec(item, answers, quantity_of(answers))
        return self.repo.create_run(item["id"], answers, spec.model_dump(mode="json")), spec

    def _launch(self, research_id: str, runs: list[tuple[str, ResearchSpec]]) -> None:
        if research_id in self.tasks:  # worker alive: it picks these up after its current item
            self.queues[research_id].extend(runs)
            return
        self.queues[research_id] = deque(runs)
        self.tasks[research_id] = asyncio.create_task(self._worker(research_id))
        self.tasks[research_id].add_done_callback(_log_task_error)

    async def start(self, research_id: str) -> list[str]:
        items = self.repo.get_research(research_id)["items"]
        if research_id in self.tasks or any(i["latest_run"] and i["latest_run"]["status"] in ACTIVE for i in items):
            raise ConflictError("Research is already running.")
        selected = [i for i in items if i["selected"]]
        if not selected:
            raise AppError("Select at least one item to research.")
        errors = {}
        for i in selected:
            if e := validate_answers([Question.model_validate(q) for q in i["questions"]], i["answers"]):
                errors[i["id"]] = e
        if errors:
            raise AppError("Some items need answers before research can start.", details={"items": errors})
        runs = [self._queue_run(i) for i in selected]  # get_research returns items in position order
        self._launch(research_id, runs)
        return [r for r, _ in runs]

    async def retry(self, item_id: str) -> str:
        item = self.repo.get_item(item_id)
        runs = self.repo.runs_for_item(item_id)
        if not runs or runs[0]["status"] not in RETRYABLE:
            raise ConflictError("Only failed, interrupted or cancelled items can be retried.")
        if e := validate_answers([Question.model_validate(q) for q in item["questions"]], item["answers"]):
            raise AppError("This item needs answers before research can start.", details={"items": {item_id: e}})
        run = self._queue_run(item)
        self._launch(item["research_id"], [run])
        return run[0]

    async def cancel(self, research_id: str) -> None:
        items = self.repo.get_research(research_id)["items"]
        self.queues.get(research_id, deque()).clear()
        for i in items:
            run = i["latest_run"]
            if run and run["status"] in ACTIVE:
                if run["id"] in self.running:
                    self.running[run["id"]].set()  # guard raises Cancelled at the next node
                else:
                    self.repo.set_run(run["id"], status="cancelled")

    async def _worker(self, research_id: str) -> None:
        q = self.queues[research_id]
        cancelled = False
        try:
            while q:
                run_id, spec = q.popleft()
                try:
                    await self._run_one(run_id, spec)
                except Exception:
                    log.exception("run %s crashed", run_id)
                    self._fail(run_id, "Research failed unexpectedly")
        except asyncio.CancelledError:
            cancelled = True  # shutdown() marks the queued runs interrupted
            raise
        finally:
            if not cancelled:
                for run_id, _ in q:
                    self._fail(run_id, "Research failed unexpectedly")
            del self.tasks[research_id], self.queues[research_id]

    def _fail(self, run_id: str, error: str) -> None:
        try:
            self.repo.set_run(run_id, status="failed", error=error)
        except Exception:
            log.exception("could not mark run %s failed", run_id)

    async def _run_one(self, run_id: str, spec: ResearchSpec) -> None:
        cancel = asyncio.Event()
        try:
            async with self.sem:
                if not self.repo.set_run(run_id, status="researching"):
                    return  # cancelled while it waited in the queue
                self.running[run_id] = cancel
                deps = self.make_deps(run_id, cancel)
                research = asyncio.wait_for(self.research_fn(deps, spec, "item"), self.timeout)
                if self.retail_fn:
                    retail = asyncio.ensure_future(self._retail(run_id, deps, spec))
                    try:
                        result = await research
                    except BaseException:
                        retail.cancel()  # a failed or cancelled item stores no retail result
                        raise
                    await retail
                else:
                    result = await research
        except Cancelled:
            self.repo.set_run(run_id, status="cancelled")
        except TimeoutError:
            self.repo.set_run(run_id, status="failed", error="Research timed out")
        except asyncio.CancelledError:  # server shutdown, also while waiting for the semaphore
            self.repo.set_run(run_id, status="interrupted")
            raise
        except AppError as exc:
            self.repo.set_run(run_id, status="failed", error=exc.message)
        except Exception:
            log.exception("research run %s failed", run_id)
            self.repo.set_run(run_id, status="failed", error="Research failed unexpectedly")
        else:
            if cancel.is_set():  # partial results of a cancelled item are discarded
                self.repo.set_run(run_id, status="cancelled")
            else:
                self.repo.set_run(run_id, status="done", result=result.model_dump(mode="json"))
        finally:
            self.running.pop(run_id, None)

    async def _retail(self, run_id: str, deps: ResearchDeps, spec: ResearchSpec) -> None:
        """Never raises (except on shutdown): a retail failure is stored as an empty result with a note."""
        try:
            res = await asyncio.wait_for(self.retail_fn(deps, spec), self.timeout)
        except asyncio.CancelledError:
            raise
        except Cancelled:
            return  # the item was cancelled; its results are discarded
        except Exception:
            log.exception("retail lookup for run %s failed", run_id)
            res = RetailResult(notes=["Retail: lookup failed"])
        try:
            self.repo.set_retail(run_id, res.model_dump(mode="json"))
        except Exception:
            log.exception("could not save retail for run %s", run_id)

    async def split(self, item_id: str) -> None:
        """Start part research for a done item; progress goes to the latest run's event stream (phase "split")."""
        item = self.repo.get_item(item_id)
        analysis = item["analysis"] or {}
        parts = analysis.get("parts") or []
        if not analysis.get("splittable") or not parts:
            raise ConflictError("This item cannot be split into parts.")
        runs = self.repo.runs_for_item(item_id)
        if not runs or runs[0]["status"] != "done":
            raise ConflictError("Finish the item research before splitting it.")
        run = runs[0]
        if run["split_status"] == "running":
            raise ConflictError("A split is already running for this item.")
        self.repo.set_split(run["id"], status="running", split={}, error="")
        task = asyncio.create_task(self._split_task(run, parts))
        task.add_done_callback(_log_task_error)
        self.split_tasks[run["id"]] = task

    async def _split_task(self, run: dict, parts: list[dict]) -> None:
        run_id = run["id"]
        try:
            res = await self._split_parts(run, parts)
            self.repo.set_split(run_id, status="done", split=res.model_dump(mode="json"))
            self._event(run_id, "Split finished" if res.complete else "Split finished with missing parts")
        except asyncio.CancelledError:
            self.repo.set_split(run_id, status="interrupted")
            raise
        except Exception:
            log.exception("split of run %s failed", run_id)
            try:
                self.repo.set_split(run_id, status="failed", error="Split failed unexpectedly")
            except Exception:
                log.exception("could not mark split of run %s failed", run_id)
        finally:
            self.split_tasks.pop(run_id, None)

    def _event(self, run_id: str, message: str) -> None:
        try:
            self.repo.add_event(run_id, "split", message[:300])
        except Exception:
            log.exception("could not record split event")

    async def _split_parts(self, run: dict, parts: list[dict]) -> SplitResult:
        parent = ResearchSpec.model_validate(run["spec"])
        self._event(run["id"], f"Researching {len(parts)} parts")

        async def one(part: dict) -> tuple[PartResult, Decimal | None]:
            spec = build_part_spec(parent, part)
            count = max(1, int(part.get("count_per_unit") or 1))
            out, unit = PartResult(part=part["name"], count_per_unit=count, offer=None), None
            try:
                async with self.sem:
                    self._event(run["id"], f"Searching for {spec.name}")
                    deps = self.make_deps(run["id"], asyncio.Event())
                    result = await asyncio.wait_for(self.research_fn(deps, spec, "part"), self.timeout)
                rng = purchase_range(result.offers, spec.quantity)
                out.offer = next((o for o in result.offers if o.id == rng.lowest_id), None)
                unit = rng.lowest_unit
                out.notes = result.notes
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # one failing part never fails the split
                log.exception("part %s failed", part["name"])
                out.notes = [f"Research failed: {getattr(exc, 'message', None) or exc}"]
            found = f"cheapest from {out.offer.manufacturer}" if out.offer else "no manufacturer found"
            self._event(run["id"], f"{spec.name}: {found}")
            return out, unit

        done = await asyncio.gather(*(one(p) for p in parts))
        complete = all(unit is not None and r.offer for r, unit in done)
        total = sum((unit * r.count_per_unit for r, unit in done), Decimal(0)) if complete else None
        finished = purchase_range(ItemResult.model_validate(run["result"]).offers, parent.quantity).lowest_unit
        return SplitResult(parts=[r for r, _ in done], parts_total=total, finished_lowest=finished, complete=complete)

    async def shutdown(self) -> None:
        queued = [run_id for q in self.queues.values() for run_id, _ in q]
        tasks = [*self.tasks.values(), *self.split_tasks.values()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for run_id in queued:
            self.repo.set_run(run_id, status="interrupted")
