"""Test SQL-only quantitative anomaly detection (Rule 2)."""

import pytest
from datetime import date
from src.domain.enums import Window
from src.processors.anomaly_detector import AnomalyDetector, compute_rolling_zscores


class _FakeTimescaleRepo:
    def __init__(self, records=None):
        self.records = records or []
        self.called_with = None

    async def get_anomalies(self, ticker: str, start: date, end: date, threshold: float = 1.8):
        self.called_with = (ticker, start, end, threshold)
        return [
            r for r in self.records
            if abs(r.get("delivery_20d_zscore", 0.0)) >= threshold
        ]


def test_rolling_zscore_calculation():
    # Constant series has 0 std -> zscore 0.0
    series = [50.0] * 20
    scores = compute_rolling_zscores(series)
    assert scores[-1] == 0.0

    # Sudden spike
    spike_series = [50.0] * 19 + [90.0]
    scores_spike = compute_rolling_zscores(spike_series)
    assert scores_spike[-1] is not None
    assert scores_spike[-1] > 2.0  # Clear positive spike


@pytest.mark.asyncio
async def test_anomaly_detector_queries_timescale_only():
    mock_records = [
        {
            "trade_date": date(2026, 10, 10),
            "session_type": "CLOSE",
            "delivery_pct": 82.5,
            "delivery_20d_zscore": 2.45,
            "pe_ratio": 24.5,
            "pe_5yr_percentile": 85.0,
        },
        {
            "trade_date": date(2026, 10, 11),
            "session_type": "OPEN",  # Must be dropped!
            "delivery_pct": 80.0,
            "delivery_20d_zscore": 2.10,
            "pe_ratio": 24.0,
            "pe_5yr_percentile": 84.0,
        },
        {
            "trade_date": date(2026, 10, 12),
            "session_type": "CLOSE",
            "delivery_pct": 52.0,
            "delivery_20d_zscore": 0.50,  # Below threshold!
            "pe_ratio": 23.8,
            "pe_5yr_percentile": 80.0,
        },
    ]

    repo = _FakeTimescaleRepo(mock_records)
    detector = AnomalyDetector(repo)

    anomalies = await detector.get_delivery_anomalies("TATASTEEL", Window.LAST_6M, threshold=1.8)

    assert len(anomalies) == 1
    hit = anomalies[0]
    assert hit.trade_date == "2026-10-10"
    assert hit.session_type == "CLOSE"
    assert hit.delivery_20d_zscore == 2.45
    assert hit.delivery_pct == 82.5

    assert repo.called_with[0] == "TATASTEEL"
    assert repo.called_with[3] == 1.8
