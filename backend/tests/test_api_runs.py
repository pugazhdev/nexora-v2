"""Run endpoints: start, cancel, retry, SSE events, restart recovery."""
import asyncio
import json
import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.research.deps import Cancelled
from app.research.schemas import ItemResult
from tests.fakes import FakeLLM
from tests.test_runs import mk_item, seed


async def quick(deps, spec, mode):
    for msg in ("Searching", "Found 3 listings"):
        deps.repo.add_event(deps.run_id, "search", msg)
        await asyncio.sleep(0.01)
    return ItemResult(spec_title=spec.title, quantity=spec.quantity, notes=["ok"])


async def block(deps, spec, mode):  # like the graph: runs until the guard sees the cancel event
    for _ in range(3000):
        if deps.cancel.is_set():
            raise Cancelled()
        await asyncio.sleep(0.01)


def fast(settings: Settings) -> Settings:
    return settings.model_copy(update={"sse_poll_seconds": 0.02, "sse_idle_close_seconds": 0.1})


def app_client(settings, fn):
    return TestClient(create_app(fast(settings), db=Database(settings.database_url), research_fn=fn, llm=FakeLLM({})))


def wait_for(c, rid, cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        body = c.get(f"/api/research/{rid}").json()
        if cond(body):
            return body
        time.sleep(0.01)
    raise AssertionError(body)


def statuses(body):
    return [i["latest_run"]["status"] if i["latest_run"] else None for i in body["items"]]


def test_start_validates_and_returns_run_ids(settings, db, repo):
    rid, _ = seed(repo, mk_item("A", answers={}))
    with app_client(settings, quick) as c:
        r = c.post(f"/api/research/{rid}/start")
        assert r.status_code == 400 and r.json()["error"]["details"]["items"]
        rid2, _ = seed(repo, mk_item("A"), mk_item("B"))
        r = c.post(f"/api/research/{rid2}/start")
        assert r.status_code == 200 and len(r.json()["run_ids"]) == 2
        wait_for(c, rid2, lambda b: b["status"] == "done")
        assert c.post("/api/research/nope/start").status_code == 404


def test_cancel_endpoint(settings, db, repo):
    rid, _ = seed(repo, mk_item("A"), mk_item("B"))
    with app_client(settings, block) as c:
        c.post(f"/api/research/{rid}/start")
        wait_for(c, rid, lambda b: statuses(b)[0] == "researching")
        assert c.post(f"/api/research/{rid}/cancel").status_code == 200
        wait_for(c, rid, lambda b: statuses(b) == ["cancelled", "cancelled"])


def test_restart_marks_interrupted_and_retry_works(settings, db, repo):
    rid, (a,) = seed(repo)
    with app_client(settings, block) as c1:
        assert c1.post(f"/api/research/{rid}/start").status_code == 200
        wait_for(c1, rid, lambda b: statuses(b) == ["researching"])
        old = repo.runs_for_item(a)[0]["id"]
        with app_client(settings, quick) as c2:  # the "restarted" server on the same DB file
            body = c2.get(f"/api/research/{rid}").json()
            assert statuses(body) == ["interrupted"]
            r = c2.post(f"/api/items/{a}/retry")
            assert r.status_code == 200 and r.json()["run_id"] != old
            wait_for(c2, rid, lambda b: statuses(b) == ["done"])
            assert c2.post(f"/api/items/{a}/retry").status_code == 409
    assert [x["status"] for x in repo.runs_for_item(a)] == ["done", "interrupted"]


def test_edit_answers_after_done_then_start_creates_new_run(settings, db, repo):
    rid, (a,) = seed(repo)
    with app_client(settings, quick) as c:
        c.post(f"/api/research/{rid}/start")
        wait_for(c, rid, lambda b: b["status"] == "done")
        r = c.patch(f"/api/research/{rid}/items/{a}", json={"answers": {"quantity": 500}})
        assert r.status_code == 200
        assert c.post(f"/api/research/{rid}/start").status_code == 200
        body = wait_for(c, rid, lambda b: b["status"] == "done" and b["items"][0]["latest_run"]["spec"]["quantity"] == 500)
        assert body["items"][0]["latest_run"]["result"]["quantity"] == 500
    runs = repo.runs_for_item(a)
    assert len(runs) == 2 and runs[1]["result"]["quantity"] == 100 and runs[1]["answers"] == {"quantity": 100}


def parse_sse(text):
    msgs = []
    for block_ in text.replace("\r\n", "\n").split("\n\n"):
        m = {}
        for line in block_.split("\n"):
            if line.startswith(":") or ": " not in line:
                continue
            k, v = line.split(": ", 1)
            m[k] = v
        if m:
            msgs.append(m)
    return msgs


def stream(c, url, **kw):
    with c.stream("GET", url, **kw) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        return parse_sse("".join(r.iter_text()))


def test_sse_streams_steps_then_closes(settings, db, repo):
    rid, _ = seed(repo, mk_item("A"), mk_item("B"))
    with app_client(settings, quick) as c:
        c.post(f"/api/research/{rid}/start")
        msgs = stream(c, f"/api/research/{rid}/events")  # returns only because the stream closed
        steps = [m for m in msgs if m["event"] == "step"]
        assert [json.loads(m["data"])["message"] for m in steps] == ["Searching", "Found 3 listings"] * 2
        ids = [int(m["id"]) for m in steps]
        assert ids == sorted(ids) and json.loads(steps[0]["data"])["item_id"]
        status = [json.loads(m["data"]) for m in msgs if m["event"] == "status"]
        assert status[-1]["status"] == "done"
        assert [i["status"] for i in status[-1]["items"]] == ["done", "done"]
        later = stream(c, f"/api/research/{rid}/events?after={ids[1]}")
        assert [int(m["id"]) for m in later if m["event"] == "step"] == ids[2:]
        resumed = stream(c, f"/api/research/{rid}/events", headers={"Last-Event-ID": str(ids[2])})
        assert [int(m["id"]) for m in resumed if m["event"] == "step"] == ids[3:]
        assert c.get("/api/research/nope/events").status_code == 404


def test_sse_ends_cleanly_when_research_deleted(settings, db, repo, monkeypatch):
    from app.repo import Repository

    rid, _ = seed(repo)
    orig = Repository.events_after

    def deleting(self, research_id, after_id):
        out = orig(self, research_id, after_id)
        self.delete_research(research_id)
        return out

    monkeypatch.setattr(Repository, "events_after", deleting)
    with TestClient(create_app(fast(settings), db=db, llm=FakeLLM({}))) as c:
        assert stream(c, f"/api/research/{rid}/events") == []
