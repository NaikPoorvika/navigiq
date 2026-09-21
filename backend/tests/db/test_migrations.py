"""Migration tests (section 104).

  * empty database -> head, and the migrated schema matches the models
    exactly (no autogenerate drift)
  * head -> pre-v2 -> head round trip
  * a v1 database WITH DATA -> head preserves and remaps it: categories move
    to taxonomy v2, POIs outside the 90 km envelope are kept but deactivated,
    legacy plans get an owner, invalid rows are repaired rather than blocking
    the upgrade

Each test builds its own scratch database; none touches the shared test or
development databases. Tests are synchronous because Alembic runs its own
event loop.
"""
from __future__ import annotations

import os

import psycopg
import pytest
from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.db

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRE_V2 = "7886a04d8931"
SCRATCH = os.environ["DATABASE_URL"].rsplit("/", 1)[0] + "/navigiq_migtest"   # set by conftest

# Frozen copy of the v1 category seed (alembic/seeds/01-poi-categories.sql, NQ-012).
V1_CATEGORIES = [
    (1, "cafe", "Cafe", 45, True, False, 300, True),
    (4, "bar", "Bar", 90, True, False, 800, False),
    (6, "historical", "Historical Site", 60, False, True, 50, False),
    (9, "art_gallery", "Art Gallery", 60, True, False, 50, False),
    (10, "park", "Park", 60, False, True, 0, False),
    (13, "sunset", "Sunset Spot", 45, False, True, 0, False),
    (18, "nightlife", "Nightlife", 120, True, False, 1000, False),
    (20, "landmark", "Landmark", 30, False, True, 0, False),
]


def sync(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def alembic_cfg(url: str) -> Config:
    cfg = Config(os.path.join(BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND, "alembic"))
    cfg.attributes["database_url"] = url
    return cfg


@pytest.fixture
def scratch_db(test_database):
    dsn = sync(SCRATCH)
    admin = dsn.rsplit("/", 1)[0] + "/postgres"
    name = dsn.rsplit("/", 1)[1]
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{name}"')
    yield SCRATCH
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_empty_to_head_matches_the_models(scratch_db):
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    from app.db.base import Base

    command.upgrade(alembic_cfg(scratch_db), "head")
    engine = create_engine(sync(scratch_db).replace("postgresql://", "postgresql+psycopg://"))
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={
                "include_object": lambda o, n, t, r, c: not (
                    t == "table" and r and n not in Base.metadata.tables)})
            diff = compare_metadata(ctx, Base.metadata)
            rev = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
    finally:
        engine.dispose()
    assert diff == [], diff
    assert rev == "b21e4c7a9f30"


