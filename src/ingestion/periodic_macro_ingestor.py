"""Monthly and bi-monthly official macro / mutual-fund ingestion.

Live agency and exchange clients are intentionally adapters: this module owns
canonical resolution, temporal state changes, locking, and persistence.  A
caller may inject fixture records in tests or an official AMFI/MoSPI/RBI
adapter in production without changing any graph or SQL write rules.
"""

from __future__ import annotations

import inspect
import logging
from datetime import UTC, date, datetime, time
from typing import Any, Protocol

from src.ingestion.base import BasePeriodicMacroIngestor, IngestionResult
from src.processors.entity_resolver import CanonicalEntityResolver
from src.processors.news_dedup import build_news_props

logger = logging.getLogger(__name__)


class PeriodicOfficialSource(Protocol):
    """Normalized records from official AMFI/MoSPI/RBI/exchange adapters."""

    async def fetch_macro_indicators(self, as_of: date) -> list[dict[str, Any]]: ...

    async def fetch_mf_holdings(self, as_of: date) -> list[dict[str, Any]]: ...

    async def fetch_sector_updates(self, as_of: date) -> list[dict[str, Any]]: ...


def _as_date(value: Any, fallback: date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    return fallback


def _as_datetime(value: Any, fallback: date) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.combine(fallback, time.min, tzinfo=UTC)


class PeriodicMacroIngestor(BasePeriodicMacroIngestor):
    """Single-flight monthly/bimonthly pipeline for official periodic data."""

    def __init__(
        self,
        timescale_repo: Any,
        falkor_repo: Any,
        source: PeriodicOfficialSource | None = None,
        stream_ingestor: Any | None = None,
        resolver: CanonicalEntityResolver | None = None,
        redis_client: Any | None = None,
    ) -> None:
        self._timescale = timescale_repo
        self._falkor = falkor_repo
        self._source = source
        self._stream_ingestor = stream_ingestor
        self._resolver = resolver or CanonicalEntityResolver.from_seed()
        self._redis = redis_client

    async def run(
        self,
        as_of: date | None = None,
        macro_records: list[dict[str, Any]] | None = None,
        mf_records: list[dict[str, Any]] | None = None,
        sector_updates: list[dict[str, Any]] | None = None,
    ) -> IngestionResult:
        """Ingest one bounded official-release batch under a distributed lock."""
        as_of = as_of or datetime.now(UTC).date()
        if not self._acquire_lock("periodic_macro", 3600):
            return IngestionResult(status="SKIPPED", error="Lock busy (single-flight guard)")

        run_id: int | None = None
        try:
            run_id = await self._timescale.record_ingest_run("periodic_macro", "RUNNING")
            if macro_records is None:
                macro_records = await self._fetch("fetch_macro_indicators", as_of)
            if mf_records is None:
                mf_records = await self._fetch("fetch_mf_holdings", as_of)
            if sector_updates is None:
                sector_updates = await self._fetch("fetch_sector_updates", as_of)

            macro = await self.ingest_macro_indicators(macro_records, as_of)
            holdings = await self.ingest_mf_holdings(mf_records, as_of)
            macro_news_writes = await self._ingest_macro_release_news(macro_records, as_of)
            news_writes = await self._ingest_sector_updates(sector_updates)
            status = "PARTIAL" if "FAILED" in (macro.status, holdings.status) else "COMPLETED"
            await self._timescale.update_ingest_run(run_id, status)
            return IngestionResult(
                status=status,
                records_seen=macro.records_seen + holdings.records_seen + len(sector_updates),
                records_persisted=macro.records_persisted + holdings.records_persisted,
                graph_writes=holdings.graph_writes + macro_news_writes + news_writes,
                skipped=macro.skipped + holdings.skipped,
                details={"macro": macro.details, "mf": holdings.details, "sector_articles": len(sector_updates)},
            )
        except Exception as exc:
            logger.exception("Periodic macro ingestion failed")
            if run_id is not None:
                await self._timescale.update_ingest_run(run_id, "FAILED", error=str(exc))
            return IngestionResult(status="FAILED", error=str(exc))
        finally:
            self._release_lock("periodic_macro")

    async def ingest_macro_indicators(
        self, records: list[dict[str, Any]] | None = None, as_of: date | None = None
    ) -> IngestionResult:
        as_of = as_of or datetime.now(UTC).date()
        normalized: list[dict[str, Any]] = []
        skipped = 0
        for record in records or []:
            raw_id = str(record.get("macro_id") or record.get("id") or "")
            resolved = self._resolver.resolve_registry(raw_id)
            if resolved is None or resolved.kind != "macro" or record.get("value") is None:
                skipped += 1
                continue
            try:
                value = float(record["value"])
                observation_date = _as_date(record.get("observation_date"), as_of)
                published_at = _as_datetime(record.get("published_at"), as_of)
            except (TypeError, ValueError):
                skipped += 1
                continue
            normalized.append(
                {
                    "macro_id": resolved.id,
                    "observation_date": observation_date,
                    "published_at": published_at,
                    "valid_from_ts": int(published_at.timestamp()),
                    "value": value,
                    "unit": record.get("unit"),
                    "source_id": record.get("source_id", "OFFICIAL_RELEASE"),
                    "source_as_of": _as_datetime(record.get("source_as_of"), as_of),
                    "payload": record.get("payload", record),
                }
            )
        written = await self._timescale.append_macro_observations(normalized)
        return IngestionResult(
            status="COMPLETED", records_seen=len(records or []), records_persisted=written,
            skipped=skipped, details={"macro_ids": sorted({item['macro_id'] for item in normalized})},
        )

    async def ingest_mf_holdings(
        self, records: list[dict[str, Any]] | None = None, as_of: date | None = None
    ) -> IngestionResult:
        as_of = as_of or datetime.now(UTC).date()
        persisted = graph_writes = skipped = 0
        for record in records or []:
            ticker = self._resolver.resolve_stock(str(record.get("ticker") or record.get("stock") or ""))
            amc_id = str(record.get("amc_id") or "").strip()
            amc_name = str(record.get("amc_name") or record.get("amc") or "").strip()
            if ticker is None or not amc_id or not amc_name:
                skipped += 1
                continue
            try:
                month = _as_date(record.get("month"), as_of).replace(day=1)
                published_at = _as_datetime(record.get("published_at"), as_of)
                props = {
                    "month": month,
                    "ticker": ticker,
                    "amc_id": amc_id,
                    "amc_name": amc_name,
                    "shares_held": record.get("shares_held"),
                    "stake_pct": record.get("stake_pct"),
                    "delta_stake_pct": record.get("delta_stake_pct"),
                    "valid_from_ts": int(published_at.timestamp()),
                }
            except (TypeError, ValueError):
                skipped += 1
                continue
            inserted = await self._timescale.rotate_mf_holding(props)
            if inserted:
                persisted += 1
            # The graph call is idempotent and is deliberately attempted even
            # after a SQL replay, healing a previous cross-store partial run.
            if self._falkor.rotate_mf_holding(ticker, props):
                graph_writes += 1
        return IngestionResult(
            status="COMPLETED", records_seen=len(records or []), records_persisted=persisted,
            graph_writes=graph_writes, skipped=skipped,
        )

    async def _ingest_sector_updates(self, updates: list[dict[str, Any]]) -> int:
        if not updates or self._stream_ingestor is None:
            return 0
        prepared = [{**update, "category": update.get("category", "SECTOR_UPDATE")} for update in updates]
        stats = await self._stream_ingestor.ingest_articles(prepared)
        return int(getattr(stats, "canonical_created", 0))

    async def _ingest_macro_release_news(
        self, records: list[dict[str, Any]], as_of: date
    ) -> int:
        """Route narrative official releases and assert their known macro link."""
        if self._stream_ingestor is None:
            return 0
        articles: list[dict[str, Any]] = []
        macro_links: list[tuple[str, str]] = []
        for record in records:
            headline = str(record.get("headline") or "").strip()
            resolved = self._resolver.resolve_registry(str(record.get("macro_id") or record.get("id") or ""))
            if not headline or resolved is None or resolved.kind != "macro":
                continue
            published_at = _as_datetime(record.get("published_at"), as_of)
            event_date = published_at.date().isoformat()
            article = {
                "headline": headline,
                "summary": record.get("summary", ""),
                "source_url": record.get("source_url", ""),
                "source": record.get("source_id", "OFFICIAL_RELEASE"),
                "event_date": event_date,
                "event_ts": int(published_at.timestamp()),
                "category": "MACRO",
                "primary_entity": resolved.id,
            }
            articles.append(article)
            news_id = build_news_props(
                headline=headline,
                primary_entity=resolved.id,
                event_date=event_date,
                event_ts=article["event_ts"],
                summary=str(article["summary"]),
                source=str(article["source"]),
                source_url=str(article["source_url"]),
                category="MACRO",
            )["id"]
            macro_links.append((news_id, resolved.id))
        if not articles:
            return 0
        stats = await self._stream_ingestor.ingest_articles(articles)
        writes = int(getattr(stats, "canonical_created", 0))
        for news_id, macro_id in macro_links:
            self._falkor.merge_news_shock(
                news_id=news_id,
                target_kind="macro",
                target_id=macro_id,
                confidence=1.0,
                rationale="Official macro release",
                inferred_by="official_periodic_release",
            )
            writes += 1
        return writes

    async def _fetch(self, method_name: str, as_of: date) -> list[dict[str, Any]]:
        if self._source is None:
            return []
        method = getattr(self._source, method_name, None)
        if method is None:
            return []
        value = method(as_of)
        return await value if inspect.isawaitable(value) else value

    def _acquire_lock(self, name: str, lease_seconds: int) -> bool:
        if self._redis is None:
            return True
        try:
            return bool(self._redis.set(f"lock:{name}", "1", nx=True, ex=lease_seconds))
        except Exception as exc:
            logger.warning("Redis lock error for %s: %s; failing open", name, exc)
            return True

    def _release_lock(self, name: str) -> None:
        if self._redis is None:
            return
        try:
            self._redis.delete(f"lock:{name}")
        except Exception:
            pass
