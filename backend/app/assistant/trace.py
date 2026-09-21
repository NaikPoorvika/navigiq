"""Per-request trace and HARD limits for the bounded agent (sections 56, 76).

Limits are enforced here, in Python, on every transition and tool call - no
prompt can raise them. Exceeding one raises LimitExceeded, which the agent
turns into a clean FAIL state with a user-safe message.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field

from app.llm.service import CallRecord

MAX_TOOL_CALLS = 10
MAX_STATE_TRANSITIONS = 14
MAX_CLARIFICATIONS = 2
MAX_REPLANS = 2
MAX_IDENTICAL_TOOL_CALLS = 1
MAX_RAG_QUERIES = 2
MAX_PLAN_VARIANTS = 3
MAX_LLM_CALLS = 6


class LimitExceeded(RuntimeError):
    def __init__(self, limit: str, value: int):
        super().__init__(f"{limit} exceeded ({value})")
        self.limit = limit
        self.value = value
        self.code = "AGENT_LIMIT"


def canonical_hash(tool_name: str, args: dict) -> str:
    blob = json.dumps({"tool": tool_name, "args": args}, sort_keys=True, default=str,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class ToolCallRecord:
    seq: int
    tool_name: str
    args_hash: str
    status: str
    error_code: str | None
    latency_ms: int


@dataclass
class Trace:
    trace_id: uuid.UUID = field(default_factory=uuid.uuid4)
    started: float = field(default_factory=time.perf_counter)
    states: list[str] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    llm_calls: list[CallRecord] = field(default_factory=list)
    hash_counts: dict[str, int] = field(default_factory=dict)
    rag_queries: int = 0
    replans: int = 0
    variants: int = 0
    intent: str | None = None
    intent_confidence: float | None = None
    intent_source: str | None = None
    workflow: str | None = None
    status: str = "running"
    error_code: str | None = None
    ranking_config_version: str | None = None
    limits: dict = field(default_factory=lambda: {
        "MAX_TOOL_CALLS": MAX_TOOL_CALLS, "MAX_STATE_TRANSITIONS": MAX_STATE_TRANSITIONS,
        "MAX_CLARIFICATIONS": MAX_CLARIFICATIONS, "MAX_REPLANS": MAX_REPLANS,
        "MAX_IDENTICAL_TOOL_CALLS": MAX_IDENTICAL_TOOL_CALLS, "MAX_RAG_QUERIES": MAX_RAG_QUERIES,
        "MAX_PLAN_VARIANTS": MAX_PLAN_VARIANTS, "MAX_LLM_CALLS": MAX_LLM_CALLS})

    # --- enforcement ------------------------------------------------------------

    def enter(self, state: str) -> None:
        if len(self.states) >= self.limits["MAX_STATE_TRANSITIONS"]:
            raise LimitExceeded("MAX_STATE_TRANSITIONS", len(self.states) + 1)
        self.states.append(state)

    def before_tool(self, tool_name: str, args: dict) -> str:
        if len(self.tool_calls) >= self.limits["MAX_TOOL_CALLS"]:
            raise LimitExceeded("MAX_TOOL_CALLS", len(self.tool_calls) + 1)
        h = canonical_hash(tool_name, args)
        count = self.hash_counts.get(h, 0)
        if count >= self.limits["MAX_IDENTICAL_TOOL_CALLS"]:
            raise LimitExceeded("MAX_IDENTICAL_TOOL_CALLS", count + 1)
        self.hash_counts[h] = count + 1
        if tool_name in ("retrieve_bengaluru_knowledge", "answer_grounded_question"):
            if self.rag_queries >= self.limits["MAX_RAG_QUERIES"]:
                raise LimitExceeded("MAX_RAG_QUERIES", self.rag_queries + 1)
            self.rag_queries += 1
        if tool_name in ("build_itinerary", "modify_itinerary"):
            if self.replans >= self.limits["MAX_REPLANS"]:
                raise LimitExceeded("MAX_REPLANS", self.replans + 1)
            self.replans += 1
        if tool_name == "create_what_if_variant":
            if self.variants >= self.limits["MAX_PLAN_VARIANTS"]:
                raise LimitExceeded("MAX_PLAN_VARIANTS", self.variants + 1)
            self.variants += 1
        return h

    def after_tool(self, tool_name: str, h: str, status: str, error_code: str | None,
                   latency_ms: int) -> None:
        self.tool_calls.append(ToolCallRecord(len(self.tool_calls) + 1, tool_name, h, status,
                                              error_code, latency_ms))

    def record_llm(self, rec: CallRecord) -> None:
        if len(self.llm_calls) >= self.limits["MAX_LLM_CALLS"]:
            raise LimitExceeded("MAX_LLM_CALLS", len(self.llm_calls) + 1)
        self.llm_calls.append(rec)

    def llm_budget_left(self) -> bool:
        return len(self.llm_calls) < self.limits["MAX_LLM_CALLS"]

    @property
    def latency_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)

    def summary(self) -> dict:
        return {
            "trace_id": str(self.trace_id), "intent": self.intent,
            "intent_confidence": self.intent_confidence, "intent_source": self.intent_source,
            "workflow": self.workflow, "states": self.states, "status": self.status,
            "error_code": self.error_code, "latency_ms": self.latency_ms,
            "tool_calls": [{"tool": t.tool_name, "args_hash": t.args_hash[:16],
                            "status": t.status, "latency_ms": t.latency_ms}
                           for t in self.tool_calls],
            "llm_calls": [{"task": c.task, "model": c.model, "prompt_version": c.prompt_version,
                           "prompt_hash": c.prompt_hash[:16], "status": c.status,
                           "cached": c.cached, "latency_ms": c.latency_ms}
                          for c in self.llm_calls],
            "ranking_config_version": self.ranking_config_version,
        }
