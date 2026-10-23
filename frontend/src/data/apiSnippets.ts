import { ApiSnippet } from '../types/api';

export const API_SNIPPETS: Record<string, ApiSnippet> = {
  curl: {
    id: 'curl',
    label: 'cURL',
    title: 'curl — GET /api/v1/stocks/{ticker}/context',
    code: `curl -X GET "http://localhost:8000/api/v1/stocks/TATASTEEL/context?window=LAST_6M&limit=50" \\
     -H "Accept: application/json"`
  },
  mcp: {
    id: 'mcp',
    label: 'MCP Tool (Cursor/Claude)',
    title: 'Model Context Protocol (MCP) — get_stock_dossier',
    code: `{
  "name": "get_stock_dossier",
  "arguments": {
    "ticker": "TATASTEEL",
    "window": "LAST_6M"
  }
}
// Returns FalkorDB multi-hop news + TimescaleDB delivery z-scores directly into Claude / Cursor`
  },
  python: {
    id: 'python',
    label: 'Python (httpx)',
    title: 'Python 3.12 (httpx) — Asynchronous Context Fetch',
    code: `import httpx

async def fetch_stock_context(ticker: str):
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        resp = await client.get(
            f"/api/v1/stocks/{ticker}/context",
            params={"window": "LAST_6M", "limit": 50}
        )
        resp.raise_for_status()
        return resp.json()

dossier = await fetch_stock_context("TATASTEEL")
print(f"Direct News Count: {len(dossier['direct_news'])}")
print(f"Active Graph Nodes: {len(dossier['nodes'])}")`
  },
  response: {
    id: 'response',
    label: 'Sample Dossier JSON',
    title: 'StockDossierResponse JSON (Strict Dual-Store Contract)',
    code: `{
  "ticker": "TATASTEEL",
  "window": "LAST_6M",
  "start_ts": 1729728000,
  "end_ts": 1761234567,
  "processing_status": "completed",
  "nodes": [
    {
      "id": "Stock:TATASTEEL",
      "kind": "Stock",
      "properties": {
        "name": "Tata Steel Limited",
        "sector": "Metals & Mining",
        "exchange": "NSE"
      }
    },
    {
      "id": "Commodity:COKING_COAL",
      "kind": "Commodity",
      "properties": {
        "name": "Hard Coking Coal FOB Australia",
        "benchmark": "Platts Premium Low Vol"
      }
    },
    {
      "id": "MacroFactor:RBI_REPO_RATE",
      "kind": "MacroFactor",
      "properties": {
        "stance": "HAWKISH",
        "current_rate": 6.50
      }
    }
  ],
  "edges": [
    {
      "id": "TATASTEEL:EXPOSED_TO:COKING_COAL",
      "source": "Stock:TATASTEEL",
      "target": "Commodity:COKING_COAL",
      "relation": "EXPOSED_TO",
      "confidence": 0.88,
      "properties": {
        "exposure_nature": "INPUT_RAW_MATERIAL",
        "margin_impact": "NEGATIVE",
        "sensitivity": "HIGH"
      },
      "rationale": "High dependence on imported metallurgical coal for domestic blast furnace operations (~0.77t coal per tonne of steel)."
    }
  ],
  "direct_news": [
    {
      "id": "reg30-kalinganagar-expansion",
      "headline": "Tata Steel commissions 5 MTPA Kalinganagar Blast Furnace",
      "citation": {
        "url": "https://nseindia.com/corporate/reg30/kalinganagar.pdf",
        "publisher": "NSE",
        "event_date": "2026-10-22"
      },
      "impact_type": "DIRECTLY_IMPACTS",
      "confidence": 0.94
    }
  ]
}`
  }
};

