"""MCP tool server (Milestone 3): stdlib JSON-RPC adapter, zero new deps."""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from src.domain.enums import Window
from src.processors.entity_resolver import CanonicalEntityResolver
from src.services.stock_context_service import StockContextService

TOOL_NAME = "get_stock_dossier"


def build_tool_schema() -> dict[str, Any]:
    return {"name": TOOL_NAME, "description": "Get bounded stock dossier.",
            "inputSchema": {"type": "object",
                            "properties": {"ticker": {"type": "string"},
                                           "window": {"type": "string", "enum": ["LAST_6M", "LAST_1Y"],
                                                      "default": "LAST_6M"}},
                            "required": ["ticker"]}}


async def call_tool(service: StockContextService, args: dict[str, Any]) -> dict[str, Any]:
    ticker = args.get("ticker", "")
    raw_window = args.get("window", "LAST_6M")
    try:
        window = Window(raw_window)
    except ValueError:
        raise ValueError(f"Invalid window {raw_window!r}: use LAST_6M | LAST_1Y") from None
    dossier = await service.get_stock_dossier(ticker, window)
    return dossier.model_dump(mode="json")


def make_service(falkor_repo: Any, timescale_repo: Any) -> StockContextService:
    return StockContextService(falkor_repo, timescale_repo,
                               resolver=CanonicalEntityResolver.from_seed())


def serve_forever(service: StockContextService) -> None:
    asyncio.run(_serve(service))


async def _serve(service: StockContextService) -> None:
    reader = asyncio.StreamReader()
    await asyncio.get_event_loop().connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid, method, params = req.get("id"), req.get("method"), req.get("params", {})
        if method == "initialize":
            _reply(rid, {"protocolVersion": "2024-11-05", "serverInfo": {"name": "stockgraph", "version": "0.1.0"}})
        elif method == "tools/list":
            _reply(rid, {"tools": [build_tool_schema()]})
        elif method == "tools/call" and params.get("name") == TOOL_NAME:
            try:
                _reply(rid, {"content": [{"type": "text", "text": json.dumps(await call_tool(service, params.get("arguments", {})))}]})
            except (ValueError, Exception) as exc:
                _reply(rid, None, str(exc))
        else:
            _reply(rid, None, f"Unknown method {method!r}")


def _reply(rid: Any, result: Any, error: str | None = None) -> None:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "id": rid}
    msg["result" if error is None else "error"] = result if error is None else {"code": -32000, "message": error}
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()
