"""Interactive Terminal Demo Runner.

Allows testing the entire bot flow immediately in the console:
1. Preemptive stock news feed & rising stock alerts
2. Interactive Buy / Sell selection with quantity
3. Application layer order execution & receipt generation
4. Portfolio state tracking
"""

import asyncio
import io
import sys

# Ensure UTF-8 output on Windows consoles
if sys.stdout and isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from feed import feed_manager, StockNewsItem, RisingStockAlert
from api_client import api_client


async def run_cli_demo():
    print("\n" + "=" * 65)
    print("📈 STOCKGRAPH BOT — INTERACTIVE TERMINAL SIMULATOR")
    print("=" * 65)
    print("This simulator demonstrates how the bot feeds alerts, processes")
    print("Buy/Sell user responses, and interacts with the application layer.")
    print("=" * 65 + "\n")

    user_id = 99901
    user_name = "TraderDemo"

    while True:
        print("\nChoose an action:")
        print(" [1] Simulate Preemptive Stock News Alert")
        print(" [2] Simulate Rising / Momentum Stock Alert")
        print(" [3] View Simulated Portfolio")
        print(" [4] Check Application Layer Health (:8001 / :8000)")
        print(" [5] Exit")

        choice = input("\nEnter choice [1-5]: ").strip()

        if choice == "1":
            item = feed_manager.get_news_item()
            print("\n" + "—" * 60)
            print("⚡ INCOMING TELEGRAM ALERT: STOCK NEWS IMPACT")
            print("—" * 60)
            print(f"Company:    {item.company_name} ({item.ticker})")
            print(f"CMP:        ₹{item.cmp:,.2f} | Sentiment: {item.sentiment_emoji}")
            print(f"Catalyst:   {item.catalyst}")
            print(f"Headline:   {item.headline}")
            print(f"Summary:    {item.summary}")
            print(f"Impact:     {item.impact_rationale}")
            print("—" * 60)
            print("Interactive Inline Buttons presented to user:")
            print(f" [B] 🟢 Buy {item.ticker}    [S] 🔴 Sell {item.ticker}    [C] 📊 Graph Context    [X] Ignore")

            sub_action = input("\nUser response [B/S/C/X]: ").strip().upper()
            if sub_action in ("B", "S"):
                act = "BUY" if sub_action == "B" else "SELL"
                qty = 25
                print(f"\nUser clicked '{act}'. Selecting default demo quantity: {qty} shares...")
                order = await api_client.execute_trade_order(
                    ticker=item.ticker,
                    action=act,
                    quantity=qty,
                    price=item.cmp,
                    user_id=user_id,
                    user_name=user_name,
                )
                print("\n" + "✅" * 15 + " BOT ACKNOWLEDGEMENT " + "✅" * 15)
                print(f"Order ID:        {order['order_id']}")
                print(f"Stock:           {order['ticker']} (NSE)")
                print(f"Action:          {order['action']}")
                print(f"Quantity:        {order['quantity']} shares")
                print(f"Executed Price:  ₹{order['execution_price']:,.2f}")
                print(f"Total Amount:    ₹{order['total_value']:,.2f}")
                print(f"Status:          {order['status']} via Application Layer")
                print("✅" * 40)

            elif sub_action == "C":
                print(f"\nFetching StockGraph context for {item.ticker}...")
                ctx = await api_client.get_stock_graph_context(item.ticker)
                nodes = ctx.get("nodes", [])
                edges = ctx.get("edges", [])
                print(f"Context retrieved: {len(nodes)} nodes, {len(edges)} dynamic ontology edges.")
                for edge in edges:
                    print(f" • {edge.get('source')} -[{edge.get('relation')}]-> {edge.get('target')} (conf: {edge.get('confidence')})")

        elif choice == "2":
            alert = feed_manager.get_rising_alert()
            print("\n" + "—" * 60)
            print("🚀 INCOMING TELEGRAM ALERT: RISING STOCK BREAKOUT")
            print("—" * 60)
            print(f"Company:         {alert.company_name} ({alert.ticker})")
            print(f"Price:           ₹{alert.cmp:,.2f} (+{alert.change_pct:.2f}%)")
            print(f"Breakout Level:  {alert.breakout_level}")
            print(f"Volume Surge:    {alert.volume_surge}")
            print(f"Delivery %:      {alert.delivery_pct:.1f}%")
            print(f"Catalyst:        {alert.catalyst}")
            print("—" * 60)
            print(f" [B] 🟢 Buy Breakout (+{alert.change_pct:.1f}%)    [S] 🔴 Short/Sell    [X] Ignore")

            sub_action = input("\nUser response [B/S/X]: ").strip().upper()
            if sub_action in ("B", "S"):
                act = "BUY" if sub_action == "B" else "SELL"
                qty = 50
                print(f"\nUser clicked '{act}'. Selecting demo quantity: {qty} shares...")
                order = await api_client.execute_trade_order(
                    ticker=alert.ticker,
                    action=act,
                    quantity=qty,
                    price=alert.cmp,
                    user_id=user_id,
                    user_name=user_name,
                )
                print("\n" + "✅" * 15 + " BOT ACKNOWLEDGEMENT " + "✅" * 15)
                print(f"Order ID:        {order['order_id']}")
                print(f"Stock:           {order['ticker']} (NSE)")
                print(f"Action:          {order['action']}")
                print(f"Quantity:        {order['quantity']} shares")
                print(f"Executed Price:  ₹{order['execution_price']:,.2f}")
                print(f"Total Amount:    ₹{order['total_value']:,.2f}")
                print(f"Status:          {order['status']} via Application Layer")
                print("✅" * 40)

        elif choice == "3":
            summary = api_client.get_user_portfolio_summary(user_id)
            positions = summary["active_positions"]
            print("\n" + "💼" * 10 + " SIMULATED PORTFOLIO " + "💼" * 10)
            if not positions:
                print("No positions yet. Buy a stock in option [1] or [2].")
            else:
                for ticker, qty in positions.items():
                    print(f" • {ticker}: {qty} shares")
                print(f"\nTotal Invested: ₹{summary['total_invested_value']:,.2f}")
                print(f"Total Orders:   {summary['total_orders_count']}")
            print("💼" * 31)

        elif choice == "4":
            print("\nPinging backend services...")
            health = await api_client.check_services_health()
            print(f"Upstox Data Service (:8001):   {'ONLINE' if health['upstox_data'] else 'OFFLINE (Fallback simulated)'}")
            print(f"StockGraph Service (:8000):     {'ONLINE' if health['stockgraph'] else 'OFFLINE (Fallback simulated)'}")

        elif choice == "5":
            print("\nExiting demo simulator. Goodbye!")
            break


if __name__ == "__main__":
    asyncio.run(run_cli_demo())
