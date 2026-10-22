"""Generic resilient HTTP transport (shared by NSE Bhavcopy + news providers).

Shared by the provider adapters so the transport is not
owned by the NSE-specific module. `source_adapter.py` re-exports these
names, so existing imports and tests are unchanged.

Responsibilities (single purpose: "fetch a URL, survive the network"):

1. Throttled requests (`ThrottledSession`) - respect ToS / rate limits.
2. Rotating User-Agents - avoid bot-keying on a single UA string.
3. Retry with exponential backoff on retryable statuses (403/429/5xx).
4. Non-retryable 4xx fails fast (no wasted retries on a 404).
5. Network-level exceptions (DNS/TLS/reset) are retried.
6. An injectable `fetcher` makes every behaviour unit-testable offline.

No provider-specific knowledge lives here: URLs, auth headers and response
shapes are supplied by the caller.
"""

from __future__ import annotations

import logging
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from upstox_service.config.settings import settings

logger = logging.getLogger(__name__)

# Rotated per attempt so bot rules cannot key on a single UA string.
USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockGraph/0.1 (+research; contact: ops)",
    "Mozilla/5.0 (X11; Linux x86_64) StockGraph/0.1 (+research; contact: ops)",
    "StockGraph/0.1 (compatible; StockGraph-Data-Sync; +research)",
)

# Retried with backoff; anything else (4xx other than 403/429) fails fast.
RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}

#: Query parameters that carry a credential. They must never reach a log.
_SECRET_QUERY_PARAMS = ("api_key", "apikey", "api_token", "token", "access_token", "key")


def redact_url(url: str) -> str:
    """Mask credential query parameters so a URL is safe to log.

    Provider keys travel as query parameters (`?api_token=...`), so a raw
    URL in a log line would publish the credential.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in _SECRET_QUERY_PARAMS and value:
            value = "REDACTED"
        pairs.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


class ThrottledSession:
    """Minimal rate-limiter for external HTTP (ToS/rate-limit respect)."""

    def __init__(self, requests_per_second: float | None = None) -> None:
        self._interval = 1.0 / (requests_per_second or settings.nse_requests_per_second)
        self._last: float = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        gap = now - self._last
        if gap < self._interval:
            time.sleep(self._interval - gap)
        self._last = time.monotonic()


@dataclass
class FetchOutcome:
    """Result of one HTTP attempt sequence."""

    ok: bool
    status: int | None = None
    text: str | None = None
    attempts: int = 0
    fallback_to: str | None = None  # e.g. BSE_FALLBACK when NSE fails
    error: str | None = None


class ResilientHttpClient:
    """Throttled + UA-rotated + backoff HTTP client.

    stdlib-only (`urllib`) so no new dependency is needed. A `fetcher`
    callable may be injected for unit tests
    (`(url, headers, timeout) -> (status, text)`); the default performs live
    HTTP. Non-retryable 4xx fails fast; retryable 403/429/5xx exhaust
    retries then return `ok=False` with `fallback_to` set so the caller can
    degrade instead of failing hard.
    """

    def __init__(
        self,
        throttle: ThrottledSession | None = None,
        fetcher: Callable[[str, dict[str, str], int], tuple[int, str]] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._throttle = throttle or ThrottledSession()
        self._fetcher = fetcher or self._live_fetch
        self._rng = rng or random.Random()

    @staticmethod
    def _live_fetch(url: str, headers: dict[str, str], timeout: int) -> tuple[int, str]:
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            # The error body matters: providers explain a plan refusal in it
            # ("Restricted Endpoint ...", "This is a premium endpoint").
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - body is best-effort
                body = ""
            return exc.code or 0, body

    def _backoff(self, attempt: int) -> float:
        base = settings.nse_backoff_base_seconds
        return base * (2.0**attempt) + self._rng.uniform(0, base)

    def fetch(
        self,
        url: str,
        extra_headers: dict[str, str] | None = None,
        fallback_to: str | None = None,
    ) -> FetchOutcome:
        """Fetch `url`, retrying transient failures.

        `extra_headers` carries per-provider auth (e.g. Currents' Bearer
        token) and is merged over the rotating User-Agent. `fallback_to`
        names the degraded source the caller should switch to when the
        request ultimately fails (e.g. `BSE_FALLBACK` for NSE Bhavcopy).

        On failure the last response body is preserved in `text`: providers
        often explain a refusal in the body (a paywall notice) rather than
        the status line, and the caller needs to see it.
        """
        attempts = 0
        last_error: str | None = None
        last_status: int | None = None
        last_text: str | None = None
        while attempts <= settings.nse_max_retries:
            self._throttle.wait()
            headers = {"User-Agent": self._rng.choice(USER_AGENTS)}
            if extra_headers:
                headers.update(extra_headers)
            try:
                status, text = self._fetcher(url, headers, settings.nse_timeout_seconds)
            except Exception as exc:  # network-level (DNS/TLS/reset) -> retryable
                last_error = f"{type(exc).__name__}: {exc}"
                attempts += 1
                if attempts <= settings.nse_max_retries:
                    time.sleep(self._backoff(attempts))
                continue
            last_status = status
            last_text = text
            if status == 200:
                return FetchOutcome(ok=True, status=status, text=text, attempts=attempts + 1)
            if status in RETRYABLE_STATUS and attempts < settings.nse_max_retries:
                last_error = f"HTTP {status} (retryable)"
                logger.warning("Fetch %s -> %s; retry %d", redact_url(url), status, attempts + 1)
                time.sleep(self._backoff(attempts))
                attempts += 1
                continue
            last_error = f"HTTP {status}"
            break
        logger.error("Fetch failed %s: %s", redact_url(url), last_error)
        return FetchOutcome(
            ok=False,
            status=last_status,
            text=last_text,
            attempts=attempts + 1,
            fallback_to=fallback_to,
            error=last_error,
        )
