"""Milestone 1 (fixed spec): Window dossier, SQL-only anomalies, YAML registry."""

import yaml

from src.config.settings import settings
from src.domain.enums import Window
from src.domain.schemas import QuantSummary, StockDossierResponse, resolve_window
from src.repositories import falkor_repo as falkor_module
from src.repositories import timescale_repo as timescale_module


def test_dossier_request_shape_is_window_only():
    start_ts, end_ts = resolve_window(Window.LAST_6M)
    d = StockDossierResponse(ticker="TATASTEEL", window=Window.LAST_6M, start_ts=0, end_ts=0)
    d.start_ts, d.end_ts = start_ts, end_ts
    assert d.window == Window.LAST_6M
    assert d.start_ts < d.end_ts
    assert d.direct_news == []
    assert d.quant_summary is None
    assert not hasattr(d, "daily_anomalies")
    assert not hasattr(d, "from_date")


def test_quant_summary_carries_vendor_provenance():
    q = QuantSummary(vendor_id="vendor-x", row_count=10)
    assert q.vendor_id == "vendor-x"
    assert q.vendor_as_of is None
    assert not hasattr(q, "mode")
    assert not hasattr(q, "unfiltered")


def test_dedup_thresholds_are_settings_not_hardcoded():
    assert settings.dedup_cosine_threshold == 0.92
    assert settings.dedup_window_hours == 48
    assert "0.92" not in falkor_module.VECTOR_DUP_QUERY
    assert "48" not in falkor_module.VECTOR_DUP_QUERY
    assert "$threshold" in falkor_module.VECTOR_DUP_QUERY
    assert "$window_secs" in falkor_module.VECTOR_DUP_QUERY


def test_registry_yaml_has_seed_ids():
    with open("src/config/ontology_seed.yaml", encoding="utf-8") as fh:
        seed = yaml.safe_load(fh)
    commodity_ids = {c["id"] for c in seed["commodities"]}
    assert {"BRENT_CRUDE", "HRC_STEEL", "COKING_COAL"} <= commodity_ids
    # No :Currency nodes — USD/INR forex is the USD_INR_FX macro factor.
    assert "currencies" not in seed
    macro_ids = {m["id"] for m in seed["macro_factors"]}
    assert {
        "RBI_REPO_RATE",
        "INDIA_CPI",
        "INDIA_GDP_GROWTH",
        "USD_INR_FX",
        "INDIA_10Y_YIELD",
        "US_FED_RATE",
        "GOVT_CAPEX_SPEND",
    } <= macro_ids
    # Commodity inter-links (e.g. coking coal <-> steel).
    by_id = {c["id"]: c for c in seed["commodities"]}
    assert "COKING_COAL" in by_id["HRC_STEEL"].get("related_ids", [])
    # Macro explainers feed MacroFactorDetail (why-it-moved from news, not fabricated).
    for m in seed["macro_factors"]:
        assert m.get("description") and m.get("why_it_moves") and m.get("equity_transmission")
        assert m.get("default_scope") in {"BROAD", "SELECTIVE"}
    tickers = {s["ticker"] for s in seed["stocks"]}
    assert {"TATASTEEL", "RELIANCE", "INFY"} <= tickers


def test_timescale_ddl_matches_fixed_spec():
    ddl = timescale_module.DDL_SCHEMA
    for table in [
        "vendor_quotes_raw",
        "daily_stock_metrics",
        "daily_macro_and_flows",
        "quarterly_financials",
        "institutional_deals_raw",
        "monthly_mf_holdings_raw",
        "ingest_runs",
        "vendor_sync_state",
    ]:
        assert table in ddl
    assert "create_hypertable('daily_stock_metrics'" in ddl
    assert "create_hypertable('daily_macro_and_flows'" not in ddl
    assert "vendor_id" in ddl and "vendor_as_of" in ddl
    assert "session_type VARCHAR(10)" in ddl
    assert "PRIMARY KEY (trade_date, session_type, ticker)" in ddl
    assert "session_type = 'CLOSE'" in timescale_module.ANOMALIES_QUERY
    assert "ABS(delivery_20d_zscore) >= $4" in timescale_module.ANOMALIES_QUERY


def test_staging_tables_keep_vintages_never_overwrite():
    ddl = timescale_module.DDL_SCHEMA
    assert "PRIMARY KEY (vendor_id, ticker, trade_date, series, fetched_at)" in ddl
    assert "PRIMARY KEY (ticker, quarter_label, valid_from_ts)" in ddl
    assert "PRIMARY KEY (month, ticker, amc_id, valid_from_ts)" in ddl
    latest = timescale_module.LATEST_VINTAGE_QUERY
    assert "DISTINCT ON (vendor_id, ticker, trade_date, series)" in latest
    assert "fetched_at DESC" in latest


def test_falkor_indexes_match_fixed_spec():
    joined = "\n".join(falkor_module.INDEX_CYPHER_STATEMENTS)
    assert "DailyAnomalyEvent" not in joined
    assert "NewsEvent) ON (n.id)" in joined
    assert "VECTOR INDEX" in joined


def test_market_session_enum_and_quant_summary():
    from src.domain.enums import MarketSession
    from src.domain.schemas import DailyStockMetricItem

    assert MarketSession.OPEN == "OPEN"
    assert MarketSession.CLOSE == "CLOSE"
    item = DailyStockMetricItem(trade_date="2026-10-17", session_type=MarketSession.OPEN, open_price=150.0)
    assert item.session_type == MarketSession.OPEN
    q = QuantSummary(vendor_id="vendor-x", row_count=1, latest_open=150.0, latest_close=152.5)
    assert q.latest_open == 150.0
    assert q.latest_close == 152.5

