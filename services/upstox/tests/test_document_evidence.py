import base64
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from upstox_service.adapters.api.document_routes import DocumentInput, build_document_router
from upstox_service.application.documents import extract_document, store_original
from upstox_service.application.financial_context import (
    narrative_quarter_context,
    normalize_statements,
)


def test_original_versions_preserve_page_locators_and_immutable_hashes(tmp_path):
    content = base64.b64encode(b"Guidance on page one\fA revised outlook on page two").decode()
    result = extract_document(content, "text/plain")
    assert result.pages[1]["page"] == 2
    assert result.chunks[1]["locator"].startswith("page 2")
    digest = store_original(str(tmp_path), result)
    assert store_original(str(tmp_path), result) == digest
    assert (tmp_path / digest).read_bytes() == result.original
    revised = extract_document(base64.b64encode(b"Changed guidance").decode(), "text/plain")
    assert store_original(str(tmp_path), revised) != digest


@pytest.mark.parametrize("content,media,limit", [("!!!", "text/plain", 1024),
    (base64.b64encode(b"abc").decode(), "text/plain", 2),
    (base64.b64encode(b"   ").decode(), "text/plain", 1024)])
def test_extraction_rejects_invalid_empty_and_oversize_originals(content, media, limit):
    with pytest.raises(ValueError):
        extract_document(content, media, limit)


def test_intake_is_failclosed_without_operator_credential():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from upstox_service.config.settings import Settings
    app = FastAPI()
    config = Settings(_env_file=None).model_copy(update={"document_internal_api_key": ""})
    app.include_router(build_document_router(object(), object(), config))
    payload = {"ticker": "TCS", "title": "Guidance", "source_url": "https://example.org/filing",
               "media_type": "text/plain", "content_base64": "SGVsbG8=", "redistribution_permitted": True}
    with TestClient(app) as client:
        assert client.post("/api/v1/documents", json=payload).status_code == 503


def test_document_intake_requires_distribution_rights_and_disallows_credential_urls():
    with pytest.raises(ValueError):
        DocumentInput(ticker="TCS", title="Document", source_url="https://u:secret@example.org/doc",
                      media_type="text/plain", content_base64="SGVsbG8=", redistribution_permitted=True)
    with pytest.raises(ValueError):
        DocumentInput(ticker="TCS", title="Document", source_url="https://example.org/doc",
                      media_type="text/plain", content_base64="SGVsbG8=", redistribution_permitted=False)


def test_quarter_normalization_does_not_mislabel_annual_or_operating_profit():
    payload = {"income-statement": {"data": {"time_period": "quarterly", "units_in": "crore",
        "income_statement": [
            {"category": "revenue", "history": [{"period": "Jun 2026", "value": 120},
                                                    {"period": "Jun 2025", "value": 100}]},
            {"category": "net_profit", "history": [{"period": "Jun 2026", "value": 12}]},
            {"category": "operating_profit", "history": [{"period": "Jun 2026", "value": 30}]}],
        "full_statement": [{"particular": "Revenue", "history": [{"period": "Jun 2026", "value": 9999}]}]}}}
    received = datetime(2026, 10, 24, tzinfo=UTC)
    rows = normalize_statements("TCS", payload, "UPSTOX", received)
    latest = rows[-1]
    assert latest["quarter_label"] == "Q1FY2027"
    assert latest["revenue_cr"] == Decimal(120)
    assert latest["rev_yoy_pct"] == Decimal("20.00")
    assert "ebitda_cr" not in latest
    assert latest["published_date"] == received.date()
    assert latest["valid_from_ts"] == int(received.timestamp())
    assert "Revenue increased year over year" in narrative_quarter_context(rows)
    payload["income-statement"]["data"]["time_period"] = "yearly"
    assert normalize_statements("TCS", payload, "UPSTOX", received) == []


def test_pdf_citations_extract_actual_page_text():
    pytest.importorskip("pypdf")
    import io

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(300, 300)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 20 Td (Management guidance) Tj ET")
    page[NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    result = extract_document(base64.b64encode(output.getvalue()).decode(), "application/pdf")
    assert result.pages[0]["text"] == "Management guidance"
    assert result.chunks[0]["page"] == 1


@pytest.mark.asyncio
async def test_live_document_revisions_and_duplicate_original_receipts():
    import os
    if os.getenv("RUN_DATA_SQL_TESTS") != "1":
        pytest.skip("Opt-in SQL integration test")
    import json
    from contextlib import asynccontextmanager
    from uuid import uuid4

    import asyncpg
    from upstox_service.adapters.repositories.timescale.documents import DocumentRepository
    from upstox_service.config.settings import Settings
    conn = await asyncpg.connect(Settings().timescale_dsn)
    transaction = conn.transaction()
    await transaction.start()
    schema = "document_test_" + uuid4().hex
    try:
        await conn.execute(f"CREATE SCHEMA {schema}")
        await conn.execute(f"SET LOCAL search_path TO {schema},public")
        await conn.execute("CREATE TABLE entity_catalog(kind text,entity_id text)")
        await conn.execute("INSERT INTO entity_catalog VALUES('Stock','TCS')")
        class Pool:
            @asynccontextmanager
            async def acquire(self):
                yield conn
        class Data:
            async def connect(self):
                return Pool()
        repo = DocumentRepository(Data())
        await repo.init_schema()
        request = DocumentInput(ticker="TCS", title="Guidance", source_url="https://example.org/source",
            media_type="text/plain", content_base64="SGVsbG8=", redistribution_permitted=True)
        first_content = extract_document(request.content_base64, "text/plain")
        first = await repo.save(request, first_content)
        duplicate = await repo.save(request, first_content)
        revised = await repo.save(request, extract_document("V29ybGQ=", "text/plain"))
        old_again = await repo.save(request, first_content)
        assert [first["revision"], revised["revision"], old_again["revision"]] == [1, 2, 1]
        assert duplicate["received_at"] == first["received_at"] == old_again["received_at"]
        assert duplicate["duplicate"] is True
        assert await conn.fetchval("SELECT revision FROM source_documents") == 2
        events = [json.loads(row["event"]) for row in await conn.fetch("SELECT event FROM document_outbox ORDER BY created_at")]
        assert [event["revision"] for event in events] == [1, 2]
        assert (await repo.get(first["version_id"]))["pages"][0]["text"] == "Hello"
    finally:
        await transaction.rollback()
        await conn.close()
