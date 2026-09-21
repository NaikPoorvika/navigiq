"""Database-level guarantees (section 104): constraints, cascades, spatial,
vector and trigram queries, and concurrent plan edits.

The schema is the last line of defence: application bugs must not be able
to store an impossible POI, an ownerless plan or a malformed version.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.schemas.tripspec import TripSpec
from app.services import plans as plan_service
from app.services.planning.modify import Modification
from app.services.planning.store import Owner, PlanConflict

pytestmark = pytest.mark.db


async def violates(db, sql: str, params: dict | None = None) -> str:
    """Run `sql`, expect the database to refuse it, return the constraint name."""
    with pytest.raises((IntegrityError, DBAPIError)) as ei:
        await db.execute(text(sql), params or {})
        await db.flush()
    await db.rollback()
    return str(ei.value.orig)


@pytest.mark.parametrize("sql,constraint", [
    ("UPDATE pois SET quality_score = 1.5 WHERE name = 'Test Garden'", "ck_pois_quality"),
    ("UPDATE pois SET prominence = -0.1 WHERE name = 'Test Garden'", "ck_pois_prominence"),
    ("UPDATE pois SET distance_from_center_km = -1 WHERE name = 'Test Garden'", "ck_pois_distance"),
    ("UPDATE pois SET region_bucket = 'MARS' WHERE name = 'Test Garden'", "ck_pois_region"),
    ("UPDATE pois SET indoor_outdoor = 'sideways' WHERE name = 'Test Garden'",
     "ck_pois_indoor_outdoor"),
    ("UPDATE pois SET visit_duration_min = 500 WHERE name = 'Test Garden'",
     "ck_pois_duration_order"),
    ("UPDATE pois SET estimated_cost_min = 99999 WHERE name = 'Test Garden'", "ck_pois_cost_order"),
    ("UPDATE poi_opening_hours SET close_min = open_min WHERE NOT closed_all_day",
     "ck_hours_interval"),
    ("UPDATE poi_opening_hours SET day_of_week = 7", "ck_hours_dow"),
])
async def test_poi_check_constraints(db, sql, constraint):
    assert constraint in await violates(db, sql)


async def test_unique_source_reference_and_slug(db):
    msg = await violates(db, """
        UPDATE pois SET source_ref = (SELECT source_ref FROM pois WHERE name = 'Test Lake')
        WHERE name = 'Test Garden'""")
    assert "uq_pois_source_ref" in msg
    msg = await violates(db, """
        UPDATE pois SET slug = (SELECT slug FROM pois WHERE name = 'Test Lake')
        WHERE name = 'Test Garden'""")
    assert "uq_pois_slug" in msg


async def test_interactions_need_an_owner_and_a_known_action(db):
    poi = (await db.execute(text("SELECT id FROM pois LIMIT 1"))).scalar()
    assert "ck_interaction_owner" in await violates(db, """
        INSERT INTO poi_interactions (poi_id, action, context) VALUES (:p, 'view', '{}')""",
                                                    {"p": poi})
    assert "ck_interaction_action" in await violates(db, """
        INSERT INTO poi_interactions (poi_id, session_id, action, context)
        VALUES (:p, 'sess-constraint-0001', 'hack', '{}')""", {"p": poi})


async def test_feedback_is_bounded(db):
    assert "ck_feedback_rating" in await violates(db, """
        INSERT INTO feedback (session_id, target_type, target_id, rating)
        VALUES ('sess-constraint-0001', 'poi', '1', 5)""")
    assert "ck_feedback_len" in await violates(db, """
        INSERT INTO feedback (session_id, target_type, target_id, rating, comment)
        VALUES ('sess-constraint-0001', 'poi', '1', 1, repeat('x', 2001))""")


async def _new_plan(db, owner: Owner) -> int:
    spec = TripSpec(start_time="10:00", end_time="16:00", interests=["garden", "cafe"])
    outcome = await plan_service.create_plan(db, spec, owner)
    assert outcome.status == "ok", outcome.to_dict()
    return outcome.itinerary["itinerary_id"]


async def test_plans_need_an_owner_and_well_formed_versions(db):
    pid = await _new_plan(db, Owner(None, "db-owner-check-0001"))
    assert "ck_itinerary_owner" in await violates(db, """
        UPDATE itineraries SET user_id = NULL, session_id = NULL WHERE id = :i""", {"i": pid})
    assert "ck_version_variant_shape" in await violates(db, """
        UPDATE itinerary_versions SET kind = 'variant' WHERE itinerary_id = :i""", {"i": pid})
    assert "ck_stop_times" in await violates(db, """
        UPDATE itinerary_stops SET depart_min = arrive_min - 1 WHERE version_id IN
        (SELECT id FROM itinerary_versions WHERE itinerary_id = :i)""", {"i": pid})
    assert "uq_version_no" in await violates(db, """
        INSERT INTO itinerary_versions (itinerary_id, version_no, kind, reason, total_cost_inr,
            total_duration_min, total_walk_m, validator_report)
        VALUES (:i, 1, 'version', 'dup', 0, 0, 0, '{}')""", {"i": pid})


async def test_pois_used_by_plans_cannot_be_deleted(db):
    pid = await _new_plan(db, Owner(None, "db-restrict-00001"))
    poi = (await db.execute(text("""
        SELECT s.poi_id FROM itinerary_stops s JOIN itinerary_versions v ON v.id = s.version_id
        WHERE v.itinerary_id = :i LIMIT 1"""), {"i": pid})).scalar()
    msg = await violates(db, "DELETE FROM pois WHERE id = :p", {"p": poi})
    assert "itinerary_stops" in msg      # deactivate, never delete, a POI a plan uses


async def test_deleting_a_user_cascades_to_everything_they_own(db):
    uid = uuid.uuid4()
    await db.execute(text("""INSERT INTO "user" (id, email, hashed_password, is_active, is_superuser)
                             VALUES (:i, :e, 'x', true, false)"""),
                     {"i": uid, "e": f"cascade-{uid.hex[:8]}@example.test"})
    await db.commit()
    owner = Owner(uid, None)
    pid = await _new_plan(db, owner)
    poi = (await db.execute(text("SELECT id FROM pois WHERE name = 'Test Garden'"))).scalar()
    conv = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO saved_pois (user_id, poi_id) VALUES (:u, :p);
    """), {"u": uid, "p": poi})
    await db.execute(text("INSERT INTO user_preferences (user_id) VALUES (:u)"), {"u": uid})
    await db.execute(text("""INSERT INTO poi_interactions (user_id, poi_id, action, context)
                             VALUES (:u, :p, 'view', '{}')"""), {"u": uid, "p": poi})
    await db.execute(text("""INSERT INTO conversations (id, user_id, state)
                             VALUES (:c, :u, '{}')"""), {"c": conv, "u": uid})
    await db.execute(text("""INSERT INTO messages (conversation_id, role, content)
                             VALUES (:c, 'user', 'hi')"""), {"c": conv})
    await db.execute(text("""INSERT INTO refresh_tokens (user_id, token_hash, family_id, expires_at)
                             VALUES (:u, :h, :f, now() + interval '1 day')"""),
                     {"u": uid, "h": uuid.uuid4().hex + uuid.uuid4().hex, "f": uuid.uuid4()})
    await db.commit()
    versions = (await db.execute(text("SELECT id FROM itinerary_versions WHERE itinerary_id = :i"),
                                 {"i": pid})).scalars().all()

    await db.execute(text('DELETE FROM "user" WHERE id = :u'), {"u": uid})
    await db.commit()
    for table, where in (("itineraries", "user_id = :u"), ("saved_pois", "user_id = :u"),
                         ("user_preferences", "user_id = :u"),
                         ("poi_interactions", "user_id = :u"), ("conversations", "user_id = :u"),
                         ("refresh_tokens", "user_id = :u"), ("tripspecs", "user_id = :u")):
        n = (await db.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"),
                              {"u": uid})).scalar()
        assert n == 0, table
    assert (await db.execute(text("SELECT count(*) FROM messages WHERE conversation_id = :c"),
                             {"c": conv})).scalar() == 0
    assert (await db.execute(text("SELECT count(*) FROM itinerary_stops WHERE version_id = "
                                  "ANY(:v)"), {"v": list(versions)})).scalar() == 0
    # shared data survives
    assert (await db.execute(text("SELECT count(*) FROM pois WHERE id = :p"),
                             {"p": poi})).scalar() == 1


