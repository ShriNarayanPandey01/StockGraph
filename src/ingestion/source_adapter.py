"""NSE Bhavcopy source adapter (Issue 2 mitigation).

Priority chain (Rule 7 extension): `NSE_BHAVCOPY` (official
`sec_bhavdata_full.csv`, primary source of truth for Delivery %) >
`BSE_FALLBACK` > `ChartProviderAdapter` vendor (e.g. Upstox). The dossier
never fails on a single-source outage — sources degrade in priority order.

Hardening vs. Jun-2026 circular + Akamai/ToS reality:
1. Throttled session with rotating User-Agents and retries+backoff
   (`ResilientHttpClient`: `nse_max_retries`, `nse_backoff_base_seconds`) —
   Akamai 403s/429s/5xx are retried with exponential backoff, then surfaced
   as retryable `ingest_runs` errors with a BSE/vendor fallback signal.
2. Versioned column-alias parser (`COLUMN_ALIASES`): the Jun-2026 circular
   renamed `DELIV_PER` variants; unknown columns are logged as SCHEMA_DRIFT,
   never crash the sync.
3. Raw payloads stage immutably into `vendor_quotes_raw` with
   `vendor_id='NSE_BHAVCOPY'` — revisions arrive as new vintages (Rule 7).

Milestone 1 scope: parser + adapter interfaces with frozen CSV fixtures.
Live HTTP wiring lands in Milestone 4 (`daily_eod_ingestor`).
"""

from __future__ import annotations

import csv
import io
import logging
import random
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.config.settings import settings

logger = logging.getLogger(__name__)

BHAVCOPY_VENDOR_ID = "NSE_BHAVCOPY"
BSE_FALLBACK_VENDOR_ID = "BSE_FALLBACK"

# Rotated per attempt so Akamai bot rules cannot key on a single UA string.
USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockGraph/0.1 (+research; contact: ops)",
    "Mozilla/5.0 (X11; Linux x86_64) StockGraph/0.1 (+research; contact: ops)",
    "StockGraph/0.1 (compatible; NSE-Bhavcopy-Sync; +research)",
)

# Retried with backoff; anything else (4xx other than 403/429) fails fast.
RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}

# Jun-2026 circular renamed several delivery/turnover columns. Canonical key
# first, known aliases after. Unknown-but-present columns are ignored with a
# SCHEMA_DRIFT log — the sync must never crash on a rename.
COLUMN_ALIASES: dict[str, list[str]] = {
    "SYMBOL": ["SYMBOL", "Scrip Symbol", "SCRIP"],
    "CLOSE_PRICE": ["CLOSE_PRICE", "Close Price", "CLOSE", "Close"],
    "DELIV_PER": ["DELIV_PER", "DELIV_PERC", "Delivery %", "DELIV_PCT", "DeliveryPercent"],
    "TTL_TRD_QNTY": ["TTL_TRD_QNTY", "Total Traded Qty", "VOLUME", "TotalTradedQuantity"],
    "DELIV_QTY": ["DELIV_QTY", "Delivery Qty", "DELIV_QTY_NEW"],
    "TURNOVER_LACS": ["TURNOVER_LACS", "Turnover (Lacs)", "TURNOVER"],
}

REQUIRED_COLUMNS = ("SYMBOL", "CLOSE_PRICE")


@dataclass
class BhavcopyParseResult:
    rows: list[dict[str, Any]]
    unknown_columns: list[str] = field(default_factory=list)
    schema_version: str = "v2026_06"


def resolve_columns(header: list[str]) -> tuple[dict[str, str], list[str]]:
    """Map canonical keys → actual CSV header names; report unknowns."""
    norm = {h.strip(): h for h in header}
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in norm:
                mapping[canonical] = norm[alias]
                used.add(norm[alias])
                break
    unknown = [h for h in header if h not in used]
    return mapping, unknown


