"""Assistant execution traces (section 76). Retention is bounded by
TRACE_RETENTION_DAYS and enforced by app.services.observability.prune.

Stored: intent, workflow, states visited, tool names with canonical argument
hashes, latencies, LLM task/model/prompt version/prompt hash, status. Never
stored: passwords, tokens, or raw prompt/response text.
"""
import uuid

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index,
    Integer, Numeric, SmallInteger, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base_class import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)  # trace id
    conversation_id = Column(UUID(as_uuid=True),
                             ForeignKey("conversations.id", ondelete="CASCADE"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"))
    intent = Column(String(40))
    intent_confidence = Column(Numeric(4, 3))
    intent_source = Column(String(10))
    workflow = Column(String(40))
    states = Column(JSONB, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="running")
    error_code = Column(String(40))
    tool_call_count = Column(SmallInteger, nullable=False, default=0)
    llm_call_count = Column(SmallInteger, nullable=False, default=0)
    ranking_config_version = Column(String(20))
    latency_ms = Column(Integer)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id = Column(BigInteger, primary_key=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"),
                    nullable=False, index=True)
    seq = Column(SmallInteger, nullable=False)
    tool_name = Column(String(60), nullable=False)
    args_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False)
    error_code = Column(String(40))
    latency_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LLMCall(Base):
    __tablename__ = "llm_calls"
    id = Column(BigInteger, primary_key=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"),
                    index=True)
    task = Column(String(40), nullable=False)
    model = Column(String(80), nullable=False)
    prompt_version = Column(String(20), nullable=False)
    prompt_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False)
    error_code = Column(String(40))
    cached = Column(Boolean, nullable=False, default=False)
    latency_ms = Column(Integer)
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(BigInteger, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"))
    session_id = Column(String(64))
    target_type = Column(String(20), nullable=False)
    target_id = Column(String(80), nullable=False)
    rating = Column(SmallInteger, nullable=False)
    comment = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("rating IN (-1, 0, 1)", name="ck_feedback_rating"),
        CheckConstraint("char_length(coalesce(comment, '')) <= 2000", name="ck_feedback_len"),
        CheckConstraint("target_type IN ('answer','poi','itinerary','recommendation')",
                        name="ck_feedback_target"),
        Index("ix_feedback_target", "target_type", "target_id"),
    )
