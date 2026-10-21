"""Chart vendor adapter + sync/normalization (Rule 7).

All numeric reads/writes go through ChartProviderAdapter - no vendor SDK
imports outside this file. Raw payloads stage immutably into
vendor_quotes_raw with vintage key (vendor_id, ticker, trade_date, series,
fetched_at); a revision inserts a NEW vintage, never overwrites.
Normalization reads the latest vintage per key and inserts two checkpoint
rows per day (OPEN + CLOSE) into daily_stock_metrics.

Backfill watermark: vendor_sync_state tracks the last trade_date pushed per
(vendor_id, ticker, series). Each sync inserts rows with
trade_date > last_trade_date, then advances the watermark. A revision sweep
re-fetches the trailing vendor_revision_lookback_days window and stages
changed payloads as new vintages (the watermark only moves forward).
"""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import math
from typing import Any

from src.config.settings import settings
from src.domain.enums import MarketSession

logger = logging.getLogger(__name__)

OPEN_SERIES = "EOD_OPEN"
CLOSE_SERIES = "EOD_CLOSE"


@dataclass(frozen=True)
class EodBar:
    """One vendor daily bar; numeric coercion happens at normalization."""

    trade_date: date
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    volume: int | None = None


class ChartProviderAdapter(ABC):
    """Generic vendor contract - the ONLY vendor touchpoint (Rule 7)."""

    vendor_id: str = "vendor"

    @abstractmethod
    def get_eod_series(self, ticker: str, start: date, end: date) -> list[dict]:
        """Return daily bars as dicts with trade_date + OHLCV keys."""

    @abstractmethod
    def get_macro_series(self, keys: list[str], start: date, end: date) -> list[dict]:
        """Return macro/flow rows as dicts with trade_date + key columns."""