def parse_bhavcopy_csv(text: str) -> BhavcopyParseResult:
    """Parse `sec_bhavdata_full.csv` text with alias-tolerant columns.

    Raises `ValueError` only when a REQUIRED column is absent (genuine
    breakage); extra/renamed optional columns degrade to SCHEMA_DRIFT.
    """
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("Bhavcopy CSV has no header row")
    mapping, unknown = resolve_columns(reader.fieldnames)
    missing = [c for c in REQUIRED_COLUMNS if c not in mapping]
    if missing:
        raise ValueError(f"Bhavcopy missing required columns {missing}; header={reader.fieldnames}")
    rows = []
    for raw in reader:
        row = {canon: raw.get(actual) for canon, actual in mapping.items()}
        if row.get("SYMBOL"):
            rows.append(row)
    return BhavcopyParseResult(rows=rows, unknown_columns=unknown)


class ThrottledSession:
    """Minimal rate-limiter for NSE/BSE HTTP (ToS/Akamai respect)."""

    def __init__(self, requests_per_second: float | None = None) -> None:
        self._interval = 1.0 / (requests_per_second or settings.nse_requests_per_second)
        self._last: float = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        gap = now - self._last
        if gap < self._interval:
            time.sleep(self._interval - gap)
        self._last = time.monotonic()


@dataclass
class FetchOutcome:
    ok: bool
    status: int | None = None
    text: str | None = None
    attempts: int = 0
    fallback_to: str | None = None  # BSE_FALLBACK / vendor when NSE fails
    error: str | None = None


class ResilientHttpClient:
    """Throttled + UA-rotated + backoff HTTP for Akamai-gated NSE endpoints.

    stdlib-only (`urllib`) so no new dependency is needed in Milestone 1.
    A `fetcher` callable may be injected for unit tests
    (`(url, headers, timeout) -> (status, text)`); default performs live HTTP.
    Non-retryable 4xx fails fast; retryable 403/429/5xx exhaust retries then
    return `ok=False` with `fallback_to=BSE_FALLBACK` so the scheduler can
    degrade instead of failing the dossier.
    """

    def __init__(
        self,
        throttle: ThrottledSession | None = None,
        fetcher: Callable[[str, dict[str, str], int], tuple[int, str]] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._throttle = throttle or ThrottledSession()
        self._fetcher = fetcher or self._live_fetch
        self._rng = rng or random.Random()

    @staticmethod
    def _live_fetch(url: str, headers: dict[str, str], timeout: int) -> tuple[int, str]:
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return exc.code or 0, ""

    def _backoff(self, attempt: int) -> float:
        base = settings.nse_backoff_base_seconds
        return base * (2.0**attempt) + self._rng.uniform(0, base)

    def fetch(self, url: str) -> FetchOutcome:
        attempts = 0
        last_error: str | None = None
        last_status: int | None = None
        while attempts <= settings.nse_max_retries:
            self._throttle.wait()
            headers = {"User-Agent": self._rng.choice(USER_AGENTS)}
            try:
                status, text = self._fetcher(url, headers, settings.nse_timeout_seconds)
            except Exception as exc:  # network-level (DNS/TLS/reset) → retryable
                last_error = f"{type(exc).__name__}: {exc}"
                attempts += 1
                if attempts <= settings.nse_max_retries:
                    time.sleep(self._backoff(attempts))
                continue
            last_status = status
            if status == 200:
                return FetchOutcome(ok=True, status=status, text=text, attempts=attempts + 1)
            if status in RETRYABLE_STATUS and attempts < settings.nse_max_retries:
                last_error = f"HTTP {status} (retryable)"
                logger.warning("NSE fetch %s -> %s; retry %d", url, status, attempts + 1)
                time.sleep(self._backoff(attempts))
                attempts += 1
                continue
            last_error = f"HTTP {status}"
            break
        logger.error("NSE fetch failed %s: %s — falling back", url, last_error)
        return FetchOutcome(
            ok=False,
            status=last_status,
            attempts=attempts + 1,
            fallback_to=BSE_FALLBACK_VENDOR_ID,
            error=last_error,
        )
