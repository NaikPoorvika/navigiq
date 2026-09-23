"""Endpoint-level tests for POST /api/v1/plan/draft (Change #4).

Covers the response-contract discriminator specifically: both the
clarification path and the successful-plan path must carry an explicit
`needs_clarification` boolean, so a caller never has to infer the outcome
from the presence or absence of unrelated fields (`days`, `tripspec`, ...).

The clarification-path tests need no database (see test_draft_builder.py:
_resolve() short-circuits before any query when a place ref is None). The
successful-path test does need the places table and is skipped cleanly if
it is not reachable, the same convention test_routing.py uses for OSRM.
"""
from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import deps

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq")
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

from app.main import app  # noqa: E402


def _places_gazetteer_up() -> bool:
    """Best-effort check that origin resolution will actually work, not
    just that Postgres is reachable - the two have been observed to diverge
    (see the final report for this task)."""
    from app.config import settings
    try:
        import asyncio

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        async def probe() -> bool:
            engine = create_async_engine(settings.DATABASE_URL)
            try:
                async with engine.connect() as conn:
                    await conn.execute(
                        text("SELECT kind FROM places LIMIT 1"))
                return True
            finally:
                await engine.dispose()

        return asyncio.run(probe())
    except Exception:  # noqa: BLE001 - any failure means "not usable"
        return False


@pytest_asyncio.fixture
async def async_client():
    """A client whose database work stays inside this test's event loop.

    Without the override the request uses the application's shared engine,
    whose pooled asyncpg connections belong to whatever loop created them -
    and a pooled connection touched from a later test's loop fails with
    "Event loop is closed". NullPool means a connection is never reused
    across tests.
    """
    engine = create_async_engine(DB_URL, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def get_test_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[deps.get_db] = get_test_db
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()

pytestmark = pytest.mark.asyncio


# --- clarification path: no database access required -----------------------

async def test_clarification_response_has_explicit_discriminator(async_client):
    response = await async_client.post("/api/v1/plan/draft", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["needs_clarification"] is True
    assert isinstance(body["clarifications"], list)
    assert body["clarifications"], "an empty draft must ask something"
    assert isinstance(body["assumptions"], list)
    assert body["tripspec"] is None


async def test_clarification_response_shape_matches_the_documented_contract(
        async_client):
    response = await async_client.post(
        "/api/v1/plan/draft", json={"date_phrase": "not a real phrase"})
    body = response.json()
    assert body["needs_clarification"] is True
    # "resolved" carries what was worked out before a question stopped the
    # build - date, times, party size - so the UI doesn't re-resolve them
    # and drift from the server's answer.
    assert set(body.keys()) == {
        "needs_clarification", "clarifications", "assumptions", "tripspec", "resolved"}
    for clarification in body["clarifications"]:
        assert set(clarification.keys()) == {"field", "question", "options"}


async def test_clarification_cap_holds_through_the_endpoint(async_client):
    response = await async_client.post(
        "/api/v1/plan/draft", json={"date_phrase": "not a real phrase"})
    body = response.json()
    from app.services.planning.draft_builder import MAX_CLARIFICATIONS
    assert len(body["clarifications"]) <= MAX_CLARIFICATIONS


async def test_malformed_draft_is_rejected_before_the_handler_runs(
        async_client):
    """A schema-invalid body (Change #1's strict time pattern) must fail as
    a 422 from FastAPI/Pydantic, not reach build_tripspec at all."""
    response = await async_client.post(
        "/api/v1/plan/draft", json={"start_time_local": "9:00"})
    assert response.status_code == 422


# --- successful path: needs the real places gazetteer -----------------------

@pytest.mark.skipif(not _places_gazetteer_up(),
                    reason="places table with a working 'kind' column is "
                          "not available - see the final report for this "
                          "task, this is a pre-existing environment issue")
async def test_successful_response_has_explicit_false_discriminator(
        async_client):
    response = await async_client.post("/api/v1/plan/draft", json={
        "origin": {"name": "Koramangala"},
        "date_phrase": "saturday",
        "interests": [{"category": "cafe"}],
    })
    body = response.json()
    assert body["needs_clarification"] is False
    assert "tripspec" in body and body["tripspec"] is not None
    assert "days" in body
    assert "assumptions" in body
    assert "attribution" in body
