"""Application errors shared by Platform services and transport adapters."""


class PlatformError(Exception):
    """An expected failure with an HTTP-safe status and detail."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)
