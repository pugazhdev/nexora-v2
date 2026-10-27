import io
import re
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.intake.schemas import IntakeAnalysisDraft
from app.main import create_app
from tests.fakes import FakeLLM
from tests.test_intake_graph import draft, item, q

Z = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z$")


def make_client(settings, db, *outs, llm=None):
    llm = llm or FakeLLM({IntakeAnalysisDraft: list(outs)})
    return TestClient(create_app(settings, db=db, llm=llm)), llm


def analyse(c, text="2 mL syringe"):
    r = c.post("/api/research", data={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_analyse_text_creates_research(settings, db):
    c, _ = make_client(settings, db, draft(item("Syringe", questions=[q("size")]), item("Aspirin", "medicine")))
    body = analyse(c)
    assert body["title"] == "Syringe"
    assert body["status"] == "draft" and body["message"] is None
    syr, med = body["items"]
    assert syr["in_scope"] and syr["selected"] and syr["latest_run"] is None
    assert [x["key"] for x in syr["questions"]] == ["quantity", "size"]
    assert syr["answer_errors"]["quantity"] and "size" in syr["answer_errors"]
    assert not med["in_scope"] and not med["selected"] and med["scope_reason"]
    for k in ("id", "position", "name", "category", "known_attributes", "answers", "splittable", "parts",
              "image_region_hint"):
        assert k in syr
    assert c.get(f"/api/research/{body['id']}").json()["items"][0]["name"] == "Syringe"


def test_title_capped_at_60_chars(settings, db):
    c, _ = make_client(settings, db, draft(item("A" * 50), item("B" * 50)))
    assert len(analyse(c)["title"]) <= 60


def test_analyse_with_image_saves_upload(settings, db, tmp_path):
    c, _ = make_client(settings, db, draft(item()))
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(buf, format="PNG")
    r = c.post("/api/research", files={"image": ("a.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    saved = tmp_path / "uploads" / f"{r.json()['id']}.png"
    assert saved.read_bytes() == buf.getvalue()
    stored = c.get(f"/api/research/{r.json()['id']}").json()["image_path"]
    assert stored.endswith(f"{r.json()['id']}.png") and Path(stored).exists()


def test_bad_image_not_saved(settings, db, tmp_path):
    c, _ = make_client(settings, db)
    r = c.post("/api/research", files={"image": ("a.png", b"not an image", "image/png")})
    assert r.status_code >= 400
    assert not (tmp_path / "uploads").exists() or not list((tmp_path / "uploads").iterdir())


def test_analyse_without_input_400(settings, db):
    c, _ = make_client(settings, db)
    r = c.post("/api/research", data={"text": "  "})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


def test_analyse_without_key_503(settings, db):
    llm = FakeLLM({})
    llm.is_configured = lambda: False
    c, _ = make_client(settings, db, llm=llm)
    r = c.post("/api/research", data={"text": "syringe"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "config_missing"
    assert r.json()["error"]["message"] == "Set OPENAI_API_KEY, OPENAI_MODEL and OPENAI_VISION_MODEL in backend/.env"


def test_analyse_rate_limited(db, tmp_path):
    s = Settings(_env_file=None, database_url="sqlite://",
                 uploads_dir=str(tmp_path), analyse_rate_limit_per_minute=1)
    c, _ = make_client(s, db, draft(item()), draft(item()))
    assert c.post("/api/research", data={"text": "a"}).status_code == 200
    assert c.post("/api/research", data={"text": "a"}).status_code == 429


def test_get_unknown_404(client):
    assert client.get("/api/research/nope").status_code == 404


def test_patch_answers_returns_errors(settings, db):
    c, _ = make_client(settings, db, draft(item("Syringe", questions=[q("size")])))
    body = analyse(c)
    it = body["items"][0]
    r = c.patch(f"/api/research/{body['id']}/items/{it['id']}", json={"answers": {"quantity": 5, "size": "9"}})
    assert r.status_code == 200
    out = r.json()
    assert out["answers"] == {"quantity": 5, "size": "9"}
    assert out["answer_errors"] == {"size": "pick one of the listed options"}
    r = c.patch(f"/api/research/{body['id']}/items/{it['id']}", json={"answers": {"quantity": 5, "size": "0"}})
    assert r.json()["answer_errors"] == {}
    r = c.patch(f"/api/research/{body['id']}/items/{it['id']}", json={"selected": False})
    assert r.json()["selected"] is False


def test_patch_unknown_item_404(settings, db):
    c, _ = make_client(settings, db, draft(item()))
    body = analyse(c)
    assert c.patch(f"/api/research/{body['id']}/items/nope", json={"selected": False}).status_code == 404


def test_cannot_select_out_of_scope_item(settings, db):
    c, _ = make_client(settings, db, draft(item("Aspirin", "medicine"), item("Syringe")))
    body = analyse(c)
    med = body["items"][0]
    r = c.patch(f"/api/research/{body['id']}/items/{med['id']}", json={"selected": True})
    assert r.status_code == 409
    assert c.patch(f"/api/research/{body['id']}/items/{med['id']}", json={"selected": False}).status_code == 200


def test_history_lists_newest_first(settings, db):
    c, _ = make_client(settings, db, draft(item("First")), draft(item("Second")))
    analyse(c)
    analyse(c)
    rows = c.get("/api/research?limit=10&offset=0").json()
    assert [r["title"] for r in rows] == ["Second", "First"]
    assert Z.match(rows[0]["created_at"])
    assert len(c.get("/api/research?limit=1&offset=1").json()) == 1


def test_timestamps_are_utc_z(settings, db, repo):
    from app.models import ResearchItem  # noqa: F401

    c, _ = make_client(settings, db, draft(item()))
    body = analyse(c)
    assert Z.match(body["created_at"])
    iid = body["items"][0]["id"]
    run_id = repo.create_run(iid, {}, {})
    repo.set_run(run_id, status="done", result={})
    latest = c.get(f"/api/research/{body['id']}").json()["items"][0]["latest_run"]
    for k in ("created_at", "finished_at"):
        assert Z.match(latest[k]), latest


def test_patch_after_done_run_leaves_run_untouched(settings, db, repo):
    c, _ = make_client(settings, db, draft(item("Syringe", questions=[q("size")])))
    body = analyse(c)
    iid = body["items"][0]["id"]
    run_id = repo.create_run(iid, {"quantity": 1}, {"name": "Syringe"})
    repo.set_run(run_id, status="done", result={"ok": True})
    before = repo.runs_for_item(iid)
    r = c.patch(f"/api/research/{body['id']}/items/{iid}", json={"answers": {"quantity": 9, "size": "0"}})
    assert r.status_code == 200
    assert r.json()["latest_run"]["status"] == "done"
    assert repo.runs_for_item(iid) == before
