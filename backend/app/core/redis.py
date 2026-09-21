"""Optional Redis. Every caller degrades when it is down (section 119):
NavigIQ's caches are in-process and Redis is only an accelerator, so a Redis
outage is reported by /health but never breaks a request."""
from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from app.config import settings

redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True,
                              socket_connect_timeout=0.5, socket_timeout=0.5)


async def redis_ping() -> bool:
    if not settings.REDIS_ENABLED:
        return False
    try:
        return bool(await asyncio.wait_for(redis_client.ping(), 1.0))
    except Exception:  # noqa: BLE001
        return False


async def get_redis():
    return redis_client
