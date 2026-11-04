"""Future Platform connection settings; health checks need no credentials."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTS_", env_file=".env", extra="ignore")
    enabled: bool = False
    platform_url: str = "http://localhost:8002"
    platform_service_key: SecretStr = SecretStr("")
    poll_seconds: float = Field(default=5, ge=1, le=60)
    heartbeat_seconds: float = Field(default=2, ge=1, le=30)
    deadline_seconds: int = Field(default=180, ge=10, le=180)
    max_output_tokens: int = Field(default=8192, ge=1, le=32000)
    usage_log_path: str = 'logs/agents/agent-model-usage.jsonl'
    usage_log_max_bytes: int = Field(default=10_485_760, ge=1024, le=1_073_741_824)
    usage_log_backup_count: int = Field(default=5, ge=1, le=50)
    llm_enabled: bool = Field(default=False, validation_alias=AliasChoices('AGENTS_LLM_ENABLED', 'LLM_ENABLED'))
    llm_provider: Literal['legacy', 'baseten', 'openai', 'anthropic', 'openrouter', 'openai_compatible', 'litellm'] = Field(default='legacy', validation_alias=AliasChoices('AGENTS_LLM_PROVIDER', 'LLM_PROVIDER'))
    llm_chat_model: str = Field(default='gpt-4o-mini', validation_alias=AliasChoices('AGENTS_LLM_CHAT_MODEL', 'LLM_CHAT_MODEL'))
    llm_json_mode: Literal['auto', 'json_object', 'json_schema', 'prompt'] = Field(default='auto', validation_alias=AliasChoices('AGENTS_LLM_JSON_MODE', 'LLM_JSON_MODE'))
    llm_reasoning_effort: Literal['minimal', 'low', 'medium', 'high', 'xhigh'] = Field(default='low', validation_alias=AliasChoices('AGENTS_LLM_REASONING_EFFORT', 'LLM_REASONING_EFFORT'))
    openai_api_key: SecretStr = Field(default=SecretStr(''), validation_alias=AliasChoices('AGENTS_OPENAI_API_KEY', 'OPENAI_API_KEY'))
    baseten_api_key: SecretStr = Field(default=SecretStr(''), validation_alias=AliasChoices('AGENTS_BASETEN_API_KEY', 'BASETEN_API_KEY'))
    baseten_api_base: str = Field(default='https://inference.baseten.co/v1', validation_alias=AliasChoices('AGENTS_BASETEN_API_BASE', 'BASETEN_API_BASE'))
    anthropic_api_key: SecretStr = Field(default=SecretStr(''), validation_alias=AliasChoices('AGENTS_ANTHROPIC_API_KEY', 'ANTHROPIC_API_KEY'))
    openrouter_api_key: SecretStr = Field(default=SecretStr(''), validation_alias=AliasChoices('AGENTS_OPENROUTER_API_KEY', 'OPENROUTER_API_KEY'))
    llm_api_key: SecretStr = Field(default=SecretStr(''), validation_alias=AliasChoices('AGENTS_LLM_API_KEY', 'LLM_API_KEY'))
    llm_api_base: str = Field(default='', validation_alias=AliasChoices('AGENTS_LLM_API_BASE', 'LLM_API_BASE'))

    @field_validator("platform_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Platform URL must be HTTP(S) without embedded credentials")
        return value.rstrip("/")

    @field_validator('baseten_api_base', 'llm_api_base')
    @classmethod
    def validate_model_url(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Model URL must be HTTP(S) without embedded credentials')
        return value.rstrip('/')
