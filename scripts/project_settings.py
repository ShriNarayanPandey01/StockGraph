"""Configuration used only by project-wide backup/reset tooling.

This deliberately lives outside either deployable service because the data
maintenance script must address TimescaleDB, FalkorDB, and Redis together.
Runtime services continue to own their own narrower settings models.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class ProjectDataSettings(BaseSettings):
    """Local project data targets guarded by :mod:`scripts.project_data`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    timescale_dsn: str = "postgresql://stockgraph:stockgraph@localhost:5432/stockgraph"
    falkor_host: str = "localhost"
    falkor_port: int = 6379
    falkor_graph_name: str = "stock_graph"
    redis_url: str = "redis://localhost:6380/0"
