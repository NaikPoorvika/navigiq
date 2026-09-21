"""POI, discovery and collections endpoints. None of them needs the LLM:
Explore, search, details, filters, saved places and collections keep working
when Ollama is down (section 54)."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import api_error, current_user, get_db, optional_user, owner
from app.assistant.tools import RecommendArgs
from app.domain.taxonomy import Category, Mood, PartyType, category_catalog
from app.models.user import User
from app.services import interactions
from app.services.collections import definitions, list_collections
from app.services.planning.store import Owner
from app.services.poi.search import filtered_search, get_poi_detail, resolve_location
from app.services.recommendation.engine import (
    load_novelty, load_preferences, make_anchor, recommend, reference_poi,
)
from app.services.recommendation.scoring import RecommendationRequest, reason_text

router = APIRouter()
collections_router = APIRouter()
ATTRIBUTION = "Place data © OpenStreetMap contributors (ODbL)"


def _items(res) -> list[dict]:
    out = []
    for s in res.items:
        d = s.to_dict()
        d["why"] = [reason_text(r) for r in s.reasons[:3]]
        out.append(d)
    return out


@router.get("/categories")
async def categories() -> dict:
    cat = category_catalog()
    return {"categories": [{"key": c.key, "name": c.name, "group": c.group, "theme": c.theme,
                            "indoor_outdoor": c.indoor_outdoor.value,
                            "typical_visit_minutes": c.duration[1]}
                           for c in cat.values()],
            "moods": [m.value for m in Mood]}


@router.get("")
async def list_pois(
    q: Annotated[str | None, Query(max_length=100)] = None,
    category: Annotated[list[Category] | None, Query()] = None,
    tag: Annotated[list[str] | None, Query(max_length=5)] = None,
    area: Annotated[str | None, Query(max_length=80)] = None,
    radius_km: Annotated[float, Query(gt=0, le=30)] = 3.0,
    scope: Literal["city", "regional", "anywhere"] | None = None,
    max_cost: Annotated[int | None, Query(ge=0, le=50_000)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 24,
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.geo.regions import geo_config
    near = None
    resolved = None
    if area:
        resolved = await resolve_location(db, area)
        if resolved is None:
            raise api_error(status.HTTP_404_NOT_FOUND, "AREA_NOT_FOUND",
                            f"'{area}' was not found on the map")
        near = (resolved.lat, resolved.lon)
    buckets = [b.value for b in geo_config().scope_buckets[scope]] if scope and not near else None
    recs = await filtered_search(db, query=q, categories=[c.value for c in category or []] or None,
                                 tags=tag, buckets=buckets, max_cost_pp=max_cost, near=near,
                                 radius_km=radius_km, limit=limit)
    return {"count": len(recs), "items": [r.card() for r in recs],
            "area": resolved.to_dict() if resolved else None, "attribution": ATTRIBUTION}


class SearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str | None = Field(default=None, max_length=100)
    categories: list[Category] = Field(default_factory=list, max_length=5)
    tags: list[str] = Field(default_factory=list, max_length=5)
    area: str | None = Field(default=None, max_length=80)
    radius_km: float = Field(default=3.0, gt=0, le=30)
    max_cost_per_person: int | None = Field(default=None, ge=0, le=50_000)
    limit: int = Field(default=20, ge=1, le=50)


@router.post("/search")
async def search(body: SearchBody, db: AsyncSession = Depends(get_db)) -> dict:
    return await list_pois(q=body.query, category=body.categories or None, tag=body.tags or None,
                           area=body.area, radius_km=body.radius_km, scope=None,
                           max_cost=body.max_cost_per_person, limit=body.limit, db=db)


async def _run_recommend(db, who: Owner, body: RecommendArgs, *, mode: str, seed=None,
                         user_id=None) -> dict:
    from app.domain.taxonomy import is_valid_category, is_valid_mood
    anchor = None
    if body.area:
        r = await resolve_location(db, body.area)
        if r is None:
            raise api_error(status.HTTP_404_NOT_FOUND, "AREA_NOT_FOUND",
                            f"'{body.area}' was not found on the map")
        anchor = make_anchor(r.name, r.lat, r.lon, min(r.radius_km, 3.0))
    req = RecommendationRequest(
        interests=[i for i in body.interests if not (is_valid_mood(i) and not is_valid_category(i))],
        moods=[m.value for m in body.moods] + [i for i in body.interests
                                               if is_valid_mood(i) and not is_valid_category(i)],
        avoid_interests=list(body.avoid), anchor=anchor, scope=body.scope,
        budget_per_person=body.budget_per_person, party_type=body.party_type, mode=mode,
        limit=body.limit, seed=seed, rain_expected=body.rain_expected,
        indoor_preference=body.indoor_preference, quiet=body.quiet, kids=body.kids,
        dietary=list(body.dietary), exclude_ids=list(body.exclude_ids))
    req.novelty = await load_novelty(db, user_id=who.user_id, session_id=who.session_id)
    if mode == "for_you":
        req.preferences = await load_preferences(db, user_id)
    res = await recommend(db, req)
    items = _items(res)
    await interactions.record_shown(db, who, [i["id"] for i in items], f"api_{mode}")
    return {"items": items, "meta": res.to_dict()["meta"], "attribution": ATTRIBUTION}


@router.post("/recommend")
async def recommend_endpoint(body: RecommendArgs, db: AsyncSession = Depends(get_db),
                             who: Owner = Depends(owner)) -> dict:
    return await _run_recommend(db, who, body, mode=body.mode, user_id=who.user_id)


@router.post("/surprise")
async def surprise(body: RecommendArgs | None = None, db: AsyncSession = Depends(get_db),
                   who: Owner = Depends(owner)) -> dict:
    import hashlib
    import time
    body = body or RecommendArgs()
    seed = int(hashlib.sha256(f"{who.user_id or who.session_id}:{time.time_ns()}".encode())
               .hexdigest()[:8], 16)
    return await _run_recommend(db, who, body.model_copy(update={"limit": min(body.limit, 5)}),
                                mode="surprise", seed=seed)


@collections_router.get("")
async def collections(ids: Annotated[list[str] | None, Query(max_length=30)] = None,
                      limit: Annotated[int, Query(ge=1, le=20)] = 8,
                      db: AsyncSession = Depends(get_db), who: Owner = Depends(owner)) -> dict:
    cols = await list_collections(db, who, limit=limit, ids=ids)
    return {"collections": cols,
            "available": [{"id": c["id"], "title": c["title"], "subtitle": c.get("subtitle")}
                          for c in definitions()], "attribution": ATTRIBUTION}


@router.get("/resolve-area")
async def resolve_area(name: Annotated[str, Query(min_length=2, max_length=80)],
                       db: AsyncSession = Depends(get_db)) -> dict:
    r = await resolve_location(db, name)
    return {"resolved": r is not None, "area": r.to_dict() if r else None}


@router.get("/{poi_id}")
async def detail(poi_id: int, db: AsyncSession = Depends(get_db),
                 user: User | None = Depends(optional_user), who: Owner = Depends(owner)) -> dict:
    if poi_id <= 0 or poi_id > 2_147_483_647:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "place not found")
    d = await get_poi_detail(db, poi_id)
    if d is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "place not found")
    d["saved"] = poi_id in await interactions.saved_ids(db, who)
    await interactions.record(db, who, poi_id, "view")
    return d


@router.get("/{poi_id}/hours")
async def hours(poi_id: int, on: date | None = None, db: AsyncSession = Depends(get_db)) -> dict:
    from app.assistant.tools import PoiHoursArgs, ToolContext, h_hours
    from app.assistant.trace import Trace
    try:
        return await h_hours(ToolContext(db=db, owner=Owner(None, None), role=None, trace=Trace()),
                             PoiHoursArgs(poi_id=poi_id, on=on))
    except LookupError:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "place not found")


@router.get("/{poi_id}/similar")
async def similar(poi_id: int, limit: Annotated[int, Query(ge=1, le=20)] = 8,
                  db: AsyncSession = Depends(get_db), who: Owner = Depends(owner)) -> dict:
    ref = await reference_poi(db, poi_id)
    if ref is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "place not found")
    req = RecommendationRequest(similar_to=ref, mode="similar", limit=limit, exclude_ids=[poi_id])
    req.novelty = await load_novelty(db, user_id=who.user_id, session_id=who.session_id)
    res = await recommend(db, req)
    await interactions.record(db, who, poi_id, "show_similar")
    return {"reference": ref.card(), "items": _items(res), "meta": res.to_dict()["meta"]}


@router.post("/{poi_id}/save")
async def save(poi_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await interactions.save_poi(db, Owner(user.id, None), poi_id)
    except LookupError:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "place not found")


@router.delete("/{poi_id}/save")
async def unsave(poi_id: int, user: User = Depends(current_user),
                 db: AsyncSession = Depends(get_db)) -> dict:
    return await interactions.unsave_poi(db, Owner(user.id, None), poi_id)


@router.post("/{poi_id}/dismiss")
async def dismiss(poi_id: int, db: AsyncSession = Depends(get_db), who: Owner = Depends(owner)) -> dict:
    if who.user_id is None and not who.session_id:
        raise api_error(status.HTTP_400_BAD_REQUEST, "SESSION_REQUIRED",
                        "send X-NavigIQ-Session or sign in")
    try:
        return await interactions.dismiss_poi(db, who, poi_id)
    except LookupError:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "place not found")


class InteractionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["view", "click", "add_to_plan", "remove_from_plan", "show_similar",
                    "tell_me_more", "mark_visited"]


@router.post("/{poi_id}/interactions", status_code=status.HTTP_204_NO_CONTENT)
async def interaction(poi_id: int, body: InteractionBody, db: AsyncSession = Depends(get_db),
                      who: Owner = Depends(owner)) -> None:
    if not await interactions.poi_exists(db, poi_id):
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "place not found")
    await interactions.record(db, who, poi_id, body.action)


async def stats(db: AsyncSession) -> dict:
    row = (await db.execute(text("SELECT count(*) FILTER (WHERE active), count(*) FILTER "
                                 "(WHERE active AND recommendable) FROM pois"))).one()
    return {"active": row[0], "recommendable": row[1]}

