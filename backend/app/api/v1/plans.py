"""Plan endpoints. NO LLM in any of them: this is the structured planning
path that keeps working when the model is down (section 54). Every returned
itinerary has passed the independent validator (section 96).

Error codes are stable; the frontend switches on the code, never the text:
  SEMANTIC_INVALID   the request contradicts itself (422)
  INFEASIBLE         nothing fits; relaxations are offered (409)
  VALIDATION_FAILED  no candidate plan passed the validator; nothing shown (422)
  NOT_FOUND          no such plan for this owner (404) - also for other users' plans
  CONFLICT           the plan changed underneath the request (409)
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import api_error, get_db, owner
from app.schemas.tripspec import TripSpec
from app.services import plans as plan_service
from app.services.planning import store
from app.services.planning.modify import Modification, ModificationError
from app.services.planning.store import Owner, PlanConflict, PlanNotFound

router = APIRouter()
HTTP_422 = 422   # Starlette renamed the constant; the number is the contract


def _require_owner(who: Owner) -> None:
    if who.user_id is None and not who.session_id:
        raise api_error(status.HTTP_400_BAD_REQUEST, "SESSION_REQUIRED",
                        "send X-NavigIQ-Session or sign in to create plans")


def _outcome_response(outcome) -> dict:
    d = outcome.to_dict()
    if outcome.status == "ok":
        return {"ok": True, **d}
    if outcome.status == "invalid_request":
        raise api_error(HTTP_422, "SEMANTIC_INVALID",
                        "The request contradicts itself.",
                        errors=(outcome.semantic or {}).get("errors"), trip_spec=d["trip_spec"])
    if outcome.status == "validation_failed":
        raise api_error(HTTP_422, "VALIDATION_FAILED",
                        "No plan passed independent validation, so none is shown.",
                        validator_report=outcome.validator)
    feas = outcome.feasibility or {}
    raise api_error(status.HTTP_409_CONFLICT, "INFEASIBLE",
                    feas.get("message") or "That combination isn't feasible with the current "
                                           "constraints.",
                    feasibility=feas, trip_spec=d["trip_spec"], weather=d["weather"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(spec: TripSpec, db: AsyncSession = Depends(get_db),
                 who: Owner = Depends(owner)) -> dict:
    _require_owner(who)
    spec = spec.model_copy(update={"source": "form"}) if spec.source == "llm" else spec
    outcome = await plan_service.create_plan(db, spec, who)
    return _outcome_response(outcome)


@router.post("/preview")
async def preview(spec: TripSpec, db: AsyncSession = Depends(get_db)) -> dict:
    """Plan without saving - used by the form's live preview."""
    outcome = await plan_service.create_plan(db, spec, Owner(None, None), persist=False)
    return _outcome_response(outcome)


@router.get("")
async def list_plans(db: AsyncSession = Depends(get_db), who: Owner = Depends(owner)) -> dict:
    return {"plans": await store.list_plans(db, who)}


@router.get("/{itinerary_id}")
async def get_plan(itinerary_id: int, version: Annotated[int | None, Query(ge=1)] = None,
                   db: AsyncSession = Depends(get_db), who: Owner = Depends(owner)) -> dict:
    try:
        return await store.get_plan(db, itinerary_id, who, version_no=version)
    except PlanNotFound:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "plan not found")


@router.get("/{itinerary_id}/versions")
async def versions(itinerary_id: int, db: AsyncSession = Depends(get_db),
                   who: Owner = Depends(owner)) -> dict:
    try:
        return {"versions": await store.list_versions(db, itinerary_id, who)}
    except PlanNotFound:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "plan not found")


class ModifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operations: list[dict] = Field(min_length=1, max_length=3)
    expected_version_no: int | None = Field(default=None, ge=1)


def _mods(ops: list[dict]) -> list[Modification]:
    try:
        return [Modification.model_validate(o) for o in ops]
    except ValidationError as exc:
        raise api_error(HTTP_422, "INVALID_MODIFICATION",
                        "; ".join(e["msg"] for e in exc.errors()[:3]))


