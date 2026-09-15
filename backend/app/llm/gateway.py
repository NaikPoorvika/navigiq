"""NQ-028 - The LLM gateway contract.

The single chokepoint for model access. No other module talks to Ollama:
consumers depend on LLMGateway, receive OllamaGateway in production and
FakeLLM in tests, and cannot tell the difference except by the output.

The contract is transport-only. It knows nothing about TripSpec, intents,
prompts, retrieval or tools - those belong to the tasks that consume it.

Argument validation lives here, shared by both implementations, so a
malformed call fails identically against the fake and the real model. A
test that passes against FakeLLM should not start failing on a live server
because the fake was more permissive.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from .types import ChatMessage, Embeddings, Generation

# Upper bound on generated tokens when a caller does not choose one. Hitting
# it raises LLMTruncated rather than returning partial text, so callers with
# long outputs (explanations, answers) should pass their own limit.
DEFAULT_MAX_TOKENS = 1024


@runtime_checkable
class LLMGateway(Protocol):
    @property
    def generation_model(self) -> str: ...

    @property
    def embedding_model(self) -> str: ...

    @property
    def embedding_dimension(self) -> int: ...

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.0,
        seed: int | None = None,
        json_schema: Mapping[str, Any] | None = None,
    ) -> Generation:
        """Run one chat completion.

        json_schema, when given, is passed to the model as a decoding
        constraint. The gateway does not parse or validate the returned
        text against it; that is the consuming task's job.

        Raises an LLMError subclass on every failure. Never returns
        truncated or empty text.
        """
        ...

    async def embed(self, texts: Sequence[str]) -> Embeddings:
        """Embed each text. Vectors come back in input order, each of
        exactly `embedding_dimension` floats, or an LLMError is raised."""
        ...

    async def aclose(self) -> None: ...


def validate_generate_args(
    messages: Sequence[ChatMessage],
    *,
    max_tokens: int,
    temperature: float,
    seed: int | None,
    json_schema: Mapping[str, Any] | None,
) -> tuple[ChatMessage, ...]:
    if isinstance(messages, (str, bytes)) or not isinstance(messages, Sequence):
        raise TypeError("messages must be a sequence of ChatMessage")
    result = tuple(messages)
    if not result:
        raise ValueError("messages must not be empty")
    for message in result:
        if not isinstance(message, ChatMessage):
            raise TypeError(
                f"messages must contain ChatMessage, got {type(message).__name__}")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
        raise ValueError(f"max_tokens must be a positive int, got {max_tokens!r}")
    if (isinstance(temperature, bool) or not isinstance(temperature, (int, float))
            or not math.isfinite(temperature) or not 0.0 <= temperature <= 2.0):
        raise ValueError(f"temperature must be within 0.0-2.0, got {temperature!r}")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise TypeError(f"seed must be an int or None, got {type(seed).__name__}")
    if json_schema is not None and not isinstance(json_schema, Mapping):
        raise TypeError("json_schema must be a mapping or None")
    return result


def validate_embed_args(texts: Sequence[str]) -> tuple[str, ...]:
    # A bare string is a Sequence of characters. Embedding it would silently
    # return one vector per character, so it is rejected outright.
    if isinstance(texts, (str, bytes)):
        raise TypeError("texts must be a sequence of strings, not a single string")
    if not isinstance(texts, Sequence):
        raise TypeError("texts must be a sequence of strings")
    result = tuple(texts)
    if not result:
        raise ValueError("texts must not be empty")
    for text in result:
        if not isinstance(text, str):
            raise TypeError(f"texts must contain str, got {type(text).__name__}")
    return result


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "Embeddings",
    "Generation",
    "LLMGateway",
    "validate_embed_args",
    "validate_generate_args",
]
