"""Embeddings with IDENTICAL normalisation at ingestion and query time.

nomic-embed-text is trained with task prefixes: documents are embedded as
"search_document: <text>" and queries as "search_query: <text>". Both sides
also pass through the same whitespace normalisation and are L2-normalised
here, so cosine distance in pgvector compares like with like. Changing any
of this requires re-embedding the corpus (ADR-012).
"""
from __future__ import annotations

import math
import re

from app.llm.gateway import LLMGateway

DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "
MAX_EMBED_CHARS = 2000
BATCH = 32


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:MAX_EMBED_CHARS]


def l2(v) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


async def embed_documents(gateway: LLMGateway, texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        batch = [DOC_PREFIX + _norm_text(t) for t in texts[i:i + BATCH]]
        res = await gateway.embed(batch)
        out.extend(l2(v) for v in res.vectors)
    return out


async def embed_query(gateway: LLMGateway, query: str) -> list[float]:
    res = await gateway.embed([QUERY_PREFIX + _norm_text(query)])
    return l2(res.vectors[0])


def vector_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"
