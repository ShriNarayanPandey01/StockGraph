import json


class RedisPublisher:
    def __init__(self, client, stream: str = "stockgraph:events:v1"):
        self._client = client
        self._stream = stream

    async def publish(self, event: dict) -> str:
        # No MAXLEN trim: SQL outbox and Redis stream retention must allow outage replay.
        return await self._client.xadd(self._stream, {"event": json.dumps(event, default=str)})
