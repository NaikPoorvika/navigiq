"""Recommendation scoring (sections 34-36, 87-89). Pure: synthetic POIRecords."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.domain.taxonomy import PartyType
from app.services.poi.repository import HoursInterval, POIRecord
from app.services.recommendation.scoring import (
    NEUTRAL, Anchor, NoveltyContext, Preferences, RecommendationRequest, budget_fit, config,
    geographic_relevance, hard_filter, interest_match, jaccard, mood_match, party_suitability,
    score_poi, select_diverse, similarity_to, weather_fit,
)


def poi(pid=1, name="P", category="cafe", tags=(), moods=(), secondary=(), cost=(100, 300, 600),
        io="indoor", quality=0.5, prominence=0.1, suit=None, chain=None, region="CITY_CORE",
        dist=5.0, anchor_km=None, diet=(), access=(), hours=None, hours_conf=0.3, curated=False,
        visit=(30, 60, 120), escape=False, editorial=None):
    s = {k: None for k in ("family_friendly", "kids_friendly", "senior_friendly",
                           "couple_friendly", "solo_friendly", "group_friendly")}
    s.update(suit or {})
    r = POIRecord(
        id=pid, slug=f"p{pid}", name=name, category=category, secondary=list(secondary),
        lat=12.97, lon=77.59, distance_from_center_km=dist, region_bucket=region, district=None,
        locality="Testnagar", neighborhood=None, experience_tags=list(tags), mood_tags=list(moods),
        food_tags=[], dietary_tags=list(diet), accessibility_tags=list(access), indoor_outdoor=io,
        weather_suitability="rain_friendly" if io == "indoor" else "dry_weather", visit=visit,
        cost=cost, cost_confidence="category_default", hours_confidence=hours_conf,
        prominence=prominence, quality=quality, editorial=editorial, curated=curated,
        recommendable=True, suitability=s, primary_destination=escape, large_time_block=escape,
        short_escape=escape, day_trip=escape, is_chain=chain is not None, chain_key=chain,
        short_description=None, image_url=None, image_attribution=None, source_names=[],
        source_urls=[], source_license="ODbL-1.0", anchor_km=anchor_km)
    if hours is not None:
        r.hours = [HoursInterval(o, c, False, 0.9) for o, c in hours]
        r.hours_loaded_for_day = 0
        r.hours_confidence = 0.9
    return r


CFG = config()


# --- components ---------------------------------------------------------------------------------

def test_neutral_when_no_signal():
    r = RecommendationRequest()
    p = poi()
    assert interest_match(p, r, CFG) == NEUTRAL
    assert mood_match(p, r) == NEUTRAL
    assert party_suitability(p, r) == NEUTRAL
    assert budget_fit(p, r) == NEUTRAL
    assert weather_fit(p, r) == NEUTRAL


def test_interest_match_prefers_exact_category():
    r = RecommendationRequest(interests=["cafe"])
    assert interest_match(poi(category="cafe"), r, CFG) > interest_match(
        poi(category="dessert", secondary=["cafe"]), r, CFG) > interest_match(
        poi(category="park"), r, CFG)


def test_mood_match_requires_evidence_beyond_category():
    r = RecommendationRequest(moods=["romantic"])
    tagged = poi(category="lake", moods=["romantic"])
    plain_cafe = poi(category="cafe")
    assert mood_match(tagged, r) == 1.0
    assert mood_match(plain_cafe, r) < CFG["relevance"]["min_relevance"]


def test_party_suitability_true_unknown_false():
    r = RecommendationRequest(party_type=PartyType.COUPLE)
    assert party_suitability(poi(suit={"couple_friendly": True}), r) == 1.0
    assert party_suitability(poi(), r) == NEUTRAL
    assert party_suitability(poi(suit={"couple_friendly": False}), r) < 0.1


def test_budget_fit():
    r = RecommendationRequest(budget_per_person=500)
    assert budget_fit(poi(cost=(0, 0, 0)), r) == 1.0
    assert budget_fit(poi(cost=(100, 300, 700)), r) == 0.75
    cheap = RecommendationRequest(moods=["budget"])
    assert budget_fit(poi(cost=(0, 0, 0)), cheap) > budget_fit(poi(cost=(500, 700, 900)), cheap)


def test_weather_prefers_indoor_when_raining():
    r = RecommendationRequest(rain_expected=True)
    assert weather_fit(poi(io="indoor"), r) > weather_fit(poi(io="mixed"), r) > weather_fit(
        poi(io="outdoor"), r)


def test_geography_local_anchor_decays_with_distance():
    r = RecommendationRequest(anchor=Anchor("T", 12.97, 77.59, 3.0))
    assert geographic_relevance(poi(anchor_km=0.2), r, CFG) > geographic_relevance(
        poi(anchor_km=4.0), r, CFG)


def test_geography_regional_sweet_spot():
    r = RecommendationRequest(scope="regional")
    assert geographic_relevance(poi(dist=60), r, CFG) == 1.0
    assert geographic_relevance(poi(dist=5), r, CFG) < 0.6


def test_preferences_favorite_and_disliked():
    r = RecommendationRequest(preferences=Preferences(favorite_categories={"lake"},
                                                      disliked_categories={"mall"}))
    from app.services.recommendation.scoring import preference_fit
    assert preference_fit(poi(category="lake"), r, CFG) > NEUTRAL
    assert preference_fit(poi(category="mall"), r, CFG) < 0.1


# --- hard filters -------------------------------------------------------------------------------

@pytest.mark.parametrize("req,p,reason", [
    (RecommendationRequest(avoid_interests=["mall"]), poi(category="mall"), "avoided_category"),
    (RecommendationRequest(avoid_interests=["nightlife"]), poi(category="nightlife"),
     "avoided_category"),
    (RecommendationRequest(budget_per_person=200), poi(cost=(100, 300, 600)), "over_budget"),
    (RecommendationRequest(kids=True), poi(suit={"kids_friendly": False}), "not_kid_friendly"),
    (RecommendationRequest(party_type=PartyType.FAMILY_WITH_KIDS),
     poi(category="nightlife", suit={"kids_friendly": False}), "not_kid_friendly"),
    (RecommendationRequest(accessibility=["wheelchair_accessible"]), poi(),
     "accessibility_unverified"),
    (RecommendationRequest(dietary=["vegetarian"]), poi(category="restaurant"),
     "dietary_unverified"),
    (RecommendationRequest(indoor_preference="indoor"), poi(io="outdoor"), "outdoor_excluded"),
    (RecommendationRequest(rain_expected=True, weather_sensitive=True), poi(io="outdoor"),
     "rain_outdoor"),
    (RecommendationRequest(exclude_ids=[1]), poi(pid=1), "excluded_id"),
    (RecommendationRequest(mode="hidden_gems"), poi(chain="brand:x", quality=0.8), "not_hidden_gem"),
    (RecommendationRequest(mode="hidden_gems"), poi(curated=True, quality=0.9), "not_hidden_gem"),
    (RecommendationRequest(mode="surprise"), poi(quality=0.2), "below_surprise_quality"),
])
def test_hard_filters(req, p, reason):
    assert hard_filter(p, req) == reason


def test_dietary_is_satisfied_by_stricter_tags_and_ignored_for_non_food():
    req = RecommendationRequest(dietary=["vegetarian"])
    assert hard_filter(poi(category="restaurant", diet=["pure_vegetarian"]), req) is None
    assert hard_filter(poi(category="museum"), req) is None


def test_closed_now_is_filtered_only_with_reliable_hours():
    req = RecommendationRequest(at=datetime(2026, 9, 21, 20, 0), require_open=True)
    assert hard_filter(poi(hours=[(600, 1080)]), req) == "closed_at_requested_time"
    assert hard_filter(poi(), req) is None


def test_hidden_gem_accepts_offbeat_or_undocumented():
    req = RecommendationRequest(mode="hidden_gems")
    assert hard_filter(poi(tags=["offbeat"], prominence=0.8, quality=0.5), req) is None
    assert hard_filter(poi(prominence=0.05, quality=0.5), req) is None
    assert hard_filter(poi(prominence=0.6, quality=0.5), req) == "not_hidden_gem"


# --- scoring, gates and reasons ---------------------------------------------------------------

def test_requested_category_dominates_a_famous_irrelevant_place():
    req = RecommendationRequest(interests=["cafe"])
    cafe = score_poi(poi(pid=1, category="cafe", quality=0.3), req)
    garden = score_poi(poi(pid=2, category="garden", quality=0.95, prominence=0.9), req)
    assert cafe.score > garden.score


def test_theme_categories_act_as_moods():
    req = RecommendationRequest(interests=["photography", "cafe"])
    assert "photography" in req.moods and req.categories == ["cafe"]


def test_reason_codes_are_derived_not_invented():
    req = RecommendationRequest(interests=["cafe"], budget_per_person=500,
                                party_type=PartyType.COUPLE, rain_expected=True)
    s = score_poi(poi(tags=["photogenic"], suit={"couple_friendly": True}), req)
    assert {"MATCHES_CAFE", "UNDER_BUDGET", "GOOD_FOR_COUPLES", "RAIN_FRIENDLY",
            "GOOD_FOR_PHOTOGRAPHY"} <= set(s.reasons)
    assert "FREE_ENTRY" not in s.reasons


def test_no_reason_without_evidence():
    s = score_poi(poi(category="park"), RecommendationRequest(interests=["cafe"]))
    assert "MATCHES_CAFE" not in s.reasons


# --- novelty ----------------------------------------------------------------------------------

def test_recently_shown_penalty_strong_for_different_mild_for_discover():
    shown = NoveltyContext(shown_recently={1})
    base = score_poi(poi(pid=1), RecommendationRequest()).score
    mild = score_poi(poi(pid=1), RecommendationRequest(novelty=shown)).score
    strong = score_poi(poi(pid=1), RecommendationRequest(novelty=shown, mode="surprise")).score
    assert strong < mild < base


def test_dismissed_is_penalised_not_permanent_ban():
    nov = NoveltyContext(dismissed={1})
    s = score_poi(poi(pid=1), RecommendationRequest(novelty=nov)).score
    assert 0 < s < score_poi(poi(pid=1), RecommendationRequest()).score


def test_different_mode_excludes_previous_results():
    req = RecommendationRequest(mode="different", novelty=NoveltyContext(previous_ids={1}))
    assert hard_filter(poi(pid=1), req) == "previously_shown"


def test_saved_boost_in_preferences():
    from app.services.recommendation.scoring import preference_fit
    r = RecommendationRequest(preferences=Preferences(saved_categories={"cafe": 3}))
    assert preference_fit(poi(category="cafe"), r, CFG) > NEUTRAL


# --- selection ---------------------------------------------------------------------------------

def _scored(items):
    return [score_poi(p, RecommendationRequest()) for p in items]


def test_diversity_caps_categories_and_chains():
    items = [poi(pid=i, category="cafe", quality=0.9 - i * 0.01) for i in range(6)]
    items += [poi(pid=10 + i, category="park", quality=0.5) for i in range(3)]
    items += [poi(pid=20 + i, category="dessert", chain="brand:x", quality=0.8) for i in range(3)]
    chosen = select_diverse(_scored(items), 8)
    cats = [s.poi.category for s in chosen]
    assert cats.count("cafe") <= CFG["diversity"]["max_per_category"]
    assert sum(1 for s in chosen if s.poi.chain_key == "brand:x") <= 1


def test_requested_category_is_not_capped():
    items = [poi(pid=i, category="cafe", quality=0.9 - i * 0.01) for i in range(6)]
    chosen = select_diverse(_scored(items), 6, requested={"cafe"})
    assert len(chosen) == 6


def test_selection_is_deterministic():
    items = [poi(pid=i, category=c, quality=0.5) for i, c in enumerate(["cafe", "park", "lake"] * 3)]
    a = [s.poi.id for s in select_diverse(_scored(items), 5)]
    b = [s.poi.id for s in select_diverse(_scored(list(reversed(items))), 5)]
    assert a == b


def test_surprise_is_seeded_and_stays_in_quality_pool():
    items = [poi(pid=i, category=["cafe", "park", "lake", "museum"][i % 4],
                 quality=0.5 + (i % 5) * 0.08) for i in range(40)]
    req = RecommendationRequest(mode="surprise")
    scored = [score_poi(p, req) for p in items if hard_filter(p, req) is None]
    a = [s.poi.id for s in select_diverse(scored, 3, mode="surprise", seed=11)]
    b = [s.poi.id for s in select_diverse(scored, 3, mode="surprise", seed=11)]
    assert a == b
    assert len(a) == 3
    pool = sorted(scored, key=lambda s: -s.score)[:CFG["surprise"]["pool_size"]]
    assert set(a) <= {s.poi.id for s in pool}
    heroes = {select_diverse(scored, 3, mode="surprise", seed=s)[0].poi.id for s in range(20)}
    assert len(heroes) >= 3, "surprise must vary across seeds, not always pick the top item"


def test_jaccard():
    assert jaccard({1, 2}, {1, 2}) == 1.0
    assert jaccard({1, 2}, {3}) == 0.0
    assert jaccard(set(), set()) == 0.0


def test_similarity_uses_more_than_category():
    ref = poi(category="lake", tags=["peaceful", "nature", "scenic"], moods=["peaceful"],
              io="outdoor", cost=(0, 0, 0))
    garden = poi(pid=2, category="garden", tags=["peaceful", "nature"], moods=["peaceful"],
                 io="outdoor", cost=(0, 0, 50))
    mall = poi(pid=3, category="mall", tags=["shopping"], io="indoor", cost=(0, 0, 0))
    assert similarity_to(garden, ref, None) > similarity_to(mall, ref, None)
