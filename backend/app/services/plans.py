"""Plan lifecycle: create, modify, what-if, apply/reject, restore, compare.

Every path runs the deterministic engine and the independent validator. A
modification creates a new version; a what-if creates a PENDING variant that
leaves the current plan untouched until the user applies it (section 60).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.nlu.timeparse import now_ist
from app.schemas.tripspec import TripSpec, migrate_tripspec
from app.services.planning import store, trips
from app.services.planning.engine import PlanOutcome, plan
from app.services.planning.modify import (
    Applied, CurrentStop, Modification, ModificationError, apply_modifications, area_ref,
)
from app.services.planning.store import Owner, PlanConflict
from app.services.planning.validator.facts import load_facts, rules_for
from app.services.planning.validator.itinerary import PlannedStop, validate
from app.services.poi.search import resolve_location

MAX_PLAN_VARIANTS = 3


async def resolve_areas(db: AsyncSession, spec: TripSpec, area_names: list[str]) -> tuple[TripSpec, list[str]]:
    """Resolve area names to gazetteer coordinates. Unknown names are reported,
    never guessed."""
    notes: list[str] = []
    data = spec.model_dump()
    for name in area_names[:1]:
        resolved = await resolve_location(db, name)
        if resolved is None:
            notes.append(f"Couldn't find '{name}' on the map, so the plan isn't limited to it")
            continue
        data["anchor_area"] = area_ref(resolved).model_dump()
    return TripSpec.model_validate(data), notes


async def create_plan(db: AsyncSession, spec: TripSpec, owner: Owner, *,
                      now: datetime | None = None, persist: bool = True) -> PlanOutcome:
    async def persist_fn(outcome: PlanOutcome) -> dict:
        return await store.create(db, outcome, owner)
    fn = persist_fn if persist else None
    if spec.is_trip:
        return await trips.plan_trip(db, spec, now=now or now_ist(), persist_fn=fn)
    return await plan(db, spec, now=now or now_ist(), persist_fn=fn)


def _current_stops(view: dict) -> list[CurrentStop]:
    return [CurrentStop(s["seq"], s["poi"]["id"], s["poi"]["name"], s["poi"]["category"])
            for s in (view.get("itinerary") or {}).get("stops", [])]


async def modify_plan(db: AsyncSession, itinerary_id: int, owner: Owner,
                      mods: list[Modification], *, hypothetical: bool = False,
                      expected_version_no: int | None = None,
                      now: datetime | None = None) -> dict:
    view = await store.get_plan(db, itinerary_id, owner)
    if trips.is_trip_itinerary(view["itinerary"]):
        outcome, summary = await trips.modify_trip(db, view, mods, now=now or now_ist(),
                                                   resolve_location=resolve_location)
    else:
        if any(m.day not in (None, 1) for m in mods):
            raise ModificationError("this plan is a single day")
        spec = migrate_tripspec(view["trip_spec"])
        stops = _current_stops(view)
        applied: Applied = apply_modifications(spec, stops, mods)
        new_spec = applied.spec
        notes: list[str] = []
        if applied.area_to_resolve:
            new_spec, notes = await resolve_areas(db, new_spec, [applied.area_to_resolve])
        outcome = await plan(db, new_spec, now=now or now_ist(), directives=applied.directives)
        outcome.notes = notes + outcome.notes
        summary = applied.summary
    op_record = {"operations": [m.model_dump(mode="json", exclude_none=True) for m in mods],
                 "summary": summary}
    result = {"status": outcome.status, "outcome": outcome, "summary": summary,
              "previous": view}
    if not outcome.ok:
        return result
    label = "; ".join(summary) or "Modified"
    if hypothetical:
        pending = [v for v in await store.list_versions(db, itinerary_id, owner)
                   if v["kind"] == "variant" and v["variant_status"] == "pending"]
        if len(pending) >= MAX_PLAN_VARIANTS:
            raise PlanConflict(f"at most {MAX_PLAN_VARIANTS} open what-if variants; apply or "
                               "discard one first")
        ids = await store.create_variant(db, itinerary_id, owner, outcome,
                                         change_operation=op_record, label=label)
        outcome.itinerary.update({"itinerary_id": itinerary_id, "variant_id": ids["variant_id"]})
        result["variant_id"] = ids["variant_id"]
        result["comparison"] = compare_itineraries(view["itinerary"], outcome.itinerary)
    else:
        ids = await store.add_version(db, itinerary_id, owner, outcome, reason="modification",
                                      change_operation=op_record, label=label,
                                      expected_version_no=expected_version_no)
        outcome.itinerary.update(ids)
        result["version_no"] = ids["version_no"]
        result["comparison"] = compare_itineraries(view["itinerary"], outcome.itinerary)
    return result


async def restore_version(db: AsyncSession, itinerary_id: int, version_no: int,
                          owner: Owner) -> dict:
    """Make an old version current again - as a NEW version, re-validated
    against today's data. Old rows are never mutated."""
    old = await store.get_plan(db, itinerary_id, owner, version_no=version_no)
    current = await store.get_plan(db, itinerary_id, owner)
    if old["version_no"] == current["version_no"]:
        raise PlanConflict("that version is already current")
    spec = migrate_tripspec(old["trip_spec"])
    it = old["itinerary"]
    if trips.is_trip_itinerary(it):
        report_dict = await trips.revalidate_trip(db, it)
    else:
        planned = [PlannedStop(s["seq"], s["poi"]["id"], s["arrive_min"], s["depart_min"])
                   for s in it["stops"]]
        facts = await load_facts(db, [p.poi_id for p in planned], spec.date)
        geo_hop = 25.0 if any(s["poi"].get("recommended_as_primary_destination")
                              for s in it["stops"]) else 12.0
        report_dict = validate(planned, rules_for(spec, max_hop_km=geo_hop), facts).to_dict()
    if not report_dict["valid"]:
        return {"status": "validation_failed", "validator_report": report_dict}
    outcome = PlanOutcome(status="ok", spec=spec, itinerary=it, validator=report_dict,
                          optimizer={"used": "restore"}, weather=it.get("weather"))
    ids = await store.add_version(db, itinerary_id, owner, outcome, reason="restore",
                                  change_operation={"restored_version": version_no},
                                  label=f"Restored version {version_no}")
    return {"status": "ok", **ids, "itinerary": {**it, **ids}}


