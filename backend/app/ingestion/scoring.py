"""Stage 8 - SCORE: prominence, data confidence and quality (ADR-008, ADR-026).

NONE OF THESE IS A RATING. Prominence measures documentation and notability
(Wikidata, Wikipedia, sitelinks, tag richness, curation). Data confidence
measures how much of the record is verified. Quality combines the two with
category and name signals to decide which places are worth *recommending*
unprompted. No star rating is ever computed, stored or shown.

Every score keeps its component breakdown so any ranking is explainable.
"""
from __future__ import annotations

import math

RICH_KEYS = ("website", "contact:website", "phone", "contact:phone", "opening_hours",
             "cuisine", "wheelchair", "description", "image", "addr:street", "email",
             "contact:instagram", "contact:facebook")
VERIFIABLE_CONTACT = ("website", "contact:website", "phone", "contact:phone")

CATEGORY_BASE = {
    **{c: 1.0 for c in ("palace", "fort", "museum", "science", "gallery", "heritage",
                        "monument", "architecture", "lake", "garden", "waterfall", "hill",
                        "viewpoint", "nature", "reservoir", "market", "walking_area",
                        "neighborhood")},
    **{c: 0.8 for c in ("history", "park", "forest", "entertainment", "farm", "workshop",
                        "experience", "adventure")},
    **{c: 0.7 for c in ("temple", "church", "mosque", "gaming", "activity", "mall")},
    **{c: 0.55 for c in ("cafe", "restaurant", "dessert", "nightlife", "street_food",
                         "shopping")},
    "religious_site": 0.5,
    "other": 0.4,
}

RECOMMENDABLE_THRESHOLD = 0.32
SITELINK_SATURATION = 40


def prominence(tags: dict, *, has_wikidata: bool, has_enwiki: bool, sitelinks: int,
               curated_landmark: bool) -> tuple[float, dict]:
    richness = sum(1 for k in RICH_KEYS if tags.get(k)) / len(RICH_KEYS)
    sl = min(1.0, math.log1p(max(0, sitelinks)) / math.log1p(SITELINK_SATURATION))
    parts = {
        "wikidata_presence": round(0.20 * has_wikidata, 4),
        "wikipedia_presence": round(0.20 * has_enwiki, 4),
        "sitelink_breadth": round(0.30 * sl, 4),
        "tag_richness": round(0.15 * richness, 4),
        "curated_landmark": round(0.15 * curated_landmark, 4),
    }
    return round(min(1.0, sum(parts.values())), 3), parts


def data_confidence(*, has_description: bool, hours_reliable: bool, cost_confidence: str,
                    has_locality: bool, has_wikidata: bool, tags: dict, curated: bool) -> float:
    score = 0.15
    score += 0.20 if has_description else 0
    score += 0.15 if hours_reliable else 0
    score += 0.15 if cost_confidence in ("source_tag", "curated_estimate", "free") else 0
    score += 0.10 if has_locality else 0
    score += 0.10 if has_wikidata else 0
    score += 0.10 if any(tags.get(k) for k in VERIFIABLE_CONTACT) else 0
    score += 0.05 if curated else 0
    return round(min(1.0, score), 2)


def name_quality(name: str, generic: bool) -> float:
    if generic:
        return 0.2
    letters = sum(c.isalpha() for c in name)
    if letters < 3:
        return 0.2
    if len(name) > 70:
        return 0.5
    if name.isupper() and len(name) > 6:
        return 0.7
    return 1.0


def quality(*, prominence_score: float, confidence: float, category: str, name_q: float,
            is_chain: bool, curated: bool, editorial: float | None) -> tuple[float, dict]:
    parts = {
        "prominence": round(0.35 * prominence_score, 4),
        "data_confidence": round(0.25 * confidence, 4),
        "category_base": round(0.15 * CATEGORY_BASE.get(category, 0.4), 4),
        "name_quality": round(0.10 * name_q, 4),
        "independent": round(0.05 * (not is_chain), 4),
        "curated": round(0.10 * curated, 4),
    }
    score = sum(parts.values())
    if editorial is not None:
        parts["editorial_floor"] = editorial
        score = max(score, editorial)
    return round(min(1.0, score), 3), parts


import re as _re

# Places that exist on the map but are not somewhere a visitor can go:
# schools, clubs, offices, hospitals... They stay searchable by name but are
# never suggested unprompted.
NON_VISITABLE = _re.compile(
    r"\b(school|college|club|office|court|hospital|bank|police|quarters|hostel|university|"
    r"institute|headquarters|hq|secretariat|directorate|corporation|depot|godown|warehouse|"
    r"apartment|apartments|residency|layout office|clinic|pvt|ltd|private limited|society)\b",
    _re.IGNORECASE)
# Categories whose OSM tagging (historic=building, heritage=*, tourism=
# attraction) often marks buildings rather than visitor attractions: these
# need independent evidence (Wikidata/Wikipedia, a tourism tag or curation).
NEEDS_EVIDENCE = {"heritage", "history", "architecture", "monument", "other"}


def recommendable(*, quality_score: float, curated: bool, generic: bool, active: bool,
                  category: str | None = None, name: str = "", notable: bool = True) -> bool:
    if not active or generic:
        return False
    if curated:
        return True
    if NON_VISITABLE.search(name or ""):
        return False
    if category in NEEDS_EVIDENCE and not notable:
        return False
    return quality_score >= RECOMMENDABLE_THRESHOLD
