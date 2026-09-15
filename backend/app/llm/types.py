"""NQ-028 - Value types that cross the LLM gateway boundary.

These are the only shapes downstream consumers (NQ-029 extraction, NQ-031
clarification, NQ-032 explanation, NQ-034 retrieval) receive. Nothing from
Ollama's wire format leaks through them, so the transport can change without
touching a caller.

A successful Generation is a statement that the model finished of its own
accord and produced non-empty text. It is NOT a statement that the text is
correct: ADR-002 keeps the LLM non-authoritative, and every consumer must
still validate what it receives against a deterministic contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]

_ROLES = frozenset({"system", "user", "assistant"})


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str

    def __post_init__(self) -> None:
        if self.role not in _ROLES:
            raise ValueError(
                f"role must be one of {sorted(_ROLES)}, got {self.role!r}")
        if not isinstance(self.content, str):
            raise TypeError(
                f"content must be str, got {type(self.content).__name__}")


@dataclass(frozen=True, slots=True)
class Generation:
    """A completed, non-empty, non-truncated generation."""
    text: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: float
    attempts: int


@dataclass(frozen=True, slots=True)
class Embeddings:
    """One vector per input text, in input order, each of `dimension` floats.

    `dimension` has already been checked against the configured value
    (ADR-012: 768). A vector of any other length never reaches a caller,
    because it would silently corrupt a vector(768) column in NQ-034.
    """
    vectors: tuple[tuple[float, ...], ...]
    model: str
    dimension: int
    latency_ms: float
    attempts: int