async def _modify(itinerary_id: int, body: ModifyBody, db, who, hypothetical: bool) -> dict:
    try:
        res = await plan_service.modify_plan(db, itinerary_id, who, _mods(body.operations),
                                             hypothetical=hypothetical,
                                             expected_version_no=body.expected_version_no)
    except PlanNotFound:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "plan not found")
    except PlanConflict as exc:
        raise api_error(status.HTTP_409_CONFLICT, "CONFLICT", str(exc))
    except ModificationError as exc:
        raise api_error(HTTP_422, "INVALID_MODIFICATION", str(exc))
    outcome = _outcome_response(res["outcome"])
    return {"summary": res["summary"], "version_no": res.get("version_no"),
            "variant_id": res.get("variant_id"), "comparison": res.get("comparison"),
            "previous_itinerary": res["previous"]["itinerary"], **outcome}


@router.post("/{itinerary_id}/modify")
async def modify(itinerary_id: int, body: ModifyBody, db: AsyncSession = Depends(get_db),
                 who: Owner = Depends(owner)) -> dict:
    return await _modify(itinerary_id, body, db, who, hypothetical=False)


@router.post("/{itinerary_id}/what-if")
async def what_if(itinerary_id: int, body: ModifyBody, db: AsyncSession = Depends(get_db),
                  who: Owner = Depends(owner)) -> dict:
    return await _modify(itinerary_id, body, db, who, hypothetical=True)


@router.post("/{itinerary_id}/variants/{variant_id}/apply")
async def apply_variant(itinerary_id: int, variant_id: int, db: AsyncSession = Depends(get_db),
                        who: Owner = Depends(owner)) -> dict:
    try:
        ids = await store.apply_variant(db, itinerary_id, variant_id, who)
        return await store.get_plan(db, itinerary_id, who, version_no=ids["version_no"])
    except PlanNotFound:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "variant not found")
    except PlanConflict as exc:
        raise api_error(status.HTTP_409_CONFLICT, "CONFLICT", str(exc))


@router.post("/{itinerary_id}/variants/{variant_id}/reject")
async def reject_variant(itinerary_id: int, variant_id: int, db: AsyncSession = Depends(get_db),
                         who: Owner = Depends(owner)) -> dict:
    try:
        return await store.reject_variant(db, itinerary_id, variant_id, who)
    except PlanNotFound:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "variant not found")
    except PlanConflict as exc:
        raise api_error(status.HTTP_409_CONFLICT, "CONFLICT", str(exc))


@router.post("/{itinerary_id}/restore/{version_no}")
async def restore(itinerary_id: int, version_no: int, db: AsyncSession = Depends(get_db),
                  who: Owner = Depends(owner)) -> dict:
    try:
        res = await plan_service.restore_version(db, itinerary_id, version_no, who)
    except PlanNotFound:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "plan or version not found")
    except PlanConflict as exc:
        raise api_error(status.HTTP_409_CONFLICT, "CONFLICT", str(exc))
    if res["status"] != "ok":
        raise api_error(HTTP_422, "VALIDATION_FAILED",
                        "That version no longer passes today's checks.",
                        validator_report=res.get("validator_report"))
    return res


@router.get("/{itinerary_id}/compare")
async def compare(itinerary_id: int, a: Annotated[int, Query(ge=1)], b: Annotated[int, Query(ge=1)],
                  db: AsyncSession = Depends(get_db), who: Owner = Depends(owner)) -> dict:
    try:
        return await plan_service.compare_versions(db, itinerary_id, who, a, b)
    except PlanNotFound:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "plan or version not found")


@router.post("/{itinerary_id}/save")
async def save(itinerary_id: int, db: AsyncSession = Depends(get_db),
               who: Owner = Depends(owner)) -> dict:
    try:
        return await store.set_status(db, itinerary_id, who, "saved")
    except PlanNotFound:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "plan not found")


@router.delete("/{itinerary_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(itinerary_id: int, db: AsyncSession = Depends(get_db),
                 who: Owner = Depends(owner)) -> None:
    try:
        await store.delete_plan(db, itinerary_id, who)
    except PlanNotFound:
        raise api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "plan not found")
