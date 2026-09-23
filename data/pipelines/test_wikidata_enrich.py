"""Offline tests for the matching logic - no network, no database."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from wikidata_enrich import (  # noqa: E402
    Grid, Item, Poi, accept, assign, best_match, commons_filename, parse_point,
    similarity, strip_html,
)

LALBAGH = (12.9507, 77.5848)


def item(qid, labels, lat, lon, links=10):
    return Item(qid, labels, lat, lon, f"{qid}.jpg", links)


def test_identical_names_score_one():
    assert similarity("cubbon park", "cubbon park") == 1.0


def test_unrelated_names_score_low():
    assert similarity("cubbon park", "tadka singh") < 0.1


def test_parse_point_returns_lat_lon():
    assert parse_point("Point(77.5946 12.9716)") == (12.9716, 77.5946)
    assert parse_point("garbage") is None


def test_commons_filename_decodes_url():
    url = "http://commons.wikimedia.org/wiki/Special:FilePath/Lal%20Bagh%20Glass_House.jpg"
    assert commons_filename(url) == "Lal Bagh Glass House.jpg"


def test_strip_html_removes_tags_and_truncates():
    assert strip_html('<a href="x">Jane&nbsp;Doe</a>') == "Jane Doe"
    assert len(strip_html("x" * 500, limit=50)) == 50


def test_accept_rules():
    assert accept(0.5, 100)            # close, decent name
    assert not accept(0.5, 400)        # farther needs a strong name
    assert accept(0.7, 500)
    assert not accept(0.9, 800)        # too far regardless


def test_matches_same_place_by_alias():
    pois = [Poi(1, "lalbagh botanical garden", *LALBAGH)]
    it = item("Q1", ["Lal Bagh", "Lalbagh Botanical Garden"], 12.9510, 77.5850)
    m = best_match(it, Grid(pois))
    assert m is not None and m[0].id == 1


def test_same_name_far_away_is_rejected():
    """Name alone is never enough - a namesake 2 km away is a different place."""
    pois = [Poi(1, "lalbagh botanical garden", 12.97, 77.60)]
    it = item("Q1", ["Lalbagh Botanical Garden"], *LALBAGH)
    assert best_match(it, Grid(pois)) is None


def test_nearby_but_different_name_is_rejected():
    """'Lalbagh' is also a nursing home right next to the garden."""
    pois = [Poi(1, "lalbagh nursing home", 12.9508, 77.5849)]
    it = item("Q1", ["Lalbagh Botanical Garden"], *LALBAGH)
    assert best_match(it, Grid(pois)) is None


def test_one_photo_per_poi_keeps_most_notable():
    pois = [Poi(1, "cubbon park", 12.9763, 77.5929)]
    items = [
        item("Q_small", ["Cubbon Park"], 12.9764, 77.5930, links=2),
        item("Q_big", ["Cubbon Park"], 12.9765, 77.5931, links=40),
    ]
    chosen = assign(items, Grid(pois))
    assert chosen[1][0].qid == "Q_big"


# ----------------------------------------------- fallback, retry and cache

import json  # noqa: E402

import wikidata_enrich as wd  # noqa: E402


def test_items_from_pages_needs_coordinates_and_image():
    pages = {
        "1": {"title": "Cubbon Park", "coordinates": [{"lat": 12.97, "lon": 77.59}],
              "pageimage": "Cubbon_Park.jpg", "pageprops": {"wikibase_item": "Q1"}},
        "2": {"title": "No photo", "coordinates": [{"lat": 12.9, "lon": 77.5}]},
        "3": {"title": "No coords", "pageimage": "x.jpg"},
    }
    items = wd.items_from_pages(pages)
    assert [i.qid for i in items] == ["Q1"]
    assert items[0].filename == "Cubbon Park.jpg"


def test_merge_pages_combines_continuation_batches():
    pages = {}
    wd.merge_pages(pages, {"1": {"title": "A", "coordinates": [{"lat": 1, "lon": 2}]}})
    wd.merge_pages(pages, {"1": {"title": "A", "pageimage": "a.jpg"}})
    assert pages["1"]["pageimage"] == "a.jpg" and pages["1"]["coordinates"]


def test_full_circle_is_split_and_smaller_circles_are_not():
    calls = []

    def fetch(lat, lon, radius):
        calls.append(radius)
        n = wd.GEO_LIMIT if radius == wd.GEO_RADIUS_M else 3
        return {f"{lat:.4f},{lon:.4f},{radius},{i}": {"title": "x"} for i in range(n)}

    out = {}
    wd.cover(12.97, 77.59, wd.GEO_RADIUS_M, fetch, out)
    assert calls[0] == wd.GEO_RADIUS_M
    assert len(calls) == 5                     # parent + four children, no deeper
    assert all(r == int(wd.GEO_RADIUS_M * 0.75) for r in calls[1:])


def test_child_circles_cover_the_parent_square():
    """Each child's radius must reach the far corner of its quadrant."""
    r = 10_000
    corner = (r / 2) * 2 ** 0.5
    assert int(r * 0.75) >= corner


