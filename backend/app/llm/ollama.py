"""NQ-028 - Ollama-backed LLM gateway.

Talks to the local Ollama server over its HTTP API using httpx, and turns
every failure mode into a typed LLMError. It never returns partial,
truncated or empty output.

FAILURE CLASSIFICATION, per request:

  connect refused / reset / dropped   LLMUnavailable        retried
  connect timeout                     LLMUnavailable        retried
  HTTP 5xx                            LLMUnavailable        retried
  read / write / pool timeout         LLMTimeout            not retried
  HTTP 4xx                            LLMRequestRejected    not retried
  body not the promised JSON shape    LLMMalformedResponse  not retried
  stopped at the token limit          LLMTruncated          not retried
  done=false                          LLMTruncated          not retried
  no content after reasoning removed  LLMEmptyResponse      not retried
  vector length != configured dim     LLMEmbeddingDimensionMismatch

Retries are bounded by max_retries, with exponential backoff. Only failures
that plausibly clear on their own are retried; everything deterministic is
raised on the first occurrence, because at temperature 0 the same request
produces the same failure.

GENERATION ORDER OF CHECKS matters: completion and truncation are checked
before the message content is read. A capped generation can carry text that
looks finished, and reading content first is how a truncated response gets
treated as a success.

REASONING: qwen3 is a thinking model. Thinking is disabled by default,
matching the conditions ADR-012's measurements were taken under - with it
on, reasoning tokens consume the budget and the latency figures that chose
the model no longer apply. Any <think> block that still reaches the content
is stripped before the emptiness check.

OBSERVABILITY: one structlog event per completed request, per retry and per
failure, carrying model, attempts, latency and token counts. Prompt and
response text are never logged.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

import httpx
import structlog

from .errors import (
    LLMEmbeddingDimensionMismatch,
    LLMEmptyResponse,
    LLMError,
    LLMMalformedResponse,
    LLMRequestRejected,
    LLMTimeout,
    LLMTruncated,
    LLMUnavailable,
)
from .gateway import DEFAULT_MAX_TOKENS, validate_embed_args, validate_generate_args
from .types import ChatMessage, Embeddings, Generation

logger = structlog.get_logger("app.llm")

# Connecting to a local server either works within a few seconds or the
# server is not there. Capped by the overall timeout when that is shorter.
CONNECT_TIMEOUT_S = 5.0

# First retry waits this long; each further retry doubles it.
RETRY_BACKOFF_S = 0.5

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)

_SUCCESS_DONE_REASONS = frozenset({None, "stop"})


class OllamaGateway:
    def __init__(
        self,
        *,
        host: str,
        generation_model: str,
        embedding_model: str,
        embedding_dimension: int,
        num_ctx: int,
        keep_alive: str,
        timeout_s: float,
        max_retries: int,
        think: bool = False,
        client: httpx.AsyncClient | None = None,
        retry_backoff_s: float = RETRY_BACKOFF_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not host:
            raise ValueError("host must not be empty")
        if not generation_model or not embedding_model:
            raise ValueError("generation_model and embedding_model must not be empty")
        if _not_positive_int(embedding_dimension):
            raise ValueError("embedding_dimension must be a positive int")
        if _not_positive_int(num_ctx):
            raise ValueError("num_ctx must be a positive int")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError("max_retries must be a non-negative int")
        if not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be a positive number")
        if retry_backoff_s < 0:
            raise ValueError("retry_backoff_s must not be negative")

        self._host = host.rstrip("/")
        self._generation_model = generation_model
        self._embedding_model = embedding_model
        self._embedding_dimension = embedding_dimension
        self._num_ctx = num_ctx
        self._keep_alive = keep_alive
        self._timeout_s = float(timeout_s)
        self._max_retries = max_retries
        self._think = think
        self._retry_backoff_s = retry_backoff_s
        self._sleep = sleep
        self._timeout = httpx.Timeout(self._timeout_s,
                                      connect=min(CONNECT_TIMEOUT_S, self._timeout_s))
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient(timeout=self._timeout)
        self._closed = False

    # --- LLMGateway -------------------------------------------------------

    @property
    def generation_model(self) -> str:
        return self._generation_model

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    @property
    def embedding_dimension(self) -> int:
        return self._embedding_dimension

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.0,
        seed: int | None = None,
        json_schema: Mapping[str, Any] | None = None,
    ) -> Generation:
        checked = validate_generate_args(
            messages, max_tokens=max_tokens, temperature=temperature,
            seed=seed, json_schema=json_schema)

        options: dict[str, Any] = {
            "num_ctx": self._num_ctx,
            "num_predict": max_tokens,
            "temperature": float(temperature),
        }
        if seed is not None:
            options["seed"] = seed
        body: dict[str, Any] = {
            "model": self._generation_model,
            "messages": [{"role": m.role, "content": m.content} for m in checked],
            "stream": False,
            "think": self._think,
            "keep_alive": self._keep_alive,
            "options": options,
        }
        if json_schema is not None:
            body["format"] = dict(json_schema)

        data, attempts, started = await self._post(
            "/api/chat", body, operation="generate", model=self._generation_model)
        try:
            text, model, prompt_tokens, completion_tokens = _parse_generation(
                data, max_tokens=max_tokens)
        except LLMError as error:
            raise self._failed(error, "generate", self._generation_model,
                               attempts, started)

        result = Generation(
            text=text,
            model=model or self._generation_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=_elapsed_ms(started),
            attempts=attempts,
        )
        logger.info("llm.request.completed", operation="generate",
                    model=result.model, attempts=attempts,
                    latency_ms=round(result.latency_ms, 1),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens)
        return result

    async def embed(self, texts: Sequence[str]) -> Embeddings:
        checked = validate_embed_args(texts)
        body = {
            "model": self._embedding_model,
            "input": list(checked),
            "keep_alive": self._keep_alive,
            # Ollama truncates over-long input by default and embeds what is
            # left. That is a silent substitution of a different text, so it
            # is switched off: an input beyond the model's context is
            # rejected instead.
            "truncate": False,
        }
        data, attempts, started = await self._post(
            "/api/embed", body, operation="embed", model=self._embedding_model)
        try:
            vectors = _parse_embeddings(
                data, expected_count=len(checked),
                expected_dimension=self._embedding_dimension)
        except LLMError as error:
            raise self._failed(error, "embed", self._embedding_model,
                               attempts, started)

        model = data.get("model")
        result = Embeddings(
            vectors=vectors,
            model=model if isinstance(model, str) and model else self._embedding_model,
            dimension=self._embedding_dimension,
            latency_ms=_elapsed_ms(started),
            attempts=attempts,
        )
        logger.info("llm.request.completed", operation="embed",
                    model=result.model, attempts=attempts,
                    latency_ms=round(result.latency_ms, 1),
                    inputs=len(checked), dimension=result.dimension)
        return result

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> OllamaGateway:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # --- transport --------------------------------------------------------

    async def _post(self, path: str, body: dict[str, Any], *, operation: str,
                    model: str) -> tuple[dict[str, Any], int, float]:
        """POST with bounded retries. Returns (json body, attempts, start)."""
        if self._closed:
            raise RuntimeError("LLM gateway is closed")

        url = f"{self._host}{path}"
        total_attempts = self._max_retries + 1
        started = time.perf_counter()

        for attempt in range(1, total_attempts + 1):
            try:
                response = await self._client.post(url, json=body,
                                                   timeout=self._timeout)
            except httpx.ConnectTimeout as exc:
                error: LLMError = LLMUnavailable(
                    f"could not connect to Ollama at {self._host} within "
                    f"{min(CONNECT_TIMEOUT_S, self._timeout_s):g}s")
                error.__cause__ = exc
            except httpx.TimeoutException as exc:
                error = LLMTimeout(
                    f"Ollama did not respond within {self._timeout_s:g}s")
                error.__cause__ = exc
                raise self._failed(error, operation, model, attempt, started)
            except httpx.TransportError as exc:
                error = LLMUnavailable(
                    f"could not reach Ollama at {self._host}: {type(exc).__name__}")
                error.__cause__ = exc
            else:
                status = response.status_code
                if status >= 500:
                    error = LLMUnavailable(
                        f"Ollama returned HTTP {status}: {_error_detail(response)}")
                elif status >= 400:
                    error = LLMRequestRejected(
                        f"Ollama rejected the request with HTTP {status}: "
                        f"{_error_detail(response)}", status_code=status)
                    raise self._failed(error, operation, model, attempt, started)
                else:
                    try:
                        data = response.json()
                    except ValueError as exc:
                        error = LLMMalformedResponse("Ollama response is not valid JSON")
                        error.__cause__ = exc
                        raise self._failed(error, operation, model, attempt, started)
                    if not isinstance(data, dict):
                        error = LLMMalformedResponse(
                            f"Ollama response is a JSON {type(data).__name__}, not an object")
                        raise self._failed(error, operation, model, attempt, started)
                    if "error" in data:
                        error = LLMMalformedResponse(
                            f"Ollama returned an error payload with HTTP {status}: "
                            f"{str(data['error'])[:200]}")
                        raise self._failed(error, operation, model, attempt, started)
                    return data, attempt, started

            if attempt < total_attempts:
                delay = self._retry_backoff_s * (2 ** (attempt - 1))
                logger.warning("llm.request.retry", operation=operation,
                               model=model, attempt=attempt,
                               max_attempts=total_attempts,
                               error_code=error.code, delay_s=delay)
                await self._sleep(delay)
                continue
            raise self._failed(error, operation, model, attempt, started)

        raise AssertionError("unreachable: retry loop always returns or raises")

    def _failed(self, error: LLMError, operation: str, model: str,
                attempts: int, started: float) -> LLMError:
        error.model = error.model or model
        error.attempts = attempts
        logger.warning("llm.request.failed", operation=operation, model=model,
                       attempts=attempts,
                       latency_ms=round(_elapsed_ms(started), 1),
                       error_code=error.code, error=error.message)
        return error


# --- response parsing -----------------------------------------------------

def _parse_generation(data: dict[str, Any], *, max_tokens: int
                      ) -> tuple[str, str | None, int | None, int | None]:
    done = data.get("done")
    if not isinstance(done, bool):
        raise LLMMalformedResponse("Ollama response has no boolean 'done' field")
    done_reason = data.get("done_reason")
    if done_reason is not None and not isinstance(done_reason, str):
        raise LLMMalformedResponse("Ollama 'done_reason' is not a string")
    prompt_tokens = _optional_count(data, "prompt_eval_count")
    completion_tokens = _optional_count(data, "eval_count")

    # Completion and truncation first - before any content is read.
    if not done:
        raise LLMTruncated("generation did not complete (done=false)")
    if done_reason == "length" or (completion_tokens is not None
                                   and completion_tokens >= max_tokens):
        raise LLMTruncated(
            f"generation stopped at the token limit (max_tokens={max_tokens}, "
            f"done_reason={done_reason!r}, eval_count={completion_tokens})")
    if done_reason not in _SUCCESS_DONE_REASONS:
        raise LLMMalformedResponse(f"unexpected done_reason {done_reason!r}")

    message = data.get("message")
    if not isinstance(message, dict):
        raise LLMMalformedResponse("Ollama response has no 'message' object")
    content = message.get("content")
    if not isinstance(content, str):
        raise LLMMalformedResponse("Ollama message has no string 'content'")

    text = _strip_reasoning(content)
    if not text:
        raise LLMEmptyResponse("model returned no content")

    model = data.get("model")
    return (text, model if isinstance(model, str) and model else None,
            prompt_tokens, completion_tokens)


def _parse_embeddings(data: dict[str, Any], *, expected_count: int,
                      expected_dimension: int) -> tuple[tuple[float, ...], ...]:
    raw_vectors = data.get("embeddings")
    if not isinstance(raw_vectors, list):
        raise LLMMalformedResponse("Ollama response has no 'embeddings' list")
    if len(raw_vectors) != expected_count:
        raise LLMMalformedResponse(
            f"expected {expected_count} embeddings, got {len(raw_vectors)}")

    vectors: list[tuple[float, ...]] = []
    for index, raw in enumerate(raw_vectors):
        if not isinstance(raw, list):
            raise LLMMalformedResponse(f"embedding {index} is not a list")
        if len(raw) != expected_dimension:
            raise LLMEmbeddingDimensionMismatch(
                f"embedding {index} has {len(raw)} dimensions, expected "
                f"{expected_dimension}",
                expected=expected_dimension, actual=len(raw))
        values: list[float] = []
        for value in raw:
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)):
                raise LLMMalformedResponse(
                    f"embedding {index} contains a non-numeric or non-finite value")
            values.append(float(value))
        vectors.append(tuple(values))
    return tuple(vectors)


# --- helpers --------------------------------------------------------------

def _strip_reasoning(content: str) -> str:
    cleaned = _THINK_BLOCK.sub("", content)
    cleaned = _UNCLOSED_THINK.sub("", cleaned)
    return cleaned.strip()


def _optional_count(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LLMMalformedResponse(f"Ollama '{key}' is not a non-negative integer")
    return value


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200] or "(empty body)"
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        return payload["error"][:200]
    return str(payload)[:200]


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _not_positive_int(value: object) -> bool:
    return isinstance(value, bool) or not isinstance(value, int) or value < 1
