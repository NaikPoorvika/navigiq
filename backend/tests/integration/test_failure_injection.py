"""Failure injection (sections 54, 119).

Each dependency is broken on purpose and the product must degrade the way
the architecture promises - never crash, never fake, never leak internals:

  Ollama down / timing out / malformed  -> rules, extractive answers, the
                                           structured planner; flagged in the UI
  weather down                          -> plans without weather optimisation,
                                           a visible warning, no invented forecast
  Redis down                            -> reported by /health, requests unaffected
  database down                         -> 503 DATABASE_UNAVAILABLE / a clean
                                           assistant error, no stack trace
  embeddings down                       -> sparse-only retrieval, noted
  empty retrieval                       -> the fixed refusal
  infeasible request                    -> INFEASIBLE with relaxations
  agent limit breached                  -> AGENT_LIMIT, FAIL state
  agent overall timeout                 -> TIMEOUT response, turn still persisted
"""
from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.assistant.agent import Agent
from app.assistant.state import ConversationState
from app.assistant.tools import Role
from app.llm import FakeLLM
from app.llm.errors import LLMTimeout, LLMUnavailable
from app.llm.service import LLMService
from app.services.planning.store import Owner

pytestmark = pytest.mark.db

PLAN = {"version": "2.0", "start_time": "10:00", "end_time": "17:00",
        "interests": ["garden", "museum", "cafe"]}


def sid() -> dict:
    return {"X-NavigIQ-Session": f"fail-{uuid.uuid4().hex[:20]}"}


async def chat(client, message, h, cid=None) -> dict:
    r = await client.post("/api/v1/assistant/chat", headers=h,
                          json={"message": message, "conversation_id": cid})
    assert r.status_code == 200, r.text
    assert "traceback" not in r.text.lower()
    return r.json()


def raising(exc_factory):
    def respond(_messages):
        raise exc_factory()
    return respond


# --- the language model ------------------------------------------------------------------------

@pytest.mark.parametrize("failure", [
    lambda: LLMUnavailable("ollama is down"),
    lambda: LLMTimeout("ollama timed out"),
])
async def test_assistant_keeps_working_when_the_model_fails(async_client, fake_llm_service,
                                                            failure):
    svc = fake_llm_service(responder=raising(failure))
    h = sid()
    bored = await chat(async_client, "I'm bored", h)
    assert bored["ui"]["type"] == "discovery" and bored["data"]["items"]
    search = await chat(async_client, "quiet cafe near Testnagar", h, bored["conversation_id"])
    assert search["data"]["items"] and search["data"]["items"][0]["category"] == "cafe"
    ans = await chat(async_client, "Why is Test Garden famous?", h)
    assert ans["ui"]["type"] == "knowledge_answer" and ans["sources"]
    plan = await chat(async_client, "Plan tomorrow from 10 to 5 with a garden and a museum", h)
    assert plan["ui"]["type"] == "itinerary" and plan["data"]["validator_report"]["valid"]
    # repeated failures open the breaker; the UI is told the assistant is degraded
    assert not svc.available
    last = await chat(async_client, "Surprise me", h)
    assert last["llm_available"] is False and last["data"]["items"]
    # the non-assistant product never touched the model
    assert (await async_client.get("/api/v1/pois?q=garden")).status_code == 200
    assert (await async_client.post("/api/v1/plans", headers=h, json=PLAN)).status_code == 201


async def test_malformed_model_output_falls_back_to_rules(async_client, fake_llm_service):
    fake_llm_service(responder=lambda _m: "this is not json {")
    h = sid()
    r = await chat(async_client, "Plan tomorrow from 10 to 5 with a garden and a museum", h)
    assert r["intent"] == "CREATE_ITINERARY" and r["ui"]["type"] == "itinerary"
    assert r["llm_used"] is False


async def test_llm_down_keeps_structured_extraction_working(async_client, fake_llm_service):
    fake_llm_service(responder=raising(lambda: LLMUnavailable("down")))
    r = await async_client.post("/api/v1/trip-spec/extract",
                                json={"text": "tomorrow 10am to 6pm, museums and cafes, 800 each"})
    assert r.status_code == 200
    body = r.json()
    assert body["llm_used"] is False
    assert body["trip_spec"]["start_time"] == "10:00" and body["trip_spec"]["end_time"] == "18:00"


# --- weather -------------------------------------------------------------------------------------

@pytest.fixture
def weather_down(monkeypatch):
    from app.config import settings
    from app.services.weather import client as weather

    async def boom(*_a, **_k):
        raise httpx.ConnectError("open-meteo unreachable")
    monkeypatch.setattr(settings, "WEATHER_ENABLED", True)
    monkeypatch.setattr(weather, "_fetch_day", boom)
    weather._cache.clear()
    yield


async def test_weather_outage_degrades_plans_and_answers(async_client, weather_down):
    from datetime import timedelta

    from app.nlu.timeparse import today_ist
    h = sid()
    tomorrow = (today_ist() + timedelta(days=1)).isoformat()
    r = await async_client.post("/api/v1/plans", headers=h, json={**PLAN, "date": tomorrow})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["weather"]["available"] is False
    w = await async_client.get("/api/v1/weather")
    assert w.status_code == 200 and w.json()["available"] is False
    ans = await chat(async_client, "Will it rain today?", h)
    assert "won't guess" in ans["text"] and ans["warnings"]
    assert "°C" not in ans["text"]


