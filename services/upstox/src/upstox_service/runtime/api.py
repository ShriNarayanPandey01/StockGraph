def main():
    import uvicorn

    uvicorn.run(
        "upstox_service.adapters.api.main:create_app", factory=True, host="0.0.0.0", port=8001
    )
