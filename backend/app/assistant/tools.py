"""Typed tool registry (section 57).

Every capability the agent (or the LLM's bounded tool loop) can use is a
registered tool with:
  * a Pydantic argument model: extra fields forbidden, every string length-
    bounded, every list size-bounded, every number range-bounded
  * the roles allowed to call it (anonymous visitor, signed-in user)
  * whether the LLM may select it (read-only tools only - nothing that saves,
    dismisses, plans or modifies can be chosen by a model)

No tool accepts SQL, shell commands, filesystem paths or URLs; the
architecture test enforces this over every registered model. Authorisation,
validation, size limits and the agent's hard limits all run in Python BEFORE
a handler is invoked; a model's text cannot bypass them.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.trace import LimitExceeded, Trace
from app.domain.taxonomy import Category, Mood, PartyType, is_valid_category
from app.services.planning.store import Owner

MAX_ARGS_BYTES = 4096

Str80 = Annotated[str, Field(min_length=1, max_length=80)]
Str200 = Annotated[str, Field(min_length=1, max_length=200)]
Str500 = Annotated[str, Field(min_length=1, max_length=500)]
Interest = Annotated[str, Field(min_length=2, max_length=40)]
PoiId = Annotated[int, Field(gt=0, lt=2_147_483_647)]
Limit = Annotated[int, Field(ge=1, le=20)]


class Role(str, Enum):
    ANONYMOUS = "anonymous"
    USER = "user"


ANY_ROLE = frozenset({Role.ANONYMOUS, Role.USER})
USER_ONLY = frozenset({Role.USER})


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ToolContext:
    db: AsyncSession
    owner: Owner
    role: Role
    trace: Trace
    llm: Any = None
    gateway: Any = None
    now: datetime | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class ToolResult:
    tool: str
    ok: bool
    data: Any = None
    error_code: str | None = None
    message: str | None = None


Handler = Callable[[ToolContext, BaseModel], Awaitable[Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: type[BaseModel]
    roles: frozenset
    handler: Handler
    llm_selectable: bool = False


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool {spec.name}")
        self._tools[spec.name] = spec

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def llm_catalog(self, role: Role) -> list[dict]:
        return [{"name": t.name, "description": t.description,
                 "args": t.args.model_json_schema()}
                for t in self._tools.values() if t.llm_selectable and role in t.roles]

    async def call(self, name: str, raw_args: Any, ctx: ToolContext, *,
                   from_llm: bool = False) -> ToolResult:
        spec = self._tools.get(name) if isinstance(name, str) else None
        if spec is None:
            return self._blocked(ctx, str(name)[:60], "UNKNOWN_TOOL", "no such tool")
        if ctx.role not in spec.roles:
            return self._blocked(ctx, name, "UNAUTHORIZED", "not allowed for this user")
        if from_llm and not spec.llm_selectable:
            return self._blocked(ctx, name, "UNAUTHORIZED", "tool not available to the model")
        if raw_args is None:
            raw_args = {}
        if not isinstance(raw_args, dict):
            return self._blocked(ctx, name, "INVALID_ARGS", "arguments must be an object")
        try:
            size = len(json.dumps(raw_args, default=str))
        except (TypeError, ValueError):
            return self._blocked(ctx, name, "INVALID_ARGS", "arguments are not serialisable")
        if size > MAX_ARGS_BYTES:
            return self._blocked(ctx, name, "ARGS_TOO_LARGE", "arguments too large")
        try:
            args = spec.args.model_validate(raw_args)
        except ValidationError as exc:
            return self._blocked(ctx, name, "INVALID_ARGS",
                                 "; ".join(e["msg"] for e in exc.errors()[:3]))
        canonical = args.model_dump(mode="json")
        h = ctx.trace.before_tool(name, canonical)     # raises LimitExceeded
        t0 = time.perf_counter()
        try:
            data = await spec.handler(ctx, args)
            ctx.trace.after_tool(name, h, "ok", None, int((time.perf_counter() - t0) * 1000))
            return ToolResult(name, True, data)
        except ToolError as exc:
            ctx.trace.after_tool(name, h, "error", exc.code, int((time.perf_counter() - t0) * 1000))
            return ToolResult(name, False, None, exc.code, exc.message)
        except PermissionError as exc:
            ctx.trace.after_tool(name, h, "error", "UNAUTHORIZED", 0)
            return ToolResult(name, False, None, "UNAUTHORIZED", str(exc))
        except LookupError as exc:
            ctx.trace.after_tool(name, h, "error", "NOT_FOUND", 0)
            return ToolResult(name, False, None, "NOT_FOUND", str(exc))
        except LimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - never leak internals to the model or user
            from app.db.session import is_unavailable
            await _rollback(ctx.db)
            code = "DATABASE_UNAVAILABLE" if is_unavailable(exc) else "TOOL_FAILED"
            ctx.trace.after_tool(name, h, "error", code, int((time.perf_counter() - t0) * 1000))
            return ToolResult(name, False, None, code, f"{name} failed ({type(exc).__name__})")

    def _blocked(self, ctx: ToolContext, name: str, code: str, message: str) -> ToolResult:
        ctx.trace.after_tool(name, "-", "blocked", code, 0)
        return ToolResult(name, False, None, code, message)


async def _rollback(db) -> None:
    try:
        await db.rollback()
    except Exception:  # noqa: BLE001
        pass


# ======================================================================================
# Argument models
# ======================================================================================

Scope = Literal["local", "city", "regional", "anywhere"]
CategoryEnum = Category
MoodEnum = Mood


class SearchPOIsArgs(Args):
    query: Str80 | None = None
    categories: Annotated[list[CategoryEnum], Field(max_length=5)] = []
    tags: Annotated[list[Interest], Field(max_length=5)] = []
    area: Str80 | None = None
    radius_km: Annotated[float, Field(gt=0, le=30)] = 3.0
    scope: Scope | None = None
    max_cost_per_person: Annotated[int, Field(ge=0, le=50_000)] | None = None
    limit: Limit = 8


class RecommendArgs(Args):
    interests: Annotated[list[Interest], Field(max_length=12)] = []
    moods: Annotated[list[MoodEnum], Field(max_length=8)] = []
    avoid: Annotated[list[Interest], Field(max_length=12)] = []
    area: Str80 | None = None
    scope: Scope | None = None
    budget_per_person: Annotated[int, Field(ge=0, le=50_000)] | None = None
    party_type: PartyType | None = None
    mode: Literal["discover", "hidden_gems", "for_you", "surprise", "different"] = "discover"
    when: Literal["now", "today", "tonight", "tomorrow", "weekend"] | None = None
    rain_expected: bool | None = None
    indoor_preference: Literal["indoor", "outdoor", "any"] | None = None
    quiet: bool = False
    kids: bool = False
    dietary: Annotated[list[Literal["vegetarian", "pure_vegetarian", "vegan", "halal", "jain"]],
                       Field(max_length=5)] = []
    exclude_ids: Annotated[list[PoiId], Field(max_length=100)] = []
    limit: Limit = 8


class PoiArgs(Args):
    poi_id: PoiId


class PoiHoursArgs(Args):
    poi_id: PoiId
    on: date | None = None


class PoiCostArgs(Args):
    poi_id: PoiId
    party_size: Annotated[int, Field(ge=1, le=20)] = 1


class SimilarArgs(Args):
    poi_id: PoiId
    limit: Limit = 6


class SurpriseArgs(Args):
    mood: MoodEnum | None = None
    budget_per_person: Annotated[int, Field(ge=0, le=50_000)] | None = None
    area: Str80 | None = None
    limit: Annotated[int, Field(ge=1, le=5)] = 3


class CategorySearchArgs(Args):
    category: CategoryEnum
    area: Str80 | None = None
    limit: Limit = 8


class AreaSearchArgs(Args):
    area: Str80
    limit: Limit = 8


class MoodSearchArgs(Args):
    mood: MoodEnum
    area: Str80 | None = None
    limit: Limit = 8


class InterestSearchArgs(Args):
    interest: Interest
    area: Str80 | None = None
    limit: Limit = 8


class NameArgs(Args):
    name: Str80


class WeatherArgs(Args):
    on: date | None = None
    area: Str80 | None = None


class QuestionArgs(Args):
    question: Str500
    k: Annotated[int, Field(ge=1, le=8)] = 6


class TextArgs(Args):
    text: Annotated[str, Field(min_length=1, max_length=1500)]


class SpecArgs(Args):
    spec: dict


class RankArgs(Args):
    poi_ids: Annotated[list[PoiId], Field(min_length=1, max_length=40)]
    interests: Annotated[list[Interest], Field(max_length=12)] = []
    moods: Annotated[list[MoodEnum], Field(max_length=8)] = []


class BuildArgs(Args):
    spec: dict
    persist: bool = True


class ItineraryArgs(Args):
    itinerary_id: PoiId
    version_no: Annotated[int, Field(ge=1, le=500)] | None = None


class ModifyArgs(Args):
    itinerary_id: PoiId
    operations: Annotated[list[dict], Field(min_length=1, max_length=3)]
    expected_version_no: Annotated[int, Field(ge=1, le=500)] | None = None


class CompareVersionsArgs(Args):
    itinerary_id: PoiId
    a: Annotated[int, Field(ge=1, le=500)]
    b: Annotated[int, Field(ge=1, le=500)]


class InteractionArgs(Args):
    poi_id: PoiId
    action: Literal["view", "click", "add_to_plan", "remove_from_plan", "show_similar",
                    "tell_me_more", "mark_visited"]


class NoArgs(Args):
    pass


class PreferencesArgs(Args):
    favorite_categories: Annotated[list[CategoryEnum], Field(max_length=20)] | None = None
    disliked_categories: Annotated[list[CategoryEnum], Field(max_length=20)] | None = None
    favorite_moods: Annotated[list[MoodEnum], Field(max_length=20)] | None = None
    preferred_pace: Literal["quick", "balanced", "relaxed"] | None = None
    typical_budget_inr: Annotated[int, Field(ge=0, le=200_000)] | None = None
    indoor_outdoor_preference: Literal["indoor", "outdoor", "any"] | None = None
    dietary_preferences: Annotated[list[Literal["vegetarian", "pure_vegetarian", "vegan",
                                                "halal", "jain"]], Field(max_length=5)] | None = None
    favorite_areas: Annotated[list[Str80], Field(max_length=10)] | None = None


# ======================================================================================
# Handlers
# ======================================================================================

async def _anchor(ctx: ToolContext, area: str | None):
    if not area:
        return None
    from app.services.poi.search import resolve_location
    from app.services.recommendation.engine import make_anchor
    r = await resolve_location(ctx.db, area)
    if r is None:
        raise ToolError("AREA_NOT_FOUND", f"'{area}' was not found on the map")
    return make_anchor(r.name, r.lat, r.lon, min(r.radius_km, 3.0))


async def _recommend(ctx: ToolContext, **kw) -> dict:
    from app.services.recommendation.engine import load_novelty, recommend
    from app.services.recommendation.scoring import RecommendationRequest
    req = RecommendationRequest(**kw)
    req.novelty = await load_novelty(ctx.db, user_id=ctx.owner.user_id,
                                     session_id=ctx.owner.session_id,
                                     previous_ids=ctx.extra.get("previous_ids"))
    res = await recommend(ctx.db, req)
    ctx.trace.ranking_config_version = res.config_version
    return res.to_dict()


async def h_search_pois(ctx, a: SearchPOIsArgs):
    from app.services.poi.search import filtered_search
    from app.geo.regions import geo_config
    anchor = await _anchor(ctx, a.area)
    buckets = None
    if a.scope and not anchor:
        buckets = [b.value for b in geo_config().scope_buckets[a.scope if a.scope != "local"
                                                               else "city"]]
    recs = await filtered_search(ctx.db, query=a.query, categories=[c.value for c in a.categories]
                                 or None, tags=list(a.tags) or None, buckets=buckets,
                                 max_cost_pp=a.max_cost_per_person,
                                 near=(anchor.lat, anchor.lon) if anchor else None,
                                 radius_km=a.radius_km, limit=a.limit)
    return {"items": [r.card() for r in recs],
            "anchor": {"name": anchor.name, "lat": anchor.lat, "lon": anchor.lon} if anchor else None}


async def h_recommend(ctx, a: RecommendArgs):
    from app.domain.taxonomy import is_valid_mood
    anchor = await _anchor(ctx, a.area)
    interests = [i for i in a.interests if not is_valid_mood(i) or is_valid_category(i)]
    moods = [m.value for m in a.moods] + [i for i in a.interests
                                          if is_valid_mood(i) and not is_valid_category(i)]
    return await _recommend(ctx, interests=interests, moods=moods, avoid_interests=list(a.avoid),
                            anchor=anchor, scope=a.scope, budget_per_person=a.budget_per_person,
                            party_type=a.party_type, mode=a.mode, limit=a.limit,
                            seed=ctx.extra.get("seed"), at=_when(ctx, a.when),
                            require_open=a.when in ("now", "tonight"),
                            rain_expected=a.rain_expected, indoor_preference=a.indoor_preference,
                            quiet=a.quiet, kids=a.kids, dietary=list(a.dietary),
                            exclude_ids=list(a.exclude_ids))


def _when(ctx: ToolContext, when: str | None):
    """The moment a discovery request is about, in IST - for hours and context."""
    from datetime import timedelta
    from app.nlu.timeparse import now_ist, this_weekday
    now = ctx.now or now_ist()
    if when is None:
        return None
    if when == "now":
        return now.replace(tzinfo=None)
    if when == "today":
        return now.replace(tzinfo=None, hour=max(now.hour, 10), minute=0)
    if when == "tonight":
        return now.replace(tzinfo=None, hour=max(now.hour, 19), minute=0)
    if when == "tomorrow":
        return (now + timedelta(days=1)).replace(tzinfo=None, hour=11, minute=0)
    day = this_weekday(now.date(), 5)
    return now.replace(tzinfo=None, year=day.year, month=day.month, day=day.day, hour=11,
                       minute=0)


async def h_get_poi(ctx, a: PoiArgs):
    from app.services.poi.search import get_poi_detail
    d = await get_poi_detail(ctx.db, a.poi_id)
    if d is None:
        raise LookupError("place not found")
    return d


async def h_similar(ctx, a: SimilarArgs):
    from app.services.recommendation.engine import reference_poi
    ref = await reference_poi(ctx.db, a.poi_id)
    if ref is None:
        raise LookupError("place not found")
    out = await _recommend(ctx, similar_to=ref, mode="similar", limit=a.limit,
                           exclude_ids=[a.poi_id])
    out["reference"] = ref.card()
    return out


async def h_surprise(ctx, a: SurpriseArgs):
    anchor = await _anchor(ctx, a.area)
    return await _recommend(ctx, moods=[a.mood.value] if a.mood else [], anchor=anchor,
                            budget_per_person=a.budget_per_person, mode="surprise",
                            limit=a.limit, seed=ctx.extra.get("seed"))


async def h_hours(ctx, a: PoiHoursArgs):
    from app.services.poi.repository import attach_hours, fetch_by_ids
    from app.nlu.timeparse import today_ist
    recs = await fetch_by_ids(ctx.db, [a.poi_id])
    if a.poi_id not in recs:
        raise LookupError("place not found")
    rec = recs[a.poi_id]
    on = a.on or today_ist()
    await attach_hours(ctx.db, [rec], on.weekday())
    return {"poi_id": rec.id, "name": rec.name, "date": on.isoformat(),
            "verified": rec.hours_reliable,
            "intervals": [{"open": f"{h.open_min // 60:02d}:{h.open_min % 60:02d}",
                           "close": f"{h.close_min // 60:02d}:{h.close_min % 60:02d}"
                           if h.close_min < 1440 else "24:00"} for h in rec.hours],
            "note": None if rec.hours_reliable else
            "Hours are not verified for this place; please check before going."}


async def h_cost(ctx, a: PoiCostArgs):
    from app.services.poi.repository import fetch_by_ids
    recs = await fetch_by_ids(ctx.db, [a.poi_id])
    if a.poi_id not in recs:
        raise LookupError("place not found")
    r = recs[a.poi_id]
    return {"poi_id": r.id, "name": r.name, "per_person": {"min": r.cost[0], "typical": r.cost[1],
                                                           "max": r.cost[2]},
            "party_size": a.party_size,
            "total": {"min": r.cost[0] * a.party_size, "typical": r.cost[1] * a.party_size,
                      "max": r.cost[2] * a.party_size},
            "confidence": r.cost_confidence, "basis": "estimate", "excludes": "transportation"}


async def h_by_category(ctx, a: CategorySearchArgs):
    anchor = await _anchor(ctx, a.area)
    return await _recommend(ctx, interests=[a.category.value], anchor=anchor, limit=a.limit)


async def h_by_area(ctx, a: AreaSearchArgs):
    anchor = await _anchor(ctx, a.area)
    return await _recommend(ctx, anchor=anchor, limit=a.limit)


async def h_by_mood(ctx, a: MoodSearchArgs):
    anchor = await _anchor(ctx, a.area)
    return await _recommend(ctx, moods=[a.mood.value], anchor=anchor, limit=a.limit)


async def h_by_interest(ctx, a: InterestSearchArgs):
    from app.nlu.lexicon import controlled_interest
    value = controlled_interest(a.interest)
    if value is None:
        raise ToolError("UNKNOWN_INTEREST", f"'{a.interest}' is not a known interest")
    anchor = await _anchor(ctx, a.area)
    from app.domain.taxonomy import is_valid_mood
    if is_valid_mood(value) and not is_valid_category(value):
        return await _recommend(ctx, moods=[value], anchor=anchor, limit=a.limit)
    return await _recommend(ctx, interests=[value], anchor=anchor, limit=a.limit)


async def h_resolve_location(ctx, a: NameArgs):
    from app.services.poi.search import resolve_location
    r = await resolve_location(ctx.db, a.name)
    return {"resolved": r is not None, "area": r.to_dict() if r else None}


async def h_resolve_poi(ctx, a: NameArgs):
    from app.services.poi.search import resolve_poi_name, unambiguous
    matches = await resolve_poi_name(ctx.db, a.name)
    top = unambiguous(matches)
    return {"resolved": top is not None, "poi_id": top.poi_id if top else None,
            "candidates": [{"poi_id": m.poi_id, "name": m.name,
                            "similarity": round(m.similarity, 3)} for m in matches]}


async def h_weather(ctx, a: WeatherArgs):
    from app.services.weather.client import get_window
    from app.geo.regions import geo_config
    from app.nlu.timeparse import today_ist
    cfg = geo_config()
    anchor = await _anchor(ctx, a.area) if a.area else None
    lat, lon = (anchor.lat, anchor.lon) if anchor else (cfg.center_lat, cfg.center_lon)
    on = a.on or today_ist()
    w = await get_window(lat, lon, on, 8, 20)
    return {"date": on.isoformat(), "area": anchor.name if anchor else "Bengaluru",
            **w.to_dict()}


async def h_retrieve(ctx, a: QuestionArgs):
    from app.knowledge.retrieval import retrieve
    res = await retrieve(ctx.db, a.question, k=a.k, gateway=ctx.gateway)
    return {"chunks": [c.to_source(i) | {"text": c.text[:1200]}
                       for i, c in enumerate(res.chunks, start=1)],
            "dense_available": res.dense_available, "notes": res.notes}


async def h_answer(ctx, a: QuestionArgs):
    from app.knowledge.answer import answer_question
    ans = await answer_question(ctx.db, a.question, llm=ctx.llm, gateway=ctx.gateway,
                                facts=ctx.extra.get("facts"),
                                entity_poi_ids=ctx.extra.get("entity_poi_ids"),
                                recorder=ctx.trace.record_llm, k=a.k)
    return ans.to_dict()


async def h_extract(ctx, a: TextArgs):
    from app.assistant.extraction import extract_trip_spec
    from app.nlu.timeparse import now_ist
    ex = await extract_trip_spec(a.text, now=ctx.now or now_ist(), llm=ctx.llm,
                                 recorder=ctx.trace.record_llm)
    return {"trip_spec": ex.spec.model_dump(mode="json"), "areas": ex.area_names,
            "must_include_names": ex.must_include_names, "notes": ex.notes,
            "llm_used": ex.llm_used}


def _spec(raw: dict):
    from app.schemas.tripspec import TripSpec
    try:
        return TripSpec.model_validate(raw)
    except ValidationError as exc:
        raise ToolError("INVALID_SPEC", "; ".join(e["msg"] for e in exc.errors()[:3]))


async def h_validate_spec(ctx, a: SpecArgs):
    from app.services.planning.validators.semantic import validate_semantics
    return validate_semantics(_spec(a.spec)).to_dict()


async def h_candidates(ctx, a: SpecArgs):
    spec = _spec(a.spec)
    moods = [i for i in spec.interests if i in {m.value for m in Mood}
             and not is_valid_category(i)]
    return await _recommend(ctx, interests=[i for i in spec.interests if i not in moods],
                            moods=moods, avoid_interests=list(spec.avoid_interests),
                            exclude_ids=list(spec.exclude_poi_ids), mode="plan", limit=20)


async def h_rank(ctx, a: RankArgs):
    from app.services.poi.repository import fetch_by_ids
    from app.services.recommendation.scoring import RecommendationRequest, score_poi
    recs = await fetch_by_ids(ctx.db, a.poi_ids)
    req = RecommendationRequest(interests=list(a.interests), moods=[m.value for m in a.moods])
    ranked = sorted((score_poi(r, req) for r in recs.values()), key=lambda s: (-s.score, s.poi.id))
    return {"items": [s.to_dict() for s in ranked]}


async def h_build(ctx, a: BuildArgs):
    from app.services.plans import create_plan
    outcome = await create_plan(ctx.db, _spec(a.spec), ctx.owner, now=ctx.now,
                                persist=a.persist)
    return outcome.to_dict()


async def h_validate_itinerary(ctx, a: ItineraryArgs):
    from app.schemas.tripspec import migrate_tripspec
    from app.services.planning import store
    from app.services.planning.validator.facts import load_facts, rules_for
    from app.services.planning.validator.itinerary import PlannedStop, validate
    view = await store.get_plan(ctx.db, a.itinerary_id, ctx.owner, version_no=a.version_no)
    spec = migrate_tripspec(view["trip_spec"])
    stops = [PlannedStop(s["seq"], s["poi"]["id"], s["arrive_min"], s["depart_min"])
             for s in view["itinerary"]["stops"]]
    facts = await load_facts(ctx.db, [s.poi_id for s in stops], spec.date)
    hop = 25.0 if any(s["poi"].get("recommended_as_primary_destination")
                      for s in view["itinerary"]["stops"]) else 12.0
    return validate(stops, rules_for(spec, max_hop_km=hop), facts).to_dict()


async def h_save_poi(ctx, a: PoiArgs):
    from app.services.interactions import save_poi
    return await save_poi(ctx.db, ctx.owner, a.poi_id)


async def h_dismiss(ctx, a: PoiArgs):
    from app.services.interactions import dismiss_poi
    return await dismiss_poi(ctx.db, ctx.owner, a.poi_id)


async def h_interaction(ctx, a: InteractionArgs):
    from app.services.interactions import poi_exists, record
    if not await poi_exists(ctx.db, a.poi_id):
        raise LookupError("place not found")
    await record(ctx.db, ctx.owner, a.poi_id, a.action)
    return {"recorded": True}


async def h_save_itinerary(ctx, a: ItineraryArgs):
    from app.services.planning import store
    return await store.set_status(ctx.db, a.itinerary_id, ctx.owner, "saved")


async def h_get_itinerary(ctx, a: ItineraryArgs):
    from app.services.planning import store
    return await store.get_plan(ctx.db, a.itinerary_id, ctx.owner, version_no=a.version_no)


async def h_versions(ctx, a: ItineraryArgs):
    from app.services.planning import store
    return {"versions": await store.list_versions(ctx.db, a.itinerary_id, ctx.owner)}


def _mods(ops: list[dict]):
    from app.services.planning.modify import Modification
    try:
        return [Modification.model_validate(o) for o in ops]
    except ValidationError as exc:
        raise ToolError("INVALID_MODIFICATION", "; ".join(e["msg"] for e in exc.errors()[:3]))


async def h_modify(ctx, a: ModifyArgs):
    from app.services.plans import modify_plan
    res = await modify_plan(ctx.db, a.itinerary_id, ctx.owner, _mods(a.operations),
                            expected_version_no=a.expected_version_no, now=ctx.now)
    return _mod_result(res)


async def h_what_if(ctx, a: ModifyArgs):
    from app.services.plans import modify_plan
    res = await modify_plan(ctx.db, a.itinerary_id, ctx.owner, _mods(a.operations),
                            hypothetical=True, now=ctx.now)
    return _mod_result(res)


def _mod_result(res: dict) -> dict:
    out = {k: v for k, v in res.items() if k not in ("outcome", "previous")}
    out["outcome"] = res["outcome"].to_dict()
    out["previous_itinerary"] = res["previous"]["itinerary"]
    return out


async def h_compare_versions(ctx, a: CompareVersionsArgs):
    from app.services.plans import compare_versions
    return await compare_versions(ctx.db, a.itinerary_id, ctx.owner, a.a, a.b)


async def h_get_prefs(ctx, a: NoArgs):
    from app.services.interactions import get_preferences
    return await get_preferences(ctx.db, ctx.owner)


async def h_update_prefs(ctx, a: PreferencesArgs):
    from app.services.interactions import update_preferences
    patch = {k: (v if not isinstance(v, list) else [getattr(x, "value", x) for x in v])
             for k, v in a.model_dump(exclude_none=True).items()}
    return await update_preferences(ctx.db, ctx.owner, patch)


def build_registry() -> ToolRegistry:
    r = ToolRegistry()
    T = ToolSpec
    r.register(T("search_pois", "Search places by name, category, tag, area and budget.",
                 SearchPOIsArgs, ANY_ROLE, h_search_pois, llm_selectable=True))
    r.register(T("recommend_pois", "Ranked recommendations for interests/moods/budget/area.",
                 RecommendArgs, ANY_ROLE, h_recommend))
    r.register(T("get_poi", "Full verified details for one place.", PoiArgs, ANY_ROLE,
                 h_get_poi, llm_selectable=True))
    r.register(T("get_similar_pois", "Places similar to a given place.", SimilarArgs,
                 ANY_ROLE, h_similar))
    r.register(T("get_surprise_recommendations", "High-quality surprise picks.", SurpriseArgs,
                 ANY_ROLE, h_surprise))
    r.register(T("get_poi_opening_hours", "Opening hours of a place on a date.", PoiHoursArgs,
                 ANY_ROLE, h_hours, llm_selectable=True))
    r.register(T("get_poi_cost", "Estimated cost of visiting a place.", PoiCostArgs, ANY_ROLE,
                 h_cost, llm_selectable=True))
    r.register(T("search_by_category", "Places of one category.", CategorySearchArgs, ANY_ROLE,
                 h_by_category, llm_selectable=True))
    r.register(T("search_by_area", "Good places around a named area.", AreaSearchArgs, ANY_ROLE,
                 h_by_area, llm_selectable=True))
    r.register(T("search_by_mood", "Places for a mood.", MoodSearchArgs, ANY_ROLE, h_by_mood,
                 llm_selectable=True))
    r.register(T("search_by_interest", "Places for an interest.", InterestSearchArgs, ANY_ROLE,
                 h_by_interest, llm_selectable=True))
    r.register(T("resolve_location_name", "Find a named area on the map.", NameArgs, ANY_ROLE,
                 h_resolve_location, llm_selectable=True))
    r.register(T("resolve_poi_name", "Find a place by name.", NameArgs, ANY_ROLE, h_resolve_poi,
                 llm_selectable=True))
    r.register(T("get_weather", "Forecast for a date (Open-Meteo).", WeatherArgs, ANY_ROLE,
                 h_weather, llm_selectable=True))
    r.register(T("retrieve_bengaluru_knowledge", "Retrieve knowledge passages.", QuestionArgs,
                 ANY_ROLE, h_retrieve, llm_selectable=True))
    r.register(T("answer_grounded_question", "Cited answer from the knowledge corpus.",
                 QuestionArgs, ANY_ROLE, h_answer))
    r.register(T("extract_trip_spec", "Turn a request into a TripSpec.", TextArgs, ANY_ROLE,
                 h_extract))
    r.register(T("validate_trip_spec", "Semantic validation of a TripSpec.", SpecArgs, ANY_ROLE,
                 h_validate_spec))
    r.register(T("generate_candidate_set", "Candidate places for a TripSpec.", SpecArgs,
                 ANY_ROLE, h_candidates))
    r.register(T("rank_candidates", "Deterministically rank given places.", RankArgs, ANY_ROLE,
                 h_rank))
    r.register(T("build_itinerary", "Plan and validate an itinerary.", BuildArgs, ANY_ROLE,
                 h_build))
    r.register(T("validate_itinerary", "Re-validate a stored itinerary.", ItineraryArgs,
                 ANY_ROLE, h_validate_itinerary))
    r.register(T("save_poi", "Save a place to the user's list.", PoiArgs, USER_ONLY, h_save_poi))
    r.register(T("dismiss_poi", "Mark a place as not interesting.", PoiArgs, ANY_ROLE,
                 h_dismiss))
    r.register(T("record_poi_interaction", "Record an interaction.", InteractionArgs, ANY_ROLE,
                 h_interaction))
    r.register(T("save_itinerary", "Save an itinerary.", ItineraryArgs, USER_ONLY,
                 h_save_itinerary))
    r.register(T("get_itinerary", "Get an itinerary.", ItineraryArgs, ANY_ROLE, h_get_itinerary))
    r.register(T("list_itinerary_versions", "List versions of an itinerary.", ItineraryArgs,
                 ANY_ROLE, h_versions))
    r.register(T("modify_itinerary", "Apply closed modification operations.", ModifyArgs,
                 ANY_ROLE, h_modify))
    r.register(T("compare_itinerary_versions", "Compare two versions.", CompareVersionsArgs,
                 ANY_ROLE, h_compare_versions))
    r.register(T("create_what_if_variant", "Non-destructive what-if variant.", ModifyArgs,
                 ANY_ROLE, h_what_if))
    r.register(T("get_user_preferences", "The user's explicit preferences.", NoArgs, USER_ONLY,
                 h_get_prefs))
    r.register(T("update_user_preferences", "Update explicit preferences.", PreferencesArgs,
                 USER_ONLY, h_update_prefs))
    return r


REGISTRY = build_registry()
