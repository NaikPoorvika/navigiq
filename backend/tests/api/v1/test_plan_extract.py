"""NQ-029 - endpoint tests for POST /api/v1/plan/extract.

No database, no GPU, no Ollama: the gateway dependency is overridden with a
FakeLLM, which is the whole reason extraction reaches the handler through
`Depends(get_llm_gateway)` rather than being constructed inside it.

What matters here beyond "it returns 200": every failure mode must arrive as
a distinct, stable code the frontend can switch on, and no model or user
text may be echoed back in an error body.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq",
)

from app.api.deps import get_llm_gateway  # noqa: E402
from app.llm import (  # noqa: E402
    FakeLLM,
    LLMEmptyResponse,
    LLMMalformedResponse,
    LLMRequestRejected,
    LLMTimeout,
    LLMTruncated,
    LLMUnavailable,
)
from app.main import app  # noqa: E402

pytestmark = pytest.mark.asyncio

DRAFT = {"origin": {"name": "Koramangala"}, "date_phrase": "tomorrow",
         "interests": [{"category": "cafe"}]}


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_llm_gateway, None)


def _use(gateway: FakeLLM) -> FakeLLM:
    app.dependency_overrides[get_llm_gateway] = lambda: gateway
    return gateway


def _scripted(*items) -> FakeLLM:
    return _use(FakeLLM(responses=[
        i if isinstance(i, (str, Exception)) else json.dumps(i)
        for i in items]))


# --- the happy path ---------------------------------------------------------

async def test_a_request_becomes_a_draft(client):
    _scripted(DRAFT)
    response = await client.post("/api/v1/plan/extract",
                                 json={"text": "a cafe in Koramangala tomorrow"})
    assert response.status_code == 200
    body = response.json()
    assert body["draft"]["origin"] == {"name": "Koramangala"}
    assert body["draft"]["date_phrase"] == "tomorrow"
    assert body["draft"]["interests"] == [
        {"category": "cafe", "count": 1, "priority": "should"}]
    assert body["prompt_version"] == "v1"
    assert body["model"] == "fake-generation"


async def test_the_response_is_a_draft_only_and_does_not_plan(client):
    """Extraction and planning stay separate so the user can correct the
    draft first (NQ-033). A plan here would mean spending ~15 s of
    optimisation on a reading of the sentence nobody confirmed."""
    _scripted(DRAFT)
    response = await client.post("/api/v1/plan/extract",
                                 json={"text": "a cafe in Koramangala"})
    body = response.json()
    assert set(body) == {"draft", "model", "prompt_version", "latency_ms"}
    assert "itinerary" not in body
    assert "tripspec" not in body


async def test_the_draft_is_shaped_for_post_plan_draft(client):
    """The output of this endpoint must be accepted as the input of the
    existing one, unchanged - that is the contract between them."""
    from app.schemas.trip_draft import TripDraft

    _scripted(DRAFT)
    response = await client.post("/api/v1/plan/extract",
                                 json={"text": "a cafe in Koramangala"})
    TripDraft.model_validate(response.json()["draft"])


async def test_hallucinated_coordinates_do_not_reach_the_client(client):
    _scripted({"origin": {"name": "Koramangala", "lat": 12.93, "lon": 77.62}})
    response = await client.post("/api/v1/plan/extract",
                                 json={"text": "somewhere in Koramangala"})
    assert response.status_code == 200
    assert response.json()["draft"]["origin"] == {"name": "Koramangala"}
    assert "12.93" not in response.text


# --- failures: one stable code each -----------------------------------------

@pytest.mark.parametrize("answer,reason", [
    ("not json at all", "invalid_json"),
    ('```json\n{}\n```', "invalid_json"),
    ('[{"origin": {"name": "X"}}]', "not_an_object"),
    ('{"start_time_local": "9am"}', "schema_invalid"),
    ('{"interests": [{"category": "rooftop_bar_lounge"}]}', "schema_invalid"),
])
async def test_an_unusable_answer_is_422_with_a_reason(client, answer, reason):
    _scripted(answer)
    response = await client.post("/api/v1/plan/extract",
                                 json={"text": "plan me something"})
    assert response.status_code == 422
    error = response.json()["detail"]["error"]
    assert error["code"] == "EXTRACTION_FAILED"
    assert error["details"]["reason"] == reason


@pytest.mark.parametrize("error,status,code", [
    (LLMUnavailable("down"), 503, "LLM_UNAVAILABLE"),
    (LLMTimeout("slow"), 504, "LLM_TIMEOUT"),
    (LLMTruncated("capped"), 502, "LLM_ERROR"),
    (LLMEmptyResponse("empty"), 502, "LLM_ERROR"),
    (LLMMalformedResponse("no content"), 502, "LLM_ERROR"),
    (LLMRequestRejected("rejected", status_code=400), 502, "LLM_ERROR"),
])
async def test_each_gateway_failure_has_its_own_status(client, error, status,
                                                       code):
    """A model that is down (retry later) and a model that answered garbage
    (do not retry) are different problems for the caller."""
    _scripted(error)
    response = await client.post("/api/v1/plan/extract",
                                 json={"text": "plan me something"})
    assert response.status_code == status
    assert response.json()["detail"]["error"]["code"] == code


async def test_a_truncated_answer_is_never_returned_as_a_partial_draft(client):
    _scripted(LLMTruncated("hit the cap"))
    response = await client.post("/api/v1/plan/extract",
                                 json={"text": "plan me something"})
    assert response.status_code == 502
    assert "draft" not in response.json()


async def test_error_bodies_do_not_echo_user_or_model_text(client):
    _scripted("I'm sorry Ravi Kumar, I cannot plan trips for 9876543210")
    response = await client.post(
        "/api/v1/plan/extract",
        json={"text": "plan a trip for Ravi Kumar, 9876543210"})
    assert response.status_code == 422
    assert "Ravi" not in response.text
    assert "9876543210" not in response.text


# --- request validation, before any model call -------------------------------

@pytest.mark.parametrize("body", [
    {}, {"text": ""}, {"text": "x" * 2001}, {"text": 5}, {"txt": "hello"},
])
async def test_an_invalid_body_is_422_without_calling_the_model(client, body):
    gateway = _scripted(DRAFT)
    response = await client.post("/api/v1/plan/extract", json=body)
    assert response.status_code == 422
    assert gateway.generate_calls == []


# --- wiring -------------------------------------------------------------------

async def test_without_a_configured_gateway_the_endpoint_says_so(client):
    """ASGITransport does not run the lifespan, so app.state has no gateway
    here - the same state as a misconfigured deployment. It must be an
    explicit 503, never a silent connection attempt to some default host."""
    app.dependency_overrides.pop(get_llm_gateway, None)
    response = await client.post("/api/v1/plan/extract",
                                 json={"text": "a cafe in Koramangala"})
    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "LLM_UNAVAILABLE"


async def test_the_deterministic_draft_endpoint_still_needs_no_llm(client):
    """ADR-002: /plan/draft must keep working with no model at all. NQ-029
    adds a path, it does not put the LLM in front of the existing one."""
    app.dependency_overrides.pop(get_llm_gateway, None)
    response = await client.post("/api/v1/plan/draft", json={})
    assert response.status_code == 200
    assert response.json()["needs_clarification"] is True
