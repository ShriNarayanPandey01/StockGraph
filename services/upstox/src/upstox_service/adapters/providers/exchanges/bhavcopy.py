"""NSE Bhavcopy source adapter (Issue 2 mitigation).

Priority chain (Rule 7 extension): `NSE_BHAVCOPY` (official
`sec_bhavdata_full.csv`, primary source of truth for Delivery %) >
`BSE_FALLBACK` > `ChartProviderAdapter` vendor (e.g. Upstox). The dossier
never fails on a single-source outage - sources degrade in priority order.

Hardening vs. Jun-2026 circular + Akamai/ToS reality:
1. Throttled session with rotating User-Agents and retries+backoff
   (`ResilientHttpClient`: `nse_max_retries`, `nse_backoff_base_seconds`) -
   Akamai 403s/429s/5xx are retried with exponential backoff, then surfaced
   as retryable `ingest_runs` errors with a BSE/vendor fallback signal.
2. Versioned column-alias parser (`COLUMN_ALIASES`): the Jun-2026 circular
   renamed `DELIV_PER` variants; unknown columns are logged as SCHEMA_DRIFT,
   never crash the sync.
3. Raw payloads stage immutably into `vendor_quotes_raw` with
   `vendor_id='NSE_BHAVCOPY'` - revisions arrive as new vintages (Rule 7).

The generic HTTP transport lives in `upstox_service.adapters.providers.http_client`
(shared with the news providers) and is re-exported here, so existing
imports of `ResilientHttpClient` / `ThrottledSession` keep working.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from typing import Any

from upstox_service.adapters.providers.http_client import (
    RETRYABLE_STATUS,
    USER_AGENTS,
    FetchOutcome,
    ResilientHttpClient,
    ThrottledSession,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BHAVCOPY_VENDOR_ID",
    "BSE_FALLBACK_VENDOR_ID",
    "COLUMN_ALIASES",
    "RETRYABLE_STATUS",
    "USER_AGENTS",
    "FetchOutcome",
    "ResilientHttpClient",
    "ThrottledSession",
    "parse_bhavcopy_csv",
    "resolve_columns",
]

BHAVCOPY_VENDOR_ID = "NSE_BHAVCOPY"
BSE_FALLBACK_VENDOR_ID = "BSE_FALLBACK"

# Jun-2026 circular renamed several delivery/turnover columns. Canonical key
# first, known aliases after. Unknown-but-present columns are ignored with a
# SCHEMA_DRIFT log â€” the sync must never crash on a rename.
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
    """Map canonical keys â†’ actual CSV header names; report unknowns."""
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
