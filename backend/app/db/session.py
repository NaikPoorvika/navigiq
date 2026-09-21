from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.db.base  # noqa: F401 - register every model: an ORM flush resolves foreign
#                         keys by table name, and a process that imported only
#                         some models failed with NoReferencedTableError
from app.config import settings

# Tests run each test in its own event loop; pooled asyncpg connections are
# bound to the loop that created them, so the test profile uses NullPool.
_pool_args = ({"poolclass": NullPool} if settings.APP_ENV == "test" else
              {"pool_size": settings.DB_POOL_SIZE, "max_overflow": settings.DB_MAX_OVERFLOW,
               "pool_pre_ping": True, "pool_recycle": 1800})

engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True, **_pool_args)

AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


_UNAVAILABLE = ("OperationalError", "InterfaceError", "ConnectionRefused", "CannotConnectNow",
                "ConnectionDoesNotExist", "TooManyConnections", "TimeoutError",
                "ConnectionError", "ConnectionReset")


def is_unavailable(exc: BaseException | None) -> bool:
    """True when `exc`, or anything in its cause chain, means the database
    cannot be reached (as opposed to a bug or a bad query)."""
    for _ in range(6):
        if exc is None:
            return False
        if any(k in type(exc).__name__ for k in _UNAVAILABLE):
            return True
        exc = exc.__cause__ or exc.__context__
    return False