def payload_hash(payload: dict[str, Any]) -> str:
    """Stable hash for revision comparison (sorted JSON, str-normalized)."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def to_eod_bar(raw: dict[str, Any]) -> EodBar | None:
    """Coerce a vendor row dict into an EodBar; None when unusable."""
    trade_date = raw.get("trade_date")
    if isinstance(trade_date, str):
        trade_date = date.fromisoformat(trade_date)
    if not isinstance(trade_date, date):
        return None

    def num(key: str) -> float | None:
        try:
            value = raw.get(key)
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    volume = raw.get("volume")
    try:
        volume = int(volume) if volume is not None else None
    except (TypeError, ValueError):
        volume = None
    if num("close_price") is None and num("close") is None:
        return None
    return EodBar(
        trade_date=trade_date,
        open_price=num("open_price") if num("open_price") is not None else num("open"),
        high_price=num("high_price") if num("high_price") is not None else num("high"),
        low_price=num("low_price") if num("low_price") is not None else num("low"),
        close_price=num("close_price") if num("close_price") is not None else num("close"),
        volume=volume,
    )


class MockChartProviderAdapter(ChartProviderAdapter):
    """Deterministic in-memory vendor adapter for offline tests and local development."""

    vendor_id: str = "mock_vendor"

    def __init__(self, data: dict[str, list[dict]] | None = None) -> None:
        self.data: dict[str, list[dict]] = data or {}
        self.macro_data: list[dict] = []

    def get_eod_series(self, ticker: str, start: date, end: date) -> list[dict]:
        series = self.data.get(ticker.upper(), [])
        out = []
        for bar in series:
            td = bar.get("trade_date")
            if isinstance(td, str):
                td = date.fromisoformat(td)
            if td and start <= td <= end:
                out.append(bar)
        return out

    def get_macro_series(self, keys: list[str], start: date, end: date) -> list[dict]:
        out = []
        for row in self.macro_data:
            td = row.get("trade_date")
            if isinstance(td, str):
                td = date.fromisoformat(td)
            if td and start <= td <= end:
                filtered = {"trade_date": td}
                for k in keys:
                    if k in row:
                        filtered[k] = row[k]
                out.append(filtered)
        return out


class UpstoxChartAdapter(ChartProviderAdapter):
    """Upstox market data provider adapter (Rule 7)."""

    vendor_id: str = "upstox"

    def __init__(self, api_key: str | None = None, http_client: Any | None = None) -> None:
        self._api_key = api_key
        self._http = http_client

    def get_eod_series(self, ticker: str, start: date, end: date) -> list[dict]:
        # Concrete implementation connects via Upstox historical candles API
        # Falls back to empty list when client/network is unavailable
        if self._http is None:
            return []
        try:
            url = f"https://api.upstox.com/v2/historical-candle/{ticker}/day/{end}/{start}"
            outcome = self._http.fetch(url)
            if not outcome.ok or not outcome.text:
                return []
            data = json.loads(outcome.text)
            candles = data.get("data", {}).get("candles", [])
            out = []
            for c in candles:
                # Upstox candle format: [timestamp, open, high, low, close, volume, oi]
                if len(c) >= 6:
                    trade_date = c[0].split("T")[0]
                    out.append({
                        "trade_date": trade_date,
                        "open_price": float(c[1]),
                        "high_price": float(c[2]),
                        "low_price": float(c[3]),
                        "close_price": float(c[4]),
                        "volume": int(c[5]),
                    })
            return out
        except Exception as exc:
            logger.warning("Upstox fetch failed for %s: %s", ticker, exc)
            return []

    def get_macro_series(self, keys: list[str], start: date, end: date) -> list[dict]:
        # Macro indicators fetched from vendor feeds
        return []


@dataclass(frozen=True)
class VendorSyncResult:
    """Outcome of one series sync pass."""

    staged_count: int
    new_watermark: date | None
    revisions_staged: int = 0
    gaps_detected: int = 0


class VendorSyncService:
    """Manages vendor watermarks, immutable staging, revision sweeps, and normalization (Rule 7)."""

    def __init__(self, timescale_repo: Any) -> None:
        self._repo = timescale_repo

    async def stage_raw(
        self,
        vendor_id: str,
        ticker: str,
        trade_date: date,
        series: str,
        payload: dict[str, Any],
        fetched_at: datetime | None = None,
    ) -> None:
        """Stage raw payload as an immutable vintage in vendor_quotes_raw."""
        await self._repo.stage_vendor_quote(
            vendor_id=vendor_id,
            ticker=ticker.upper(),
            trade_date=trade_date,
            series=series,
            payload=payload,
            fetched_at=fetched_at,
        )

    async def sync_ticker(
        self,
        adapter: ChartProviderAdapter,
        ticker: str,
        series: str,
        start: date,
        end: date,
    ) -> VendorSyncResult:
        """Sync new trading dates past the existing watermark and advance watermark."""
        watermark = await self._repo.get_watermark(adapter.vendor_id, ticker.upper(), series)
        fetch_start = (watermark + timedelta(days=1)) if watermark is not None else start
        if fetch_start > end:
            return VendorSyncResult(staged_count=0, new_watermark=watermark)

        bars = adapter.get_eod_series(ticker.upper(), fetch_start, end)
        staged_count = 0
        new_watermark = watermark

        for bar in bars:
            eod_bar = to_eod_bar(bar)
            if eod_bar is not None and (watermark is None or eod_bar.trade_date > watermark):
                await self.stage_raw(adapter.vendor_id, ticker, eod_bar.trade_date, series, bar)
                staged_count += 1
                if new_watermark is None or eod_bar.trade_date > new_watermark:
                    new_watermark = eod_bar.trade_date

        if new_watermark is not None and (watermark is None or new_watermark > watermark):
            await self._repo.advance_watermark(
                adapter.vendor_id, ticker.upper(), series, new_watermark
            )

        return VendorSyncResult(staged_count=staged_count, new_watermark=new_watermark)

    async def check_revisions(
        self,
        adapter: ChartProviderAdapter,
        ticker: str,
        series: str,
        end: date,
        lookback_days: int | None = None,
    ) -> int:
        """Revision sweep: re-fetch trailing lookback window, stage changed payloads as new vintages.

        The watermark only moves forward; revisions are staged as immutable newer vintages.
        """
        lookback = lookback_days or settings.vendor_revision_lookback_days
        start = end - timedelta(days=lookback)

        records = await self._repo.get_latest_vintages(adapter.vendor_id, ticker.upper(), start, end)
        staged_hashes: dict[date, str] = {}
        for r in records:
            if r["series"] == series:
                payload = r["payload"]
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        pass
                staged_hashes[r["trade_date"]] = payload_hash(payload if isinstance(payload, dict) else {})

        fresh_bars = adapter.get_eod_series(ticker.upper(), start, end)
        revisions_staged = 0
        now_ts = datetime.now(timezone.utc)

        for bar in fresh_bars:
            eod = to_eod_bar(bar)
            if eod is None:
                continue
            h = payload_hash(bar)
            if eod.trade_date in staged_hashes:
                if h != staged_hashes[eod.trade_date]:
                    await self.stage_raw(
                        adapter.vendor_id, ticker, eod.trade_date, series, bar, fetched_at=now_ts
                    )
                    revisions_staged += 1
            else:
                # Gap detected in lookback window - stage it
                await self.stage_raw(
                    adapter.vendor_id, ticker, eod.trade_date, series, bar, fetched_at=now_ts
                )
                revisions_staged += 1

        return revisions_staged

    async def normalize_ticker(
        self,
        ticker: str,
        start: date,
        end: date,
        vendor_id: str,
    ) -> int:
        """Normalize staged raw payloads into daily_stock_metrics (2 rows per day: OPEN + CLOSE)."""
        records = await self._repo.get_latest_vintages(vendor_id, ticker.upper(), start, end)
        if not records:
            return 0

        by_date: dict[date, dict[str, Any]] = {}
        for r in records:
            td = r["trade_date"]
            payload = r["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    pass
            bar = to_eod_bar(payload if isinstance(payload, dict) else {})
            if bar is not None:
                by_date[td] = {
                    "bar": bar,
                    "fetched_at": r["fetched_at"],
                    "delivery_qty": payload.get("delivery_qty") if isinstance(payload, dict) else None,
                    "delivery_pct": payload.get("delivery_pct") if isinstance(payload, dict) else None,
                    "pe_ratio": payload.get("pe_ratio") if isinstance(payload, dict) else None,
                    "pb_ratio": payload.get("pb_ratio") if isinstance(payload, dict) else None,
                    "ev_ebitda": payload.get("ev_ebitda") if isinstance(payload, dict) else None,
                    "pe_5yr_percentile": payload.get("pe_5yr_percentile") if isinstance(payload, dict) else None,
                }

        sorted_dates = sorted(by_date.keys())
        open_rows: list[dict[str, Any]] = []
        close_rows: list[dict[str, Any]] = []

        for td in sorted_dates:
            entry = by_date[td]
            bar: EodBar = entry["bar"]
            fetched_at = entry["fetched_at"]

            # 1. OPEN Session Checkpoint row
            open_rows.append({
                "trade_date": td,
                "session_type": MarketSession.OPEN.value,
                "ticker": ticker.upper(),
                "open_price": bar.open_price,
                "high_price": bar.open_price,
                "low_price": bar.open_price,
                "close_price": bar.open_price,
                "volume": 0,
                "delivery_qty": None,
                "delivery_pct": None,
                "delivery_20d_avg": None,
                "delivery_20d_zscore": None,
                "pe_ratio": entry["pe_ratio"],
                "pb_ratio": entry["pb_ratio"],
                "ev_ebitda": entry["ev_ebitda"],
                "pe_5yr_percentile": entry["pe_5yr_percentile"],
                "vendor_id": vendor_id,
                "vendor_as_of": fetched_at,
            })

            # 2. CLOSE Session Checkpoint row
            close_rows.append({
                "trade_date": td,
                "session_type": MarketSession.CLOSE.value,
                "ticker": ticker.upper(),
                "open_price": bar.open_price,
                "high_price": bar.high_price,
                "low_price": bar.low_price,
                "close_price": bar.close_price,
                "volume": bar.volume or 0,
                "delivery_qty": entry["delivery_qty"],
                "delivery_pct": entry["delivery_pct"],
                "delivery_20d_avg": None,
                "delivery_20d_zscore": None,
                "pe_ratio": entry["pe_ratio"],
                "pb_ratio": entry["pb_ratio"],
                "ev_ebitda": entry["ev_ebitda"],
                "pe_5yr_percentile": entry["pe_5yr_percentile"],
                "vendor_id": vendor_id,
                "vendor_as_of": fetched_at,
            })

        # Compute rolling 20d delivery average and zscore on CLOSE session rows
        for i, row in enumerate(close_rows):
            curr_deliv = row["delivery_pct"]
            if curr_deliv is not None:
                window = [
                    r["delivery_pct"]
                    for r in close_rows[max(0, i - 19) : i + 1]
                    if r["delivery_pct"] is not None
                ]
                if len(window) >= 5:
                    avg_val = sum(window) / len(window)
                    variance = sum((x - avg_val) ** 2 for x in window) / len(window)
                    std_val = math.sqrt(variance)
                    row["delivery_20d_avg"] = round(avg_val, 2)
                    row["delivery_20d_zscore"] = (
                        round((curr_deliv - avg_val) / std_val, 2) if std_val > 1e-4 else 0.0
                    )

        all_rows = open_rows + close_rows
        return await self._repo.upsert_daily_metrics(all_rows)

