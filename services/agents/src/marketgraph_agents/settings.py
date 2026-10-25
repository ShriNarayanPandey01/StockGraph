"""Future Platform connection settings; health checks need no credentials."""

from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTS_", env_file=".env", extra="ignore")
    platform_url: str = "http://localhost:8002"
    platform_service_key: SecretStr = SecretStr("")

    @field_validator("platform_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Platform URL must be HTTP(S) without embedded credentials")
        return value.rstrip("/")
