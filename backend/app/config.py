"""Environment-driven settings. Model names and all limits are configurable, never hardcoded elsewhere."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        # .env beats OS variables: generic names like APP_NAME are often already set machine-wide.
        return init_settings, dotenv_settings, env_settings, file_secret_settings

    app_name: str = "PharmaSource"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./data/app.db"
    uploads_dir: str = "data/uploads"
    cors_origins: str = "http://localhost:5173"

    openai_api_key: str = ""
    openai_model: str = ""
    openai_vision_model: str = ""
    provider_timeout_seconds: float = 60.0

    tavily_api_key: str = ""
    tavily_max_results: int = 8
    page_fetch_timeout_seconds: float = 10.0
    page_fetch_max_bytes: int = 1_500_000
    respect_robots: bool = True
    http_user_agent: str = "PharmaSourceBot/2.0 (+factory-price-research; contact: set-in-env)"

    max_upload_mb: float = 8.0
    max_image_pixels: int = 40_000_000
    image_max_side: int = 1600
    max_text_chars: int = 5000

    max_items: int = 10
    max_candidates: int = 30
    budget_tavily_calls: int = 12
    budget_web_search_calls: int = 2
    budget_pages: int = 30
    budget_llm_calls: int = 30
    budget_cost_search_calls: int = 6
    budget_cost_pages: int = 8
    budget_cost_llm_calls: int = 8
    item_timeout_seconds: float = 180.0
    research_concurrency: int = 2
    sse_poll_seconds: float = 0.5
    sse_idle_close_seconds: float = 2.0
    sse_keepalive_seconds: float = 15.0
    broaden_retries: int = 1
    page_cache_hours: float = 24.0
    offer_max_age_days: int = 180

    overhead_pct: float = 10.0
    mass_uncertainty_pct: float = 15.0
    unusually_low_factor: float = 0.6
    outlier_factor: float = 3.0
    extra_denylist: str = ""

    rate_limit_per_minute: int = 30
    analyse_rate_limit_per_minute: int = 10

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def denylist_extra(self) -> list[str]:
        return [d.strip().lower() for d in self.extra_denylist.split(",") if d.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()
