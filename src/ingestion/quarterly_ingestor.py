"""Quarterly official-results and guidance ingestion with temporal rotation."""

from __future__ import annotations

import hashlib
import inspect
import logging
from datetime import UTC, date, datetime
from typing import Any, Protocol

from src.ingestion.base import BaseIngestor, IngestionResult
from src.ingestion.periodic_macro_ingestor import _as_date, _as_datetime
from src.llm.chunking import chunk_guidance
from src.processors.entity_resolver import CanonicalEntityResolver
from src.processors.stock_profile_provider import StockProfileProvider

logger = logging.getLogger(__name__)


class QuarterlyOfficialSource(Protocol):
    """Normalized output from NSE/BSE XBRL and investor-document adapters."""

    async def fetch_quarterly_results(self, as_of: date) -> list[dict[str, Any]]: ...

    async def fetch_guidance_documents(self, as_of: date) -> list[dict[str, Any]]: ...


_FINANCIAL_FIELDS = (
    "revenue_cr", "rev_yoy_pct", "ebitda_cr", "ebitda_margin_pct", "pat_cr",
    "pat_yoy_pct", "debt_to_equity", "operating_cash_flow_cr", "free_cash_flow_cr",
    "order_book_cr", "promoter_holding_pct", "promoter_pledge_pct",
    "fii_holding_pct", "dii_holding_pct",
)
_SNAPSHOT_FIELD_MAP = {
    "rev_yoy_pct": "rev_yoy_pct",
    "ebitda_margin_pct": "ebitda_margin_pct",
    "pat_cr": "pat_cr",
    "debt_to_equity": "debt_to_equity",
    "free_cash_flow_cr": "fcf_cr",
    "promoter_pledge_pct": "promoter_pledge_pct",
    "order_book_cr": "order_book_cr",
}