# --- spatial, vector and trigram queries ------------------------------------------------------

async def test_postgis_distances_match_the_configured_envelope(db):
    rows = dict((await db.execute(text("""
        SELECT name, distance_from_center_km FROM pois
        WHERE name IN ('Test Garden', 'Outskirts Lake', 'Edge Viewpoint')"""))).all())
    assert abs(float(rows["Test Garden"]) - 2.0) < 0.01
    assert abs(float(rows["Outskirts Lake"]) - 40.0) < 0.01
    assert abs(float(rows["Edge Viewpoint"]) - 89.9) < 0.01
    assert (await db.execute(text("SELECT count(*) FROM pois WHERE name = 'Beyond Edge Viewpoint'"))
            ).scalar() == 0
    near = (await db.execute(text("""
        SELECT name FROM pois WHERE ST_DWithin(geom,
            ST_SetSRID(ST_MakePoint(77.5946, 12.9716), 4326)::geography, 3000)
        ORDER BY name"""))).scalars().all()
    assert "Test Garden" in near and "Outskirts Lake" not in near
    plan = "\n".join((await db.execute(text("""
        EXPLAIN SELECT id FROM pois WHERE ST_DWithin(geom,
            ST_SetSRID(ST_MakePoint(77.5946, 12.9716), 4326)::geography, 3000)"""))).scalars())
    assert "pois" in plan


