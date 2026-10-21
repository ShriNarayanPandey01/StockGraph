"""Seed the canonical ontology registry into FalkorDB (Milestone 2).

Reads `src/config/ontology_seed.yaml`, validates every cross-reference, then
issues idempotent MERGEs for nodes (Sector/Commodity/MacroFactor/Stock) and
edges (BELONGS_TO, EXPOSED_TO, SENSITIVE_TO_MACRO incl. BROAD baseline,
RELATED_TO). Seed edges carry confidence=1.0, inferred_by='seed'.

Usage: docker compose up -d falkordb; python -m src.repositories.ontology_seeder
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import yaml

from src.processors.entity_resolver import DEFAULT_SEED_PATH

logger = logging.getLogger(__name__)

SEED_EDGE_PROPS = {
    "confidence": 1.0,
    "inferred_by": "seed",
    "is_latest": True,
    "valid_from_ts": 0,
    "valid_to_ts": 9999999999,
}

MERGE_SECTOR = "MERGE (sec:Sector {id: $props.id}) SET sec += $props RETURN sec.id AS id"
MERGE_COMMODITY = "MERGE (c:Commodity {id: $props.id}) SET c += $props RETURN c.id AS id"
MERGE_MACRO = "MERGE (m:MacroFactor {id: $props.id}) SET m += $props RETURN m.id AS id"
MERGE_STOCK = "MERGE (s:Stock {ticker: $props.ticker}) SET s += $props RETURN s.ticker AS id"
MERGE_BELONGS_TO = (
    "MERGE (s:Stock {ticker: $ticker}) MERGE (sec:Sector {id: $sector_id}) "
    "MERGE (s)-[r:BELONGS_TO]->(sec) SET r += $edge RETURN type(r) AS rel"
)
MERGE_EXPOSED_TO = (
    "MERGE (s:Stock {ticker: $ticker}) MERGE (c:Commodity {id: $target_id}) "
    "MERGE (s)-[r:EXPOSED_TO]->(c) SET r += $edge RETURN type(r) AS rel"
)
MERGE_SENSITIVE_TO_MACRO = (
    "MERGE (s:Stock {ticker: $ticker}) MERGE (m:MacroFactor {id: $target_id}) "
    "MERGE (s)-[r:SENSITIVE_TO_MACRO]->(m) SET r += $edge RETURN type(r) AS rel"
)
MERGE_RELATED_TO = (
    "MERGE (a:Commodity {id: $source_id}) MERGE (b:Commodity {id: $target_id}) "
    "MERGE (a)-[r:RELATED_TO]->(b) SET r += $edge RETURN type(r) AS rel"
)


def load_and_validate_seed(seed_path: str | Path = DEFAULT_SEED_PATH) -> dict[str, Any]:
    """Load YAML and fail fast on any dangling cross-reference."""
    with open(seed_path, encoding="utf-8") as fh:
        seed = yaml.safe_load(fh)
    commodities = {c["id"] for c in seed.get("commodities", [])}
    macros = {m["id"] for m in seed.get("macro_factors", [])}
    sectors = {s["id"] for s in seed.get("sectors", [])}
    for comm in seed.get("commodities", []):
        for rel in comm.get("related_ids", []):
            if rel not in commodities:
                raise ValueError(f"Commodity {comm['id']} related_ids[{rel}]: unknown id")
    for stock in seed.get("stocks", []):
        if stock.get("sector") not in sectors:
            raise ValueError(f"Stock {stock['ticker']} sector {stock.get('sector')!r}: unknown")
        for cid in stock.get("exposures", []):
            if cid not in commodities:
                raise ValueError(f"Stock {stock['ticker']} exposures[{cid}]: unknown id")
        for mid in stock.get("macro_exposures", []):
            if mid not in macros:
                raise ValueError(f"Stock {stock['ticker']} macro_exposures[{mid}]: unknown id")
    return seed


def broad_macro_ids(seed: dict[str, Any]) -> set[str]:
    return {m["id"] for m in seed.get("macro_factors", []) if m.get("default_scope") == "BROAD"}

def seed_ontology(repo: Any, seed_path: str | Path = DEFAULT_SEED_PATH) -> dict[str, int]:
    """Validate + MERGE the full registry. Returns per-label counts."""
    seed = load_and_validate_seed(seed_path)
    counts = {"sectors": 0, "commodities": 0, "macros": 0, "stocks": 0, "edges": 0}
    repo.ensure_indexes_and_constraints()
    for sec in seed.get("sectors", []):
        repo._run(
            MERGE_SECTOR,
            {"props": {"id": sec["id"], "name": sec.get("name"), "aliases": sec.get("aliases", [])}},
        )
        counts["sectors"] += 1
    for comm in seed.get("commodities", []):
        repo._run(
            MERGE_COMMODITY,
            {
                "props": {
                    "id": comm["id"],
                    "name": comm.get("name"),
                    "unit": comm.get("unit"),
                    "aliases": comm.get("aliases", []),
                    "related_rationale": comm.get("related_rationale"),
                }
            },
        )
        counts["commodities"] += 1
    for macro in seed.get("macro_factors", []):
        repo._run(
            MERGE_MACRO,
            {
                "props": {
                    "id": macro["id"],
                    "name": macro.get("name"),
                    "unit": macro.get("unit"),
                    "aliases": macro.get("aliases", []),
                    "description": macro.get("description"),
                    "why_it_moves": macro.get("why_it_moves"),
                    "equity_transmission": macro.get("equity_transmission"),
                    "default_scope": macro.get("default_scope"),
                }
            },
        )
        counts["macros"] += 1
    broad = broad_macro_ids(seed)
    for stock in seed.get("stocks", []):
        ticker = stock["ticker"]
        repo._run(
            MERGE_STOCK,
            {
                "props": {
                    "ticker": ticker,
                    "isin": stock.get("isin"),
                    "name": stock.get("name"),
                    "aliases": stock.get("aliases", []),
                    "business_summary": stock.get("business_summary"),
                    "revenue_segments": stock.get("revenue_segments", []),
                    "raw_material_inputs": stock.get("raw_material_inputs", []),
                    "geographic_exposure": stock.get("geographic_exposure"),
                }
            },
        )
        counts["stocks"] += 1
        repo._run(
            MERGE_BELONGS_TO,
            {"ticker": ticker, "sector_id": stock["sector"], "edge": SEED_EDGE_PROPS},
        )
        counts["edges"] += 1
        for cid in stock.get("exposures", []):
            repo._run(
                MERGE_EXPOSED_TO,
                {"ticker": ticker, "target_id": cid, "edge": SEED_EDGE_PROPS},
            )
            counts["edges"] += 1
        for mid in sorted(set(stock.get("macro_exposures", [])) | broad):
            repo._run(
                MERGE_SENSITIVE_TO_MACRO,
                {"ticker": ticker, "target_id": mid, "edge": SEED_EDGE_PROPS},
            )
            counts["edges"] += 1
    for comm in seed.get("commodities", []):
        for rel in comm.get("related_ids", []):
            repo._run(
                MERGE_RELATED_TO,
                {
                    "source_id": comm["id"],
                    "target_id": rel,
                    "edge": {**SEED_EDGE_PROPS, "rationale": comm.get("related_rationale")},
                },
            )
            counts["edges"] += 1
    logger.info("Ontology seed complete: %s", counts)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed canonical ontology into FalkorDB")
    parser.add_argument("--seed", default=str(DEFAULT_SEED_PATH))
    args = parser.parse_args()
    from src.repositories.falkor_repo import FalkorGraphRAGRepository

    repo = FalkorGraphRAGRepository()
    print(f"Seeded: {seed_ontology(repo, args.seed)}")


if __name__ == "__main__":
    main()


