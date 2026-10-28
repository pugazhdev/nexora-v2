"""Per-item research budget: call counts per kind plus a wall-clock limit."""
import time
from collections.abc import Callable
from typing import Literal

# cost_* and retail_* kinds are their own budgets, so they never consume the offer branch's (R31)
Kind = Literal["tavily", "web", "pages", "llm", "cost_search", "cost_pages", "cost_llm",
               "retail_search", "retail_pages", "retail_llm"]


class Budget:
    def __init__(self, limits: dict[str, int], seconds: float, clock: Callable[[], float] = time.monotonic):
        self.limits, self.seconds, self._clock = dict(limits), seconds, clock
        self.used = {k: 0 for k in limits}
        self.exhausted: set[str] = set()
        self._start = clock()

    @classmethod
    def from_settings(cls, s, clock: Callable[[], float] = time.monotonic) -> "Budget":
        limits = {"tavily": s.budget_tavily_calls, "web": s.budget_web_search_calls,
                  "pages": s.budget_pages, "llm": s.budget_llm_calls,
                  "cost_search": s.budget_cost_search_calls, "cost_pages": s.budget_cost_pages,
                  "cost_llm": s.budget_cost_llm_calls,
                  "retail_search": s.budget_retail_search_calls, "retail_pages": s.budget_retail_pages,
                  "retail_llm": s.budget_retail_llm_calls}
        return cls(limits, s.item_timeout_seconds, clock)

    def take(self, kind: Kind, n: int = 1) -> bool:
        if kind not in self.limits:
            raise ValueError(f"unknown budget kind: {kind}")
        if self.used[kind] + n > self.limits[kind]:
            self.exhausted.add(kind)
            return False
        self.used[kind] += n
        return True

    def expired(self) -> bool:
        return self._clock() - self._start >= self.seconds
