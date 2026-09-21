"""Tier 2 - semantic validation of a TripSpec v2.

Tier 1 (Pydantic) rejects malformed values. This catches specs that are
well-formed but do not make sense: a date in the past, a budget that cannot
buy anything for the party, a window that starts before most places open.

Issues are returned, not raised: the assistant turns them into one concise
clarification and the form highlights the field.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type
from enum import Enum

from app.schemas.tripspec import TripSpec

DAYLIGHT_INTERESTS = {"park", "garden", "lake", "nature", "hill", "viewpoint", "forest",
                      "waterfall", "reservoir", "fort", "sunrise"}
FOOD_INTERESTS = {"cafe", "restaurant", "street_food", "dessert", "food", "coffee", "foodie"}
MIN_BUDGET_PER_PERSON_INR = 50


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class Issue:
    code: str
    field: str
    message: str
    severity: Severity = Severity.ERROR
    suggestion: str | None = None

    def to_dict(self) -> dict:
        return {"code": self.code, "field": self.field, "message": self.message,
                "severity": self.severity.value, "suggestion": self.suggestion}


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
        return {"valid": self.is_valid, "errors": [i.to_dict() for i in self.errors],
                "warnings": [i.to_dict() for i in self.warnings]}


def validate_semantics(spec: TripSpec, today: date_type | None = None,
                       now_minute: int | None = None) -> SemanticReport:
    from app.nlu.timeparse import minute_of_day, now_ist, today_ist
    report = SemanticReport()
    today = today or today_ist()

    if spec.date is not None:
        if spec.date < today:
            report.issues.append(Issue("DATE_IN_PAST", "date", f"{spec.date} has already passed",
                                       suggestion="Choose today or a future date"))
        elif (spec.date - today).days > 365:
            report.issues.append(Issue("DATE_TOO_FAR", "date",
                                       "plans more than a year ahead are unlikely to hold",
                                       Severity.WARNING))
        if spec.date == today and spec.end_minute is not None:
            current = now_minute if now_minute is not None else minute_of_day(now_ist())
            if spec.end_minute <= current:
                report.issues.append(Issue(
                    "WINDOW_ALREADY_OVER", "end_time",
                    "that time window has already ended today",
                    suggestion="Pick a later time or another day"))

    if spec.end_minute is not None and spec.end_minute > 23 * 60:
        report.issues.append(Issue("ENDS_VERY_LATE", "end_time",
                                   "the plan ends after 23:00; most places will be closed",
                                   Severity.WARNING))
    if spec.start_minute is not None and spec.start_minute < 6 * 60:
        report.issues.append(Issue("STARTS_VERY_EARLY", "start_time",
                                   "the plan starts before 06:00; few places will be open",
                                   Severity.WARNING))
    daylight = DAYLIGHT_INTERESTS & set(spec.interests)
    if daylight and spec.start_minute is not None and spec.start_minute >= 19 * 60:
        report.issues.append(Issue(
            "OUTDOOR_AFTER_DARK", "interests",
            f"{', '.join(sorted(daylight))} requested but the plan starts after 19:00",
            Severity.WARNING, "These are usually daylight activities"))

    total = spec.effective_budget_total
    if total is not None:
        floor = MIN_BUDGET_PER_PERSON_INR * spec.effective_party_size
        if 0 < total < floor:
            report.issues.append(Issue(
                "BUDGET_VERY_LOW", "budget_total",
                f"₹{total} for {spec.effective_party_size} people only covers free places",
                Severity.WARNING, "Free parks, lakes and temples still work"))

    if spec.budget_total is not None and spec.budget_per_person is not None:
        implied = spec.budget_per_person * spec.effective_party_size
        if abs(implied - spec.budget_total) > max(50, 0.1 * spec.budget_total):
            report.issues.append(Issue(
                "BUDGET_CONFLICT", "budget_total",
                f"total ₹{spec.budget_total} and ₹{spec.budget_per_person} per person disagree",
                suggestion="Keep one of them"))

    if spec.party_type is not None and spec.party_size is not None:
        if spec.party_type.value == "couple" and spec.party_size != 2:
            report.issues.append(Issue("PARTY_MISMATCH", "party_size",
                                       "a couple is two people", Severity.WARNING))
        if spec.party_type.value == "solo" and spec.party_size != 1:
            report.issues.append(Issue("PARTY_MISMATCH", "party_size",
                                       "solo means one person", Severity.WARNING))

    window = spec.window_minutes
    if window is not None and spec.desired_stop_count:
        min_needed = spec.desired_stop_count * 20 + (spec.desired_stop_count - 1) * \
            spec.transition_buffer_minutes
        if min_needed > window:
            # A warning, not an error: the feasibility check reports it as
            # INFEASIBLE with concrete relaxations the user can apply.
            report.issues.append(Issue(
                "TOO_MANY_STOPS", "desired_stop_count",
                f"{spec.desired_stop_count} stops do not fit in {window} minutes",
                Severity.WARNING, "Fewer stops or a longer window"))

    wants_food = bool(FOOD_INTERESTS & set(spec.interests)) or bool(spec.meal_preferences)
    if spec.dietary_preferences and not wants_food and window is not None and window < 180:
        report.issues.append(Issue("DIET_WITHOUT_FOOD", "dietary_preferences",
                                   "a dietary preference is set but no food stop is likely",
                                   Severity.WARNING))

    if set(spec.preferred_areas and [a.name.lower() for a in spec.preferred_areas]) & {
            a.lower() for a in spec.avoid_areas}:
        report.issues.append(Issue("AREA_CONFLICT", "avoid_areas",
                                   "an area is both preferred and avoided"))
    return report
