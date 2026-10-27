"""Dependency bundle nodes read from config["configurable"]["deps"]."""
import asyncio
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.clients.llm import LLM
from app.clients.tavily import Tavily
from app.config import Settings
from app.fetch.pages import PageFetcher
from app.repo import Repository
from app.research.budget import Budget


class Cancelled(Exception):
    pass


@dataclass
class ResearchDeps:
    settings: Settings
    llm: LLM
    tavily: Tavily
    fetcher: PageFetcher
    repo: Repository
    run_id: str
    budget: Budget
    cancel: asyncio.Event


async def emit(deps: ResearchDeps, phase: str, message: str, level: str = "info") -> None:
    await asyncio.to_thread(deps.repo.add_event, deps.run_id, phase, message[:300], level)


def guard(deps: ResearchDeps) -> None:
    if deps.cancel.is_set():
        raise Cancelled()


def deps_of(config: RunnableConfig) -> ResearchDeps:
    deps: Any = (config.get("configurable") or {}).get("deps")
    if deps is None:
        raise RuntimeError('research deps missing: pass config={"configurable": {"deps": ResearchDeps(...)}}')
    return deps
