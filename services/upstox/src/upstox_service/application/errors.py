"""Provider-independent errors exchanged with application services."""


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class InstrumentNotFound(ProviderError):
    """No official instrument matches the requested identity."""
