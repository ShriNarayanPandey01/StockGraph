"""NSE Bhavcopy resilience (Issue 2 mitigation). Frozen fixtures, no network."""

import pytest

from src.config.settings import settings
from src.ingestion.source_adapter import (
    BHAVCOPY_VENDOR_ID,
    BSE_FALLBACK_VENDOR_ID,
    COLUMN_ALIASES,
    RETRYABLE_STATUS,
    ResilientHttpClient,
    ThrottledSession,
    parse_bhavcopy_csv,
    resolve_columns,
)

LEGACY_CSV = """SYMBOL,CLOSE_PRICE,DELIV_PER,TTL_TRD_QNTY
RELIANCE,1500.5,62.3,1000000
TATASTEEL,150.2,45.1,5000000
"""

# Jun-2026 circular renames: DELIV_PERC + humanised headers.
JUN2026_CSV = """Scrip Symbol,Close,DELIV_PERC,Total Traded Qty,Turnover (Lacs)
RELIANCE,1500.5,62.3,1000000,15000
TATASTEEL,150.2,45.1,5000000,7500
"""


def test_settings_default_to_bhavcopy_primary():
    assert settings.bhavcopy_primary is True
    assert BHAVCOPY_VENDOR_ID == "NSE_BHAVCOPY"


def test_legacy_bhavcopy_parses():
    out = parse_bhavcopy_csv(LEGACY_CSV)
    assert len(out.rows) == 2
    assert out.rows[0]["SYMBOL"] == "RELIANCE"
    assert out.rows[0]["DELIV_PER"] == "62.3"


def test_jun2026_renamed_columns_parse_without_crash():
    out = parse_bhavcopy_csv(JUN2026_CSV)
    assert len(out.rows) == 2
    assert out.rows[1]["SYMBOL"] == "TATASTEEL"
    # Renamed delivery column still resolves to canonical DELIV_PER.
    assert out.rows[1]["DELIV_PER"] == "45.1"
    assert out.rows[1]["CLOSE_PRICE"] == "150.2"


def test_missing_required_column_raises():
    with pytest.raises(ValueError, match="required columns"):
        parse_bhavcopy_csv("SYMBOL,VOLUME\nRELIANCE,10\n")


def test_resolve_columns_reports_unknowns_not_crash():
    mapping, unknown = resolve_columns(["SYMBOL", "CLOSE_PRICE", "SOME_FUTURE_COL"])
    assert mapping["SYMBOL"] == "SYMBOL"
    assert unknown == ["SOME_FUTURE_COL"]


def test_column_alias_registry_covers_jun2026_renames():
    assert "DELIV_PERC" in COLUMN_ALIASES["DELIV_PER"]
    assert "Close" in COLUMN_ALIASES["CLOSE_PRICE"]


def test_throttle_enforces_minimum_gap(monkeypatch):
    ticks = iter([100.0, 100.0, 100.0, 101.0])
    sleeps: list[float] = []
    monkeypatch.setattr("src.ingestion.source_adapter.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("src.ingestion.source_adapter.time.sleep", lambda s: sleeps.append(s))
    sess = ThrottledSession(requests_per_second=1.0)
    sess.wait()  # first call: gap huge → no sleep
    sess.wait()  # gap 0.0 < 1.0 → must sleep
    assert sleeps and sleeps[0] == pytest.approx(1.0)


def _no_throttle_client(fetcher, **kw):
    import random

    class _NoThrottle(ThrottledSession):
        def wait(self):
            pass

    return ResilientHttpClient(throttle=_NoThrottle(), fetcher=fetcher, rng=random.Random(0), **kw)


def test_retry_then_success_on_akamai_403(monkeypatch):
    monkeypatch.setattr(settings, "nse_max_retries", 3)
    calls: list[str] = []
    uas: list[str] = []

    def flaky(url, headers, timeout):
        calls.append(url)
        uas.append(headers["User-Agent"])
        return (403, "") if len(calls) == 1 else (200, "SYMBOL\nRELIANCE\n")

    monkeypatch.setattr("src.ingestion.source_adapter.time.sleep", lambda s: None)
    out = _no_throttle_client(flaky).fetch("https://example/bhav.csv")
    assert out.ok is True and out.status == 200 and out.attempts == 2
    assert len(set(uas)) >= 1  # UA header present (rotation pool of 3)


def test_exhausted_retries_signal_bse_fallback(monkeypatch):
    monkeypatch.setattr(settings, "nse_max_retries", 2)
    monkeypatch.setattr("src.ingestion.source_adapter.time.sleep", lambda s: None)
    out = _no_throttle_client(lambda u, h, t: (503, "")).fetch("https://example/bhav.csv")
    assert out.ok is False
    assert out.fallback_to == BSE_FALLBACK_VENDOR_ID == "BSE_FALLBACK"
    assert out.attempts == 3  # initial + 2 retries


def test_non_retryable_4xx_fails_fast(monkeypatch):
    monkeypatch.setattr(settings, "nse_max_retries", 3)
    calls: list[str] = []
    monkeypatch.setattr("src.ingestion.source_adapter.time.sleep", lambda s: None)

    def not_found(url, headers, timeout):
        calls.append(url)
        return (404, "")

    out = _no_throttle_client(not_found).fetch("https://example/bhav.csv")
    assert out.ok is False and len(calls) == 1  # no retry on 404
    assert 403 in RETRYABLE_STATUS and 429 in RETRYABLE_STATUS and 404 not in RETRYABLE_STATUS


def test_network_exception_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(settings, "nse_max_retries", 3)
    monkeypatch.setattr("src.ingestion.source_adapter.time.sleep", lambda s: None)
    state = {"n": 0}

    def flaky(url, headers, timeout):
        state["n"] += 1
        if state["n"] == 1:
            raise ConnectionResetError("reset by peer")
        return (200, "ok")

    out = _no_throttle_client(flaky).fetch("https://example/bhav.csv")
    assert out.ok is True and state["n"] == 2
