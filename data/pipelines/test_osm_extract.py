"""Tests for NQ-011 POI staging extraction.

Unit tests for the pure filter/centroid logic, plus an integration test against
a synthetic .pbf generated at test time. No large fixture is committed.

Run:  python -m pytest data/pipelines/test_osm_extract.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import osmium
import osmium.osm.mutable as mutable
import pytest

sys.path.insert(0, str(Path(__file__).parent))

from osm_extract import bbox_centre, matches_filter, run  # noqa: E402


@pytest.mark.parametrize("tags", [
    {"amenity": "cafe"},
    {"tourism": "museum"},
    {"leisure": "park"},
    {"historic": "monument"},
    {"shop": "books"},
    {"craft": "pottery"},
    {"natural": "water"},
    {"natural": "peak"},
    {"man_made": "tower"},
])
def test_matches_filter_accepts_poi_tags(tags):
    assert matches_filter(tags) is True


@pytest.mark.parametrize("tags", [
    {},
    {"name": "Some Road"},
    {"highway": "residential"},
    {"building": "apartments"},
    {"landuse": "residential"},
    {"natural": "tree"},
    {"natural": "scrub"},
    {"man_made": "manhole"},
    {"man_made": "pond"},
])
def test_matches_filter_rejects_non_poi_tags(tags):
    assert matches_filter(tags) is False


def test_narrow_keys_are_value_scoped_not_key_scoped():
    assert matches_filter({"natural": "water"}) is True
    assert matches_filter({"natural": "tree"}) is False
    assert matches_filter({"man_made": "tower"}) is True
    assert matches_filter({"man_made": "pond"}) is False


def test_bbox_centre_empty_returns_none():
    assert bbox_centre([]) is None


def test_bbox_centre_single_point_is_that_point():
    assert bbox_centre([(12.5, 77.5)]) == (12.5, 77.5)


def test_bbox_centre_square():
    coords = [(12.0, 77.0), (12.0, 78.0), (13.0, 78.0), (13.0, 77.0)]
    assert bbox_centre(coords) == (12.5, 77.5)


def test_bbox_centre_ignores_point_order():
    a = bbox_centre([(12.0, 77.0), (13.0, 78.0)])
    b = bbox_centre([(13.0, 78.0), (12.0, 77.0)])
    assert a == b


@pytest.fixture
def synthetic_pbf(tmp_path: Path) -> Path:
    """Tiny extract: one POI node, one non-POI node, one POI area, one non-POI way.

    pyosmium 4.x requires mutable OSM objects; plain dicts write id=0 for every
    feature and then fail area assembly with "Way ID twice in input".
    """
    path = tmp_path / "fixture.osm.pbf"
    corners = [(1, 12.94, 77.59), (2, 12.94, 77.61), (3, 12.96, 77.61), (4, 12.96, 77.59)]

    with osmium.SimpleWriter(str(path)) as w:
        for nid, lat, lon in corners:
            w.add_node(mutable.Node(id=nid, location=(lon, lat), tags={}))
        w.add_node(mutable.Node(id=100, location=(77.6408, 12.9784),
                                tags={"amenity": "cafe", "name": "Test Cafe"}))
        w.add_node(mutable.Node(id=101, location=(77.6400, 12.9780),
                                tags={"highway": "crossing"}))
        w.add_way(mutable.Way(id=200, nodes=[1, 2, 3, 4, 1],
                              tags={"leisure": "park", "name": "Test Park", "area": "yes"}))
        w.add_way(mutable.Way(id=201, nodes=[1, 2],
                              tags={"highway": "residential", "name": "Test Road"}))
    return path


def _records(jsonl: Path) -> list:
    return [json.loads(x) for x in jsonl.read_text(encoding="utf-8").splitlines()]


def test_extraction_emits_poi_node(synthetic_pbf, tmp_path):
    out = tmp_path / "staging.jsonl"
    run(synthetic_pbf, out, tmp_path / "r.csv", tmp_path / "m.json")
    nodes = [r for r in _records(out) if r["osm_type"] == "node"]
    assert len(nodes) == 1
    rec = nodes[0]
    assert rec["osm_id"] == 100
    assert rec["source_ref"] == "node/100"
    assert rec["tags"]["name"] == "Test Cafe"
    assert rec["lat"] == pytest.approx(12.9784, abs=1e-5)
    assert rec["lon"] == pytest.approx(77.6408, abs=1e-5)


def test_extraction_assembles_area_with_centroid(synthetic_pbf, tmp_path):
    """The regression this task hinges on. A node-only reader silently loses
    Lalbagh, Cubbon Park and Bangalore Palace."""
    out = tmp_path / "staging.jsonl"
    run(synthetic_pbf, out, tmp_path / "r.csv", tmp_path / "m.json")
    areas = [r for r in _records(out) if r["osm_type"] in ("way", "relation")]
    assert len(areas) == 1, "tagged closed way must be assembled as an area"
    assert areas[0]["osm_id"] == 200
    assert areas[0]["lat"] == pytest.approx(12.95, abs=1e-4)
    assert areas[0]["lon"] == pytest.approx(77.60, abs=1e-4)


def test_extraction_filters_out_non_poi_features(synthetic_pbf, tmp_path):
    out = tmp_path / "staging.jsonl"
    run(synthetic_pbf, out, tmp_path / "r.csv", tmp_path / "m.json")
    ids = {r["osm_id"] for r in _records(out)}
    assert 101 not in ids
    assert 201 not in ids


def test_staging_schema_is_exactly_the_nq011_contract(synthetic_pbf, tmp_path):
    """Extra fields here mean NQ-013 normalization leaked into NQ-011."""
    out = tmp_path / "staging.jsonl"
    run(synthetic_pbf, out, tmp_path / "r.csv", tmp_path / "m.json")
    expected = {"osm_type", "osm_id", "source_ref", "lat", "lon", "tags"}
    for rec in _records(out):
        assert set(rec.keys()) == expected


def test_manifest_records_provenance(synthetic_pbf, tmp_path):
    out = tmp_path / "staging.jsonl"
    manifest = tmp_path / "m.json"
    run(synthetic_pbf, out, tmp_path / "r.csv", manifest)
    m = json.loads(manifest.read_text(encoding="utf-8"))
    assert m["task"] == "NQ-011"
    assert m["poi_candidates"] == 2
    assert m["by_osm_type"] == {"node": 1, "way": 1}
    assert "ODbL" in m["license"]
    assert m["source_bytes"] > 0
    assert "pyosmium_version" in m


def test_unmapped_report_lists_tag_combinations(synthetic_pbf, tmp_path):
    out = tmp_path / "staging.jsonl"
    report = tmp_path / "r.csv"
    run(synthetic_pbf, out, report, tmp_path / "m.json")
    text = report.read_text(encoding="utf-8")
    assert "tag_combination,count" in text
    assert "amenity=cafe" in text
    assert "leisure=park" in text
    assert "highway=residential" not in text


def test_extraction_is_deterministic(synthetic_pbf, tmp_path):
    """NQ-013 idempotency depends on byte-identical staging output."""
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    run(synthetic_pbf, a, tmp_path / "ra.csv", tmp_path / "ma.json")
    run(synthetic_pbf, b, tmp_path / "rb.csv", tmp_path / "mb.json")
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")
