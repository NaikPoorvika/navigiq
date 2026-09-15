"""NQ-028 - LLM gateway: the single chokepoint for model access.

Consumers depend on `LLMGateway` and handle `LLMError`. Production code gets
an `OllamaGateway` from `build_llm_gateway()`; tests get a `FakeLLM`.
"""
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
from .factory import build_llm_gateway
from .fake import FakeGenerateCall, FakeLLM
from .gateway import DEFAULT_MAX_TOKENS, LLMGateway
from .ollama import OllamaGateway
from .types import ChatMessage, Embeddings, Generation

__all__ = [
    "DEFAULT_MAX_TOKENS",
    "ChatMessage",
    "Embeddings",
    "FakeGenerateCall",
    "FakeLLM",
    "Generation",
    "LLMEmbeddingDimensionMismatch",
    "LLMEmptyResponse",
    "LLMError",
    "LLMGateway",
    "LLMMalformedResponse",
    "LLMRequestRejected",
    "LLMTimeout",
    "LLMTruncated",
    "LLMUnavailable",
    "OllamaGateway",
    "build_llm_gateway",
]
