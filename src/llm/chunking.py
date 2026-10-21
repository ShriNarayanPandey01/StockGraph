"""Chunking spec for news + concall text (Rule: vectors live in FalkorDB).

- News articles / Reg-30 filings: single chunk, head-truncated to
  `NEWS_CHUNK_TOKENS` (512). Short, self-contained, no overlap needed.
- Concall PDFs / presentations: sliding windows of `GUIDANCE_CHUNK_TOKENS`
  (512) with `GUIDANCE_OVERLAP_TOKENS` (50) overlap so guidance spanning a
  boundary is still retrievable. Chunk ids are deterministic:
  `{doc_id}#c{idx}` — re-ingestion is idempotent, never duplicated.
- Every chunk is token-measured via `src/llm/tokens.py` before embedding;
  oversized inputs are truncated, never rejected (ingestion must not crash).

Pure Python, no DB/LLM calls — fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.llm.tokens import count_tokens, truncate_to_tokens

NEWS_CHUNK_TOKENS = 512
GUIDANCE_CHUNK_TOKENS = 512
GUIDANCE_OVERLAP_TOKENS = 50


@dataclass(frozen=True)
class TextChunk:
    id: str
    text: str
    tokens: int
    index: int


def chunk_news(doc_id: str, text: str) -> list[TextChunk]:
    """Single-chunk a news article (truncate-only, never split)."""
    body = truncate_to_tokens(text or "", NEWS_CHUNK_TOKENS)
    return [TextChunk(id=f"{doc_id}#c0", text=body, tokens=count_tokens(body), index=0)]


def chunk_guidance(doc_id: str, text: str) -> list[TextChunk]:
    """Sliding-window chunker for long concall/presentation text."""
    from src.config.settings import settings
    from src.llm.tokens import _encoding_for  # local import: keeps module light

    enc = _encoding_for(settings.llm_chat_model)
    toks = enc.encode(text or "")
    if not toks:
        return []
    chunks: list[TextChunk] = []
    step = GUIDANCE_CHUNK_TOKENS - GUIDANCE_OVERLAP_TOKENS
    idx = 0
    for start in range(0, len(toks), step):
        window = toks[start : start + GUIDANCE_CHUNK_TOKENS]
        body = enc.decode(window)
        chunks.append(TextChunk(id=f"{doc_id}#c{idx}", text=body, tokens=len(window), index=idx))
        idx += 1
        if start + GUIDANCE_CHUNK_TOKENS >= len(toks):
            break
    return chunks
