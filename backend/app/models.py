"""ORM tables (spec section 7). IDs are uuid4().hex strings; run_event.id is an integer used as the SSE cursor."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def new_id() -> str:
    return uuid4().hex


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Research(Base):
    __tablename__ = "research"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    input_text: Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class ResearchItem(Base):
    __tablename__ = "research_item"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    research_id: Mapped[str] = mapped_column(ForeignKey("research.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    selected: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class ItemRun(Base):
    __tablename__ = "item_run"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    item_id: Mapped[str] = mapped_column(ForeignKey("research_item.id", ondelete="CASCADE"), index=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    split_status: Mapped[str | None] = mapped_column(String(20))
    split: Mapped[dict | None] = mapped_column(JSON)
    split_error: Mapped[str | None] = mapped_column(Text)
    retail: Mapped[dict | None] = mapped_column(JSON)  # RetailResult, kept apart from result
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class RunEvent(Base):
    __tablename__ = "run_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("item_run.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=now)
    phase: Mapped[str] = mapped_column(String(40))
    level: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(Text)


class PageCache(Base):
    __tablename__ = "page_cache"
    canonical_url: Mapped[str] = mapped_column(String(2000), primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    status: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    via: Mapped[str] = mapped_column(String(30))


class Manufacturer(Base):
    __tablename__ = "manufacturer"
    __table_args__ = (UniqueConstraint("normalised_name", "city", name="uq_manufacturer_name_city"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    normalised_name: Mapped[str] = mapped_column(String(300), index=True)
    display_name: Mapped[str] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(500))
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=now)
    starred: Mapped[bool] = mapped_column(Boolean, default=False)


class Listing(Base):
    __tablename__ = "listing"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    manufacturer_id: Mapped[str] = mapped_column(ForeignKey("manufacturer.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("research_item.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("item_run.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2000))
    platform: Mapped[str | None] = mapped_column(String(60))
    unit_price: Mapped[float | None] = mapped_column(Float)
    tiers: Mapped[list] = mapped_column(JSON, default=list)
    moq: Mapped[int | None] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    classification: Mapped[str | None] = mapped_column(String(40))
    spec_match: Mapped[str | None] = mapped_column(String(40))
