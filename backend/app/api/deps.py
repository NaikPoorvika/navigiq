"""Request dependencies: database session, identity, ownership, rate limits.

Identity: a valid `Authorization: Bearer <access token>` makes the caller a
signed-in user. Otherwise the caller is anonymous and is identified only by
the opaque `X-NavigIQ-Session` header the browser generates - enough to own
the plans and conversations it creates, nothing more. Anonymous exploration
never requires an account (section 70).
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections import OrderedDict
from typing import AsyncGenerator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.tools import Role
from app.core.security import decode_access_token
from app.crud.crud_user import get_user
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.services.planning.store import Owner

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def api_error(http_status: int, code: str, message: str, **details) -> HTTPException:
    return HTTPException(status_code=http_status,
                         detail={"error": {"code": code, "message": message,
                                           "details": details or None}})


async def optional_user(authorization: str | None = Header(default=None),
                        db: AsyncSession = Depends(get_db)) -> User | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "UNAUTHORIZED", "invalid authorization header")
    sub = decode_access_token(token.strip())
    if sub is None:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "TOKEN_INVALID",
                        "the access token is invalid or expired")
    try:
        user = await get_user(db, uuid.UUID(sub))
    except ValueError:
        user = None
    if user is None or not user.is_active:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "TOKEN_INVALID", "account unavailable")
    return user


async def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "UNAUTHORIZED", "sign in required")
    return user


def session_id(x_navigiq_session: str | None = Header(default=None)) -> str | None:
    if x_navigiq_session is None:
        return None
    if not SESSION_RE.match(x_navigiq_session):
        raise api_error(status.HTTP_400_BAD_REQUEST, "INVALID_SESSION",
                        "X-NavigIQ-Session must be 16-64 characters of [A-Za-z0-9_-]")
    return x_navigiq_session


async def owner(user: User | None = Depends(optional_user),
                sid: str | None = Depends(session_id)) -> Owner:
    return Owner(user_id=user.id if user else None, session_id=sid)


def role_of(user: User | None) -> Role:
    return Role.USER if user is not None else Role.ANONYMOUS


class RateLimiter:
    """Fixed-window counter per key. Protects the costly endpoints (assistant,
    auth) from abuse.

    With Redis the counter is shared, so the limit holds across several API
    worker processes. Without Redis (disabled, or down) it falls back to a
    bounded in-memory counter per process - still a limit, just per worker.
    A Redis outage never fails a request and is not retried for a while.
    """

    REDIS_BACKOFF_S = 30.0

    def __init__(self, name: str, limit: int, window_s: float, max_keys: int = 10_000) -> None:
        self.name = name
        self.limit = limit
        self.window_s = window_s
        self.max_keys = max_keys
        self._hits: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self._redis_down_until = 0.0

    def _memory_count(self, key: str) -> int:
        now = time.monotonic()
        start, count = self._hits.get(key, (now, 0))
        if now - start >= self.window_s:
            start, count = now, 0
        count += 1
        self._hits[key] = (start, count)
        self._hits.move_to_end(key)
        while len(self._hits) > self.max_keys:
            self._hits.popitem(last=False)
        return count

    async def _redis_count(self, key: str) -> int | None:
        from app.config import settings
        if not settings.REDIS_ENABLED or time.monotonic() < self._redis_down_until:
            return None
        from app.core.redis import redis_client
        window = int(time.time() // self.window_s)
        rk = f"navigiq:rl:{self.name}:{key}:{window}"
        try:
            pipe = redis_client.pipeline()
            pipe.incr(rk)
            pipe.expire(rk, int(self.window_s) + 5)
            count, _ = await asyncio.wait_for(pipe.execute(), 0.5)
            return int(count)
        except Exception:  # noqa: BLE001 - degrade to the in-process counter
            self._redis_down_until = time.monotonic() + self.REDIS_BACKOFF_S
            return None

    async def check(self, key: str) -> None:
        count = await self._redis_count(key)
        if count is None:
            count = self._memory_count(key)
        if count > self.limit:
            raise api_error(status.HTTP_429_TOO_MANY_REQUESTS, "RATE_LIMITED",
                            "too many requests - please slow down")


assistant_limiter = RateLimiter("assistant", limit=30, window_s=60)
auth_limiter = RateLimiter("auth", limit=20, window_s=60)


def client_key(request: Request, user: User | None = None, sid: str | None = None) -> str:
    if user is not None:
        return f"u:{user.id}"
    if sid:
        return f"s:{sid}"
    return f"ip:{request.client.host if request.client else 'unknown'}"
