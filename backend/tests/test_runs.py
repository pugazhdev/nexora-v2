"""RunService: start, sequential processing, cancel, retry, timeout, shutdown."""
import asyncio
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.errors import AppError, ConflictError
from app.research.deps import Cancelled
from app.research.schemas import ItemResult
from app.runs.service import RunService


def qn(key, kind="number", required=True):
    return {"key": key, "label": key.title(), "help": None, "kind": kind, "options": [], "unit": None,
            "min": 1, "max": None, "default": None, "required": required, "price_relevant": False}


def mk_item(name, answers=None, questions=None):
    return {"name": name, "analysis": {"category": "consumable"},
            "questions": questions or [qn("quantity")], "answers": answers if answers is not None else {"quantity": 100}}


def seed(repo, *items):
    rid = repo.create_research("x", None, "T", list(items) or [mk_item("Syringe")])
    return rid, [i["id"] for i in repo.get_research(rid)["items"]]


def service(repo, fn, grace=30.0, **kw):
    s = Settings(_env_file=None, **kw)
    make = lambda run_id, cancel: SimpleNamespace(run_id=run_id, cancel=cancel, repo=repo)  # noqa: E731
    return RunService(s, repo, make, research_fn=fn, grace_seconds=grace)


async def finish(svc):
    await asyncio.gather(*list(svc.tasks.values()))


def result(spec):
    return ItemResult(spec_title=spec.title, quantity=spec.quantity)


async def until(cond, limit=2.0):
    for _ in range(int(limit / 0.005)):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not met")


def latest(repo, item):
    return repo.runs_for_item(item)[0]


async def test_start_rejects_missing_answers(repo):
    rid, (a, b) = seed(repo, mk_item("A"), mk_item("B", answers={}))
    svc = service(repo, None)
    with pytest.raises(AppError) as e:
        await svc.start(rid)
    assert list(e.value.details["items"]) == [b] and "quantity" in e.value.details["items"][b]
    assert repo.runs_for_item(a) == []


async def test_start_rejects_when_every_item_deselected(repo):
    rid, (a,) = seed(repo)
    repo.update_item(a, selected=False)
    with pytest.raises(AppError, match="Select at least one item"):
        await service(repo, None).start(rid)
    assert repo.runs_for_item(a) == []


async def test_items_run_one_after_another(repo):
    log = []

    async def fn(deps, spec, mode):
        log.append(("start", spec.name))
        await asyncio.sleep(0.02)
        log.append(("end", spec.name))
        return result(spec)

    rid, (a, b) = seed(repo, mk_item("A"), mk_item("B"))
    svc = service(repo, fn)
    runs = await svc.start(rid)
    assert len(runs) == 2
    await finish(svc)
    assert log == [("start", "A"), ("end", "A"), ("start", "B"), ("end", "B")]
    for item in (a, b):
        r = latest(repo, item)
        assert r["status"] == "done" and r["result"]["quantity"] == 100 and r["finished_at"]


async def test_start_twice_conflicts(repo):
    gate = asyncio.Event()

    async def fn(deps, spec, mode):
        await gate.wait()
        return result(spec)

    rid, _ = seed(repo)
    svc = service(repo, fn)
    await svc.start(rid)
    with pytest.raises(ConflictError):
        await svc.start(rid)
    gate.set()
    await finish(svc)


async def test_quantity_multiplies_unit_basis(repo):
    rid, (a,) = seed(repo, mk_item("Gloves", {"quantity": "10", "unit_basis": 100},
                                   [qn("quantity"), qn("unit_basis")]))
    svc = service(repo, lambda d, s, m: asyncio.sleep(0, result(s)))
    await svc.start(rid)
    await finish(svc)
    assert latest(repo, a)["spec"]["quantity"] == 1000


async def test_cancel_marks_running_and_queued_cancelled(repo):
    async def fn(deps, spec, mode):
        await deps.cancel.wait()
        raise Cancelled()

    rid, (a, b) = seed(repo, mk_item("A"), mk_item("B"))
    svc = service(repo, fn)
    await svc.start(rid)
    await until(lambda: latest(repo, a)["status"] == "researching")
    await svc.cancel(rid)
    assert latest(repo, b)["status"] == "cancelled"
    await finish(svc)
    ra = latest(repo, a)
    assert ra["status"] == "cancelled" and ra["result"] is None and ra["finished_at"]


