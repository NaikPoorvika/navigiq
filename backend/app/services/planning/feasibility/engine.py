"""NQ-022 - Feasibility pre-check and relaxation ladder.

Runs BEFORE the optimizer. Cheap analytic lower bounds catch impossible trips
in milliseconds rather than after a 10-second CP-SAT solve that was never
going to succeed.

Uses haversine with a detour factor for the travel lower bound. That is
acceptable HERE because a lower bound only needs to be optimistic - if even
the optimistic estimate does not fit, the trip is impossible. Real OSRM times
are used everywhere else; a guessed distance must never reach a delivered
itinerary.

THE RULE: MUST constraints are never relaxed without explicit user
confirmation. Automatic relaxation is limited to dropping NICE_TO_HAVE,
reducing SHOULD counts, and widening the search radius.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from app.schemas.tripspec import Category, Interest, Priority, TripSpec

# Streets are not straight lines. Applied to haversine for the lower bound.
DETOUR_FACTOR = 1.35

# Optimistic speeds for the lower bound only. Real times come from OSRM.
LOWER_BOUND_SPEED_KMH = 25.0

# Minimum transport cost assumed per leg when a vehicle mode is allowed.
MIN_LEG_COST_INR = 30


class Violation(str, Enum):
    TIME = "TIME_INFEASIBLE"
    BUDGET = "BUDGET_INFEASIBLE"
    REACH = "REACH_INFEASIBLE"
    HOURS = "HOURS_INFEASIBLE"
    WEATHER = "WEATHER_INFEASIBLE"


@dataclass
class Relaxation:
    step: int
    description: str
    impact: str
    requires_confirmation: bool
    # What applying this would change, for apply_relaxation to act on.
    action: str
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "description": self.description,
            "impact": self.impact,
            "requires_confirmation": self.requires_confirmation,
            "action": self.action,
        }


@dataclass
class FeasibilityReport:
    feasible: bool
    violated: list[Violation] = field(default_factory=list)
    bounds: dict = field(default_factory=dict)
    suggested_relaxations: list[Relaxation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "feasible": self.feasible,
            "violated": [v.value for v in self.violated],
            "bounds": self.bounds,
            "suggested_relaxations": [
                r.to_dict() for r in self.suggested_relaxations],
        }


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


@dataclass
class CandidateSummary:
    """The minimum the pre-check needs about available POIs.

    Supplied by the caller so this module stays free of database access and
    remains a pure function - which is what makes it unit-testable.
    """
    category: str
    count: int
    min_cost_inr: int
    min_visit_minutes: int
    nearest_km: float
    any_open_in_window: bool
    all_outdoor: bool = False


class FeasibilityEngine:
    def __init__(self, category_defaults: dict[str, int] | None = None) -> None:
        # category -> default_visit_minutes, from poi_categories
        self.visit_defaults = category_defaults or {}

    def _visit_minutes(self, category: str, candidates: dict) -> int:
        c = candidates.get(category)
        if c and c.min_visit_minutes:
            return c.min_visit_minutes
        return self.visit_defaults.get(category, 45)

    def check(
        self,
        spec: TripSpec,
        candidates: dict[str, CandidateSummary],
        heavy_rain_expected: bool = False,
    ) -> FeasibilityReport:
        """Lower-bound check. Optimistic by construction - if this fails,
        no arrangement of real POIs and real travel times can succeed."""
        report = FeasibilityReport(feasible=True)
        available = spec.window_minutes

        must = spec.must_interests
        must_stops = sum(i.count for i in must)
        all_stops = spec.total_requested_stops

        # --- visit time lower bound ---------------------------------------
        required_visit = sum(
            i.count * self._visit_minutes(i.category.value, candidates)
            for i in must
        )

        # --- travel time lower bound --------------------------------------
        # Optimistic: assume every stop is at the nearest available POI of its
        # category, and legs are straight-line at a generous speed.
        legs = max(must_stops, 1)
        nearest_sum_km = sum(
            candidates[i.category.value].nearest_km * i.count
            for i in must if i.category.value in candidates
        )
        min_travel_km = nearest_sum_km * DETOUR_FACTOR
        min_travel = (min_travel_km / LOWER_BOUND_SPEED_KMH) * 60

        total_required = required_visit + min_travel

        report.bounds = {
            "available_minutes": available,
            "required_visit_minutes": round(required_visit),
            "min_travel_minutes": round(min_travel),
            "total_required_minutes": round(total_required),
            "must_stops": must_stops,
            "requested_stops": all_stops,
        }

        if total_required > available:
            report.feasible = False
            report.violated.append(Violation.TIME)

        # --- budget lower bound -------------------------------------------
        if spec.budget_inr is not None:
            min_poi_cost = sum(
                candidates[i.category.value].min_cost_inr * i.count
                for i in must if i.category.value in candidates
            ) * spec.party_size
            uses_vehicle = any(m.value != "walking" for m in spec.transport)
            min_transport = legs * MIN_LEG_COST_INR if uses_vehicle else 0
            min_cost = min_poi_cost + min_transport

            report.bounds["min_cost_inr"] = min_cost
            report.bounds["budget_inr"] = spec.budget_inr

            if min_cost > spec.budget_inr:
                report.feasible = False
                report.violated.append(Violation.BUDGET)

        # --- reach ---------------------------------------------------------
        missing = [i.category.value for i in must
                   if i.category.value not in candidates
                   or candidates[i.category.value].count == 0]
        if missing:
            report.feasible = False
            report.violated.append(Violation.REACH)
            report.bounds["categories_with_no_candidates"] = missing

        # --- opening hours --------------------------------------------------
        closed = [i.category.value for i in must
                  if i.category.value in candidates
                  and not candidates[i.category.value].any_open_in_window]
        if closed:
            report.feasible = False
            report.violated.append(Violation.HOURS)
            report.bounds["categories_closed_in_window"] = closed

        # --- weather ---------------------------------------------------------
        if heavy_rain_expected:
            washed_out = [i.category.value for i in must
                          if i.category.value in candidates
                          and candidates[i.category.value].all_outdoor]
            if washed_out:
                report.feasible = False
                report.violated.append(Violation.WEATHER)
                report.bounds["outdoor_categories_in_rain"] = washed_out

        if not report.feasible:
            report.suggested_relaxations = self._ladder(spec, report)

        return report

    def _ladder(self, spec: TripSpec, report: FeasibilityReport) -> list[Relaxation]:
        """Ordered relaxations. Steps 1, 2 and 4 are automatic; the rest
        require the user to agree, because they change what was asked for."""
        out: list[Relaxation] = []
        v = report.violated

        nice = [i for i in spec.interests if i.priority == Priority.NICE]
        if nice:
            out.append(Relaxation(
                1, f"Drop {len(nice)} optional interest(s): "
                   f"{', '.join(i.category.value for i in nice)}",
                "frees time and budget", False, "drop_nice"))

        should_multi = [i for i in spec.interests
                        if i.priority == Priority.SHOULD and i.count > 1]
        if should_multi:
            out.append(Relaxation(
                2, "Visit one of each preferred category instead of several",
                f"removes {sum(i.count - 1 for i in should_multi)} stop(s)",
                False, "reduce_should_counts"))

        if Violation.TIME in v:
            new_end = min(spec.end_minute + 60, 22 * 60)
            if new_end > spec.end_minute:
                out.append(Relaxation(
                    3, f"Extend the trip to "
                       f"{new_end // 60:02d}:{new_end % 60:02d}",
                    f"adds {new_end - spec.end_minute} minutes",
                    True, "extend_end", {"new_end_minute": new_end}))

        if Violation.REACH in v:
            out.append(Relaxation(
                4, "Search a wider area",
                "more places become reachable", False, "widen_radius"))

        if Violation.BUDGET in v:
            out.append(Relaxation(
                5, "Allow cheaper alternatives (street food instead of "
                   "restaurants)",
                "lowers the minimum cost", True, "cheaper_substitutes"))

        must = spec.must_interests
        multi_must = [i for i in must if i.count > 1]
        if multi_must:
            out.append(Relaxation(
                6, f"Reduce required stops: "
                   f"{', '.join(f'{i.count} {i.category.value}' for i in multi_must)}"
                   f" to one each",
                "significantly reduces time and cost", True,
                "reduce_must_counts"))

        if len(must) > 1:
            out.append(Relaxation(
                7, "Drop one of your required categories",
                "last resort", True, "drop_must"))

        return out


def apply_relaxation(spec: TripSpec, relaxation: Relaxation) -> TripSpec:
    """Return a modified copy. Pure - never mutates the input."""
    data = spec.model_dump()

    if relaxation.action == "drop_nice":
        data["interests"] = [i for i in data["interests"]
                             if i["priority"] != Priority.NICE.value]

    elif relaxation.action == "reduce_should_counts":
        for i in data["interests"]:
            if i["priority"] == Priority.SHOULD.value:
                i["count"] = 1

    elif relaxation.action == "extend_end":
        m = relaxation.payload["new_end_minute"]
        data["end_time_local"] = f"{m // 60:02d}:{m % 60:02d}"

    elif relaxation.action == "reduce_must_counts":
        for i in data["interests"]:
            if i["priority"] == Priority.MUST.value:
                i["count"] = 1

    elif relaxation.action in ("widen_radius", "cheaper_substitutes", "drop_must"):
        # Handled by the caller: radius is a search parameter, substitution
        # and dropping a MUST need a user choice about which one.
        pass

    return TripSpec.model_validate(data)