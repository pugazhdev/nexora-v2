"""DELETE /api/research/{id}."""
from sqlalchemy import func, select

from app.models import ItemRun, Listing, Research, ResearchItem, RunEvent
from tests.test_runs import mk_item, seed


def count(db, model):
    with db.session() as s:
        return s.scalar(select(func.count()).select_from(model))


def test_delete_removes_children_and_image(client, repo, db, settings, tmp_path):
    rid, (iid,) = seed(repo)
    other, _ = seed(repo)
    img = tmp_path / "uploads" / "img.png"
    img.parent.mkdir()
    img.write_bytes(b"x")
    repo.set_image_path(rid, img.as_posix())
    run = repo.create_run(iid, {}, {})
    repo.set_run(run, status="done")
    repo.add_event(run, "p", "m")
    m = repo.upsert_manufacturer("Acme", "acme", "Pune", "MH", None)
    repo.add_listing(m, run, {"url": "https://a/1", "platform": "indiamart"})
    assert client.delete(f"/api/research/{rid}").status_code == 204
    assert not img.exists()
    assert count(db, Research) == 1 and count(db, ResearchItem) == 1
    assert count(db, ItemRun) == 0 and count(db, RunEvent) == 0 and count(db, Listing) == 0
    assert client.get(f"/api/research/{other}").status_code == 200
    assert client.get(f"/api/research/{rid}").status_code == 404


def test_delete_missing_image_file_is_ignored(client, repo):
    rid, _ = seed(repo)
    repo.set_image_path(rid, "nope/missing.png")
    assert client.delete(f"/api/research/{rid}").status_code == 204


def test_delete_unknown_is_404(client):
    assert client.delete("/api/research/nope").status_code == 404


def test_delete_blocked_while_researching(client, repo, db):
    rid, (iid,) = seed(repo)
    run = repo.create_run(iid, {}, {})
    repo.set_run(run, status="researching")
    r = client.delete(f"/api/research/{rid}")
    assert r.status_code == 409
    assert r.json()["error"] == {"code": "conflict", "message": "Cancel the research before deleting it.", "details": {}}
    assert count(db, Research) == 1


def test_delete_blocked_while_splitting(client, repo):
    rid, (iid,) = seed(repo)
    run = repo.create_run(iid, {}, {})
    repo.set_run(run, status="done")
    repo.set_split(run, status="running")
    assert client.delete(f"/api/research/{rid}").status_code == 409


def test_delete_keeps_manufacturer_and_drops_listing_count(client, repo):
    rid, (iid,) = seed(repo, mk_item("Syringe"))
    other, (iid2,) = seed(repo)
    m = repo.upsert_manufacturer("Acme", "acme", "Pune", "MH", None)
    for item, url in ((iid, "https://a/1"), (iid2, "https://a/2")):
        run = repo.create_run(item, {}, {})
        repo.set_run(run, status="done")
        repo.add_listing(m, run, {"url": url, "platform": "indiamart"})
    assert client.get("/api/manufacturers").json()[0]["listing_count"] == 2
    assert client.delete(f"/api/research/{rid}").status_code == 204
    rows = client.get("/api/manufacturers").json()
    assert len(rows) == 1 and rows[0]["listing_count"] == 1


def test_delete_keeps_files_outside_uploads(client, repo, tmp_path):
    rid, _ = seed(repo)
    outside = tmp_path / "keep.png"
    outside.write_bytes(b"x")
    repo.set_image_path(rid, outside.as_posix())
    assert client.delete(f"/api/research/{rid}").status_code == 204
    assert outside.exists()


def test_delete_blocked_while_worker_alive(client, repo):
    rid, _ = seed(repo)
    client.app.state.run_service.tasks[rid] = object()
    try:
        assert client.delete(f"/api/research/{rid}").status_code == 409
    finally:
        del client.app.state.run_service.tasks[rid]
    assert client.delete(f"/api/research/{rid}").status_code == 204