def test_downgrade_and_upgrade_round_trip(scratch_db):
    cfg = alembic_cfg(scratch_db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, PRE_V2)
    with psycopg.connect(sync(scratch_db)) as conn:
        cols = {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'pois'")}
        assert "visit_minutes" in cols and "region_bucket" not in cols
        assert conn.execute("SELECT to_regclass('knowledge_chunks')").fetchone()[0] is None
    command.upgrade(cfg, "head")
    with psycopg.connect(sync(scratch_db)) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "b21e4c7a9f30"


def _seed_v1(dsn: str) -> dict[str, int]:
    with psycopg.connect(dsn) as conn:
        for row in V1_CATEGORIES:
            conn.execute("""INSERT INTO poi_categories (id, key, display_name, default_visit_minutes,
                            is_indoor, weather_sensitive, typical_cost_inr, meal_category)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", row)

        def poi(ref, name, cat_key, lon, lat, **extra):
            cat = next(c[0] for c in V1_CATEGORIES if c[1] == cat_key)
            conn.execute("""
                INSERT INTO pois (source, source_ref, name, name_normalized, geom, area,
                    primary_category, prominence, prominence_parts, visit_minutes,
                    cost_estimate_inr, indoor, weather_flags, tags, curated, quality_score,
                    active, content_hash)
                VALUES ('osm', %s, %s, lower(%s),
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, %s, %s, '{}',
                    %s, %s, %s, '{}', %s, false, 0.5, true, 'h')""",
                         (ref, name, name, lon, lat, extra.get("area"), cat,
                          extra.get("prominence", 0.3), extra.get("visit"), extra.get("cost"),
                          extra.get("indoor"), extra.get("tags", "{}")))
            return conn.execute("SELECT id FROM pois WHERE source_ref = %s", (ref,)).fetchone()[0]

        pub = poi("node/1", "Old Pub", "bar", 77.60, 12.97, area="Indiranagar", visit=100,
                  cost=900, indoor=True, tags='{"opening_hours": "Mo-Su 18:00-23:00"}')
        fort = poi("way/2", "Old Fort", "historical", 77.57, 12.96, prominence=0.6)
        gallery = poi("node/3", "Old Gallery", "art_gallery", 77.59, 12.98)
        far = poi("node/4", "Far Temple Town", "landmark", 78.95, 12.30)       # ~150 km away
        poi("node/5", "Sunset Rock", "sunset", 77.40, 13.10)
        conn.execute("INSERT INTO poi_category_links (poi_id, category_id, weight) VALUES "
                     "(%s, 4, 1.0), (%s, 18, 0.5)", (pub, pub))
        conn.execute("""INSERT INTO poi_opening_hours (poi_id, day_of_week, open_min, close_min,
                        is_24h, closed_all_day, source, confidence) VALUES
                        (%s, 0, 1080, 1380, false, false, 'osm', 0.9),
                        (%s, 1, 1200, 60, false, false, 'osm', 0.9)""", (pub, pub))
        uid = conn.execute("""INSERT INTO "user" (id, email, hashed_password, is_active,
                              is_superuser) VALUES (gen_random_uuid(), 'v1@example.test', 'x',
                              true, false) RETURNING id""").fetchone()[0]
        conn.execute("""INSERT INTO poi_interactions (user_id, poi_id, action, context)
                        VALUES (%s, %s, 'liked', '{}')""", (uid, fort))
        ts = conn.execute("""INSERT INTO tripspecs (payload, version, source)
                             VALUES ('{"version": "1.0"}', '1.0', 'form') RETURNING id"""
                          ).fetchone()[0]
        itin = conn.execute("""INSERT INTO itineraries (tripspec_id, status, mode)
                               VALUES (%s, 'active', 'balanced') RETURNING id""", (ts,)
                            ).fetchone()[0]
        ver = conn.execute("""INSERT INTO itinerary_versions (itinerary_id, version_no, reason,
                              total_cost_inr, total_duration_min, total_walk_m, validator_report)
                              VALUES (%s, 1, 'initial', 100, 240, 0, '{}') RETURNING id""",
                           (itin,)).fetchone()[0]
        conn.execute("UPDATE itineraries SET current_version_id = %s WHERE id = %s", (ver, itin))
        conn.execute("""INSERT INTO itinerary_stops (version_id, seq, poi_id, arrive_min,
                        depart_min, visit_minutes, cost_inr, notes)
                        VALUES (%s, 1, %s, 600, 660, 60, 0, '{}')""", (ver, gallery))
        conn.commit()
    return {"pub": pub, "fort": fort, "gallery": gallery, "far": far}


def test_v1_data_is_preserved_and_remapped(scratch_db):
    cfg = alembic_cfg(scratch_db)
    command.upgrade(cfg, PRE_V2)
    ids = _seed_v1(sync(scratch_db))
    command.upgrade(cfg, "head")

    with psycopg.connect(sync(scratch_db)) as conn:
        def one(sql, *params):
            return conn.execute(sql, params).fetchone()

        cats = dict(conn.execute("""SELECT p.name, c.key FROM pois p
                                    JOIN poi_categories c ON c.id = p.primary_category"""))
        assert cats == {"Old Pub": "nightlife", "Old Fort": "history", "Old Gallery": "gallery",
                        "Far Temple Town": "monument", "Sunset Rock": "viewpoint"}
        old_keys = {r[0] for r in conn.execute("SELECT key FROM poi_categories")}
        assert not old_keys & {"bar", "historical", "art_gallery", "sunset", "landmark"}
        # the pub linked to both bar and nightlife: one link survives, nothing duplicated
        links = conn.execute("""SELECT c.key FROM poi_category_links l
                                JOIN poi_categories c ON c.id = l.category_id
                                WHERE l.poi_id = %s""", (ids["pub"],)).fetchall()
        assert [r[0] for r in links] == ["nightlife"]

        pub = one("""SELECT locality, visit_duration_typical, estimated_cost_typical,
                     cost_confidence, indoor_outdoor, region_bucket, active,
                     opening_hours_raw, slug, distance_from_center_km, source_urls
                     FROM pois WHERE id = %s""", ids["pub"])
        assert pub[0] == "Indiranagar" and pub[1] == 100 and pub[2] == 900
        assert pub[3] == "source_tag" and pub[4] == "indoor"
        assert pub[5] == "CITY_CORE" and pub[6] is True
        assert pub[7] == "Mo-Su 18:00-23:00" and pub[8] == f"poi-{ids['pub']}"
        assert float(pub[9]) < 15
        assert pub[10] == ["https://www.openstreetmap.org/node/1"]

        far = one("SELECT region_bucket, active, recommendable FROM pois WHERE id = %s", ids["far"])
        assert far == ("OUT_OF_SCOPE", False, False)          # kept, but never served

        # the invalid overnight interval was removed; the valid one kept
        hours = conn.execute("SELECT day_of_week FROM poi_opening_hours WHERE poi_id = %s",
                             (ids["pub"],)).fetchall()
        assert [h[0] for h in hours] == [0]
        assert one("SELECT action FROM poi_interactions")[0] == "view"

        itin = one("SELECT session_id, user_id, current_version_id IS NOT NULL FROM itineraries")
        assert itin == ("legacy-unowned", None, True)
        ver = one("SELECT kind, version_no, variant_status FROM itinerary_versions")
        assert ver == ("version", 1, None)
        assert one("SELECT count(*) FROM itinerary_stops")[0] == 1
        # the generated search column exists and the old columns are gone
        cols = {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'pois'")}
        assert "search_tsv" in cols and not cols & {"visit_minutes", "cost_estimate_inr", "area"}
