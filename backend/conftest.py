"""Root test configuration.

Environment is fixed BEFORE the app is imported (settings are read at import):
  * DATABASE_URL -> the isolated test database (navigiq_test), created and
    migrated from empty once per session by tests/fixtures/testdb.py
  * LLM, weather and Redis off by default: tests opt in explicitly with a
    FakeLLM-backed service or a mocked HTTP transport.

Real-data tests (marked `realdata`) read the loaded development database and
are skipped automatically when it is not reachable.
"""
from __future__ import annotations

import os

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://navigiq_user:navigiq_password@localhost:5433/navigiq_test")
REAL_DB = os.environ.get(
    "REAL_DATABASE_URL",
    "postgresql+asyncpg://navigiq_user:navigiq_password@localhost:5433/navigiq")

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = TEST_DB
os.environ.setdefault("LLM_ENABLED", "false")
os.environ.setdefault("WEATHER_ENABLED", "false")
os.environ.setdefault("REDIS_ENABLED", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-navigiq-tests-only-0123456789")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "db: needs the migrated test database")
    config.addinivalue_line("markers", "realdata: needs the loaded development database")
    config.addinivalue_line("markers", "llm_live: needs a running Ollama")
    config.addinivalue_line("markers", "slow: long-running (fuzz, soak, eval)")


@pytest.fixture(scope="session")
def test_database():
    from tests.fixtures.testdb import prepare_test_database
    prepare_test_database(TEST_DB)
    return TEST_DB


@pytest.fixture
async def async_client(test_database):
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def db(test_database):
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
async def real_db():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    engine = create_async_engine(REAL_DB, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            n = (await conn.execute(text("SELECT count(*) FROM pois WHERE active"))).scalar()
        if not n:
            pytest.skip("development database has no POIs loaded")
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"development database unavailable: {type(exc).__name__}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def fake_llm_service():
    """Swap the process-wide LLM service for a FakeLLM-backed one."""
    from app.llm import FakeLLM
    from app.llm.service import LLMService, set_llm_service

    def make(**fake_kwargs):
        svc = LLMService(FakeLLM(**fake_kwargs), enabled=True, cache_ttl_s=0)
        set_llm_service(svc)
        return svc
    yield make
    set_llm_service(None)
