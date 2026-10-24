"""Bounded extraction from authorized, uploaded originals; never fetch arbitrary URLs."""

import base64
import hashlib
import io
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class ExtractedDocument:
    content_hash: str
    pages: list[dict]
    chunks: list[dict]
    original: bytes


def extract_document(encoded: str, media_type: str, max_bytes: int = 10 * 1024 * 1024) -> ExtractedDocument:
    if len(encoded) > ((max_bytes + 2) // 3) * 4:
        raise ValueError("Document exceeds the configured byte limit")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Document content must be valid base64") from exc
    if not data or len(data) > max_bytes:
        raise ValueError("Document is empty or exceeds the byte limit")
    if media_type == "text/plain":
        texts = data.decode("utf-8").split("\f")
    elif media_type == "application/pdf":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDF documents are unsupported")
            if len(reader.pages) > 300:
                raise ValueError("Documents are limited to 300 pages")
            texts, length = [], 0
            for page in reader.pages:
                text = page.extract_text() or ""
                length += len(text)
                if length > 1_000_000:
                    raise ValueError("Extracted document exceeds the text limit")
                texts.append(text)
        except PdfReadError as exc:
            raise ValueError("Invalid or unsupported PDF original") from exc
    else:
        raise ValueError("Only UTF-8 text and PDF originals are supported")
    if len(texts) > 300 or sum(len(t) for t in texts) > 1_000_000:
        raise ValueError("Extracted document exceeds page/text limits")
    pages, chunks = [], []
    for page, text in enumerate(texts, 1):
        text = text.strip()
        pages.append({"page": page, "text": text})
        for start in range(0, len(text), 2000):
            chunks.append({"page": page, "ordinal": len(chunks), "text": text[start:start+2000],
                           "locator": f"page {page}, characters {start + 1}-{min(start+2000, len(text))}"})
    if not chunks:
        raise ValueError("Document contains no extractable text; OCR is not available")
    return ExtractedDocument(hashlib.sha256(data).hexdigest(), pages, chunks, data)


def store_original(root: str, extracted: ExtractedDocument) -> str:
    """Content-addressed immutable objects. SQL stores only the hash, never client paths."""
    directory = Path(root).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / extracted.content_hash
    temporary = directory / f".upload-{uuid4().hex}"
    try:
        with temporary.open("xb") as stream:
            stream.write(extracted.original)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Install a complete object atomically without replacing an existing hash.
            os.link(temporary, target)
        except FileExistsError:
            if hashlib.sha256(target.read_bytes()).hexdigest() != extracted.content_hash:
                raise RuntimeError("Original object hash verification failed")
    finally:
        temporary.unlink(missing_ok=True)
    return extracted.content_hash
