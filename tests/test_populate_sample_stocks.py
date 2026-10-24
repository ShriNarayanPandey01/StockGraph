import httpx
import pytest

from scripts.populate_sample_stocks import (
    _instrument,
    _projection_status,
    normalize_symbols,
)


def test_normalize_symbols_deduplicates_and_validates() -> None:
    assert normalize_symbols([" lt ", "LT", "axisbank"]) == ["LT", "AXISBANK"]
    with pytest.raises(ValueError, match="Invalid ticker"):
        normalize_symbols(["RELIANCE/INJECTED"])


@pytest.mark.asyncio
async def test_instrument_search_follows_cursor_until_exact_symbol() -> None:
    page = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal page
        page += 1
        if page == 1:
            assert request.url.params["limit"] == "100"
            return httpx.Response(
                200,
                json={"items": [{"trading_symbol": "LTF"}], "next_cursor": "page-two"},
            )
        assert request.url.params["cursor"] == "page-two"
        return httpx.Response(
            200,
            json={
                "items": [{"exchange": "NSE", "trading_symbol": "LT"}],
                "next_cursor": None,
            },
        )

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        item = await _instrument(client, "LT", "NSE")

    assert item == {"exchange": "NSE", "trading_symbol": "LT"}
    assert page == 2


@pytest.mark.asyncio
async def test_projection_status_preserves_in_progress_state() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"processing_status": "graph_processing"})

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        status = await _projection_status(client, "LT")

    assert status == "graph_processing"
