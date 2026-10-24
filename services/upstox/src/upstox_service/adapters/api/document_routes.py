"""Operator-authenticated document intake and citation-preserving source reads."""

import asyncio
import hashlib
import hmac
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from upstox_service.adapters.repositories.timescale.documents import DocumentRepository
from upstox_service.application.documents import extract_document, store_original
from upstox_service.config.settings import Settings


class DocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(pattern=r"^[A-Z0-9&_.-]{1,40}$")
    title: str = Field(min_length=1, max_length=300)
    source_url: str = Field(max_length=2000)
    media_type: Literal["application/pdf", "text/plain"]
    document_kind: Literal["GUIDANCE", "FILING", "RESEARCH", "OTHER"] = "FILING"
    content_base64: str = Field(min_length=1, max_length=14_000_000)
    redistribution_permitted: Literal[True]

    @field_validator("source_url")
    @classmethod
    def valid_url(cls, value):
        parsed = urlparse(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("A public source citation URL without credentials is required")
        return value


def build_document_router(repository, redis_client, config=None):
    config = config or Settings()
    documents = DocumentRepository(repository)
    root = getattr(config, "document_storage_root", "./var/documents")
    router = APIRouter(prefix="/api/v1/documents", tags=["Source documents"])

    @router.post("", status_code=202)
    async def upload(request: DocumentInput, x_internal_api_key: str = Header("")):
        key = getattr(config, "document_internal_api_key", None)
        key = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key or "")
        if not key:
            raise HTTPException(503, "Document intake credentials are not configured")
        if not hmac.compare_digest(key, x_internal_api_key):
            raise HTTPException(401, "Invalid document intake credentials")
        try:
            extracted = await asyncio.to_thread(extract_document, request.content_base64,
                                               request.media_type, getattr(config, "document_max_bytes", 10485760))
            await asyncio.to_thread(store_original, root, extracted)
            result = await documents.save(request, extracted)
        except KeyError as exc:
            raise HTTPException(404, "Unknown registered stock") from exc
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        # The durable SQL outbox is retried by the Data worker if transport is down.
        try:
            await documents.publish_outbox(redis_client)
        except Exception:
            pass
        return result

    @router.get("/{version_id}")
    async def read(version_id: UUID):
        item = await documents.get(version_id)
        if item is None:
            raise HTTPException(404, "Unknown document version")
        return item

    @router.get("/{version_id}/original")
    async def original(version_id: UUID):
        item = await documents.get(version_id)
        if item is None:
            raise HTTPException(404, "Unknown document version")
        digest = item["content_hash"]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise HTTPException(503, "Invalid original object reference")
        try:
            data = await asyncio.to_thread((Path(root).resolve() / digest).read_bytes)
        except FileNotFoundError as exc:
            raise HTTPException(503, "Original temporarily unavailable") from exc
        if hashlib.sha256(data).hexdigest() != digest:
            raise HTTPException(503, "Original failed integrity verification")
        return Response(data, media_type=item["media_type"],
                        headers={"Content-Disposition": f'attachment; filename="{version_id}"',
                                 "X-Content-Type-Options": "nosniff"})

    return router
