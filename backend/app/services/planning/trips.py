"""Multi-day trips (ADR-031).

A trip is up to seven single days, each planned by the unchanged single-day
engine: its own TripSpec, its own CP-SAT solve, its own independent
validation. The trip layer adds only what spans days:

  * a place is used at most once per trip. Places on other days are passed to
    the engine as transient exclusions (PlanDirectives.exclude_ids), never
    written into a day's spec, so changing one day frees its places again;
  * the budget is split evenly across the days, so each day stays within its
    share and the trip within the total;
  * required places are spread across the days in the order given;
  * a trip-level check re-verifies no place repeats and the total budget.

Each day stores the resolved spec it was planned from. A change to one day
("make day 2 cheaper") starts from that day's own constraints and re-plans
only that day; a change to the whole trip is applied to every day.

Stored shape (itinerary_versions.itinerary):
  {kind: "trip", title, date, end_date, day_count, start_time, end_time,
   days: [{day, date, title, localities, categories, start_time, end_time,
           summary, weather, map, notes, assumptions, optimizer, spec,
           validator}],
   stops: [every stop, in day order, with `day`, `day_seq` and a trip-wide
           `seq`],
   summary, transition_buffer_minutes, transition_note, weather, map,
   assumptions, notes, optimizer, attribution}

Single-day plans keep their existing shape; nothing that reads them changes.
"""
from __future__ import annotations

from datetime import date as date_type, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.taxonomy import category_catalog, is_valid_category
from app.schemas.tripspec import TripSpec
from app.services.planning.engine import PlanDirectives, PlanOutcome, explanation_facts, plan
from app.services.planning.modify import (
    CurrentStop, ModOp, Modification, ModificationError, apply_modifications, area_ref,
)
from app.services.planning.resolve import resolve_for_planning
from app.services.planning.validator.facts import load_facts, rules_for
from app.services.planning.validator.itinerary import PlannedStop, validate
from app.services.transport import get_transportation_provider

TRIP_KIND = "trip"
STOP_OPS = (ModOp.REMOVE_STOP, ModOp.REPLACE_STOP)
TRIP_RULES = ("DUPLICATE_ACROSS_DAYS", "TRIP_BUDGET_EXCEEDED")
_CITY_WIDE = {"bengaluru", "bangalore", "bengaluru urban", "bangalore urban"}
_WEEKDAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTH = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def is_trip_itinerary(itinerary: dict | None) -> bool:
    return bool(itinerary) and itinerary.get("kind") == TRIP_KIND


def day_label(d: date_type) -> str:
    return f"{_WEEKDAY[d.weekday()]} {d.day} {_MONTH[d.month - 1]}"


# --- splitting a trip into days --------------------------------------------------------------------

def split_budget(spec: TripSpec, days: int) -> dict[str, int | None]:
    """Even split, rounded down so the days never add up to more than the total."""
    return {
        "budget_total": spec.budget_total // days if spec.budget_total is not None else None,
        "budget_per_person": (spec.budget_per_person // days
                              if spec.budget_per_person is not None else None),
    }


def day_spec_for(spec: TripSpec, day: date_type, index: int, days: int) -> TripSpec:
    data = spec.model_dump()
    data.update(split_budget(spec, days))
    data.update(date=day, end_date=None, must_include_names=[],
                must_include_poi_ids=[p for j, p in enumerate(spec.must_include_poi_ids)
                                      if j % days == index])
    return TripSpec.model_validate(data)


def stops_of_day(itinerary: dict, day: int) -> list[dict]:
    """A day's stops with their day-local sequence numbers restored."""
    return [{**s, "seq": s["day_seq"]} for s in itinerary["stops"] if s["day"] == day]


def _day_title(stops: list[dict]) -> tuple[str, list[str], list[str]]:
    """Deterministic, grounded day title: the areas the stops are in."""
    localities = list(dict.fromkeys(s["poi"].get("locality") for s in stops
                                    if s["poi"].get("locality")
                                    and s["poi"]["locality"].lower() not in _CITY_WIDE))
    catalog = category_catalog()
    categories = list(dict.fromkeys(catalog[s["poi"]["category"]].name
                                    if s["poi"]["category"] in catalog
                                    else s["poi"]["category"].replace("_", " ").title()
                                    for s in stops))
    title = " & ".join(localities[:2]) or " & ".join(categories[:2]) or "Free day"
    return title, localities[:4], categories[:4]


