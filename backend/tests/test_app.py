from app.config import Settings


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_ready_reports_db(client):
    assert client.get("/api/ready").status_code == 200


def test_env_file_beats_os_variable(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("APP_NAME=FromDotenv\n")
    monkeypatch.setenv("APP_NAME", "eScan Antivirus")
    assert Settings(_env_file=tmp_path / ".env").app_name == "FromDotenv"


def test_sqlite_uses_wal(db):
    with db.engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


def test_unknown_route_uses_error_shape(client):
    body = client.get("/api/nope").json()
    assert body["error"]["code"] == "not_found"


def test_ready_503_when_tables_missing(settings):
    from fastapi.testclient import TestClient

    from app.db import Database
    from app.main import create_app

    with TestClient(create_app(settings, db=Database(settings.database_url))) as c:  # no create_all
        r = c.get("/api/ready")
    assert r.status_code == 503 and r.json()["error"]["code"] == "not_ready"
