"""POI ingestion stages (sections 32, 84, 85): mapping, hours, tagging, dedupe,
Wikidata linking, scoring, record validation and idempotent hashing."""
from __future__ import annotations

import copy

import pytest

from app.geo.regions import destination_point_geodesic, geo_config
from app.ingestion import pipeline as P
from app.ingestion.curated import load_curated
from app.ingestion.hours import category_default, is_open_at, parse_osm
from app.ingestion.mapping import OSMMapping
from app.ingestion.normalize import chain_key, is_generic_name, normalize_name, slugify
from app.ingestion.scoring import prominence, quality, recommendable
from app.ingestion.tagging import derive_tags, parse_charge
from app.ingestion.validate import validate_record
from app.ingestion.wikidata_geo import WDItem, link, name_score

CFG = geo_config()
MAP = OSMMapping()


def at(bearing, km):
    return destination_point_geodesic(CFG.center_lat, CFG.center_lon, bearing, km)


# --- mapping ------------------------------------------------------------------------------

@pytest.mark.parametrize("tags,category", [
    ({"amenity": "cafe", "name": "X"}, "cafe"),
    ({"amenity": "place_of_worship", "religion": "hindu", "name": "X"}, "temple"),
    ({"amenity": "place_of_worship", "religion": "christian", "name": "X"}, "church"),
    ({"amenity": "place_of_worship", "religion": "muslim", "name": "X"}, "mosque"),
    ({"amenity": "place_of_worship", "religion": "jain", "name": "X"}, "religious_site"),
    ({"tourism": "museum", "name": "City Science Museum"}, "science"),
    ({"tourism": "museum", "name": "Folk Museum"}, "museum"),
    ({"historic": "castle", "castle_type": "palace", "name": "X"}, "palace"),
    ({"historic": "fort", "name": "X"}, "fort"),
    ({"natural": "peak", "name": "X"}, "hill"),
    ({"shop": "mall", "name": "X"}, "mall"),
    ({"amenity": "pub", "name": "X"}, "nightlife"),
    ({"leisure": "bowling_alley", "name": "X"}, "gaming"),
])
def test_mapping_categories(tags, category):
    assert MAP.resolve(tags, tags.get("name"), None, "node").category == category


@pytest.mark.parametrize("tags,extent,osm_type,reason", [
    ({"amenity": "cafe"}, None, "node", "missing_name"),
    ({"natural": "water", "name": "Tiny"}, 50, "way", "below_min_extent"),
    ({"natural": "water", "name": "Pond"}, None, "node", "node_without_extent"),
    ({"historic": "memorial", "name": "Plaque"}, None, "node", "not_notable"),
    ({"amenity": "atm", "name": "ATM"}, None, "node", "unmapped"),
])
def test_mapping_drops_with_reasons(tags, extent, osm_type, reason):
    res = MAP.resolve(tags, tags.get("name"), extent, osm_type)
    assert res.category is None and res.drop_reason == reason


def test_notable_small_water_is_kept():
    tags = {"natural": "water", "name": "Famous Kere", "wikidata": "Q1"}
    assert MAP.resolve(tags, "Famous Kere", 50, "way").category == "lake"


def test_theme_categories_never_primary():
    from app.domain.taxonomy import category_catalog
    assert all(not category_catalog()[r.category].theme for r in MAP.rules)


# --- opening hours --------------------------------------------------------------------------

@pytest.mark.parametrize("value,day,minute,open_", [
    ("24/7", 3, 120, True), ("Mo-Su 06:00-19:00", 0, 400, True),
    ("Mo-Su 06:00-19:00", 0, 1150, False), ("Tu-Su 10:00-17:00; Mo off", 0, 700, False),
    ("Tu-Su 10:00-17:00; Mo off", 1, 700, True), ("Mo-Fr 09:00-13:00,14:00-18:00", 2, 810, False),
    ("Mo-Fr 09:00-13:00,14:00-18:00", 2, 900, True), ("Fr 18:00-02:00", 4, 60, False),
    ("Fr 18:00-02:00", 5, 60, True), ("Fr 18:00-02:00", 4, 1200, True),
    ("Sa-Mo 10:00-12:00", 6, 600, True),
])
def test_hours_parsing(value, day, minute, open_):
    parsed = parse_osm(value)
    assert parsed is not None and parsed.confidence >= 0.5
    assert is_open_at(parsed.intervals, day, minute) is open_


@pytest.mark.parametrize("value", ["by appointment", "Mo-Fr 09:00-13:00 ish", "25:00-26:00",
                                   "", None, "x" * 300])
def test_hours_unparseable_values_are_refused(value):
    assert parse_osm(value) is None


