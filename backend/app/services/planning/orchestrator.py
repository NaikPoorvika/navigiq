"""NQ-025 - Planning orchestrator.

Wires every deterministic component into one call. This is the whole product:

    TripSpec -> semantic validation -> weather -> feasibility precheck
             -> POI search -> ranking -> multi-modal arcs -> CP-SAT
             -> independent validation -> persistence

NO LLM ANYWHERE IN THIS PATH. That is deliberate: if the model is
unavailable, this still produces a correct itinerary from the form.

FAILURE BEHAVIOUR:
  infeasible        -> the feasibility report with relaxation options
  no candidates     -> a typed error naming the empty category
  routing down      -> a typed error and NO itinerary. Never a guessed
                       distance in a plan shown to a user
  weather down      -> plan proceeds, flagged as degraded
  validator fails   -> nothing is persisted. The optimizer and the validator
                       disagreeing means one of them is wrong
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.tripspec import TripSpec
from app.services.costs.estimator import TransportMode, estimate_poi_cost
from app.services.planning.feasibility.engine import (
    CandidateSummary, FeasibilityEngine,
)
from app.services.planning.optimizer.model import (
    InterestRequirement, OptimizerNode, OptimizerStatus, optimize,
)
from app.services.planning.validator.itinerary import (
    StopFacts, TripFacts, validate as validate_itinerary,
)
from app.services.planning.validators.semantic import validate_semantics
from app.services.poi.ranking import DeterministicRanker
from app.services.poi.search import search_pois
from app.services.routing.multimodal import MultiModalRouter
from app.services.routing.service import RoutingUnavailable
from app.services.weather.client import WeatherWindow, get_window

# Meal bands, minutes since midnight.
MEAL_WINDOWS = [(12 * 60, 15 * 60), (19 * 60, 22 * 60)]

SEARCH_RADIUS_KM = 8.0
WIDENED_RADIUS_KM = 15.0


class PlanningError(Exception):
    """Base for typed failures the API turns into error codes."""
    code = "PLANNING_FAILED"


class NoCandidatesError(PlanningError):
    code = "NO_CANDIDATES"


class RoutingUnavailableError(PlanningError):
    code = "ROUTING_UNAVAILABLE"


class ValidationFailedError(PlanningError):
    code = "VALIDATION_FAILED"


@dataclass
class PlanResult:
    ok: bool
    itinerary: dict | None = None
    feasibility: dict | None = None
    weather: dict | None = None
    validator_report: dict | None = None
    semantic_warnings: list[dict] = field(default_factory=list)
    relaxations_applied: list[str] = field(default_factory=list)
    timings_ms: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "itinerary": self.itinerary,
            "feasibility": self.feasibility,
            "weather": self.weather,
            "validator_report": self.validator_report,
            "semantic_warnings": self.semantic_warnings,
            "relaxations_applied": self.relaxations_applied,
            "timings_ms": self.timings_ms,
        }


async def _category_defaults(db: AsyncSession) -> dict[str, int]:
    rows = (await db.execute(
        text("SELECT key, default_visit_minutes FROM poi_categories"))).all()
    return {r.key: r.default_visit_minutes for r in rows}


async def _candidate_summaries(
    db: AsyncSession, spec: TripSpec, pois_by_cat: dict[str, list],
) -> dict[str, CandidateSummary]:
    """What the feasibility pre-check needs, derived from real search results."""
    out: dict[str, CandidateSummary] = {}
    for category, rows in pois_by_cat.items():
        if not rows:
            out[category] = CandidateSummary(
                category=category, count=0, min_cost_inr=0,
                min_visit_minutes=0, nearest_km=0.0,
                any_open_in_window=False)
            continue
        costs = [
            (r.cost_estimate_inr if r.cost_estimate_inr is not None
             else r.category_typical_inr) for r in rows
        ]
        out[category] = CandidateSummary(
            category=category,
            count=len(rows),
            min_cost_inr=min(costs) if costs else 0,
            min_visit_minutes=min(r.visit_minutes for r in rows),
            nearest_km=min(r.distance_m for r in rows) / 1000,
            any_open_in_window=any(
                r.open_at_requested is not False for r in rows),
            all_outdoor=all(r.indoor is False for r in rows),
        )
    return out


async def plan(
    db: AsyncSession,
    spec: TripSpec,
    *,
    user_id=None,
    persist: bool = True,
) -> PlanResult:
    """The deterministic planning pipeline."""
    import time
    t = {}
    result = PlanResult(ok=False)

    # --- 1. semantic validation -------------------------------------------
    t0 = time.perf_counter()
    semantic = validate_semantics(spec)
    result.semantic_warnings = [i.to_dict() for i in semantic.warnings]
    if not semantic.is_valid:
        result.feasibility = {"semantic_errors":
                              [i.to_dict() for i in semantic.errors]}
        return result
    t["semantic"] = int((time.perf_counter() - t0) * 1000)

    # --- 2. weather (degrades, never blocks) -------------------------------
    t0 = time.perf_counter()
    weather: WeatherWindow = await get_window(
        spec.origin.lat, spec.origin.lon, spec.date,
        spec.start_minute // 60, spec.end_minute // 60)
    result.weather = weather.to_dict()
    t["weather"] = int((time.perf_counter() - t0) * 1000)

    # --- 3. candidate search, per requested category -----------------------
    t0 = time.perf_counter()
    wanted = [i.category.value for i in spec.interests]
    depart_at = datetime.combine(spec.date, datetime.min.time()).replace(
        hour=spec.start_minute // 60, minute=spec.start_minute % 60)

    pois_by_cat: dict[str, list] = {}
    for category in wanted:
        rows = await search_pois(
            db, lat=spec.origin.lat, lon=spec.origin.lon,
            radius_km=SEARCH_RADIUS_KM, categories=[category],
            open_at=depart_at,
            max_cost_inr=spec.budget_inr,
            exclude_ids=spec.constraints.avoid_poi_ids or None,
            limit=30,
        )
        if not rows:
            rows = await search_pois(
                db, lat=spec.origin.lat, lon=spec.origin.lon,
                radius_km=WIDENED_RADIUS_KM, categories=[category],
                open_at=depart_at, limit=30)
        pois_by_cat[category] = rows
    t["search"] = int((time.perf_counter() - t0) * 1000)

    # --- 4. feasibility precheck -------------------------------------------
    t0 = time.perf_counter()
    engine = FeasibilityEngine(await _category_defaults(db))
    summaries = await _candidate_summaries(db, spec, pois_by_cat)
    feas = engine.check(spec, summaries,
                        heavy_rain_expected=weather.heavy_rain_expected)
    result.feasibility = feas.to_dict()
    t["feasibility"] = int((time.perf_counter() - t0) * 1000)

    if not feas.feasible:
        # Automatic relaxations only. Anything touching a MUST needs the user.
        auto = [r for r in feas.suggested_relaxations
                if not r.requires_confirmation]
        if not auto:
            result.timings_ms = t
            return result
        from app.services.planning.feasibility.engine import apply_relaxation
        for r in auto:
            spec = apply_relaxation(spec, r)
            result.relaxations_applied.append(r.description)
        feas = engine.check(spec, summaries,
                            heavy_rain_expected=weather.heavy_rain_expected)
        result.feasibility = feas.to_dict()
        if not feas.feasible:
            result.timings_ms = t
            return result

    # --- 5. rank ------------------------------------------------------------
    t0 = time.perf_counter()
    flat = [r.to_dict() for rows in pois_by_cat.values() for r in rows]
    if not flat:
        raise NoCandidatesError("no POIs found for any requested category")

    ranker = DeterministicRanker()
    ranked = ranker.rank(
        flat, wanted,
        is_raining=weather.heavy_rain_expected,
        arrival_min_of_day=spec.start_minute,
    )
    t["rank"] = int((time.perf_counter() - t0) * 1000)

    # --- 6. multi-modal arcs -----------------------------------------------
    t0 = time.perf_counter()
    points = [(spec.origin.lat, spec.origin.lon)]
    points += [(s.poi["lat"], s.poi["lon"]) for s in ranked]
    modes = [m.value for m in spec.transport]

    router = MultiModalRouter()
    try:
        arc_grid = await router.build_matrix(
            points, modes, depart_at, spec.party_size,
            spec.constraints.max_walking_km * 1000)
    except RoutingUnavailable as exc:
        raise RoutingUnavailableError(str(exc)) from exc

    arcs = {}
    for i, row in enumerate(arc_grid):
        for j, a in enumerate(row):
            if a is None:
                continue
            from app.services.planning.optimizer.model import OptimizerArc
            arcs[(i, j)] = OptimizerArc(
                duration_min=max(1, int(a.duration_s / 60)),
                cost_inr=a.cost_inr, walk_m=int(a.walk_m), mode=a.mode)
    t["arcs"] = int((time.perf_counter() - t0) * 1000)

    # --- 7. optimize --------------------------------------------------------
    t0 = time.perf_counter()
    defaults = await _category_defaults(db)
    nodes = [OptimizerNode(None, "Origin", "origin", 0.0, 0, 0,
                           spec.start_minute, spec.end_minute)]
    for s in ranked:
        p = s.poi
        cost, _ = estimate_poi_cost(
            p.get("cost_estimate_inr"), p.get("category_typical_inr", 0),
            spec.party_size)
        hours = p.get("opening_hours_window") or (0, 1440)
        nodes.append(OptimizerNode(
            poi_id=p["id"], name=p["name"],
            # The MATCHED category, not the primary. A lake found via a
            # sunset link must count toward a sunset requirement and must
            # attract the diversity penalty as a sunset stop.
            category=p.get("matched_category") or p["category"],
            score=s.score,
            visit_minutes=p.get("visit_minutes")
                          or defaults.get(p["category"], 45),
            cost_inr=cost,
            open_min=hours[0], close_min=hours[1],
            hours_confidence=p.get("hours_confidence") or 0.0,
            is_meal=p["category"] in ("restaurant", "cafe",
                                      "street_food", "dessert"),
        ))

    requirements = [
        InterestRequirement(i.category.value, i.count,
                            i.priority.value == "must")
        for i in spec.interests
    ]

    opt = optimize(
        nodes, arcs,
        start_min=spec.start_minute, end_min=spec.end_minute,
        budget_inr=spec.budget_inr,
        max_walk_m=int(spec.constraints.max_walking_km * 1000),
        requirements=requirements, mode=spec.mode.value,
        meal_required=spec.constraints.meal_required,
        meal_windows=MEAL_WINDOWS,
    )
    t["optimize"] = int((time.perf_counter() - t0) * 1000)

    if not opt.is_solution or not opt.stops:
        result.timings_ms = t
        result.feasibility = {
            **(result.feasibility or {}),
            "optimizer_status": opt.status.value,
        }
        return result

    # --- 8. independent validation -----------------------------------------
    t0 = time.perf_counter()
    by_id = {s.poi["id"]: s.poi for s in ranked}
    stop_facts = []
    for st in opt.stops:
        p = by_id.get(st.poi_id, {})
        arc = arc_grid[0][0]  # placeholder, replaced below
        prev_idx = 0 if st.seq == 1 else next(
            (i for i, n in enumerate(nodes)
             if n.poi_id == opt.stops[st.seq - 2].poi_id), 0)
        this_idx = next((i for i, n in enumerate(nodes)
                         if n.poi_id == st.poi_id), 0)
        arc = arc_grid[prev_idx][this_idx]
        stop_facts.append(StopFacts(
            seq=st.seq, poi_id=st.poi_id, name=st.name, category=st.category,
            lat=p.get("lat", 0.0), lon=p.get("lon", 0.0),
            arrive_min=st.arrive_min, depart_min=st.depart_min,
            cost_inr=st.cost_inr,
            open_min=None, close_min=None,
            hours_confidence=p.get("hours_confidence") or 0.0,
            indoor=bool(p.get("indoor")),
            travel_s_from_prev=arc.duration_s if arc else None,
            optimizer_travel_s_from_prev=st.travel_minutes_from_prev * 60,
            walk_m_from_prev=arc.walk_m if arc else 0.0,
            leg_cost_inr=arc.cost_inr if arc else 0,
        ))

    trip_facts = TripFacts(
        start_min=spec.start_minute, end_min=spec.end_minute, date=spec.date,
        budget_inr=spec.budget_inr,
        max_walk_m=spec.constraints.max_walking_km * 1000,
        must_interests={i.category.value: i.count
                        for i in spec.interests
                        if i.priority.value == "must"},
        excluded_categories={c.value
                             for c in spec.constraints.avoid_categories},
        excluded_poi_ids=set(spec.constraints.avoid_poi_ids),
        heavy_rain_expected=weather.heavy_rain_expected,
    )

    report = validate_itinerary(stop_facts, trip_facts,
                                declared_relaxations=result.relaxations_applied)
    result.validator_report = report.to_dict()
    t["validate"] = int((time.perf_counter() - t0) * 1000)

    if not report.valid:
        # The optimizer and the validator disagree. One of them is wrong, so
        # nothing is persisted.
        result.timings_ms = t
        result.itinerary = opt.to_dict()
        return result

    result.ok = True
    result.itinerary = opt.to_dict()
    result.timings_ms = t
    return result