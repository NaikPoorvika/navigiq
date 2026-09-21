"""NQ-020 - Multi-modal arc builder.

Picks the best mode for each leg BEFORE the optimizer sees it, keeping the
CP-SAT model single-commodity: one duration and one cost per arc.

SELECTION RULE: cheapest within a 25% time tolerance of the fastest viable
mode. Walking is a HARD filter against max_walking_m, never a penalty.

PERFORMANCE: build_matrix makes TWO OSRM /table calls (car, foot) instead of
N^2 individual /route calls. For 21 points that is 2 round trips instead of
420 - arc building went from ~12 s to well under a second, which is what
makes multi-day trips practical.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services.costs.estimator import (
    TransportMode,
    estimate_leg_cost,
    mode_overhead_min,
)
from app.services.routing.service import (
    RoutingService,
    RoutingUnavailable,
    traffic_factor,
)

TIME_TOLERANCE = 0.25
MAX_SINGLE_WALK_M = 2000
ROAD_MODES = ("auto", "cab", "own_car")


@dataclass
class Arc:
    from_idx: int
    to_idx: int
    mode: str
    duration_s: float
    raw_duration_s: float
    distance_m: float
    cost_inr: int
    walk_m: float
    rejected: list[str]
    detail: dict | None = None    # mode-specific breakdown, when relevant

    def to_dict(self) -> dict:
        return {
            "from": self.from_idx, "to": self.to_idx, "mode": self.mode,
            "duration_s": round(self.duration_s, 1),
            "raw_duration_s": round(self.raw_duration_s, 1),
            "distance_m": round(self.distance_m, 1),
            "cost_inr": self.cost_inr,
            "walk_m": round(self.walk_m),
            "alternatives_rejected": self.rejected,
            "basis": "estimate",
        }


@dataclass
class _Candidate:
    mode: str
    duration_s: float
    raw_duration_s: float
    distance_m: float
    cost_inr: int
    walk_m: float
    detail: dict | None = None


def _select(i: int, j: int, candidates: list[_Candidate],
            max_walking_m: float) -> Arc | None:
    """Apply the selection rule. Returns None if no mode is viable."""
    rejected: list[str] = []
    viable = []
    for c in candidates:
        if c.walk_m > max_walking_m:
            rejected.append(f"{c.mode}: {c.walk_m:.0f}m walk exceeds "
                            f"{max_walking_m:.0f}m limit")
        else:
            viable.append(c)
    if not viable:
        return None

    fastest = min(viable, key=lambda c: c.duration_s)
    threshold = fastest.duration_s * (1 + TIME_TOLERANCE)
    within = [c for c in viable if c.duration_s <= threshold]
    winner = min(within, key=lambda c: (c.cost_inr, c.duration_s))

    for c in viable:
        if c is winner:
            continue
        if c.duration_s > threshold:
            over = (c.duration_s / max(fastest.duration_s, 1) - 1) * 100
            rejected.append(f"{c.mode}: {over:.0f}% slower than fastest")
        else:
            rejected.append(f"{c.mode}: Rs {c.cost_inr} vs Rs {winner.cost_inr}")

    return Arc(from_idx=i, to_idx=j, mode=winner.mode,
               duration_s=winner.duration_s,
               raw_duration_s=winner.raw_duration_s,
               distance_m=winner.distance_m, cost_inr=winner.cost_inr,
               walk_m=winner.walk_m, rejected=rejected, detail=winner.detail)


def _road_candidates(distance_m, raw_s, allowed_modes, depart_at,
                     party_size, mid_lat, mid_lon) -> list[_Candidate]:
    factor = traffic_factor("driving", depart_at, mid_lat, mid_lon)
    minute = (depart_at.hour * 60 + depart_at.minute) if depart_at else None
    out = []
    for mode in ROAD_MODES:
        if mode not in allowed_modes:
            continue
        overhead = mode_overhead_min(TransportMode(mode)) * 60
        duration = raw_s * factor + overhead
        cost = estimate_leg_cost(TransportMode(mode), distance_m, duration,
                                 party_size, minute)
        out.append(_Candidate(mode, duration, raw_s, distance_m, cost, 0.0))
    return out


class MultiModalRouter:
    def __init__(self, routing: RoutingService | None = None) -> None:
        self.routing = routing or RoutingService()

    async def build_arc(
        self, from_idx: int, to_idx: int,
        origin: tuple[float, float], destination: tuple[float, float],
        allowed_modes: list[str], depart_at: datetime | None = None,
        party_size: int = 1, max_walking_m: float = 3000,
    ) -> Arc:
        """One arc via individual /route calls. Used for single legs and for
        re-checking chosen legs; bulk planning uses build_matrix."""
        candidates: list[_Candidate] = []
        mid_lat = (origin[0] + destination[0]) / 2
        mid_lon = (origin[1] + destination[1]) / 2

        if "walking" in allowed_modes:
            try:
                r = await self.routing.get_route(origin, destination,
                                                 mode="walking",
                                                 depart_at=depart_at)
                if r.distance_m <= MAX_SINGLE_WALK_M:
                    candidates.append(_Candidate(
                        "walking", r.duration_s, r.raw_duration_s,
                        r.distance_m, 0, r.distance_m))
            except RoutingUnavailable:
                pass

        if any(m in allowed_modes for m in ROAD_MODES):
            try:
                r = await self.routing.get_route(origin, destination,
                                                 mode="driving",
                                                 depart_at=depart_at)
                candidates += _road_candidates(
                    r.distance_m, r.raw_duration_s, allowed_modes, depart_at,
                    party_size, mid_lat, mid_lon)
            except RoutingUnavailable:
                pass

        arc = _select(from_idx, to_idx, candidates, max_walking_m)
        if arc is None:
            raise RoutingUnavailable(
                f"no viable mode for arc {from_idx}->{to_idx}")
        return arc

    async def build_matrix(
        self, points: list[tuple[float, float]], allowed_modes: list[str],
        depart_at: datetime | None = None, party_size: int = 1,
        max_walking_m: float = 3000,
    ) -> list[list[Arc | None]]:
        """N x N arcs from two OSRM /table calls. Feeds CP-SAT (NQ-023)."""
        n = len(points)
        need_road = any(m in allowed_modes for m in ROAD_MODES)
        need_walk = "walking" in allowed_modes

        car = (await self.routing.get_matrix(points, mode="driving",
                                             depart_at=depart_at)
               if need_road else None)
        foot = (await self.routing.get_matrix(points, mode="walking",
                                              depart_at=depart_at)
                if need_walk else None)

        arcs: list[list[Arc | None]] = [[None] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                candidates: list[_Candidate] = []

                if foot is not None:
                    d = foot.distances[i][j]
                    t = foot.raw_durations[i][j]
                    if d is not None and t is not None and d <= MAX_SINGLE_WALK_M:
                        candidates.append(_Candidate(
                            "walking", float(t), float(t), float(d), 0, float(d)))

                if car is not None:
                    d = car.distances[i][j]
                    t = car.raw_durations[i][j]
                    if d is not None and t is not None:
                        mid_lat = (points[i][0] + points[j][0]) / 2
                        mid_lon = (points[i][1] + points[j][1]) / 2
                        candidates += _road_candidates(
                            float(d), float(t), allowed_modes, depart_at,
                            party_size, mid_lat, mid_lon)

                arcs[i][j] = _select(i, j, candidates, max_walking_m)
        return arcs