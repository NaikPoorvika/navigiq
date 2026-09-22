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
from app.services.costs.estimator import (
    TransportMode, estimate_poi_cost, mode_overhead_min,
)
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
from app.services.weather.client import WeatherWindow, get_window, get_windows
from app.models.itinerary import (
    Itinerary, ItineraryStop, ItineraryVersion, PlanSnapshot, TripSpecRecord,
)

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

async def _persist(
    db: AsyncSession,
    spec: TripSpec,
    opt,
    report,
    weather,
    feasibility: dict,
    ranked,
    user_id,
    relaxations: list[str],
) -> int:
    """Write the itinerary. Versions are immutable - a modification or reroute
    creates a new one rather than mutating this."""
    spec_row = TripSpecRecord(
        user_id=user_id, payload=spec.model_dump(mode="json"),
        version=spec.version, source=spec.source,
    )
    db.add(spec_row)
    await db.flush()

    itin = Itinerary(
        user_id=user_id, tripspec_id=spec_row.id,
        status="draft", mode=spec.mode.value,
    )
    db.add(itin)
    await db.flush()

    version = ItineraryVersion(
        itinerary_id=itin.id, version_no=1, reason="initial",
        total_cost_inr=opt.total_cost_inr,
        total_duration_min=opt.total_duration_min,
        total_walk_m=opt.total_walk_m,
        objective_value=int(opt.objective_value),
        validator_report=report.to_dict(),
    )
    db.add(version)
    await db.flush()

    for s in opt.stops:
        db.add(ItineraryStop(
            version_id=version.id, seq=s.seq, poi_id=s.poi_id,
            arrive_min=s.arrive_min, depart_min=s.depart_min,
            visit_minutes=s.visit_minutes, cost_inr=s.cost_inr,
            mode_from_prev=s.mode_from_prev,
            travel_seconds_from_prev=s.travel_minutes_from_prev * 60,
            notes={},
        ))

    # Everything needed to replay this plan exactly as it was produced.
    db.add(PlanSnapshot(
        version_id=version.id,
        tripspec=spec.model_dump(mode="json"),
        candidate_poi_ids=[s.poi["id"] for s in ranked],
        optimizer_params={
            "mode": spec.mode.value,
            "candidate_count": len(ranked),
            "relaxations_applied": relaxations,
        },
        optimizer_status=opt.status.value,
        solve_ms=opt.solve_ms,
        weather=weather.to_dict(),
        feasibility_report=feasibility,
    ))

    itin.current_version_id = version.id
    await db.commit()
    return itin.id
async def _hours_for_stops(
    db: AsyncSession, poi_ids: list[int], day_of_week: int,
) -> dict[int, object]:
    """Re-query opening hours from the primary table for the validator,
    rather than trusting what flowed through search and the optimizer."""
    if not poi_ids:
        return {}
    rows = (await db.execute(text("""
        SELECT DISTINCT ON (poi_id)
               poi_id, open_min, close_min, is_24h, confidence
        FROM poi_opening_hours
        WHERE poi_id = ANY(CAST(:ids AS bigint[]))
          AND day_of_week = :dow
        ORDER BY poi_id, confidence DESC, (close_min - open_min) DESC
    """), {"ids": poi_ids, "dow": day_of_week})).all()
    return {r.poi_id: r for r in rows}

async def _leg_geometry(routing, a, b, mode, depart_at) -> str | None:
    """The road shape of one leg, for drawing on the map.

    Never affects the plan: if OSRM can't answer, the map draws a straight
    line and says so. Times and distances still come from the matrix.
    """
    try:
        r = await routing.get_route(
            a, b,
            mode="walking" if mode == "walking" else "driving",
            depart_at=depart_at, include_geometry=True,
        )
        return r.geometry
    except Exception:          # noqa: BLE001 - drawing must never break a plan
        return None


async def _leg_geometries(routing, points, nodes, stops, depart_at) -> dict[int, str]:
    """Road shapes for every leg, keyed by stop sequence number."""
    out: dict[int, str] = {}
    for st in stops:
        if not st.mode_from_prev:
            continue
        prev_idx = 0 if st.seq == 1 else next(
            (i for i, n in enumerate(nodes)
             if n.poi_id == stops[st.seq - 2].poi_id), 0)
        this_idx = next((i for i, n in enumerate(nodes)
                         if n.poi_id == st.poi_id), 0)
        geometry = await _leg_geometry(routing, points[prev_idx], points[this_idx],
                                       st.mode_from_prev, depart_at)
        if geometry:
            out[st.seq] = geometry
    return out

async def _refetch_leg_seconds(routing, a, b, mode, depart_at) -> float | None:
    """Re-derive one chosen leg with an independent /route call, so the
    validator is not comparing the optimizer's travel time with itself.
    Returns None if routing is unavailable - the rule is then skipped."""
    try:
        if mode == "walking":
            r = await routing.get_route(a, b, mode="walking",
                                        depart_at=depart_at,
                                        include_geometry=False)
        else:
            overhead = mode_overhead_min(TransportMode(mode)) * 60
            r = await routing.get_route(a, b, mode="driving",
                                        depart_at=depart_at,
                                        overhead_s=overhead,
                                        include_geometry=False)
        return r.duration_s
    except (RoutingUnavailable, ValueError):
        return None

