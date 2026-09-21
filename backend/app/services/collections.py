"""Data-driven discovery collections (section 24).

Each collection is a recommendation query from data/config/collections.yaml.
Anonymous results are cached in-process for 10 minutes (they do not depend
on the viewer); "For you" is computed per signed-in user and never cached
across users.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from functools import lru_cache

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.paths import config_path
from app.domain.taxonomy import PartyType, is_valid_category, is_valid_mood, is_valid_tag
from app.services.planning.store import Owner
from app.services.recommendation.engine import load_novelty, load_preferences, recommend
from app.services.recommendation.scoring import RecommendationRequest, reason_text

CACHE_TTL_S = 600
_cache: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()


@lru_cache(maxsize=1)
def definitions() -> list[dict]:
    raw = yaml.safe_load(config_path("collections.yaml").read_text(encoding="utf-8"))
    out = []
    seen = set()
    for c in raw["collections"]:
        if c["id"] in seen:
            raise ValueError(f"duplicate collection {c['id']}")
        seen.add(c["id"])
        for i in c.get("interests", []):
            if not (is_valid_category(i) or is_valid_tag(i)):
                raise ValueError(f"collection {c['id']}: unknown interest {i}")
        for m in c.get("moods", []):
            if not is_valid_mood(m):
                raise ValueError(f"collection {c['id']}: unknown mood {m}")
        out.append(c)
    return out


def _request(c: dict, limit: int) -> RecommendationRequest:
    return RecommendationRequest(
        interests=list(c.get("interests", [])) + list(c.get("tags", [])),
        moods=list(c.get("moods", [])), avoid_interests=list(c.get("avoid", [])),
        scope=c.get("scope"), budget_per_person=c.get("budget_per_person"),
        party_type=PartyType(c["party_type"]) if c.get("party_type") else None,
        indoor_preference=c.get("indoor_preference"),
        mode=c.get("mode", "discover"), limit=limit)


async def collection_items(db: AsyncSession, c: dict, owner: Owner, limit: int = 10) -> dict:
    personal = c.get("mode") == "for_you"
    key = (c["id"], limit)
    if not personal:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
            return hit[1]
    req = _request(c, limit)
    if personal:
        req.preferences = await load_preferences(db, owner.user_id)
        req.novelty = await load_novelty(db, user_id=owner.user_id, session_id=owner.session_id)
    res = await recommend(db, req)
    items = []
    for s in res.items:
        d = s.to_dict()
        d["why"] = [reason_text(r) for r in s.reasons[:2]]
        items.append(d)
    out = {"id": c["id"], "title": c["title"], "subtitle": c.get("subtitle"), "items": items,
           "ranking_config_version": res.config_version}
    if not personal:
        _cache[key] = (time.monotonic(), out)
        while len(_cache) > 64:
            _cache.popitem(last=False)
    return out


async def list_collections(db: AsyncSession, owner: Owner, *, limit: int = 8,
                           ids: list[str] | None = None) -> list[dict]:
    out = []
    for c in definitions():
        if ids and c["id"] not in ids:
            continue
        if c.get("requires_user") and owner.user_id is None:
            continue
        col = await collection_items(db, c, owner, limit)
        if col["items"]:
            out.append(col)
    return out


def clear_cache() -> None:
    _cache.clear()
