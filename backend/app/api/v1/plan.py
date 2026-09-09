"""NQ-025 - Planning endpoints.

POST /plan                    full deterministic pipeline
POST /plan/preview-feasibility   cheap check, no optimization

NO LLM IN EITHER PATH. This is the permanent fallback when the model is
unavailable, and the endpoint the form-based UI calls (ADR-002).

Every failure mode maps to a stable error code. The frontend switches on the
code, never on the message text.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.tripspec import TripSpec
from app.services.planning.feasibility.engine import FeasibilityEngine
from app.services.planning.orchestrator import (
    NoCandidatesError,
    PlanningError,
    RoutingUnavailableError,
    plan as run_plan,
)
from app.services.planning.validators.semantic import validate_semantics

router = APIRouter()


def _error(code: str, message: str, http_status: int, **details):
    return HTTPException(
        status_code=http_status,
        detail={"error": {"code": code, "message": message,
                          "details": details or None}},
    )


@router.post("")
async def create_plan(
    spec: TripSpec,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Plan a trip. Returns an itinerary, or an explanation of why not.

    Failure codes:
      SEMANTIC_INVALID      the request contradicts itself
      INFEASIBLE            no arrangement fits; relaxations are offered
      NO_CANDIDATES         no POIs match a requested category
      ROUTING_UNAVAILABLE   OSRM is down. NO itinerary is returned rather
                            than one built on guessed distances
      VALIDATION_FAILED     the optimizer and validator disagree; nothing
                            is persisted
    """
    try:
        result = await run_plan(db, spec, persist=True)
    except NoCandidatesError as exc:
        raise _error("NO_CANDIDATES", str(exc), status.HTTP_404_NOT_FOUND)
    except RoutingUnavailableError as exc:
        raise _error(
            "ROUTING_UNAVAILABLE",
            "The routing engine is unavailable. No itinerary is returned "
            "rather than one built on estimated distances.",
            status.HTTP_503_SERVICE_UNAVAILABLE, reason=str(exc))
    except PlanningError as exc:
        raise _error(exc.code, str(exc), status.HTTP_400_BAD_REQUEST)

    if result.ok:
        return {
            "ok": True,
            "itinerary": result.itinerary,
            "weather": result.weather,
            "validator_report": result.validator_report,
            "relaxations_applied": result.relaxations_applied,
            "semantic_warnings": result.semantic_warnings,
            "timings_ms": result.timings_ms,
            "attribution": "(c) OpenStreetMap contributors, ODbL",
        }

    feas = result.feasibility or {}

    if feas.get("semantic_errors"):
        raise _error(
            "SEMANTIC_INVALID",
            "The request contradicts itself.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            errors=feas["semantic_errors"])

    if result.validator_report and not result.validator_report.get("valid"):
        # The optimizer produced something the validator rejects. One of them
        # is wrong, so nothing is persisted and nothing is returned as valid.
        raise _error(
            "VALIDATION_FAILED",
            "The itinerary failed independent validation and was discarded.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            findings=result.validator_report.get("findings"))

    # Infeasible. This is a normal outcome, not an error - the user asked for
    # something that does not fit, and the relaxations tell them what would.
    raise _error(
        "INFEASIBLE",
        "This trip does not fit the constraints given.",
        status.HTTP_409_CONFLICT,
        violated=feas.get("violated", []),
        bounds=feas.get("bounds", {}),
        suggested_relaxations=feas.get("suggested_relaxations", []),
        weather=result.weather)


@router.post("/preview-feasibility")
async def preview_feasibility(
    spec: TripSpec,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Cheap check with no optimization. Milliseconds rather than seconds -
    for a form that wants to warn before the user submits."""
    semantic = validate_semantics(spec)
    if not semantic.is_valid:
        raise _error(
            "SEMANTIC_INVALID", "The request contradicts itself.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            errors=[i.to_dict() for i in semantic.errors])

    from sqlalchemy import text
    rows = (await db.execute(
        text("SELECT key, default_visit_minutes FROM poi_categories"))).all()
    engine = FeasibilityEngine({r.key: r.default_visit_minutes for r in rows})

    # No POI search here - bounds only, using category defaults. A full check
    # happens inside POST /plan.
    report = engine.check(spec, {}, heavy_rain_expected=False)

    return {
        "feasibility": report.to_dict(),
        "semantic_warnings": [i.to_dict() for i in semantic.warnings],
        "note": "bounds only; POST /plan performs the full check",
    }