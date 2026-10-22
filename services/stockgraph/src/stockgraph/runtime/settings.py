"""Graph-only configuration. Deliberately has no relational database credentials."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    falkor_host: str = "localhost"
    falkor_port: int = 6379
    falkor_graph_name: str = "stock_graph"
    redis_url: str = "redis://localhost:6380/0"
    data_service_url: str = "http://localhost:8001"
    app_timezone: str = "Asia/Kolkata"
    event_stream: str = "stockgraph:events:v1"
    event_consumer_group: str = "graph-v1"
    event_retry_idle_ms: int = Field(default=60000, ge=1000)
    event_lease_seconds: int = Field(default=1800, ge=60)
    pagination_snapshot_max_age_seconds: int = Field(default=3600, ge=60, le=86400)
    embedding_dimension: int = Field(default=1536, ge=1)
    embedding_model: str = "text-embedding-3-small"
    llm_enabled: bool = False
    openai_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    llm_chat_model: str = "gpt-4o-mini"
    llm_ontology_model: str = "gpt-4o"
    llm_max_tokens_per_call: int = Field(default=4000, ge=1024)
    llm_monthly_usd_cap: float = Field(default=50, ge=0)
    llm_cache_ttl_days: int = Field(default=30, ge=1)
    embedding_price_per_1k: float = Field(default=0.00002, ge=0)
    chat_price_per_1k: float = Field(default=0.00015, ge=0)
    ontology_min_confidence: float = Field(default=0.65, ge=0, le=1)
    dedup_cosine_threshold: float = Field(default=0.92, ge=0, le=1)
    dedup_window_hours: int = Field(default=48, ge=1)
    dedup_vector_k: int = Field(default=50, ge=1, le=200)
    correlation_min_cosine: float = Field(default=0.68, ge=0, le=1)
    correlation_window_days: int = Field(default=14, ge=1)
    news_market_impact_max: int = Field(default=12, ge=1, le=100)
    news_symbol_suffix: str = ".NS"


settings = Settings()
