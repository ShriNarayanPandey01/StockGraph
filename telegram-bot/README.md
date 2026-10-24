# 🤖 StockGraph Telegram Intelligence Bot (Standalone Project)

A standalone Telegram bot for **Indian Equities (NSE/BSE)** that:
1. **Preemptively broadcasts stock news & momentum breakout alerts** (rising stocks with volume/delivery accumulation).
2. **Offers inline interactive Buy/Sell options** for users directly under every alert message.
3. **Acknowledges user choices**, queries the application layer, executes the trade, and delivers an instant execution receipt & portfolio update.

---

## 🏗️ How the Chatbot Interacts with the Application Layer

The diagram below outlines the dual-flow interaction pattern between the Telegram bot and your application layer services (`Upstox Data Service` on `:8001` and `StockGraph Service` on `:8000`):

```
+----------------------------------------------------------------------------------+
|                              APPLICATION LAYER                                   |
|                                                                                  |
|   +------------------------------------+   +---------------------------------+   |
|   |   Upstox Data Service (:8001)      |   |    StockGraph Service (:8000)   |   |
|   |  - NSE Bhavcopy / Price Breakouts  |   |  - FalkorDB Graph & Vector RAG  |   |
|   |  - Corporate Filings (Reg-30)      |   |  - Dynamic Ontology Builder     |   |
|   |  - Order Staging & Execution       |   |  - Macro & Sentiment Inference  |   |
|   +-----------------+------------------+   +----------------+----------------+   |
+---------------------|---------------------------------------|--------------------+
                      |                                       |
    [1. Outbound Push / Event Queue]        [3. Graph Context Query]
    - Redis Streams (`stockgraph:events:v1`)  - GET /api/v1/stocks/{ticker}/context
    - Breakout Detector / News Feeder         - Exposures, Commodities, Macro
                      |                                       |
                      v                                       v
+----------------------------------------------------------------------------------+
|                            TELEGRAM BOT SERVICE                                  |
|                                                                                  |
|   +------------------------------------+   +---------------------------------+   |
|   |  Proactive Broadcaster (scheduler) |   |    Application Layer Client     |   |
|   |  - Pushes preemptive news & surges |   |  - api_client.py                |   |
|   +-----------------+------------------+   +----------------^----------------+   |
|                     |                                       |                    |
|                     | [Send Alert Message]                  | [Execute Order]    |
|                     v                                       |                    |
|             +---------------+                       +-------+--------+           |
|             | Telegram Cloud|                       | User Taps Buy/ |           |
|             |  Bot API      |                       | Sell Inline Btn|           |
|             +-------+-------+                       +-------+--------+           |
+---------------------|---------------------------------------|--------------------+
                      v                                       |
                   [User Device: Telegram Chat Screen]        |
                   - Receives Stock Alert Card                |
                   - Clicks [🟢 Buy] or [🔴 Sell] ------------+
```

### 1. Outbound / Preemptive Flow (Push Alerts)
- **Event Detection:** Upstox ingestion jobs detect a high-momentum price/volume breakout or NSE Reg-30 corporate disclosure.
- **Enrichment:** StockGraph computes entity sentiment and dynamic exposure paths (e.g. `RELIANCE` impacted by `BRENT_CRUDE` fall).
- **Broadcast:** The bot's background broadcaster (`scheduler.py`) pulls the next curated alert and broadcasts formatted markdown messages with interactive inline keyboards (`[🟢 Buy]`, `[🔴 Sell]`, `[📊 Graph Context]`) to all subscribed chat IDs.

### 2. Inbound / Interactive Flow (Order Execution)
- **User Action:** The user taps **`🟢 Buy RELIANCE`**.
- **Callback Handling:** Telegram sends an asynchronous `CallbackQuery` to `handlers.py`.
- **Immediate Ack:** The bot calls `query.answer()` for instant UI feedback and prompts for order quantity (`10`, `25`, `50`, `100` shares).
- **Application Layer Call:** Upon selection, `api_client.execute_trade_order(...)` sends the order payload to the application gateway.
- **Execution Receipt:** The message is updated with a verified execution receipt containing:
  - Unique `order_id` (e.g. `ORD-20261024-XXXX`)
  - Executed price & total value
  - Execution mode (`SIMULATED` or `LIVE`)
  - Realized position added to `/portfolio`

---

## 📁 Project Structure

```
telegram-bot/
├── .env.example          # Sample environment configuration
├── config.py             # Configuration & environment variable loader
├── feed.py               # News feed & rising stock breakout models and data
├── api_client.py         # HTTP client communicating with Upstox (:8001) & StockGraph (:8000)
├── handlers.py           # /start, /news, /rising, /portfolio, /status & button handlers
├── scheduler.py          # Background proactive broadcast engine
├── bot.py                # Main live Telegram bot runner
├── demo_cli.py           # Interactive terminal simulator (no token required)
├── requirements.txt      # Python dependencies (python-telegram-bot, httpx, python-dotenv)
└── README.md             # Complete documentation
```

---

## 🚀 Getting Started

### 1. Install Dependencies
Dependencies are already installed in your workspace virtual environment `venv`:
```powershell
.\venv\Scripts\python.exe -m pip install -r telegram-bot\requirements.txt
```

### 2. Option A: Test with the Interactive Terminal Simulator (No Telegram Token Needed!)
You can test the entire news feed, rising breakout alerts, interactive buy/sell orders, and portfolio tracking right in your terminal:

```powershell
$env:PYTHONPATH="telegram-bot"
.\venv\Scripts\python.exe telegram-bot\demo_cli.py
```

### 3. Option B: Run the Live Telegram Bot
1. Open Telegram and search for **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot` and follow the prompts to choose a name and username.
3. Copy the HTTP API token provided by BotFather.
4. Create a `.env` file inside `telegram-bot/` (or copy from `.env.example`):
   ```bash
   cp telegram-bot/.env.example telegram-bot/.env
   ```
5. Paste your token in `telegram-bot/.env`:
   ```env
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
   ```
6. Start the bot:
   ```powershell
   $env:PYTHONPATH="telegram-bot"
   .\venv\Scripts\python.exe telegram-bot\bot.py
   ```
7. Open your bot on Telegram and send `/start`!

---

## 💬 Bot Commands

| Command | Action |
|---|---|
| `/start` | Subscribes your chat to automated preemptive news & rising stock alerts |
| `/news` | Manually triggers the latest stock news card with Buy/Sell buttons |
| `/rising` | Manually triggers the latest momentum / rising stock breakout card |
| `/portfolio` | Displays current simulated active holdings and order history |
| `/status` | Checks connection health to Upstox (:8001) and StockGraph (:8000) |
| `/stop` | Unsubscribes from automated broadcasts |
| `/help` | Shows bot commands and instructions |

