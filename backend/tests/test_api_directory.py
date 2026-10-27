"""Manufacturer directory and settings endpoints."""
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from tests.fakes import FakeLLM
from tests.test_runs import mk_item, seed


def seed_directory(repo):
    _, (iid,) = seed(repo, mk_item("Syringe"))
    run = repo.create_run(iid, {}, {})
    a = repo.upsert_manufacturer("Acme Medical", "acme medical", "Mumbai", "MH", "https://acme.example")
    b = repo.upsert_manufacturer("Zed Plastics", "zed plastics", "Chennai", "TN", None)
    for url, plat in (("https://a/1", "indiamart"), ("https://a/2", "tradeindia"), ("https://a/3", "indiamart")):
        repo.add_listing(a, run, {"url": url, "platform": plat})
    repo.add_listing(b, run, {"url": "https://b/1", "platform": "indiamart"})
    return a, b


def test_directory_lists_after_research(client, repo):
    a, b = seed_directory(repo)
    rows = client.get("/api/manufacturers").json()
    assert [r["id"] for r in rows] == [b, a]  # newest last_seen first
    acme = rows[1]
    assert acme["name"] == "Acme Medical" and acme["city"] == "Mumbai" and acme["state"] == "MH"
    assert acme["website"] == "https://acme.example" and acme["starred"] is False
    assert acme["platforms"] == ["indiamart", "tradeindia"] and acme["listing_count"] == 3
    assert acme["last_seen"].endswith("Z")
    assert [r["id"] for r in client.get("/api/manufacturers?q=CHEN").json()] == [b]
    assert [r["id"] for r in client.get("/api/manufacturers?q=acme").json()] == [a]


def test_star_and_filter(client, repo):
    a, b = seed_directory(repo)
    r = client.patch(f"/api/manufacturers/{a}", json={"starred": True})
    assert r.status_code == 200 and r.json()["starred"] is True and r.json()["listing_count"] == 3
    assert [m["id"] for m in client.get("/api/manufacturers?starred=true").json()] == [a]
    assert [m["id"] for m in client.get("/api/manufacturers?starred=false").json()] == [b]
    assert client.patch("/api/manufacturers/nope", json={"starred": True}).status_code == 404
    assert client.patch(f"/api/manufacturers/{a}", json={"starred": "maybe"}).status_code == 422


def test_settings_never_leaks_keys(settings, db):
    s = settings.model_copy(
        update={"openai_api_key": "sk-secret-openai-123", "tavily_api_key": "tvly-secret-456", "openai_model": "m1"}
    )
    with TestClient(create_app(s, db=Database(s.database_url), llm=FakeLLM({}))) as c:
        r = c.get("/api/settings")
    assert "sk-secret-openai-123" not in r.text and "tvly-secret-456" not in r.text
    body = r.json()
    assert body["openai_configured"] is True and body["tavily_configured"] is True
    assert body["model"] == "m1" and body["research_concurrency"] == 2
    assert body["budgets"]["budget_cost_pages"] == 8 and body["budgets"]["budget_tavily_calls"] == 12
    assert body["denylist"] == sorted(body["denylist"]) and body["denylist"]


def test_manufacturers_paginate(client, repo):
    _, (iid,) = seed(repo, mk_item("Syringe"))
    run = repo.create_run(iid, {}, {})
    ids = []
    for i in range(5):
        m = repo.upsert_manufacturer(f"M{i}", f"m{i}", None, None, None)
        repo.add_listing(m, run, {"url": f"https://m/{i}", "platform": "indiamart"})
        ids.append(m)
    p1 = [m["id"] for m in client.get("/api/manufacturers?limit=2&offset=0").json()]
    p2 = [m["id"] for m in client.get("/api/manufacturers?limit=2&offset=2").json()]
    p3 = [m["id"] for m in client.get("/api/manufacturers?limit=2&offset=4").json()]
    assert len(p1) == 2 and len(p2) == 2 and len(p3) == 1 and sorted(p1 + p2 + p3) == sorted(ids)
    assert len(client.get("/api/manufacturers").json()) == 5
    assert client.get("/api/manufacturers?limit=201").status_code == 422


def test_item_runs_and_run_by_id(client, repo):
    _, (iid,) = seed(repo, mk_item("Syringe"))
    r1 = repo.create_run(iid, {}, {})
    repo.set_run(r1, status="done", result={"spec_title": "x"})
    r2 = repo.create_run(iid, {}, {})
    rows = client.get(f"/api/items/{iid}/runs").json()
    assert [r["id"] for r in rows] == [r2, r1]
    assert set(rows[0]) == {"id", "status", "started_at", "finished_at"}
    full = client.get(f"/api/runs/{r1}").json()
    assert full["id"] == r1 and full["result"] == {"spec_title": "x"} and "split" in full
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/items/nope/runs").status_code == 404


def test_history_item_count_is_in_scope_items(client, repo):
    repo.create_research("x", None, "T", [mk_item("A"), {**mk_item("B"), "analysis": {"in_scope": False}}])
    assert client.get("/api/research").json()[0]["item_count"] == 1


def test_manufacturer_count(client, repo):
    a, _ = seed_directory(repo)
    assert client.get("/api/manufacturers/count").json() == {"total": 2, "starred": 0}
    client.patch(f"/api/manufacturers/{a}", json={"starred": True})
    assert client.get("/api/manufacturers/count").json() == {"total": 2, "starred": 1}


def test_manufacturer_confirmed_when_any_listing_is_manufacturer(client, repo):
    # I4: the directory tags a maker "Unconfirmed" unless one of its listings was classified manufacturer
    _, (iid,) = seed(repo, mk_item("Syringe"))
    run = repo.create_run(iid, {}, {})
    a = repo.upsert_manufacturer("Acme", "acme", None, None, None)
    b = repo.upsert_manufacturer("Zed", "zed", None, None, None)
    repo.add_listing(a, run, {"url": "https://a/1", "classification": "unconfirmed"})
    repo.add_listing(a, run, {"url": "https://a/2", "classification": "manufacturer"})
    repo.add_listing(b, run, {"url": "https://b/1", "classification": "unconfirmed"})
    rows = {r["id"]: r for r in client.get("/api/manufacturers").json()}
    assert rows[a]["confirmed"] is True and rows[b]["confirmed"] is False
    assert client.patch(f"/api/manufacturers/{b}", json={"starred": True}).json()["confirmed"] is False
