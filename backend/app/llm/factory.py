"""NQ-028 - Build the production gateway from configuration.

Settings are imported lazily. `app.config` instantiates its Settings object
at import time, which requires DATABASE_URL; importing it here at module
level would make `app.llm` - and therefore FakeLLM in unit tests - unusable
without a database configured.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from .ollama import OllamaGateway

if TYPE_CHECKING:
    from app.config import Settings


def build_llm_gateway(settings: Settings | None = None, *,
                      client: httpx.AsyncClient | None = None) -> OllamaGateway:
    """An OllamaGateway configured from the ADR-012 settings.

    The caller owns the result and should close it (`await gateway.aclose()`
    or `async with`). A client passed in is not closed by the gateway.
    """
    if settings is None:
        from app.config import settings as app_settings
        settings = app_settings
    return OllamaGateway(
        host=settings.OLLAMA_HOST,
        generation_model=settings.OLLAMA_GEN_MODEL,
        embedding_model=settings.OLLAMA_EMBED_MODEL,
        embedding_dimension=settings.OLLAMA_EMBED_DIM,
        num_ctx=settings.OLLAMA_NUM_CTX,
        keep_alive=settings.OLLAMA_KEEP_ALIVE,
        timeout_s=settings.OLLAMA_TIMEOUT_S,
        max_retries=settings.OLLAMA_MAX_RETRIES,
        client=client,
    )
