"""Data-service settings; graph credentials deliberately do not exist here."""

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)
    timescale_dsn: str = "postgresql://stockgraph:stockgraph@localhost:5432/stockgraph"
    redis_url: str = "redis://localhost:6380/0"
    event_stream: str = "stockgraph:events:v1"
    app_timezone: str = "Asia/Kolkata"
    upstox_analytics_token: SecretStr = SecretStr("")
    upstox_api_base_url: str = "https://api.upstox.com/v2"
    upstox_timeout_seconds: float = 30
    upstox_max_retries: int = Field(default=3, ge=0, le=6)
    job_max_attempts: int = Field(default=3, ge=1)
    job_lease_seconds: int = Field(default=600, ge=60)
    marketaux_api_key: str = Field(default="", repr=False)
    currents_api_key: str = Field(
        default="",
        repr=False,
        validation_alias=AliasChoices("CURRENTS_API_KEY", "CURRENT_NEWS_API_KEY"),
    )
    fmp_api_key: str = Field(default="", repr=False)
    alpha_vantage_api_key: str = Field(default="", repr=False)
    news_providers_enabled: str = "marketaux,currents,alphavantage,fmp"
    news_requests_per_run: int = 2
    news_daily_request_cap: int | None = None
    news_lookback_minutes: int = 720
    news_max_window_minutes: int = 1440
    news_max_articles_per_run: int = 60
    news_summary_max_chars: int = 600
    news_currents_country: str = "in"
    news_currents_categories: str = "finance,economy,politics"
    news_currents_include_broad: bool = True
    news_eligibility_url: str = "http://localhost:8000/internal/v1/news/eligibility"
    news_eligibility_timeout_seconds: float = Field(default=8, gt=0, le=60)
    news_symbol_suffix: str = ".NS"
    news_alpha_vantage_symbol_suffix: str = ".BSE"
    nse_requests_per_second: float = 1
    nse_timeout_seconds: int = 30
    nse_max_retries: int = 3
    nse_backoff_base_seconds: float = 1
    vendor_revision_lookback_days: int = 10


settings = Settings()
