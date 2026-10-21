"""Application settings (Pydantic BaseSettings)."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # TimescaleDB
    timescale_dsn: str = "postgresql://stockgraph:stockgraph@localhost:5432/stockgraph"

    # FalkorDB (unified graph + vector store — Rule 1: no other graph/vector DB)
    falkor_host: str = "localhost"
    falkor_port: int = 6379
    falkor_graph_name: str = "stock_graph"
    embedding_dimension: int = 1536

    # Redis (L1 dedup cache, scheduler locks)
    redis_url: str = "redis://localhost:6380/0"

    app_timezone: str = "Asia/Kolkata"

    # Rule 5 tunables: multi-layered news dedup thresholds (never hardcoded).
    dedup_cosine_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    dedup_window_hours: int = Field(default=48, ge=1)
    # L3 vector candidate fan-out: FalkorDB returns top-K globally, then we
    # post-filter by ticker/window in Cypher and re-score cosine in Python.
    # K=5 missed in-ticker dups when global neighbours belonged to other
    # tickers; K=50 bounds recall loss while keeping the 48h window cheap.
    dedup_vector_k: int = Field(default=50, ge=1, le=200)

    # Rule 5 L4 cross-news correlation tunables (never hardcoded).
    correlation_min_cosine: float = Field(default=0.68, ge=0.0, le=1.0)
    correlation_window_days: int = Field(default=14, ge=1)

    # Rule 4 tunable: minimum confidence for persisting/traversing dynamic
    # ontology edges (DynamicOntologyBuilder) and news impact edges.
    ontology_min_confidence: float = Field(default=0.65, ge=0.0, le=1.0)

    # Rule 7 tunable: trailing trading-day window re-fetched by the vendor
    # revision sweep. The backfill watermark only moves forward, so revisions
    # of already-synced dates are caught here and staged as new vintages.
    vendor_revision_lookback_days: int = Field(default=10, ge=1)

    # Issue 1 mitigation: LLM/embedding layer tunables (kill-switch + budget).
    # `llm_enabled=false` keeps CI fully offline; providers raise when called.
    llm_enabled: bool = False
    llm_chat_model: str = "gpt-4o-mini"
    llm_ontology_model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"
    llm_max_tokens_per_call: int = Field(default=4000, ge=256)
    llm_monthly_usd_cap: float = Field(default=50.0, ge=0.0)
    llm_cache_ttl_days: int = Field(default=30, ge=1)

    # Issue 2 mitigation: NSE sourcing tunables (Bhavcopy-primary + throttle).
    bhavcopy_primary: bool = True
    nse_requests_per_second: float = Field(default=1.0, ge=0.1, le=10.0)
    nse_timeout_seconds: int = Field(default=30, ge=5, le=300)
    # Retry/backoff + UA rotation for Akamai-gated NSE endpoints.
    nse_max_retries: int = Field(default=3, ge=0, le=10)
    nse_backoff_base_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    # Per-1k-token USD prices for budget pre-flight estimates.
    embedding_price_per_1k: float = Field(default=0.00002, ge=0.0)
    chat_price_per_1k: float = Field(default=0.00015, ge=0.0)


settings = Settings()