def compare_itineraries(a: dict, b: dict) -> dict:
    """Deterministic diff between two itineraries (current vs variant/version)."""
    sa = {s["poi"]["id"]: s for s in a.get("stops", [])}
    sb = {s["poi"]["id"]: s for s in b.get("stops", [])}
    added = [sb[i]["poi"]["name"] for i in sb if i not in sa]
    removed = [sa[i]["poi"]["name"] for i in sa if i not in sb]
    retimed = [sb[i]["poi"]["name"] for i in sb if i in sa and (
        sa[i]["arrive"] != sb[i]["arrive"] or sa[i]["depart"] != sb[i]["depart"])]
    ca = a["summary"]["estimated_cost"]["typical"]
    cb = b["summary"]["estimated_cost"]["typical"]
    days = trips.compare_days(a, b) if (trips.is_trip_itinerary(a)
                                        or trips.is_trip_itinerary(b)) else None
    return {
        "days": days,
        "changed_days": [d["day"] for d in days if d["changed"]] if days else None,
        "added": added, "removed": removed, "retimed": retimed,
        "kept": [sb[i]["poi"]["name"] for i in sb if i in sa],
        "stop_count": {"current": len(sa), "variant": len(sb)},
        "estimated_cost": {"current": ca, "variant": cb, "delta": cb - ca},
        "window": {"current": [a["start_time"], a["end_time"]],
                   "variant": [b["start_time"], b["end_time"]]},
        "span_minutes": {"current": a["summary"]["span_minutes"],
                         "variant": b["summary"]["span_minutes"]},
    }


async def compare_versions(db: AsyncSession, itinerary_id: int, owner: Owner, a: int,
                           b: int) -> dict:
    va = await store.get_plan(db, itinerary_id, owner, version_no=a)
    vb = await store.get_plan(db, itinerary_id, owner, version_no=b)
    return {"a": a, "b": b, "comparison": compare_itineraries(va["itinerary"], vb["itinerary"])}


__all__ = ["ModificationError", "MAX_PLAN_VARIANTS", "compare_itineraries", "compare_versions",
           "create_plan", "modify_plan", "resolve_areas", "restore_version"]
