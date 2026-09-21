"""Independent itinerary validator (v2, section 46).

THE RULE THAT MAKES THIS REAL: re-derive from primary sources. Stops carry
only what the optimizer decided (which POI, when). Everything the rules check
against - existence, coordinates, hours for that weekday, cost ranges, tags,
duration bounds - is RE-QUERIED from the database by `facts.load_facts`, not
taken from the optimizer's arithmetic. A validator that trusts the thing it
checks validates nothing.

Any finding means the itinerary is not returned as valid. 100 % of
itineraries shown to users as valid pass this validator (release gate).

No travel time exists in this version (ADR-022): consecutive stops need a gap
of at least the transition buffer, and straight-line hop distance is checked
only for geographic coherence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from app.domain.taxonomy import FOOD_CATEGORIES
from app.geo.distance import haversine_km
from app.services.poi.repository import POIRecord
from app.services.recommendation.scoring import DIET_SATISFIES

BOUNDARY_TOLERANCE_KM = 1e-6


class Rule(str, Enum):
    EXISTS = "POI_NOT_FOUND"
    SCOPE = "OUT_OF_REGION"
    COHERENCE = "HOP_TOO_FAR"
    DUPLICATE = "DUPLICATE_STOP"
    HOURS = "VENUE_CLOSED"
    OVERLAP = "SCHEDULE_OVERLAP"
    BUFFER = "TRANSITION_BUFFER_VIOLATED"
    WINDOW = "OUTSIDE_TIME_WINDOW"
    BUDGET = "BUDGET_EXCEEDED"
    MUST = "MUST_INCLUDE_MISSING"
    EXCLUDED = "EXCLUSION_VIOLATED"
    REQUIREMENT = "REQUIREMENT_VIOLATED"
    DURATION = "INVALID_DURATION"
    CLAIM = "UNSUPPORTED_CLAIM"


ALL_RULES = [r.value for r in Rule]


@dataclass
class Finding:
    rule: Rule
    stop_seq: int | None
    message: str
    expected: str | None = None
    actual: str | None = None

    def to_dict(self) -> dict:
        return {"rule": self.rule.value, "stop_seq": self.stop_seq, "message": self.message,
                "expected": self.expected, "actual": self.actual}


@dataclass
class ValidatorReport:
    valid: bool
    findings: list[Finding] = field(default_factory=list)
    rules_run: list[str] = field(default_factory=list)
    recomputed_cost_inr: int = 0

    def to_dict(self) -> dict:
        return {"valid": self.valid, "rules_run": self.rules_run,
                "findings": [f.to_dict() for f in self.findings],
                "recomputed_cost_inr": self.recomputed_cost_inr}

    def rules_failed(self) -> set[str]:
        return {f.rule.value for f in self.findings}


@dataclass
class PlannedStop:
    """What the planner decided. Nothing else is trusted."""
    seq: int
    poi_id: int
    arrive_min: int
    depart_min: int


@dataclass
class TripRules:
    start_min: int
    end_min: int
    transition_buffer_min: int
    party_size: int
    budget_total: int | None
    envelope_radius_km: float
    center_lat: float
    center_lon: float
    exploration_radius_km: float
    max_hop_km: float
    must_include_ids: set[int] = field(default_factory=set)
    exclude_ids: set[int] = field(default_factory=set)
    avoid_categories: set[str] = field(default_factory=set)
    avoid_tags: set[str] = field(default_factory=set)
    dietary: list[str] = field(default_factory=list)
    accessibility: list[str] = field(default_factory=list)
    indoor_preference: str | None = None
    kids: bool = False


def validate(stops: list[PlannedStop], rules: TripRules, facts: dict[int, POIRecord],
             *, explanation: str | None = None, fact_numbers: set[str] | None = None
             ) -> ValidatorReport:
    report = ValidatorReport(valid=True, rules_run=list(ALL_RULES))
    f = report.findings
    ordered = sorted(stops, key=lambda s: s.seq)

    # 1. existence -------------------------------------------------------------
    for s in ordered:
        if s.poi_id not in facts:
            f.append(Finding(Rule.EXISTS, s.seq, f"POI {s.poi_id} does not exist or is inactive"))
    known = [s for s in ordered if s.poi_id in facts]

    # 2. geographic scope and 3. coherence ----------------------------------------
    for s in known:
        p = facts[s.poi_id]
        d = haversine_km(rules.center_lat, rules.center_lon, p.lat, p.lon)
        stored = p.distance_from_center_km
        limit = min(rules.envelope_radius_km, rules.exploration_radius_km)
        if stored > limit + BOUNDARY_TOLERANCE_KM:
            f.append(Finding(Rule.SCOPE, s.seq, f"{p.name} is outside the {limit:.0f} km scope",
                             expected=f"<= {limit:.1f} km", actual=f"{stored:.1f} km"))
        elif abs(d - stored) > max(1.0, 0.01 * stored):
            f.append(Finding(Rule.SCOPE, s.seq, f"{p.name} coordinates disagree with its "
                             f"stored distance", expected=f"{stored:.1f} km", actual=f"{d:.1f} km"))
    for a, b in zip(known, known[1:]):
        pa, pb = facts[a.poi_id], facts[b.poi_id]
        hop = haversine_km(pa.lat, pa.lon, pb.lat, pb.lon)
        if hop > rules.max_hop_km + BOUNDARY_TOLERANCE_KM:
            f.append(Finding(Rule.COHERENCE, b.seq, f"{pb.name} is {hop:.1f} km from the "
                             f"previous stop", expected=f"<= {rules.max_hop_km:.0f} km",
                             actual=f"{hop:.1f} km"))

    # 4. duplicates ------------------------------------------------------------------
    seen: set[int] = set()
    for s in ordered:
        if s.poi_id in seen:
            f.append(Finding(Rule.DUPLICATE, s.seq, f"POI {s.poi_id} appears more than once"))
        seen.add(s.poi_id)

    # 5. opening hours (only where the hours are reliable) --------------------------
    for s in known:
        p = facts[s.poi_id]
        if not p.hours_reliable or p.hours_loaded_for_day is None:
            continue
        if p.open_interval_containing(s.arrive_min, s.depart_min) is None:
            f.append(Finding(Rule.HOURS, s.seq, f"{p.name} is not open for the whole visit",
                             actual=f"{_hm(s.arrive_min)}-{_hm(s.depart_min)}",
                             expected=", ".join(f"{_hm(h.open_min)}-{_hm(h.close_min)}"
                                                for h in p.hours) or "closed that day"))

    # 6-8. schedule ---------------------------------------------------------------------
    prev = None
    for s in ordered:
        if s.depart_min < s.arrive_min:
            f.append(Finding(Rule.OVERLAP, s.seq, "departure is before arrival"))
        if s.arrive_min < rules.start_min or s.depart_min > rules.end_min:
            f.append(Finding(Rule.WINDOW, s.seq, "stop falls outside the requested window",
                             expected=f"{_hm(rules.start_min)}-{_hm(rules.end_min)}",
                             actual=f"{_hm(s.arrive_min)}-{_hm(s.depart_min)}"))
        if prev is not None:
            if s.arrive_min < prev.depart_min:
                f.append(Finding(Rule.OVERLAP, s.seq, "visit overlaps the previous stop",
                                 expected=f">= {_hm(prev.depart_min)}", actual=_hm(s.arrive_min)))
            elif s.arrive_min - prev.depart_min < rules.transition_buffer_min:
                f.append(Finding(Rule.BUFFER, s.seq, "gap to the previous stop is shorter than "
                                 "the transition buffer",
                                 expected=f">= {rules.transition_buffer_min} min",
                                 actual=f"{s.arrive_min - prev.depart_min} min"))
        prev = s

    # 9. duration bounds ------------------------------------------------------------------
    for s in known:
        p = facts[s.poi_id]
        visit = s.depart_min - s.arrive_min
        if not (p.visit[0] <= visit <= p.visit[2]):
            f.append(Finding(Rule.DURATION, s.seq, f"{p.name} visit length is outside its "
                             f"known range", expected=f"{p.visit[0]}-{p.visit[2]} min",
                             actual=f"{visit} min"))

    # 10. budget, re-summed from the database -------------------------------------------
    total = sum(facts[s.poi_id].cost[1] for s in known) * rules.party_size
    report.recomputed_cost_inr = total
    if rules.budget_total is not None and total > rules.budget_total:
        f.append(Finding(Rule.BUDGET, None, "re-summed estimated cost exceeds the budget",
                         expected=f"<= ₹{rules.budget_total}", actual=f"₹{total}"))

    # 11. must-include ------------------------------------------------------------------------
    present = {s.poi_id for s in known}
    for pid in sorted(rules.must_include_ids - present):
        f.append(Finding(Rule.MUST, None, f"required place {pid} is missing"))

    # 12. exclusions ---------------------------------------------------------------------------
    for s in known:
        p = facts[s.poi_id]
        if s.poi_id in rules.exclude_ids:
            f.append(Finding(Rule.EXCLUDED, s.seq, f"{p.name} was explicitly excluded"))
        if p.category in rules.avoid_categories:
            f.append(Finding(Rule.EXCLUDED, s.seq, f"{p.name} is in avoided category "
                             f"'{p.category}'"))
        hit = rules.avoid_tags & (set(p.experience_tags) | set(p.mood_tags))
        if hit:
            f.append(Finding(Rule.EXCLUDED, s.seq, f"{p.name} has avoided trait "
                             f"{sorted(hit)}"))

    # 13. explicit requirements --------------------------------------------------------------
    for s in known:
        p = facts[s.poi_id]
        if rules.dietary and p.category in FOOD_CATEGORIES:
            for need in rules.dietary:
                if not DIET_SATISFIES.get(need, {need}) & set(p.dietary_tags):
                    f.append(Finding(Rule.REQUIREMENT, s.seq, f"{p.name} is not verified "
                                     f"{need}"))
        if "wheelchair_accessible" in rules.accessibility and \
                "wheelchair_accessible" not in p.accessibility_tags:
            f.append(Finding(Rule.REQUIREMENT, s.seq, f"{p.name} is not verified wheelchair "
                             "accessible"))
        if rules.indoor_preference == "indoor" and p.indoor_outdoor == "outdoor":
            f.append(Finding(Rule.REQUIREMENT, s.seq, f"{p.name} is outdoors"))
        if rules.kids and p.suitability.get("kids_friendly") is False:
            f.append(Finding(Rule.REQUIREMENT, s.seq, f"{p.name} is not suitable for kids"))

    # 14. unsupported claims in the explanation --------------------------------------------------
    if explanation and fact_numbers is not None:
        for num in unsupported_numbers(explanation, fact_numbers):
            f.append(Finding(Rule.CLAIM, None, f"explanation states '{num}', which no fact "
                             "supports"))

    report.valid = not f
    return report


_NUM_RE = re.compile(r"(?<![\w.])(?:₹\s?)?\d[\d,]*(?:\.\d+)?(?:\s?(?:km|min|minutes|hours|%))?")


def normalize_number(token: str) -> str:
    return re.sub(r"[₹,\s]|km|minutes|min|hours|%", "", token)


def unsupported_numbers(text: str, fact_numbers: set[str]) -> list[str]:
    """Every number in generated text must appear in the fact block (numeric
    entailment). Times like 10:30 are checked as their components."""
    allowed = {normalize_number(n) for n in fact_numbers}
    out = []
    for token in _NUM_RE.findall(text):
        norm = normalize_number(token)
        if norm and norm not in allowed:
            out.append(token.strip())
    return out


def _hm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"
