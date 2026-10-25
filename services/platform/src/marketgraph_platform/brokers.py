"""Encrypted optional credentials; broker secrets never enter account responses."""
import json

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from marketgraph_platform.repository import PlatformError


class TokenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: SecretStr = Field(min_length=1, max_length=8192)


class BrokerVault:
    def __init__(self, key: SecretStr):
        self.__key = key

    def _cipher(self):
        try:
            return Fernet(self.__key.get_secret_value().encode())
        except (ValueError, TypeError):
            raise PlatformError(503, "Broker credential encryption is not configured") from None

    def encrypt(self, user_id, token):
        # Bind ciphertext to its owner, so swapping database rows fails closed.
        return self._cipher().encrypt(json.dumps({
            "owner": str(user_id), "token": token.get_secret_value()
        }).encode())

    def decrypt(self, user_id, encrypted):
        try:
            value = json.loads(self._cipher().decrypt(bytes(encrypted)))
            if value["owner"] != str(user_id):
                raise ValueError("Owner mismatch")
            return SecretStr(value["token"])
        except (InvalidToken, ValueError, KeyError, TypeError):
            raise PlatformError(503, "Broker credential is unavailable; reconnect or check encryption configuration") from None


class BrokerConnections:
    def __init__(self, repository, settings, canonical_client):
        self.repository = repository
        self.client = canonical_client
        self.__vault = BrokerVault(settings.broker_encryption_key)

    async def status(self, user_id):
        row = await self.repository.pool.fetchrow(
            "SELECT status,revision,validated_at FROM platform_broker_connections WHERE user_id=$1", user_id)
        return dict(row) if row else {"status": "disconnected", "revision": 0, "validated_at": None}

    async def connect(self, user, token):
        encrypted = self.__vault.encrypt(user.id, token)
        await self.client.post_internal("/internal/v1/upstox/validate-credential",
                                        {"access_token": token.get_secret_value()})
        async with self.repository.pool.acquire() as conn, conn.transaction():
            owner = await conn.fetchrow("SELECT disabled FROM platform_users WHERE id=$1 FOR UPDATE", user.id)
            if owner is None or owner["disabled"]:
                raise PlatformError(403, "Account is unavailable")
            await conn.execute(
                "INSERT INTO platform_broker_connections(user_id,encrypted_token,status,validated_at) "
                "VALUES($1,$2,'connected',now()) ON CONFLICT(user_id) DO UPDATE SET "
                "encrypted_token=EXCLUDED.encrypted_token,revision=platform_broker_connections.revision+1,"
                "status='connected',validated_at=now(),updated_at=now()", user.id, encrypted)
        return await self.status(user.id)

    async def disconnect(self, user_id):
        await self.repository.pool.execute(
            "UPDATE platform_broker_connections SET encrypted_token=NULL,revision=revision+1,"
            "status='disconnected',validated_at=NULL,updated_at=now() WHERE user_id=$1", user_id)
        return await self.status(user_id)

    async def headers_for(self, user_id):
        row = await self.repository.pool.fetchrow(
            "SELECT status,revision,encrypted_token FROM platform_broker_connections WHERE user_id=$1", user_id)
        if row is None or row["status"] == "disconnected":
            return {}
        if row["status"] != "connected":
            raise PlatformError(409, "broker_reconnect_required")
        token = self.__vault.decrypt(user_id, row["encrypted_token"])
        return {"X-Upstox-Access-Token": token.get_secret_value(),
                "X-MarketGraph-Credential-Scope": f"{user_id}:{row['revision']}"}

    async def read(self, user_id, path, params=None):
        headers = await self.headers_for(user_id)
        try:
            return await self.client.get(path, params, headers=headers)
        except PlatformError as exc:
            if exc.status == 401 and headers and exc.detail == "broker_reconnect_required":
                revision = int(headers["X-MarketGraph-Credential-Scope"].rsplit(":", 1)[1])
                await self.repository.pool.execute(
                    "UPDATE platform_broker_connections SET status='reconnect_required',updated_at=now() "
                    "WHERE user_id=$1 AND revision=$2", user_id, revision)
                raise PlatformError(409, "broker_reconnect_required") from None
            raise


def build_broker_router(current_user):
    router = APIRouter(tags=["Upstox connections"])

    @router.get("/api/v1/me/broker-connections/upstox")
    async def status(request: Request, user=Depends(current_user)):
        return await request.app.state.brokers.status(user.id)

    @router.put("/api/v1/me/broker-connections/upstox")
    async def connect(body: TokenInput, request: Request, user=Depends(current_user)):
        return await request.app.state.brokers.connect(user, body.access_token)

    @router.delete("/api/v1/me/broker-connections/upstox")
    async def disconnect(request: Request, user=Depends(current_user)):
        return await request.app.state.brokers.disconnect(user.id)

    return router

