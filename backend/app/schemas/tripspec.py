"""TripSpec v2 - the canonical planning contract (ADR-025).

The ONLY input to the planning engine, whether it came from the plan form,
from language extraction, from a modification or from a what-if.

Changes from v1 (NQ-021):
  * No transport modes, walking caps or routing inputs - transportation is
    deferred (ADR-022). Consecutive stops are separated by
    `transition_buffer_minutes`, which is a gap, never a travel time.
  * Interests are one controlled list (categories, experience tags, moods).
    Nothing outside the vocabulary validates, so a model cannot invent one.
  * Most fields are optional: a spec may be partial while a conversation is
    still gathering it. `resolve_for_planning` produces the complete spec the
    planner needs and records every default it applied as an assumption.
  * Coordinates only ever come from the gazetteer (resolved in Python). A
    model-supplied lat/lon is rejected unless it is inside the envelope bbox.

THREE VALIDATION TIERS: schema (here), semantic (validators/semantic.py),
feasibility (feasibility/engine.py). None runs in a prompt.
"""
from __future__ import annotations

import datetime as dt
from datetime import datetime, timedelta
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.taxonomy import (
    PartyType, is_valid_category, is_valid_mood, is_valid_tag,
)

TRIPSPEC_VERSION: Literal["2.0"] = "2.0"

# Envelope bounding box (90 km around the centre, generously rounded). Guards
# against hallucinated coordinates; the precise envelope test is geodesic.
BBOX_MIN_LAT, BBOX_MAX_LAT = 12.1, 13.8
BBOX_MIN_LON, BBOX_MAX_LON = 76.7, 78.5

MIN_WINDOW_MIN = 60
MAX_WINDOW_MIN = 16 * 60


class Pace(str, Enum):
    QUICK = "quick"
    BALANCED = "balanced"
    RELAXED = "relaxed"


# Kept as an alias: v1 code and stored payloads call this PlanningMode.
PlanningMode = Pace

MealPreference = Literal["breakfast", "lunch", "dinner", "snacks", "coffee"]
DietaryPreference = Literal["vegetarian", "pure_vegetarian", "vegan", "halal", "jain"]
FamilyRequirement = Literal["kids_friendly", "senior_friendly"]
AccessibilityRequirement = Literal["wheelchair_accessible"]


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


def minutes_to_hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def is_controlled_interest(value: str) -> bool:
    return is_valid_category(value) or is_valid_tag(value) or is_valid_mood(value)


class AreaRef(BaseModel):
    """A named area. lat/lon are filled ONLY by the gazetteer resolver."""
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=80)]
    lat: Annotated[float, Field(ge=BBOX_MIN_LAT, le=BBOX_MAX_LAT)] | None = None
    lon: Annotated[float, Field(ge=BBOX_MIN_LON, le=BBOX_MAX_LON)] | None = None
    source_ref: str | None = None
    radius_km: Annotated[float, Field(gt=0, le=90)] | None = None

    @property
    def resolved(self) -> bool:
        return self.lat is not None and self.lon is not None

    @model_validator(mode="after")
    def _both_or_neither(self) -> AreaRef:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("area lat and lon must be given together")
        return self


class TripSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["2.0"] = TRIPSPEC_VERSION
    city: Literal["Bengaluru"] = "Bengaluru"
    exploration_radius_km: Annotated[float, Field(gt=0, le=90)] = 90.0

    # The field is named `date`, so the type is referenced through the module
    # to avoid the class attribute shadowing it during annotation evaluation.
    date: dt.date | None = None
    start_time: str | None = None                 # HH:MM, Asia/Kolkata
    end_time: str | None = None

    anchor_area: AreaRef | None = None
    preferred_areas: Annotated[list[AreaRef], Field(max_length=5)] = Field(default_factory=list)
    avoid_areas: Annotated[list[Annotated[str, Field(max_length=80)]],
                           Field(max_length=5)] = Field(default_factory=list)

    party_size: Annotated[int, Field(ge=1, le=20)] | None = None
    party_type: PartyType | None = None

    budget_total: Annotated[int, Field(ge=0, le=200_000)] | None = None
    budget_per_person: Annotated[int, Field(ge=0, le=50_000)] | None = None

    interests: Annotated[list[str], Field(max_length=12)] = Field(default_factory=list)
    avoid_interests: Annotated[list[str], Field(max_length=12)] = Field(default_factory=list)

    must_include_poi_ids: Annotated[list[int], Field(max_length=6)] = Field(default_factory=list)
    must_include_names: Annotated[list[Annotated[str, Field(max_length=120)]],
                                  Field(max_length=6)] = Field(default_factory=list)
    exclude_poi_ids: Annotated[list[int], Field(max_length=100)] = Field(default_factory=list)

    pace: Pace = Pace.BALANCED
    desired_stop_count: Annotated[int, Field(ge=1, le=8)] | None = None
    max_stop_count: Annotated[int, Field(ge=1, le=8)] | None = None

    indoor_preference: Literal["indoor", "outdoor", "any"] | None = None
    weather_sensitive: bool | None = None

    meal_preferences: Annotated[list[MealPreference], Field(max_length=5)] = Field(
        default_factory=list)
    dietary_preferences: Annotated[list[DietaryPreference], Field(max_length=5)] = Field(
        default_factory=list)
    family_requirements: Annotated[list[FamilyRequirement], Field(max_length=2)] = Field(
        default_factory=list)
    accessibility_requirements: Annotated[list[AccessibilityRequirement],
                                          Field(max_length=1)] = Field(default_factory=list)

    romantic: bool | None = None
    quiet_preference: bool | None = None
    crowd_sensitivity: Literal["low", "medium", "high"] | None = None

    transition_buffer_minutes: Annotated[int, Field(ge=0, le=90)] = 15

    free_text_interests: Annotated[list[Annotated[str, Field(max_length=80)]],
                                   Field(max_length=10)] = Field(default_factory=list)
    source_utterance: Annotated[str, Field(max_length=2000)] = ""
    source: Literal["form", "llm", "modification", "what_if"] = "form"

    # --- derived ------------------------------------------------------------------

    @property
    def start_minute(self) -> int | None:
        return _hhmm(self.start_time) if self.start_time else None

    @property
    def end_minute(self) -> int | None:
        return _hhmm(self.end_time) if self.end_time else None

    @property
    def window_minutes(self) -> int | None:
        if self.start_minute is None or self.end_minute is None:
            return None
        return self.end_minute - self.start_minute

    @property
    def effective_party_size(self) -> int:
        if self.party_size:
            return self.party_size
        from app.nlu.quantities import DEFAULT_PARTY_SIZE
        return DEFAULT_PARTY_SIZE.get(self.party_type, 1) if self.party_type else 1

    @property
    def effective_budget_total(self) -> int | None:
        """Total budget for the party, from whichever form was given."""
        if self.budget_total is not None:
            return self.budget_total
        if self.budget_per_person is not None:
            return self.budget_per_person * self.effective_party_size
        return None

    @property
    def is_plannable(self) -> bool:
        return (self.date is not None and self.start_minute is not None
                and self.end_minute is not None)

    def start_datetime(self) -> datetime | None:
        if self.date is None or self.start_minute is None:
            return None
        return datetime.combine(self.date, datetime.min.time()) + timedelta(
            minutes=self.start_minute)

    # --- schema validation ------------------------------------------------------------

    @field_validator("start_time", "end_time")
    @classmethod
    def _valid_time(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return minutes_to_hhmm(_hhmm(v))

    @field_validator("interests", "avoid_interests")
    @classmethod
    def _controlled(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if not is_controlled_interest(x)]
        if bad:
            raise ValueError(f"not in the controlled vocabulary: {bad}")
        return list(dict.fromkeys(v))

    @field_validator("free_text_interests")
    @classmethod
    def _bounded_free_text(cls, v: list[str]) -> list[str]:
        return [p.strip() for p in v if p.strip()]

    @field_validator("must_include_poi_ids", "exclude_poi_ids")
    @classmethod
    def _positive_ids(cls, v: list[int]) -> list[int]:
        if any(i <= 0 for i in v):
            raise ValueError("POI ids are positive integers")
        return list(dict.fromkeys(v))

    @model_validator(mode="after")
    def _window_is_sane(self) -> TripSpec:
        if self.start_minute is not None and self.end_minute is not None:
            span = self.end_minute - self.start_minute
            if span <= 0:
                raise ValueError("end_time must be after start_time; overnight plans are "
                                 "not supported")
            if span < MIN_WINDOW_MIN:
                raise ValueError(f"the time window must be at least {MIN_WINDOW_MIN} minutes")
            if span > MAX_WINDOW_MIN:
                raise ValueError("the time window must not exceed 16 hours")
        return self

    @model_validator(mode="after")
    def _nothing_wanted_and_avoided(self) -> TripSpec:
        clash = set(self.interests) & set(self.avoid_interests)
        if clash:
            raise ValueError(f"interests both requested and avoided: {sorted(clash)}")
        both = set(self.must_include_poi_ids) & set(self.exclude_poi_ids)
        if both:
            raise ValueError(f"POIs both required and excluded: {sorted(both)}")
        return self

    @model_validator(mode="after")
    def _stop_counts_consistent(self) -> TripSpec:
        if (self.desired_stop_count and self.max_stop_count
                and self.desired_stop_count > self.max_stop_count):
            raise ValueError("desired_stop_count exceeds max_stop_count")
        cap = self.max_stop_count
        if cap is not None and len(self.must_include_poi_ids) > cap:
            raise ValueError(f"max_stop_count is {cap} but {len(self.must_include_poi_ids)} "
                             f"places are required")
        return self


# --- v1 -> v2 migration ------------------------------------------------------------------

_V1_CATEGORY = {"bar": "nightlife", "historical": "history", "art_gallery": "gallery",
                "sunset": "sunset", "bookstore": "shopping", "landmark": "monument"}


def _v1_interest(value: str) -> str | None:
    v = _V1_CATEGORY.get(value, value)
    return v if is_controlled_interest(v) else None


def migrate_tripspec(raw: dict) -> TripSpec:
    """Upgrade a stored spec to the current version.

    A version bump without a branch here fails test_migration_covers_all_versions -
    the guard against silently unreadable history.
    """
    version = raw.get("version", "1.0")
    if version == "2.0":
        return TripSpec.model_validate(raw)
    if version == "1.0":
        return TripSpec.model_validate(_v1_to_v2(raw))
    raise ValueError(f"no migration path from TripSpec version {version!r}")


def _v1_to_v2(raw: dict) -> dict:
    c = raw.get("constraints") or {}
    origin = raw.get("origin") or {}
    interests = [x for x in (_v1_interest(i.get("category", "")) for i in raw.get("interests", []))
                 if x]
    avoid = [x for x in (_v1_interest(a) for a in c.get("avoid_categories", [])) if x]
    dietary = [d for d, flag in (("vegetarian", c.get("vegetarian")), ("vegan", c.get("vegan")),
                                 ("halal", c.get("halal"))) if flag]
    anchor = None
    if origin.get("lat") is not None:
        lat, lon = float(origin["lat"]), float(origin["lon"])
        if BBOX_MIN_LAT <= lat <= BBOX_MAX_LAT and BBOX_MIN_LON <= lon <= BBOX_MAX_LON:
            anchor = {"name": origin.get("name") or "Starting point", "lat": lat, "lon": lon}
    return {
        "date": raw.get("date"),
        "start_time": raw.get("start_time_local"),
        "end_time": raw.get("end_time_local"),
        "anchor_area": anchor,
        "party_size": raw.get("party_size"),
        "budget_total": raw.get("budget_inr"),
        "interests": list(dict.fromkeys(interests))[:12],
        "avoid_interests": [a for a in dict.fromkeys(avoid) if a not in interests][:12],
        "exclude_poi_ids": c.get("avoid_poi_ids", []),
        "max_stop_count": c.get("max_stops"),
        "indoor_preference": "indoor" if c.get("indoor_preferred") else None,
        "dietary_preferences": dietary,
        "accessibility_requirements": (["wheelchair_accessible"]
                                       if c.get("accessibility_required") else []),
        "crowd_sensitivity": "high" if c.get("avoid_crowds") else None,
        "pace": raw.get("mode", "balanced"),
        "free_text_interests": raw.get("free_text_interests", [])[:10],
        "source": raw.get("source", "form") if raw.get("source") in (
            "form", "llm", "modification", "what_if") else "form",
    }
