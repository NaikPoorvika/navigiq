"""NQ-028 - Typed LLM gateway failures.

Every way a model call can go wrong ends in one of these. None of them is
ever converted into a plausible-looking result: a caller either receives a
Generation / Embeddings it can use, or an LLMError it must handle. That is
the same discipline as RoutingUnavailable in the routing service - an honest
error beats a confident fiction (ADR-002).

`code` is stable and meant for callers to switch on, mirroring the planning
orchestrator's PlanningError codes. Messages are for humans and logs.

`retryable` records the gateway's own policy. By the time a caller sees an
error, the gateway has already spent its retries on it; the flag says why it
was or was not retried, not that the caller should try again.
"""
from __future__ import annotations


class LLMError(Exception):
    code = "LLM_ERROR"
    retryable = False

    def __init__(self, message: str, *, model: str | None = None,
                 attempts: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.model = model
        self.attempts = attempts


class LLMUnavailable(LLMError):
    """Ollama could not be reached, dropped the connection, or returned 5xx.

    Retried, because a restarting server or a momentary queue-full 503 does
    recover.
    """
    code = "LLM_UNAVAILABLE"
    retryable = True


class LLMTimeout(LLMError):
    """The server accepted the request but did not answer in time.

    Not retried. A generation that already exhausted its timeout would
    exhaust it again, and a second attempt doubles the wait against the
    ASSUMPTION-002 latency budget before the caller can fall back.
    """
    code = "LLM_TIMEOUT"


class LLMRequestRejected(LLMError):
    """Ollama refused the request (HTTP 4xx) - unknown model, bad payload,
    or an embedding input longer than the model's context.

    Not retried: the same request fails the same way.
    """
    code = "LLM_REQUEST_REJECTED"

    def __init__(self, message: str, *, status_code: int,
                 model: str | None = None, attempts: int | None = None) -> None:
        super().__init__(message, model=model, attempts=attempts)
        self.status_code = status_code


class LLMMalformedResponse(LLMError):
    """The response body is not the shape Ollama's API promises."""
    code = "LLM_MALFORMED_RESPONSE"


class LLMEmptyResponse(LLMError):
    """The model finished but produced no usable text."""
    code = "LLM_EMPTY_RESPONSE"


class LLMTruncated(LLMError):
    """The generation stopped at the token limit or never completed.

    Checked before emptiness and before any content is read, because a
    capped response can still look complete - the failure that invalidated
    the superseded NQ-027 benchmark results.
    """
    code = "LLM_TRUNCATED"


class LLMEmbeddingDimensionMismatch(LLMError):
    """An embedding vector's length differs from the configured dimension."""
    code = "LLM_EMBEDDING_DIMENSION_MISMATCH"

    def __init__(self, message: str, *, expected: int, actual: int,
                 model: str | None = None, attempts: int | None = None) -> None:
        super().__init__(message, model=model, attempts=attempts)
        self.expected = expected
        self.actual = actual
