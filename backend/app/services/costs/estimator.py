"""NQ-015 - Cost estimation.

ONE implementation, consumed by the optimizer, the validator and the API.
Three implementations would produce three different totals for the same trip.

Money is integer rupees. Never floats - rounding drift across 5 legs and 4
stops produces totals that do not reconcile with what the user is shown.

Every result carries basis="estimate". Nothing here is live pricing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[4] / "data" / "config" / "fares.yaml"


class TransportMode(str, Enum):
    WALKING = "walking"
    METRO = "metro"
    AUTO = "auto"
    CAB = "cab"
    OWN_CAR = "own_car"
    BIKE = "bike"


@dataclass(frozen=True)
class CostLine:
    label: str
    amount_inr: int
    basis: str = "estimate"


@dataclass
class CostBreakdown:
    lines: list[CostLine] = field(default_factory=list)
    unknown_count: int = 0

    @property
    def total_inr(self) -> int:
        return sum(line.amount_inr for line in self.lines)

    def add(self, label: str, amount: int, basis: str = "estimate") -> None:
        self.lines.append(CostLine(label, int(round(amount)), basis))

    def to_dict(self) -> dict:
        return {
            "total_inr": self.total_inr,
            "currency": "INR",
            "basis": "estimate",
            "unknown_cost_items": self.unknown_count,
            "lines": [
                {"label": l.label, "amount_inr": l.amount_inr, "basis": l.basis}
                for l in self.lines
            ],
        }


@lru_cache(maxsize=1)
def _config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def config_valid_from() -> str:
    """Surfaced in API responses so stale fare data is visible, not hidden."""
    return str(_config()["valid_from"])


def estimate_leg_cost(
    mode: TransportMode,
    distance_m: float,
    duration_s: float,
    party_size: int = 1,
    depart_min_of_day: int | None = None,
) -> int:
    """Cost of one travel leg, in whole rupees.

    Auto, cab and own_car are per-vehicle: party size does not multiply them
    up to 4 people. Metro is per-person.
    """
    cfg = _config()
    km = distance_m / 1000.0

    if mode in (TransportMode.WALKING, TransportMode.BIKE):
        return 0

    if mode == TransportMode.METRO:
        for band in cfg["metro"]["bands"]:
            if km <= band["max_km"]:
                return int(band["fare"]) * party_size
        return int(cfg["metro"]["bands"][-1]["fare"]) * party_size

    if mode == TransportMode.OWN_CAR:
        c = cfg["own_car"]
        return int(round(km * c["per_km"] + c["parking_flat"]))

    c = cfg["auto"] if mode == TransportMode.AUTO else cfg["cab"]
    if km <= c["minimum_km"]:
        fare = float(c["minimum_fare"])
    else:
        fare = c["minimum_fare"] + (km - c["minimum_km"]) * c["per_km"]

    if mode == TransportMode.AUTO and depart_min_of_day is not None:
        night_start, night_end = c["night_start_min"], c["night_end_min"]
        is_night = (depart_min_of_day >= night_start
                    or depart_min_of_day < night_end)
        if is_night:
            fare *= c["night_multiplier"]

    if mode == TransportMode.CAB:
        fare *= cfg["cab"]["surge_multiplier"]

    return int(round(fare))


def mode_overhead_min(mode: TransportMode) -> int:
    """Time beyond pure travel: hailing, waiting, parking, station access.

    The optimizer must include this or every itinerary is optimistic by
    5-8 minutes per leg, which compounds badly across four stops.
    """
    cfg = _config()
    return {
        TransportMode.AUTO: cfg["auto"]["hail_overhead_min"],
        TransportMode.CAB: cfg["cab"]["hail_overhead_min"],
        TransportMode.OWN_CAR: cfg["own_car"]["parking_overhead_min"],
        TransportMode.METRO: cfg["metro"]["access_overhead_min"],
    }.get(mode, 0)


def estimate_poi_cost(
    cost_estimate_inr: int | None,
    category_typical_inr: int,
    party_size: int = 1,
) -> tuple[int, str]:
    """Return (amount, basis).

    An unknown cost must NEVER be treated as free - the optimizer would then
    systematically prefer unpriced POIs. Fall back to the category median and
    say so.
    """
    if cost_estimate_inr is not None:
        return int(cost_estimate_inr) * party_size, "poi_specific"
    return int(category_typical_inr) * party_size, "category_median"


def estimate_trip_cost(
    stops: list[dict],
    legs: list[dict],
    party_size: int = 1,
) -> CostBreakdown:
    """Itemized trip cost.

    stops: [{name, cost_estimate_inr | None, category_typical_inr}]
    legs:  [{mode, distance_m, duration_s, depart_min_of_day | None}]
    """
    bd = CostBreakdown()

    for stop in stops:
        amount, basis = estimate_poi_cost(
            stop.get("cost_estimate_inr"),
            stop.get("category_typical_inr", 0),
            party_size,
        )
        if basis == "category_median" and amount > 0:
            bd.unknown_count += 1
        if amount:
            bd.add(stop.get("name", "stop"), amount, basis)

    for i, leg in enumerate(legs, start=1):
        mode = TransportMode(leg["mode"])
        amount = estimate_leg_cost(
            mode, leg["distance_m"], leg["duration_s"],
            party_size, leg.get("depart_min_of_day"),
        )
        if amount:
            bd.add(f"leg {i} ({mode.value})", amount)

    return bd
