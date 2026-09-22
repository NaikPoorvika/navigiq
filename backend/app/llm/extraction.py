"""NQ-029 - natural language -> TripDraft.

    "cafe and a park near Koramangala tomorrow"
                    |
              LLMGateway (NQ-028, qwen3:14b, schema-constrained)
                    |
              TripDraft (NQ-029 prep / ADR-015)

This module is the ONLY place a user's free text becomes structured trip
fields. It is deliberately small and deliberately incapable:

  - it does not resolve places to coordinates   (draft_builder / ADR-011)
  - it does not resolve date phrases to dates   (resolve_date_phrase)
  - it does not plan, rank, route or optimise   (NQ-022 .. NQ-025)
  - it does not touch Postgres, OSRM, OR-Tools or any external API
  - it does not repair what the model returned

That last one matters most. If the model emits prose, a markdown fence, a
missing brace or a field that violates the schema, this raises
`TripDraftExtractionFailed` rather than salvaging it. Silent repair hides
prompt regressions: a stripped fence still counts as a pass, so the day the
model starts fencing every response, nothing is measured and nothing is
fixed. An honest failure is the whole point of the gateway's typed errors
(ADR-002), and the eval in `ai/evals/nq029/` measures how often it happens.

Safety comes from the contract, not from trust: `TripDraft` has no lat/lon
field anywhere and `extra="ignore"` at every level, so a model that invents
coordinates has them dropped on validation (see test_extraction.py). The
model's output is never authoritative - it is a draft the user can correct
and the deterministic layer must still resolve.

PRIVACY: user requests and raw model output are never logged. Only sizes,
timings, outcomes and field NAMES appear in the log stream.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

from app.schemas.trip_draft import TripDraft
from app.schemas.tripspec import Category, PlanningMode, TransportMode

from .errors import LLMError
from .gateway import LLMGateway
from .types import ChatMessage, Generation

logger = structlog.get_logger("app.llm.extraction")

# Prompts are versioned in the repo and live under backend/ rather than the
# repo-level ai/ directory because the backend image's Docker build context
# is backend/ only - a prompt outside it would not ship with the service.
#
# Versions are kept side by side, never overwritten, so any past evaluation
# can be re-run against the same prompt (the model itself is not
# bit-reproducible across sessions - see ai/evals/nq030/README.md):
#   v1  NQ-029 baseline (ai/evals/nq029/)
#   v2  NQ-030 restraint-focused prompt (ai/evals/nq030/) - the default
PROMPT_VERSION = "v2"
PROMPT_VERSIONS = ("v1", "v2")
PROMPT_DIR = Path(__file__).parent / "prompts"

# A TripDraft is a handful of short fields; schema-constrained decoding
# bounds the shape but not the length. 512 leaves ample room for a maximal
# draft (10 free-text interests at 80 chars is itself only ~200 tokens) while
# still capping a model that ignores the instruction to stop. Hitting it
# raises LLMTruncated from the gateway - a truncated draft is never parsed.
EXTRACTION_MAX_TOKENS = 512

# Extraction is a deterministic-as-possible operation: same request, same
# draft. Temperature is fixed at 0.0 and not exposed as a parameter; the
# seed is exposed only so an eval can vary it to measure stability.
EXTRACTION_TEMPERATURE = 0.0
DEFAULT_SEED = 0

# Requests longer than this are rejected before reaching the model rather
# than silently overrunning OLLAMA_NUM_CTX (8192 by default), where the
# system prompt would be the part that falls out of the window.
MAX_USER_REQUEST_CHARS = 2000

# Failure reasons, stable enough for callers and the eval to count.
REASON_INVALID_JSON = "invalid_json"
REASON_NOT_AN_OBJECT = "not_an_object"
REASON_SCHEMA_INVALID = "schema_invalid"


class TripDraftExtractionFailed(LLMError):
    """The model answered, but the answer was not a usable TripDraft.

    Distinct from the gateway's transport-level failures: the call itself
    succeeded, so this is a prompt/model quality signal, not an outage.
    `reason` says which stage rejected it and `details` carries field paths
    and error types only - never model text and never user text.
    """

    code = "TRIPDRAFT_EXTRACTION_FAILED"
    retryable = False

    def __init__(self, message: str, *, reason: str,
                 model: str | None = None, attempts: int | None = None,
                 details: Sequence[str] = ()) -> None:
        super().__init__(message, model=model, attempts=attempts)
        self.reason = reason
        self.details = tuple(details)


@dataclass(frozen=True, slots=True)
class DraftExtraction:
    """A validated draft plus the provenance an eval and an API need."""

    draft: TripDraft
    model: str
    prompt_version: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    attempts: int


@lru_cache(maxsize=None)
def render_prompt(version: str = PROMPT_VERSION) -> str:
    """The system prompt, with the closed enums injected from the code.

    The enum values are never typed into the markdown. A category added to
    `Category` without the prompt being updated would otherwise be a value
    the model is never told about - silent prompt/code drift that no test
    would catch. Here it simply appears.
    """
    path = PROMPT_DIR / f"tripdraft_extraction_{version}.md"
    try:
        template = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:  # pragma: no cover - packaging error
        raise FileNotFoundError(
            f"extraction prompt {version!r} is missing at {path}") from exc
    return template.format(
        categories=", ".join(c.value for c in Category),
        transport_modes=", ".join(t.value for t in TransportMode),
        planning_modes=", ".join(m.value for m in PlanningMode),
        # The order constrained decoding forces keys into (NQ-030). Taken
        # from the schema actually sent, so it cannot drift from it. v1
        # has no placeholder for it; str.format ignores unused names.
        field_order=", ".join(draft_json_schema()["properties"]),
    )


@lru_cache(maxsize=1)
def draft_json_schema() -> dict[str, Any]:
    """TripDraft's JSON schema, for Ollama's constrained decoding."""
    return TripDraft.model_json_schema()


async def extract_trip_draft(
    user_request: str,
    *,
    gateway: LLMGateway,
    prompt_version: str = PROMPT_VERSION,
    max_tokens: int = EXTRACTION_MAX_TOKENS,
    seed: int | None = DEFAULT_SEED,
) -> DraftExtraction:
    """Extract a validated TripDraft from one user message.

    Raises `TripDraftExtractionFailed` if the model's answer is not a valid
    draft, or any other `LLMError` if the call itself failed. Never returns
    a partially-repaired or guessed draft.
    """
    text = _checked_request(user_request)

    messages = (
        ChatMessage(role="system", content=render_prompt(prompt_version)),
        ChatMessage(role="user", content=text),
    )

    # Failures from the gateway (unavailable, timeout, truncated, empty,
    # malformed) propagate as-is: they are already typed and already logged
    # by the gateway, and re-wrapping them would hide which one happened.
    generation = await gateway.generate(
        messages,
        max_tokens=max_tokens,
        temperature=EXTRACTION_TEMPERATURE,
        seed=seed,
        json_schema=draft_json_schema(),
    )

    payload = _parse_object(generation)
    draft = _validate(payload, generation)

    logger.info(
        "llm.extraction.completed",
        prompt_version=prompt_version,
        model=generation.model,
        request_chars=len(text),
        latency_ms=round(generation.latency_ms, 1),
        attempts=generation.attempts,
        # Which fields were populated, never what they contain.
        fields=sorted(draft.model_dump(exclude_none=True,
                                       exclude_defaults=True)),
    )
    return DraftExtraction(
        draft=draft,
        model=generation.model,
        prompt_version=prompt_version,
        latency_ms=generation.latency_ms,
        prompt_tokens=generation.prompt_tokens,
        completion_tokens=generation.completion_tokens,
        attempts=generation.attempts,
    )


def _checked_request(user_request: str) -> str:
    if not isinstance(user_request, str):
        raise TypeError(
            f"user_request must be str, got {type(user_request).__name__}")
    text = user_request.strip()
    if not text:
        raise ValueError("user_request must not be empty")
    if len(text) > MAX_USER_REQUEST_CHARS:
        raise ValueError(
            f"user_request is {len(text)} characters, over the "
            f"{MAX_USER_REQUEST_CHARS} limit")
    return text


def _parse_object(generation: Generation) -> dict[str, Any]:
    """Model text -> JSON object. No fence stripping, no bracket hunting."""
    try:
        payload = json.loads(generation.text)
    except json.JSONDecodeError as exc:
        details = (f"pos:{exc.pos}",)
        _log_failure(REASON_INVALID_JSON, generation, details=details)
        raise TripDraftExtractionFailed(
            "model response was not valid JSON",
            reason=REASON_INVALID_JSON, model=generation.model,
            attempts=generation.attempts, details=details,
        ) from exc

    if not isinstance(payload, dict):
        kind = type(payload).__name__
        _log_failure(REASON_NOT_AN_OBJECT, generation, details=(kind,))
        raise TripDraftExtractionFailed(
            f"model response was JSON {kind}, not an object",
            reason=REASON_NOT_AN_OBJECT, model=generation.model,
            attempts=generation.attempts, details=(kind,),
        )
    return payload


def _validate(payload: dict[str, Any], generation: Generation) -> TripDraft:
    try:
        return TripDraft.model_validate(payload)
    except ValidationError as exc:
        # Field paths and error types only. Pydantic's rendered messages
        # quote the offending value, which is model output derived from the
        # user's text, so they are never logged or returned.
        details = tuple(
            _path(err["loc"]) + ":" + str(err["type"])
            for err in exc.errors()[:5]
        )
        _log_failure(REASON_SCHEMA_INVALID, generation, details=details)
        raise TripDraftExtractionFailed(
            "model response did not satisfy the TripDraft schema",
            reason=REASON_SCHEMA_INVALID, model=generation.model,
            attempts=generation.attempts, details=details,
        ) from exc


def _path(loc: Sequence[Any]) -> str:
    return ".".join(str(part) for part in loc) or "(root)"


def _log_failure(reason: str, generation: Generation, *,
                 details: Sequence[str]) -> None:
    logger.warning(
        "llm.extraction.failed",
        reason=reason,
        model=generation.model,
        details=list(details),
        response_chars=len(generation.text),
        completion_tokens=generation.completion_tokens,
    )
