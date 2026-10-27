"""All persistence goes through Repository. Methods return plain dicts."""

from datetime import timedelta

from sqlalchemy import case, delete, desc, func, literal_column, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.db import Database
from app.errors import ConflictError, NotFoundError
from app.models import (
    ItemRun,
    Listing,
    Manufacturer,
    PageCache,
    Research,
    ResearchItem,
    RunEvent,
    now,
)

TERMINAL = {"done", "failed", "cancelled", "interrupted"}
ACTIVE = {"queued", "researching"}


def _iso(v) -> str:
    """Stored datetimes are naive UTC; emit them with a Z so browsers do not read them as local time."""
    return v.isoformat() + "Z"


def _d(row) -> dict:
    out = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    return {k: (_iso(v) if hasattr(v, "isoformat") else v) for k, v in out.items()}


# ponytail: rowid tiebreak is SQLite specific; swap for a sequence column if another DB is used
def _newest_first(model):
    return (desc(model.created_at), desc(literal_column(f"{model.__tablename__}.rowid")))


def _status(items: list[dict]) -> str:
    runs = [i["latest_run"] for i in items]
    if any(r and r["status"] in ACTIVE for r in runs):
        return "researching"
    sel = [i["latest_run"] for i in items if i["selected"]]
    if sel and all(r and r["status"] in TERMINAL for r in sel):
        return "done"
    return "draft"


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # research
    def create_research(self, input_text, image_path, title, items) -> str:
        with self.db.session() as s:
            r = Research(input_text=input_text, image_path=image_path, title=title)
            s.add(r)
            s.flush()
            for pos, it in enumerate(items):
                s.add(
                    ResearchItem(
                        research_id=r.id,
                        name=it["name"],
                        analysis=it.get("analysis", {}),
                        questions=it.get("questions", []),
                        answers=it.get("answers", {}),
                        selected=it.get("selected", True),
                        position=pos,
                    )
                )
            return r.id

    def set_image_path(self, research_id: str, path: str) -> None:
        with self.db.session() as s:
            r = s.get(Research, research_id)
            if not r:
                raise NotFoundError("Research not found.")
            r.image_path = path

    def _items(self, s, research_id: str) -> list[dict]:
        out = []
        for it in s.scalars(
            select(ResearchItem).where(ResearchItem.research_id == research_id).order_by(ResearchItem.position)
        ):
            run = s.scalars(
                select(ItemRun).where(ItemRun.item_id == it.id).order_by(*_newest_first(ItemRun)).limit(1)
            ).first()
            out.append({**_d(it), "latest_run": _d(run) if run else None})
        return out

    def get_research(self, research_id: str) -> dict:
        with self.db.session() as s:
            r = s.get(Research, research_id)
            if not r:
                raise NotFoundError("Research not found.")
            items = self._items(s, research_id)
            return {**_d(r), "status": _status(items), "items": items}

    def _summary(self, s, research_id: str) -> dict:
        items = self._items(s, research_id)
        n = sum(1 for i in items if i["analysis"].get("in_scope", True))
        return {"status": _status(items), "item_count": n}

    def list_research(self, limit: int, offset: int) -> list[dict]:
        with self.db.session() as s:
            rows = s.scalars(
                select(Research).order_by(*_newest_first(Research)).limit(limit).offset(offset)
            ).all()
            return [
                {
                    "id": r.id,
                    "title": r.title,
                    "created_at": _iso(r.created_at),
                    **self._summary(s, r.id),
                }
                for r in rows
            ]

    def delete_research(self, research_id: str) -> str | None:
        """Delete a research and all its rows (SQLite FKs are off, so cascade by hand). Returns image_path."""
        with self.db.session() as s:
            r = s.get(Research, research_id)
            if not r:
                raise NotFoundError("Research not found.")
            items = self._items(s, research_id)
            if any(i["latest_run"] and (i["latest_run"]["status"] in ACTIVE
                                        or i["latest_run"]["split_status"] == "running") for i in items):
                raise ConflictError("Cancel the research before deleting it.")
            item_ids = [i["id"] for i in items]
            run_ids = select(ItemRun.id).where(ItemRun.item_id.in_(item_ids))
            s.execute(delete(Listing).where(Listing.run_id.in_(run_ids)))
            s.execute(delete(RunEvent).where(RunEvent.run_id.in_(run_ids)))
            s.execute(delete(ItemRun).where(ItemRun.item_id.in_(item_ids)))
            s.execute(delete(ResearchItem).where(ResearchItem.research_id == research_id))
            path = r.image_path
            s.delete(r)
            return path

    def update_item(self, item_id: str, *, selected=None, answers=None) -> dict:
        with self.db.session() as s:
            it = s.get(ResearchItem, item_id)
            if not it:
                raise NotFoundError("Item not found.")
            if selected is not None:
                it.selected = selected
            if answers is not None:
                it.answers = answers
            return _d(it)

    # runs
    def create_run(self, item_id: str, answers: dict, spec: dict) -> str:
        with self.db.session() as s:
            if not s.get(ResearchItem, item_id):
                raise NotFoundError("Item not found.")
            run = ItemRun(item_id=item_id, answers=answers, spec=spec, status="queued")
            s.add(run)
            s.flush()
            return run.id

    def _run(self, s, run_id: str) -> ItemRun:
        run = s.get(ItemRun, run_id)
        if not run:
            raise NotFoundError("Run not found.")
        return run

    def set_run(self, run_id: str, *, status: str, result=None, error=None) -> bool:
        """Returns False (and changes nothing) once the run is terminal, so a late "done" cannot undo "cancelled"."""
        with self.db.session() as s:
            run = self._run(s, run_id)
            if run.status in TERMINAL:
                return False
            run.status = status
            if result is not None:
                run.result = result
            if error is not None:
                run.error = error
            if status == "researching":
                run.started_at = now()
            elif status in TERMINAL:
                run.finished_at = now()
            return True

    def set_split(self, run_id: str, *, status: str, split=None, error=None) -> None:
        with self.db.session() as s:
            run = self._run(s, run_id)
            run.split_status = status
            if split is not None:
                run.split = split
            if error is not None:
                run.split_error = error

    def get_item(self, item_id: str) -> dict:
        with self.db.session() as s:
            it = s.get(ResearchItem, item_id)
            if not it:
                raise NotFoundError("Item not found.")
            return _d(it)

    def get_run(self, run_id: str) -> dict:
        with self.db.session() as s:
            return _d(self._run(s, run_id))

    def runs_for_item(self, item_id: str) -> list[dict]:
        with self.db.session() as s:
            rows = s.scalars(select(ItemRun).where(ItemRun.item_id == item_id).order_by(*_newest_first(ItemRun)))
            return [_d(r) for r in rows]

    def mark_interrupted(self) -> int:
        with self.db.session() as s:
            n = s.execute(
                update(ItemRun).where(ItemRun.status.in_(ACTIVE)).values(status="interrupted", finished_at=now())
            ).rowcount
            s.execute(update(ItemRun).where(ItemRun.split_status == "running").values(split_status="interrupted"))
            return n

    # events
    def add_event(self, run_id: str, phase: str, message: str, level: str = "info") -> int:
        with self.db.session() as s:
            e = RunEvent(run_id=run_id, phase=phase, message=message, level=level)
            s.add(e)
            s.flush()
            return e.id

    def events_after(self, research_id: str, after_id: int) -> list[dict]:
        with self.db.session() as s:
            rows = s.execute(
                select(RunEvent, ItemRun.item_id)
                .join(ItemRun, RunEvent.run_id == ItemRun.id)
                .join(ResearchItem, ItemRun.item_id == ResearchItem.id)
                .where(ResearchItem.research_id == research_id, RunEvent.id > after_id)
                .order_by(RunEvent.id)
            ).all()
            return [{**_d(e), "item_id": item_id} for e, item_id in rows]

    # page cache
    def cache_get(self, url: str, max_age_hours: float) -> dict | None:
        with self.db.session() as s:
            row = s.get(PageCache, url)
            if row and row.fetched_at > now() - timedelta(hours=max_age_hours):
                return _d(row)
            return None

    def cache_put(self, url: str, text: str, via: str, status: int) -> None:
        with self.db.session() as s:
            s.merge(PageCache(canonical_url=url, text=text, via=via, status=status, fetched_at=now()))

    # manufacturers and listings
    def upsert_manufacturer(self, display_name, normalised_name, city, state, website) -> str:
        try:
            return self._upsert_manufacturer(display_name, normalised_name, city, state, website)
        except IntegrityError:  # a concurrent insert won the race: the row exists now, so update it
            return self._upsert_manufacturer(display_name, normalised_name, city, state, website)

    def _upsert_manufacturer(self, display_name, normalised_name, city, state, website) -> str:
        with self.db.session() as s:
            m = s.scalars(
                select(Manufacturer).where(Manufacturer.normalised_name == normalised_name, Manufacturer.city == city)
            ).first()
            if m:
                m.last_seen = now()
                m.state = m.state or state
                m.website = m.website or website
            else:
                m = Manufacturer(
                    display_name=display_name, normalised_name=normalised_name, city=city, state=state, website=website
                )
                s.add(m)
                s.flush()
            return m.id

    def add_listing(self, manufacturer_id: str, run_id: str, offer: dict) -> None:
        with self.db.session() as s:
            run = self._run(s, run_id)
            s.add(
                Listing(
                    manufacturer_id=manufacturer_id,
                    item_id=run.item_id,
                    run_id=run_id,
                    url=offer["url"],
                    platform=offer.get("platform"),
                    unit_price=offer.get("unit_price"),
                    tiers=offer.get("tiers", []),
                    moq=offer.get("moq"),
                    classification=offer.get("classification"),
                    spec_match=offer.get("spec_match"),
                )
            )

    # ponytail: group_concat is SQLite/MySQL specific; use array_agg on Postgres
    def list_manufacturers(
        self, starred: bool | None = None, q: str | None = None, limit: int | None = None, offset: int = 0
    ) -> list[dict]:
        """One aggregate query: manufacturer columns plus platforms (sorted, distinct), listing_count and
        confirmed (any listing classified manufacturer)."""
        with self.db.session() as s:
            stmt = (
                select(Manufacturer, func.count(Listing.id), func.group_concat(Listing.platform.distinct()),
                       func.max(case((Listing.classification == "manufacturer", 1), else_=0)))
                .outerjoin(Listing, Listing.manufacturer_id == Manufacturer.id)
                .group_by(Manufacturer.id)
                .order_by(desc(Manufacturer.last_seen), Manufacturer.id)
            )
            if starred is not None:
                stmt = stmt.where(Manufacturer.starred == starred)
            if q and q.strip():
                like = f"%{q.strip().lower()}%"
                stmt = stmt.where(
                    or_(func.lower(Manufacturer.display_name).like(like), func.lower(Manufacturer.city).like(like))
                )
            if limit is not None:
                stmt = stmt.limit(limit).offset(offset)
            return [
                {**_d(m), "listing_count": n, "platforms": sorted(p.split(",")) if p else [], "confirmed": bool(c)}
                for m, n, p, c in s.execute(stmt)
            ]

    def manufacturer_counts(self) -> dict:
        with self.db.session() as s:
            total = s.scalar(select(func.count(Manufacturer.id)))
            starred = s.scalar(select(func.count(Manufacturer.id)).where(Manufacturer.starred == True))  # noqa: E712
            return {"total": total, "starred": starred}

    def star_manufacturer(self, mid: str, starred: bool) -> None:
        with self.db.session() as s:
            m = s.get(Manufacturer, mid)
            if not m:
                raise NotFoundError("Manufacturer not found.")
            m.starred = starred
