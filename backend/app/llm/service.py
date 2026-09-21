"""LLM service: the ONE place application code asks a model for anything.

Wraps the NQ-028 transport gateway with:
  * task-based routing       every call names a task; the task picks the model
  * versioned prompts        each prompt has a version and a content hash that
                             is recorded with every call (observability)
  * schema-constrained output where the task has a JSON schema; the parsed
                             result is returned only if it is valid JSON
  * circuit breaker          after N consecutive transport failures the breaker
                             opens and calls fail fast until the reset window
  * bounded concurrency      a semaphore with a queue timeout (Ollama serialises
                             generation on one GPU - ENVIRONMENT.md)
  * response cache           temperature-0 structural tasks only, bounded LRU
  * tracing                  a recorder callback receives task, model, prompt
                             version/hash, status, latency and token counts -
                             never prompt or response text

Application services never import OllamaGateway directly; the architecture
lint test (tests/unit/test_architecture.py) enforces it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

from .errors import LLMError, LLMMalformedResponse, LLMUnavailable
from .gateway import LLMGateway
from .types import ChatMessage

logger = structlog.get_logger("app.llm.service")


class LLMBusy(LLMUnavailable):
    """The request waited longer than the queue timeout for a model slot."""
    code = "LLM_BUSY"


class LLMCircuitOpen(LLMUnavailable):
    code = "LLM_CIRCUIT_OPEN"


class LLMDisabled(LLMUnavailable):
    code = "LLM_DISABLED"


@dataclass(frozen=True)
class Prompt:
    task: str
    version: str
    system: str
    user_template: str
    schema: dict | None = None
    max_tokens: int = 512
    temperature: float = 0.0

    @property
    def hash(self) -> str:
        blob = json.dumps({"s": self.system, "u": self.user_template, "j": self.schema,
                           "v": self.version}, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def render(self, **variables: Any) -> list[ChatMessage]:
        return [ChatMessage("system", self.system),
                ChatMessage("user", self.user_template.format(**variables))]


@dataclass
class LLMResult:
    task: str
    text: str
    parsed: Any
    model: str
    prompt_version: str
    prompt_hash: str
    latency_ms: int
    cached: bool
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass
class CallRecord:
    task: str
    model: str
    prompt_version: str
    prompt_hash: str
    status: str
    error_code: str | None
    cached: bool
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


Recorder = Callable[[CallRecord], None]


@dataclass
class Breaker:
    threshold: int
    reset_s: float
    failures: int = 0
    opened_at: float | None = None
    clock: Callable[[], float] = field(default=time.monotonic)

    @property
    def open(self) -> bool:
        if self.opened_at is None:
            return False
        if self.clock() - self.opened_at >= self.reset_s:
            # Half-open: let one request through; its outcome decides.
            self.opened_at = None
            self.failures = self.threshold - 1
            return False
        return True

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = self.clock()


class LLMService:
    def __init__(self, gateway: LLMGateway | None, *, enabled: bool = True,
                 max_concurrency: int = 2, queue_timeout_s: float = 30.0,
                 breaker_threshold: int = 3, breaker_reset_s: float = 30.0,
                 cache_ttl_s: int = 3600, cache_max: int = 512,
                 task_models: dict[str, str] | None = None) -> None:
        self.gateway = gateway
        self.enabled = enabled and gateway is not None
        self._sem = asyncio.Semaphore(max_concurrency)
        self._queue_timeout_s = queue_timeout_s
        self.breaker = Breaker(breaker_threshold, breaker_reset_s)
        self._cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._cache_ttl_s = cache_ttl_s
        self._cache_max = cache_max
        self.task_models = task_models or {}

    @property
    def available(self) -> bool:
        return self.enabled and not self.breaker.open

    def model_for(self, task: str) -> str:
        default = self.gateway.generation_model if self.gateway else "none"
        return self.task_models.get(task, default)

    async def run(self, prompt: Prompt, *, recorder: Recorder | None = None,
                  use_cache: bool = True, **variables: Any) -> LLMResult:
        model = self.model_for(prompt.task)
        messages = prompt.render(**variables)
        t0 = time.perf_counter()

        def record(status: str, code: str | None, cached: bool, gen=None) -> None:
            if recorder is None:
                return
            recorder(CallRecord(
                task=prompt.task, model=model, prompt_version=prompt.version,
                prompt_hash=prompt.hash, status=status, error_code=code, cached=cached,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                prompt_tokens=getattr(gen, "prompt_tokens", None),
                completion_tokens=getattr(gen, "completion_tokens", None)))

        if not self.enabled:
            record("error", LLMDisabled.code, False)
            raise LLMDisabled("LLM is disabled")
        if self.breaker.open:
            record("error", LLMCircuitOpen.code, False)
            raise LLMCircuitOpen("LLM circuit open after repeated failures")

        cache_key = None
        if use_cache and prompt.temperature == 0.0 and self._cache_ttl_s > 0:
            blob = json.dumps({"m": model, "h": prompt.hash,
                               "msgs": [[m.role, m.content] for m in messages]}, sort_keys=True)
            cache_key = hashlib.sha256(blob.encode("utf-8")).hexdigest()
            hit = self._cache.get(cache_key)
            if hit and time.monotonic() - hit[0] < self._cache_ttl_s:
                self._cache.move_to_end(cache_key)
                text = hit[1]
                record("ok", None, True)
                return LLMResult(prompt.task, text, _parse(text, prompt), model, prompt.version,
                                 prompt.hash, int((time.perf_counter() - t0) * 1000), True)

        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._queue_timeout_s)
        except asyncio.TimeoutError as exc:
            record("error", LLMBusy.code, False)
            raise LLMBusy("no model slot available in time") from exc
        try:
            gen = await self.gateway.generate(
                messages, max_tokens=prompt.max_tokens, temperature=prompt.temperature,
                seed=42 if prompt.temperature == 0.0 else None, json_schema=prompt.schema)
        except LLMError as exc:
            if isinstance(exc, LLMUnavailable) or exc.code == "LLM_TIMEOUT":
                self.breaker.failure()
            record("error", exc.code, False)
            raise
        finally:
            self._sem.release()
        self.breaker.success()
        parsed = _parse(gen.text, prompt)
        if prompt.schema is not None and parsed is None:
            record("error", LLMMalformedResponse.code, False, gen)
            raise LLMMalformedResponse("model output is not valid JSON", model=model)
        if cache_key is not None:
            self._cache[cache_key] = (time.monotonic(), gen.text)
            while len(self._cache) > self._cache_max:
                self._cache.popitem(last=False)
        record("ok", None, False, gen)
        return LLMResult(prompt.task, gen.text, parsed, model, prompt.version, prompt.hash,
                         int((time.perf_counter() - t0) * 1000), False,
                         gen.prompt_tokens, gen.completion_tokens)


def _parse(text: str, prompt: Prompt) -> Any:
    if prompt.schema is None:
        return None
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):]
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        value = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Process-wide service built from settings (ADR-012 defaults)."""
    global _service
    if _service is None:
        from app.config import settings
        from .factory import build_llm_gateway
        gateway = build_llm_gateway(settings) if settings.LLM_ENABLED else None
        _service = LLMService(
            gateway, enabled=settings.LLM_ENABLED,
            max_concurrency=settings.LLM_MAX_CONCURRENCY,
            queue_timeout_s=settings.LLM_QUEUE_TIMEOUT_S,
            breaker_threshold=settings.LLM_BREAKER_THRESHOLD,
            breaker_reset_s=settings.LLM_BREAKER_RESET_S,
            cache_ttl_s=settings.LLM_CACHE_TTL_S)
    return _service


def set_llm_service(service: LLMService | None) -> None:
    """Tests and failure-injection runs swap the service (e.g. FakeLLM-backed)."""
    global _service
    _service = service
