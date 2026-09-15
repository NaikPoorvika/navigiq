"""NQ-028 - OllamaGateway against the real local Ollama server.

Optional. Skipped cleanly when Ollama is not reachable or either ADR-012
model is not pulled, so the suite stays green on a machine without a GPU -
the same convention the routing tests use for OSRM.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq",
)

from app.config import settings  # noqa: E402
from app.llm import (  # noqa: E402
    ChatMessage,
    LLMRequestRejected,
    LLMTruncated,
    build_llm_gateway,
)


def _ollama_has_accepted_models() -> bool:
    try:
        response = httpx.get(f"{settings.OLLAMA_HOST}/api/tags", timeout=2.0)
        names = {m.get("name", "") for m in response.json().get("models", [])}
    except Exception:  # noqa: BLE001 - any failure means "not available"
        return False
    available = names | {name.removesuffix(":latest") for name in names}
    return {settings.OLLAMA_GEN_MODEL, settings.OLLAMA_EMBED_MODEL} <= available


pytestmark = pytest.mark.skipif(
    not _ollama_has_accepted_models(),
    reason=f"Ollama at {settings.OLLAMA_HOST} with {settings.OLLAMA_GEN_MODEL} "
           f"and {settings.OLLAMA_EMBED_MODEL} is not available",
)


async def test_live_generation_returns_text():
    async with build_llm_gateway() as gateway:
        result = await gateway.generate(
            [ChatMessage("user", "Reply with the single word: ok")], max_tokens=64)
    assert result.text
    assert result.model.startswith(settings.OLLAMA_GEN_MODEL.split(":")[0])
    assert result.completion_tokens is not None and result.completion_tokens < 64


async def test_live_embedding_has_the_accepted_dimension():
    async with build_llm_gateway() as gateway:
        result = await gateway.embed(["quiet cafe in Indiranagar", "lakeside park"])
    assert result.dimension == 768
    assert len(result.vectors) == 2
    assert all(len(vector) == 768 for vector in result.vectors)


async def test_live_token_limit_raises_truncated():
    async with build_llm_gateway() as gateway:
        with pytest.raises(LLMTruncated):
            await gateway.generate(
                [ChatMessage("user", "Write a long paragraph about Bengaluru.")],
                max_tokens=4)


async def test_live_oversized_embedding_input_is_rejected():
    async with build_llm_gateway() as gateway:
        with pytest.raises(LLMRequestRejected):
            await gateway.embed([" ".join(["Bengaluru"] * 6000)])
