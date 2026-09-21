"""Conversations and messages.

`state` is the structured conversational context (active itinerary, last
shown POIs, current TripSpec, recently shown ids for novelty). It is bounded
by app.services.assistant.state so it cannot grow without limit.
"""
import uuid

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base_class import Base


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), index=True)
    session_id = Column(String(64), index=True)
    state = Column(JSONB, nullable=False, default=dict)
    summary = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"
    id = Column(BigInteger, primary_key=True)
    conversation_id = Column(UUID(as_uuid=True),
                             ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(12), nullable=False)
    content = Column(Text, nullable=False)
    payload = Column(JSONB)
    intent = Column(String(40))
    trace_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_messages_conversation", "conversation_id", "id"),)
