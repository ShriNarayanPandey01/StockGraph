"""Two daily checkpoints, bounded recovery, and official delivery attribution."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from upstox_service.application.errors import ProviderError
from upstox_service.application.ports import (
    BhavcopyProviderPort,
    CheckpointRepositoryPort,
    PriceCheckpointProviderPort,
)


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


class CheckpointCollectionService:
    """Coordinate checkpoint recovery using injected source and storage ports."""

    def __init__(self, repo: CheckpointRepositoryPort, prices: PriceCheckpointProviderPort,
                 bhavcopy: BhavcopyProviderPort, *, revision_days: int = 10,
                 catchup_days: int = 30) -> None:
        self._repo = repo
        self._prices = prices
        self._bhavcopy = bhavcopy
        self._revision_days = revision_days
        self._catchup_days = catchup_days

    async def collect(self, session: str) -> str:
        if session not in ("OPEN", "CLOSE"):
            raise ValueError("Unknown checkpoint session")
        now = datetime.now(UTC)
        today = now.astimezone(ZoneInfo("Asia/Kolkata")).date()
        official_cache = {}
        degraded = False
        for row in await self._repo.list_catalog("Stock"):
            entity = row["payload"]
            ticker = entity["ticker"]
            key = entity.get("instrument_key") or f"{entity.get('exchange', 'NSE')}_EQ|{entity['isin']}"
            watermark = await self._repo.get_watermark("UPSTOX", ticker, session)
            dates = recovery_dates(today, watermark, self._revision_days, self._catchup_days)
            missing = await self._repo.missing_checkpoint_dates(
                ticker, session, today - timedelta(days=self._catchup_days), today
            )
            dates = sorted(set(dates).union(missing))
            for trade_date in dates:
                metric, body = None, None
                try:
                    metric, body = await self._prices.fetch_checkpoint(key, trade_date, session, today)
                except (ProviderError, ValueError, TypeError, IndexError):
                    degraded = True
                official = None
                if session == "CLOSE" or metric is None:
                    if trade_date not in official_cache:
                        official_cache[trade_date] = await self._bhavcopy.fetch(trade_date)
                    official = official_cache[trade_date].get(ticker)
                if metric is not None:
                    await self._repo.stage_vendor_quote("UPSTOX", ticker, trade_date, session, body, now)
                    metric.update(trade_date=trade_date, ticker=ticker, session_type=session,
                                  vendor_id="UPSTOX", vendor_as_of=now)
                    if session == "CLOSE" and official:
                        metric.update(delivery_pct=_number(official.get("DELIV_PER")),
                                      delivery_qty=_number(official.get("DELIV_QTY"), integer=True),
                                      delivery_vendor_id="NSE_BHAVCOPY", delivery_vendor_as_of=now)
                    elif session == "CLOSE":
                        degraded = True
                else:
                    metric = _official_metric(official, ticker, trade_date, session, now) if official else None
                    degraded = True
                if official:
                    await self._repo.stage_vendor_quote("NSE_BHAVCOPY", ticker, trade_date, session, official, now)
                if metric is None:
                    continue
                await self._repo.upsert_daily_metrics([metric])
                await self._repo.advance_watermark(metric["vendor_id"], ticker, session, trade_date)
        return "DEGRADED" if degraded else "SUCCESS"
