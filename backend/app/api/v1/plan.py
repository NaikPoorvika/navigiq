"""NQ-025 - Planning endpoints.

POST /plan                    full deterministic pipeline
POST /plan/preview-feasibility   cheap check, no optimization

NO LLM IN EITHER PATH. This is the permanent fallback when the model is
unavailable, and the endpoint the form-based UI calls (ADR-002).

Every failure mode maps to a stable error code. The frontend switches on the
code, never on the message text.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.trip_draft import TripDraft
from app.services.planning.draft_builder import build_tripspec
from app.services.planning.orchestrator import plan_trip
from app.api.deps import get_db, get_llm_gateway
from app.llm import LLMError, LLMGateway, LLMTimeout, LLMUnavailable
from app.llm.extraction import (
    MAX_USER_REQUEST_CHARS,
    TripDraftExtractionFailed,
    extract_trip_draft,
)
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
@router.post("/trip")
async def create_trip(
    spec: TripSpec,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Multi-day. Each day planned independently, no POI repeated.
    Takes ~15 s PER DAY."""
    result = await plan_trip(db, spec, persist=True)
    return {**result, "attribution": "(c) OpenStreetMap contributors, ODbL"}


@router.post("/draft")
async def plan_from_draft(
    draft: TripDraft,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """For NQ-029. The LLM's TripDraft goes in; either clarifying questions
    or a planned trip come out.

    needs_clarification=true is a normal outcome, not an error: ask the user
    the question(s) and resubmit the draft with the answer filled in.

    needs_clarification is always present and explicit (true or false) so a
    caller can branch on it directly rather than on the presence of
    unrelated fields such as `days` or `tripspec`. No existing consumer of
    this endpoint was found in the repository when this discriminator was
    added, so this is additive rather than a breaking change.
    """
    built = await build_tripspec(db, draft)
    if built.needs_clarification:
        return built.to_dict()

    result = await plan_trip(db, built.tripspec, persist=True)
    return {
        "needs_clarification": False,
        **result,
        "assumptions": built.assumptions,
        "tripspec": built.tripspec.model_dump(mode="json"),
        "attribution": "(c) OpenStreetMap contributors, ODbL",
    }


class ExtractRequest(BaseModel):
    """One natural-language trip request. Bounded here so an oversized body
    is a 422 from the schema rather than a truncated model context."""

    text: Annotated[str, Field(min_length=1, max_length=MAX_USER_REQUEST_CHARS)]


@router.post("/extract")
async def extract_draft(
    body: ExtractRequest,
    gateway: LLMGateway = Depends(get_llm_gateway),
) -> dict:
    """NQ-029. Natural language in, a validated TripDraft out. No planning.

    Extraction is separated from planning on purpose. The draft is returned
    for the user to SEE and CORRECT (the editable chips of NQ-033) before
    anything is planned, because the model's reading of a sentence is a
    proposal, not a fact (ADR-002). Send the confirmed draft to
    `POST /plan/draft` to actually plan it; that endpoint is unchanged.

    Nothing here is authoritative: places stay names, dates stay phrases,
    and any coordinate the model invents is dropped by the TripDraft schema
    before this returns.

    Failure codes:
      EXTRACTION_FAILED     the model answered, but not with a valid draft.
                            `reason` is invalid_json / not_an_object /
                            schema_invalid; `fields` names the offending
                            fields. No model or user text is echoed back
      LLM_UNAVAILABLE       no model server reachable (503)
      LLM_TIMEOUT           the model did not answer in time (504)
      LLM_ERROR             any other gateway failure, including a response
                            that was empty or hit the token cap (502)
    """
    try:
        extraction = await extract_trip_draft(body.text, gateway=gateway)
    except TripDraftExtractionFailed as exc:
        raise _error("EXTRACTION_FAILED", exc.message,
                     status.HTTP_422_UNPROCESSABLE_ENTITY,
                     reason=exc.reason, fields=list(exc.details))
    except LLMUnavailable as exc:
        raise _error("LLM_UNAVAILABLE", exc.message,
                     status.HTTP_503_SERVICE_UNAVAILABLE)
    except LLMTimeout as exc:
        raise _error("LLM_TIMEOUT", exc.message,
                     status.HTTP_504_GATEWAY_TIMEOUT)
    except LLMError as exc:
        raise _error("LLM_ERROR", exc.message, status.HTTP_502_BAD_GATEWAY,
                     llm_code=exc.code)

    return {
        "draft": extraction.draft.model_dump(mode="json"),
        "model": extraction.model,
        "prompt_version": extraction.prompt_version,
        "latency_ms": round(extraction.latency_ms, 1),
    }