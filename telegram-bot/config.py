"""Configuration settings for the Telegram Stock Intelligence Bot."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Search for .env first in local telegram-bot folder, then in parent workspace
BOT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BOT_DIR.parent

if (BOT_DIR / ".env").exists():
    load_dotenv(BOT_DIR / ".env")
elif (WORKSPACE_DIR / ".env").exists():
    load_dotenv(WORKSPACE_DIR / ".env")


class Config:
    """Bot and backend configuration settings."""

    # Telegram bot token (from @BotFather)
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    # Application layer service URLs
    UPSTOX_SERVICE_URL: str = os.getenv("UPSTOX_SERVICE_URL", "http://localhost:8001").rstrip("/")
    STOCKGRAPH_SERVICE_URL: str = os.getenv("STOCKGRAPH_SERVICE_URL", "http://localhost:8000").rstrip("/")

    # Proactive alert broadcasting configuration
    ALERT_INTERVAL_SECONDS: int = int(os.getenv("ALERT_INTERVAL_SECONDS", "45"))
    ENABLE_PROACTIVE_ALERTS: bool = os.getenv("ENABLE_PROACTIVE_ALERTS", "true").lower() in ("true", "1", "yes")

    # Subscriber state file persistence
    SUBSCRIBERS_FILE: Path = BOT_DIR / os.getenv("SUBSCRIBERS_FILE", "subscribers.json")

    # Order simulation settings
    SIMULATED_ORDER_MODE: bool = os.getenv("SIMULATED_ORDER_MODE", "true").lower() in ("true", "1", "yes")


config = Config()