def test_grid_circles_cover_the_area_without_gaps():
    step_km = wd.GEO_RADIUS_M / 1000 * 1.4
    assert (step_km / 2) * 2 ** 0.5 <= wd.GEO_RADIUS_M / 1000
    assert len(wd.grid_points(60)) == 121


class FakeResponse:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_retry_waits_out_a_rate_limit(monkeypatch):
    responses = iter([FakeResponse(429, {"Retry-After": "7"}), FakeResponse(200)])
    slept = []
    monkeypatch.setattr(wd.time, "sleep", slept.append)

    class Client:
        def get(self, url, params):
            return next(responses)

    assert wd.get_with_retry(Client(), "https://query.wikidata.org/sparql", {}).status_code == 200
    assert slept == [7]


def test_cached_answer_is_reused(tmp_path, monkeypatch):
    cache = tmp_path / "items.json"
    item = wd.Item("Q1", ["Cubbon Park"], 12.97, 77.59, "c.jpg", 12)
    cache.write_text(json.dumps({"source": "wdqs", "fetched_at": "now",
                                 "items": [wd.asdict(item)]}))
    monkeypatch.setattr(wd, "CACHE", cache)

    def boom():
        raise AssertionError("must not query when a cache exists")

    monkeypatch.setattr(wd, "items_from_wdqs", boom)
    assert wd.fetch_items()[0].qid == "Q1"


def test_query_service_failure_falls_back_to_wikipedia(tmp_path, monkeypatch):
    monkeypatch.setattr(wd, "CACHE", tmp_path / "items.json")

    def down():
        raise RuntimeError("429")

    fallback = [wd.Item("Q2", ["Lalbagh"], 12.95, 77.58, "l.jpg", 30)]
    monkeypatch.setattr(wd, "items_from_wdqs", down)
    monkeypatch.setattr(wd, "items_from_wikipedia", lambda: fallback)
    assert wd.fetch_items()[0].qid == "Q2"
    assert json.loads((tmp_path / "items.json").read_text())["source"] == "wikipedia"


# ------------------------------------------- the "names only part" rule
# Real cases from the first live dry run.

import pytest  # noqa: E402

from wikidata_enrich import names_only_part  # noqa: E402

WRONG = [
    ("Bengaluru", "bengaluru logo"),
    ("Yelahanka", "yelahanka lake"),
    ("Electronic City", "seasons electronic city"),
    ("Gottigere", "gottigere tank"),
    ("Chikkajala", "chikkajala fort"),
    ("Abbigere", "abbigere lake"),
    ("Marathahalli", "marathahalli bridge"),
]

RIGHT = [
    ("Cubbon Park", "cubbon park"),
    ("Freedom Park, Bangalore", "freedom park"),
    ("St. Mary's Basilica, Bangalore", "st mary's basilica"),
    ("Tipu Sultan's Summer Palace", "tippu's summer palace"),
    ("Lalbagh Botanical Garden, Bangalore", "lalbagh botanical gardens"),
    ("Savandurga", "savanadurga"),
    ("Nageshvara Temple", "naganatheshwara temple"),
    ("Government Museum, Bengaluru", "karnataka government museum"),
    ("Mavalli Tiffin Room", "mavalli tiffin rooms"),
]


@pytest.mark.parametrize("label,poi", WRONG)
def test_area_named_after_is_rejected(label, poi):
    assert names_only_part(label, poi)


@pytest.mark.parametrize("label,poi", RIGHT)
def test_real_matches_are_kept(label, poi):
    assert not names_only_part(label, poi)


def test_locality_is_not_matched_to_the_lake_named_after_it():
    pois = [Poi(1, "yelahanka lake", 13.1005, 77.5963)]
    it = item("Q_area", ["Yelahanka"], 13.1040, 77.5990, links=21)
    assert best_match(it, Grid(pois)) is None


def test_alias_that_names_the_whole_place_still_matches():
    """'Ulsoor Lake' has the alias 'Halasuru Lake' - that one names it fully."""
    pois = [Poi(1, "halasuru lake", 12.9817, 77.6192)]
    it = item("Q_lake", ["Ulsoor Lake", "Halasuru Lake"], 12.9820, 77.6200)
    assert best_match(it, Grid(pois)) is not None
