"""Health-only template runtime. It never starts an agent or contacts Platform."""

from fastapi import FastAPI

from marketgraph_agents.registry import AGENTS


def create_app() -> FastAPI:
    app = FastAPI(title="MarketGraph agents template", version="0.1.0")

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "service": "marketgraph-agents",
            "execution_enabled": False,
            "registered_agents": len(AGENTS),
        }

    return app


def main() -> None:
    import uvicorn

    uvicorn.run("marketgraph_agents.runtime:create_app", factory=True, host="0.0.0.0", port=8005)


if __name__ == "__main__":
    main()
