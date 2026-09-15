"""NQ-028 - FakeLLM, the deterministic gateway for tests.

Implements LLMGateway with no GPU, no network and no randomness, so suites
that exercise model-consuming code (NQ-029 onwards) run anywhere and give
the same answer every time.

It enforces the same success invariants as the real gateway rather than
being more forgiving: an empty response raises LLMEmptyResponse, a response
at or over max_tokens raises LLMTruncated, and malformed arguments are
rejected by the same shared validators. Code tested against the fake should
not meet a new failure class the first time it meets a real model.

Three ways to control generation, mutually exclusive:

  responses   a script consumed in order. An LLMError in the script is
              raised instead of returned, to exercise failure paths.
  responder   a callable deciding the text from the messages.
  (neither)   a deterministic digest of the request. When a json_schema is
              given, the digest is wrapped in a JSON object so the output at
              least parses; it will not satisfy the schema - script a real
              response for that.

Token counts are whitespace word counts. They are an approximation, used
only so the truncation rule has something to apply to.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import LLMEmptyResponse, LLMError, LLMTruncated
from .gateway import DEFAULT_MAX_TOKENS, validate_embed_args, validate_generate_args
from .types import ChatMessage, Embeddings, Generation

DEFAULT_FAKE_EMBEDDING_DIMENSION = 768


@dataclass(frozen=True, slots=True)
class FakeGenerateCall:
    messages: tuple[ChatMessage, ...]
    max_tokens: int
    temperature: float
    seed: int | None
    json_schema: dict[str, Any] | None


class FakeLLM:
    def __init__(
        self,
        *,
        responses: Iterable[str | LLMError] | None = None,
        responder: Callable[[tuple[ChatMessage, ...]], str] | None = None,
        generation_model: str = "fake-generation",
        embedding_model: str = "fake-embedding",
        embedding_dimension: int = DEFAULT_FAKE_EMBEDDING_DIMENSION,
    ) -> None:
        if responses is not None and responder is not None:
            raise ValueError("pass responses or responder, not both")
        if (isinstance(embedding_dimension, bool)
                or not isinstance(embedding_dimension, int) or embedding_dimension < 1):
            raise ValueError("embedding_dimension must be a positive int")

        self._script: deque[str | LLMError] | None = None
        if responses is not None:
            script = list(responses)
            for item in script:
                if not isinstance(item, (str, LLMError)):
                    raise TypeError(
                        "responses may contain only str or LLMError instances, "
                        f"got {type(item).__name__}")
            self._script = deque(script)

        self._responder = responder
        self._generation_model = generation_model
        self._embedding_model = embedding_model
        self._embedding_dimension = embedding_dimension
        self._closed = False

        self.generate_calls: list[FakeGenerateCall] = []
        self.embed_calls: list[tuple[str, ...]] = []

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
        self._check_open()
        checked = validate_generate_args(
            messages, max_tokens=max_tokens, temperature=temperature,
            seed=seed, json_schema=json_schema)
        call = FakeGenerateCall(
            messages=checked,
            max_tokens=max_tokens,
            temperature=float(temperature),
            seed=seed,
            json_schema=dict(json_schema) if json_schema is not None else None,
        )
        self.generate_calls.append(call)

        if self._script is not None:
            if not self._script:
                raise RuntimeError("FakeLLM response script is exhausted")
            item = self._script.popleft()
            if isinstance(item, LLMError):
                raise item
            raw = item
        elif self._responder is not None:
            raw = self._responder(checked)
            if not isinstance(raw, str):
                raise TypeError(
                    f"responder must return str, got {type(raw).__name__}")
        else:
            raw = _default_text(call)

        text = raw.strip()
        if not text:
            raise LLMEmptyResponse("FakeLLM produced an empty response",
                                   model=self._generation_model, attempts=1)
        completion_tokens = len(text.split())
        if completion_tokens >= max_tokens:
            raise LLMTruncated(
                f"FakeLLM response of {completion_tokens} tokens reached "
                f"max_tokens={max_tokens}",
                model=self._generation_model, attempts=1)

        return Generation(
            text=text,
            model=self._generation_model,
            prompt_tokens=sum(len(m.content.split()) for m in checked),
            completion_tokens=completion_tokens,
            latency_ms=0.0,
            attempts=1,
        )

    async def embed(self, texts: Sequence[str]) -> Embeddings:
        self._check_open()
        checked = validate_embed_args(texts)
        self.embed_calls.append(checked)
        return Embeddings(
            vectors=tuple(
                _deterministic_vector(self._embedding_model, text,
                                      self._embedding_dimension)
                for text in checked),
            model=self._embedding_model,
            dimension=self._embedding_dimension,
            latency_ms=0.0,
            attempts=1,
        )

    async def aclose(self) -> None:
        self._closed = True

    async def __aenter__(self) -> FakeLLM:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # --- internals --------------------------------------------------------

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("LLM gateway is closed")


def _default_text(call: FakeGenerateCall) -> str:
    canonical = json.dumps(
        {
            "messages": [[m.role, m.content] for m in call.messages],
            "max_tokens": call.max_tokens,
            "temperature": call.temperature,
            "seed": call.seed,
            "json_schema": call.json_schema,
        },
        sort_keys=True, ensure_ascii=False, default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    if call.json_schema is not None:
        return json.dumps({"fake_response": digest})
    return f"fake-response-{digest}"


def _deterministic_vector(model: str, text: str, dimension: int) -> tuple[float, ...]:
    """A unit vector derived from sha256 in counter mode.

    Identical text gives an identical vector; different text gives an
    unrelated one. It carries no semantic meaning - similarity between two
    fake vectors says nothing about the texts - so retrieval quality can
    only be tested against the real embedding model.
    """
    values: list[float] = []
    counter = 0
    while len(values) < dimension:
        block = hashlib.sha256(
            f"{model}\x00{counter}\x00{text}".encode("utf-8")).digest()
        for offset in range(0, len(block), 4):
            word = int.from_bytes(block[offset:offset + 4], "big")
            values.append(word / 0xFFFFFFFF * 2.0 - 1.0)
        counter += 1
    values = values[:dimension]
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0.0:
        return tuple([1.0] + [0.0] * (dimension - 1))
    return tuple(v / norm for v in values)