def test_category_default_is_low_confidence_and_valid():
    d = category_default("museum")
    assert d.confidence < 0.5 and len(d.intervals) == 7
    assert all(0 <= i.open_min < i.close_min <= 1440 for i in d.intervals)


def test_impossible_interval_rejected_at_construction():
    from app.ingestion.hours import Interval
    with pytest.raises(ValueError):
        Interval(0, 600, 500)


# --- normalisation ---------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [("Bangalore Palace", "Bengaluru Palace"),
                                 ("Malleswaram", "Malleshwaram"), ("MG Road", "M.G. Road"),
                                 ("Lal Bagh", "Lalbagh"), ("Ulsoor Lake", "Halasuru Lake"),
                                 ("St. Mark's", "Saint Mark's")])
def test_spelling_variants_fold_together(a, b):
    assert normalize_name(a) == normalize_name(b)


def test_slug_and_generic_names():
    assert slugify("Café Déjà Vu!", "node1") == "cafe-deja-vu-node1"
    assert is_generic_name("Cafe") and is_generic_name("Kids Park")
    assert not is_generic_name("Quiet Cafe")


def test_chain_key_prefers_brand_wikidata():
    assert chain_key({"brand:wikidata": "Q1", "brand": "B"}, "X") == "wd:Q1"
    assert chain_key({"brand": "Brew Co"}, "X") == "brand:brew co"
    assert chain_key({}, "X") is None


# --- tagging -----------------------------------------------------------------------------------

def _tags(category, osm=None, region="CITY_CORE", km=5.0, notable=False, chain=False):
    return derive_tags(category=category, secondary=[], rule_tags=[], osm=osm or {},
                       region_bucket=region, distance_km=km, extent_m=None, notable=notable,
                       is_chain=chain)


@pytest.mark.parametrize("value,amount", [("₹20", 20), ("Rs. 50", 50), ("30 INR", 30),
                                          ("₹20 adults, ₹10 children", 20), ("free", None),
                                          ("₹10, ₹20, ₹30", None), (None, None)])
def test_parse_charge(value, amount):
    assert parse_charge(value) == amount


def test_cost_from_charge_and_fee_no():
    assert _tags("museum", {"charge": "₹50"}).cost == (50, 50, 50)
    t = _tags("park", {"fee": "no"})
    assert t.cost == (0, 0, 0) and t.cost_confidence == "source_tag"


def test_food_fee_no_does_not_make_food_free():
    assert _tags("restaurant", {"fee": "no"}).cost[1] > 0


def test_suitability_defaults_to_unknown_not_true():
    s = _tags("other").suitability
    assert all(v is None for v in s.values())


def test_nightlife_is_never_kid_friendly():
    s = _tags("nightlife").suitability
    assert s["kids_friendly"] is False and s["family_friendly"] is False


def test_dietary_and_accessibility_from_source_tags():
    t = _tags("restaurant", {"diet:vegetarian": "only", "wheelchair": "yes"})
    assert "pure_vegetarian" in t.dietary_tags and "vegetarian" in t.dietary_tags
    assert "wheelchair_accessible" in t.accessibility_tags


def test_indoor_outdoor_and_weather():
    assert _tags("museum").weather_suitability == "rain_friendly"
    assert _tags("park").weather_suitability == "dry_weather"


def test_regional_flags():
    far = _tags("hill", region="NEARBY_ESCAPE", km=70, notable=True)
    assert far.regional["short_escape"] and far.regional["recommended_as_primary_destination"]
    assert far.regional["requires_large_time_block"]
    city = _tags("cafe", region="CITY_CORE", km=3)
    assert not any(city.regional.values())


def test_experience_tags_and_moods_are_controlled():
    from app.domain.taxonomy import is_valid_mood, is_valid_tag
    t = _tags("lake", {"boat": "yes"})
    assert all(is_valid_tag(x) for x in t.experience_tags)
    assert all(is_valid_mood(m) for m in t.mood_tags)
    assert "boating" in t.activity_tags


# --- dedupe & wikidata linking --------------------------------------------------------------

def _rec(name, cat, lat, lon, ref, **kw):
    return {"source": "osm", "source_ref": ref, "osm_type": "node", "osm_id": int(ref.split("/")[1]),
            "lat": lat, "lon": lon, "extent_m": None, "tags": {"name": name, **kw.pop("tags", {})},
            "name": name, "name_normalized": normalize_name(name), "category": cat,
            "secondary": [], "rule_tags": [], "rule_index": 0, "wikidata_id": kw.pop("qid", None),
            "aliases": [], "generic_name": False, **kw}


