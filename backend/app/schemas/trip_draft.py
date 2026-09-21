"""NQ-029 contract - what the LLM fills in.

The model extracts WORDS, never facts:
  - places as names         "Indiranagar", not 12.97, 77.64
  - dates as phrases        "Saturday", not 2026-09-12
  - everything optional     missing fields become clarifying questions

draft_builder.py turns this into a TripSpec deterministically. If the model
emits coordinates or any other unknown field, it is IGNORED (extra="ignore"),
so a hallucinated lat/lon can never reach the planner (ADR-002).

Use TripDraft.model_json_schema() for schema-constrained decoding.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.tripspec import Category, PlanningMode, Priority, TransportMode


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

    # "today", "tomorrow", "Saturday", "next Sunday", "2026-09-12"
    date_phrase: Annotated[str, Field(max_length=40)] | None = None
    start_time_local: str | None = None          # "HH:MM"
    end_time_local: str | None = None
    days: Annotated[int, Field(ge=1, le=7)] | None = None

    budget_inr: Annotated[int, Field(ge=0, le=100_000)] | None = None
    party_size: Annotated[int, Field(ge=1, le=10)] | None = None

    interests: list[DraftInterest] = Field(default_factory=list)
    free_text_interests: list[str] = Field(default_factory=list)
    transport: list[TransportMode] = Field(default_factory=list)

    max_walking_km: Annotated[float, Field(ge=0, le=15)] | None = None
    vegetarian: bool | None = None
    mode: PlanningMode | None = None