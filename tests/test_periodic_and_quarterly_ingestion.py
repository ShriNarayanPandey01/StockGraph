"""Milestone 5 ingestion tests run entirely with fixture-backed repositories."""

from datetime import UTC, date, datetime

from src.ingestion.periodic_macro_ingestor import PeriodicMacroIngestor
from src.ingestion.quarterly_ingestor import QuarterlyIngestor
from src.repositories.falkor_repo import FalkorGraphRAGRepository


class _Timescale:
    def __init__(self):
        self.macros = []
        self.holdings = []
        self.financials = []

    async def record_ingest_run(self, job_name, status):
        return 1

    async def update_ingest_run(self, run_id, status, error=None):
        return None

    async def append_macro_observations(self, rows):
        self.macros.extend(rows)
        return len(rows)

    async def rotate_mf_holding(self, row):
        if row in self.holdings:
            return False
        self.holdings.append(row)
        return True

    async def insert_quarterly_financials(self, row):
        if row in self.financials:
            return False
        self.financials.append(row)
        return True


class _Falkor:
    def __init__(self):
        self.holdings = []
        self.snapshots = {}
        self.guidance = []
        self.guidance_sets = set()
        self.rotated_edges = []

    def rotate_mf_holding(self, ticker, props):
        key = (ticker, props["amc_id"], props["valid_from_ts"])
        if key in self.holdings:
            return False
        self.holdings.append(key)
        return True

    def has_quarterly_snapshot(self, snapshot_id):
        return snapshot_id in self.snapshots

    def rotate_validity_interval_node(self, ticker, new_ts, props):
        self.snapshots[props["id"]] = dict(props, valid_from_ts=new_ts)
        return {"new_id": props["id"], "old_id": None}

    def replace_guidance_chunks(self, ticker, set_id, new_ts, chunks):
        if (ticker, set_id) in self.guidance_sets:
            return 0
        self.guidance_sets.add((ticker, set_id))
        self.guidance.extend((ticker, set_id, new_ts, chunk) for chunk in chunks)
        return len(chunks)

    def get_active_exposures(self, ticker):
        return ["COKING_COAL"]

    def get_latest_quarterly_snapshot(self, ticker):
        return {"quarter": "Q2FY27", "ebitda_margin_pct": 20.0}

    def get_latest_guidance_highlights(self, ticker):
        return ["Demand is stable."]

    def rotate_dynamic_ontology_edges(self, ticker, edges, new_ts):
        self.rotated_edges.append((ticker, list(edges), new_ts))
        return len(edges)


class _Embedder:
    def embed_one(self, text):
        return [0.1, 0.2]


class _Ontology:
    def __init__(self):
        self.cards = []

    def infer_edges(self, card, now_ts):
        self.cards.append((card, now_ts))
        return []


async def test_periodic_macro_and_mf_holdings_are_canonical_and_temporal():
    timescale, falkor = _Timescale(), _Falkor()
    ingestor = PeriodicMacroIngestor(timescale, falkor)
    as_of = date(2026, 10, 12)

    macro = await ingestor.ingest_macro_indicators(
        [{
            "macro_id": "CPI", "observation_date": "2026-09-01",
            "published_at": "2026-10-12T12:00:00+00:00", "value": 4.2,
            "source_id": "MOSPI",
        }],
        as_of,
    )
    holdings = await ingestor.ingest_mf_holdings(
        [{
            "ticker": "Tata Steel", "amc_id": "HDFC", "amc_name": "HDFC AMC",
            "month": "2026-09-01", "published_at": "2026-10-12T12:00:00+00:00",
            "stake_pct": 1.25, "delta_stake_pct": 0.15,
        }],
        as_of,
    )

    assert macro.records_persisted == 1
    assert timescale.macros[0]["macro_id"] == "INDIA_CPI"
    assert holdings.records_persisted == holdings.graph_writes == 1
    assert timescale.holdings[0]["ticker"] == "TATASTEEL"
    assert falkor.holdings[0][0] == "TATASTEEL"


async def test_quarterly_results_guidance_and_ontology_refresh_are_idempotent():
    timescale, falkor, ontology = _Timescale(), _Falkor(), _Ontology()
    ingestor = QuarterlyIngestor(
        timescale, falkor, embedding_provider=_Embedder(), ontology_builder=ontology
    )
    published = datetime(2026, 10, 17, 12, tzinfo=UTC)
    financial = {
        "ticker": "TATASTEEL", "quarter": "Q2FY27", "published_at": published,
        "revenue_cr": 1000, "ebitda_margin_pct": 20, "pat_cr": 120,
        "debt_to_equity": 0.4, "free_cash_flow_cr": 50,
        "promoter_pledge_pct": 0, "source_id": "NSE_XBRL",
    }
    guidance = {
        "ticker": "TATASTEEL", "quarter": "Q2FY27", "published_at": published,
        "source_document_id": "nse-doc-1", "text": "Management expects stable demand. " * 80,
        "concall_summary": "Demand stable; capex on track.",
    }

    first = await ingestor.run(result_records=[financial], guidance_documents=[guidance])
    second = await ingestor.run(result_records=[financial], guidance_documents=[guidance])

    assert first.status == "COMPLETED"
    assert first.records_persisted >= 2
    assert len(timescale.financials) == 1
    assert len(falkor.snapshots) == 1
    assert falkor.guidance and falkor.guidance[0][3]["embedding"] == [0.1, 0.2]
    assert ontology.cards[0][0].latest_quarter_summary
    assert ontology.cards[0][0].latest_guidance_highlights == ["Demand is stable."]
    assert second.records_persisted == 0


def test_guidance_embedding_write_uses_falkor_vecf32(monkeypatch):
    repo = FalkorGraphRAGRepository()
    calls = []

    def fake_run(query, params):
        calls.append((query, params))
        if "MERGE (g:GuidanceChunk" in query:
            return [["doc#c0"]]
        return []

    monkeypatch.setattr(repo, "_run", fake_run)
    written = repo.replace_guidance_chunks(
        "TATASTEEL",
        "guidance:TATASTEEL:Q2FY27:1:abc",
        1,
        [{"id": "doc#c0", "quarter": "Q2FY27", "embedding": [0.1, 0.2]}],
    )

    assert written == 1
    assert any("vecf32($embedding)" in query for query, _ in calls)
