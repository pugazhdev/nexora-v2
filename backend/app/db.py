"""SQLAlchemy engine and sessions. SQLite runs in WAL mode so reads do not block the writer."""

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str):
        parsed = make_url(url)
        sqlite = parsed.get_backend_name() == "sqlite"
        if sqlite and parsed.database and parsed.database != ":memory:":
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(url, future=True)
        if sqlite:

            @event.listens_for(self.engine, "connect")
            def _pragmas(conn, _):
                cur = conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.close()

        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self):
        with self._sessions() as s:
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise

    def create_all(self) -> None:
        from app import models  # noqa: F401  (registers tables on Base.metadata)

        Base.metadata.create_all(self.engine)

    def ping(self) -> bool:
        """True if the DB answers and every model table exists."""
        from app import models  # noqa: F401  (registers tables on Base.metadata)

        try:
            with self.engine.connect() as c:
                c.execute(text("SELECT 1"))
            return set(Base.metadata.tables) <= set(inspect(self.engine).get_table_names())
        except Exception:
            return False
