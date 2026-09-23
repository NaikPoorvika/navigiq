"""NQ-029 contract - what the LLM fills in.

The model extracts WORDS, never facts:
  - places as names         "Indiranagar", not 12.97, 77.64
  - dates as phrases        "Saturday", not 2026-09-12
  - everything optional     missing fields become clarifying questions

draft_builder.py turns this into a TripSpec deterministically. If the model
emits coordinates or any other unknown field, it is IGNORED (extra="ignore"),
so a hallucinated lat/lon can never reach the planner (ADR-002).

Use TripDraft.model_json_schema() for schema-constrained decoding.

HARDENING (pre-NQ-029, see ADR-019): two fields are stricter here than the
same-named fields on TripSpec, deliberately.

  start_time_local / end_time_local   TripSpec's own `_hhmm` parser accepts
      "9:00" (no leading zero). Here it must not - the LLM is being asked to
      always emit exactly "HH:MM", and accepting a looser format at this
      layer would let a malformed time slip past the schema and fail late,
      inside draft_builder's TripSpec construction, as a generic Pydantic
      error instead of a field-specific clarification. A missing time
      (None) is untouched - draft_builder still owns picking a default.

  free_text_interests   previously unbounded here even though TripSpec
      bounds the same field (10 entries, 80 chars). Matched to TripSpec's
      limit for the same reason: a draft that passes this schema but fails
      TripSpec construction downstream turns into the same kind of late,
      generic failure instead of an early, clear one.

date_phrase is NOT given a matching runtime constraint. The vocabulary
`resolve_date_phrase()` (draft_builder.py) actually accepts is documented on
the field below so a prompt can be written against it, but this schema does
not duplicate that resolution logic or reject phrases outside it - phrases
it cannot parse become a clarifying question at that layer, same as today.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.tripspec import Category, PlanningMode, Priority, TransportMode

# Exactly "HH:MM", 24-hour, zero-padded: hour 00-23, minute 00-59. No am/pm,
# no single-digit hour, no free text. Matches what the LLM is asked to emit;
# see the module docstring for why this is stricter than TripSpec's own
# time parser. Declared with Field(pattern=...) rather than a hand-written
# validator so the constraint is also visible in model_json_schema() and
# can guide schema-constrained decoding (NQ-028), not just reject after the
# fact.
_STRICT_HHMM_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"

# Mirrors TripSpec._bounded_free_text exactly (tripspec.py), but declared
# with Field(max_length=...) at both the list and item level rather than a
# hand-written validator, for the same reason as the time pattern above:
# TripSpec's equivalent validator does not show up in ITS json schema, but
# TripDraft's does need to, so the bound can inform constrained decoding
# rather than only reject after the fact.
#
# Kept as a free-text OVERFLOW for concepts that do not map to the closed
# Category enum, not a substitute for normal category extraction - an LLM
# that dumps many/long phrases here instead of mapping them is doing the
# extraction task wrong, and this bound makes that fail fast and visibly
# rather than silently downstream in draft_builder.
FREE_TEXT_MAX_ITEMS = 10
FREE_TEXT_MAX_LENGTH = 80


class PlaceRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: Annotated[str, Field(min_length=1, max_length=200)]


class DraftInterest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    category: Category
    count: Annotated[int, Field(ge=1, le=5)] = 1
    priority: Priority = Priority.SHOULD


class TripDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    origin: PlaceRef | None = None
    destination: PlaceRef | None = None

    # Resolved deterministically by resolve_date_phrase() in draft_builder.py
    # - never here, never by the model. Documented vocabulary (as of this
    # writing; re-check resolve_date_phrase() before relying on this list,
    # it is not enforced at this layer):
    #   "today" / "tonight"
    #   "tomorrow"
    #   "day after tomorrow" / "day after"
    #   "weekend" / "this weekend"                    -> the coming Saturday
    #   a weekday name or 3-letter abbreviation,
    #     case-insensitive, optionally prefixed with
    #     "this " / "next " / "coming "                -> "next X" always
    #                                                      skips today even
    #                                                      if today is X
    #   an ISO date "YYYY-MM-DD"
    # Anything else resolves to None and becomes a clarifying question.
    date_phrase: Annotated[str, Field(max_length=40)] | None = None

    start_time_local: Annotated[
        str, Field(pattern=_STRICT_HHMM_PATTERN)] | None = None
    end_time_local: Annotated[
        str, Field(pattern=_STRICT_HHMM_PATTERN)] | None = None
    days: Annotated[int, Field(ge=1, le=7)] | None = None

    budget_inr: Annotated[int, Field(ge=0, le=100_000)] | None = None
    party_size: Annotated[int, Field(ge=1, le=10)] | None = None

    interests: list[DraftInterest] = Field(default_factory=list)
    free_text_interests: Annotated[
        list[Annotated[str, Field(max_length=FREE_TEXT_MAX_LENGTH)]],
        Field(max_length=FREE_TEXT_MAX_ITEMS),
    ] = Field(default_factory=list)
    transport: list[TransportMode] = Field(default_factory=list)

    max_walking_km: Annotated[float, Field(ge=0, le=15)] | None = None
    vegetarian: bool | None = None
    mode: PlanningMode | None = None