def _day_entry(day_no: int, outcome: PlanOutcome) -> tuple[dict, list[dict]]:
    it = outcome.itinerary
    title, localities, categories = _day_title(it["stops"])
    entry = {
        "day": day_no, "date": it["date"], "title": title,
        "localities": localities, "categories": categories,
        "start_time": it["start_time"], "end_time": it["end_time"],
        "summary": it["summary"], "weather": it["weather"], "map": it["map"],
        "notes": it["notes"], "assumptions": it["assumptions"], "optimizer": it["optimizer"],
        "spec": outcome.spec.model_dump(mode="json"), "validator": outcome.validator,
    }
    return entry, it["stops"]


def trip_title(spec: TripSpec, days: int) -> str:
    bits = [category_catalog()[i].name for i in spec.interests if is_valid_category(i)][:2]
    return f"{days}-day {' & '.join(bits)} trip" if bits else f"{days} days around Bengaluru"


# --- assembling and checking a trip -----------------------------------------------------------------

def check_trip(days: list[dict], stops: list[dict], budget: int | None) -> dict:
    """Trip-level rules on top of each day's own validator report."""
    findings = []
    seen: dict[int, int] = {}
    for s in stops:
        pid = s["poi"]["id"]
        if pid in seen:
            findings.append({"rule": "DUPLICATE_ACROSS_DAYS", "stop_seq": s["seq"],
                             "message": f"{s['poi']['name']} is on day {seen[pid]} and day "
                                        f"{s['day']}", "expected": None, "actual": None})
        seen.setdefault(pid, s["day"])
    total = sum(s["estimated_cost"]["typical"] for s in stops)
    if budget is not None and total > budget:
        findings.append({"rule": "TRIP_BUDGET_EXCEEDED", "stop_seq": None,
                         "message": f"estimated ₹{total} exceeds the trip budget of ₹{budget}",
                         "expected": str(budget), "actual": str(total)})
    reports = [d.get("validator") or {} for d in days]
    return {
        "valid": not findings and all(r.get("valid") for r in reports),
        "rules_run": sorted({r for rep in reports for r in rep.get("rules_run", [])}
                            | set(TRIP_RULES)),
        "findings": findings + [{**f, "day": d["day"]} for d, rep in zip(days, reports)
                                for f in rep.get("findings", [])],
        "recomputed_cost_inr": sum(r.get("recomputed_cost_inr", 0) for r in reports),
        "days": [{"day": d["day"], "valid": bool(r.get("valid"))} for d, r in zip(days, reports)],
    }


def assemble_trip(spec: TripSpec, days: list[dict], day_stops: list[list[dict]],
                  assumptions: list[str], notes: list[str]) -> dict:
    stops = []
    for entry, dstops in zip(days, day_stops):
        for s in dstops:
            stops.append({**s, "seq": len(stops) + 1, "day": entry["day"], "day_seq": s["seq"]})
    total = {k: sum(s["estimated_cost"][k] for s in stops) for k in ("min", "typical", "max")}
    budget = spec.effective_budget_total
    lats = [s["poi"]["lat"] for s in stops]
    lons = [s["poi"]["lon"] for s in stops]
    party = spec.effective_party_size
    return {
        "kind": TRIP_KIND,
        "title": trip_title(spec, len(days)),
        "date": days[0]["date"], "end_date": days[-1]["date"], "day_count": len(days),
        "start_time": min(d["start_time"] for d in days),
        "end_time": max(d["end_time"] for d in days),
        "days": days,
        "stops": stops,
        "summary": {
            "stop_count": len(stops), "day_count": len(days),
            "estimated_cost": {**total, "currency": "INR", "basis": "estimate",
                               "excludes": "transportation"},
            "budget": budget,
            "within_budget": budget is None or total["typical"] <= budget,
            "max_may_exceed_budget": budget is not None and total["max"] > budget,
            "total_visit_minutes": sum(s["visit_minutes"] for s in stops),
            "span_minutes": sum(d["summary"]["span_minutes"] for d in days),
            "interests": list(spec.interests), "pace": spec.pace.value, "party_size": party,
            "party_type": spec.party_type.value if spec.party_type else None,
        },
        "transition_buffer_minutes": spec.transition_buffer_minutes,
        "transition_note": get_transportation_provider().note(),
        "weather": {"available": any((d.get("weather") or {}).get("available") for d in days),
                    "days": [{"day": d["day"], **(d.get("weather") or {})} for d in days]},
        "map": {"center": ({"lat": (min(lats) + max(lats)) / 2, "lon": (min(lons) + max(lons)) / 2}
                           if stops else None),
                "bbox": [min(lats), min(lons), max(lats), max(lons)] if stops else None},
        "assumptions": assumptions,
        "notes": notes,
        "optimizer": "trip",
        "attribution": "Place data © OpenStreetMap contributors (ODbL); descriptions from "
                       "Wikipedia (CC BY-SA) where noted.",
    }


