"""Quantitative Anomaly Detector (Rule 2: SQL-only, zero graph writes).

Quant anomalies are SQL-only computed queries on the CLOSE session:
  WHERE session_type = 'CLOSE' AND abs(delivery_20d_zscore) >= 1.8
Over the resolved temporal window (LAST_6M | LAST_1Y).

No graph nodes or edges are ever created for anomalies.
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from src.domain.enums import MarketSession, Window
from src.repositories.timescale_repo import TimescaleRepository

logger = logging.getLogger(__name__)

DEFAULT_DELIVERY_ZSCORE_THRESHOLD = 1.8


class DeliveryAnomaly(BaseModel):
    """One delivery percentage z-score anomaly row."""

    trade_date: str
    session_type: str = MarketSession.CLOSE.value
    delivery_pct: float | None = None
    delivery_20d_zscore: float | None = None
    pe_ratio: float | None = None
    pe_5yr_percentile: float | None = None


def compute_rolling_zscores(
    series: list[float], window_size: int = 20
) -> list[float | None]:
    """Compute rolling z-scores over a floating-point sequence (pure helper)."""
    out: list[float | None] = []
    for i, val in enumerate(series):
        window = series[max(0, i - window_size + 1) : i + 1]
        if len(window) < 5:
            out.append(None)
            continue
        mean = sum(window) / len(window)
        var = sum((x - mean) ** 2 for x in window) / len(window)
        std = math.sqrt(var)
        if std <= 1e-6:
            out.append(0.0)
        else:
            out.append(round((val - mean) / std, 2))
    return out


class AnomalyDetector:
    """Thin SQL-only wrapper over TimescaleRepository.get_anomalies (Rule 2)."""

    def __init__(self, timescale_repo: Any) -> None:
        self._timescale = timescale_repo

    async def get_delivery_anomalies(
        self,
        ticker: str,
        window: Window,
        threshold: float = DEFAULT_DELIVERY_ZSCORE_THRESHOLD,
    ) -> list[DeliveryAnomaly]:
        """Fetch delivery percentage anomalies for a stock over a fixed window.

        Enforces:
        - window resolution (LAST_6M or LAST_1Y)
        - session_type = 'CLOSE'
        - ABS(delivery_20d_zscore) >= threshold
        """
        start_date, end_date = TimescaleRepository.window_dates(window)
        records = await self._timescale.get_anomalies(
            ticker=ticker.upper(),
            start=start_date,
            end=end_date,
            threshold=threshold,
        )

        anomalies: list[DeliveryAnomaly] = []
        for r in records or []:
            td = r.get("trade_date") if isinstance(r, dict) else getattr(r, "trade_date", None)
            td_str = td.isoformat() if hasattr(td, "isoformat") else str(td or "")
            session = r.get("session_type") if isinstance(r, dict) else getattr(r, "session_type", None)
            # Guarantee CLOSE session invariant
            if session and session != MarketSession.CLOSE.value:
                continue

            def _flt(key: str) -> float | None:
                val = r.get(key) if isinstance(r, dict) else getattr(r, key, None)
                try:
                    return float(val) if val is not None else None
                except (TypeError, ValueError):
                    return None

            anomalies.append(
                DeliveryAnomaly(
                    trade_date=td_str,
                    session_type=MarketSession.CLOSE.value,
                    delivery_pct=_flt("delivery_pct"),
                    delivery_20d_zscore=_flt("delivery_20d_zscore"),
                    pe_ratio=_flt("pe_ratio"),
                    pe_5yr_percentile=_flt("pe_5yr_percentile"),
                )
            )

        return anomalies
