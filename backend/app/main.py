import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import RateLimiter
from app.api.routes import router
from app.clients.llm import LLM
from app.clients.tavily import Tavily
from app.config import Settings, get_settings
from app.db import Database
from app.errors import install_error_handlers
from app.fetch.pages import PageFetcher
from app.fetch.url_safety import SafeFetcher
from app.repo import Repository
from app.research.budget import Budget
from app.research.deps import ResearchDeps
from app.research.graph import run_research
from app.runs.service import RunService

log = logging.getLogger("pharmasource")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if app.state.db.ping():  # tables exist (alembic upgrade head ran)
        log.info("marked %d interrupted runs", Repository(app.state.db).mark_interrupted())
    else:
        log.warning("database tables missing; run: alembic upgrade head")
    yield
    await app.state.run_service.shutdown()


def create_app(
    settings: Settings | None = None,
    *,
    db: Database | None = None,
    llm=None,
    tavily=None,
    fetcher=None,
    research_fn=None,
) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level)
    app = FastAPI(title=f"{settings.app_name} API", version="2.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db or Database(settings.database_url)
    # llm / tavily / fetcher / research_fn are injection points (tests pass fakes).
    app.state.llm = llm or LLM(
        settings.openai_api_key, settings.openai_model, settings.openai_vision_model, settings.provider_timeout_seconds
    )
    app.state.tavily = tavily or Tavily(settings.tavily_api_key, settings.provider_timeout_seconds)
    repo = Repository(app.state.db)
    app.state.fetcher = fetcher or PageFetcher(
        SafeFetcher(
            timeout=settings.page_fetch_timeout_seconds,
            max_bytes=settings.page_fetch_max_bytes,
            user_agent=settings.http_user_agent,
            respect_robots=settings.respect_robots,
        ),
        app.state.tavily,
        repo,
        settings.page_cache_hours,
    )

    def make_deps(run_id, cancel):
        return ResearchDeps(settings, app.state.llm, app.state.tavily, app.state.fetcher, repo, run_id,
                            Budget.from_settings(settings), cancel)

    app.state.run_service = RunService(settings, repo, make_deps, research_fn or run_research)
    app.state.analyse_limiter = RateLimiter(settings.analyse_rate_limit_per_minute)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(router)
    return app


def app_factory() -> FastAPI:
    return create_app()
