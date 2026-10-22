"""Two daily checkpoints only; official Bhavcopy owns delivery measurements."""

import asyncio
from datetime import UTC, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from upstox_service.adapters.providers.exchanges.bhavcopy import parse_bhavcopy_csv
from upstox_service.adapters.providers.http_client import ResilientHttpClient
from upstox_service.adapters.providers.upstox.client import ProviderError, UpstoxClient


def _number(value, *, integer=False):
    if value is None or str(value).strip() in ("", "-"):
        return None
    try:
        return (
            int(float(str(value).replace(",", "")))
            if integer
            else float(str(value).replace(",", ""))
        )
    except (ValueError, TypeError):
        return None


async def collect_checkpoints(repo, config, session: str):
    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo("Asia/Kolkata")).date()
    client = UpstoxClient(
        config.upstox_analytics_token,
        base_url=config.upstox_api_base_url,
        timeout=config.upstox_timeout_seconds,
        max_retries=config.upstox_max_retries,
    )
    delivery = {}
    degraded = False
    if session == "CLOSE":
        url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{today:%d%m%Y}.csv"
        outcome = await asyncio.to_thread(ResilientHttpClient().fetch, url)
        if outcome.ok and outcome.text:
            try:
                delivery = {
                    row["SYMBOL"].strip(): row for row in parse_bhavcopy_csv(outcome.text).rows
                }
            except ValueError:
                degraded = True
        else:
            degraded = True
    try:
        for row in await repo.list_catalog("Stock"):
            entity = row["payload"]
            ticker = entity["ticker"]
            key = (
                entity.get("instrument_key")
                or f"{entity.get('exchange', 'NSE')}_EQ|{entity['isin']}"
            )
            try:
                if session == "OPEN":
                    body = await client.get("/market-quote/quotes", {"instrument_key": key})
                    quotes = list(body.get("data", {}).values())
                    if len(quotes) != 1:
                        degraded = True
                        continue
                    record = quotes[0]
                    last_trade = (
                        datetime.fromtimestamp(float(record.get("last_trade_time", 0)) / 1000, UTC)
                        .astimezone(ZoneInfo("Asia/Kolkata"))
                        .date()
                    )
                    if last_trade != today:
                        continue  # Market holidays must not fabricate trading dates.
                    ohlc = record.get("ohlc", {})
                    price = ohlc.get("open")
                    if price is None:
                        degraded = True
                        continue
                    metric = {
                        "trade_date": today,
                        "ticker": ticker,
                        "session_type": "OPEN",
                        "open_price": price,
                        "close_price": record.get("last_price", price),
                        "volume": record.get("volume", 0),
                    }
                else:
                    body = await client.get(
                        f"/historical-candle/{quote(key, safe='')}/day/{today.isoformat()}"
                    )
                    records = [
                        r
                        for r in body.get("data", {}).get("candles", [])
                        if datetime.fromisoformat(r[0]).date() == today
                    ]
                    if not records:
                        continue
                    candle = records[0]
                    metric = {
                        "trade_date": today,
                        "ticker": ticker,
                        "session_type": "CLOSE",
                        "open_price": candle[1],
                        "high_price": candle[2],
                        "low_price": candle[3],
                        "close_price": candle[4],
                        "volume": candle[5],
                    }
                await repo.stage_vendor_quote("UPSTOX", ticker, today, session, body, now)
                metric.update(vendor_id="UPSTOX", vendor_as_of=now)
                official = delivery.get(ticker)
                if official:
                    await repo.stage_vendor_quote(
                        "NSE_BHAVCOPY", ticker, today, "CLOSE", official, now
                    )
                    metric.update(
                        delivery_pct=_number(official.get("DELIV_PER")),
                        delivery_qty=_number(official.get("DELIV_QTY"), integer=True),
                        delivery_vendor_id="NSE_BHAVCOPY",
                        delivery_vendor_as_of=now,
                    )
                    # Trace delivery independently; price stays attributed to UPSTOX.
                await repo.upsert_daily_metrics([metric])
                await repo.advance_watermark("UPSTOX", ticker, session, today)
            except (ProviderError, ValueError, TypeError, IndexError):
                degraded = True
                # Official closing data remains useful when the price vendor is down.
                official = delivery.get(ticker) if session == "CLOSE" else None
                if official and _number(official.get("CLOSE_PRICE")) is not None:
                    await repo.stage_vendor_quote(
                        "NSE_BHAVCOPY", ticker, today, "CLOSE", official, now
                    )
                    await repo.upsert_daily_metrics(
                        [
                            {
                                "trade_date": today,
                                "ticker": ticker,
                                "session_type": "CLOSE",
                                "close_price": _number(official.get("CLOSE_PRICE")),
                                "volume": _number(official.get("TTL_TRD_QNTY"), integer=True) or 0,
                                "delivery_pct": _number(official.get("DELIV_PER")),
                                "delivery_qty": _number(official.get("DELIV_QTY"), integer=True),
                                "vendor_id": "NSE_BHAVCOPY",
                                "vendor_as_of": now,
                                "delivery_vendor_id": "NSE_BHAVCOPY",
                                "delivery_vendor_as_of": now,
                            }
                        ]
                    )
                    await repo.advance_watermark("NSE_BHAVCOPY", ticker, "CLOSE", today)
        return "DEGRADED" if degraded else "SUCCESS"
    finally:
        await client.close()
