"""Structured, UI-aware assistant responses (section 73).

The frontend switches on `ui.type`, never on the text. Text is for people;
`data` carries the verified structures the UI renders (POI cards, the
itinerary, sources), so nothing the user relies on exists only in prose.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

UIType = Literal["message", "discovery", "poi_list", "poi_details", "comparison",
                 "knowledge_answer", "clarification", "trip_spec", "itinerary",
                 "itinerary_comparison", "feasibility_error", "error"]


class Suggestion(BaseModel):
    label: str
    message: str


class AssistantResponse(BaseModel):
    conversation_id: str
    intent: str
    text: str
    data: dict[str, Any] = Field(default_factory=dict)
    ui: dict[str, Any] = Field(default_factory=lambda: {"type": "message"})
    sources: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    trace_id: str
    llm_used: bool = False
    llm_available: bool = True


MOOD_CHIPS = [
    Suggestion(label="Surprise me", message="Surprise me"),
    Suggestion(label="Food", message="Somewhere good to eat"),
    Suggestion(label="Nature", message="Something with nature"),
    Suggestion(label="Something active", message="Something active"),
    Suggestion(label="Chill", message="Something chill and relaxing"),
    Suggestion(label="Explore", message="Somewhere interesting to explore"),
    Suggestion(label="Date idea", message="A date idea"),
    Suggestion(label="Cheap", message="Cheap things to do"),
]

AFTER_RESULTS = [
    Suggestion(label="Show something different", message="Show me something different"),
    Suggestion(label="Plan my day", message="Plan my day around these"),
    Suggestion(label="Hidden gems", message="Any hidden gems?"),
]

TIME_CHIPS = [
    Suggestion(label="10 AM – 6 PM", message="10 AM to 6 PM"),
    Suggestion(label="Afternoon", message="afternoon"),
    Suggestion(label="Evening", message="evening"),
    Suggestion(label="You decide", message="You decide"),
]

ERROR_MESSAGES = {
    "NO_CANDIDATES": "I couldn't find places that match all of that. Try widening the area, "
                     "budget or interests.",
    "PLAN_INFEASIBLE": "That combination isn't feasible with the current constraints.",
    "LLM_UNAVAILABLE": "My language assistant is offline right now, so I'm using structured "
                       "search. Explore, search, place details and the plan form all still work.",
    "WEATHER_UNAVAILABLE": "Weather is unavailable right now, so these ideas aren't weather-"
                           "adjusted.",
    "DATABASE_UNAVAILABLE": "I can't reach NavigIQ's place data right now. Please try again "
                            "in a moment.",
    "AGENT_LIMIT": "That request needed more steps than I allow myself. Could you break it "
                   "into a simpler question?",
    "INTERNAL": "Something went wrong on my side. Please try again.",
}
