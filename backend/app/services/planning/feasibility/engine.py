"""Feasibility pre-check and relaxation suggestions (v2, section 47).

Runs BEFORE the optimizer. Cheap lower bounds catch impossible requests in
milliseconds - "10 places in 2 hours for ₹100" - instead of after a solve
that was never going to succeed.

No travel time is estimated anywhere (ADR-022). The time lower bound is the
sum of each stop's MINIMUM visit duration plus the transition buffers between
them; the cost lower bound is the sum of MINIMUM estimated costs for the party.
If even these optimistic bounds do not fit, the request is infeasible.

Relaxations are suggestions for the user, each carrying the concrete
modification operation that would apply it. Nothing that touches something
the user explicitly required is ever applied automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.schemas.tripspec import TripSpec, minutes_to_hhmm


class Violation(str, Enum):
    TIME = "TIME_INFEASIBLE"
    BUDGET = "BUDGET_INFEASIBLE"
    NO_CANDIDATES = "NO_CANDIDATES"
    MUST_CLOSED = "MUST_INCLUDE_CLOSED"
    STOPS = "STOP_COUNT_INFEASIBLE"


@dataclass
class Relaxation:
    code: str
    description: str
    operation: dict             # a closed modification op the UI can apply

    def to_dict(self) -> dict:
        return {"code": self.code, "description": self.description,
                "operation": self.operation}


@dataclass
class FeasibilityReport:
    feasible: bool
    violated: list[Violation] = field(default_factory=list)
    bounds: dict = field(default_factory=dict)
    relaxations: list[Relaxation] = field(default_factory=list)
    message: str | None = None

    def to_dict(self) -> dict:
        return {"feasible": self.feasible, "violated": [v.value for v in self.violated],
                "bounds": self.bounds, "message": self.message,
                "suggested_relaxations": [r.to_dict() for r in self.relaxations]}


@dataclass
class StopBound:
    """The minimum a required stop costs in time and money."""
    name: str
    min_visit: int
    min_cost_pp: int
    open_in_window: bool | None     # None = hours unknown


def check(spec: TripSpec, *, must: list[StopBound], candidate_count: int,
          min_visit_any: int = 20, min_cost_pp_any: int = 0) -> FeasibilityReport:
    """Lower-bound check on a plannable spec."""
    report = FeasibilityReport(feasible=True)
    window = spec.window_minutes or 0
    buffer = spec.transition_buffer_minutes
    party = spec.effective_party_size
    budget = spec.effective_budget_total
    requested = max(spec.desired_stop_count or 0, len(must), 1)

    must_time = sum(b.min_visit for b in must)
    extra = max(0, requested - len(must))
    min_time = must_time + extra * min_visit_any + max(0, requested - 1) * buffer
    min_cost = (sum(b.min_cost_pp for b in must) + extra * min_cost_pp_any) * party
    report.bounds = {
        "available_minutes": window, "min_required_minutes": min_time,
        "requested_stops": requested, "transition_buffer_minutes": buffer,
        "party_size": party, "min_estimated_cost_inr": min_cost,
        "budget_inr": budget, "candidate_count": candidate_count,
    }

    if min_time > window:
        report.feasible = False
        report.violated.append(Violation.TIME if len(must) or not spec.desired_stop_count
                               else Violation.STOPS)
    if budget is not None and min_cost > budget:
        report.feasible = False
        report.violated.append(Violation.BUDGET)
    closed = [b.name for b in must if b.open_in_window is False]
    if closed:
        report.feasible = False
        report.violated.append(Violation.MUST_CLOSED)
        report.bounds["closed_required_places"] = closed
    if candidate_count == 0 and not must:
        report.feasible = False
        report.violated.append(Violation.NO_CANDIDATES)

    if not report.feasible:
        report.relaxations = relaxations(spec, report, min_time)
        report.message = describe(report)
    return report


def relaxations(spec: TripSpec, report: FeasibilityReport, min_time: int) -> list[Relaxation]:
    out: list[Relaxation] = []
    v = set(report.violated)
    window = spec.window_minutes or 0
    requested = report.bounds["requested_stops"]
    if Violation.TIME in v or Violation.STOPS in v:
        if requested > 1:
            fewer = max(1, requested - max(1, (min_time - window) // 45 + 1))
            out.append(Relaxation("REDUCE_STOPS", f"Plan {fewer} stop{'s' * (fewer > 1)} "
                                  f"instead of {requested}",
                                  {"op": "set_stop_count", "count": fewer}))
        if spec.end_minute is not None:
            new_end = min(23 * 60, spec.end_minute + max(60, min_time - window + 15))
            if new_end > spec.end_minute:
                out.append(Relaxation("INCREASE_TIME", f"End at {minutes_to_hhmm(new_end)} "
                                      f"instead of {spec.end_time}",
                                      {"op": "set_end_time", "time": minutes_to_hhmm(new_end)}))
        if spec.pace.value != "quick":
            out.append(Relaxation("FASTER_PACE", "Use a quicker pace with shorter visits",
                                  {"op": "set_pace", "pace": "quick"}))
    if Violation.BUDGET in v:
        needed = report.bounds["min_estimated_cost_inr"]
        rounded = ((needed + 99) // 100) * 100
        out.append(Relaxation("INCREASE_BUDGET", f"Raise the budget to about ₹{rounded}",
                              {"op": "set_budget", "amount": rounded}))
        out.append(Relaxation("FREE_PLACES", "Focus on free places like parks, lakes and "
                              "temples", {"op": "add_interest", "interest": "budget"}))
    if Violation.NO_CANDIDATES in v:
        if spec.anchor_area is not None:
            out.append(Relaxation("CHANGE_AREA", "Search across the whole city instead of "
                                  f"around {spec.anchor_area.name}",
                                  {"op": "set_area", "area": None}))
        if spec.interests:
            out.append(Relaxation("WIDEN_CATEGORIES", "Allow a wider mix of places",
                                  {"op": "remove_interest", "interest": spec.interests[-1]}))
    if Violation.MUST_CLOSED in v:
        out.append(Relaxation("CHANGE_TIME", "Pick a time window when the required place "
                              "is open", {"op": "set_start_time", "time": None}))
    return out


def describe(report: FeasibilityReport) -> str:
    b = report.bounds
    parts = []
    if Violation.TIME in report.violated or Violation.STOPS in report.violated:
        parts.append(f"{b['requested_stops']} stops need at least {b['min_required_minutes']} "
                     f"minutes but the window is {b['available_minutes']}")
    if Violation.BUDGET in report.violated:
        parts.append(f"the places need at least ₹{b['min_estimated_cost_inr']} but the budget "
                     f"is ₹{b['budget_inr']}")
    if Violation.MUST_CLOSED in report.violated:
        parts.append("a required place is closed in that window: "
                     + ", ".join(b.get("closed_required_places", [])))
    if Violation.NO_CANDIDATES in report.violated:
        parts.append("no places match all of these constraints")
    return "That combination isn't feasible with the current constraints: " + "; ".join(
        parts) + "."
