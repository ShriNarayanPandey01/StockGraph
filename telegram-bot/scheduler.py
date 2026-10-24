"""Scheduler and proactive alert broadcaster for the Telegram Bot."""

import asyncio
import json
import logging
from typing import Set
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, TelegramError

from config import config
from feed import feed_manager, StockNewsItem, RisingStockAlert

logger = logging.getLogger(__name__)


class SubscriberManager:
    """Persists and manages active chat IDs subscribed to proactive alerts."""

    def __init__(self, storage_path):
        self.storage_path = storage_path
        self._subscribers: Set[int] = set()
        self._load()

    def _load(self):
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._subscribers = set(data.get("subscribers", []))
            except Exception as e:
                logger.error(f"Error loading subscribers file: {e}")

    def _save(self):
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump({"subscribers": list(self._subscribers)}, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving subscribers file: {e}")

    def add(self, chat_id: int) -> bool:
        """Adds a chat ID. Returns True if newly added."""
        if chat_id not in self._subscribers:
            self._subscribers.add(chat_id)
            self._save()
            return True
        return False

    def remove(self, chat_id: int) -> bool:
        """Removes a chat ID."""
        if chat_id in self._subscribers:
            self._subscribers.remove(chat_id)
            self._save()
            return True
        return False

    def get_all(self) -> Set[int]:
        return set(self._subscribers)


subscriber_manager = SubscriberManager(config.SUBSCRIBERS_FILE)


def build_alert_card(item) -> tuple[str, InlineKeyboardMarkup]:
    """Builds formatted Telegram message and inline action buttons for an alert."""
    if isinstance(item, StockNewsItem):
        text = (
            f"⚡ *STOCK NEWS IMPACT ALERT*\n\n"
            f"🏢 *{item.company_name}* (`{item.ticker}`)\n"
            f"📊 *CMP:* `₹{item.cmp:,.2f}` | *Sentiment:* {item.sentiment_emoji}\n"
            f"📌 *Catalyst:* {item.catalyst}\n\n"
            f"📰 *Headline:* {item.headline}\n\n"
            f"💡 *Summary:* {item.summary}\n\n"
            f"🔍 *Market Impact:* {item.impact_rationale}\n"
            f"🏛 *Source:* _{item.source}_\n"
        )
        keyboard = [
            [
                InlineKeyboardButton(f"🟢 Buy {item.ticker}", callback_data=f"buy:{item.ticker}:{item.cmp}"),
                InlineKeyboardButton(f"🔴 Sell {item.ticker}", callback_data=f"sell:{item.ticker}:{item.cmp}"),
            ],
            [
                InlineKeyboardButton("📊 Graph Context", callback_data=f"ctx:{item.ticker}"),
                InlineKeyboardButton("📰 Source Link", url=item.url or "https://www.nseindia.com"),
            ]
        ]
    elif isinstance(item, RisingStockAlert):
        text = (
            f"🚀 *MOMENTUM / RISING STOCK BREAKOUT*\n\n"
            f"🏢 *{item.company_name}* (`{item.ticker}`)\n"
            f"📈 *CMP:* `₹{item.cmp:,.2f}` (*+{item.change_pct:.2f}%*)\n"
            f"💥 *Breakout Level:* {item.breakout_level}\n"
            f"📊 *Volume Surge:* `{item.volume_surge}`\n"
            f"📦 *Delivery Accumulation:* `{item.delivery_pct:.1f}%`\n\n"
            f"🎯 *Catalyst:* {item.catalyst}\n"
        )
        keyboard = [
            [
                InlineKeyboardButton(f"🟢 Buy {item.ticker} (+{item.change_pct:.1f}%)", callback_data=f"buy:{item.ticker}:{item.cmp}"),
                InlineKeyboardButton(f"🔴 Short/Sell", callback_data=f"sell:{item.ticker}:{item.cmp}"),
            ],
            [
                InlineKeyboardButton("📊 Graph Context", callback_data=f"ctx:{item.ticker}"),
            ]
        ]
    else:
        text = "Market update received."
        keyboard = []

    return text, InlineKeyboardMarkup(keyboard)


async def proactive_broadcaster_task(bot: Bot):
    """Background coroutine that broadcasts stock news and rising stock alerts periodically."""
    if not config.ENABLE_PROACTIVE_ALERTS:
        logger.info("Proactive alerts disabled via configuration.")
        return

    logger.info(f"Proactive broadcaster started. Interval: {config.ALERT_INTERVAL_SECONDS}s")
    
    # Initial grace period before starting broadcast loop
    await asyncio.sleep(10)

    while True:
        try:
            subscribers = subscriber_manager.get_all()
            if subscribers:
                alert_item = feed_manager.get_next_proactive_alert()
                text, reply_markup = build_alert_card(alert_item)

                dead_subscribers = []
                for chat_id in subscribers:
                    try:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=text,
                            parse_mode="Markdown",
                            reply_markup=reply_markup,
                            disable_web_page_preview=True,
                        )
                        logger.debug(f"Pushed alert to chat {chat_id}")
                    except Forbidden:
                        logger.warning(f"User {chat_id} blocked bot. Removing.")
                        dead_subscribers.append(chat_id)
                    except TelegramError as e:
                        logger.error(f"Failed to send alert to {chat_id}: {e}")

                for dead_id in dead_subscribers:
                    subscriber_manager.remove(dead_id)

            await asyncio.sleep(config.ALERT_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("Proactive broadcaster task cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in proactive broadcaster: {e}", exc_info=True)
            await asyncio.sleep(15)

