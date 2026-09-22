"""Sign-up, login and profile through the real API and database.

Each test gets its own NullPool engine (asyncpg connections cannot be shared
across pytest-asyncio event loops) and cleans up the users it creates.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import deps
from app.main import app

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq")
TEST_DOMAIN = "@auth-test.navigiq.local"


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(DB_URL, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def get_test_db():
        async with sessions() as s:
            yield s

    app.dependency_overrides[deps.get_db] = get_test_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.execute(text('DELETE FROM "user" WHERE email LIKE :d'), {"d": f"%{TEST_DOMAIN}"})
    await engine.dispose()


def new_email() -> str:
    return f"t{uuid.uuid4().hex[:10]}{TEST_DOMAIN}"


async def sign_up(client, email, password="secret123"):
    return await client.post("/api/v1/auth/users", json={"email": email, "password": password})


async def log_in(client, email, password="secret123"):
    r = await client.post("/api/v1/auth/login/access-token",
                          data={"username": email, "password": password})
    return r


async def token_for(client, email) -> dict:
    await sign_up(client, email)
    r = await log_in(client, email)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_cannot_register_as_superuser(client):
    r = await client.post("/api/v1/auth/users", json={
        "email": new_email(), "password": "secret123", "is_superuser": True})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_new_user_is_never_superuser(client):
    r = await sign_up(client, new_email())
    assert r.status_code == 200
    assert r.json()["is_superuser"] is False


@pytest.mark.asyncio
async def test_email_case_does_not_create_a_second_account(client):
    email = new_email()
    assert (await sign_up(client, email.upper())).status_code == 200
    assert (await sign_up(client, email)).status_code == 400
    assert (await log_in(client, email.upper())).status_code == 200


@pytest.mark.asyncio
async def test_weak_password_rejected(client):
    assert (await sign_up(client, new_email(), password="short")).status_code == 422


@pytest.mark.asyncio
async def test_wrong_password_rejected(client):
    email = new_email()
    await sign_up(client, email)
    assert (await log_in(client, email, "wrongpass1")).status_code == 400


@pytest.mark.asyncio
async def test_me_requires_a_token(client):
    assert (await client.get("/api/v1/auth/users/me")).status_code == 401


@pytest.mark.asyncio
async def test_profile_round_trip(client):
    headers = await token_for(client, new_email())
    r = await client.patch("/api/v1/auth/users/me", headers=headers, json={
        "display_name": "Poorvika",
        "home": {"name": "Koramangala", "lat": 12.9357, "lon": 77.6241},
        "interests": ["cafe", "park", "cafe"],
        "vegetarian": True,
    })
    assert r.status_code == 200, r.text
    me = (await client.get("/api/v1/auth/users/me", headers=headers)).json()
    assert me["display_name"] == "Poorvika"
    assert me["home_name"] == "Koramangala" and me["home_lat"] == 12.9357
    assert me["interests"] == ["cafe", "park"]          # de-duplicated, order kept
    assert me["vegetarian"] is True


@pytest.mark.asyncio
async def test_patch_changes_only_what_was_sent(client):
    headers = await token_for(client, new_email())
    await client.patch("/api/v1/auth/users/me", headers=headers,
                       json={"display_name": "A", "vegetarian": True})
    r = await client.patch("/api/v1/auth/users/me", headers=headers, json={"display_name": "B"})
    assert r.json()["display_name"] == "B" and r.json()["vegetarian"] is True


@pytest.mark.asyncio
async def test_unknown_interest_rejected(client):
    headers = await token_for(client, new_email())
    r = await client.patch("/api/v1/auth/users/me", headers=headers, json={"interests": ["arcades"]})
    assert r.status_code == 422
    assert r.json()["detail"]["error"]["code"] == "SEMANTIC_INVALID"


@pytest.mark.asyncio
async def test_home_outside_region_rejected(client):
    headers = await token_for(client, new_email())
    r = await client.patch("/api/v1/auth/users/me", headers=headers,
                           json={"home": {"name": "Delhi", "lat": 28.61, "lon": 77.21}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_profile_cannot_grant_superuser(client):
    headers = await token_for(client, new_email())
    r = await client.patch("/api/v1/auth/users/me", headers=headers, json={"is_superuser": True})
    assert r.status_code == 422


# ------------------------------------------------------------ delete account

async def delete_me(client, headers, password="secret123"):
    return await client.request("DELETE", "/api/v1/auth/users/me",
                                headers=headers, json={"password": password})


@pytest.mark.asyncio
async def test_delete_needs_the_right_password(client):
    email = new_email()
    headers = await token_for(client, email)
    assert (await delete_me(client, headers, "wrongpass1")).status_code == 400
    assert (await log_in(client, email)).status_code == 200      # still there


@pytest.mark.asyncio
async def test_deleted_account_is_gone(client):
    email = new_email()
    headers = await token_for(client, email)
    assert (await delete_me(client, headers)).status_code == 204
    assert (await log_in(client, email)).status_code == 400      # can't sign in
    me = await client.get("/api/v1/auth/users/me", headers=headers)
    assert me.status_code in (401, 404)                          # old token is useless


@pytest.mark.asyncio
async def test_email_can_be_reused_after_deletion(client):
    email = new_email()
    headers = await token_for(client, email)
    await delete_me(client, headers)
    assert (await sign_up(client, email)).status_code == 200


@pytest.mark.asyncio
async def test_delete_requires_a_token(client):
    r = await client.request("DELETE", "/api/v1/auth/users/me", json={"password": "secret123"})
    assert r.status_code == 401
