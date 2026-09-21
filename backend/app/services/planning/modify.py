"""Natural-language itinerary modification: a CLOSED set of operations.

The LLM (or the rule parser) only chooses an operation and its arguments.
Python applies it to the TripSpec and the current stops, replans with the
deterministic engine and revalidates. The model never edits itinerary JSON.

Stability: operations that change the whole day (budget, time, pace...) keep
the current stops as PREFERRED so the plan changes as little as it must;
operations that target one stop (remove/replace/add) LOCK the other stops.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.taxonomy import is_valid_category
from app.schemas.tripspec import AreaRef, Pace, TripSpec, is_controlled_interest, _hhmm
from app.services.planning.engine import PlanDirectives


class ModOp(str, Enum):
    REMOVE_STOP = "remove_stop"
    ADD_POI = "add_poi"
    REPLACE_STOP = "replace_stop"
    SET_BUDGET = "set_budget"
    SET_START_TIME = "set_start_time"
    SET_END_TIME = "set_end_time"
    SHIFT_TIME = "shift_time"
    SET_STOP_COUNT = "set_stop_count"
    SET_PACE = "set_pace"
    SET_AREA = "set_area"
    AVOID_AREA = "avoid_area"
    AVOID_CATEGORY = "avoid_category"
    PREFER_CATEGORY = "prefer_category"
    ADD_INTEREST = "add_interest"
    REMOVE_INTEREST = "remove_interest"
    SET_INDOOR_PREFERENCE = "set_indoor_preference"
    SET_TRANSITION_BUFFER = "set_transition_buffer"
    ADD_MEAL = "add_meal"


REQUIRED = {
    ModOp.REMOVE_STOP: ("target_seq",), ModOp.ADD_POI: ("poi_id",),
    ModOp.REPLACE_STOP: ("target_seq",), ModOp.SET_BUDGET: ("amount",),
    ModOp.SET_START_TIME: ("time",), ModOp.SET_END_TIME: ("time",),
    ModOp.SHIFT_TIME: ("minutes",), ModOp.SET_STOP_COUNT: ("count",),
    ModOp.SET_PACE: ("pace",), ModOp.SET_AREA: (), ModOp.AVOID_AREA: ("area",),
    ModOp.AVOID_CATEGORY: ("category",), ModOp.PREFER_CATEGORY: ("category",),
    ModOp.ADD_INTEREST: ("interest",), ModOp.REMOVE_INTEREST: ("interest",),
    ModOp.SET_INDOOR_PREFERENCE: ("preference",), ModOp.SET_TRANSITION_BUFFER: ("minutes",),
    ModOp.ADD_MEAL: ("meal",),
}


class Modification(BaseModel):
    """One closed operation. Unknown fields are rejected."""
    model_config = ConfigDict(extra="forbid")

    op: ModOp
    target_seq: int | None = Field(default=None, ge=1, le=12)
    poi_id: int | None = Field(default=None, gt=0)
    amount: int | None = Field(default=None, ge=0, le=200_000)
    time: str | None = None
    minutes: int | None = Field(default=None, ge=-600, le=600)
    count: int | None = Field(default=None, ge=1, le=8)
    pace: Pace | None = None
    area: str | None = Field(default=None, max_length=80)
    category: str | None = None
    interest: str | None = None
    preference: Literal["indoor", "outdoor", "any"] | None = None
    meal: Literal["breakfast", "lunch", "dinner", "snacks", "coffee"] | None = None

    @model_validator(mode="after")
    def _check(self) -> Modification:
        for name in REQUIRED[self.op]:
            if getattr(self, name) is None:
                raise ValueError(f"{self.op.value} requires {name}")
        if self.time is not None:
            _hhmm(self.time)
        if self.category is not None and not is_valid_category(self.category):
            raise ValueError(f"unknown category {self.category!r}")
        if self.interest is not None and not is_controlled_interest(self.interest):
            raise ValueError(f"unknown interest {self.interest!r}")
        if self.op == ModOp.SET_TRANSITION_BUFFER and not 0 <= (self.minutes or 0) <= 90:
            raise ValueError("transition buffer must be 0-90 minutes")
        return self


@dataclass
class CurrentStop:
    seq: int
    poi_id: int
    name: str
    category: str


@dataclass
class Applied:
    spec: TripSpec
    directives: PlanDirectives
    summary: list[str] = field(default_factory=list)
    area_to_resolve: str | None = None


class ModificationError(ValueError):
    code = "INVALID_MODIFICATION"


def _hhmm_add(value: str, minutes: int) -> str:
    m = max(0, min(23 * 60 + 59, _hhmm(value) + minutes))
    return f"{m // 60:02d}:{m % 60:02d}"


def apply_modifications(spec: TripSpec, stops: list[CurrentStop],
                        mods: list[Modification]) -> Applied:
    """Pure: returns a new spec and planner directives. Never mutates input."""
    if not mods:
        raise ModificationError("no modification given")
    data = spec.model_dump()
    data["source"] = "modification"
    by_seq = {s.seq: s for s in stops}
    current_ids = [s.poi_id for s in stops]
    locked: list[int] | None = None
    preferred = list(current_ids)
    max_override: int | None = None
    replacement_category: str | None = None
    summary: list[str] = []
    area_to_resolve: str | None = None

    for m in mods:
        if m.op in (ModOp.REMOVE_STOP, ModOp.REPLACE_STOP):
            target = by_seq.get(m.target_seq)
            if target is None:
                raise ModificationError(f"there is no stop {m.target_seq}")
            data["exclude_poi_ids"] = list(dict.fromkeys(data["exclude_poi_ids"]
                                                         + [target.poi_id]))
            data["must_include_poi_ids"] = [i for i in data["must_include_poi_ids"]
                                            if i != target.poi_id]
            keep = [i for i in (locked if locked is not None else current_ids)
                    if i != target.poi_id]
            locked = keep
            if m.op == ModOp.REMOVE_STOP:
                max_override = len(keep)
                summary.append(f"Removed {target.name}")
            else:
                max_override = len(keep) + 1
                replacement_category = m.category
                summary.append(f"Replaced {target.name}"
                               + (f" with a {m.category.replace('_', ' ')}" if m.category else ""))
        elif m.op == ModOp.ADD_POI:
            if m.poi_id in data["exclude_poi_ids"]:
                data["exclude_poi_ids"].remove(m.poi_id)
            keep = list(locked if locked is not None else current_ids)
            locked = list(dict.fromkeys(keep + [m.poi_id]))
            max_override = len(locked)
            summary.append("Added a place")
        elif m.op == ModOp.SET_BUDGET:
            data["budget_total"], data["budget_per_person"] = m.amount, None
            summary.append(f"Budget set to ₹{m.amount}")
        elif m.op == ModOp.SET_START_TIME:
            data["start_time"] = m.time
            summary.append(f"Start at {m.time}")
        elif m.op == ModOp.SET_END_TIME:
            data["end_time"] = m.time
            summary.append(f"End by {m.time}")
        elif m.op == ModOp.SHIFT_TIME:
            if spec.start_time is None or spec.end_time is None:
                raise ModificationError("the plan has no time window to shift")
            data["start_time"] = _hhmm_add(spec.start_time, m.minutes)
            data["end_time"] = _hhmm_add(spec.end_time, m.minutes)
            if _hhmm(data["end_time"]) - _hhmm(data["start_time"]) < 60:
                raise ModificationError("shifting that far leaves less than an hour today")
            word = "later" if m.minutes > 0 else "earlier"
            summary.append(f"Starts {abs(m.minutes) // 60 or abs(m.minutes)}"
                           f"{' h' if abs(m.minutes) >= 60 else ' min'} {word}")
        elif m.op == ModOp.SET_STOP_COUNT:
            data["desired_stop_count"] = m.count
            if data.get("max_stop_count") and data["max_stop_count"] < m.count:
                data["max_stop_count"] = m.count
            if m.count < len(current_ids):
                preferred = current_ids[: m.count]
            max_override = m.count
            summary.append(f"{m.count} stop{'s' * (m.count > 1)}")
        elif m.op == ModOp.SET_PACE:
            data["pace"] = m.pace
            summary.append(f"{m.pace.value.capitalize()} pace")
        elif m.op == ModOp.SET_AREA:
            if m.area:
                area_to_resolve = m.area
                summary.append(f"Around {m.area}")
            else:
                data["anchor_area"] = None
                summary.append("Anywhere in the city")
            preferred = []
        elif m.op == ModOp.AVOID_AREA:
            data["avoid_areas"] = list(dict.fromkeys(data["avoid_areas"] + [m.area]))[:5]
            summary.append(f"Avoiding {m.area}")
        elif m.op == ModOp.AVOID_CATEGORY:
            data["avoid_interests"] = list(dict.fromkeys(data["avoid_interests"] + [m.category]))
            data["interests"] = [i for i in data["interests"] if i != m.category]
            removed = [s for s in stops if s.category == m.category]
            data["exclude_poi_ids"] = list(dict.fromkeys(data["exclude_poi_ids"]
                                                         + [s.poi_id for s in removed]))
            if locked is not None:
                locked = [i for i in locked if i not in {s.poi_id for s in removed}]
            summary.append(f"No {m.category.replace('_', ' ')}")
        elif m.op in (ModOp.PREFER_CATEGORY, ModOp.ADD_INTEREST):
            value = m.category or m.interest
            data["interests"] = list(dict.fromkeys(data["interests"] + [value]))[:12]
            data["avoid_interests"] = [i for i in data["avoid_interests"] if i != value]
            summary.append(f"More {value.replace('_', ' ')}")
        elif m.op == ModOp.REMOVE_INTEREST:
            data["interests"] = [i for i in data["interests"] if i != m.interest]
            summary.append(f"Less {m.interest.replace('_', ' ')}")
        elif m.op == ModOp.SET_INDOOR_PREFERENCE:
            data["indoor_preference"] = m.preference
            summary.append({"indoor": "Indoors", "outdoor": "Outdoors",
                            "any": "Indoor or outdoor"}[m.preference])
        elif m.op == ModOp.SET_TRANSITION_BUFFER:
            data["transition_buffer_minutes"] = m.minutes
            summary.append(f"{m.minutes}-minute transition buffers")
        elif m.op == ModOp.ADD_MEAL:
            data["meal_preferences"] = list(dict.fromkeys(data["meal_preferences"] + [m.meal]))
            food = "cafe" if m.meal in ("coffee", "snacks", "breakfast") else "restaurant"
            data["interests"] = list(dict.fromkeys(data["interests"] + [food]))[:12]
            if max_override is None:
                max_override = len(current_ids) + 1
            summary.append(f"Added {m.meal}")

    if locked is not None:
        data["must_include_poi_ids"] = list(dict.fromkeys(data["must_include_poi_ids"]))
    new_spec = TripSpec.model_validate(data)
    return Applied(
        spec=new_spec,
        directives=PlanDirectives(
            locked_ids=list(locked or []),
            preferred_ids=[i for i in preferred if i not in set(new_spec.exclude_poi_ids)],
            replacement_category=replacement_category,
            max_stops_override=max_override),
        summary=summary, area_to_resolve=area_to_resolve)


def area_ref(resolved) -> AreaRef:
    return AreaRef(name=resolved.name, lat=resolved.lat, lon=resolved.lon,
                   source_ref=resolved.source_ref, radius_km=resolved.radius_km)
