"""HTTP routes.

Research JSON (flat): id, title, created_at (UTC, "...Z"), image_path (or null), status (draft|researching|done),
message (screening note on POST, else null), items[].
Item JSON: id, position, name, category, in_scope, scope_reason, selected, known_attributes, questions,
answers, answer_errors (validate_answers on current answers), splittable, parts, image_region_hint,
latest_run (run row or null).
History rows: id, title, created_at, status.
Errors: {"error": {"code", "message", "details"}}.
"""

import asyncio
import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Header, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.api.deps import analyse_limit, get_db, get_llm, get_repo, get_runs, get_settings_dep
from app.config import Settings
from app.db import Database
from app.errors import ConfigError, ConflictError, NotFoundError
from app.intake.graph import run_intake
from app.intake.image import sniff_mime
from app.intake.schemas import Question, validate_answers
from app.repo import TERMINAL, Repository
from app.research.domains import build_denylist
from app.runs.service import RunService

router = APIRouter(prefix="/api")

_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_CONFIG_MSG = "Set OPENAI_API_KEY, OPENAI_MODEL and OPENAI_VISION_MODEL in backend/.env"


def _require_llm(llm) -> None:
    if not llm.is_configured():
        err = ConfigError(_CONFIG_MSG)
        err.code = "config_missing"
        raise err


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Database = Depends(get_db)):
    if db.ping():
        return {"status": "ready"}
    body = {"error": {"code": "not_ready", "message": "Database is not ready.", "details": {}}}
    return JSONResponse(body, status_code=503)


def _item_json(row: dict) -> dict:
    a = row["analysis"]
    questions = [Question.model_validate(q) for q in row["questions"]]
    return {
        "id": row["id"],
        "position": row["position"],
        "name": row["name"],
        "category": a.get("category"),
        "in_scope": a.get("in_scope", True),
        "scope_reason": a.get("scope_reason"),
        "selected": row["selected"],
        "known_attributes": a.get("known_attributes", []),
        "questions": row["questions"],
        "answers": row["answers"],
        "answer_errors": validate_answers(questions, row["answers"]),
        "splittable": a.get("splittable", False),
        "parts": a.get("parts", []),
        "image_region_hint": a.get("image_region_hint", ""),
        "latest_run": row["latest_run"],
    }


def _research_json(row: dict, message: str | None = None) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "image_path": row["image_path"],
        "status": row["status"],
        "message": message,
        "items": [_item_json(i) for i in row["items"]],
    }


def _title(screened) -> str:
    names = [s.item.name for s in screened.items if s.in_scope] or [s.item.name for s in screened.items]
    return ", ".join(names)[:60] or "Untitled research"


def _save_upload(uploads: Path, rid: str, data: bytes) -> str:
    uploads.mkdir(parents=True, exist_ok=True)
    path = uploads / f"{rid}.{_EXT[sniff_mime(data)]}"
    path.write_bytes(data)
    return path.as_posix()


@router.post("/research", dependencies=[Depends(analyse_limit)])
async def analyse(
    image: UploadFile | None = None,
    text: str | None = Form(None),
    llm=Depends(get_llm),
    settings: Settings = Depends(get_settings_dep),
    repo: Repository = Depends(get_repo),
):
    _require_llm(llm)
    data = await image.read() if image else None
    screened = await run_intake(llm, settings, text=text, image_bytes=data or None)  # validates the image too
    rid = repo.create_research(
        (text or "").strip() or None,
        None,
        _title(screened),
        [
            {
                "name": s.item.name,
                "analysis": {
                    **s.item.model_dump(exclude={"questions"}),
                    "in_scope": s.in_scope,
                    "scope_reason": s.scope_reason,
                },
                "questions": [q.model_dump() for q in s.item.questions],
                "answers": {
                    q.key: q.default for q in s.item.questions if q.default is not None
                },
                "selected": s.selected,
            }
            for s in screened.items
        ],
    )
    if data:
        path = await asyncio.to_thread(_save_upload, Path(settings.uploads_dir), rid, data)
        repo.set_image_path(rid, path)
    return _research_json(repo.get_research(rid), screened.message)


@router.get("/research")
def history(limit: int = 20, offset: int = 0, repo: Repository = Depends(get_repo)):
    return repo.list_research(max(1, min(limit, 100)), max(0, offset))


@router.get("/research/{research_id}")
def get_research(research_id: str, repo: Repository = Depends(get_repo)):
    return _research_json(repo.get_research(research_id))


@router.delete("/research/{research_id}", status_code=204)
def delete_research(
    research_id: str,
    repo: Repository = Depends(get_repo),
    runs: RunService = Depends(get_runs),
    settings: Settings = Depends(get_settings_dep),
):
    if research_id in runs.tasks:  # a worker is still alive for it
        raise ConflictError("Cancel the research before deleting it.")
    path = repo.delete_research(research_id)
    if path:
        f, root = Path(path).resolve(), Path(settings.uploads_dir).resolve()
        if f.is_relative_to(root):  # never delete outside the uploads folder
            f.unlink(missing_ok=True)
    return Response(status_code=204)


class ItemPatch(BaseModel):
    selected: bool | None = None
    answers: dict | None = None


