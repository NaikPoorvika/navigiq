"""Persist assistant traces (agent_runs, tool_calls, llm_calls) and prune them.

Stored per run: trace id, intent (+confidence, source), workflow, states
visited, tool names with canonical argument hashes and latencies, LLM task,
model, prompt version and hash, status and error code, ranking config
version. Never stored: message text in the trace, passwords, tokens.

Retention is bounded (TRACE_RETENTION_DAYS); pruning runs at startup and
every PRUNE_EVERY persisted runs, so trace tables cannot grow without limit.
"""
from __future__ import annotations

import json
import uuid

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.trace import Trace

logger = structlog.get_logger("app.observability")
PRUNE_EVERY = 200
_persisted = 0


async def persist_trace(db: AsyncSession, trace: Trace, *, conversation_id: uuid.UUID | None,
                        user_id: uuid.UUID | None) -> None:
    global _persisted
    try:
        await db.execute(text("""
            INSERT INTO agent_runs (id, conversation_id, user_id, intent, intent_confidence,
                intent_source, workflow, states, status, error_code, tool_call_count,
                llm_call_count, ranking_config_version, latency_ms)
            VALUES (:id, :cid, :uid, :intent, :conf, :src, :wf, CAST(:states AS jsonb), :status,
                    :err, :tc, :lc, :rcv, :lat)
        """), {"id": trace.trace_id, "cid": conversation_id, "uid": user_id,
               "intent": trace.intent, "conf": trace.intent_confidence, "src": trace.intent_source,
               "wf": trace.workflow, "states": json.dumps(trace.states), "status": trace.status,
               "err": trace.error_code, "tc": len(trace.tool_calls), "lc": len(trace.llm_calls),
               "rcv": trace.ranking_config_version, "lat": trace.latency_ms})
        for t in trace.tool_calls:
            await db.execute(text("""
                INSERT INTO tool_calls (run_id, seq, tool_name, args_hash, status, error_code,
                                        latency_ms)
                VALUES (:r, :s, :n, :h, :st, :e, :l)
            """), {"r": trace.trace_id, "s": t.seq, "n": t.tool_name[:60], "h": t.args_hash[:64],
                   "st": t.status, "e": t.error_code, "l": t.latency_ms})
        for c in trace.llm_calls:
            await db.execute(text("""
                INSERT INTO llm_calls (run_id, task, model, prompt_version, prompt_hash, status,
                    error_code, cached, latency_ms, prompt_tokens, completion_tokens)
                VALUES (:r, :t, :m, :v, :h, :s, :e, :c, :l, :pt, :ct)
            """), {"r": trace.trace_id, "t": c.task, "m": c.model, "v": c.prompt_version,
                   "h": c.prompt_hash, "s": c.status, "e": c.error_code, "c": c.cached,
                   "l": c.latency_ms, "pt": c.prompt_tokens, "ct": c.completion_tokens})
        await db.commit()
        _persisted += 1
        if _persisted % PRUNE_EVERY == 0:
            await prune(db)
    except Exception as exc:  # noqa: BLE001 - observability must never break a response
        logger.warning("trace_persist_failed", error=type(exc).__name__)
        await db.rollback()


async def prune(db: AsyncSession, retention_days: int | None = None) -> int:
    from app.config import settings
    days = retention_days or settings.TRACE_RETENTION_DAYS
    res = await db.execute(text(
        "DELETE FROM agent_runs WHERE started_at < now() - make_interval(days => :d)"), {"d": days})
    await db.execute(text(
        "DELETE FROM llm_calls WHERE run_id IS NULL AND created_at < now() - make_interval(days => :d)"),
        {"d": days})
    await db.commit()
    return res.rowcount or 0
