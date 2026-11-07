"""Application errors that distinguish unavailable inference from empty results."""


class InferenceError(RuntimeError):
    """Model inference failed; the event remains eligible for retry."""


class BudgetExceeded(RuntimeError):
    """The configured inference budget is exhausted or unavailable."""


class LLMDisabled(RuntimeError):
    """External inference is disabled by configuration."""
