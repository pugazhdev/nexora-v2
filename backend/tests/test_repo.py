from tests.helpers import ITEM, SPEC, seeded_item


def test_create_and_get_research(repo):
    rid = repo.create_research("2 mL syringe", None, "Syringe", [ITEM])
    r = repo.get_research(rid)
    assert r["items"][0]["name"] == "Disposable syringe" and r["items"][0]["latest_run"] is None
    assert r["status"] == "draft"
    assert [x["id"] for x in repo.list_research(10, 0)] == [rid]


def test_get_missing_raises(repo):
    import pytest

    from app.errors import NotFoundError

    with pytest.raises(NotFoundError):
        repo.get_research("nope")


def test_update_item(repo):
    item = seeded_item(repo)
    out = repo.update_item(item, selected=False, answers={"capacity": "5 mL"})
    assert out["selected"] is False and out["answers"] == {"capacity": "5 mL"}


def test_new_run_keeps_old_result(repo):
    item = seeded_item(repo)
    r1 = repo.create_run(item, {"capacity": "2 mL"}, SPEC)
    repo.set_run(r1, status="done", result={"x": 1})
    r2 = repo.create_run(item, {"capacity": "3 mL"}, SPEC)
    runs = repo.runs_for_item(item)
    assert [r["id"] for r in runs] == [r2, r1] and runs[1]["result"] == {"x": 1}
    assert runs[1]["finished_at"] is not None and runs[0]["status"] == "queued"


def test_status_derivation(repo):
    rid = repo.create_research(None, None, "T", [ITEM])
    item = repo.get_research(rid)["items"][0]["id"]
    run = repo.create_run(item, {}, SPEC)
    assert repo.get_research(rid)["status"] == "researching"
    repo.set_run(run, status="done", result={})
    assert repo.get_research(rid)["status"] == "done"
    assert repo.list_research(10, 0)[0]["status"] == "done"


def test_set_split(repo):
    item = seeded_item(repo)
    run = repo.create_run(item, {}, SPEC)
    repo.set_split(run, status="done", split={"a": 1})
    r = repo.runs_for_item(item)[0]
    assert r["split_status"] == "done" and r["split"] == {"a": 1}


def test_mark_interrupted(repo):
    item = seeded_item(repo)
    run = repo.create_run(item, {}, SPEC)
    repo.set_run(run, status="researching")
    assert repo.mark_interrupted() == 1
    assert repo.runs_for_item(item)[0]["status"] == "interrupted"


def test_mark_interrupted_split(repo):
    item = seeded_item(repo)
    run = repo.create_run(item, {}, SPEC)
    repo.set_run(run, status="done", result={})
    repo.set_split(run, status="running")
    repo.mark_interrupted()
    r = repo.runs_for_item(item)[0]
    assert r["split_status"] == "interrupted" and r["status"] == "done"


def test_events_after_cursor(repo):
    rid = repo.create_research(None, None, "T", [ITEM])
    item = repo.get_research(rid)["items"][0]["id"]
    run = repo.create_run(item, {}, SPEC)
    ids = [repo.add_event(run, "p", f"m{i}") for i in range(3)]
    ev = repo.events_after(rid, ids[0])
    assert [e["id"] for e in ev] == ids[1:] and ev[0]["message"] == "m1"


def test_cache_respects_age(repo):
    repo.cache_put("https://a.example/x", "body", "direct", 200)
    assert repo.cache_get("https://a.example/x", 0) is None
    assert repo.cache_get("https://a.example/x", 24)["text"] == "body"
    repo.cache_put("https://a.example/x", "new", "direct", 200)
    assert repo.cache_get("https://a.example/x", 24)["text"] == "new"


def test_manufacturer_upsert_is_idempotent(repo):
    a = repo.upsert_manufacturer("Acme Ltd", "acme", "Pune", "MH", None)
    b = repo.upsert_manufacturer("ACME Limited", "acme", "Pune", "MH", "https://acme.example")
    c = repo.upsert_manufacturer("Acme Ltd", "acme", "Delhi", "DL", None)
    assert a == b and a != c
    assert [m["website"] for m in repo.list_manufacturers() if m["id"] == a] == ["https://acme.example"]


def test_listing_and_star(repo):
    item = seeded_item(repo)
    run = repo.create_run(item, {}, SPEC)
    m = repo.upsert_manufacturer("Acme", "acme", None, None, None)
    repo.add_listing(m, run, {"url": "https://a.example", "platform": "indiamart", "unit_price": 2.5,
                              "tiers": [], "moq": 100, "classification": "factory", "spec_match": "exact"})
    repo.star_manufacturer(m, True)
    assert [x["id"] for x in repo.list_manufacturers(starred=True)] == [m]
    assert repo.list_manufacturers(starred=False) == []
