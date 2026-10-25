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
