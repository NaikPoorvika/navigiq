"""Structured, bounded conversation state (section 61).

Stored as JSON on conversations.state. Every list has a hard cap so state
cannot grow without limit over a long conversation (soak concern, section
122); older entries fall off the front.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

MAX_LAST_POIS = 12
MAX_SHOWN_HISTORY = 80
MAX_TURNS_SUMMARY = 8


class LastPOI(BaseModel):
    id: int
    name: str
    category: str


class PendingClarification(BaseModel):
    kind: str                     # time_budget | mood | which_place | which_stop | intent
    question: str
    options: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class ConversationState(BaseModel):
    active_itinerary_id: int | None = None
    active_version_no: int | None = None
    active_stops: list[LastPOI] = Field(default_factory=list)       # seq order
    pending_variant_id: int | None = None
    last_pois: list[LastPOI] = Field(default_factory=list)          # most recent results, in order
    last_focus_poi: LastPOI | None = None                           # "it", "that place"
    last_collection: str | None = None
    last_comparison_ids: list[int] = Field(default_factory=list)
    last_request: dict[str, Any] | None = None                      # for "something different"
    shown_history: list[int] = Field(default_factory=list)
    current_trip_spec: dict[str, Any] | None = None
    pending_clarification: PendingClarification | None = None
    clarification_count: int = 0
    turn_count: int = 0
    recent_intents: list[str] = Field(default_factory=list)
    summary: str = ""

    def remember_results(self, pois: list[LastPOI], request: dict[str, Any] | None) -> None:
        self.last_pois = pois[:MAX_LAST_POIS]
        if pois:
            self.last_focus_poi = pois[0] if len(pois) == 1 else self.last_focus_poi
        if request is not None:
            self.last_request = request
        ids = [p.id for p in pois]
        self.shown_history = (self.shown_history + [i for i in ids
                                                    if i not in self.shown_history])[
            -MAX_SHOWN_HISTORY:]

    def focus(self, poi: LastPOI) -> None:
        self.last_focus_poi = poi

    def note_turn(self, intent: str) -> None:
        self.turn_count += 1
        self.recent_intents = (self.recent_intents + [intent])[-MAX_TURNS_SUMMARY:]
        self.summary = (f"{self.turn_count} turns; recent: {', '.join(self.recent_intents)}; "
                        f"plan: {self.active_itinerary_id or 'none'}")

    def set_plan(self, itinerary_id: int, version_no: int, stops: list[LastPOI],
                 spec: dict[str, Any]) -> None:
        self.active_itinerary_id = itinerary_id
        self.active_version_no = version_no
        self.active_stops = stops
        self.current_trip_spec = spec
        self.pending_variant_id = None
