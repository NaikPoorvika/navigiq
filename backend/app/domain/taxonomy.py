"""ADR-024 - Controlled vocabularies: categories, experience tags, moods.

Every enum here is CLOSED. The LLM may only choose among these values (its
output is validated against them) and can never add one; unmapped phrases go
to free-text interests and are resolved by the deterministic lexicon.

Category metadata (durations, per-person cost bands, indoor/outdoor) lives in
data/config/categories.yaml so it can be reviewed without reading code. The
enum and the YAML are checked against each other at load time.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

import yaml

from app.core.paths import config_path


class Category(str, Enum):
    PARK = "park"
    GARDEN = "garden"
    LAKE = "lake"
    NATURE = "nature"
    HILL = "hill"
    VIEWPOINT = "viewpoint"
    FOREST = "forest"
    WATERFALL = "waterfall"
    RESERVOIR = "reservoir"
    MUSEUM = "museum"
    GALLERY = "gallery"
    SCIENCE = "science"
    HISTORY = "history"
    HERITAGE = "heritage"
    PALACE = "palace"
    FORT = "fort"
    MONUMENT = "monument"
    ARCHITECTURE = "architecture"
    TEMPLE = "temple"
    CHURCH = "church"
    MOSQUE = "mosque"
    RELIGIOUS_SITE = "religious_site"
    CAFE = "cafe"
    RESTAURANT = "restaurant"
    STREET_FOOD = "street_food"
    DESSERT = "dessert"
    SHOPPING = "shopping"
    MARKET = "market"
    MALL = "mall"
    ENTERTAINMENT = "entertainment"
    GAMING = "gaming"
    ACTIVITY = "activity"
    ADVENTURE = "adventure"
    NIGHTLIFE = "nightlife"
    FARM = "farm"
    EXPERIENCE = "experience"
    WORKSHOP = "workshop"
    PHOTOGRAPHY = "photography"
    ROMANTIC = "romantic"
    FAMILY = "family"
    KIDS = "kids"
    NEIGHBORHOOD = "neighborhood"
    WALKING_AREA = "walking_area"
    OTHER = "other"


class ExperienceTag(str, Enum):
    PEACEFUL = "peaceful"
    ROMANTIC = "romantic"
    PHOTOGENIC = "photogenic"
    EDUCATIONAL = "educational"
    ADVENTUROUS = "adventurous"
    SPIRITUAL = "spiritual"
    HISTORIC = "historic"
    CULTURAL = "cultural"
    SCENIC = "scenic"
    SOCIAL = "social"
    QUIET = "quiet"
    PREMIUM = "premium"
    BUDGET = "budget"
    FAMILY = "family"
    KIDS = "kids"
    GROUP = "group"
    SOLO = "solo"
    SUNRISE = "sunrise"
    SUNSET = "sunset"
    NATURE = "nature"
    FOOD = "food"
    COFFEE = "coffee"
    SHOPPING = "shopping"
    ART = "art"
    MUSIC = "music"
    GAMING = "gaming"
    SPORTS = "sports"
    OUTDOOR = "outdoor"
    INDOOR = "indoor"
    RAIN_FRIENDLY = "rain_friendly"
    RELAXING = "relaxing"
    ACTIVE = "active"
    OFFBEAT = "offbeat"
    WORK_FRIENDLY = "work_friendly"


class Mood(str, Enum):
    PEACEFUL = "peaceful"
    ROMANTIC = "romantic"
    ADVENTUROUS = "adventurous"
    SOCIAL = "social"
    CREATIVE = "creative"
    CULTURAL = "cultural"
    SPIRITUAL = "spiritual"
    ACTIVE = "active"
    RELAXING = "relaxing"
    FOODIE = "foodie"
    NATURE = "nature"
    PHOTOGRAPHY = "photography"
    NIGHTLIFE = "nightlife"
    LEARNING = "learning"
    FAMILY = "family"
    LUXURY = "luxury"
    BUDGET = "budget"
    OFFBEAT = "offbeat"
    SCENIC = "scenic"
    QUIET = "quiet"


class IndoorOutdoor(str, Enum):
    INDOOR = "indoor"
    OUTDOOR = "outdoor"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class PartyType(str, Enum):
    SOLO = "solo"
    COUPLE = "couple"
    FRIENDS = "friends"
    FAMILY = "family"
    FAMILY_WITH_KIDS = "family_with_kids"
    PARENTS = "parents"
    COLLEAGUES = "colleagues"


# What a mood means in terms of the controlled vocabulary. Used twice: to
# derive a POI's mood_tags at ingestion, and to score POIs for a mood at
# query time - so both sides of the match use one definition.
MOOD_DEFINITIONS: dict[Mood, dict[str, list[str]]] = {
    Mood.PEACEFUL: {"tags": ["peaceful", "quiet", "scenic", "nature"],
                    "categories": ["garden", "lake", "park", "forest", "reservoir", "church"]},
    Mood.ROMANTIC: {"tags": ["romantic", "scenic", "sunset", "peaceful", "premium"],
                    "categories": ["cafe", "lake", "viewpoint", "garden", "restaurant", "dessert"]},
    Mood.ADVENTUROUS: {"tags": ["adventurous", "active"],
                       "categories": ["hill", "adventure", "activity", "waterfall", "forest"]},
    Mood.SOCIAL: {"tags": ["social", "group"],
                  "categories": ["cafe", "restaurant", "gaming", "nightlife", "market",
                                 "entertainment", "street_food", "walking_area"]},
    Mood.CREATIVE: {"tags": ["art"],
                    "categories": ["gallery", "workshop", "museum", "experience"]},
    Mood.CULTURAL: {"tags": ["cultural", "historic"],
                    "categories": ["museum", "heritage", "palace", "fort", "market", "temple",
                                   "monument", "architecture", "neighborhood"]},
    Mood.SPIRITUAL: {"tags": ["spiritual"],
                     "categories": ["temple", "church", "mosque", "religious_site"]},
    Mood.ACTIVE: {"tags": ["active", "sports", "adventurous"],
                  "categories": ["activity", "hill", "adventure", "park", "gaming"]},
    Mood.RELAXING: {"tags": ["relaxing", "peaceful", "quiet"],
                    "categories": ["cafe", "garden", "lake", "park"]},
    Mood.FOODIE: {"tags": ["food", "coffee"],
                  "categories": ["restaurant", "street_food", "cafe", "dessert", "market"]},
    Mood.NATURE: {"tags": ["nature", "scenic", "outdoor"],
                  "categories": ["park", "garden", "lake", "forest", "hill", "waterfall",
                                 "reservoir", "nature", "viewpoint"]},
    Mood.PHOTOGRAPHY: {"tags": ["photogenic", "scenic", "sunset", "sunrise"],
                       "categories": ["viewpoint", "heritage", "palace", "lake", "market",
                                      "architecture", "fort", "waterfall", "hill"]},
    Mood.NIGHTLIFE: {"tags": ["music", "social"], "categories": ["nightlife"]},
    Mood.LEARNING: {"tags": ["educational"],
                    "categories": ["museum", "science", "gallery", "heritage", "history"]},
    Mood.FAMILY: {"tags": ["family", "kids"],
                  "categories": ["park", "science", "museum", "entertainment", "farm", "nature"]},
    Mood.LUXURY: {"tags": ["premium"], "categories": []},
    Mood.BUDGET: {"tags": ["budget"], "categories": ["street_food", "park", "market", "temple"]},
    Mood.OFFBEAT: {"tags": ["offbeat", "quiet"], "categories": []},
    Mood.SCENIC: {"tags": ["scenic", "photogenic", "sunset"],
                  "categories": ["viewpoint", "lake", "hill", "waterfall", "reservoir"]},
    Mood.QUIET: {"tags": ["quiet", "peaceful"],
                 "categories": ["garden", "gallery", "church", "forest", "lake"]},
}

MEAL_CATEGORIES = frozenset({"cafe", "restaurant", "street_food"})
FOOD_CATEGORIES = frozenset({"cafe", "restaurant", "street_food", "dessert"})
REGIONAL_CATEGORIES = frozenset({"hill", "waterfall", "reservoir", "forest", "nature",
                                 "fort", "farm", "adventure"})


@dataclass(frozen=True)
class CategoryInfo:
    key: str
    name: str
    group: str
    indoor_outdoor: IndoorOutdoor
    duration: tuple[int, int, int]      # min, typical, max minutes
    cost: tuple[int, int, int]          # min, typical, max INR per person
    default_tags: tuple[str, ...]
    meal: bool
    theme: bool


@lru_cache(maxsize=1)
def category_catalog() -> dict[str, CategoryInfo]:
    raw = yaml.safe_load(config_path("categories.yaml").read_text(encoding="utf-8"))
    out: dict[str, CategoryInfo] = {}
    tag_values = {t.value for t in ExperienceTag}
    for key, c in raw["categories"].items():
        dmin, dtyp, dmax = c["dur"]
        cmin, ctyp, cmax = c["cost"]
        if not (0 < dmin <= dtyp <= dmax):
            raise ValueError(f"category {key}: durations must satisfy 0<min<=typ<=max")
        if not (0 <= cmin <= ctyp <= cmax):
            raise ValueError(f"category {key}: costs must satisfy 0<=min<=typ<=max")
        unknown = set(c.get("default_tags", [])) - tag_values
        if unknown:
            raise ValueError(f"category {key}: unknown default tags {sorted(unknown)}")
        out[key] = CategoryInfo(
            key=key, name=c["name"], group=c["group"],
            indoor_outdoor=IndoorOutdoor(c["io"]),
            duration=(dmin, dtyp, dmax), cost=(cmin, ctyp, cmax),
            default_tags=tuple(c.get("default_tags", [])),
            meal=bool(c.get("meal", False)), theme=bool(c.get("theme", False)),
        )
    enum_keys = {c.value for c in Category}
    if set(out) != enum_keys:
        raise ValueError(
            f"categories.yaml and Category enum differ: yaml-only "
            f"{sorted(set(out) - enum_keys)}, enum-only {sorted(enum_keys - set(out))}")
    return out


def is_valid_category(value: str) -> bool:
    return value in Category._value2member_map_


def is_valid_tag(value: str) -> bool:
    return value in ExperienceTag._value2member_map_


def is_valid_mood(value: str) -> bool:
    return value in Mood._value2member_map_


def moods_for(tags: set[str], category: str, secondary: set[str] | None = None) -> list[str]:
    """Deterministic mood derivation for a POI.

    A mood applies when the POI carries the tag of the same name, when its
    category is one of the mood's categories AND it carries at least one of
    the mood's tags, or when it carries three or more of the mood's tags.
    Category alone is not enough - a bare "park" does not become peaceful
    by type.
    """
    secondary = secondary or set()
    out = []
    for mood, definition in MOOD_DEFINITIONS.items():
        mood_tags = set(definition["tags"])
        hits = len(tags & mood_tags)
        in_cat = category in definition["categories"] or bool(
            secondary & set(definition["categories"]))
        if (mood.value in tags
                or (in_cat and hits >= 1)
                or hits >= 3
                or (not definition["categories"] and hits >= 1)):
            out.append(mood.value)
    return sorted(out)
