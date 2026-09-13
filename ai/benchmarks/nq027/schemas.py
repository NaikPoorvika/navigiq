"""Output contracts for the structured task classes.

TripSpec is IMPORTED from the backend, never copied. A benchmark that
validates against its own transcription of the schema measures agreement with
the transcription, and drifts silently the moment NQ-021 changes. Importing
the real model means a schema change breaks this benchmark loudly, which is
the correct behaviour.

The other contracts here describe LLM outputs that do not exist in the
backend yet (NQ-028 onwards). They are defined at the shape the deterministic
layer will require, so what is measured now is what will be needed later.
"""
from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas.tripspec import (  # noqa: E402  - path set above
    Category,
    TripSpec,
)

__all__ = [
    "Category", "TripSpec", "Intent", "IntentClassification", "ToolName",
    "ToolCall", "ClarifyQuestion", "TOOL_REGISTRY", "tripspec_schema",
]


class Intent(str, Enum):
    """What the user is asking for. Routes to a handler, so it is closed."""
    PLAN_TRIP = "plan_trip"
    MODIFY_TRIP = "modify_trip"
    EXPLAIN_ITINERARY = "explain_itinerary"
    REROUTE = "reroute"
    POI_QUESTION = "poi_question"
    OUT_OF_SCOPE = "out_of_scope"


class IntentClassification(BaseModel):
    intent: Intent
    # Advisory only, exactly as TripSpec.confidence is. Never gates anything.
    confidence: float = Field(ge=0, le=1)


class ToolName(str, Enum):
    """The typed tool registry of ADR-004.

    Closed by construction: a model cannot call a tool that is not a member,
    because a non-member fails enum validation before anything is executed.
    Each maps to a deterministic service that already exists in the backend.
    """
    SEARCH_POIS = "search_pois"                # services/poi/search.py
    GET_POI_DETAIL = "get_poi_detail"          # services/poi/search.py
    ROUTE_BETWEEN = "route_between"            # services/routing/service.py
    GET_WEATHER_WINDOW = "get_weather_window"  # services/weather/client.py
    CHECK_FEASIBILITY = "check_feasibility"    # planning/feasibility/engine.py
    CREATE_PLAN = "create_plan"                # planning/orchestrator.py
    VALIDATE_ITINERARY = "validate_itinerary"  # planning/validator/itinerary.py


# Human-readable registry handed to the model in the tool_select prompt.
TOOL_REGISTRY: dict[str, dict] = {
    ToolName.SEARCH_POIS.value: {
        "description": "Find points of interest near a coordinate under hard "
                       "filters. Use for 'what is near', 'find me a cafe'.",
        "arguments": {
            "lat": "float, required", "lon": "float, required",
            "radius_km": "float, optional, default 3",
            "categories": "list of category keys, optional",
            "limit": "int, optional, default 20",
        },
    },
    ToolName.GET_POI_DETAIL.value: {
        "description": "Full record for ONE known POI id, including opening "
                       "hours. Use when the user asks about a specific place "
                       "already identified by id.",
        "arguments": {"poi_id": "int, required"},
    },
    ToolName.ROUTE_BETWEEN.value: {
        "description": "Authoritative distance and duration between two "
                       "coordinates. Use for 'how long does it take'.",
        "arguments": {
            "from_lat": "float", "from_lon": "float",
            "to_lat": "float", "to_lon": "float",
            "mode": "one of walking, auto, cab, own_car, bike",
        },
    },
    ToolName.GET_WEATHER_WINDOW.value: {
        "description": "Forecast for a date and hour range at a coordinate. "
                       "Use when weather affects the plan.",
        "arguments": {
            "lat": "float", "lon": "float", "date": "YYYY-MM-DD",
            "start_hour": "int 0-23", "end_hour": "int 0-23",
        },
    },
    ToolName.CHECK_FEASIBILITY.value: {
        "description": "Can this trip exist at all, without optimising it. "
                       "Cheap pre-check before planning.",
        "arguments": {"tripspec": "a TripSpec object"},
    },
    ToolName.CREATE_PLAN.value: {
        "description": "Run the full deterministic planner and return an "
                       "itinerary. The expensive one; use when the user "
                       "actually wants a plan built.",
        "arguments": {"tripspec": "a TripSpec object"},
    },
    ToolName.VALIDATE_ITINERARY.value: {
        "description": "Re-check an existing itinerary against its "
                       "constraints. Use after a modification.",
        "arguments": {"itinerary_id": "int, required"},
    },
}


class ToolCall(BaseModel):
    tool: ToolName
    arguments: dict = Field(default_factory=dict)
    reason: str = Field(default="", max_length=400)


class ClarifyQuestion(BaseModel):
    """One question, not an interrogation.

    max_length is a contract, not a style note: the clarification UI shows a
    single line, and a model that writes a paragraph has failed the task even
    though the text is well-formed.
    """
    question: str = Field(min_length=5, max_length=300)
    missing_fields: list[str] = Field(min_length=1, max_length=5)


def tripspec_schema() -> dict:
    """TripSpec as a JSON Schema for Ollama structured output.

    Ollama resolves $defs/$ref, verified against this exact schema before the
    harness was written, so the nested enums survive the grammar conversion.
    """
    return TripSpec.model_json_schema()
