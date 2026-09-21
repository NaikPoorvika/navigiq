"""Health endpoints.

/health       cheap liveness + database/redis reachability
/health/deep  every dependency, with what degrades when each is down:
              database (required), PostGIS/pgvector/pg_trgm, POI inventory,
              knowledge corpus, Redis (optional cache), Ollama (optional:
              assistant falls back to rules/extractive), weather (optional).
"""
from __future__ import annotations

import asyncio
import time

import httpx
import structlog
from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.core.redis import redis_ping
from app.db.session import engine

router = APIRouter()
logger = structlog.get_logger(__name__)


async def _db() -> dict:
    t0 = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "latency_ms": int((time.perf_counter() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": type(exc).__name__}


@router.get("/health")
async def health() -> dict:
    db = await _db()
    redis_ok = await redis_ping()
    status = "ok" if db["status"] == "ok" else "degraded"
    return {"status": status, "database": db["status"],
            "redis": "ok" if redis_ok else ("disabled" if not settings.REDIS_ENABLED else "error")}


@router.get("/health/deep")
async def deep() -> dict:
    out: dict = {"database": await _db()}
    if out["database"]["status"] == "ok":
        try:
            async with engine.connect() as conn:
                exts = set((await conn.execute(text(
                    "SELECT extname FROM pg_extension"))).scalars().all())
                pois = (await conn.execute(text(
                    "SELECT count(*) FILTER (WHERE active), count(*) FILTER (WHERE active AND "
                    "recommendable) FROM pois"))).one()
                chunks = (await conn.execute(text(
                    "SELECT count(*), count(embedding) FROM knowledge_chunks"))).one()
                poi_emb = (await conn.execute(text("SELECT count(*) FROM poi_embeddings"))).scalar()
                rev = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            out["extensions"] = {e: e in exts for e in ("postgis", "vector", "pg_trgm")}
            out["inventory"] = {"active_pois": pois[0], "recommendable_pois": pois[1],
                                "poi_embeddings": poi_emb}
            out["knowledge"] = {"chunks": chunks[0], "embedded_chunks": chunks[1]}
            out["schema_revision"] = rev
        except Exception as exc:  # noqa: BLE001
            out["inventory"] = {"status": "error", "error": type(exc).__name__}
    out["redis"] = {"status": "ok" if await redis_ping() else "unavailable",
                    "degrades_to": "no cache"}
    out["ollama"] = await _ollama()
    out["weather"] = {"enabled": settings.WEATHER_ENABLED,
                      "degrades_to": "plans without weather optimisation"}
    out["transportation"] = {"provider": settings.TRANSPORTATION_PROVIDER,
                             "note": "deferred in this version"}
    required_ok = out["database"]["status"] == "ok"
    out["status"] = "ok" if required_ok and out["ollama"]["status"] == "ok" else (
        "degraded" if required_ok else "error")
    return out


async def _ollama() -> dict:
    from app.llm.service import get_llm_service
    svc = get_llm_service()
    if not settings.LLM_ENABLED:
        return {"status": "disabled", "degrades_to": "rule-based assistant"}
    try:
        async with httpx.AsyncClient(timeout=2.5) as c:
            r = await asyncio.wait_for(c.get(f"{settings.OLLAMA_HOST}/api/tags"), 3.0)
            r.raise_for_status()
            models = {m["name"] for m in r.json().get("models", [])}
        needed = {settings.OLLAMA_GEN_MODEL, settings.OLLAMA_EMBED_MODEL}
        have = {n for n in needed if n in models or f"{n}:latest" in models}
        return {"status": "ok" if have == needed else "degraded", "models_present": sorted(have),
                "models_required": sorted(needed), "circuit_open": svc.breaker.open}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "error": type(exc).__name__,
                "degrades_to": "rule-based assistant, extractive answers, form planning"}
