"""Tests for the LLM-facing draft contract and multi-day support.

Pure tests run without a database. The integration tests at the bottom need
Postgres and the places table.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://navigiq:navigiq_local_dev@localhost:5433/navigiq",
)

from app.schemas.trip_draft import TripDraft  # noqa: E402
from app.schemas.tripspec import TripSpec  # noqa: E402
from app.services.planning.draft_builder import (  # noqa: E402
    build_tripspec,
    resolve_date_phrase,
)

MONDAY = date(2026, 9, 21)
SATURDAY = date(2026, 9, 26)


# --- date phrases: resolved in Python, never by the model -----------------

@pytest.mark.parametrize("phrase,expected", [
    ("today", MONDAY),
    ("tomorrow", date(2026, 9, 22)),
    ("day after tomorrow", date(2026, 9, 23)),
    ("saturday", SATURDAY),
    ("this saturday", SATURDAY),
    ("Saturday", SATURDAY),
    ("sat", SATURDAY),
    ("weekend", SATURDAY),
    ("2026-10-01", date(2026, 10, 1)),
])
def test_date_phrases(phrase, expected):
    assert resolve_date_phrase(phrase, MONDAY) == expected


def test_bare_weekday_on_that_day_means_today():
    assert resolve_date_phrase("monday", MONDAY) == MONDAY


def test_next_weekday_on_that_day_means_a_week_later():
    assert resolve_date_phrase("next monday", MONDAY) == date(2026, 9, 28)


def test_unparseable_phrase_returns_none_not_a_guess():
    assert resolve_date_phrase("sometime soon", MONDAY) is None


@pytest.mark.parametrize("phrase", [
    "sometime soon", "next week", "in two days", "eventually", "soon",
    "the 5th", "next month",
])
def test_representative_unsupported_phrases_all_return_none(phrase):
    """A phrase outside the resolver's vocabulary must become a clarifying
    question (via None), never a guess."""
    assert resolve_date_phrase(phrase, MONDAY) is None


# Every phrase form documented on TripDraft.date_phrase (trip_draft.py) as
# supported, one representative example each. If resolve_date_phrase()'s
# actual vocabulary ever changes, this is the test that must be updated
# alongside that docstring - it exists so the two cannot silently drift
# apart (Change #2: schema/prompt documentation must match resolver reality,
# never invent or duplicate resolution logic).
DOCUMENTED_SUPPORTED_PHRASES = [
    "today", "tonight", "tomorrow", "day after tomorrow", "day after",
    "weekend", "this weekend",
    "monday", "Monday", "mon", "this monday", "next monday", "coming monday",
    "2026-10-01",
]


@pytest.mark.parametrize("phrase", DOCUMENTED_SUPPORTED_PHRASES)
def test_documented_vocabulary_is_actually_supported(phrase):
    assert resolve_date_phrase(phrase, MONDAY) is not None, (
        f"{phrase!r} is documented on TripDraft.date_phrase as supported "
        f"but resolve_date_phrase() returned None for it")


# --- the draft contract -----------------------------------------------------

def test_draft_ignores_hallucinated_coordinates():
    """ADR-002. If the model emits lat/lon, they must never reach planning."""
    d = TripDraft(origin={"name": "Koramangala", "lat": 99.9, "lon": 99.9})
    assert not hasattr(d.origin, "lat")
    assert d.origin.model_dump() == {"name": "Koramangala"}


def test_draft_ignores_unknown_fields():
    d = TripDraft(origin={"name": "Jayanagar"}, rating=5, secret="x")
    assert "rating" not in d.model_dump()


def test_draft_rejects_invented_categories():
    """The Category enum is closed. A model cannot invent one."""
    with pytest.raises(Exception):
        TripDraft(interests=[{"category": "rooftop_hookah_lounge"}])


def test_draft_json_schema_exists_for_constrained_decoding():
    schema = TripDraft.model_json_schema()
    assert "origin" in schema["properties"]
    assert "lat" not in str(schema["$defs"].get("PlaceRef", {}))


# --- multi-day ---------------------------------------------------------------

def _spec(**over):
    base = dict(origin={"lat": 12.9357, "lon": 77.6241}, date="2026-09-26",
                start_time_local="10:00", end_time_local="18:00",
                interests=[{"category": "restaurant"}])
    base.update(over)
    return TripSpec(**base)


def test_single_day_is_the_default():
    assert _spec().days == 1
    assert _spec().day_dates == [SATURDAY]


def test_day_dates_are_consecutive():
    assert _spec(days=3).day_dates == [
        SATURDAY, date(2026, 9, 27), date(2026, 9, 28)]


@pytest.mark.parametrize("days", [0, 8])
def test_days_are_bounded(days):
    with pytest.raises(Exception):
        _spec(days=days)


# --- Change #5: clarification cap -------------------------------------------
# _resolve() short-circuits before touching the database when a place ref is
# None (see draft_builder.py), so a maximal-clarification scenario can be
# built entirely from missing-field cases below, with no places-table
# dependency. Destination-specific resolution cases are in the integration
# section further down.

@pytest.mark.asyncio
async def test_clarification_cap_is_never_exceeded(db):
    """Missing origin + missing interests + an unparseable date phrase can
    all fire in the same draft - four sources of clarification are latent
    in build_tripspec (origin, destination, interests, date), but the
    response must never carry more than MAX_CLARIFICATIONS."""
    from app.services.planning.draft_builder import MAX_CLARIFICATIONS

    r = await build_tripspec(db, TripDraft(date_phrase="not a real phrase"))
    # No origin, no interests, no destination, an unparseable date: every
    # non-time clarification source is triggered at once.
    assert r.needs_clarification
    assert r.tripspec is None
    assert len(r.to_dict()["clarifications"]) <= MAX_CLARIFICATIONS


@pytest.mark.asyncio
async def test_clarification_cap_ordering_is_deterministic(db):
    """Origin is resolved first in build_tripspec, so when both origin and
    interests are missing, origin's question must be the one that survives
    the cap - not an arbitrary one."""
    r = await build_tripspec(db, TripDraft())  # origin, interests both absent
    assert r.needs_clarification
    fields = [c["field"] for c in r.to_dict()["clarifications"]]
    assert fields[0] == "origin"


@pytest.mark.asyncio
async def test_tripspec_is_none_whenever_clarification_is_needed(db):
    r = await build_tripspec(db, TripDraft(date_phrase="gibberish"))
    assert r.needs_clarification
    assert r.tripspec is None
    assert r.to_dict()["tripspec"] is None


# --- integration: needs the places table ---------------------------------

@pytest_asyncio.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    async with async_sessionmaker(engine)() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_origin_is_resolved_not_trusted(db):
    draft = TripDraft(origin={"name": "Koramangala", "lat": 99.9, "lon": 99.9},
                      date_phrase="saturday",
                      interests=[{"category": "restaurant"}])
    r = await build_tripspec(db, draft)
    assert r.tripspec is not None
    assert abs(r.tripspec.origin.lat - 12.9357) < 0.01
    assert abs(r.tripspec.origin.lon - 77.6241) < 0.01


@pytest.mark.asyncio
async def test_ambiguous_origin_asks_instead_of_guessing(db):
    r = await build_tripspec(db, TripDraft(
        origin={"name": "Indiranagar"}, interests=[{"category": "cafe"}]))
    assert r.needs_clarification
    assert r.tripspec is None
    assert r.clarifications[0].field == "origin"
    assert len(r.clarifications[0].options) >= 2


@pytest.mark.asyncio
async def test_missing_origin_asks(db):
    r = await build_tripspec(db, TripDraft(interests=[{"category": "cafe"}]))
    assert r.needs_clarification
    assert r.clarifications[0].field == "origin"


@pytest.mark.asyncio
async def test_missing_interests_asks(db):
    r = await build_tripspec(db, TripDraft(origin={"name": "Koramangala"}))
    assert r.needs_clarification
    assert any(c.field == "interests" for c in r.clarifications)


@pytest.mark.asyncio
async def test_unknown_place_asks_rather_than_guessing(db):
    r = await build_tripspec(db, TripDraft(
        origin={"name": "asdfghjkl"}, interests=[{"category": "cafe"}]))
    assert r.needs_clarification
    assert r.tripspec is None


@pytest.mark.asyncio
async def test_defaults_are_recorded_as_assumptions(db):
    r = await build_tripspec(db, TripDraft(
        origin={"name": "Koramangala"}, interests=[{"category": "cafe"}]))
    assert r.assumptions, "defaults must be visible, not silent"


# --- destination resolution -------------------------------------------------
# Section 8: same resolver, same _resolve() codepath as origin, but with
# required=False. Uses the existing gazetteer/resolution behaviour only -
# no new destination semantics.

@pytest.mark.asyncio
async def test_destination_missing_is_not_a_clarification(db):
    """destination is optional (required=False in _resolve) - unlike
    origin, omitting it must never itself trigger a question."""
    r = await build_tripspec(db, TripDraft(
        origin={"name": "Koramangala"}, interests=[{"category": "cafe"}]))
    assert not any(c.field == "destination" for c in r.clarifications)


@pytest.mark.asyncio
async def test_destination_supplied_and_resolvable(db):
    r = await build_tripspec(db, TripDraft(
        origin={"name": "Koramangala"}, destination={"name": "Jayanagar"},
        date_phrase="saturday", interests=[{"category": "cafe"}]))
    assert r.tripspec is not None, r.clarifications
    assert r.tripspec.destination is not None
    assert r.tripspec.destination.lat is not None
    assert r.tripspec.destination.lon is not None


@pytest.mark.asyncio
async def test_destination_supplied_but_unknown_asks_rather_than_guessing(db):
    r = await build_tripspec(db, TripDraft(
        origin={"name": "Koramangala"}, destination={"name": "asdfghjkl"},
        interests=[{"category": "cafe"}]))
    assert r.needs_clarification
    assert r.tripspec is None
    assert any(c.field == "destination" for c in r.clarifications)


@pytest.mark.asyncio
async def test_destination_supplied_but_ambiguous_asks(db):
    """'Indiranagar' is the same genuinely-ambiguous case documented in
    ADR-011 for origin; the resolver applies identically to destination."""
    r = await build_tripspec(db, TripDraft(
        origin={"name": "Koramangala"}, destination={"name": "Indiranagar"},
        interests=[{"category": "cafe"}]))
    assert r.needs_clarification
    assert r.tripspec is None
    dest_clar = [c for c in r.clarifications if c.field == "destination"]
    assert dest_clar, r.clarifications
    assert len(dest_clar[0].options) >= 2
