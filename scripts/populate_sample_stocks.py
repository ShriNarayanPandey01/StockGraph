"""Refresh the SQL equity directory and register sample stocks in StockGraph.

Run from the repository root so the service settings load the local `.env`:

    uv run --package upstox-service python scripts/populate_sample_stocks.py

The universe refresh writes the complete NSE/BSE equity directory to TimescaleDB.
The selected symbols are then submitted through the normal registration/outbox
pipeline, which projects them into FalkorDB. Re-running is safe: projected stocks
are skipped, while an SQL-registered but unprojected stock is re-queued.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from collections.abc import Sequence
from urllib.parse import quote

import httpx

DEFAULT_SYMBOLS = ("LT", "AXISBANK")
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9&._-]{0,24}$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=list(DEFAULT_SYMBOLS),
        help="NSE ticker symbols to register (default: LT AXISBANK)",
    )
    parser.add_argument("--exchange", choices=("NSE", "BSE"), default="NSE")
    parser.add_argument(
        "--graph-url",
        default="http://127.0.0.1:8000",
        help="StockGraph API base URL",
    )
    parser.add_argument(
        "--data-url",
        default="http://127.0.0.1:8001",
        help="Upstox Data Service API base URL",
    )
    parser.add_argument(
        "--skip-universe-refresh",
        action="store_true",
        help="Use the current TimescaleDB equity directory without refreshing it",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=900,
        help="Maximum wait for each data and graph registration job (default: 900)",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=3,
        help="Delay between registration status checks (default: 3)",
    )
    return parser


def normalize_symbols(symbols: Sequence[str]) -> list[str]:
    normalized = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols))
    invalid = [symbol for symbol in normalized if not SYMBOL_PATTERN.fullmatch(symbol)]
    if invalid:
        raise ValueError(f"Invalid ticker symbol(s): {', '.join(invalid)}")
    return normalized


async def _health(client: httpx.AsyncClient, service: str) -> None:
    try:
        response = await client.get("/health")
        response.raise_for_status()
    except httpx.HTTPError:
        raise RuntimeError(f"{service} API is unavailable; check its URL and health endpoint") from None


async def _instrument(
    client: httpx.AsyncClient, symbol: str, exchange: str
) -> dict | None:
    cursor = None
    while True:
        params = {"query": symbol, "exchange": exchange, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        try:
            response = await client.get("/api/v1/stocks", params=params)
            response.raise_for_status()
        except httpx.HTTPError:
            raise RuntimeError("Could not query the SQL stock directory") from None
        page = response.json()
        for item in page.get("items", []):
            if (
                item.get("exchange") == exchange
                and item.get("trading_symbol", "").upper() == symbol
            ):
                return item
        cursor = page.get("next_cursor")
        if not cursor:
            return None


async def _projection_status(client: httpx.AsyncClient, symbol: str) -> str | None:
    try:
        response = await client.get(
            f"/api/v1/stocks/{quote(symbol, safe='')}/context",
            params={"window": "LAST_6M", "limit": 1, "offset": 0},
        )
    except httpx.HTTPError:
        raise RuntimeError("Could not query the StockGraph context API") from None
    if response.status_code == 404:
        return None
    if response.is_error:
        raise RuntimeError(f"StockGraph context API returned HTTP {response.status_code}")
    return str(response.json().get("processing_status", "completed")).lower()


async def _wait_for_projection(
    client: httpx.AsyncClient,
    symbol: str,
    timeout_seconds: int,
    poll_seconds: float,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = await _projection_status(client, symbol)
        if status in {"completed", "failed"}:
            return status
        await asyncio.sleep(poll_seconds)
    raise RuntimeError(f"Graph projection is still running for {symbol}")


async def _wait_for_job(
    client: httpx.AsyncClient,
    job_id: str,
    symbol: str,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = await client.get(f"/api/v1/jobs/{quote(job_id, safe='')}")
            response.raise_for_status()
        except httpx.HTTPError:
            raise RuntimeError(f"Could not read registration status for {symbol}") from None
        status = response.json()
        data_state = str(status.get("data_state") or status.get("state") or "pending").lower()
        graph_state = str(status.get("graph_state") or "pending").lower()
        if data_state == "failed" or graph_state == "failed":
            raise RuntimeError(f"Registration failed for {symbol}; inspect job {job_id} in the APIs")
        if data_state == "completed" and graph_state == "completed":
            return status
        await asyncio.sleep(poll_seconds)
    raise RuntimeError(f"Registration is still running for {symbol}; job ID: {job_id}")


async def populate(args: argparse.Namespace) -> int:
    from upstox_service.runtime.scheduler import equity_universe_job

    symbols = normalize_symbols(args.symbols)
    if args.wait_seconds < 1 or args.poll_seconds <= 0:
        raise ValueError("Wait and polling intervals must be positive")

    if not args.skip_universe_refresh:
        print("Refreshing the NSE/BSE equity directory into TimescaleDB...", flush=True)
        outcome = await equity_universe_job()
        if outcome != "SUCCESS":
            raise RuntimeError(
                "Equity-universe refresh did not complete "
                f"(status: {outcome or 'unknown'}); check the Data Service and Redis"
            )
        print("Equity-universe refresh: SUCCESS", flush=True)

    async with (
        httpx.AsyncClient(base_url=args.data_url.rstrip("/"), timeout=30) as data_client,
        httpx.AsyncClient(base_url=args.graph_url.rstrip("/"), timeout=30) as graph_client,
    ):
        await _health(data_client, "Upstox Data Service")
        await _health(graph_client, "StockGraph")
        failures = 0

        for symbol in symbols:
            instrument = await _instrument(data_client, symbol, args.exchange)
            if instrument is None:
                print(
                    f"{symbol}: not found in the official {args.exchange} equity directory",
                    flush=True,
                )
                failures += 1
                continue

            projection_status = await _projection_status(graph_client, symbol)
            if projection_status == "completed":
                print(
                    f"{symbol}: already present in TimescaleDB and FalkorDB; skipped",
                    flush=True,
                )
                continue
            if projection_status in {"pending", "graph_processing"}:
                projection_status = await _wait_for_projection(
                    graph_client,
                    symbol,
                    args.wait_seconds,
                    args.poll_seconds,
                )
                if projection_status == "completed":
                    print(f"{symbol}: existing graph projection completed", flush=True)
                    continue

            try:
                response = await graph_client.post(
                    "/api/v1/stocks",
                    json={
                        "query": symbol,
                        "exchange": args.exchange,
                        "strengths": [],
                        "business_exclusions": [],
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError:
                raise RuntimeError(f"Could not submit {symbol} through StockGraph registration") from None
            job_id = response.json().get("job_id")
            if not job_id:
                raise RuntimeError(f"StockGraph did not return a registration job ID for {symbol}")

            await _wait_for_job(
                graph_client,
                str(job_id),
                symbol,
                args.wait_seconds,
                args.poll_seconds,
            )
            print(f"{symbol}: registered in TimescaleDB and projected to FalkorDB", flush=True)

        print(f"Completed: {len(symbols) - failures}/{len(symbols)} requested symbols", flush=True)
        return 1 if failures else 0


def main() -> None:
    args = build_parser().parse_args()
    try:
        exit_code = asyncio.run(populate(args))
    except (RuntimeError, ValueError) as exc:
        print(f"Population stopped: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
