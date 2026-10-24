"""Composes instrument, company-profile, statements and daily checkpoint reads."""

from datetime import UTC, datetime
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

from upstox_service.adapters.providers.upstox.client import ProviderError, UpstoxClient
from upstox_service.application.financial_context import (
    narrative_quarter_context,
    normalize_statements,
)
from upstox_service.domain.models import CompanyBundle, StockRegistration


class UpstoxCompanyProvider:
    def __init__(self, client: UpstoxClient):
        self._client = client

    async def resolve(self, query: str, exchange: str = "NSE") -> dict:
        body = await self._client.get(
            "/instruments/search",
            {"query": query, "exchanges": exchange, "segments": "EQ", "records": 30},
        )
        rows = [
            row
            for row in body.get("data", [])
            if row.get("segment") == f"{exchange}_EQ"
            and row.get("isin")
            and row.get("instrument_key")
        ]
        exact = [
            r
            for r in rows
            if query.strip().casefold()
            in {
                str(r.get(k, "")).casefold()
                for k in ("trading_symbol", "name", "isin", "short_name")
            }
        ]
        if len(exact) == 1:
            return exact[0]
        pages = body.get("meta_data", {}).get("page", {}).get("total_pages", 1)
        if len(rows) == 1 and pages == 1:
            return rows[0]
        if not rows:
            raise ProviderError("No official equity instrument matched the requested stock")
        raise ProviderError("Ambiguous stock name; submit an exact symbol or ISIN")

    async def fetch_prospectus_links(self, isin: str) -> list[dict[str, str]]:
        """Return Upstox-supplied DRHP/RHP URLs for a current/recent IPO.

        The company-fundamentals profile API deliberately contains no IPO
        documents.  Upstox documents the URLs on ``GET /ipos/{id}``, so first
        resolve a listing by ISIN and then read its detail record.  IPO data is
        supplementary to the stock profile: an unavailable IPO feed must not
        prevent normal company registration or profile reads.
        """
        ipo_id: str | None = None
        # The listing endpoint defaults to open IPOs and supports the four
        # documented lifecycle states.  One page (30 newest items) keeps a
        # normal stock-profile refresh bounded while covering the IPOs for
        # which prospectus links are actionable.
        for status in ("upcoming", "open", "closed", "listed"):
            try:
                listing = await self._client.get(
                    "/ipos", {"status": status, "page_number": 1, "records": 30}
                )
            except ProviderError:
                continue
            rows = listing.get("data")
            if not isinstance(rows, list):
                continue
            match = next(
                (
                    row
                    for row in rows
                    if isinstance(row, dict)
                    and str(row.get("isin", "")).upper() == isin.upper()
                    and isinstance(row.get("id"), str)
                    and row["id"].strip()
                ),
                None,
            )
            if match is not None:
                ipo_id = match["id"].strip()
                break
        if ipo_id is None:
            return []
        try:
            detail_response = await self._client.get(f"/ipos/{quote(ipo_id, safe='')}")
        except ProviderError:
            return []
        detail = detail_response.get("data")
        if not isinstance(detail, dict) or str(detail.get("isin", "")).upper() != isin.upper():
            return []

        links: list[dict[str, str]] = []
        for document_type, field in (("DRHP", "drhp_url"), ("RHP", "rhp_url")):
            url = detail.get(field)
            url = url.strip() if isinstance(url, str) else ""
            parsed = urlparse(url) if url else None
            if parsed and parsed.scheme in {"http", "https"} and parsed.netloc:
                links.append({"document_type": document_type, "url": url})
        return links

    async def fetch_company(self, request: StockRegistration) -> CompanyBundle:
        instrument = await self.resolve(request.query, request.exchange)
        isin = quote(instrument["isin"], safe="")
        profile = await self._client.get(f"/fundamentals/{isin}/profile")
        data = profile.get("data", {})
        summary = data.get("company_profile")
        if not isinstance(summary, str) or not summary.strip():
            raise ProviderError("Upstox returned no company business description")
        now = datetime.now(UTC)
        prospectus_links = await self.fetch_prospectus_links(instrument["isin"])
        entity = {
            "ticker": instrument["trading_symbol"],
            "isin": instrument["isin"],
            "instrument_key": instrument["instrument_key"],
            "name": instrument["name"],
            "exchange": request.exchange,
            "aliases": list(
                dict.fromkeys(filter(None, [instrument.get("short_name"), request.query]))
            ),
            "business_summary": summary,
            "revenue_segments": [],
            "raw_material_inputs": [],
            "geographic_exposure": None,
            "strengths": request.strengths,
            "business_exclusions": request.business_exclusions,
            "provider_sector": data.get("sector", ""),
            "prospectus_links": prospectus_links,
            "vendor_id": "UPSTOX",
            "vendor_as_of": now.isoformat(),
            "profile_provenance": {"vendor_id": "UPSTOX", "vendor_as_of": now.isoformat()},
        }
        statements = {}
        warnings = []
        for series in ("income-statement", "balance-sheet", "cash-flow"):
            try:
                params = {"type": "consolidated", "fs": "true"}
                if series == "income-statement":
                    params["time_period"] = "quarterly"
                statements[series] = await self._client.get(
                    f"/fundamentals/{isin}/{series}", params
                )
            except ProviderError as exc:
                warnings.append(f"{series}: {exc}")
        entity["latest_quarter_summary"] = narrative_quarter_context(
            normalize_statements(entity["ticker"], statements, "UPSTOX", now)
        )
        # Never label an arbitrary intraday quote as an official CLOSE checkpoint.
        checkpoint = None
        checkpoint_raw = None
        try:
            key = quote(instrument["instrument_key"], safe="")
            today = now.astimezone(ZoneInfo("Asia/Kolkata")).date()
            candles = await self._client.get(f"/historical-candle/{key}/day/{today.isoformat()}")
            checkpoint_raw = candles
            rows = candles.get("data", {}).get("candles", [])
            completed = [r for r in rows if datetime.fromisoformat(r[0]).date() < today]
            if completed:
                row = max(completed, key=lambda x: x[0])
                checkpoint = {
                    "trade_date": datetime.fromisoformat(row[0]).date(),
                    "session_type": "CLOSE",
                    "open_price": row[1],
                    "high_price": row[2],
                    "low_price": row[3],
                    "close_price": row[4],
                    "volume": row[5],
                }
        except (ProviderError, ValueError, IndexError, TypeError) as exc:
            warnings.append(
                f"price checkpoint: {exc}"
                if isinstance(exc, ProviderError)
                else "price checkpoint: invalid provider payload"
            )
        raw = {"instrument": instrument, "profile": profile}
        if checkpoint_raw is not None:
            raw["historical_close"] = checkpoint_raw
        return CompanyBundle(
            entity=entity,
            raw=raw,
            statements=statements,
            checkpoint=checkpoint,
            warnings=warnings,
        )
