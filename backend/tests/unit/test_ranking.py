"""Tests for NQ-017 deterministic ranking."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.poi.ranking import (  # noqa: E402
    DeterministicRanker,
    RankingContext,
)


def poi(pid, category, distance_m=500, prominence=0.0, indoor=None,
        secondary=None, **kw):
    return {
        "id": pid, "name": f"POI-{pid}", "category": category,
        "distance_m": distance_m, "prominence": prominence,
        "indoor": indoor, "secondary_categories": secondary or [], **kw,
    }


@pytest.fixture
def ranker():
    return DeterministicRanker()


@pytest.fixture
def ctx():
    return RankingContext(wanted_categories=["cafe"], chosen_category_counts={})


# --- category match ------------------------------------------------------

def test_exact_category_match_scores_one(ranker, ctx):
    s = ranker.score(poi(1, "cafe"), ctx)
    assert s.components["category_match"] == 1.0


def test_wrong_category_scores_zero(ranker, ctx):
    s = ranker.score(poi(1, "temple"), ctx)
    assert s.components["category_match"] == 0.0


def test_secondary_category_scores_its_link_weight(ranker, ctx):
    """A lake linked to sunset at 0.6 should partially match a sunset request."""
    c = RankingContext(wanted_categories=["sunset"], chosen_category_counts={})
    s = ranker.score(
        poi(1, "lake", secondary=[{"category": "sunset", "weight": 0.6}]), c)
    assert s.components["category_match"] == 0.6


def test_no_preference_is_neutral_not_zero(ranker):
    c = RankingContext(wanted_categories=[], chosen_category_counts={})
    s = ranker.score(poi(1, "cafe"), c)
    assert s.components["category_match"] == 0.5


# --- proximity -----------------------------------------------------------

def test_closer_scores_higher(ranker, ctx):
    near = ranker.score(poi(1, "cafe", distance_m=100), ctx)
    far = ranker.score(poi(2, "cafe", distance_m=3000), ctx)
    assert near.components["proximity"] > far.components["proximity"]
    assert near.score > far.score


def test_proximity_never_negative_beyond_falloff(ranker, ctx):
    s = ranker.score(poi(1, "cafe", distance_m=50_000), ctx)
    assert s.components["proximity"] == 0.0


def test_zero_distance_scores_full_proximity(ranker, ctx):
    s = ranker.score(poi(1, "cafe", distance_m=0), ctx)
    assert s.components["proximity"] == 1.0


# --- diversity -----------------------------------------------------------

def test_diversity_decays_with_repeats(ranker):
    first = RankingContext(["cafe"], {})
    second = RankingContext(["cafe"], {"cafe": 1})
    third = RankingContext(["cafe"], {"cafe": 2})
    a = ranker.score(poi(1, "cafe"), first).components["diversity"]
    b = ranker.score(poi(1, "cafe"), second).components["diversity"]
    c = ranker.score(poi(1, "cafe"), third).components["diversity"]
    assert a > b > c


def test_diversity_unaffected_by_other_categories(ranker):
    c = RankingContext(["cafe"], {"temple": 3})
    assert ranker.score(poi(1, "cafe"), c).components["diversity"] == 1.0


# --- prominence ----------------------------------------------------------

def test_editorial_score_overrides_prominence(ranker, ctx):
    """Curated POIs carry a hand-set editorial score that wins."""
    s = ranker.score(poi(1, "cafe", prominence=0.02, editorial_score=0.9), ctx)
    assert s.components["prominence"] == 0.9


def test_prominence_contributes_but_does_not_dominate(ranker, ctx):
    """94% of real POIs score below 0.06. A distant famous POI must not beat
    a near relevant one."""
    famous_far = ranker.score(poi(1, "cafe", distance_m=4500, prominence=1.0), ctx)
    plain_near = ranker.score(poi(2, "cafe", distance_m=100, prominence=0.0), ctx)
    assert plain_near.score > famous_far.score


# --- weather -------------------------------------------------------------

def test_rain_favours_indoor(ranker):
    c = RankingContext(["cafe"], {}, is_raining=True)
    indoor = ranker.score(poi(1, "cafe", indoor=True), c)
    outdoor = ranker.score(poi(2, "cafe", indoor=False), c)
    assert indoor.components["weather_fit"] > outdoor.components["weather_fit"]


def test_golden_hour_favours_sunset_spots(ranker):
    c = RankingContext(["sunset"], {}, arrival_min_of_day=18 * 60)
    sunset = ranker.score(poi(1, "sunset"), c)
    other = ranker.score(poi(2, "cafe"), c)
    assert sunset.components["weather_fit"] > other.components["weather_fit"]


def test_sunset_bonus_not_applied_at_midday(ranker):
    noon = RankingContext(["sunset"], {}, arrival_min_of_day=12 * 60)
    dusk = RankingContext(["sunset"], {}, arrival_min_of_day=18 * 60)
    assert (ranker.score(poi(1, "sunset"), dusk).components["weather_fit"]
            > ranker.score(poi(1, "sunset"), noon).components["weather_fit"])


# --- rank() --------------------------------------------------------------

def test_rank_respects_limit(ranker):
    pois = [poi(i, "cafe", distance_m=i * 100) for i in range(1, 30)]
    assert len(ranker.rank(pois, ["cafe"], limit=5)) == 5


def test_rank_is_deterministic(ranker):
    pois = [poi(i, "cafe", distance_m=i * 137) for i in range(1, 20)]
    a = [s.poi["id"] for s in ranker.rank(pois, ["cafe"], limit=10)]
    b = [s.poi["id"] for s in ranker.rank(pois, ["cafe"], limit=10)]
    assert a == b


def test_rank_interleaves_categories_rather_than_clustering(ranker):
    """THE reason rank() is greedy rather than a single sort. Sorted once,
    the top 5 would all be cafes because each was scored against an empty
    selection."""
    pois = ([poi(i, "cafe", distance_m=100 + i) for i in range(1, 11)]
            + [poi(100 + i, "temple", distance_m=150 + i) for i in range(1, 11)])
    top = ranker.rank(pois, ["cafe", "temple"], limit=6)
    cats = [s.poi["category"] for s in top]
    assert len(set(cats)) > 1, f"all one category: {cats}"


def test_different_requests_return_different_places(ranker):
    """Guards against the ranker always surfacing the same handful."""
    pois = ([poi(i, "cafe", distance_m=i * 200) for i in range(1, 11)]
            + [poi(100 + i, "temple", distance_m=i * 200) for i in range(1, 11)]
            + [poi(200 + i, "park", distance_m=i * 200) for i in range(1, 11)])
    a = {s.poi["id"] for s in ranker.rank(pois, ["cafe"], limit=5)}
    b = {s.poi["id"] for s in ranker.rank(pois, ["temple"], limit=5)}
    c = {s.poi["id"] for s in ranker.rank(pois, ["park"], limit=5)}
    assert a != b and b != c and a != c


def test_components_sum_to_score(ranker, ctx):
    s = ranker.score(poi(1, "cafe", distance_m=250, prominence=0.4), ctx)
    expected = sum(ranker.w[k] * v for k, v in s.components.items())
    assert s.score == pytest.approx(expected)


def test_breakdown_is_exposed_for_explanations(ranker, ctx):
    d = ranker.score(poi(1, "cafe"), ctx).to_dict()
    assert "rank_score" in d
    assert set(d["rank_components"]) == {
        "category_match", "prominence", "proximity", "diversity", "weather_fit"}
