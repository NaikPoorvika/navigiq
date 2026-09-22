"""Pure recommendation scoring (ADR-027). No database, no LLM, no clock.

  hard filters  -> a POI failing any is excluded, never down-ranked
  components    -> twelve scores in [0, 1], neutral 0.5 when there is no signal
  total         -> weighted sum x novelty multiplier (mode dependent)
  selection     -> greedy with category/chain diversity decay and caps
  reason codes  -> derived deterministically from components and attributes;
                   the LLM may phrase them but never add to them
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Literal

import yaml

from app.core.paths import config_path
from app.domain.taxonomy import (
    FOOD_CATEGORIES, MOOD_DEFINITIONS, Mood, PartyType, is_valid_category, is_valid_mood,
)
from app.services.poi.repository import POIRecord

Mode = Literal["discover", "surprise", "different", "hidden_gems", "similar", "for_you",
               "search", "plan"]
Scope = Literal["local", "city", "regional", "anywhere"]

NEUTRAL = 0.5


@lru_cache(maxsize=1)
def config() -> dict:
    cfg = yaml.safe_load(config_path("recommendation_weights.yaml").read_text(encoding="utf-8"))
    total = sum(cfg["weights"].values())
    if not math.isclose(total, 1.0, abs_tol=1e-6):
        raise ValueError(f"recommendation weights must sum to 1.0, got {total}")
    return cfg


@dataclass
class NoveltyContext:
    shown_recently: set[int] = field(default_factory=set)
    dismissed: set[int] = field(default_factory=set)
    visited: set[int] = field(default_factory=set)
    saved: set[int] = field(default_factory=set)
    previous_ids: set[int] = field(default_factory=set)      # last result set
    previous_categories: set[str] = field(default_factory=set)


@dataclass
class Preferences:
    favorite_categories: set[str] = field(default_factory=set)
    disliked_categories: set[str] = field(default_factory=set)
    favorite_moods: set[str] = field(default_factory=set)
    saved_categories: dict[str, int] = field(default_factory=dict)


@dataclass
class Anchor:
    name: str
    lat: float
    lon: float
    radius_km: float


@dataclass
class RecommendationRequest:
    interests: list[str] = field(default_factory=list)      # categories + tags
    moods: list[str] = field(default_factory=list)
    avoid_interests: list[str] = field(default_factory=list)
    exclude_ids: list[int] = field(default_factory=list)
    party_type: PartyType | None = None
    party_size: int | None = None
    budget_per_person: int | None = None
    scope: Scope | None = None
    anchor: Anchor | None = None
    at: datetime | None = None                   # when the user would go (IST)
    require_open: bool = False
    rain_expected: bool | None = None
    indoor_preference: str | None = None
    weather_sensitive: bool = False
    quiet: bool = False
    dietary: list[str] = field(default_factory=list)
    accessibility: list[str] = field(default_factory=list)
    kids: bool = False
    novelty: NoveltyContext = field(default_factory=NoveltyContext)
    preferences: Preferences | None = None
    semantic: dict[int, float] | None = None     # poi_id -> cosine similarity
    similar_to: POIRecord | None = None
    mode: Mode = "discover"
    limit: int = 8
    seed: int | None = None
    recommendable_only: bool = True

    def __post_init__(self) -> None:
        # Theme categories (photography, romantic, family, kids) describe an
        # experience, not a place type, so they act as moods/tags here - no
        # POI has "photography" as its category.
        theme_as = {"photography": "photography", "romantic": "romantic", "family": "family"}
        moods = list(self.moods)
        interests = []
        for i in self.interests:
            if i in theme_as:
                moods.append(theme_as[i])
            else:
                interests.append(i)
        # "kids" is both a theme category and an experience tag.
        self.interests = list(dict.fromkeys(interests))
        self.moods = list(dict.fromkeys(moods))

    @property
    def categories(self) -> list[str]:
        return [i for i in self.interests if is_valid_category(i) and i != "kids"]

    @property
    def tags(self) -> list[str]:
        return [i for i in self.interests if (not is_valid_category(i) or i == "kids")
                and not is_valid_mood(i)]

    @property
    def avoid_categories(self) -> list[str]:
        return [i for i in self.avoid_interests if is_valid_category(i)]

    @property
    def avoid_tags(self) -> list[str]:
        return [i for i in self.avoid_interests if not is_valid_category(i)]


@dataclass
class Scored:
    poi: POIRecord
    score: float
    components: dict[str, float]
    reasons: list[str]

    def to_dict(self) -> dict:
        return {**self.poi.card(), "score": round(self.score, 4),
                "score_components": {k: round(v, 3) for k, v in self.components.items()},
                "reason_codes": self.reasons}


# --- hard filters ---------------------------------------------------------------------

DIET_SATISFIES = {
    "vegetarian": {"vegetarian", "pure_vegetarian", "vegan", "jain"},
    "pure_vegetarian": {"pure_vegetarian", "jain"},
    "vegan": {"vegan"},
    "halal": {"halal"},
    "jain": {"jain"},
}


def hard_filter(poi: POIRecord, req: RecommendationRequest) -> str | None:
    """The reason a POI is excluded, or None when it passes."""
    if poi.id in req.exclude_ids:
        return "excluded_id"
    if poi.category in req.avoid_categories:
        return "avoided_category"
    if set(req.avoid_tags) & set(poi.experience_tags):
        return "avoided_tag"
    if set(req.avoid_tags) & set(poi.mood_tags):
        return "avoided_mood"
    if req.budget_per_person is not None and poi.cost[1] > req.budget_per_person:
        return "over_budget"
    if (req.kids or req.party_type == PartyType.FAMILY_WITH_KIDS) and \
            poi.suitability.get("kids_friendly") is False:
        return "not_kid_friendly"
    if "wheelchair_accessible" in req.accessibility and \
            "wheelchair_accessible" not in poi.accessibility_tags:
        return "accessibility_unverified"
    if req.dietary and poi.category in FOOD_CATEGORIES:
        for need in req.dietary:
            if not DIET_SATISFIES.get(need, {need}) & set(poi.dietary_tags):
                return "dietary_unverified"
    if req.indoor_preference == "indoor" and poi.indoor_outdoor == "outdoor":
        return "outdoor_excluded"
    if req.indoor_preference == "outdoor" and poi.indoor_outdoor == "indoor":
        return "indoor_excluded"
    if req.rain_expected and req.weather_sensitive and poi.indoor_outdoor == "outdoor":
        return "rain_outdoor"
    if req.require_open and req.at is not None and poi.hours_reliable \
            and poi.hours_loaded_for_day is not None:
        minute = req.at.hour * 60 + req.at.minute
        if poi.open_interval_containing(minute, minute + 15) is None:
            return "closed_at_requested_time"
    if req.similar_to is not None and poi.id == req.similar_to.id:
        return "is_reference_poi"
    if req.mode in ("surprise", "different") and poi.id in req.novelty.dismissed:
        return "dismissed"
    if req.mode == "different" and poi.id in req.novelty.previous_ids:
        return "previously_shown"
    if req.mode == "hidden_gems":
        cfg = config()["hidden_gems"]
        offbeat = "offbeat" in poi.experience_tags
        if poi.is_chain or poi.quality < cfg["min_quality"]:
            return "not_hidden_gem"
        if poi.curated and not offbeat:
            return "not_hidden_gem"
        if not offbeat and poi.prominence > cfg["max_prominence"]:
            return "not_hidden_gem"
    if req.mode == "surprise" and poi.quality < config()["surprise"]["min_quality"]:
        return "below_surprise_quality"
    return None


# --- components --------------------------------------------------------------------------

def interest_match(poi: POIRecord, req: RecommendationRequest, cfg: dict) -> float:
    wanted = req.categories + req.tags
    if not wanted:
        return NEUTRAL
    w = cfg["interest_weights"]
    scores = []
    for item in wanted:
        if item == poi.category:
            scores.append(w["category_exact"])
        elif item in poi.secondary:
            scores.append(w["category_secondary"])
        elif item in poi.experience_tags:
            scores.append(w["tag"])
        elif item in poi.mood_tags:
            scores.append(w["mood"])
        else:
            scores.append(0.0)
    return 0.7 * max(scores) + 0.3 * (sum(scores) / len(scores))


def mood_match(poi: POIRecord, req: RecommendationRequest) -> float:
    if not req.moods:
        return NEUTRAL
    scores = []
    tags = set(poi.experience_tags)
    for m in req.moods:
        if m in poi.mood_tags:
            scores.append(1.0)
            continue
        definition = MOOD_DEFINITIONS.get(Mood(m)) if is_valid_mood(m) else None
        if not definition:
            scores.append(0.0)
            continue
        overlap = len(tags & set(definition["tags"])) / max(1, len(definition["tags"]))
        # Category alone is weak evidence for a mood (not every cafe is
        # romantic); it stays below the relevance gate unless a tag agrees.
        cat = 0.25 if poi.category in definition["categories"] else 0.0
        scores.append(min(0.8, 0.6 * overlap + cat))
    return 0.7 * max(scores) + 0.3 * (sum(scores) / len(scores))


PARTY_FLAG = {
    PartyType.COUPLE: "couple_friendly", PartyType.FRIENDS: "group_friendly",
    PartyType.COLLEAGUES: "group_friendly", PartyType.FAMILY: "family_friendly",
    PartyType.FAMILY_WITH_KIDS: "kids_friendly", PartyType.PARENTS: "senior_friendly",
    PartyType.SOLO: "solo_friendly",
}


def party_suitability(poi: POIRecord, req: RecommendationRequest) -> float:
    if req.party_type is None:
        return NEUTRAL
    value = poi.suitability.get(PARTY_FLAG[req.party_type])
    return {True: 1.0, None: NEUTRAL, False: 0.05}[value]


def budget_fit(poi: POIRecord, req: RecommendationRequest) -> float:
    cmin, ctyp, cmax = poi.cost
    if req.budget_per_person is not None:
        cap = req.budget_per_person
        if cmax <= cap:
            return 1.0
        return 0.75 if ctyp <= cap else 0.0
    if "budget" in req.moods or "budget" in req.tags:
        return max(0.0, 1.0 - min(1.0, ctyp / 800.0))
    if "luxury" in req.moods or "premium" in req.tags:
        return 1.0 if "premium" in poi.experience_tags else 0.4
    return NEUTRAL


def weather_fit(poi: POIRecord, req: RecommendationRequest) -> float:
    if req.rain_expected is None:
        if req.indoor_preference == "indoor":
            return {"indoor": 1.0, "mixed": 0.6}.get(poi.indoor_outdoor, 0.2)
        return NEUTRAL
    if req.rain_expected:
        return {"indoor": 1.0, "mixed": 0.6, "outdoor": 0.1}.get(poi.indoor_outdoor, NEUTRAL)
    return {"outdoor": 0.65, "mixed": 0.6}.get(poi.indoor_outdoor, NEUTRAL)


def geographic_relevance(poi: POIRecord, req: RecommendationRequest, cfg: dict) -> float:
    g = cfg["geography"]
    if req.anchor is not None and poi.anchor_km is not None:
        return max(0.0, 1.0 - poi.anchor_km / max(g["local_falloff_km"], req.anchor.radius_km * 1.5))
    if req.scope == "regional":
        lo, hi = g["regional_sweet_spot_km"]
        d = poi.distance_from_center_km
        if lo <= d <= hi:
            return 1.0
        return max(0.2, 1.0 - abs(d - (lo if d < lo else hi)) / 30.0)
    if req.scope in ("city", "local"):
        return max(0.0, 1.0 - poi.distance_from_center_km / g["city_falloff_km"])
    return NEUTRAL


def preference_fit(poi: POIRecord, req: RecommendationRequest, cfg: dict) -> float:
    p = req.preferences
    if p is None:
        return NEUTRAL
    score = NEUTRAL
    cats = poi.all_categories
    if cats & p.favorite_categories:
        score += 0.35
    if set(poi.mood_tags) & p.favorite_moods:
        score += 0.2
    if poi.category in p.disliked_categories:
        score = 0.05
    if p.saved_categories.get(poi.category):
        score += min(cfg["novelty"]["saved_boost"], 0.05 * p.saved_categories[poi.category])
    return max(0.0, min(1.0, score))


def novelty_multiplier(poi: POIRecord, req: RecommendationRequest, cfg: dict) -> float:
    n = cfg["novelty"]
    ctx = req.novelty
    mult = 1.0
    strength = 1.0 if req.mode in ("surprise", "different", "for_you") else 0.35
    if poi.id in ctx.shown_recently:
        mult *= 1 - n["shown_recently_penalty"] * strength
    if poi.id in ctx.dismissed:
        mult *= 1 - n["dismissed_penalty"]
    if poi.id in ctx.visited and req.mode in ("surprise", "different", "for_you", "hidden_gems"):
        mult *= 1 - n["visited_penalty"]
    return mult


def novelty_component(poi: POIRecord, req: RecommendationRequest, cfg: dict) -> float:
    base = novelty_multiplier(poi, req, cfg)
    if req.mode == "different" and req.novelty.previous_categories and \
            poi.category not in req.novelty.previous_categories:
        base = min(1.0, base + cfg["novelty"]["category_novelty_boost"])
    return base


def context_fit(poi: POIRecord, req: RecommendationRequest) -> float:
    if req.at is None:
        return NEUTRAL
    minute = req.at.hour * 60 + req.at.minute
    score = NEUTRAL
    if poi.hours_reliable and poi.hours_loaded_for_day is not None:
        score = 1.0 if poi.open_interval_containing(minute, minute + 30) else 0.1
    tags = set(poi.experience_tags)
    if "sunset" in tags and 16 * 60 + 30 <= minute <= 18 * 60 + 30:
        score = max(score, 0.95)
    if "sunrise" in tags and 5 * 60 + 30 <= minute <= 7 * 60 + 30:
        score = max(score, 0.95)
    if poi.category == "nightlife":
        score = min(score, 0.15) if minute < 17 * 60 else max(score, 0.8)
    return score


def similarity_to(poi: POIRecord, ref: POIRecord, semantic: float | None) -> float:
    """Multi-signal similarity for "show similar" (section 23)."""
    cat = 1.0 if poi.category == ref.category else (
        0.6 if poi.all_categories & ref.all_categories else 0.0)
    tags_a, tags_b = set(poi.experience_tags), set(ref.experience_tags)
    tag_j = len(tags_a & tags_b) / max(1, len(tags_a | tags_b))
    mood_a, mood_b = set(poi.mood_tags), set(ref.mood_tags)
    mood_j = len(mood_a & mood_b) / max(1, len(mood_a | mood_b))
    io = 1.0 if poi.indoor_outdoor == ref.indoor_outdoor else 0.5
    budget = 1.0 - min(1.0, abs(poi.cost[1] - ref.cost[1]) / max(300, ref.cost[1] + 1))
    party = sum(1 for k, v in ref.suitability.items() if v and poi.suitability.get(k)) / max(
        1, sum(1 for v in ref.suitability.values() if v))
    sem = semantic if semantic is not None else NEUTRAL
    return (0.22 * cat + 0.22 * tag_j + 0.16 * mood_j + 0.14 * sem + 0.1 * io
            + 0.08 * budget + 0.08 * party)


def relevance_gate(poi: POIRecord, req: RecommendationRequest, c: dict[str, float],
                   cfg: dict) -> float:
    """Keep well-documented but irrelevant places from outranking what was
    asked for. An explicitly requested CATEGORY ("cafe near Jayanagar") is
    close to a requirement; moods and tags are softer."""
    if req.similar_to is not None:
        return 1.0
    g = cfg["relevance"]
    if req.categories and not (poi.all_categories & set(req.categories)):
        return g["category_miss"]
    wanted_other = bool(req.tags or req.moods)
    if wanted_other:
        rel = max(c["interest_match"] if req.tags else 0.0, c["mood_match"] if req.moods else 0.0)
        if rel < g["min_relevance"]:
            return g["relevance_miss"]
    return 1.0


def score_poi(poi: POIRecord, req: RecommendationRequest) -> Scored:
    cfg = config()
    sem = req.semantic.get(poi.id) if req.semantic else None
    components = {
        "interest_match": interest_match(poi, req, cfg),
        "mood_match": mood_match(poi, req),
        "semantic_similarity": sem if sem is not None else NEUTRAL,
        "quality": poi.quality,
        "prominence": (1.0 - poi.prominence) if req.mode == "hidden_gems" else poi.prominence,
        "party_suitability": party_suitability(poi, req),
        "budget_fit": budget_fit(poi, req),
        "weather_suitability": weather_fit(poi, req),
        "geographic_relevance": geographic_relevance(poi, req, cfg),
        "preference_fit": preference_fit(poi, req, cfg),
        "novelty": novelty_component(poi, req, cfg),
        "context_fit": context_fit(poi, req),
    }
    if req.similar_to is not None:
        components["interest_match"] = similarity_to(poi, req.similar_to, sem)
    w = cfg["weights"]
    total = sum(w[k] * v for k, v in components.items())
    total *= novelty_multiplier(poi, req, cfg)
    total *= relevance_gate(poi, req, components, cfg)
    return Scored(poi=poi, score=total, components=components,
                  reasons=reason_codes(poi, req, components, cfg))


# --- reasons -------------------------------------------------------------------------------

def reason_codes(poi: POIRecord, req: RecommendationRequest, c: dict[str, float],
                 cfg: dict) -> list[str]:
    out: list[str] = []
    tags = set(poi.experience_tags)
    for item in req.categories + req.tags:
        if item == poi.category or item in poi.secondary or item in tags:
            out.append(f"MATCHES_{item.upper()}")
    for m in req.moods:
        if m in poi.mood_tags:
            out.append(f"MATCHES_{m.upper()}")
    if req.similar_to is not None and c["interest_match"] >= 0.45:
        out.append("SIMILAR_TO_REFERENCE")
    flag_reason = {"family_friendly": "GOOD_FOR_FAMILY", "kids_friendly": "GOOD_FOR_KIDS",
                   "couple_friendly": "GOOD_FOR_COUPLES", "group_friendly": "GOOD_FOR_GROUPS",
                   "senior_friendly": "GOOD_FOR_PARENTS", "solo_friendly": "GOOD_FOR_SOLO"}
    if req.party_type is not None:
        flag = PARTY_FLAG[req.party_type]
        if poi.suitability.get(flag):
            out.append(flag_reason[flag])
    if req.budget_per_person is not None and poi.cost[1] <= req.budget_per_person:
        out.append("UNDER_BUDGET")
    if poi.cost[2] == 0:
        out.append("FREE_ENTRY")
    if req.anchor is not None and poi.anchor_km is not None and poi.anchor_km <= req.anchor.radius_km:
        out.append("NEAR_PREFERRED_AREA")
    if req.rain_expected and poi.indoor_outdoor in ("indoor", "mixed"):
        out.append("RAIN_FRIENDLY")
    if req.novelty.previous_ids and poi.id not in req.novelty.shown_recently and req.mode in (
            "different", "surprise", "for_you"):
        out.append("NOVEL_FOR_USER")
    if "photogenic" in tags:
        out.append("GOOD_FOR_PHOTOGRAPHY")
    if poi.visit[1] <= cfg["reasons"]["short_activity_max_min"]:
        out.append("SHORT_ACTIVITY")
    if poi.short_escape or poi.day_trip:
        out.append("WEEKEND_ESCAPE")
    if poi.prominence >= cfg["reasons"]["high_prominence_min"] or (poi.editorial or 0) >= 0.85:
        out.append("HIGH_PROMINENCE")
    if req.quiet and "quiet" in tags:
        out.append("QUIET_MATCH")
    if req.mode == "hidden_gems":
        out.append("HIDDEN_GEM")
    if poi.curated:
        out.append("NAVIGIQ_PICK")
    if req.at is not None and c["context_fit"] >= 0.95 and poi.hours_reliable:
        out.append("OPEN_AT_REQUESTED_TIME")
    if "sunset" in tags and ("sunset" in req.tags or "scenic" in req.moods):
        out.append("SUNSET_SPOT")
    if "sunrise" in tags and "sunrise" in req.tags:
        out.append("SUNRISE_SPOT")
    if "work_friendly" in tags and "work_friendly" in req.tags:
        out.append("WORK_FRIENDLY")
    return list(dict.fromkeys(out))


REASON_TEXT = {
    "UNDER_BUDGET": "Fits your budget", "FREE_ENTRY": "Free to visit",
    "MEAL_STOP": "A meal stop in your time window",
    "GOOD_FOR_FAMILY": "Family friendly", "GOOD_FOR_KIDS": "Good with kids",
    "GOOD_FOR_COUPLES": "Nice for couples", "GOOD_FOR_GROUPS": "Good for groups",
    "GOOD_FOR_PARENTS": "Easy-going for parents", "GOOD_FOR_SOLO": "Good solo",
    "NEAR_PREFERRED_AREA": "Close to the area you asked about",
    "RAIN_FRIENDLY": "Works if it rains", "NOVEL_FOR_USER": "Something new for you",
    "GOOD_FOR_PHOTOGRAPHY": "Photogenic", "SHORT_ACTIVITY": "Quick visit",
    "WEEKEND_ESCAPE": "Makes a good short escape", "HIGH_PROMINENCE": "A well-known landmark",
    "QUIET_MATCH": "Usually quiet", "HIDDEN_GEM": "Lesser-known find",
    "NAVIGIQ_PICK": "NavigIQ pick", "OPEN_AT_REQUESTED_TIME": "Open when you want to go",
    "SUNSET_SPOT": "Good at sunset", "SUNRISE_SPOT": "Good at sunrise",
    "WORK_FRIENDLY": "Laptop friendly", "SIMILAR_TO_REFERENCE": "Similar in feel",
}


def reason_text(code: str) -> str:
    if code in REASON_TEXT:
        return REASON_TEXT[code]
    if code.startswith("MATCHES_"):
        return "Matches " + code.removeprefix("MATCHES_").replace("_", " ").lower()
    return code.replace("_", " ").capitalize()


# --- selection -------------------------------------------------------------------------------

def select_diverse(scored: list[Scored], limit: int, *, mode: Mode = "discover",
                   seed: int | None = None, requested: set[str] | None = None) -> list[Scored]:
    """Greedy diverse selection. Deterministic: ties break on POI id.

    Surprise mode draws from a high-quality pool with a seeded, score-weighted
    choice, so "surprise me" is not always the same answer yet never random
    among weak places.
    """
    cfg = config()["diversity"]
    pool = sorted(scored, key=lambda s: (-s.score, s.poi.id))
    if mode == "surprise":
        sc = config()["surprise"]
        pool = pool[: sc["pool_size"]]
        rng = random.Random(seed if seed is not None else 0)
        weighted: list[Scored] = []
        remaining = list(pool)
        while remaining and len(weighted) < len(pool):
            weights = [max(1e-6, s.score) ** 3 for s in remaining]
            pick = rng.choices(range(len(remaining)), weights=weights, k=1)[0]
            weighted.append(remaining.pop(pick))
        pool = weighted
    chosen: list[Scored] = []
    cat_count: dict[str, int] = {}
    chain_count: dict[str, int] = {}
    candidates = list(pool)
    while candidates and len(chosen) < limit:
        best_idx, best_val = None, -1.0
        for idx, s in enumerate(candidates):
            # A category the user explicitly asked for ("cafes near X") is
            # neither capped nor decayed - they want several of it.
            asked = requested is not None and s.poi.category in requested
            if not asked and cat_count.get(s.poi.category, 0) >= cfg["max_per_category"]:
                continue
            if s.poi.chain_key and chain_count.get(s.poi.chain_key, 0) >= cfg["max_per_chain"]:
                continue
            decay = 1.0 if asked else cfg["same_category_decay"] ** cat_count.get(s.poi.category, 0)
            val = s.score * decay
            if s.poi.chain_key:
                val *= cfg["same_chain_decay"] ** chain_count.get(s.poi.chain_key, 0)
            if mode == "surprise":
                val = 1.0 / (idx + 1)     # keep the seeded order, diversity caps still apply
            if val > best_val:
                best_idx, best_val = idx, val
        if best_idx is None:
            break
        s = candidates.pop(best_idx)
        chosen.append(s)
        cat_count[s.poi.category] = cat_count.get(s.poi.category, 0) + 1
        if s.poi.chain_key:
            chain_count[s.poi.chain_key] = chain_count.get(s.poi.chain_key, 0) + 1
    return chosen


def jaccard(a: set[int], b: set[int]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)
