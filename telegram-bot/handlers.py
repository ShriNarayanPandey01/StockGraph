"""Telegram Bot Command and Callback Query Handlers."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from api_client import api_client
from feed import feed_manager
from scheduler import subscriber_manager, build_alert_card

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command and registers user for proactive stock alerts."""
    user = update.effective_user
    chat_id = update.effective_chat.id

    is_new = subscriber_manager.add(chat_id)

    welcome_msg = (
        f"👋 Welcome to *StockGraph Intelligence Bot*, {user.first_name}!\n\n"
        f"🤖 *What I Do:*\n"
        f"• *Preemptive Stock News:* Instant alerts on market-material corporate filings and sector shocks.\n"
        f"• *Rising Stock Breakouts:* Real-time surge alerts with delivery volume accumulation.\n"
        f"• *Direct Action Buttons:* Tap *Buy* or *Sell* directly from the alert to execute orders via the application layer.\n"
        f"• *Graph Context:* Trace commodity exposures, macro sensitivities, and supply chains.\n\n"
        f"🔔 *Broadcast Status:* {'✅ Subscribed to real-time proactive pushes.' if is_new else '✅ Already subscribed to proactive pushes.'}\n\n"
        f"⚡ *Quick Commands:*\n"
        f"• `/news` - Trigger a stock news impact alert\n"
        f"• `/rising` - Trigger a rising stock breakout alert\n"
        f"• `/portfolio` - View active positions & executed orders\n"
        f"• `/status` - Check backend application layer connection\n"
        f"• `/help` - Show full documentation"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /help command."""
    help_text = (
        f"📖 *StockGraph Bot Guide & Architecture*\n\n"
        f"1️⃣ *How do preemptive alerts work?*\n"
        f"The bot runs a background scheduler that monitors market events. When high-conviction news or technical breakouts occur, you receive an interactive alert card.\n\n"
        f"2️⃣ *How does Buy/Sell interact with the Application Layer?*\n"
        f"When you tap Buy/Sell, the bot makes an asynchronous API call to the backend trading/data service (`:8001`), validates margin/limits, and logs an executed order receipt.\n\n"
        f"3️⃣ *Commands:*\n"
        f"• `/start` - Subscribe to automated alerts\n"
        f"• `/news` - Receive an immediate stock news card\n"
        f"• `/rising` - Receive an immediate rising stock alert\n"
        f"• `/portfolio` - Check simulated portfolio & order history\n"
        f"• `/status` - Verify Upstox & StockGraph service health\n"
        f"• `/stop` - Unsubscribe from automated alerts"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unsubscribes the user from proactive alerts."""
    chat_id = update.effective_chat.id
    subscriber_manager.remove(chat_id)
    await update.message.reply_text(
        "🔕 You have unsubscribed from proactive alerts. You can still use `/news`, `/rising`, or re-subscribe anytime with `/start`."
    )


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually fetches and sends the next stock news card with Buy/Sell options."""
    news_item = feed_manager.get_news_item()
    text, reply_markup = build_alert_card(news_item)
    await update.message.reply_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )


async def rising_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually fetches and sends the next rising breakout stock alert."""
    rising_alert = feed_manager.get_rising_alert()
    text, reply_markup = build_alert_card(rising_alert)
    await update.message.reply_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the user's executed positions and order summary."""
    user = update.effective_user
    summary = api_client.get_user_portfolio_summary(user.id)

    positions = summary["active_positions"]
    total_invested = summary["total_invested_value"]
    order_count = summary["total_orders_count"]

    if not positions:
        msg = (
            f"💼 *Simulated Portfolio for {user.first_name}*\n\n"
            f"No active positions yet.\n"
            f"Use `/news` or `/rising` and click *🟢 Buy* on any stock to open a position!"
        )
    else:
        pos_lines = []
        for ticker, qty in positions.items():
            pos_lines.append(f"• *{ticker}*: `{qty}` shares")
        positions_str = "\n".join(pos_lines)

        msg = (
            f"💼 *Simulated Portfolio for {user.first_name}*\n\n"
            f"📈 *Active Holdings:*\n{positions_str}\n\n"
            f"💰 *Total Estimated Value:* `₹{total_invested:,.2f}`\n"
            f"📑 *Total Orders Placed:* `{order_count}`\n\n"
            f"_(Connected via StockGraph / Upstox Application Gateway)_"
        )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Checks the live connection to backend Upstox and StockGraph microservices."""
    msg = await update.message.reply_text("🔍 Checking backend microservices health...")
    health = await api_client.check_services_health()

    upstox_status = "🟢 ONLINE" if health["upstox_data"] else "🟡 STANDALONE MOCK (Service at :8001 offline)"
    stockgraph_status = "🟢 ONLINE" if health["stockgraph"] else "🟡 STANDALONE MOCK (Service at :8000 offline)"

    text = (
        f"🌐 *Application Layer Health Check*\n\n"
        f"• *Upstox Data Service (`:8001`):* {upstox_status}\n"
        f"• *StockGraph Service (`:8000`):* {stockgraph_status}\n\n"
        f"⚙️ *Operational Mode:* {'Full Standalone / Demo Resilience' if not all(health.values()) else 'Fully Integrated Live Backends'}\n"
        f"The Telegram Bot remains 100% operational in demo mode even when backend services are not running."
    )
    await msg.edit_text(text, parse_mode="Markdown")


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles interactive button callbacks (Buy, Sell, Quantity Selection, Graph Context)."""
    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split(":")
    action_type = parts[0]

    if action_type in ("buy", "sell"):
        ticker = parts[1]
        price = float(parts[2])
        action = action_type.upper()

        qty_keyboard = [
            [
                InlineKeyboardButton(f"10 shares (₹{10*price:,.0f})", callback_data=f"exec:{action}:{ticker}:10:{price}"),
                InlineKeyboardButton(f"25 shares (₹{25*price:,.0f})", callback_data=f"exec:{action}:{ticker}:25:{price}"),
            ],
            [
                InlineKeyboardButton(f"50 shares (₹{50*price:,.0f})", callback_data=f"exec:{action}:{ticker}:50:{price}"),
                InlineKeyboardButton(f"100 shares (₹{100*price:,.0f})", callback_data=f"exec:{action}:{ticker}:100:{price}"),
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
            ],
        ]
        prompt = (
            f"🛒 *Confirm {action} Order*\n\n"
            f"🏢 Stock: *{ticker}*\n"
            f"💵 Price per share: `₹{price:,.2f}`\n\n"
            f"Select quantity to execute through the Application Layer:"
        )
        await query.message.reply_text(
            prompt,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(qty_keyboard),
        )

    elif action_type == "exec":
        # Format: exec:<action>:<ticker>:<qty>:<price>
        action = parts[1]
        ticker = parts[2]
        qty = int(parts[3])
        price = float(parts[4])

        user = update.effective_user
        order = await api_client.execute_trade_order(
            ticker=ticker,
            action=action,
            quantity=qty,
            price=price,
            user_id=user.id,
            user_name=user.username or user.first_name,
        )

        receipt = (
            f"✅ *ORDER EXECUTED THROUGH APPLICATION LAYER*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 *Order ID:* `{order['order_id']}`\n"
            f"🏢 *Stock:* *{order['ticker']}* (NSE)\n"
            f"⚡ *Action:* `{order['action']}`\n"
            f"📦 *Quantity:* `{order['quantity']}` shares\n"
            f"💰 *Executed Price:* `₹{order['execution_price']:,.2f}`\n"
            f"💵 *Total Value:* `₹{order['total_value']:,.2f}`\n"
            f"🏷 *Estimated Brokerage:* `₹{order['brokerage_fees']:,.2f}`\n"
            f"🕒 *Timestamp (UTC):* `{order['executed_at'][:19]}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✨ Check `/portfolio` to see your updated positions!"
        )
        await query.edit_message_text(receipt, parse_mode="Markdown")

    elif action_type == "ctx":
        # Format: ctx:<ticker>
        ticker = parts[1]
        await query.message.reply_chat_action("typing")
        ctx = await api_client.get_stock_graph_context(ticker)

        edges = ctx.get("edges", []) if ctx else []
        nodes = ctx.get("nodes", []) if ctx else []

        commodities = [e["target"].split(":")[-1] for e in edges if e.get("relation") == "EXPOSED_TO"]
        macros = [e["target"].split(":")[-1] for e in edges if e.get("relation") == "SENSITIVE_TO_MACRO"]

        com_str = ", ".join(f"`{c}`" for c in commodities) if commodities else "None direct"
        mac_str = ", ".join(f"`{m}`" for m in macros) if macros else "Broad Indian macro"

        card = (
            f"🌐 *StockGraph Dynamic Knowledge Context*\n\n"
            f"🏢 *Entity:* `{ticker}`\n"
            f"🛢 *Exposed Commodities:* {com_str}\n"
            f"📉 *Macro Factor Sensitivities:* {mac_str}\n"
            f"🔗 *Graph Nodes In Scope:* `{len(nodes)}`\n"
            f"📈 *Dynamic Ontology Edges:* `{len(edges)}`\n\n"
            f"💡 _Inferred via StockGraph Temporal GraphRAG + FalkorDB._"
        )
        await query.message.reply_text(card, parse_mode="Markdown")

    elif action_type == "cancel":
        await query.edit_message_text("❌ Order cancelled.")

