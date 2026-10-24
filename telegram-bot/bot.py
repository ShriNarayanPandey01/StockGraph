"""Main entry point for the Telegram Stock Intelligence Bot.

Can run in two modes:
1. Live Telegram Bot (requires TELEGRAM_BOT_TOKEN in .env or environment)
2. Interactive Terminal Demo Simulation (for testing news feed, buttons & order execution without a Telegram bot token)
"""

import asyncio
import io
import logging
import sys

# Ensure UTF-8 output on Windows consoles
if sys.stdout and isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    Application,
)

from config import config
from handlers import (
    start_command,
    help_command,
    news_command,
    rising_command,
    portfolio_command,
    status_command,
    stop_command,
    callback_query_handler,
)
from scheduler import proactive_broadcaster_task

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("StockGraphBot")


async def post_init(application: Application) -> None:
    """Invoked after bot initialization to start background async tasks."""
    logger.info("Initializing proactive market alert broadcaster...")
    asyncio.create_task(proactive_broadcaster_task(application.bot))


def run_telegram_bot():
    """Runs the live Telegram Bot using python-telegram-bot polling."""
    token = config.TELEGRAM_BOT_TOKEN
    if not token or token == "your_telegram_bot_token_here":
        print("\n" + "=" * 70)
        print("⚠️  TELEGRAM_BOT_TOKEN NOT CONFIGURED")
        print("=" * 70)
        print("To run the live bot on Telegram:")
        print("1. Open Telegram and search for @BotFather")
        print("2. Send /newbot and follow prompts to get your bot HTTP API Token")
        print("3. Paste it into 'telegram-bot/.env':")
        print("   TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ")
        print("4. Restart: python bot.py")
        print("-" * 70)
        print("💡 Alternatively, you can test the entire workflow right now using:")
        print("   python demo_cli.py")
        print("=" * 70 + "\n")
        sys.exit(1)

    print("🚀 Starting StockGraph Telegram Bot...")
    app = ApplicationBuilder().token(token).post_init(post_init).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("rising", rising_command))
    app.add_handler(CommandHandler("portfolio", portfolio_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("stop", stop_command))

    # Register interactive callback query handler
    app.add_handler(CallbackQueryHandler(callback_query_handler))

    logger.info("Bot is active and polling for updates. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    run_telegram_bot()
