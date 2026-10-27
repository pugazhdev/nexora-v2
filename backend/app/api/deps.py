"""Shared FastAPI dependencies."""

import time
from collections import defaultdict, deque

from fastapi import Request

from app.config import Settings
from app.db import Database
from app.errors import RateLimitedError
from app.repo import Repository


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


class RateLimiter:
    """Sliding one-minute window per client IP, in memory."""

    # ponytail: per-process memory; use a shared store if running several workers
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)

    def __call__(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        q, t = self.hits[key], time.monotonic()
        while q and t - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            raise RateLimitedError("Too many requests. Wait a minute and try again.")
        q.append(t)


def analyse_limit(request: Request) -> None:
    request.app.state.analyse_limiter(request)


def get_llm(request: Request):
    return request.app.state.llm


def get_repo(request: Request) -> Repository:
    return Repository(request.app.state.db)


def get_runs(request: Request):
    return request.app.state.run_service
