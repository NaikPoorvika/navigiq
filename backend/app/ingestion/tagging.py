"""Stage 6 - TAG: experience tags, moods, suitability, weather, cost and
duration ranges. Pure, deterministic rules over source tags and category.

Every rule here derives from a verifiable input (an OSM tag, a category, a
geographic band). Nothing is guessed from the name, and nothing is scored as
a rating. Where the input is silent, suitability is left NULL (unknown)
rather than defaulted to True.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.taxonomy import (
    FOOD_CATEGORIES, IndoorOutdoor, category_catalog, is_valid_tag, moods_for,
)

FAMILY_CATS = {"park", "garden", "lake", "museum", "science", "palace", "fort", "nature",
               "farm", "entertainment", "monument", "architecture", "heritage", "viewpoint"}
KIDS_CATS = {"science", "park", "farm", "entertainment", "gaming", "museum"}
SENIOR_CATS = {"garden", "park", "museum", "gallery", "temple", "church", "mosque",
               "religious_site", "cafe", "restaurant", "palace", "lake", "heritage",
               "architecture", "science", "monument"}
SENIOR_UNSUITABLE = {"hill", "adventure", "waterfall", "forest", "activity", "nightlife"}
COUPLE_CATS = {"cafe", "dessert", "restaurant", "lake", "viewpoint", "garden", "gallery",
               "museum", "nightlife", "palace", "heritage", "workshop", "experience",
               "walking_area", "hill", "reservoir"}
SOLO_CATS = {"cafe", "museum", "gallery", "park", "garden", "shopping", "temple", "church",
             "mosque", "religious_site", "walking_area", "viewpoint", "heritage",
             "architecture", "science", "lake", "market", "workshop"}
GROUP_CATS = {"gaming", "activity", "adventure", "nightlife", "restaurant", "entertainment",
              "street_food", "hill", "farm", "experience", "market", "mall"}
REGIONAL_ESCAPE_CATS = {"hill", "waterfall", "reservoir", "lake", "forest", "nature", "fort",
                        "farm", "adventure", "viewpoint", "temple", "palace", "heritage",
                        "history", "experience", "religious_site", "entertainment"}
LARGE_BLOCK_CATS = {"hill", "adventure", "farm", "nature"}

CUISINE_TAGS = {
    "coffee_shop": "coffee", "coffee": "coffee", "tea": "tea", "south_indian": "south_indian",
    "north_indian": "north_indian", "indian": "indian", "chinese": "chinese",
    "italian": "italian", "pizza": "pizza", "burger": "burger", "biryani": "biryani",
    "ice_cream": "ice_cream", "cake": "desserts", "dessert": "desserts", "bakery": "bakery",
    "kerala": "kerala", "andhra": "andhra", "chettinad": "chettinad", "udupi": "udupi",
    "vegetarian": "vegetarian", "seafood": "seafood", "continental": "continental",
    "asian": "asian", "japanese": "japanese", "korean": "korean", "thai": "thai",
    "mexican": "mexican", "juice": "juice", "chaat": "chaat", "street_food": "street_food",
    "sandwich": "sandwich", "breakfast": "breakfast", "cafe": "cafe", "mughlai": "mughlai",
    "karnataka": "karnataka", "mangalorean": "mangalorean", "arab": "arabian",
}

_MONEY_RE = re.compile(r"(?:₹|rs\.?|inr)\s*(\d{1,5})|(\d{1,5})\s*(?:₹|rs\.?|inr|rupees)",
                       re.IGNORECASE)


@dataclass
class TagResult:
    experience_tags: list[str] = field(default_factory=list)
    mood_tags: list[str] = field(default_factory=list)
    food_tags: list[str] = field(default_factory=list)
    dietary_tags: list[str] = field(default_factory=list)
    activity_tags: list[str] = field(default_factory=list)
    accessibility_tags: list[str] = field(default_factory=list)
    indoor_outdoor: str = IndoorOutdoor.UNKNOWN.value
    weather_suitability: str = "all_weather"
    suitability: dict[str, bool | None] = field(default_factory=dict)
    visit_duration: tuple[int, int, int] = (30, 60, 120)
    cost: tuple[int, int, int] = (0, 0, 0)
    cost_confidence: str = "category_default"
    regional: dict[str, bool] = field(default_factory=dict)


def parse_charge(value: str | None) -> int | None:
    """A single rupee amount from an OSM charge/fee tag, or None.

    Only an unambiguous single amount is accepted. "₹20 (adults), ₹10
    (children)" yields the first amount, which is the adult fare in every
    Bengaluru example checked; multiple different amounts beyond that are
    refused rather than guessed.
    """
    if not value:
        return None
    amounts = [int(a or b) for a, b in _MONEY_RE.findall(value)]
    if not amounts:
        return None
    if len(set(amounts)) > 2:
        return None
    return amounts[0] if amounts[0] <= 20000 else None


def derive_tags(*, category: str, secondary: list[tuple[str, float]], rule_tags: list[str],
                osm: dict, region_bucket: str, distance_km: float, extent_m: float | None,
                notable: bool, is_chain: bool) -> TagResult:
    cat = category_catalog()[category]
    secondary_keys = {s for s, _ in secondary}
    tags: set[str] = set(cat.default_tags) | {t for t in rule_tags if is_valid_tag(t)}
    for s in secondary_keys:
        info = category_catalog().get(s)
        if info and info.theme:
            tags.update(info.default_tags)
    result = TagResult()

    # --- indoor/outdoor ------------------------------------------------------
    io = cat.indoor_outdoor.value
    if osm.get("indoor") == "yes" or osm.get("covered") == "yes":
        io = "indoor"
    elif category in FOOD_CATEGORIES and osm.get("outdoor_seating") == "yes":
        io = "mixed"
    result.indoor_outdoor = io
    tags.discard("indoor")
    tags.discard("outdoor")
    tags.discard("rain_friendly")
    if io == "indoor":
        tags.update({"indoor", "rain_friendly"})
    elif io == "outdoor":
        tags.add("outdoor")
    else:
        tags.update({"indoor", "outdoor"})
    result.weather_suitability = {"indoor": "rain_friendly", "outdoor": "dry_weather"}.get(
        io, "all_weather")

    # --- OSM-derived experience tags ------------------------------------------
    cuisine = [c.strip().lower() for c in re.split(r"[;,]", osm.get("cuisine", "")) if c.strip()]
    for c in cuisine:
        if c in ("coffee_shop", "coffee"):
            tags.add("coffee")
    if osm.get("internet_access") in ("wlan", "yes", "wifi") and category in FOOD_CATEGORIES:
        tags.add("work_friendly")
    if osm.get("live_music") == "yes":
        tags.add("music")
    if osm.get("historic") or osm.get("heritage"):
        tags.add("historic")
    if osm.get("religion"):
        tags.add("spiritual")
    if category in ("park", "garden") and (extent_m or 0) >= 500:
        tags.update({"nature", "peaceful", "photogenic"})
    if category == "lake":
        tags.add("sunset")
    if osm.get("sport") in ("climbing", "paragliding", "free_flying", "zipline"):
        tags.update({"adventurous", "active", "sports"})
    if osm.get("leisure") in ("golf_course", "horse_riding", "ice_rink", "stadium"):
        tags.add("sports")

    # --- food / dietary / accessibility ------------------------------------
    result.food_tags = sorted({CUISINE_TAGS[c] for c in cuisine if c in CUISINE_TAGS})
    diet = set()
    if osm.get("diet:vegetarian") in ("yes", "only") or "vegetarian" in cuisine:
        diet.add("vegetarian")
    if osm.get("diet:vegetarian") == "only":
        diet.add("pure_vegetarian")
    if osm.get("diet:vegan") in ("yes", "only"):
        diet.add("vegan")
    if osm.get("diet:halal") in ("yes", "only") or osm.get("halal") == "yes":
        diet.add("halal")
    if osm.get("diet:jain") in ("yes", "only"):
        diet.add("jain")
    result.dietary_tags = sorted(diet)
    access = set()
    if osm.get("wheelchair") == "yes":
        access.add("wheelchair_accessible")
    elif osm.get("wheelchair") == "limited":
        access.add("wheelchair_limited")
    elif osm.get("wheelchair") == "no":
        access.add("not_wheelchair_accessible")
    if osm.get("toilets:wheelchair") == "yes":
        access.add("accessible_toilets")
    result.accessibility_tags = sorted(access)
    activity = set()
    if osm.get("sport"):
        activity.update(s.strip() for s in osm["sport"].split(";") if s.strip())
    if category in ("hill",):
        activity.add("trekking")
    if category == "lake" and osm.get("boat") == "yes":
        activity.add("boating")
    result.activity_tags = sorted(a[:40] for a in activity)

    # --- cost ------------------------------------------------------------------
    cmin, ctyp, cmax = cat.cost
    confidence = "category_default"
    charge = parse_charge(osm.get("charge")) or parse_charge(osm.get("fee"))
    if charge is not None:
        cmin = ctyp = cmax = charge
        confidence = "source_tag"
    elif osm.get("fee") == "no" and category not in FOOD_CATEGORIES \
            and category not in ("nightlife", "gaming", "activity", "entertainment"):
        cmin = ctyp = cmax = 0
        confidence = "source_tag"
    elif ctyp == 0 and cmax == 0:
        confidence = "free"
    result.cost = (cmin, ctyp, cmax)
    result.cost_confidence = confidence
    if ctyp <= 200:
        tags.add("budget")
    if ctyp >= 1200:
        tags.add("premium")

    result.visit_duration = cat.duration

    # --- suitability (None = unknown, never guessed True) ----------------------
    s: dict[str, bool | None] = {k: None for k in (
        "family_friendly", "kids_friendly", "senior_friendly", "couple_friendly",
        "solo_friendly", "group_friendly")}
    if category in FAMILY_CATS or {"family", "kids"} & (tags | secondary_keys):
        s["family_friendly"] = True
    if category in KIDS_CATS or "kids" in (tags | secondary_keys):
        s["kids_friendly"] = True
    if category == "nightlife":
        s["family_friendly"] = False
        s["kids_friendly"] = False
    if category in SENIOR_CATS:
        s["senior_friendly"] = True
    if category in SENIOR_UNSUITABLE:
        s["senior_friendly"] = False
    if category in COUPLE_CATS:
        s["couple_friendly"] = True
    if category in SOLO_CATS:
        s["solo_friendly"] = True
    if category in GROUP_CATS:
        s["group_friendly"] = True
    result.suitability = s
    for flag, tag in (("family_friendly", "family"), ("kids_friendly", "kids"),
                      ("group_friendly", "group"), ("solo_friendly", "solo")):
        if s[flag]:
            tags.add(tag)

    # --- region behaviour --------------------------------------------------------
    far = region_bucket in ("OUTSKIRTS", "NEARBY_ESCAPE")
    escape_cat = category in REGIONAL_ESCAPE_CATS
    short_escape = far and escape_cat and (notable or category in (
        "hill", "waterfall", "reservoir", "forest", "nature", "fort", "farm", "adventure"))
    large_block = category in LARGE_BLOCK_CATS or distance_km >= 45.0
    result.regional = {
        "short_escape": short_escape,
        "day_trip_suitable": short_escape and (distance_km >= 40.0 or large_block),
        "requires_large_time_block": bool(large_block and (far or category in LARGE_BLOCK_CATS)),
        "recommended_as_primary_destination": bool(
            short_escape and (distance_km >= 30.0 or category in LARGE_BLOCK_CATS)),
    }
    if short_escape and not is_chain and not notable:
        tags.add("offbeat")
    if category in ("workshop", "farm", "experience"):
        tags.add("offbeat")

    result.experience_tags = sorted(t for t in tags if is_valid_tag(t))
    result.mood_tags = moods_for(set(result.experience_tags), category, secondary_keys)
    return result
