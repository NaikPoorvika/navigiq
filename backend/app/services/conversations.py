"""Conversation persistence and the assistant chat entry point.

Owns: loading/creating a conversation for its owner, running the agent with
an overall timeout, and persisting the turn (messages, bounded state, trace).
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.agent import Agent
from app.assistant.response import ERROR_MESSAGES, AssistantResponse
from app.assistant.state import ConversationState
from app.assistant.tools import Role
from app.models.conversation import Conversation, Message
from app.services.observability import persist_trace
from app.services.planning.store import Owner

AGENT_TIMEOUT_S = 90.0
MAX_MESSAGES_RETURNED = 50


class ConversationNotFound(Exception):
    pass


async def load_or_create(db: AsyncSession, conversation_id: str | None,
                         owner: Owner) -> Conversation:
    if conversation_id:
        try:
            cid = uuid.UUID(conversation_id)
        except ValueError:
            raise ConversationNotFound("conversation not found")
        conv = await db.get(Conversation, cid)
        if conv is None or not _owns(conv, owner):
            raise ConversationNotFound("conversation not found")
        return conv
    conv = Conversation(user_id=owner.user_id,
                        session_id=None if owner.user_id else owner.session_id, state={})
    db.add(conv)
    await db.commit()
    return conv


def _owns(conv: Conversation, owner: Owner) -> bool:
    if conv.user_id is not None:
        return owner.user_id is not None and conv.user_id == owner.user_id
    return owner.session_id is not None and conv.session_id == owner.session_id


async def chat(db: AsyncSession, *, message: str, conversation_id: str | None, owner: Owner,
               role: Role, llm, gateway) -> AssistantResponse:
    conv = await load_or_create(db, conversation_id, owner)
    state = ConversationState.model_validate(conv.state or {})
    agent = Agent(db=db, owner=owner, role=role, state=state, conversation_id=str(conv.id),
                  llm=llm, gateway=gateway)
    try:
        response = await asyncio.wait_for(agent.run(message), timeout=AGENT_TIMEOUT_S)
    except asyncio.TimeoutError:
        agent.trace.status = "failed"
        agent.trace.error_code = "TIMEOUT"
        await db.rollback()
        response = agent.respond(agent.trace.intent or "UNKNOWN",
                                 "That took too long, so I stopped. Please try again.", "error",
                                 data={"error": {"code": "TIMEOUT"}})
    try:
        db.add(Message(conversation_id=conv.id, role="user", content=message[:2000]))
        db.add(Message(conversation_id=conv.id, role="assistant", content=response.text[:4000],
                       payload=response.model_dump(mode="json"), intent=response.intent,
                       trace_id=agent.trace.trace_id))
        await db.execute(text("UPDATE conversations SET state = CAST(:s AS jsonb), "
                              "summary = :sum, updated_at = now() WHERE id = :id"),
                         {"s": state.model_dump_json(), "sum": state.summary[:500], "id": conv.id})
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        response.warnings.append(ERROR_MESSAGES["DATABASE_UNAVAILABLE"])
    await persist_trace(db, agent.trace, conversation_id=conv.id, user_id=owner.user_id)
    return response


async def history(db: AsyncSession, conversation_id: str, owner: Owner) -> dict:
    conv = await load_or_create(db, conversation_id, owner)
    rows = (await db.execute(text("""
        SELECT role, content, payload, intent, created_at FROM messages
        WHERE conversation_id = :c ORDER BY id DESC LIMIT :n
    """), {"c": conv.id, "n": MAX_MESSAGES_RETURNED})).all()
    return {"conversation_id": str(conv.id),
            "state": ConversationState.model_validate(conv.state or {}).model_dump(
                include={"active_itinerary_id", "active_version_no", "pending_variant_id"}),
            "messages": [{"role": r.role, "content": r.content, "payload": r.payload,
                          "intent": r.intent, "created_at": r.created_at.isoformat()}
                         for r in reversed(rows)]}
