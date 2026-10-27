import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.repo import Repository


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        uploads_dir=str(tmp_path / "uploads"),
    )


@pytest.fixture
def db(settings):
    d = Database(settings.database_url)
    d.create_all()
    return d


@pytest.fixture
def client(settings, db):
    with TestClient(create_app(settings, db=db)) as c:
        yield c


@pytest.fixture
def repo(db):
    return Repository(db)
