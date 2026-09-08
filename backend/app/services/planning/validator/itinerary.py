"""NQ-024 - Independent itinerary validator.

THE RULE THAT MAKES THIS REAL: re-derive from primary sources. Do not reuse
the optimizer's arithmetic. A validator that trusts the thing it is checking
validates nothing.

So: re-query opening hours from the database, re-fetch routes from OSRM,
re-sum costs from the cost model. If the optimizer and the validator disagree,
one of them is wrong and the itinerary does not get persisted.

Written by a different person from the optimizer (NQ-023), deliberately. If
one author writes both, the same wrong assumption gets made twice and the
validator agrees with the bug.

Nine rules, nine mutation tests. A validator that never fails is not a
validator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type
from enum import Enum

# Tolerances. Travel times are re-fetched, and OSRM caching plus rounding
# means an exact match is not expected.
TRAVEL_TOLERANCE_S = 60
COST_TOLERANCE_INR = 1
SINGLE_WALK_CAP_M = 1500

BBOX_MIN_LAT, BBOX_MAX_LAT = 11.9, 13.75
BBOX_MIN_LON, BBOX_MAX_LON = 76.7, 78.9


class Rule(str, Enum):
    TRAVEL_TIME = "TRAVEL_TIME_MISMATCH"
    OPENING_HOURS = "VENUE_CLOSED"
    BUDGET = "BUDGET_EXCEEDED"
    TIMELINE = "TIMELINE_INVALID"
    WALKING = "WALKING_EXCEEDED"
    MUST_INTERESTS = "MUST_UNSATISFIED"
    EXCLUSIONS = "EXCLUSION_VIOLATED"
    BOUNDS = "OUT_OF_BOUNDS"
    WEATHER = "WEATHER_UNSUITABLE"


@dataclass
class Finding:
    rule: Rule
    stop_seq: int | None
    message: str
    expected: str | None = None
    actual: str | None = None

    def to_dict(self) -> dict:
        return {
            "rule": self.rule.value,
            "stop_seq": self.stop_seq,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass
class ValidatorReport:
    valid: bool
    findings: list[Finding] = field(default_factory=list)
    rules_run: list[str] = field(default_factory=list)
    relaxations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "rules_run": self.rules_run,
            "findings": [f.to_dict() for f in self.findings],
            "relaxations": self.relaxations,
        }


@dataclass
class StopFacts:
    """Primary-source truth about one stop, fetched independently of the
    optimizer. Supplied by the caller (NQ-025) so this stays a pure function.
    """
    seq: int
    poi_id: int | None
    name: str
    category: str
    lat: float
    lon: float
    arrive_min: int
    depart_min: int
    cost_inr: int
    # Re-queried from poi_opening_hours, not taken from the optimizer.
    open_min: int | None
    close_min: int | None
    hours_confidence: float
    indoor: bool
    # Re-fetched from OSRM, not taken from the optimizer.
    travel_s_from_prev: float | None
    optimizer_travel_s_from_prev: float | None
    walk_m_from_prev: float
    leg_cost_inr: int


@dataclass
class TripFacts:
    start_min: int
    end_min: int
    date: date_type
    budget_inr: int | None
    max_walk_m: float
    must_interests: dict[str, int]          # category -> required count
    excluded_categories: set[str]
    excluded_poi_ids: set[int]
    heavy_rain_expected: bool = False


def validate(
    stops: list[StopFacts],
    trip: TripFacts,
    declared_relaxations: list[str] | None = None,
) -> ValidatorReport:
    """Nine independent rules. Any finding blocks persistence."""
    report = ValidatorReport(valid=True, relaxations=declared_relaxations or [])
    f = report.findings

    # --- 1. travel times re-fetched, not trusted ---------------------------
    report.rules_run.append(Rule.TRAVEL_TIME.value)
    for s in stops:
        if s.travel_s_from_prev is None or s.optimizer_travel_s_from_prev is None:
            continue
        drift = abs(s.travel_s_from_prev - s.optimizer_travel_s_from_prev)
        if drift > TRAVEL_TOLERANCE_S:
            f.append(Finding(
                Rule.TRAVEL_TIME, s.seq,
                f"re-fetched travel time to {s.name} differs from the "
                f"optimizer's by {drift:.0f}s",
                expected=f"{s.optimizer_travel_s_from_prev:.0f}s",
                actual=f"{s.travel_s_from_prev:.0f}s"))

    # --- 2. opening hours re-queried ---------------------------------------
    report.rules_run.append(Rule.OPENING_HOURS.value)
    for s in stops:
        # Low-confidence hours are category defaults (NQ-014). They are a soft
        # optimizer constraint, so the validator must not treat them as hard
        # either - otherwise 91% of POIs fail validation.
        if s.hours_confidence < 0.5:
            continue
        if s.open_min is None or s.close_min is None:
            continue
        if s.arrive_min < s.open_min:
            f.append(Finding(
                Rule.OPENING_HOURS, s.seq,
                f"{s.name} is scheduled before it opens",
                expected=f"opens {s.open_min // 60:02d}:{s.open_min % 60:02d}",
                actual=f"arrives {s.arrive_min // 60:02d}:{s.arrive_min % 60:02d}"))
        if s.depart_min > s.close_min:
            f.append(Finding(
                Rule.OPENING_HOURS, s.seq,
                f"{s.name} is scheduled past closing",
                expected=f"closes {s.close_min // 60:02d}:{s.close_min % 60:02d}",
                actual=f"leaves {s.depart_min // 60:02d}:{s.depart_min % 60:02d}"))

    # --- 3. budget re-summed ------------------------------------------------
    report.rules_run.append(Rule.BUDGET.value)
    if trip.budget_inr is not None:
        total = sum(s.cost_inr + s.leg_cost_inr for s in stops)
        if total > trip.budget_inr + COST_TOLERANCE_INR:
            f.append(Finding(
                Rule.BUDGET, None,
                "re-summed cost exceeds the budget",
                expected=f"<= Rs {trip.budget_inr}",
                actual=f"Rs {total}"))

    # --- 4. timeline --------------------------------------------------------
    report.rules_run.append(Rule.TIMELINE.value)
    previous_depart = trip.start_min
    for s in stops:
        if s.arrive_min < previous_depart:
            f.append(Finding(
                Rule.TIMELINE, s.seq,
                f"{s.name} is scheduled before the previous stop ends",
                expected=f">= {previous_depart}", actual=str(s.arrive_min)))
        if s.depart_min < s.arrive_min:
            f.append(Finding(
                Rule.TIMELINE, s.seq,
                f"{s.name} departs before it is reached"))
        if s.arrive_min < trip.start_min or s.depart_min > trip.end_min:
            f.append(Finding(
                Rule.TIMELINE, s.seq,
                f"{s.name} falls outside the trip window",
                expected=f"{trip.start_min}-{trip.end_min}",
                actual=f"{s.arrive_min}-{s.depart_min}"))
        previous_depart = s.depart_min

    # --- 5. walking ---------------------------------------------------------
    report.rules_run.append(Rule.WALKING.value)
    total_walk = sum(s.walk_m_from_prev for s in stops)
    if total_walk > trip.max_walk_m:
        f.append(Finding(
            Rule.WALKING, None, "total walking exceeds the limit",
            expected=f"<= {trip.max_walk_m:.0f}m", actual=f"{total_walk:.0f}m"))
    for s in stops:
        if s.walk_m_from_prev > SINGLE_WALK_CAP_M:
            f.append(Finding(
                Rule.WALKING, s.seq,
                f"a single walk to {s.name} is unreasonably long",
                expected=f"<= {SINGLE_WALK_CAP_M}m",
                actual=f"{s.walk_m_from_prev:.0f}m"))

    # --- 6. MUST interests --------------------------------------------------
    report.rules_run.append(Rule.MUST_INTERESTS.value)
    for category, required in trip.must_interests.items():
        got = sum(1 for s in stops if s.category == category)
        if got < required:
            # Acceptable only if the shortfall was declared as a relaxation
            # the user agreed to.
            declared = any(category in r for r in report.relaxations)
            if not declared:
                f.append(Finding(
                    Rule.MUST_INTERESTS, None,
                    f"required category '{category}' is short and no "
                    f"relaxation was declared",
                    expected=str(required), actual=str(got)))

    # --- 7. exclusions ------------------------------------------------------
    report.rules_run.append(Rule.EXCLUSIONS.value)
    seen_ids: set[int] = set()
    for s in stops:
        if s.category in trip.excluded_categories:
            f.append(Finding(
                Rule.EXCLUSIONS, s.seq,
                f"{s.name} is in an excluded category '{s.category}'"))
        if s.poi_id is not None:
            if s.poi_id in trip.excluded_poi_ids:
                f.append(Finding(
                    Rule.EXCLUSIONS, s.seq,
                    f"{s.name} was explicitly excluded"))
            if s.poi_id in seen_ids:
                f.append(Finding(
                    Rule.EXCLUSIONS, s.seq,
                    f"{s.name} appears more than once"))
            seen_ids.add(s.poi_id)

    # --- 8. bounds ----------------------------------------------------------
    report.rules_run.append(Rule.BOUNDS.value)
    for s in stops:
        if not (BBOX_MIN_LAT <= s.lat <= BBOX_MAX_LAT
                and BBOX_MIN_LON <= s.lon <= BBOX_MAX_LON):
            f.append(Finding(
                Rule.BOUNDS, s.seq,
                f"{s.name} is outside the supported region",
                actual=f"{s.lat},{s.lon}"))

    # --- 9. weather ---------------------------------------------------------
    report.rules_run.append(Rule.WEATHER.value)
    if trip.heavy_rain_expected:
        for s in stops:
            if not s.indoor:
                f.append(Finding(
                    Rule.WEATHER, s.seq,
                    f"{s.name} is outdoors and heavy rain is forecast"))

    report.valid = not f
    return report