@router.patch("/research/{research_id}/items/{item_id}")
def patch_item(research_id: str, item_id: str, body: ItemPatch, repo: Repository = Depends(get_repo)):
    items = repo.get_research(research_id)["items"]
    row = next((i for i in items if i["id"] == item_id), None)
    if not row:
        raise NotFoundError("Item not found.")
    if body.selected and not row["analysis"].get("in_scope", True):
        raise ConflictError("This item is out of scope and cannot be selected.")
    updated = repo.update_item(item_id, selected=body.selected, answers=body.answers)
    return _item_json({**row, **updated})


@router.post("/research/{research_id}/start")
async def start(research_id: str, runs: RunService = Depends(get_runs), llm=Depends(get_llm)):
    _require_llm(llm)
    return {"run_ids": await runs.start(research_id)}


@router.post("/research/{research_id}/cancel")
async def cancel(research_id: str, runs: RunService = Depends(get_runs), repo: Repository = Depends(get_repo)):
    await runs.cancel(research_id)
    return _research_json(repo.get_research(research_id))


@router.post("/items/{item_id}/retry")
async def retry(item_id: str, runs: RunService = Depends(get_runs)):
    return {"run_id": await runs.retry(item_id)}


@router.post("/items/{item_id}/split")
async def split(item_id: str, runs: RunService = Depends(get_runs), llm=Depends(get_llm)):
    _require_llm(llm)
    await runs.split(item_id)
    return {"status": "running"}


def _sse(event: str, data: dict, eid: int | None = None) -> str:
    head = f"id: {eid}\n" if eid is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data)}\n\n"


def _snapshot(research: dict) -> dict:
    items = [
        {"item_id": i["id"], "run_id": r["id"], "status": r["status"], "error": r["error"]}
        for i in research["items"]
        if (r := i["latest_run"])
    ]
    return {"status": research["status"], "items": items}


@router.get("/research/{research_id}/events")
async def events(
    research_id: str,
    request: Request,
    after: int | None = None,
    last_event_id: str | None = Header(None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings_dep),
):
    repo.get_research(research_id)  # 404 before the stream opens
    if after is None:
        after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    async def stream():
        cursor, last, quiet_since, sent_at = after, None, time.monotonic(), time.monotonic()
        while not await request.is_disconnected():
            out = []
            try:
                events = await asyncio.to_thread(repo.events_after, research_id, cursor)
                research = await asyncio.to_thread(repo.get_research, research_id)
            except NotFoundError:  # deleted while streaming: end cleanly
                return
            for e in events:
                cursor = e["id"]
                out.append(_sse("step", e, cursor))
            snap = _snapshot(research)
            if snap != last:
                last = snap
                out.append(_sse("status", snap, cursor))
            now_ = time.monotonic()
            if out:
                quiet_since = sent_at = now_
                yield "".join(out)
            elif now_ - sent_at >= settings.sse_keepalive_seconds:
                sent_at = now_
                yield ": keepalive\n\n"
            selected = [i["latest_run"] for i in research["items"] if i["selected"]]
            finished = all(r is None or r["status"] in TERMINAL for r in selected)
            if finished and now_ - quiet_since >= settings.sse_idle_close_seconds:
                return
            await asyncio.sleep(settings.sse_poll_seconds)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)


def _manufacturer_json(m: dict) -> dict:
    return {
        "id": m["id"],
        "name": m["display_name"],
        "city": m["city"],
        "state": m["state"],
        "website": m["website"],
        "platforms": m["platforms"],
        "listing_count": m["listing_count"],
        "last_seen": m["last_seen"],
        "starred": m["starred"],
        "confirmed": m["confirmed"],
    }


@router.get("/manufacturers/count")
def manufacturer_count(repo: Repository = Depends(get_repo)):
    return repo.manufacturer_counts()


@router.get("/manufacturers")
def manufacturers(
    starred: bool | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: Repository = Depends(get_repo),
):
    return [_manufacturer_json(m) for m in repo.list_manufacturers(starred, q, limit, offset)]


class ManufacturerPatch(BaseModel):
    starred: bool


@router.patch("/manufacturers/{manufacturer_id}")
def patch_manufacturer(manufacturer_id: str, body: ManufacturerPatch, repo: Repository = Depends(get_repo)):
    repo.star_manufacturer(manufacturer_id, body.starred)
    return _manufacturer_json(next(m for m in repo.list_manufacturers() if m["id"] == manufacturer_id))


@router.get("/settings")
def settings_status(settings: Settings = Depends(get_settings_dep), llm=Depends(get_llm)):
    """Read-only configuration status. Never returns key values."""
    return {
        "openai_configured": llm.is_configured(),
        "tavily_configured": bool(settings.tavily_api_key.strip()),
        "model": settings.openai_model,
        "vision_model": settings.openai_vision_model,
        "budgets": {k: v for k, v in settings.model_dump().items() if k.startswith("budget_")},
        "research_concurrency": settings.research_concurrency,
        "denylist": sorted(build_denylist(settings.extra_denylist)),
    }


@router.get("/items/{item_id}/runs")
def item_runs(item_id: str, repo: Repository = Depends(get_repo)):
    repo.get_item(item_id)
    return [{k: r[k] for k in ("id", "status", "started_at", "finished_at")} for r in repo.runs_for_item(item_id)]


@router.get("/runs/{run_id}")
def get_run(run_id: str, repo: Repository = Depends(get_repo)):
    return repo.get_run(run_id)