def _scale_relaxations(feas: dict, days: int) -> dict:
    """A failed day's suggestions are per-day; a budget raise is restated for the trip."""
    out = []
    for r in feas.get("suggested_relaxations") or []:
        op = dict(r.get("operation") or {})
        if op.get("op") == "set_budget" and op.get("amount") is not None:
            op["amount"] = op["amount"] * days
            r = {**r, "description": f"Raise the trip budget to about ₹{op['amount']}"}
        out.append({**r, "operation": op} if r.get("operation") is not None else r)
    return {**feas, "suggested_relaxations": out}


def _failed(trip_spec: TripSpec, day_no: int, day_date: str, out: PlanOutcome, days: int,
            assumptions: list[str]) -> PlanOutcome:
    label = day_label(date_type.fromisoformat(day_date)) if day_date else f"day {day_no}"
    prefix = f"Day {day_no} ({label}): "
    feas = None
    if out.feasibility is not None:
        feas = _scale_relaxations(out.feasibility, days)
        feas = {**feas, "day": day_no,
                "message": prefix + (feas.get("message") or "nothing fits that day's constraints.")}
    semantic = out.semantic
    if semantic and semantic.get("errors"):
        semantic = {**semantic, "day": day_no, "errors": [
            {**e, "message": prefix + e["message"]} for e in semantic["errors"]]}
    return PlanOutcome(status=out.status, spec=trip_spec, assumptions=assumptions + out.assumptions,
                       semantic=semantic, feasibility=feas, validator=out.validator,
                       weather=out.weather, warnings=out.warnings,
                       notes=[prefix + n for n in out.notes], optimizer=out.optimizer,
                       timings_ms=out.timings_ms)


async def plan_days(db: AsyncSession, trip_spec: TripSpec, specs: list[TripSpec], *,
                    now: datetime, directives: dict[int, PlanDirectives] | None = None,
                    keep: dict[int, tuple[dict, list[dict]]] | None = None,
                    current_ids: dict[int, list[int]] | None = None,
                    assumptions: list[str] | None = None,
                    notes: list[str] | None = None) -> PlanOutcome:
    """Plan every day not in `keep`, in order, and assemble the trip.

    `keep` holds unchanged days (entry, stops). `current_ids` holds the places
    each day has now: a re-planned day avoids every OTHER day's places, using
    the new ones for days already re-planned and the current ones otherwise.
    """
    directives = directives or {}
    keep = keep or {}
    current_ids = current_ids or {}
    assumptions = list(assumptions or [])
    n = len(specs)
    entries: list[dict] = []
    all_stops: list[list[dict]] = []
    new_ids: dict[int, list[int]] = {}
    candidate_ids: list[int] = []
    optimizer_days = []
    timings: dict[str, int] = {}
    for i, day_spec in enumerate(specs):
        if i in keep:
            entry, stops = keep[i]
            entries.append(entry)
            all_stops.append(stops)
            new_ids[i] = [s["poi"]["id"] for s in stops]
            optimizer_days.append({"day": i + 1, "used": "kept"})
            continue
        others = [pid for j in range(n) if j != i
                  for pid in new_ids.get(j, current_ids.get(j, []))]
        d = directives.get(i) or PlanDirectives()
        d = PlanDirectives(**{**d.__dict__,
                              "exclude_ids": sorted(set(d.exclude_ids) | set(others)),
                              "preferred_ids": [p for p in d.preferred_ids if p not in others]})
        out = await plan(db, day_spec, now=now, directives=d)
        if not out.ok:
            return _failed(trip_spec, i + 1, day_spec.date.isoformat() if day_spec.date else "",
                           out, n, assumptions)
        entry, stops = _day_entry(i + 1, out)
        entries.append(entry)
        all_stops.append(stops)
        new_ids[i] = [s["poi"]["id"] for s in stops]
        candidate_ids += out.candidate_ids
        optimizer_days.append({"day": i + 1, **out.optimizer})
        for k, v in out.timings_ms.items():
            timings[k] = timings.get(k, 0) + v

    itinerary = assemble_trip(trip_spec, entries, all_stops, assumptions, list(notes or []))
    report = check_trip(entries, itinerary["stops"], trip_spec.effective_budget_total)
    outcome = PlanOutcome(status="ok" if report["valid"] else "validation_failed",
                          spec=trip_spec, itinerary=itinerary if report["valid"] else None,
                          assumptions=assumptions, validator=report, weather=itinerary["weather"],
                          notes=list(notes or []),
                          candidates_considered=len(set(candidate_ids)),
                          optimizer={"used": "trip", "days": optimizer_days},
                          timings_ms=timings, candidate_ids=list(dict.fromkeys(candidate_ids)))
    if outcome.ok:
        outcome.fact_block = explanation_facts(itinerary)
    return outcome


