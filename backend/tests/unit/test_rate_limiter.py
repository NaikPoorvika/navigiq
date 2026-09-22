"""Rate limiting: shared through Redis across API workers, per-process when
Redis is unavailable, and never failing a request because Redis is down."""
from __future__ import annotations

import secrets

import pytest
from fastapi import HTTPException

from app.api.deps import RateLimiter
from app.config import settings


async def test_in_memory_limit_when_redis_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_ENABLED", False)
    lim = RateLimiter("t_mem", limit=3, window_s=60)
    for _ in range(3):
        await lim.check("k")
    with pytest.raises(HTTPException) as exc:
        await lim.check("k")
    assert exc.value.status_code == 429
    await lim.check("another-key")          # keys are independent


async def test_redis_outage_degrades_to_memory_and_backs_off(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_ENABLED", True)

    class Broken:
        def pipeline(self):
            raise ConnectionError("redis down")

    import app.core.redis as redis_mod
    monkeypatch.setattr(redis_mod, "redis_client", Broken())
    lim = RateLimiter("t_down", limit=2, window_s=60)
    await lim.check("k")
    await lim.check("k")
    with pytest.raises(HTTPException):
        await lim.check("k")
    # after one failure Redis isn't tried again for a while
    assert lim._redis_down_until > 0


async def test_limit_is_shared_through_redis(monkeypatch):
    """Two limiter instances stand in for two API worker processes."""
    import app.core.redis as redis_mod
    from redis.asyncio import Redis
    client = Redis.from_url("redis://localhost:6379/15", decode_responses=True,
                            socket_connect_timeout=0.5, socket_timeout=0.5)
    try:
        await client.ping()
    except Exception:  # noqa: BLE001
        pytest.skip("no local Redis")
    monkeypatch.setattr(settings, "REDIS_ENABLED", True)
    monkeypatch.setattr(redis_mod, "redis_client", client)
    name = f"t_shared_{secrets.token_hex(4)}"
    worker_a = RateLimiter(name, limit=3, window_s=60)
    worker_b = RateLimiter(name, limit=3, window_s=60)
    await worker_a.check("k")
    await worker_b.check("k")
    await worker_a.check("k")
    with pytest.raises(HTTPException):
        await worker_b.check("k")            # the 4th request, counted across both
    await client.aclose()