async def plan(
    db: AsyncSession,
    spec: TripSpec,
    *,
    user_id=None,
    persist: bool = True,
    weather: WeatherWindow | None = None,
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
    # A multi-day trip fetches every day's forecast in one request and passes
    # each day in; a single-day plan fetches its own.
    if weather is None:
        weather = await get_window(
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
        cost, cost_basis = estimate_poi_cost(
            p.get("cost_estimate_inr"), p.get("category_typical_inr", 0),
            spec.party_size)
        # The trip day's opening window, from search. The optimizer treats
        # it as hard only when confidence >= 0.5 (real OSM hours); category
        # defaults stay soft, per NQ-014.
        if p.get("is_24h") or p.get("open_min") is None:
            hours = (0, 1440)
        else:
            hours = (p["open_min"], p["close_min"])
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
            lat=p["lat"], lon=p["lon"], cost_basis=cost_basis,
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
    hours_now = await _hours_for_stops(
        db, [st.poi_id for st in opt.stops if st.poi_id], spec.date.weekday())
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
        refetched = (
            await _refetch_leg_seconds(router.routing, points[prev_idx],
                                       points[this_idx], st.mode_from_prev,
                                       depart_at)
            if arc and st.mode_from_prev else None)
        stop_facts.append(StopFacts(
            seq=st.seq, poi_id=st.poi_id, name=st.name, category=st.category,
            lat=p.get("lat", 0.0), lon=p.get("lon", 0.0),
            arrive_min=st.arrive_min, depart_min=st.depart_min,
            cost_inr=st.cost_inr,
                        open_min=(None if (h := hours_now.get(st.poi_id)) is None
                      else (0 if h.is_24h else h.open_min)),
            close_min=(None if h is None
                       else (1440 if h.is_24h else h.close_min)),
            hours_confidence=float(h.confidence) if h is not None else 0.0,
            indoor=bool(p.get("indoor")),
            travel_s_from_prev=refetched,
            optimizer_travel_s_from_prev=arc.duration_s if arc else None,
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

    t0 = time.perf_counter()
    geometries = await _leg_geometries(router.routing, points, nodes,
                                       opt.stops, depart_at)
    t["geometry"] = int((time.perf_counter() - t0) * 1000)

    for stop in result.itinerary["stops"]:
        p = by_id.get(stop["poi_id"], {})
        for key in ("image_url", "image_credit", "image_license", "image_source_url"):
            stop[key] = p.get(key)
        stop["geometry"] = geometries.get(stop["seq"])
    result.itinerary["origin"] = {"name": spec.origin.name,
                                  "lat": spec.origin.lat,
                                  "lon": spec.origin.lon}

    if persist:
        itinerary_id = await _persist(
            db, spec, opt, report, weather, result.feasibility or {},
            ranked, user_id, result.relaxations_applied)
        result.itinerary["itinerary_id"] = itinerary_id

    result.timings_ms = t
    return result
# --------------------------------------------------------------------------
# Multi-day (Option B): independent days, no POI repeated across them.
# --------------------------------------------------------------------------

async def plan_trip(
    db: AsyncSession,
    spec: TripSpec,
    *,
    user_id=None,
    persist: bool = True,
) -> dict:
    """Plan each day as its own single-day itinerary.

    Days run SEQUENTIALLY because day N must exclude the POIs used on days
    1..N-1. At ~15 s per day, 3 days is ~45 s - the arc-building fix matters
    more here than anywhere.

    A failed day does not abort the trip; each day reports its own result so
    the UI can show a partial plan honestly.
    """
    used: list[int] = list(spec.constraints.avoid_poi_ids)
    days_out: list[dict] = []

    # One weather request for the whole trip, not one per day.
    windows = await get_windows(
        spec.origin.lat, spec.origin.lon, spec.day_dates,
        spec.start_minute // 60, spec.end_minute // 60)

    for number, day_date in enumerate(spec.day_dates, start=1):
        day_spec = spec.model_copy(update={
            "date": day_date,
            "days": 1,
            "constraints": spec.constraints.model_copy(
                update={"avoid_poi_ids": list(used)}),
        })

        try:
            r = await plan(db, day_spec, user_id=user_id, persist=persist,
                           weather=windows.get(day_date))
            entry = {"day": number, "date": day_date.isoformat(),
                     **r.to_dict()}
            if r.ok and r.itinerary:
                used += [s["poi_id"] for s in r.itinerary["stops"]
                         if s.get("poi_id")]
        except PlanningError as exc:
            entry = {"day": number, "date": day_date.isoformat(),
                     "ok": False,
                     "error": {"code": exc.code, "message": str(exc)}}

        days_out.append(entry)

    return {
        "ok": all(d.get("ok") for d in days_out),
        "days_planned": sum(1 for d in days_out if d.get("ok")),
        "days_requested": spec.days,
        "days": days_out,
    }
