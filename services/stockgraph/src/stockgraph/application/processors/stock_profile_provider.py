"""Context cards from the committed Falkor projection, not a seed file."""

from stockgraph.application.ports import GuidanceReader, StockProfileReader
from stockgraph.domain.schemas import StockContextCard


class StockProfileProvider:
    def __init__(self, repo: StockProfileReader, guidance: GuidanceReader | None = None) -> None:
        self._repo = repo
        self._guidance = guidance

    def build_context_card(self, ticker: str) -> StockContextCard:
        profile = self._repo.get_entity("Stock", ticker.upper())
        if profile is None:
            raise KeyError(f"Unknown registered stock {ticker!r}")
        guidance = profile.get("latest_guidance_highlights", [])
        # Pure narrative chunks from committed source documents, never SQL financial series.
        if self._guidance is not None:
            guidance = self._guidance.guidance_highlights(ticker.upper()) or guidance
        return StockContextCard(
            ticker=ticker.upper(),
            business_summary=profile.get("business_summary"),
            revenue_segments=profile.get("revenue_segments", []),
            raw_material_inputs=profile.get("raw_material_inputs", []),
            geographic_exposure=profile.get("geographic_exposure"),
            strengths=profile.get("strengths", []),
            business_exclusions=profile.get("business_exclusions", []),
            latest_quarter_summary=profile.get("latest_quarter_summary"),
            latest_guidance_highlights=guidance,
            active_exposures=self._repo.get_active_exposures(ticker.upper()),
            sector=profile.get("sector"),
        )
