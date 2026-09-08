"""NQ-021 - the Category enum must match poi_categories.key exactly.

If these drift, searches silently return nothing: the enum accepts a value
the database has never heard of, the filter matches zero rows, and the user
sees an empty result with no error anywhere.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq",
)

from app.schemas.tripspec import Category  # noqa: E402

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def test_enum_matches_database_exactly(db):
    rows = (await db.execute(text("SELECT key FROM poi_categories"))).scalars().all()
    in_db = set(rows)
    in_enum = {c.value for c in Category}

    missing_in_db = in_enum - in_db
    missing_in_enum = in_db - in_enum

    assert not missing_in_db, (
        f"Category values with no poi_categories row: {sorted(missing_in_db)}. "
        f"Searches for these silently return nothing.")
    assert not missing_in_enum, (
        f"poi_categories rows with no Category value: {sorted(missing_in_enum)}. "
        f"These POIs can never be requested.")