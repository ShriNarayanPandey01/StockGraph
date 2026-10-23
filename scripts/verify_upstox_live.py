"""Read-only live verification for every implemented Upstox provider capability.

Run from the repository root after setting ``UPSTOX_ANALYTICS_TOKEN`` in the
git-ignored .env file:

    $env:PYTHONPATH = "services/upstox/src"
    .venv/Scripts/python.exe scripts/verify_upstox_live.py

The script never prints credentials or response payloads, and it deliberately
does not call registration/outbox endpoints or persist any response to SQL.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from upstox_service.adapters.providers.upstox.client import UpstoxClient
from upstox_service.adapters.providers.upstox.market import UpstoxMarketProvider
from upstox_service.adapters.providers.upstox.stock_data import UpstoxStockDataProvider
from upstox_service.config.settings import Settings


async def main() -> int:
    settings = Settings()
    if not settings.upstox_analytics_token.get_secret_value():
        print(json.dumps({"error": "UPSTOX_ANALYTICS_TOKEN is not configured"}))
        return 2

    v2 = UpstoxClient(
        settings.upstox_analytics_token,
        base_url=settings.upstox_api_base_url,
        timeout=settings.upstox_timeout_seconds,
        max_retries=settings.upstox_max_retries,
    )
    v3 = UpstoxClient(
        settings.upstox_analytics_token,
        base_url=settings.upstox_api_v3_base_url,
        timeout=settings.upstox_timeout_seconds,
        max_retries=settings.upstox_max_retries,
    )
    stock = UpstoxStockDataProvider(v2, v3)
    market = UpstoxMarketProvider(v2)
    ist_today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    results: dict[str, dict[str, str]] = {}

    async def check(name: str, operation: Callable[[], Awaitable[object]]) -> object | None:
        try:
            value = await operation()
        except Exception as exc:  # Report provider availability/entitlements, keep testing.
            results[name] = {"status": "failed", "error": str(exc)[:240]}
            return None
        results[name] = {"status": "ok"}
        return value

    try:
        await check("equity_universe", stock.fetch_equity_universe)
        reliance = await check("stock_identity", lambda: stock.resolve("RELIANCE", "NSE"))
        if isinstance(reliance, dict):
            isin = reliance["isin"]
            key = reliance["instrument_key"]
            await check("company_profile", lambda: stock.fetch_profile(isin))
            await check("shareholding", lambda: stock.fetch_shareholding(isin))
            await check(
                "daily_candles",
                lambda: stock.fetch_daily_candles(key, ist_today - timedelta(days=10), ist_today - timedelta(days=1)),
            )

        nifty = await check("derivatives_underlying", lambda: market.resolve_underlying("NIFTY 50", "NSE"))
        expiry: str | None = None
        if nifty is not None:
            expiries = await check("option_expiries", lambda: market.option_expiries("NIFTY 50", "NSE"))
            if isinstance(expiries, dict) and expiries.get("expiries"):
                expiry = expiries["expiries"][0]
                await check("option_chain", lambda: market.option_chain("NIFTY 50", "NSE", expiry))

        await check(
            "smartlist_mtf",
            lambda: market.smartlist("mtf", asset_type=None, category=None, page_number=1, page_size=10),
        )
        await check(
            "smartlist_options",
            lambda: market.smartlist(
                "options", asset_type="STOCK", category="TOP_TRADED", page_number=1, page_size=10
            ),
        )
        await check(
            "smartlist_futures",
            lambda: market.smartlist(
                "futures", asset_type="STOCK", category="TOP_TRADED", page_number=1, page_size=10
            ),
        )
        await check(
            "fii_flows",
            lambda: market.institutional_flows("FII", ("NSE_EQ|CASH",), "1D", None),
        )
        await check(
            "dii_flows",
            lambda: market.institutional_flows("DII", ("NSE_EQ|CASH",), "1D", None),
        )
        await check("market_holidays", lambda: market.holidays(None))
        await check("exchange_status", lambda: market.exchange_status("NSE"))

        if expiry is not None:
            await check(
                "pcr",
                lambda: market.derivatives_analytics(
                    "pcr", "NIFTY 50", "NSE", expiry, ist_today, bucket_interval=60
                ),
            )
            await check(
                "oi",
                lambda: market.derivatives_analytics("oi", "NIFTY 50", "NSE", expiry, ist_today),
            )
            await check(
                "change_oi",
                lambda: market.derivatives_analytics(
                    "change-oi", "NIFTY 50", "NSE", expiry, ist_today, interval=1
                ),
            )
            await check(
                "max_pain",
                lambda: market.derivatives_analytics(
                    "max-pain", "NIFTY 50", "NSE", expiry, ist_today, bucket_interval=60
                ),
            )
    finally:
        await stock.close()
        await v2.close()
        await v3.close()

    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if all(item["status"] == "ok" for item in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
