"""Token counting + truncation (tiktoken). No network, fully unit-testable.

Every prompt/chunk is measured BEFORE any LLM call and head-truncated to
`settings.llm_max_tokens_per_call`. Tokenizer resolution is lazy (tiktoken
only imported on first use) so `tiktoken` stays an optional-at-runtime dep
and unit tests never pay model-download costs.
"""

from __future__ import annotations

from functools import lru_cache

from stockgraph.runtime.settings import settings

MODEL_ENCODINGS: dict[str, str] = {
    "gpt-4o-mini": "o200k_base",
    "gpt-4o": "o200k_base",
    "text-embedding-3-small": "cl100k_base",
}


@lru_cache(maxsize=4)
def _encoding_for(model: str):  # type: ignore[no-untyped-def]
    import tiktoken

    enc_name = MODEL_ENCODINGS.get(model, "cl100k_base")
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding(enc_name)


def count_tokens(text: str, model: str | None = None) -> int:
    """Return the token count of `text` under the model's encoding."""
    if not text:
        return 0
    return len(_encoding_for(model or settings.llm_chat_model).encode(text))


def truncate_to_tokens(text: str, max_tokens: int | None = None, model: str | None = None) -> str:
    """Head-truncate `text` to at most `max_tokens` tokens (default from settings)."""
    limit = max_tokens if max_tokens is not None else settings.llm_max_tokens_per_call
    enc = _encoding_for(model or settings.llm_chat_model)
    toks = enc.encode(text or "")
    if len(toks) <= limit:
        return text
    return enc.decode(toks[:limit])