# --- redis ---------------------------------------------------------------------------------------

async def test_redis_outage_is_reported_but_harmless(async_client, monkeypatch):
    from redis.asyncio import Redis

    from app.config import settings
    from app.core import redis as redis_mod
    monkeypatch.setattr(settings, "REDIS_ENABLED", True)
    monkeypatch.setattr(redis_mod, "redis_client",
                        Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2))
    r = await async_client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["redis"] == "error" and r.json()["database"] == "ok"
    assert (await async_client.get("/api/v1/pois?limit=3")).status_code == 200


# --- the database --------------------------------------------------------------------------------

@pytest.fixture
def broken_engine():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    engine = create_async_engine("postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none",
                                 poolclass=NullPool, connect_args={"timeout": 2})
    yield async_sessionmaker(engine, expire_on_commit=False)


async def test_database_outage_returns_503_without_internals(test_database, broken_engine):
    from app.api import deps
    from app.main import app

    async def broken_db():
        async with broken_engine() as s:
            yield s
    app.dependency_overrides[deps.get_db] = broken_db
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/v1/pois?limit=3")
            assert r.status_code == 503
            assert r.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
            low = r.text.lower()
            assert "traceback" not in low and "asyncpg" not in low and "127.0.0.1" not in low
    finally:
        app.dependency_overrides.pop(deps.get_db, None)


async def test_agent_reports_database_outage_cleanly(broken_engine):
    async with broken_engine() as db:
        agent = Agent(db=db, owner=Owner(None, "fail-db-000000001"), role=Role.ANONYMOUS,
                      state=ConversationState(), conversation_id="c")
        resp = await agent.run("quiet cafe near Testnagar")
    assert resp.ui["type"] == "error"
    assert resp.data["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert agent.trace.status == "failed" and agent.trace.states[-1] == "FAIL"
    assert "asyncpg" not in resp.text.lower()


# --- retrieval -----------------------------------------------------------------------------------

class NoEmbeddings(FakeLLM):
    async def embed(self, texts):
        raise LLMUnavailable("embedding model is down")


async def test_embedding_outage_falls_back_to_sparse_retrieval(db):
    from app.knowledge.retrieval import retrieve
    res = await retrieve(db, "When was Test Garden laid out?", k=4, gateway=NoEmbeddings())
    assert not res.dense_available
    assert res.chunks and "Test Garden" in res.chunks[0].title
    assert any("dense retrieval unavailable" in n for n in res.notes)


async def test_nothing_relevant_means_the_fixed_refusal(db):
    from app.knowledge.answer import UNKNOWN, answer_question
    ans = await answer_question(db, "What is the airspeed velocity of an unladen swallow?")
    assert ans.text == UNKNOWN and not ans.answerable and ans.sources == []


# --- planning and the agent's own limits -------------------------------------------------------------

async def test_impossible_plan_is_infeasible_with_relaxations(db):
    agent = Agent(db=db, owner=Owner(None, "fail-infeasible-01"), role=Role.ANONYMOUS,
                  state=ConversationState(), conversation_id="c")
    resp = await agent.run("Plan today from 10:00 to 10:30 with 6 stops, a museum, a lake, a "
                           "fort and a garden, budget 20 rupees")
    assert resp.ui["type"] in ("feasibility_error", "clarification"), resp.text
    if resp.ui["type"] == "feasibility_error":
        assert "itinerary" not in resp.data


async def test_limit_breach_ends_in_a_clean_fail(db):
    agent = Agent(db=db, owner=Owner(None, "fail-limit-000001"), role=Role.ANONYMOUS,
                  state=ConversationState(), conversation_id="c")
    agent.trace.limits["MAX_TOOL_CALLS"] = 0
    resp = await agent.run("quiet cafe near Testnagar")
    assert resp.data["error"] == {"code": "AGENT_LIMIT", "limit": "MAX_TOOL_CALLS"}
    assert agent.trace.status == "failed" and agent.trace.error_code == "AGENT_LIMIT"
    assert agent.trace.states[-1] == "FAIL"


class SlowGateway:
    generation_model = "slow"
    embedding_model = "slow"
    embedding_dimension = 768

    async def generate(self, *a, **k):
        await asyncio.sleep(5)
        raise LLMTimeout("never answers")

    async def embed(self, texts):
        raise LLMUnavailable("no")


async def test_agent_timeout_still_persists_the_turn(db, monkeypatch):
    from app.services import conversations
    monkeypatch.setattr(conversations, "AGENT_TIMEOUT_S", 0.3)
    owner = Owner(None, "fail-timeout-00001")
    llm = LLMService(SlowGateway(), cache_ttl_s=0)
    resp = await conversations.chat(db, message="how is bengaluru's culture?",
                                    conversation_id=None, owner=owner, role=Role.ANONYMOUS,
                                    llm=llm, gateway=llm.gateway)
    assert resp.data["error"]["code"] == "TIMEOUT"
    n = (await db.execute(text("SELECT count(*) FROM messages WHERE conversation_id = "
                               "CAST(:c AS uuid)"), {"c": resp.conversation_id})).scalar()
    assert n == 2
    run = (await db.execute(text("SELECT status, error_code FROM agent_runs WHERE id = "
                                 "CAST(:t AS uuid)"), {"t": resp.trace_id})).first()
    assert run.status == "failed" and run.error_code == "TIMEOUT"