async def plan_trip(db: AsyncSession, spec: TripSpec, *, now: datetime,
                    persist_fn=None) -> PlanOutcome:
    """Plan a multi-day TripSpec (spec.is_trip) day by day."""
    dates = spec.trip_dates()
    n = len(dates)
    assumptions: list[str] = []
    # Day one may be moved to tomorrow when it's too late today; the trip moves with it.
    first = resolve_for_planning(spec.model_copy(update={"end_date": None}), now).spec.date
    if first != dates[0]:
        shift = first - dates[0]
        dates = [d + shift for d in dates]
        assumptions.append("It's late today, so the trip starts tomorrow")
    assumptions.append(f"{n} days: {day_label(dates[0])} – {day_label(dates[-1])}")
    if spec.effective_budget_total is not None:
        per_day = spec.effective_budget_total // n
        assumptions.append(f"Budget split evenly: about ₹{per_day} per day")
    if len(spec.must_include_poi_ids) > 1:
        assumptions.append("Required places are spread across the days")
    specs = [day_spec_for(spec, d, i, n) for i, d in enumerate(dates)]
    # The trip spec keeps a concrete daily window so a later "start an hour
    # later" has something to shift; a typical (non-first) day's window.
    template = spec.model_copy(update={"date": dates[0], "end_date": dates[-1]})
    if template.start_time is None or template.end_time is None:
        typical = resolve_for_planning(specs[-1], now).spec
        template = template.model_copy(update={"start_time": typical.start_time,
                                               "end_time": typical.end_time})
    template = TripSpec.model_validate(template.model_dump())
    outcome = await plan_days(db, template, specs, now=now, assumptions=assumptions)
    if outcome.ok and persist_fn is not None:
        outcome.itinerary.update(await persist_fn(outcome))
    return outcome


# --- changing a trip ----------------------------------------------------------------------------------

def _scope(mods: list[Modification], itinerary: dict) -> list[tuple[int | None, Modification]]:
    """Which day each operation applies to (None = every day).

    A stop is named either by `day` + that day's `target_seq`, or by the
    trip-wide `target_seq` alone. An added place goes to the requested day, or
    to the day with the fewest stops.
    """
    days = itinerary["days"]
    stops = itinerary["stops"]
    n = len(days)
    out: list[tuple[int | None, Modification]] = []
    for m in mods:
        day = m.day
        if day is not None and not 1 <= day <= n:
            raise ModificationError(f"this trip has {n} days, so there is no day {day}")
        if m.op in STOP_OPS:
            if day is None:
                st = next((s for s in stops if s["seq"] == m.target_seq), None)
                if st is None:
                    raise ModificationError(f"there is no stop {m.target_seq}")
                day, local = st["day"], st["day_seq"]
            else:
                local = m.target_seq
            m = m.model_copy(update={"target_seq": local})
        elif m.op == ModOp.ADD_POI:
            where = next((s for s in stops if s["poi"]["id"] == m.poi_id), None)
            if where is not None:
                raise ModificationError(f"{where['poi']['name']} is already on day {where['day']}")
            if day is None:
                count = {d["day"]: 0 for d in days}
                for s in stops:
                    count[s["day"]] += 1
                day = min(count, key=lambda k: (count[k], k))
        out.append((day, m.model_copy(update={"day": None})))
    return out


