"""Two daily checkpoints, bounded recovery, and official delivery attribution."""

import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from upstox_service.adapters.providers.exchanges.bhavcopy import parse_bhavcopy_csv
from upstox_service.adapters.providers.http_client import ResilientHttpClient
from upstox_service.adapters.providers.upstox.client import ProviderError, UpstoxClient


def _number(value, *, integer=False):
    if value is None or str(value).strip() in ("", "-"):
        return None
    try:
        value = float(str(value).replace(",", ""))
        return int(value) if integer else value
    except (ValueError, TypeError):
        return None


def recovery_dates(today, watermark, revision_days=10, catchup_days=30):
    """Recover missed weekdays and sweep revisions, bounded even after long outages."""
    sweep = today - timedelta(days=max(0, revision_days))
    start = min(watermark + timedelta(days=1), sweep) if watermark else sweep
    start = max(start, today - timedelta(days=max(catchup_days, revision_days)))
    return [
        start + timedelta(days=i)
        for i in range((today - start).days + 1)
        if (start + timedelta(days=i)).weekday() < 5
    ]


def _official_metric(official, ticker, trade_date, session, now):
    price = _number(official.get("OPEN_PRICE" if session == "OPEN" else "CLOSE_PRICE"))
    if price is None:
        return None
    metric = {
        "trade_date": trade_date,
        "ticker": ticker,
        "session_type": session,
        "open_price": _number(official.get("OPEN_PRICE")),
        "close_price": price,
        "volume": _number(official.get("TTL_TRD_QNTY"), integer=True) or 0,
        "vendor_id": "NSE_BHAVCOPY",
        "vendor_as_of": now,
    }
    if session == "CLOSE":
        metric.update(
            delivery_pct=_number(official.get("DELIV_PER")),
            delivery_qty=_number(official.get("DELIV_QTY"), integer=True),
            delivery_vendor_id="NSE_BHAVCOPY",
            delivery_vendor_as_of=now,
        )
    return metric


async def collect_checkpoints(repo, config, session: str):
    if session not in ("OPEN", "CLOSE"):
        raise ValueError("Unknown checkpoint session")
    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo("Asia/Kolkata")).date()
    client = UpstoxClient(
        config.upstox_analytics_token,
        base_url=config.upstox_api_base_url,
        timeout=config.upstox_timeout_seconds,
        max_retries=config.upstox_max_retries,
    )
    official_cache = {}
    degraded = False

    async def official_for(trade_date):
        if trade_date not in official_cache:
            url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{trade_date:%d%m%Y}.csv"
            outcome = await asyncio.to_thread(ResilientHttpClient().fetch, url)
            rows = {}
            if outcome.ok and outcome.text:
                try:
                    rows = {r["SYMBOL"].strip(): r for r in parse_bhavcopy_csv(outcome.text).rows}
                except ValueError:
                    pass
            official_cache[trade_date] = rows
        return official_cache[trade_date]

    try:
        for row in await repo.list_catalog("Stock"):
            entity = row["payload"]
            ticker = entity["ticker"]
            key = (
                entity.get("instrument_key")
                or f"{entity.get('exchange', 'NSE')}_EQ|{entity['isin']}"
            )
            watermark = await repo.get_watermark("UPSTOX", ticker, session)
            dates = recovery_dates(
                today,
                watermark,
                getattr(config, "vendor_revision_lookback_days", 10),
                getattr(config, "vendor_catchup_days", 30),
            )
            if hasattr(repo, "missing_checkpoint_dates"):
                missing = await repo.missing_checkpoint_dates(
                    ticker,
                    session,
                    today - timedelta(days=getattr(config, "vendor_catchup_days", 30)),
                    today,
                )
                dates = sorted(set(dates).union(missing))
            for trade_date in dates:
                metric, body = None, None
                try:
                    if session == "OPEN" and trade_date == today:
                        body = await client.get("/market-quote/quotes", {"instrument_key": key})
                        quotes = list(body.get("data", {}).values())
                        if len(quotes) == 1:
                            record = quotes[0]
                            stamp = float(record.get("last_trade_time", 0)) / 1000
                            last_trade = (
                                datetime.fromtimestamp(stamp, UTC)
                                .astimezone(ZoneInfo("Asia/Kolkata"))
                                .date()
                            )
                            price = record.get("ohlc", {}).get("open")
                            if last_trade == trade_date and price is not None:
                                metric = {
                                    "open_price": price,
                                    "close_price": record.get("last_price", price),
                                    "volume": record.get("volume", 0),
                                }
                    else:
                        body = await client.get(
                            f"/historical-candle/{quote(key, safe='')}/day/{trade_date.isoformat()}"
                        )
                        candles = [
                            r
                            for r in body.get("data", {}).get("candles", [])
                            if datetime.fromisoformat(r[0]).date() == trade_date
                        ]
                        if candles:
                            candle = candles[0]
                            # Historical OPEN recovery records the actual opening
                            # price, never a later close masquerading as a live quote.
                            metric = {
                                "open_price": candle[1],
                                "close_price": candle[1] if session == "OPEN" else candle[4],
                                "volume": 0 if session == "OPEN" else candle[5],
                            }
                            if session == "CLOSE":
                                metric.update(high_price=candle[2], low_price=candle[3])
                except (ProviderError, ValueError, TypeError, IndexError):
                    degraded = True
                official = (
                    (await official_for(trade_date)).get(ticker)
                    if session == "CLOSE" or metric is None
                    else None
                )
                if metric is not None:
                    await repo.stage_vendor_quote("UPSTOX", ticker, trade_date, session, body, now)
                    metric.update(
                        trade_date=trade_date,
                        ticker=ticker,
                        session_type=session,
                        vendor_id="UPSTOX",
                        vendor_as_of=now,
                    )
                    if session == "CLOSE" and official:
                        metric.update(
                            delivery_pct=_number(official.get("DELIV_PER")),
                            delivery_qty=_number(official.get("DELIV_QTY"), integer=True),
                            delivery_vendor_id="NSE_BHAVCOPY",
                            delivery_vendor_as_of=now,
                        )
                    elif session == "CLOSE":
                        degraded = True  # A vendor candle does not establish official delivery.
                else:
                    # Empty successful vendor responses need the same fallback as failures.
                    metric = (
                        _official_metric(official, ticker, trade_date, session, now)
                        if official
                        else None
                    )
                    degraded = True
                if official:
                    await repo.stage_vendor_quote(
                        "NSE_BHAVCOPY", ticker, trade_date, session, official, now
                    )
                if metric is None:
                    # No observations means unavailable, never an invented holiday/price.
                    continue
                await repo.upsert_daily_metrics([metric])
                await repo.advance_watermark(metric["vendor_id"], ticker, session, trade_date)
        return "DEGRADED" if degraded else "SUCCESS"
    finally:
        await client.close()