def test_dedupe_merges_name_proximity_and_same_qid():
    lat, lon = at(0, 3)
    recs = [_rec("Same Place", "park", lat, lon, "node/1"),
            _rec("Same Place", "park", lat + 0.0003, lon, "node/2"),
            _rec("Other", "park", lat, lon, "node/3", qid="Q5"),
            _rec("Other Name", "park", lat + 0.0001, lon, "node/4", qid="Q5")]
    out = P.deduplicate(copy.deepcopy(recs), P.Manifest())
    assert len(out) == 2


def test_brand_qid_on_distant_branches_is_cleared_not_merged():
    recs = []
    for i in range(3):
        lat, lon = at(i * 90, 5)
        recs.append(_rec("Brew", "cafe", lat, lon, f"node/{i + 1}", qid="Q77"))
    out = P.deduplicate(recs, P.Manifest())
    assert len(out) == 3 and all(r["wikidata_id"] is None for r in out)


def test_curated_landmark_absorbs_nearby_same_name_duplicates():
    # regression: the curated Bull Temple (a Wikidata item) competed with two
    # OSM "Bull Temple" nodes in search, so the name was always "ambiguous"
    lat, lon = at(200, 3)
    landmark = _rec("Dodda Basavana Gudi (Bull Temple)", "temple", lat, lon, "node/1",
                    qid="Q1531614", curated=True, aliases=["Bull Temple", "Nandi Temple"])
    near = _rec("Bull Temple", "temple", lat + 0.0005, lon, "node/2")           # ~55 m
    far = _rec("Bull Temple", "temple", lat + 0.02, lon, "node/3")              # ~2.2 km
    other_group = _rec("Bull Temple", "restaurant", lat, lon + 0.0003, "node/4")
    other_qid = _rec("Bull Temple", "temple", lat, lon + 0.0002, "node/5", qid="Q99")
    out = P.absorb_curated_duplicates([landmark, near, far, other_group, other_qid], P.Manifest())
    refs = {r["source_ref"] for r in out}
    assert refs == {"node/1", "node/3", "node/4", "node/5"}
    assert landmark["merged_refs"] == ["node/2"]


def test_chain_detection_by_repeated_names():
    recs = [_rec("Chain Tea", "cafe", *at(i * 60, 4 + i), f"node/{i + 1}") for i in range(4)]
    out = P.deduplicate(recs, P.Manifest())
    assert all(r["is_chain"] for r in out)


def test_name_score_allows_generic_extra_words_only():
    assert name_score("Lalbagh Botanical Gardens", "Lalbagh") >= 96
    assert name_score("Lalbagh Grand", "Lalbagh") < 88


def test_wikidata_linking_is_one_to_one_and_type_aware():
    lat, lon = at(0, 2)
    garden = _rec("Lalbagh Botanical Gardens", "garden", lat, lon, "node/1", is_chain=False)
    resto = _rec("Lalbagh Grand", "restaurant", lat + 0.0005, lon, "node/2", is_chain=False)
    item = WDItem("Q200711", "Lalbagh", lat + 0.001, lon, "Lal Bagh", {"Q167346"})
    res = link([garden, resto], [item])
    assert garden["wikidata_id"] == "Q200711" and resto["wikidata_id"] is None
    assert res["linked"] == 1


def test_settlements_are_never_linked():
    lat, lon = at(0, 2)
    rec = _rec("Nandi Hills", "hill", lat, lon, "node/1", is_chain=False)
    link([rec], [WDItem("Q3", "Nandi Hills", lat, lon, "Nandi Hills", {"Q486972"})])
    assert rec["wikidata_id"] is None


# --- scoring & validation ---------------------------------------------------------------------

def test_scores_are_bounded_and_explained():
    p, parts = prominence({"website": "x"}, has_wikidata=True, has_enwiki=True, sitelinks=100,
                          curated_landmark=True)
    assert 0 <= p <= 1 and set(parts) >= {"wikidata_presence", "sitelink_breadth"}
    q, qparts = quality(prominence_score=p, confidence=1.0, category="palace", name_q=1.0,
                        is_chain=False, curated=True, editorial=None)
    assert 0 <= q <= 1 and "category_base" in qparts


def test_editorial_score_is_a_floor_not_a_rating():
    q, _ = quality(prominence_score=0, confidence=0, category="other", name_q=0.2,
                   is_chain=True, curated=True, editorial=0.9)
    assert q == 0.9


