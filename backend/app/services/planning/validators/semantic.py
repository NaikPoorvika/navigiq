"""NQ-021 tier 2 - semantic validation.

Tier 1 (Pydantic) catches malformed values. This catches specs that are
well-formed but do not make sense: a date in the past, a budget that cannot
buy the requested categories, transport that contradicts the walking limit.

Tier 3 (NQ-022 feasibility) then asks whether the trip can exist at all
given real POIs and real travel times.

These return structured issues rather than raising, because the agent in
NQ-031 needs to turn them into a clarifying question, and the form in
NQ-026 needs to highlight a specific field.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type
from enum import Enum

from app.schemas.tripspec import Category, TransportMode, TripSpec


class Severity(str, Enum):
    ERROR = "error"       # cannot plan
    WARNING = "warning"   # can plan, but the user should know


@dataclass
class Issue:
    code: str
    field: str
    message: str
    severity: Severity = Severity.ERROR
    suggestion: str | None = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "field": self.field,
            "message": self.message,
            "severity": self.severity.value,
            "suggestion": self.suggestion,
        }


@dataclass
class SemanticReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "valid": self.is_valid,
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
        }


# Categories that cannot be visited after dark in any useful sense.
DAYLIGHT_ONLY = {Category.PARK, Category.LAKE, Category.NATURE,
                 Category.VIEWPOINT, Category.HISTORICAL}

# Rough floor per person for a trip with any paid category in it.
MIN_BUDGET_PER_PERSON_INR = 50


def validate_semantics(
    spec: TripSpec,
    today: date_type | None = None,
) -> SemanticReport:
    report = SemanticReport()
    today = today or date_type.today()

    # --- date -------------------------------------------------------------
    if spec.date < today:
        report.issues.append(Issue(
            "DATE_IN_PAST", "date",
            f"{spec.date} has already passed",
            suggestion="Choose today or a future date"))

    if (spec.date - today).days > 365:
        report.issues.append(Issue(
            "DATE_TOO_FAR", "date",
            "planning more than a year ahead is unlikely to be accurate",
            Severity.WARNING))

    # --- time window ------------------------------------------------------
    if spec.end_minute > 23 * 60:
        report.issues.append(Issue(
            "ENDS_VERY_LATE", "end_time_local",
            "the trip ends after 23:00; most places will be closed",
            Severity.WARNING))

    if spec.start_minute < 6 * 60:
        report.issues.append(Issue(
            "STARTS_VERY_EARLY", "start_time_local",
            "the trip starts before 06:00; few places will be open",
            Severity.WARNING))

    # Outdoor categories requested entirely after dark.
    outdoor_must = [i for i in spec.must_interests
                    if i.category in DAYLIGHT_ONLY]
    if outdoor_must and spec.start_minute >= 19 * 60:
        names = ", ".join(i.category.value for i in outdoor_must)
        report.issues.append(Issue(
            "OUTDOOR_AFTER_DARK", "interests",
            f"{names} requested but the trip starts after 19:00",
            Severity.WARNING,
            "These are usually daylight activities"))

    # --- budget -----------------------------------------------------------
    if spec.budget_inr is not None:
        floor = MIN_BUDGET_PER_PERSON_INR * spec.party_size
        if spec.budget_inr < floor:
            report.issues.append(Issue(
                "BUDGET_TOO_LOW", "budget_inr",
                f"Rs {spec.budget_inr} for {spec.party_size} people is below "
                f"a workable minimum of Rs {floor}",
                suggestion=f"Raise the budget to at least Rs {floor}, or "
                           f"request only free categories"))

    # --- transport --------------------------------------------------------
    if TransportMode.WALKING not in spec.transport:
        report.issues.append(Issue(
            "NO_WALKING", "transport",
            "walking is not an allowed mode; every stop needs a vehicle leg",
            Severity.WARNING))

    walk_only = spec.transport == [TransportMode.WALKING]
    if walk_only and spec.total_requested_stops > 3:
        report.issues.append(Issue(
            "WALKING_ONLY_MANY_STOPS", "transport",
            f"{spec.total_requested_stops} stops on foot is ambitious",
            Severity.WARNING,
            "Add auto or cab , or reduce the number of stops"))

    if walk_only and spec.constraints.max_walking_km < 3:
        report.issues.append(Issue(
            "WALKING_ONLY_SHORT_LIMIT", "constraints.max_walking_km",
            f"walking-only with a {spec.constraints.max_walking_km} km limit "
            f"leaves very little reach"))

    # --- interests --------------------------------------------------------
    if spec.constraints.max_stops is not None:
        if spec.total_requested_stops > spec.constraints.max_stops:
            report.issues.append(Issue(
                "TOO_MANY_INTERESTS", "interests",
                f"{spec.total_requested_stops} stops requested but max_stops "
                f"is {spec.constraints.max_stops}",
                Severity.WARNING,
                "Lower-priority interests will be dropped first"))

    seen: set[Category] = set()
    for i in spec.interests:
        if i.category in seen:
            report.issues.append(Issue(
                "DUPLICATE_INTEREST", "interests",
                f"{i.category.value} appears more than once",
                suggestion="Use a single entry with a higher count"))
        seen.add(i.category)

    # --- dietary ----------------------------------------------------------
    c = spec.constraints
    if c.vegan and not c.vegetarian:
        report.issues.append(Issue(
            "VEGAN_WITHOUT_VEGETARIAN", "constraints",
            "vegan is set but vegetarian is not; vegan implies vegetarian",
            Severity.WARNING))

    meal_categories = {Category.RESTAURANT, Category.CAFE,
                       Category.STREET_FOOD, Category.DESSERT}
    wants_food = any(i.category in meal_categories for i in spec.interests)
    if (c.vegetarian or c.vegan or c.halal) and not wants_food:
        report.issues.append(Issue(
            "DIET_WITHOUT_FOOD", "constraints",
            "a dietary restriction is set but no food stop was requested",
            Severity.WARNING))

    return report