def _per_day(m: Modification, days: int) -> Modification:
    if m.op == ModOp.SET_BUDGET:
        return m.model_copy(update={"amount": m.amount // days})
    return m


async def modify_trip(db: AsyncSession, view: dict, mods: list[Modification], *,
                      now: datetime, resolve_location) -> tuple[PlanOutcome, list[str]]:
    """Apply closed operations to a stored trip. Unaffected days are kept as they are."""
    itinerary = view["itinerary"]
    trip_spec = TripSpec.model_validate(view["trip_spec"])
    days = itinerary["days"]
    n = len(days)
    scoped = _scope(mods, itinerary)
    trip_level = [m for d, m in scoped if d is None]

    summary: list[str] = []
    area_cache: dict[str, object] = {}

    async def with_area(spec: TripSpec, area: str | None) -> TripSpec:
        if not area:
            return spec
        if area not in area_cache:
            area_cache[area] = await resolve_location(db, area)
        resolved = area_cache[area]
        if resolved is None:
            raise ModificationError(f"couldn't find '{area}' on the map")
        return spec.model_copy(update={"anchor_area": area_ref(resolved)})

    new_template = trip_spec
    if trip_level:
        applied = apply_modifications(trip_spec, [], trip_level)
        new_template = await with_area(applied.spec, applied.area_to_resolve)
        summary += applied.summary

    specs: list[TripSpec] = []
    directives: dict[int, PlanDirectives] = {}
    keep: dict[int, tuple[dict, list[dict]]] = {}
    current_ids: dict[int, list[int]] = {}
    day_budget_changed = False
    for i, entry in enumerate(days):
        day_no = i + 1
        dstops = stops_of_day(itinerary, day_no)
        current_ids[i] = [s["poi"]["id"] for s in dstops]
        day_spec = TripSpec.model_validate(entry["spec"])
        own = [m for d, m in scoped if d == day_no]
        day_mods = own + [_per_day(m, n) for m in trip_level]
        if not day_mods:
            specs.append(day_spec)
            keep[i] = (entry, dstops)
            continue
        current = [CurrentStop(s["seq"], s["poi"]["id"], s["poi"]["name"], s["poi"]["category"])
                   for s in dstops]
        applied = apply_modifications(day_spec, current, day_mods)
        specs.append(await with_area(applied.spec, applied.area_to_resolve))
        directives[i] = applied.directives
        if own:
            own_summary = apply_modifications(day_spec, current, own).summary
            summary += [f"Day {day_no}: {s[0].lower() + s[1:]}" for s in own_summary]
            day_budget_changed |= any(m.op == ModOp.SET_BUDGET for m in own)

    if day_budget_changed and all(s.effective_budget_total is not None for s in specs):
        new_template = new_template.model_copy(update={
            "budget_total": sum(s.effective_budget_total for s in specs),
            "budget_per_person": None})
    new_template = TripSpec.model_validate(
        {**new_template.model_dump(), "source": "modification"})
    outcome = await plan_days(db, new_template, specs, now=now, directives=directives, keep=keep,
                              current_ids=current_ids, assumptions=itinerary.get("assumptions"),
                              notes=[])
    return outcome, summary


async def revalidate_trip(db: AsyncSession, itinerary: dict) -> dict:
    """Re-run every day's independent validator against today's data (restore)."""
    days = []
    for entry in itinerary["days"]:
        spec = TripSpec.model_validate(entry["spec"])
        dstops = stops_of_day(itinerary, entry["day"])
        planned = [PlannedStop(s["seq"], s["poi"]["id"], s["arrive_min"], s["depart_min"])
                   for s in dstops]
        facts = await load_facts(db, [p.poi_id for p in planned], spec.date)
        geo_hop = 25.0 if any(s["poi"].get("recommended_as_primary_destination")
                              for s in dstops) else 12.0
        report = validate(planned, rules_for(spec, max_hop_km=geo_hop), facts)
        days.append({**entry, "validator": report.to_dict()})
    budget = None
    if all(TripSpec.model_validate(d["spec"]).effective_budget_total is not None for d in days):
        budget = sum(TripSpec.model_validate(d["spec"]).effective_budget_total for d in days)
    return check_trip(days, itinerary["stops"], budget)


def compare_days(a: dict, b: dict) -> list[dict]:
    """Per-day differences between two trips (or a trip and a single day)."""
    def by_day(it: dict) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {}
        for s in it.get("stops", []):
            out.setdefault(s.get("day", 1), []).append(s)
        return out
    da, db_ = by_day(a), by_day(b)
    rows = []
    for day in sorted(set(da) | set(db_)):
        sa = {s["poi"]["id"]: s for s in da.get(day, [])}
        sb = {s["poi"]["id"]: s for s in db_.get(day, [])}
        ca = sum(s["estimated_cost"]["typical"] for s in sa.values())
        cb = sum(s["estimated_cost"]["typical"] for s in sb.values())
        added = [sb[i]["poi"]["name"] for i in sb if i not in sa]
        removed = [sa[i]["poi"]["name"] for i in sa if i not in sb]
        retimed = [sb[i]["poi"]["name"] for i in sb if i in sa and (
            sa[i]["arrive"] != sb[i]["arrive"] or sa[i]["depart"] != sb[i]["depart"])]
        rows.append({"day": day, "added": added, "removed": removed, "retimed": retimed,
                     "changed": bool(added or removed or retimed),
                     "estimated_cost": {"current": ca, "variant": cb, "delta": cb - ca}})
    return rows