async def test_generated_search_vector_tracks_search_text(db):
    hit = (await db.execute(text("""
        SELECT name FROM pois WHERE search_tsv @@ plainto_tsquery('simple', 'garden')"""))
           ).scalars().all()
    assert "Test Garden" in hit


async def test_trigram_similarity_finds_misspellings(db):
    top = (await db.execute(text("""
        SELECT name FROM pois ORDER BY similarity(name_normalized, 'test gardn') DESC LIMIT 1"""))
           ).scalar()
    assert top == "Test Garden"


async def test_vector_search_returns_the_nearest_chunk(db):
    row = (await db.execute(text("""
        SELECT id, embedding::text AS v FROM knowledge_chunks WHERE embedding IS NOT NULL LIMIT 1"""))
           ).first()
    nearest = (await db.execute(text("""
        SELECT id, embedding <=> CAST(:v AS vector) AS d FROM knowledge_chunks
        ORDER BY embedding <=> CAST(:v AS vector) LIMIT 1"""), {"v": row.v})).first()
    assert nearest.id == row.id and nearest.d < 1e-6
    idx = (await db.execute(text("""
        SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_knowledge_chunks_hnsw'"""))).scalar()
    assert idx and "hnsw" in idx and "vector_cosine_ops" in idx


# --- concurrency ------------------------------------------------------------------------------------

async def test_stale_edit_is_refused_not_silently_applied(test_database):
    """Two edits based on version 1: the second must get a conflict, even
    though its session read the plan before the first edit committed."""
    from app.db.session import AsyncSessionLocal
    owner = Owner(None, "db-concurrency-0001")
    async with AsyncSessionLocal() as s0:
        pid = await _new_plan(s0, owner)
    mod = [Modification.model_validate({"op": "set_pace", "pace": "relaxed"})]
    async with AsyncSessionLocal() as a, AsyncSessionLocal() as b:
        from app.services.planning import store
        await store.get_plan(b, pid, owner)            # B has now seen version 1
        res_a = await plan_service.modify_plan(a, pid, owner, mod, expected_version_no=1)
        assert res_a["version_no"] == 2
        with pytest.raises(PlanConflict):
            await plan_service.modify_plan(b, pid, owner,
                                           [Modification.model_validate({"op": "set_budget",
                                                                         "amount": 900})],
                                           expected_version_no=1)


async def test_concurrent_edits_keep_version_numbers_unique(test_database):
    from app.db.session import AsyncSessionLocal
    owner = Owner(None, "db-concurrency-0002")
    async with AsyncSessionLocal() as s0:
        pid = await _new_plan(s0, owner)

    async def edit(op: dict):
        async with AsyncSessionLocal() as s:
            try:
                return await plan_service.modify_plan(s, pid, owner,
                                                      [Modification.model_validate(op)])
            except PlanConflict as exc:
                return exc

    results = await asyncio.gather(edit({"op": "set_pace", "pace": "relaxed"}),
                                   edit({"op": "set_budget", "amount": 2000}),
                                   edit({"op": "set_pace", "pace": "quick"}))
    nos = [r["version_no"] for r in results if isinstance(r, dict) and r.get("version_no")]
    assert len(nos) == len(set(nos)) and nos
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT version_no FROM itinerary_versions WHERE itinerary_id = :i AND kind = 'version'
            ORDER BY version_no"""), {"i": pid})).scalars().all()
    assert rows == list(range(1, len(rows) + 1))
