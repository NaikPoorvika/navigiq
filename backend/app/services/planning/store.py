"""Itinerary persistence: immutable versions, what-if variants, restore.

Every change creates a new row; nothing is updated in place except the
itinerary's `current_version_id` pointer and a variant's status. Ownership is
enforced on every read and write: a signed-in user owns their plans; an
anonymous session owns plans created with its session id. User A can never
read or change user B's plans (tests/api/test_isolation.py).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.itinerary import (
    Itinerary, ItineraryStop, ItineraryVersion, PlanSnapshot, TripSpecRecord,
)


class PlanNotFound(Exception):
    code = "NOT_FOUND"


class PlanForbidden(Exception):
    code = "FORBIDDEN"


class PlanConflict(Exception):
    code = "CONFLICT"


@dataclass(frozen=True)
class Owner:
    user_id: uuid.UUID | None
    session_id: str | None

    def owns(self, itin: Itinerary) -> bool:
        if itin.user_id is not None:
            return self.user_id is not None and itin.user_id == self.user_id
        return self.session_id is not None and itin.session_id == self.session_id


async def _get_owned(db: AsyncSession, itinerary_id: int, owner: Owner,
                     *, for_update: bool = False) -> Itinerary:
    stmt = select(Itinerary).where(Itinerary.id == itinerary_id)
    if for_update:
        stmt = stmt.with_for_update()
    itin = (await db.execute(stmt)).scalar_one_or_none()
    if itin is None:
        raise PlanNotFound(f"plan {itinerary_id} not found")
    if not owner.owns(itin):
        # Existence is not revealed to non-owners.
        raise PlanNotFound(f"plan {itinerary_id} not found")
    return itin


async def _write_version(db: AsyncSession, itin: Itinerary, outcome, *, version_no: int | None,
                         kind: str, reason: str, parent_id: int | None,
                         change_operation: dict | None, label: str | None,
                         variant_status: str | None = None) -> ItineraryVersion:
    it = outcome.itinerary
    v = ItineraryVersion(
        itinerary_id=itin.id, version_no=version_no, kind=kind, variant_status=variant_status,
        parent_version_id=parent_id, reason=reason, change_operation=change_operation,
        label=label, tripspec_snapshot=outcome.spec.model_dump(mode="json"),
        itinerary={k: v for k, v in it.items() if k not in ("itinerary_id", "version_no")},
        total_cost_inr=it["summary"]["estimated_cost"]["typical"],
        total_duration_min=it["summary"]["span_minutes"], total_walk_m=0,
        validator_report=outcome.validator or {},
    )
    db.add(v)
    await db.flush()
    for st in it["stops"]:
        db.add(ItineraryStop(
            version_id=v.id, seq=st["seq"], poi_id=st["poi"]["id"],
            arrive_min=st["arrive_min"], depart_min=st["depart_min"],
            visit_minutes=st["visit_minutes"], cost_inr=st["estimated_cost"]["typical"],
            transition_buffer_min=st["transition_buffer_before_min"],
            notes={"reason_codes": st["reason_codes"]},
        ))
    db.add(PlanSnapshot(
        version_id=v.id, tripspec=outcome.spec.model_dump(mode="json"),
        candidate_poi_ids=outcome.candidate_ids, optimizer_params=outcome.optimizer,
        optimizer_status=outcome.optimizer.get("used", "unknown"),
        solve_ms=outcome.timings_ms.get("optimize"), weather=outcome.weather,
        feasibility_report=outcome.feasibility,
    ))
    return v


async def create(db: AsyncSession, outcome, owner: Owner) -> dict:
    spec_row = TripSpecRecord(user_id=owner.user_id, payload=outcome.spec.model_dump(mode="json"),
                              version=outcome.spec.version, source=outcome.spec.source)
    db.add(spec_row)
    await db.flush()
    itin = Itinerary(user_id=owner.user_id, session_id=None if owner.user_id else owner.session_id,
                     title=outcome.itinerary["title"], tripspec_id=spec_row.id,
                     status="draft", mode=outcome.spec.pace.value)
    db.add(itin)
    await db.flush()
    v = await _write_version(db, itin, outcome, version_no=1, kind="version", reason="initial",
                             parent_id=None, change_operation=None, label="Original plan")
    itin.current_version_id = v.id
    await db.commit()
    return {"itinerary_id": itin.id, "version_no": 1}


async def add_version(db: AsyncSession, itinerary_id: int, owner: Owner, outcome, *,
                      reason: str, change_operation: dict | None, label: str | None,
                      expected_version_no: int | None = None) -> dict:
    itin = await _get_owned(db, itinerary_id, owner, for_update=True)
    current = await db.get(ItineraryVersion, itin.current_version_id)
    if expected_version_no is not None and current is not None and \
            current.version_no != expected_version_no:
        raise PlanConflict(f"plan changed: current version is {current.version_no}, "
                           f"not {expected_version_no}")
    next_no = (await db.execute(text(
        "SELECT COALESCE(MAX(version_no), 0) + 1 FROM itinerary_versions "
        "WHERE itinerary_id = :i AND kind = 'version'"), {"i": itin.id})).scalar_one()
    v = await _write_version(db, itin, outcome, version_no=next_no, kind="version",
                             reason=reason, parent_id=current.id if current else None,
                             change_operation=change_operation, label=label)
    itin.current_version_id = v.id
    itin.title = outcome.itinerary["title"]
    await db.commit()
    return {"itinerary_id": itin.id, "version_no": next_no}


async def create_variant(db: AsyncSession, itinerary_id: int, owner: Owner, outcome, *,
                         change_operation: dict, label: str) -> dict:
    itin = await _get_owned(db, itinerary_id, owner)
    v = await _write_version(db, itin, outcome, version_no=None, kind="variant",
                             reason="what_if", parent_id=itin.current_version_id,
                             change_operation=change_operation, label=label,
                             variant_status="pending")
    await db.commit()
    return {"itinerary_id": itin.id, "variant_id": v.id}


async def get_variant(db: AsyncSession, itinerary_id: int, variant_id: int,
                      owner: Owner) -> ItineraryVersion:
    await _get_owned(db, itinerary_id, owner)
    v = await db.get(ItineraryVersion, variant_id)
    if v is None or v.itinerary_id != itinerary_id or v.kind != "variant":
        raise PlanNotFound("variant not found")
    return v


async def apply_variant(db: AsyncSession, itinerary_id: int, variant_id: int,
                        owner: Owner) -> dict:
    itin = await _get_owned(db, itinerary_id, owner, for_update=True)
    var = await get_variant(db, itinerary_id, variant_id, owner)
    if var.variant_status != "pending":
        raise PlanConflict(f"variant is already {var.variant_status}")
    if var.parent_version_id != itin.current_version_id:
        raise PlanConflict("the plan changed since this what-if was created")
    next_no = (await db.execute(text(
        "SELECT COALESCE(MAX(version_no), 0) + 1 FROM itinerary_versions "
        "WHERE itinerary_id = :i AND kind = 'version'"), {"i": itin.id})).scalar_one()
    v = ItineraryVersion(
        itinerary_id=itin.id, version_no=next_no, kind="version", reason="apply_variant",
        parent_version_id=itin.current_version_id,
        change_operation={"applied_variant": var.id, **(var.change_operation or {})},
        label=var.label, tripspec_snapshot=var.tripspec_snapshot, itinerary=var.itinerary,
        total_cost_inr=var.total_cost_inr, total_duration_min=var.total_duration_min,
        total_walk_m=0, validator_report=var.validator_report,
    )
    db.add(v)
    await db.flush()
    await db.execute(text("""
        INSERT INTO itinerary_stops (version_id, seq, poi_id, arrive_min, depart_min,
            visit_minutes, cost_inr, transition_buffer_min, notes)
        SELECT :new, seq, poi_id, arrive_min, depart_min, visit_minutes, cost_inr,
               transition_buffer_min, notes FROM itinerary_stops WHERE version_id = :old
    """), {"new": v.id, "old": var.id})
    var.variant_status = "applied"
    itin.current_version_id = v.id
    await db.commit()
    return {"itinerary_id": itin.id, "version_no": next_no}


async def reject_variant(db: AsyncSession, itinerary_id: int, variant_id: int,
                         owner: Owner) -> dict:
    var = await get_variant(db, itinerary_id, variant_id, owner)
    if var.variant_status != "pending":
        raise PlanConflict(f"variant is already {var.variant_status}")
    var.variant_status = "rejected"
    await db.commit()
    return {"itinerary_id": itinerary_id, "variant_id": variant_id, "status": "rejected"}


def _version_view(itin: Itinerary, v: ItineraryVersion) -> dict:
    return {
        "itinerary_id": itin.id, "version_no": v.version_no, "kind": v.kind,
        "variant_id": v.id if v.kind == "variant" else None,
        "variant_status": v.variant_status, "reason": v.reason, "label": v.label,
        "change_operation": v.change_operation,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "is_current": v.id == itin.current_version_id,
        "trip_spec": v.tripspec_snapshot, "itinerary": v.itinerary,
        "validator_report": v.validator_report,
    }


async def get_plan(db: AsyncSession, itinerary_id: int, owner: Owner,
                   version_no: int | None = None) -> dict:
    itin = await _get_owned(db, itinerary_id, owner)
    if version_no is None:
        v = await db.get(ItineraryVersion, itin.current_version_id)
    else:
        v = (await db.execute(select(ItineraryVersion).where(
            ItineraryVersion.itinerary_id == itin.id, ItineraryVersion.kind == "version",
            ItineraryVersion.version_no == version_no))).scalar_one_or_none()
    if v is None:
        raise PlanNotFound("version not found")
    view = _version_view(itin, v)
    view.update({"title": itin.title, "status": itin.status,
                 "created_at": itin.created_at.isoformat() if itin.created_at else None})
    return view


async def list_versions(db: AsyncSession, itinerary_id: int, owner: Owner,
                        include_variants: bool = True) -> list[dict]:
    itin = await _get_owned(db, itinerary_id, owner)
    rows = (await db.execute(select(ItineraryVersion).where(
        ItineraryVersion.itinerary_id == itin.id).order_by(ItineraryVersion.id))).scalars().all()
    out = []
    for v in rows:
        if v.kind == "variant" and not include_variants:
            continue
        view = _version_view(itin, v)
        view.pop("itinerary")
        view.pop("trip_spec")
        view["stop_count"] = len((v.itinerary or {}).get("stops", []))
        view["estimated_cost_typical"] = v.total_cost_inr
        out.append(view)
    return out


async def list_plans(db: AsyncSession, owner: Owner, limit: int = 50) -> list[dict]:
    if owner.user_id is not None:
        cond, params = "i.user_id = :u", {"u": owner.user_id}
    elif owner.session_id:
        cond, params = "i.user_id IS NULL AND i.session_id = :s", {"s": owner.session_id}
    else:
        return []
    rows = (await db.execute(text(f"""
        SELECT i.id, i.title, i.status, i.created_at, v.version_no, v.itinerary
        FROM itineraries i JOIN itinerary_versions v ON v.id = i.current_version_id
        WHERE {cond} ORDER BY i.id DESC LIMIT :lim
    """), {**params, "lim": limit})).all()
    return [{
        "itinerary_id": r.id, "title": r.title, "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "version_no": r.version_no, "date": (r.itinerary or {}).get("date"),
        "stop_count": len((r.itinerary or {}).get("stops", [])),
        "stops_preview": [s["poi"]["name"] for s in (r.itinerary or {}).get("stops", [])][:4],
        "estimated_cost": ((r.itinerary or {}).get("summary") or {}).get("estimated_cost"),
    } for r in rows]


async def set_status(db: AsyncSession, itinerary_id: int, owner: Owner, status: str) -> dict:
    itin = await _get_owned(db, itinerary_id, owner)
    if status not in ("draft", "saved", "abandoned"):
        raise PlanConflict(f"cannot set status {status!r}")
    itin.status = status
    await db.commit()
    return {"itinerary_id": itin.id, "status": status}


async def delete_plan(db: AsyncSession, itinerary_id: int, owner: Owner) -> None:
    itin = await _get_owned(db, itinerary_id, owner)
    itin.current_version_id = None
    await db.flush()
    await db.delete(itin)
    await db.commit()


async def claim_session_plans(db: AsyncSession, session_id: str, user_id: uuid.UUID) -> int:
    """After sign-in, adopt the plans this browser created anonymously."""
    res = await db.execute(text("""
        UPDATE itineraries SET user_id = :u, session_id = NULL
        WHERE user_id IS NULL AND session_id = :s
    """), {"u": user_id, "s": session_id})
    await db.commit()
    return res.rowcount or 0
