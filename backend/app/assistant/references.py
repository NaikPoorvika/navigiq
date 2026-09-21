"""Deterministic reference resolution (section 104).

"the second one", "that cafe", "the museum", "the last place", "it",
"remove it", "the first one" - resolved against the last shown results or
the active plan's stops, WITHOUT the LLM. When a phrase matches more than one
candidate (two cafes, "that cafe") the result is AMBIGUOUS and the caller
asks a short clarification instead of guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.nlu.text import normalize_utterance
from app.assistant.state import ConversationState, LastPOI

ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4,
            "4th": 4, "fifth": 5, "5th": 5, "sixth": 6, "6th": 6, "seventh": 7, "eighth": 8,
            "pehla": 1, "doosra": 2, "teesra": 3, "modala": 1, "eradane": 2, "moorane": 3}
CATEGORY_WORDS = {
    "cafe": "cafe", "café": "cafe", "coffee place": "cafe", "coffee shop": "cafe",
    "restaurant": "restaurant", "museum": "museum", "gallery": "gallery", "park": "park",
    "garden": "garden", "lake": "lake", "temple": "temple", "church": "church",
    "mosque": "mosque", "palace": "palace", "fort": "fort", "market": "market", "mall": "mall",
    "viewpoint": "viewpoint", "hill": "hill", "waterfall": "waterfall", "bar": "nightlife",
    "pub": "nightlife", "dessert place": "dessert", "bakery": "dessert", "monument": "monument",
    "street food": "street_food", "food stall": "street_food", "zoo": "nature",
    "coffee bar": "cafe", "shopping street": "walking_area", "street": "walking_area",
    "walk": "walking_area", "neighbourhood": "neighborhood", "neighborhood": "neighborhood",
}
# Words that name a family of categories: "the shopping bit" is whichever
# shopping-type stop the plan has.
CATEGORY_GROUPS = {
    "shopping": {"shopping", "mall", "market", "walking_area"},
    "food": {"restaurant", "cafe", "street_food", "dessert"},
    "restaurant": {"restaurant"},
}


@dataclass
class Reference:
    status: str                    # resolved | ambiguous | none
    poi: LastPOI | None = None
    seq: int | None = None         # position in the list it came from (1-based)
    candidates: list[LastPOI] | None = None
    source: str | None = None      # stops | results | focus


def _pool(state: ConversationState, prefer_plan: bool) -> tuple[list[LastPOI], str]:
    if prefer_plan and state.active_stops:
        return state.active_stops, "stops"
    if state.last_pois:
        return state.last_pois, "results"
    return state.active_stops, "stops"


def resolve_reference(message: str, state: ConversationState, *,
                      prefer_plan: bool = False) -> Reference:
    t = normalize_utterance(message)
    pool, source = _pool(state, prefer_plan)

    m = re.search(r"\b(stop|number|no\.?|#|option)\s*(\d{1,2})\b", t)
    if m:
        n = int(m[2])
        return _by_position(pool, n, source)
    for word, n in ORDINALS.items():
        if re.search(rf"\b(the )?{word}\b( one| stop| place| option| suggestion)?", t):
            return _by_position(pool, n, source)
    if re.search(r"\b(the )?(last|final) (one|stop|place|option)\b|\bthe last\b", t):
        return _by_position(pool, len(pool), source) if pool else Reference("none")

    words = {**CATEGORY_WORDS, **{w: None for w in CATEGORY_GROUPS if w not in CATEGORY_WORDS}}
    for word, category in sorted(words.items(), key=lambda kv: -len(kv[0])):
        # "the museum", "that cafe", and Hindi "museum wala"
        if re.search(rf"\b(the|that|this) {re.escape(word)}\b|\b{re.escape(word)} "
                     rf"(wala|waala|wali|waali|one|bit|stop)\b", t):
            wanted = CATEGORY_GROUPS.get(word, {category})
            matches = [p for p in pool if p.category in wanted]
            if len(matches) == 1:
                return Reference("resolved", matches[0], pool.index(matches[0]) + 1,
                                 source=source)
            if len(matches) > 1:
                return Reference("ambiguous", candidates=matches, source=source)
            return Reference("none")

    for p in pool:
        name = normalize_utterance(p.name)
        if len(name) >= 4 and name in t:
            return Reference("resolved", p, pool.index(p) + 1, source=source)

    if re.search(r"\b(it|that|this|that place|this place|that one|this one|there)\b", t):
        if state.last_focus_poi is not None:
            return Reference("resolved", state.last_focus_poi, source="focus")
        if len(pool) == 1:
            return Reference("resolved", pool[0], 1, source=source)
        if pool:
            return Reference("ambiguous", candidates=pool[:4], source=source)
    return Reference("none")


def _by_position(pool: list[LastPOI], n: int, source: str) -> Reference:
    if 1 <= n <= len(pool):
        return Reference("resolved", pool[n - 1], n, source=source)
    return Reference("none")
