"""Encrypted optional credentials; broker secrets never enter account responses."""
import json

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from marketgraph_platform.application.ports import (
    BrokerRepositoryPort,
    CredentialVaultPort,
    DataClientPort,
)
from marketgraph_platform.errors import PlatformError


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


class BrokerConnectionService:
    def __init__(self, repository: BrokerRepositoryPort, settings,
                 data_client: DataClientPort, vault: CredentialVaultPort | None = None):
        self._repository = repository
        self._client = data_client
        self._vault = vault or BrokerVault(settings.broker_encryption_key)

    async def status(self, user_id):
        return await self._repository.broker_status(user_id)

    async def connect(self, user, token):
        encrypted = self._vault.encrypt(user.id, token)
        await self._client.post_internal("/internal/v1/upstox/validate-credential",
                                        {"access_token": token.get_secret_value()})
        return await self._repository.save_broker_credential(user.id, encrypted)

    async def disconnect(self, user_id):
        return await self._repository.disconnect_broker(user_id)

    async def headers_for(self, user_id):
        row = await self._repository.read_broker_credential(user_id)
        if row is None or row["status"] == "disconnected":
            return {}
        if row["status"] != "connected":
            raise PlatformError(409, "broker_reconnect_required")
        token = self._vault.decrypt(user_id, row["encrypted_token"])
        return {"X-Upstox-Access-Token": token.get_secret_value(),
                "X-MarketGraph-Credential-Scope": f"{user_id}:{row['revision']}"}

    async def read(self, user_id, path, params=None):
        headers = await self.headers_for(user_id)
        try:
            return await self._client.get(path, params, headers=headers)
        except PlatformError as exc:
            if exc.status == 401 and headers and exc.detail == "broker_reconnect_required":
                revision = int(headers["X-MarketGraph-Credential-Scope"].rsplit(":", 1)[1])
                await self._repository.require_broker_reconnect(user_id, revision)
                raise PlatformError(409, "broker_reconnect_required") from None
            raise


BrokerConnections = BrokerConnectionService


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

