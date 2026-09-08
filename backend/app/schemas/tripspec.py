"""NQ-021 - TripSpec: the canonical planning contract.

The ONLY accepted input to the planning engine, whether it came from the
form (NQ-026), from language extraction (NQ-029), from a modification
(NQ-045) or from a what-if (NQ-046).

THREE VALIDATION TIERS, none of which the LLM can bypass because validation
runs on the deserialized object, not in a prompt:
  1. schema      - types, enums, ranges, bbox            (here, Pydantic)
  2. semantic    - cross-field consistency               (validators/semantic.py)
  3. feasibility - can this trip exist at all            (NQ-022)

CATEGORY IS A CLOSED ENUM. Leaving it open is the door through which a
model invents categories. Unmapped phrases go to free_text_interests and
are resolved by similarity later, never by inventing an enum value.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TRIPSPEC_VERSION: Literal["1.0"] = "1.0"

# Bounding box.
#
# WIDENED from the draft 12.6-13.3 / 77.3-77.9 to match the actual OSM
# extract (lat 11.906-13.716, lon 76.708-78.865) and to admit regional
# destinations. Nandi Hills sits at 13.37 and would have failed the draft
# guard while appearing in landmark_names and in the demo scenario.
#
# The guard exists to catch a model hallucinating coordinates in another
# country. It is NOT a trip-radius control - that is radius_km and the
# NQ-022 feasibility engine.
BBOX_MIN_LAT, BBOX_MAX_LAT = 11.9, 13.75
BBOX_MIN_LON, BBOX_MAX_LON = 76.7, 78.9


class Priority(str, Enum):
    MUST = "must"
    SHOULD = "should"
    NICE = "nice_to_have"


class TransportMode(str, Enum):
    WALKING = "walking"
    AUTO = "auto"
    CAB = "cab"
    OWN_CAR = "own_car"
    BIKE = "bike"


class Category(str, Enum):
    """Closed. Must match poi_categories.key exactly - seeded in NQ-012."""
    CAFE = "cafe"
    RESTAURANT = "restaurant"
    STREET_FOOD = "street_food"
    BAR = "bar"
    DESSERT = "dessert"
    HISTORICAL = "historical"
    TEMPLE = "temple"
    MUSEUM = "museum"
    ART_GALLERY = "art_gallery"
    PARK = "park"
    LAKE = "lake"
    VIEWPOINT = "viewpoint"
    SUNSET = "sunset"
    NATURE = "nature"
    SHOPPING = "shopping"
    MARKET = "market"
    BOOKSTORE = "bookstore"
    NIGHTLIFE = "nightlife"
    ENTERTAINMENT = "entertainment"
    LANDMARK = "landmark"


class PlanningMode(str, Enum):
    BALANCED = "balanced"
    QUICK = "quick"
    RELAXED = "relaxed"


class GeoPoint(BaseModel):
    name: str | None = None
    lat: Annotated[float, Field(ge=BBOX_MIN_LAT, le=BBOX_MAX_LAT)]
    lon: Annotated[float, Field(ge=BBOX_MIN_LON, le=BBOX_MAX_LON)]


class Interest(BaseModel):
    category: Category
    count: Annotated[int, Field(ge=1, le=5)] = 1
    priority: Priority = Priority.SHOULD


class Constraints(BaseModel):
    vegetarian: bool = False
    vegan: bool = False
    halal: bool = False
    avoid_categories: list[Category] = Field(default_factory=list)
    avoid_poi_ids: list[int] = Field(default_factory=list)
    max_walking_km: Annotated[float, Field(ge=0, le=15)] = 3.0
    max_stops: Annotated[int, Field(ge=1, le=8)] | None = None
    accessibility_required: bool = False
    avoid_crowds: bool = False
    indoor_preferred: bool = False    # set deterministically from the forecast
    meal_required: bool = True


def _hhmm(value: str) -> int:
    """'HH:MM' to minutes since midnight."""
    try:
        h, m = value.split(":")
        h, m = int(h), int(m)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"time must be HH:MM, got {value!r}") from exc
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"time out of range: {value!r}")
    return h * 60 + m


class TripSpec(BaseModel):
    version: Literal["1.0"] = TRIPSPEC_VERSION

    origin: GeoPoint
    destination: GeoPoint | None = None      # None means round trip / open end

    date: date
    start_time_local: str                    # Asia/Kolkata
    end_time_local: str

    budget_inr: Annotated[int, Field(ge=0, le=100_000)] | None = None
    party_size: Annotated[int, Field(ge=1, le=10)] = 1

    interests: Annotated[list[Interest], Field(min_length=1, max_length=8)]
    free_text_interests: list[str] = Field(default_factory=list)

    transport: Annotated[list[TransportMode], Field(min_length=1)] = Field(
        default_factory=lambda: [TransportMode.WALKING, TransportMode.AUTO])

    constraints: Constraints = Field(default_factory=Constraints)
    mode: PlanningMode = PlanningMode.BALANCED

    language: str = "en"
    source: Literal["llm", "form", "modification", "what_if"] = "form"
    # The model's own confidence. Advisory only - never gates a decision.
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None

    # --- derived ---------------------------------------------------------

    @property
    def start_minute(self) -> int:
        return _hhmm(self.start_time_local)

    @property
    def end_minute(self) -> int:
        return _hhmm(self.end_time_local)

    @property
    def window_minutes(self) -> int:
        return self.end_minute - self.start_minute

    @property
    def start_datetime(self) -> datetime:
        return datetime.combine(self.date, datetime.min.time()) + timedelta(
            minutes=self.start_minute)

    @property
    def must_interests(self) -> list[Interest]:
        return [i for i in self.interests if i.priority == Priority.MUST]

    @property
    def total_requested_stops(self) -> int:
        return sum(i.count for i in self.interests)

    # --- schema validation ------------------------------------------------

    @field_validator("start_time_local", "end_time_local")
    @classmethod
    def _valid_time(cls, v: str) -> str:
        _hhmm(v)
        return v

    @field_validator("free_text_interests")
    @classmethod
    def _bounded_free_text(cls, v: list[str]) -> list[str]:
        if len(v) > 10:
            raise ValueError("at most 10 free-text interests")
        for phrase in v:
            if len(phrase) > 80:
                raise ValueError(f"free-text interest too long: {phrase[:40]!r}")
        return v

    @model_validator(mode="after")
    def _window_is_sane(self) -> TripSpec:
        span = self.window_minutes
        if span <= 0:
            raise ValueError(
                "end_time must be after start_time; overnight trips are "
                "not supported")
        if span < 60:
            raise ValueError("trip window must be at least 60 minutes")
        if span > 16 * 60:
            raise ValueError("trip window must not exceed 16 hours")
        return self

    @model_validator(mode="after")
    def _no_category_both_wanted_and_avoided(self) -> TripSpec:
        wanted = {i.category for i in self.interests}
        clash = wanted & set(self.constraints.avoid_categories)
        if clash:
            raise ValueError(
                f"categories both requested and excluded: "
                f"{sorted(c.value for c in clash)}")
        return self

    @model_validator(mode="after")
    def _walking_only_needs_walking_budget(self) -> TripSpec:
        if (self.transport == [TransportMode.WALKING]
                and self.constraints.max_walking_km < 1):
            raise ValueError(
                "a walking-only trip requires max_walking_km of at least 1")
        return self

    @model_validator(mode="after")
    def _max_stops_not_below_must_count(self) -> TripSpec:
        cap = self.constraints.max_stops
        if cap is None:
            return self
        must = sum(i.count for i in self.must_interests)
        if must > cap:
            raise ValueError(
                f"max_stops is {cap} but {must} stops are marked MUST")
        return self


def migrate_tripspec(raw: dict) -> TripSpec:
    """Upgrade a stored spec to the current version.

    A version bump without a branch here fails test_migration_covers_all
    versions - that test is the guard against silently unreadable history.
    """
    version = raw.get("version", "1.0")
    if version == "1.0":
        return TripSpec.model_validate(raw)
    raise ValueError(f"no migration path from TripSpec version {version!r}")