async def test_cancel_discards_result_returned_after_cancel(repo):
    async def fn(deps, spec, mode):
        await until(deps.cancel.is_set)
        return result(spec)

    rid, (a,) = seed(repo)
    svc = service(repo, fn)
    await svc.start(rid)
    await until(lambda: latest(repo, a)["status"] == "researching")
    await svc.cancel(rid)
    await finish(svc)
    assert latest(repo, a)["status"] == "cancelled" and latest(repo, a)["result"] is None


async def test_retry_only_from_terminal_failure_states(repo):
    async def fn(deps, spec, mode):
        return result(spec)

    rid, (a,) = seed(repo)
    svc = service(repo, fn)
    with pytest.raises(ConflictError):
        await svc.retry(a)  # never run
    await svc.start(rid)
    await finish(svc)
    with pytest.raises(ConflictError):
        await svc.retry(a)  # done
    for status in ("failed", "interrupted", "cancelled"):
        old = latest(repo, a)["id"]
        repo.create_run(a, {}, {})
        repo.set_run(latest(repo, a)["id"], status=status)
        new = await svc.retry(a)
        assert new != old
        await finish(svc)
        assert latest(repo, a)["id"] == new and latest(repo, a)["status"] == "done"
    repo.create_run(a, {}, {})
    with pytest.raises(ConflictError):
        await svc.retry(a)  # queued


async def test_timeout_marks_failed(repo):
    async def fn(deps, spec, mode):
        await asyncio.sleep(10)

    rid, (a,) = seed(repo)
    svc = service(repo, fn, grace=0.0, item_timeout_seconds=0.05)
    await svc.start(rid)
    await finish(svc)
    r = latest(repo, a)
    assert r["status"] == "failed" and r["error"] == "Research timed out"


async def test_failure_marks_failed_and_continues(repo):
    async def fn(deps, spec, mode):
        if spec.name == "A":
            raise RuntimeError("boom secret detail")
        if spec.name == "B":
            raise AppError("Search providers are down.")
        return result(spec)

    rid, (a, b, c) = seed(repo, mk_item("A"), mk_item("B"), mk_item("C"))
    svc = service(repo, fn)
    await svc.start(rid)
    await finish(svc)
    assert latest(repo, a)["error"] == "Research failed unexpectedly"
    assert latest(repo, b)["error"] == "Search providers are down."
    assert [latest(repo, x)["status"] for x in (a, b, c)] == ["failed", "failed", "done"]


async def test_concurrency_limited_across_research(repo):
    running, peak = 0, 0

    async def fn(deps, spec, mode):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1
        return result(spec)

    svc = service(repo, fn, research_concurrency=2)
    for _ in range(3):
        rid, _ = seed(repo)
        await svc.start(rid)
    await finish(svc)
    assert peak == 2


async def test_shutdown_marks_running_and_queued_interrupted(repo):
    async def fn(deps, spec, mode):
        await asyncio.sleep(10)

    rid, (a, b) = seed(repo, mk_item("A"), mk_item("B"))
    svc = service(repo, fn)
    await svc.start(rid)
    await until(lambda: latest(repo, a)["status"] == "researching")
    await svc.shutdown()
    assert [latest(repo, x)["status"] for x in (a, b)] == ["interrupted", "interrupted"]
    assert not svc.tasks


def test_set_run_ignores_update_after_terminal(repo):
    rid, (a,) = seed(repo)
    run = repo.create_run(a, {}, {})
    assert repo.set_run(run, status="cancelled") is True
    assert repo.set_run(run, status="done", result={"x": 1}) is False
    r = latest(repo, a)
    assert r["status"] == "cancelled" and r["result"] is None


def test_mark_interrupted_covers_queued_and_sets_finished_at(repo):
    rid, (a,) = seed(repo)
    repo.create_run(a, {}, {})
    assert repo.mark_interrupted() == 1
    r = latest(repo, a)
    assert r["status"] == "interrupted" and r["finished_at"]