@pytest.mark.parametrize("kw,ok", [
    ({"quality_score": 0.9, "category": "heritage", "name": "Old Club", "notable": True}, False),
    ({"quality_score": 0.9, "category": "heritage", "name": "Old Hall", "notable": False}, False),
    ({"quality_score": 0.9, "category": "heritage", "name": "Old Hall", "notable": True}, True),
    ({"quality_score": 0.1, "category": "cafe", "name": "Nice Cafe", "notable": False}, False),
    ({"quality_score": 0.5, "category": "cafe", "name": "Nice Cafe", "notable": False}, True),
])
def test_recommendable_rules(kw, ok):
    assert recommendable(curated=False, generic=False, active=True, **kw) is ok


def _valid_record():
    lat, lon = at(0, 2)
    return {"lat": lat, "lon": lon, "source_ref": "node/1", "slug": "x-node1", "name": "X",
            "distance_from_center_km": 2.0, "region_bucket": "CITY_CORE", "category": "cafe",
            "secondary": [], "visit_duration": [30, 60, 120], "cost": [100, 300, 600],
            "cost_confidence": "category_default",
            "hours": [{"day": 0, "open_min": 480, "close_min": 1320}],
            "experience_tags": ["coffee"], "mood_tags": ["foodie"], "prominence": 0.1,
            "quality_score": 0.4, "data_confidence": 0.3, "source_license": "ODbL-1.0",
            "source_urls": ["https://www.openstreetmap.org/node/1"]}


def test_valid_record_passes():
    assert validate_record(_valid_record()) == []


@pytest.mark.parametrize("mutation,error", [
    (lambda r: r.update(lat=95), "invalid_coordinates"),
    (lambda r: r.update(lon=float("nan")), "invalid_coordinates"),
    (lambda r: r.update(slug=""), "missing_canonical_id"),
    (lambda r: r.update(distance_from_center_km=-1), "invalid_distance"),
    (lambda r: r.update(region_bucket="MOON"), "invalid_region"),
    (lambda r: r.update(category="spaceport"), "invalid_category"),
    (lambda r: r.update(category="romantic"), "invalid_category"),
    (lambda r: r.update(visit_duration=[60, 30, 120]), "invalid_duration"),
    (lambda r: r.update(visit_duration=[-5, 30, 120]), "invalid_duration"),
    (lambda r: r.update(cost=[500, 300, 600]), "invalid_cost"),
    (lambda r: r.update(hours=[{"day": 0, "open_min": 900, "close_min": 800}]),
     "impossible_opening_interval"),
    (lambda r: r.update(experience_tags=["telepathic"]), "unknown_experience_tag"),
    (lambda r: r.update(quality_score=1.5), "invalid_quality_score"),
    (lambda r: r.update(source_license=""), "missing_license"),
    (lambda r: r.update(source_urls=[]), "missing_source_url"),
])
def test_each_data_quality_assertion_fires(mutation, error):
    r = _valid_record()
    mutation(r)
    assert error in validate_record(r)


def test_content_hash_is_stable_and_sensitive():
    r = {k: v for k, v in _valid_record().items()}
    h1 = P.content_hash(r)
    assert P.content_hash(copy.deepcopy(r)) == h1
    r["name"] = "Y"
    assert P.content_hash(r) != h1


def test_geo_filter_is_inclusive_at_boundary():
    els = []
    for i, km in enumerate((89.9, 90.0, 90.1), start=1):
        lat, lon = at(45, km)
        els.append({"type": "node", "id": i, "lat": lat, "lon": lon, "tags": {"name": f"p{i}"}})
    out = P.geo_filter({"g": {"elements": els}}, CFG, P.Manifest())
    assert [r["source_ref"] for r in out] == ["node/1", "node/2"]


def test_ways_without_center_use_bounds_midpoint():
    from app.ingestion.overpass import element_to_record
    el = {"type": "way", "id": 9, "bounds": {"minlat": 12.9, "minlon": 77.5, "maxlat": 13.0,
                                             "maxlon": 77.6}, "tags": {"name": "Lake"}}
    rec = element_to_record(el, "g")
    assert rec["lat"] == pytest.approx(12.95) and rec["lon"] == pytest.approx(77.55)
    assert rec["extent_m"] > 10_000


def test_curated_file_is_valid_and_never_supplies_coordinates():
    entries = load_curated()
    assert len(entries) >= 50
    for e in entries:
        assert not hasattr(e, "lat") and not hasattr(e, "lon")
        assert e.cost is None or e.cost[0] <= e.cost[1] <= e.cost[2]


def test_curated_rejects_bad_entries(tmp_path):
    bad = tmp_path / "c.yaml"
    bad.write_text("entries:\n  - key: a\n    match: {name: X}\n    experience_tags: [flying]\n",
                   encoding="utf-8")
    with pytest.raises(ValueError):
        load_curated(bad)