class QuarterlyIngestor(BaseIngestor):
    """Ingest quarterly official records, graph context, RAG, then ontology."""

    def __init__(
        self,
        timescale_repo: Any,
        falkor_repo: Any,
        source: QuarterlyOfficialSource | None = None,
        embedding_provider: Any | None = None,
        ontology_builder: Any | None = None,
        resolver: CanonicalEntityResolver | None = None,
        redis_client: Any | None = None,
    ) -> None:
        self._timescale = timescale_repo
        self._falkor = falkor_repo
        self._source = source
        self._embedder = embedding_provider
        self._ontology_builder = ontology_builder
        self._resolver = resolver or CanonicalEntityResolver.from_seed()
        self._redis = redis_client
        self._profiles = StockProfileProvider(repo=falkor_repo)

    async def run(
        self,
        as_of: date | None = None,
        result_records: list[dict[str, Any]] | None = None,
        guidance_documents: list[dict[str, Any]] | None = None,
    ) -> IngestionResult:
        """Run one replay-safe quarterly batch under the quarterly lock."""
        as_of = as_of or datetime.now(UTC).date()
        if not self._acquire_lock("quarterly", 7200):
            return IngestionResult(status="SKIPPED", error="Lock busy (single-flight guard)")
        run_id: int | None = None
        try:
            run_id = await self._timescale.record_ingest_run("quarterly", "RUNNING")
            if result_records is None:
                result_records = await self._fetch("fetch_quarterly_results", as_of)
            if guidance_documents is None:
                guidance_documents = await self._fetch("fetch_guidance_documents", as_of)

            financial = await self.ingest_financial_results(result_records, as_of)
            guidance = await self.ingest_guidance_documents(guidance_documents, as_of)
            ontology_writes, ontology_errors = self._refresh_ontology(financial.details.get("refreshed", {}))
            status = "PARTIAL" if guidance.details.get("embedding_failures") or ontology_errors else "COMPLETED"
            await self._timescale.update_ingest_run(run_id, status)
            return IngestionResult(
                status=status,
                records_seen=financial.records_seen + guidance.records_seen,
                records_persisted=financial.records_persisted + guidance.records_persisted,
                graph_writes=financial.graph_writes + guidance.graph_writes + ontology_writes,
                skipped=financial.skipped + guidance.skipped,
                details={
                    "financial": financial.details,
                    "guidance": guidance.details,
                    "ontology_writes": ontology_writes,
                    "ontology_errors": ontology_errors,
                },
            )
        except Exception as exc:
            logger.exception("Quarterly ingestion failed")
            if run_id is not None:
                await self._timescale.update_ingest_run(run_id, "FAILED", error=str(exc))
            return IngestionResult(status="FAILED", error=str(exc))
        finally:
            self._release_lock("quarterly")

    async def ingest_financial_results(
        self, records: list[dict[str, Any]] | None = None, as_of: date | None = None
    ) -> IngestionResult:
        as_of = as_of or datetime.now(UTC).date()
        persisted = graph_writes = skipped = 0
        refreshed: dict[str, int] = {}
        for record in records or []:
            ticker = self._resolver.resolve_stock(str(record.get("ticker") or record.get("stock") or ""))
            quarter = str(record.get("quarter_label") or record.get("quarter") or "").upper().strip()
            if ticker is None or not quarter:
                skipped += 1
                continue
            try:
                published_at = _as_datetime(record.get("published_at"), as_of)
                valid_from_ts = int(published_at.timestamp())
                published_date = _as_date(record.get("published_date") or published_at, as_of)
            except (TypeError, ValueError):
                skipped += 1
                continue
            row: dict[str, Any] = {
                "ticker": ticker,
                "quarter_label": quarter,
                "published_date": published_date,
                "valid_from_ts": valid_from_ts,
                "source_id": record.get("source_id", "OFFICIAL_FILING"),
                "source_as_of": _as_datetime(record.get("source_as_of"), as_of),
            }
            try:
                for field in _FINANCIAL_FIELDS:
                    value = record.get(field)
                    row[field] = float(value) if value is not None else None
            except (TypeError, ValueError):
                skipped += 1
                continue

            inserted = await self._timescale.insert_quarterly_financials(row)
            if inserted:
                persisted += 1
            snapshot_id = f"qtr:{ticker}:{quarter}:{valid_from_ts}"
            snapshot_props = {
                "id": snapshot_id,
                "quarter": quarter,
                "published_date": published_date.isoformat(),
                "source_id": row["source_id"],
                **{snapshot_key: row[financial_key] for financial_key, snapshot_key in _SNAPSHOT_FIELD_MAP.items()},
            }
            snapshot_exists = getattr(self._falkor, "has_quarterly_snapshot", None)
            exists = bool(snapshot_exists(snapshot_id)) if callable(snapshot_exists) else not inserted
            if not exists:
                rotation = self._falkor.rotate_validity_interval_node(
                    ticker, valid_from_ts, snapshot_props
                )
                if rotation.get("new_id"):
                    graph_writes += 1
            refreshed[ticker] = valid_from_ts
        return IngestionResult(
            status="COMPLETED", records_seen=len(records or []), records_persisted=persisted,
            graph_writes=graph_writes, skipped=skipped, details={"refreshed": refreshed},
        )

    async def ingest_guidance_documents(
        self, documents: list[dict[str, Any]] | None = None, as_of: date | None = None
    ) -> IngestionResult:
        as_of = as_of or datetime.now(UTC).date()
        persisted = graph_writes = skipped = embedding_failures = 0
        for document in documents or []:
            ticker = self._resolver.resolve_stock(str(document.get("ticker") or document.get("stock") or ""))
            quarter = str(document.get("quarter_label") or document.get("quarter") or "").upper().strip()
            text = str(document.get("text") or document.get("content") or "").strip()
            if ticker is None or not quarter or not text:
                skipped += 1
                continue
            try:
                published_at = _as_datetime(document.get("published_at"), as_of)
                valid_from_ts = int(published_at.timestamp())
            except (TypeError, ValueError):
                skipped += 1
                continue
            source_document_id = str(document.get("source_document_id") or document.get("source_url") or "")
            digest = hashlib.sha1(f"{ticker}|{quarter}|{published_at.isoformat()}|{source_document_id}|{text}".encode()).hexdigest()
            guidance_set_id = f"guidance:{ticker}:{quarter}:{valid_from_ts}:{digest[:16]}"
            chunks = chunk_guidance(guidance_set_id, text)
            if not chunks:
                skipped += 1
                continue
            embeddings: list[list[float] | None] = [None] * len(chunks)
            if self._embedder is not None:
                for index, chunk in enumerate(chunks):
                    try:
                        embeddings[index] = self._embedder.embed_one(chunk.text)
                    except Exception as exc:
                        logger.warning("Guidance embedding failed for %s: %s", chunk.id, exc)
                        embedding_failures += 1
            summary = str(document.get("concall_summary") or document.get("summary") or text[:900])
            chunk_props: list[dict[str, Any]] = []
            for chunk, embedding in zip(chunks, embeddings):
                chunk_props.append(
                    {
                        "id": chunk.id,
                        "quarter": quarter,
                        "chunk_index": chunk.index,
                        "text": chunk.text,
                        "concall_summary": summary,
                        "source_document_id": source_document_id or digest,
                        "source_url": document.get("source_url"),
                        "order_book_cr": document.get("order_book_cr"),
                        "embedding": embedding,
                    }
                )
            written = self._falkor.replace_guidance_chunks(
                ticker, guidance_set_id, valid_from_ts, chunk_props
            )
            persisted += len(chunks) if written else 0
            graph_writes += written
        return IngestionResult(
            status="PARTIAL" if embedding_failures else "COMPLETED",
            records_seen=len(documents or []), records_persisted=persisted,
            graph_writes=graph_writes, skipped=skipped,
            details={"embedding_failures": embedding_failures},
        )

    def _refresh_ontology(self, refreshed: dict[str, int]) -> tuple[int, list[str]]:
        if self._ontology_builder is None:
            return 0, []
        written = 0
        errors: list[str] = []
        for ticker, valid_from_ts in refreshed.items():
            try:
                card = self._profiles.build_context_card(ticker)
                edges = self._ontology_builder.infer_edges(card, now_ts=valid_from_ts)
                written += self._falkor.rotate_dynamic_ontology_edges(ticker, edges, valid_from_ts)
            except Exception as exc:
                logger.warning("Ontology refresh failed for %s: %s", ticker, exc)
                errors.append(ticker)
        return written, errors

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
