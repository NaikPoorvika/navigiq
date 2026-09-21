from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

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
