"""Deterministic planning engine (section 41).

    TripSpec -> resolve defaults -> semantic validation -> weather (optional)
      -> candidate retrieval (recommendation engine) -> hard filters -> ranking
      -> geographic clustering -> feasibility pre-check -> CP-SAT (greedy fallback)
      -> independent validation (re-queried facts) -> itinerary -> explanation facts

NO LLM ANYWHERE IN THIS PATH. It is the permanent fallback when the model is
down and the only thing that ever produces an itinerary. The LLM may later
phrase the explanation from the fact block this returns.

Never returns an invalid plan: if neither CP-SAT's nor the greedy fallback's
result passes the validator, the outcome is INFEASIBLE / VALIDATION_FAILED
with the reasons, not a plan.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.taxonomy import (
    MEAL_CATEGORIES, PartyType, category_catalog, is_valid_category,
    is_valid_mood,
)
from app.geo.distance import haversine_km
from app.geo.regions import geo_config
from app.nlu.timeparse import now_ist
from app.schemas.tripspec import TripSpec, minutes_to_hhmm
from app.services.planning.feasibility.engine import StopBound, check as feasibility_check
from app.services.planning.optimizer.greedy import greedy_schedule
from app.services.planning.optimizer.model import (
    OptimizerArc, OptimizerNode, OptimizerResult, optimize,
)
from app.services.planning.resolve import resolve_for_planning
from app.services.planning.validator.facts import load_facts, rules_for
from app.services.planning.validator.itinerary import PlannedStop, validate
from app.services.planning.validators.semantic import validate_semantics
from app.services.poi.repository import POIRecord, attach_hours, fetch_by_ids
from app.services.recommendation.engine import recommend
from app.services.recommendation.scoring import (
    Anchor, RecommendationRequest, Scored, reason_text, score_poi,
)
from app.services.transport import get_transportation_provider
from app.services.weather.client import WeatherWindow, get_window

PACE = {
    "quick": {"visit": 0.8, "max_stops": 6},
    "balanced": {"visit": 1.0, "max_stops": 5},
    "relaxed": {"visit": 1.25, "max_stops": 3},
}
CANDIDATE_CAP = 20          # ADR-010: CP-SAT proves optimality at 20 single-worker
SOLVE_TIME_LIMIT_S = 6.0        # wall-clock safety cap only
SOLVE_WORK_LIMIT = 1.0          # deterministic-time budget: reproducible under load; on a
                                # 6-request benchmark it matched the 8 s wall-clock objective
                                # every time while cutting the worst solve from 8.0 s to 3.2 s
COMPACTNESS_WEIGHT = 200.0  # 1 km of hop costs ~0.02 of a stop's score
EARLY_START_WEIGHT = 20     # per minute of arrival after the window opens: an idle
                            # hour weighs about as much as 0.6 km of extra hops
DEFAULT_CATEGORY_CAP = 2          # when the request names no categories at all
UNREQUESTED_CATEGORY_CAP = 1      # otherwise: at most one stop of a category nobody asked for
COVERAGE_WEIGHT = 40_000          # ~0.7 of a typical stop's score: cover each requested category
MEAL_WINDOWS = {"breakfast": (7 * 60 + 30, 10 * 60 + 30), "lunch": (12 * 60, 15 * 60),
                "dinner": (19 * 60, 22 * 60)}


@dataclass
class PlanOutcome:
    status: str                         # ok | infeasible | invalid_request | validation_failed
    spec: TripSpec
    itinerary: dict | None = None
    assumptions: list[str] = field(default_factory=list)
    semantic: dict | None = None
    feasibility: dict | None = None
    validator: dict | None = None
    weather: dict | None = None
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    candidates_considered: int = 0
    optimizer: dict = field(default_factory=dict)
    timings_ms: dict = field(default_factory=dict)
    fact_block: dict | None = None
    candidate_ids: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict:
        return {
            "status": self.status, "itinerary": self.itinerary,
            "trip_spec": self.spec.model_dump(mode="json"), "assumptions": self.assumptions,
            "semantic": self.semantic, "feasibility": self.feasibility,
            "validator_report": self.validator, "weather": self.weather,
            "warnings": self.warnings, "notes": self.notes,
            "candidates_considered": self.candidates_considered, "optimizer": self.optimizer,
            "timings_ms": self.timings_ms,
        }


@dataclass
class PlanDirectives:
    """Extra instructions from modifications: keep, prefer or drop places."""
    locked_ids: list[int] = field(default_factory=list)       # must stay (hard)
    preferred_ids: list[int] = field(default_factory=list)    # soft bonus
    replacement_category: str | None = None
    scope: str | None = None                                   # force local/city/regional
    max_stops_override: int | None = None
    # Places already used on another day of the same trip. Transient: never
    # written into the spec, so a later change to that day frees them again.
    exclude_ids: list[int] = field(default_factory=list)


def _split_interests(spec: TripSpec) -> tuple[list[str], list[str]]:
    moods = [i for i in spec.interests if is_valid_mood(i) and not is_valid_category(i)]
    others = [i for i in spec.interests if i not in moods]
    if spec.romantic and "romantic" not in moods:
        moods.append("romantic")
    if spec.quiet_preference and "quiet" not in moods:
        moods.append("quiet")
    return others, moods


def _party_type(spec: TripSpec) -> PartyType | None:
    if spec.party_type is not None:
        return spec.party_type
    if spec.party_size == 1:
        return PartyType.SOLO
    return None


def _scope_for(spec: TripSpec, directives: PlanDirectives) -> str:
    if directives.scope:
        return directives.scope
    if spec.anchor_area is not None and spec.anchor_area.resolved:
        return "local"
    cats = {i for i in spec.interests if is_valid_category(i)}
    from app.domain.taxonomy import REGIONAL_CATEGORIES
    if cats and cats <= REGIONAL_CATEGORIES:
        return "anywhere"
    return "city"


async def plan(db: AsyncSession, spec: TripSpec, *, now: datetime | None = None,
               directives: PlanDirectives | None = None,
               novelty=None, persist_fn=None) -> PlanOutcome:
    t: dict[str, int] = {}
    t_all = time.perf_counter()
    now = now or now_ist()
    directives = directives or PlanDirectives()
    geo = geo_config()
    planning_cfg = geo.planning

    # --- resolve and validate -------------------------------------------------------------
    resolution = resolve_for_planning(spec, now)
    spec = resolution.spec
    out = PlanOutcome(status="ok", spec=spec, assumptions=resolution.assumptions)
    semantic = validate_semantics(spec, today=now.date(),
                                  now_minute=now.hour * 60 + now.minute)
    out.semantic = semantic.to_dict()
    out.warnings = [w.message for w in semantic.warnings]
    if not semantic.is_valid:
        out.status = "invalid_request"
        return out

    party = spec.effective_party_size
    budget = spec.effective_budget_total
    pace = PACE[spec.pace.value]
    scope = _scope_for(spec, directives)

    # --- weather (never blocks) ----------------------------------------------------------------
    t0 = time.perf_counter()
    anchor = spec.anchor_area if spec.anchor_area and spec.anchor_area.resolved else None
    wlat, wlon = (anchor.lat, anchor.lon) if anchor else (geo.center_lat, geo.center_lon)
    weather: WeatherWindow = await get_window(wlat, wlon, spec.date, spec.start_minute // 60,
                                              spec.end_minute // 60)
    out.weather = weather.to_dict()
    if not weather.available:
        out.notes.append("Weather unavailable - planned without weather optimisation")
    t["weather"] = int((time.perf_counter() - t0) * 1000)

    # --- must-includes ------------------------------------------------------------------------------
    must_ids = list(dict.fromkeys(spec.must_include_poi_ids + directives.locked_ids))
    musts = await fetch_by_ids(db, must_ids)
    missing = [i for i in must_ids if i not in musts]
    if missing:
        out.status = "invalid_request"
        out.semantic = {"valid": False, "errors": [{
            "code": "MUST_INCLUDE_NOT_FOUND", "field": "must_include_poi_ids",
            "message": f"required places not found: {missing}", "severity": "error",
            "suggestion": None}], "warnings": []}
        return out
    await attach_hours(db, musts.values(), spec.date.weekday())

    # --- candidates ------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    interests, moods = _split_interests(spec)
    if directives.replacement_category:
        interests = [directives.replacement_category]
    rain = weather.wet if weather.available else None
    req = RecommendationRequest(
        interests=interests, moods=moods, avoid_interests=list(spec.avoid_interests),
        exclude_ids=sorted(set(spec.exclude_poi_ids) | set(must_ids)
                           | set(directives.exclude_ids)),
        party_type=_party_type(spec), party_size=party,
        budget_per_person=(budget // party) if budget is not None else None,
        scope=scope if scope != "local" else None,
        anchor=(Anchor(anchor.name, anchor.lat, anchor.lon,
                       anchor.radius_km or planning_cfg["cluster_radius_km_city"])
                if anchor else None),
        at=datetime.combine(spec.date, datetime.min.time()).replace(
            hour=spec.start_minute // 60, minute=spec.start_minute % 60),
        rain_expected=rain, indoor_preference=spec.indoor_preference,
        weather_sensitive=bool(spec.weather_sensitive), quiet=bool(spec.quiet_preference),
        dietary=list(spec.dietary_preferences),
        accessibility=list(spec.accessibility_requirements),
        kids="kids_friendly" in spec.family_requirements, mode="plan", limit=60,
    )
    if novelty is not None:
        req.novelty = novelty
    rec = await recommend(db, req)
    pool: list[Scored] = list(rec.items)
    if len(pool) < 8:
        req.recommendable_only = False
        rec2 = await recommend(db, req)
        seen = {s.poi.id for s in pool}
        pool += [s for s in rec2.items if s.poi.id not in seen]
    need_meal, meal_windows = _meal_needs(spec)
    if need_meal and not any(s.poi.category in MEAL_CATEGORIES for s in pool):
        meal_req = RecommendationRequest(**{**req.__dict__, "interests": ["restaurant", "cafe"],
                                            "moods": [], "limit": 12})
        seen = {p.poi.id for p in pool}
        for s in (await recommend(db, meal_req)).items:
            if s.poi.id in seen:
                continue
            # Scored against the user's request, not the meal search, so a
            # lunch stop never outranks what was actually asked for.
            meal = score_poi(s.poi, req)
            meal.reasons = ["MEAL_STOP"] + [r for r in meal.reasons
                                            if not r.startswith("MATCHES_")][:2]
            pool.append(meal)
    must_scored = [score_poi(p, req) for p in musts.values()]
    out.candidates_considered = len(pool) + len(must_scored)
    t["candidates"] = int((time.perf_counter() - t0) * 1000)

    # --- clustering ------------------------------------------------------------------------------------
    cluster, center, is_escape = choose_cluster(
        pool, must_scored, anchor, scope, spec, planning_cfg)
    if is_escape:
        out.notes.append("This works better as the main destination for the day, so the plan "
                         "is built around it.")
        if center is not None and len(cluster) < 8:
            # A day built around one escape should not be one stop and an idle
            # afternoon: add the best places near it, scored against the
            # user's own request so they rank below what was asked for.
            fill = RecommendationRequest(**{
                **req.__dict__, "interests": [], "moods": [], "scope": None, "limit": 15,
                "anchor": Anchor("escape", center[0], center[1],
                                 planning_cfg["cluster_radius_km_escape"])})
            seen = {s.poi.id for s in cluster} | {m.poi.id for m in must_scored}
            extra = [score_poi(s.poi, req) for s in (await recommend(db, fill)).items
                     if s.poi.id not in seen]
            cluster += extra[:max(0, CANDIDATE_CAP - len(cluster) - len(must_scored))]
    max_hop = planning_cfg["max_hop_km_escape"] if is_escape else planning_cfg["max_hop_km_city"]

    # --- feasibility --------------------------------------------------------------------------------------
    bounds = [StopBound(p.poi.name, _visit(p.poi, pace["visit"]), p.poi.cost[0],
                        _open_in_window(p.poi, spec)) for p in must_scored]
    min_visit_any = min((_visit(s.poi, pace["visit"]) for s in cluster), default=20)
    min_cost_any = min((s.poi.cost[0] for s in cluster), default=0)
    feas = feasibility_check(spec, must=bounds, candidate_count=len(cluster),
                             min_visit_any=min_visit_any, min_cost_pp_any=min_cost_any)
    out.feasibility = feas.to_dict()
    if not feas.feasible:
        out.status = "infeasible"
        out.timings_ms = {**t, "total": int((time.perf_counter() - t_all) * 1000)}
        return out

    # --- optimize --------------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    nodes, arcs, index = build_problem(cluster, must_scored, spec, pace["visit"], max_hop,
                                       directives, rain)
    max_stops = directives.max_stops_override or min(pace["max_stops"],
                                                     spec.max_stop_count or 8)
    min_stops = spec.desired_stop_count
    if min_stops:
        max_stops = max(min_stops, min(max_stops, min_stops)) if not spec.max_stop_count \
            else min(spec.max_stop_count, min_stops)
    max_stops = max(max_stops, len(must_scored))
    caps = _category_caps(spec, cluster, max_stops, must_scored)
    common = dict(start_min=spec.start_minute, end_min=spec.end_minute, budget_inr=budget,
                  max_walk_m=10 ** 9, requirements=[], mode=spec.pace.value,
                  visit_multiplier=1.0, min_visit_minutes=1, category_caps=caps,
                  compactness_weight=COMPACTNESS_WEIGHT, early_start_weight=EARLY_START_WEIGHT,
                  coverage_categories=[i for i in spec.interests if is_valid_category(i)
                                       and not category_catalog()[i].theme],
                  coverage_weight=COVERAGE_WEIGHT)
    attempts = []
    opt = optimize(nodes, arcs, **common, max_stops=max_stops, min_stops=min_stops,
                   meal_required=need_meal, meal_windows=meal_windows,
                   time_limit_s=SOLVE_TIME_LIMIT_S,
                   deterministic_limit=SOLVE_WORK_LIMIT)
    attempts.append(("cpsat", opt))
    if not opt.is_solution and need_meal:
        opt = optimize(nodes, arcs, **common, max_stops=max_stops, min_stops=min_stops,
                       meal_required=False, time_limit_s=SOLVE_TIME_LIMIT_S,
                       deterministic_limit=SOLVE_WORK_LIMIT)
        attempts.append(("cpsat_no_meal", opt))
        if opt.is_solution:
            out.notes.append("A meal stop didn't fit these constraints, so none is included")
    if not opt.is_solution and min_stops:
        opt = optimize(nodes, arcs, **common, max_stops=max_stops, min_stops=None,
                       time_limit_s=SOLVE_TIME_LIMIT_S,
                       deterministic_limit=SOLVE_WORK_LIMIT)
        attempts.append(("cpsat_relaxed_count", opt))
        if opt.is_solution and len(opt.stops) < min_stops:
            out.notes.append(f"Only {len(opt.stops)} stops fit; you asked for {min_stops}")
    greedy = greedy_schedule(nodes, arcs, start_min=spec.start_minute, end_min=spec.end_minute,
                             budget_inr=budget, max_stops=max_stops, category_caps=caps,
                             min_visit_minutes=1)
    t["optimize"] = int((time.perf_counter() - t0) * 1000)

    # --- validate: CP-SAT result first, greedy as fallback --------------------------------------
    t0 = time.perf_counter()
    chosen = None
    facts = None
    report = None
    rules = rules_for(spec, max_hop_km=max_hop)
    rules.exclude_ids |= set(directives.exclude_ids)
    for name, result in ([("cpsat", opt)] if opt.is_solution and opt.stops else []) + (
            [("greedy", greedy)] if greedy.is_solution and greedy.stops else []):
        planned = [PlannedStop(s.seq, s.poi_id, s.arrive_min, s.depart_min) for s in result.stops]
        facts = await load_facts(db, [p.poi_id for p in planned], spec.date)
        report = validate(planned, rules, facts)
        if report.valid:
            chosen = (name, result)
            break
        out.notes.append(f"{name} result rejected by the validator: "
                         f"{sorted(report.rules_failed())}")
    t["validate"] = int((time.perf_counter() - t0) * 1000)
    out.optimizer = {"attempts": [{"name": n, "status": r.status.value, "solve_ms": r.solve_ms,
                                   "stops": len(r.stops)} for n, r in attempts]
                     + [{"name": "greedy", "status": greedy.status.value,
                         "solve_ms": greedy.solve_ms, "stops": len(greedy.stops)}],
                     "candidate_count": len(nodes) - 1}
    out.candidate_ids = [n.poi_id for n in nodes[1:]]
    if report is not None:
        out.validator = report.to_dict()
    if chosen is None:
        out.status = "infeasible" if not (opt.is_solution or greedy.is_solution) else \
            "validation_failed"
        if out.status == "infeasible":
            out.feasibility = {**(out.feasibility or {}), "feasible": False,
                               "message": "No arrangement of places fits every constraint.",
                               "suggested_relaxations": [r.to_dict() for r in (
                                   _fallback_relaxations(spec))]}
        out.timings_ms = {**t, "total": int((time.perf_counter() - t_all) * 1000)}
        return out

    name, result = chosen
    out.optimizer["used"] = name
    by_id = {s.poi.id: s for s in cluster + must_scored}
    out.itinerary = build_itinerary(spec, result, facts, by_id, weather, out, center)
    out.fact_block = explanation_facts(out.itinerary)
    out.timings_ms = {**t, "total": int((time.perf_counter() - t_all) * 1000)}
    if persist_fn is not None:
        out.itinerary.update(await persist_fn(out))
    return out


def _visit(poi: POIRecord, mult: float) -> int:
    lo, typ, hi = poi.visit
    return max(lo, min(hi, int(round(typ * mult))))


def _open_in_window(poi: POIRecord, spec: TripSpec) -> bool | None:
    if not poi.hours_reliable or poi.hours_loaded_for_day is None:
        return None
    for h in poi.hours:
        if h.is_24h:
            return True
        if min(h.close_min, spec.end_minute) - max(h.open_min, spec.start_minute) >= poi.visit[0]:
            return True
    return False


def _meal_needs(spec: TripSpec) -> tuple[bool, list[tuple[int, int]]]:
    s, e = spec.start_minute, spec.end_minute
    wanted = [m for m in spec.meal_preferences if m in MEAL_WINDOWS]
    if wanted:
        return True, [MEAL_WINDOWS[m] for m in wanted]
    windows = []
    if s <= 12 * 60 + 30 and e >= 14 * 60 + 30 and e - s >= 240:
        windows.append(MEAL_WINDOWS["lunch"])
    if s <= 19 * 60 + 30 and e >= 21 * 60 and e - s >= 240:
        windows.append(MEAL_WINDOWS["dinner"])
    return bool(windows), windows


def _category_caps(spec: TripSpec, cluster: list[Scored], max_stops: int = 5,
                   musts: list[Scored] | None = None) -> dict[str, int]:
    requested = {i for i in spec.interests if is_valid_category(i)}
    other = UNREQUESTED_CATEGORY_CAP if requested else DEFAULT_CATEGORY_CAP
    # Several requested categories share the day: "a garden, a museum and a
    # cafe" should not become three cafes.
    share = max(1, min(3, -(-max_stops // len(requested)))) if requested else 3
    caps = {}
    for s in cluster:
        c = s.poi.category
        caps[c] = share if c in requested else other
    for c in ("restaurant", "nightlife", "mall"):
        if c in caps:
            caps[c] = min(caps[c], 2 if c in requested else 1)
    # One big outing per day: never two hill treks or two safaris.
    for c in ("hill", "adventure", "nature", "farm"):
        if c in caps:
            caps[c] = 1
    # Places the user must keep (named stops, or the stops a modification
    # leaves in place) always fit: a cap never makes a kept plan infeasible.
    for m in musts or []:
        c = m.poi.category
        caps[c] = max(caps.get(c, 0), sum(1 for x in musts if x.poi.category == c))
    return caps


def choose_cluster(pool: list[Scored], musts: list[Scored], anchor, scope: str, spec: TripSpec,
                   cfg: dict) -> tuple[list[Scored], tuple[float, float] | None, bool]:
    """Pick a geographically coherent subset (<= CANDIDATE_CAP) of the pool.

    Distance here is only a coherence measure; nothing converts it to time.
    """
    window = spec.window_minutes or 0
    long_window = window >= cfg["primary_destination_min_window_min"]
    # A nearby-escape destination is only planned as THE destination of a
    # long day, never packed in as one stop of many.
    escape_candidates = [s for s in pool + musts if (s.poi.primary_destination or
                         s.poi.region_bucket == "NEARBY_ESCAPE")]
    must_escape = [s for s in musts if s in escape_candidates]
    is_escape = False
    center = None
    if must_escape or (scope in ("regional", "anywhere") and long_window and escape_candidates
                       and not anchor and not musts):
        main = must_escape[0] if must_escape else max(
            escape_candidates, key=lambda s: (s.score, -s.poi.id))
        center = (main.poi.lat, main.poi.lon)
        radius = cfg["cluster_radius_km_escape"]
        is_escape = True
        if main not in musts:
            musts.append(main)
    elif anchor is not None:
        center = (anchor.lat, anchor.lon)
        radius = max(anchor.radius_km or 0, cfg["cluster_radius_km_city"])
    elif musts:
        center = (sum(m.poi.lat for m in musts) / len(musts),
                  sum(m.poi.lon for m in musts) / len(musts))
        radius = max(cfg["cluster_radius_km_city"], 2 + max(
            haversine_km(center[0], center[1], m.poi.lat, m.poi.lon) for m in musts))
    else:
        radius = cfg["cluster_radius_km_city"]
        best = None
        top = sorted(pool, key=lambda s: (-s.score, s.poi.id))[:15]
        for c in top:
            members = sorted((s.score for s in pool if haversine_km(
                c.poi.lat, c.poi.lon, s.poi.lat, s.poi.lon) <= radius), reverse=True)[:10]
            value = sum(members)
            if best is None or value > best[0] + 1e-9:
                best = (value, c)
        if best is not None:
            center = (best[1].poi.lat, best[1].poi.lon)

    def keep(s: Scored) -> bool:
        if s in musts:
            return False
        if not is_escape and (s.poi.large_time_block or s.poi.region_bucket == "NEARBY_ESCAPE") \
                and not long_window:
            return False
        if center is None:
            return True
        return haversine_km(center[0], center[1], s.poi.lat, s.poi.lon) <= radius

    members = sorted((s for s in pool if keep(s)), key=lambda s: (-s.score, s.poi.id))
    slots = max(0, CANDIDATE_CAP - len(musts))
    # Stratified: the best few of every requested category are candidates
    # even when one category's places all score higher (cheap cafes with
    # verified hours can otherwise crowd the garden out of the problem).
    requested = [i for i in spec.interests if is_valid_category(i)]
    reserved: list[Scored] = []
    if requested:
        per = max(2, slots // (2 * len(requested)))
        for c in dict.fromkeys(requested):
            reserved += [s for s in members if s.poi.category == c][:per]
    reserved = reserved[:slots]
    taken = {s.poi.id for s in reserved}
    chosen = reserved + [s for s in members if s.poi.id not in taken][:slots - len(reserved)]
    chosen.sort(key=lambda s: (-s.score, s.poi.id))
    meals = [s for s in members[slots:] if s.poi.category in MEAL_CATEGORIES][:3]
    if meals and not any(s.poi.category in MEAL_CATEGORIES for s in chosen):
        chosen = chosen[: max(0, slots - len(meals))] + meals
    return chosen, center, is_escape


def build_problem(cluster: list[Scored], musts: list[Scored], spec: TripSpec, visit_mult: float,
                  max_hop: float, directives: PlanDirectives, rain: bool | None):
    nodes = [OptimizerNode(None, "Start", "origin", 0.0, 0, 0, spec.start_minute,
                           spec.end_minute)]
    index: dict[int, int] = {}
    party = spec.effective_party_size
    must_ids = {m.poi.id for m in musts}
    preferred = set(directives.preferred_ids)
    for s in musts + cluster:
        p = s.poi
        if p.id in index:
            continue
        open_min, close_min, conf = 0, 1440, p.hours_confidence
        if p.hours_reliable and p.hours_loaded_for_day is not None:
            if not p.hours:
                if p.id not in must_ids:
                    continue          # closed all day - not a candidate
            else:
                best = max(p.hours, key=lambda h: min(h.close_min, spec.end_minute)
                           - max(h.open_min, spec.start_minute))
                open_min, close_min = (0, 1440) if best.is_24h else (best.open_min,
                                                                      best.close_min)
        score = s.score + (0.3 if p.id in preferred else 0.0)
        index[p.id] = len(nodes)
        nodes.append(OptimizerNode(
            poi_id=p.id, name=p.name, category=p.category, score=min(1.5, score),
            visit_minutes=_visit(p, visit_mult), cost_inr=p.cost[1] * party,
            open_min=open_min, close_min=close_min, hours_confidence=conf,
            is_meal=p.category in MEAL_CATEGORIES, must_visit=p.id in must_ids))
    arcs: dict[tuple[int, int], OptimizerArc] = {}
    buffer = spec.transition_buffer_minutes
    pois = {i: s.poi for s in musts + cluster for i in [index.get(s.poi.id)] if i is not None}
    n = len(nodes)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if i == 0 or j == 0:
                arcs[(i, j)] = OptimizerArc(0, 0, 0, "start" if i == 0 else "end", 0.0)
                continue
            a, b = pois[i], pois[j]
            hop = haversine_km(a.lat, a.lon, b.lat, b.lon)
            if hop <= max_hop:
                arcs[(i, j)] = OptimizerArc(buffer, 0, 0, "transition", round(hop, 3))
    return nodes, arcs, index


def _fallback_relaxations(spec: TripSpec):
    from app.services.planning.feasibility.engine import Relaxation
    out = [Relaxation("REDUCE_STOPS", "Ask for fewer stops",
                      {"op": "set_stop_count", "count": max(1, (spec.desired_stop_count or 3) - 1)})]
    if spec.effective_budget_total is not None:
        out.append(Relaxation("INCREASE_BUDGET", "Raise the budget",
                              {"op": "set_budget",
                               "amount": int(spec.effective_budget_total * 1.5) + 100}))
    if spec.anchor_area is not None:
        out.append(Relaxation("CHANGE_AREA", "Search the whole city",
                              {"op": "set_area", "area": None}))
    if spec.end_minute is not None and spec.end_minute < 22 * 60:
        out.append(Relaxation("INCREASE_TIME", "Allow a longer time window",
                              {"op": "set_end_time",
                               "time": minutes_to_hhmm(min(22 * 60, spec.end_minute + 120))}))
    if spec.interests:
        out.append(Relaxation("WIDEN_CATEGORIES", "Allow a wider mix of places",
                              {"op": "remove_interest", "interest": spec.interests[-1]}))
    return out


def build_itinerary(spec: TripSpec, result: OptimizerResult, facts: dict[int, POIRecord],
                    scored: dict[int, Scored], weather: WeatherWindow, out: PlanOutcome,
                    center) -> dict:
    party = spec.effective_party_size
    provider = get_transportation_provider()
    stops = []
    total_min = total_typ = total_max = 0
    prev_depart = None
    for s in result.stops:
        p = facts[s.poi_id]
        sc = scored.get(s.poi_id)
        cmin, ctyp, cmax = (c * party for c in p.cost)
        total_min, total_typ, total_max = total_min + cmin, total_typ + ctyp, total_max + cmax
        reasons = sc.reasons if sc else []
        stops.append({
            "seq": s.seq, "poi": p.card(),
            "arrive": minutes_to_hhmm(s.arrive_min), "depart": minutes_to_hhmm(s.depart_min),
            "arrive_min": s.arrive_min, "depart_min": s.depart_min,
            "visit_minutes": s.depart_min - s.arrive_min,
            "estimated_cost": {"min": cmin, "typical": ctyp, "max": cmax,
                               "party_size": party, "confidence": p.cost_confidence},
            # The gap before a stop is the fixed transition buffer plus any free
            # time (e.g. waiting for a place to open). Neither is travel time.
            "transition_buffer_before_min": 0 if prev_depart is None
            else min(spec.transition_buffer_minutes, s.arrive_min - prev_depart),
            "free_time_before_min": (s.arrive_min - spec.start_minute) if prev_depart is None
            else max(0, s.arrive_min - prev_depart - spec.transition_buffer_minutes),
            "hours_verified": p.hours_reliable,
            "reason_codes": reasons,
            "why": [reason_text(r) for r in reasons[:3]],
        })
        prev_depart = s.depart_min
    lats = [st["poi"]["lat"] for st in stops]
    lons = [st["poi"]["lon"] for st in stops]
    interests = list(spec.interests)
    title_bits = [category_catalog()[i].name for i in interests if is_valid_category(i)][:2]
    title = ("Your Bengaluru day" if not title_bits
             else f"{' & '.join(title_bits)} day")
    budget = spec.effective_budget_total
    return {
        "title": title,
        "date": spec.date.isoformat(), "start_time": spec.start_time, "end_time": spec.end_time,
        "stops": stops,
        "summary": {
            "stop_count": len(stops),
            "estimated_cost": {"min": total_min, "typical": total_typ, "max": total_max,
                               "currency": "INR", "basis": "estimate",
                               "excludes": "transportation"},
            "budget": budget,
            "within_budget": budget is None or total_typ <= budget,
            "max_may_exceed_budget": budget is not None and total_max > budget,
            "total_visit_minutes": sum(st["visit_minutes"] for st in stops),
            "span_minutes": (stops[-1]["depart_min"] - stops[0]["arrive_min"]) if stops else 0,
            "interests": interests, "pace": spec.pace.value, "party_size": party,
            "party_type": spec.party_type.value if spec.party_type else None,
        },
        "transition_buffer_minutes": spec.transition_buffer_minutes,
        "transition_note": provider.note(),
        "weather": weather.to_dict(),
        "map": {"center": {"lat": center[0], "lon": center[1]} if center else None,
                "bbox": [min(lats), min(lons), max(lats), max(lons)] if stops else None},
        "assumptions": out.assumptions,
        "notes": out.notes,
        "optimizer": out.optimizer.get("used"),
        "attribution": "Place data © OpenStreetMap contributors (ODbL); descriptions from "
                       "Wikipedia (CC BY-SA) where noted.",
    }


def explanation_facts(itinerary: dict) -> dict:
    """The only facts an LLM explanation may use (section 75)."""
    stops = []
    numbers: set[str] = set()
    for st in itinerary["stops"]:
        stops.append({
            "seq": st["seq"], "name": st["poi"]["name"], "category": st["poi"]["category"],
            "arrive": st["arrive"], "depart": st["depart"],
            "estimated_cost_typical": st["estimated_cost"]["typical"],
            "reason_codes": st["reason_codes"], "region": st["poi"]["region_bucket"],
            "locality": st["poi"]["locality"], "day": st.get("day"),
        })
        if st.get("day"):
            numbers.add(str(st["day"]))
        numbers.update({str(st["seq"]), st["arrive"], st["depart"],
                        str(st["estimated_cost"]["typical"]), str(st["visit_minutes"])})
        numbers.update(st["arrive"].split(":") + st["depart"].split(":"))
    s = itinerary["summary"]
    numbers.update({str(s["stop_count"]), str(s["estimated_cost"]["typical"]),
                    str(s["estimated_cost"]["min"]), str(s["estimated_cost"]["max"]),
                    str(itinerary["transition_buffer_minutes"]), str(s["party_size"])})
    if s["budget"] is not None:
        numbers.add(str(s["budget"]))
    numbers.update(itinerary["start_time"].split(":") + itinerary["end_time"].split(":"))
    numbers.update({itinerary["start_time"], itinerary["end_time"]})
    for d in itinerary.get("days") or []:
        numbers.update({str(d["day"]), d["start_time"], d["end_time"]})
        numbers.update(d["start_time"].split(":") + d["end_time"].split(":"))
    if itinerary.get("day_count"):
        numbers.add(str(itinerary["day_count"]))
    return {"stops": stops, "summary": s, "date": itinerary["date"],
            "end_date": itinerary.get("end_date"),
            "window": [itinerary["start_time"], itinerary["end_time"]],
            "transition_note": itinerary["transition_note"], "allowed_numbers": sorted(numbers)}
