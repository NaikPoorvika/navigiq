"""Real-data checks against the loaded development database (section 104).

These run only when the full Bengaluru inventory is loaded (the `real_db`
fixture skips otherwise). They pin behaviour that synthetic fixtures cannot:
spelling variants people actually type, the anchor landmarks, the envelope
and data-quality invariants of the real pipeline output, and the core
recommendation promises on real density.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.geo.regions import geo_config
from app.services.poi.search import resolve_location, resolve_poi_name, unambiguous
from app.services.recommendation.engine import make_anchor, recommend
from app.services.recommendation.scoring import RecommendationRequest

pytestmark = pytest.mark.realdata


@pytest.mark.parametrize("variants", [
    ("Malleswaram", "Malleshwaram"),
    ("MG Road", "M.G. Road", "Mahatma Gandhi Road"),
    ("Jayanagar", "jayanagar"),
])
async def test_area_spelling_variants_resolve_to_one_place(real_db, variants):
    names = {(await resolve_location(real_db, v)).name for v in variants}
    assert len(names) == 1, names


@pytest.mark.parametrize("variants,expected", [
    (("Lalbagh", "Lal Bagh", "lalbag", "Lalbagh Botanical Garden"), "Lalbagh Botanical Garden"),
    (("Bangalore Palace", "Bengaluru Palace"), "Bangalore Palace"),
    (("Cubbon Park", "cubbon park"), "Cubbon Park"),
])
async def test_landmark_spelling_variants(real_db, variants, expected):
    for v in variants:
        top = unambiguous(await resolve_poi_name(real_db, v))
        assert top is not None and top.name == expected, v


ANCHORS = ["Lalbagh Botanical Garden", "Cubbon Park", "Bangalore Palace", "Vidhana Soudha",
           "Nandi Hills", "Tipu Sultan's Summer Palace", "ISKCON Temple"]


async def test_anchor_landmarks_are_present_and_recommendable(real_db):
    rows = (await real_db.execute(text("""
        SELECT name, recommendable, wikidata_id, region_bucket FROM pois
        WHERE active AND name = ANY(:n)"""), {"n": ANCHORS})).all()
    found = {r.name: r for r in rows}
    assert set(found) == set(ANCHORS)
    for r in found.values():
        assert r.recommendable, r.name
    assert found["Nandi Hills"].region_bucket == "OUTSKIRTS"            # ~45 km north
    assert found["Lalbagh Botanical Garden"].region_bucket == "CITY_CORE"


async def test_inventory_invariants(real_db):
    radius = geo_config().radius_km
    q = await real_db.execute(text("""
        SELECT
          count(*) FILTER (WHERE active AND distance_from_center_km > :r + 0.0001) AS outside,
          count(*) FILTER (WHERE active AND (name IS NULL OR btrim(name) = '')) AS unnamed,
          count(*) FILTER (WHERE active AND region_bucket = 'OUT_OF_SCOPE') AS bad_bucket,
          count(*) FILTER (WHERE recommendable AND NOT active) AS rec_inactive,
          count(*) FILTER (WHERE active AND (NOT ST_IsValid(geom::geometry)
                           OR ST_Y(geom::geometry) NOT BETWEEN 11 AND 15
                           OR ST_X(geom::geometry) NOT BETWEEN 76 AND 79)) AS bad_geom,
          count(*) FILTER (WHERE recommendable) AS recommendable,
          count(*) FILTER (WHERE active) AS active
        FROM pois"""), {"r": radius})
    s = q.one()
    assert s.outside == 0 and s.unnamed == 0 and s.bad_bucket == 0
    assert s.rec_inactive == 0 and s.bad_geom == 0
    assert s.active >= 5000 and s.recommendable >= 2000
    dup_qids = (await real_db.execute(text("""
        SELECT wikidata_id FROM pois WHERE active AND wikidata_id IS NOT NULL
        GROUP BY wikidata_id HAVING count(*) > 1"""))).scalars().all()
    assert dup_qids == []
    # every image is attributed; every recommendable POI names its sources
    unattributed = (await real_db.execute(text("""
        SELECT count(*) FROM pois WHERE active AND image_url IS NOT NULL
        AND (image_attribution IS NULL OR image_attribution->>'license' IS NULL)"""))).scalar()
    unsourced = (await real_db.execute(text("""
        SELECT count(*) FROM pois WHERE recommendable AND cardinality(source_names) = 0"""))
                 ).scalar()
    assert unattributed == 0 and unsourced == 0


async def test_there_is_no_rating_data_to_fabricate(real_db):
    cols = set((await real_db.execute(text("""
        SELECT column_name FROM information_schema.columns WHERE table_name = 'pois'"""))
                ).scalars().all())
    assert not {c for c in cols if "rating" in c or "stars" in c or "review" in c}


async def test_local_request_stays_local(real_db):
    area = await resolve_location(real_db, "Indiranagar")
    res = await recommend(real_db, RecommendationRequest(
        interests=["cafe"], anchor=make_anchor(area.name, area.lat, area.lon, 3.0), limit=8))
    assert len(res.items) >= 5
    for s in res.items:
        assert s.poi.category == "cafe"
        assert s.poi.region_bucket in ("CITY_CORE", "CITY")
        assert s.poi.distance_from_center_km < 30


async def test_regional_request_reaches_escapes(real_db):
    res = await recommend(real_db, RecommendationRequest(
        interests=["hill", "waterfall", "nature"], scope="regional", limit=8))
    assert res.items
    assert all(s.poi.region_bucket in ("OUTSKIRTS", "NEARBY_ESCAPE") for s in res.items)


async def test_exclusions_and_hidden_gems(real_db):
    res = await recommend(real_db, RecommendationRequest(
        moods=["chill"], avoid_interests=["mall"], limit=12))
    assert res.items and all(s.poi.category != "mall" for s in res.items)
    gems = await recommend(real_db, RecommendationRequest(mode="hidden_gems", limit=8))
    assert gems.items
    assert all(not s.poi.is_chain for s in gems.items)
    assert all(s.poi.prominence <= 0.2 or "offbeat" in s.poi.experience_tags for s in gems.items)


async def test_diverse_general_discovery(real_db):
    res = await recommend(real_db, RecommendationRequest(limit=8))
    cats = [s.poi.category for s in res.items]
    assert len(cats) == 8 and len(set(cats)) >= 5
    chains = [s.poi.chain_key for s in res.items if s.poi.chain_key]
    assert len(chains) == len(set(chains))
