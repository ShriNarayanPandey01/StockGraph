"""Platform accounts, service credentials and operating configuration."""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLATFORM_", env_file=".env", extra="ignore", populate_by_name=True)
    database_dsn: SecretStr = SecretStr("postgresql://marketgraph_platform:local-platform-change-me@localhost:5432/marketgraph_platform")
    redis_url: SecretStr = SecretStr("redis://localhost:6380/0")
    data_service_url: str = "http://localhost:8001"
    graph_service_url: str = "http://localhost:8000"
    professional_weight: float = Field(default=1.5, gt=1, le=3)
    ordinary_weight: float = Field(default=1.0, gt=0, le=1)
    http_timeout_seconds: float = Field(default=15, gt=0, le=120)
    db_pool_size: int = Field(default=10, ge=1, le=100)
    outbox_stream: str = "stockgraph:platform-events:v1"
    outbox_lease_seconds: int = Field(default=60, ge=10, le=600)
    outbox_batch_size: int = Field(default=50, ge=1, le=500)
    operational_requests_per_minute: int = Field(default=120, ge=1)
    agent_work_lease_seconds: int = Field(default=120, ge=10)
    agent_work_max_attempts: int = Field(default=5, ge=1)
    agent_service_key: SecretStr = SecretStr("")
    operational_max_pending_jobs_per_user: int = Field(default=20, ge=1)
    agent_lease_seconds: int = Field(default=300, ge=10)
    max_agent_attempts: int = Field(default=3, ge=1)
    monitor_batch_size: int = Field(default=100, ge=1, le=1000)
    monitor_min_interval_seconds: int = Field(default=60, ge=60)
    internal_service_key: SecretStr = Field(default=SecretStr(""), validation_alias="MARKETGRAPH_INTERNAL_SERVICE_KEY")
    broker_encryption_key: SecretStr = SecretStr("")
    document_internal_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="DOCUMENT_INTERNAL_API_KEY")
    admin_name: str = Field(default="Developer", min_length=1, max_length=200)
    admin_email: str = ""
    admin_password: SecretStr = SecretStr("")
    session_ttl_seconds: int = Field(default=43200, ge=300, le=604800)
    auth_code_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    auth_code_max_attempts: int = Field(default=5, ge=1, le=10)
    auth_resend_seconds: int = Field(default=60, ge=30, le=3600)
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_timeout_seconds: float = Field(default=10, gt=0, le=60)

    @field_validator("admin_email", "smtp_from")
    @classmethod
    def account_email(cls, value: str) -> str:
        import re
        value = value.strip().casefold()
        if value and (len(value) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value)):
            raise ValueError("A valid email address is required")
        return value

    @field_validator("data_service_url", "graph_service_url")
    @classmethod
    def service_url(cls, value: str) -> str:
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("service URL must be HTTP(S) without credentials")
        return value.rstrip("/")
