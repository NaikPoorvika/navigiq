"""NQ-020 - Multi-modal arc builder.

Picks the best mode for each leg BEFORE the optimizer sees it. This keeps
the CP-SAT model single-commodity: the optimizer reasons about one duration
and one cost per arc, not a mode choice per arc.

SELECTION RULE: cheapest within a time tolerance.
  Fastest-wins would mean metro is never chosen - Indiranagar to Lalbagh is
  47 min by metro against ~25 by auto. A rule that guarantees a mode is
  never selected makes building it pointless. This instead matches how
  people travel: take the cheaper option if it is not much slower.

HARD CONSTRAINT: an arc whose walking distance exceeds the trip's
max_walking_km is rejected outright, not penalised.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services.costs.estimator import (
    TransportMode,
    estimate_leg_cost,
    mode_overhead_min,
)

from app.services.routing.service import RoutingService, RoutingUnavailable

# Accept a mode up to this much slower than the fastest if it costs less.
TIME_TOLERANCE = 0.25

# Beyond this, walking stops being a viable mode for a single leg regardless
# of the trip-level cap.
MAX_SINGLE_WALK_M = 2000


@dataclass
class Arc:
    """One leg, with its chosen mode already decided."""
    from_idx: int
    to_idx: int
    mode: str
    duration_s: float
    raw_duration_s: float
    distance_m: float
    cost_inr: int
    walk_m: float
    rejected: list[str]           # modes considered and why they lost
    detail: dict | None = None    # metro leg breakdown, when relevant

    def to_dict(self) -> dict:
        return {
            "from": self.from_idx,
            "to": self.to_idx,
            "mode": self.mode,
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


class MultiModalRouter:
    def __init__(self, routing: RoutingService | None = None) -> None:
        self.routing = routing or RoutingService()

    async def _walking(self, o, d, depart_at) -> _Candidate | None:
        try:
            r = await self.routing.get_route(o, d, mode="walking",
                                             depart_at=depart_at)
        except RoutingUnavailable:
            return None
        if r.distance_m > MAX_SINGLE_WALK_M:
            return None
        return _Candidate("walking", r.duration_s, r.raw_duration_s,
                          r.distance_m, 0, r.distance_m)

    async def _road(self, mode, o, d, depart_at, party_size) -> _Candidate | None:
        try:
            overhead = mode_overhead_min(TransportMode(mode)) * 60
            r = await self.routing.get_route(o, d, mode="driving",
                                             depart_at=depart_at,
                                             overhead_s=overhead)
        except RoutingUnavailable:
            return None
        minute = (depart_at.hour * 60 + depart_at.minute) if depart_at else None
        cost = estimate_leg_cost(TransportMode(mode), r.distance_m,
                                 r.duration_s, party_size, minute)
        return _Candidate(mode, r.duration_s, r.raw_duration_s,
                          r.distance_m, cost, 0.0)

    def _metro(self, o, d, depart_at, party_size) -> _Candidate | None:
        try:
            r = self.metro.route(o, d, depart_at)
        except MetroUnavailable:
            return None
        walk_m = r.access_walk_m + r.egress_walk_m
        return _Candidate("metro", r.total_duration_s, r.total_duration_s,
                          r.network_km * 1000, r.fare_inr * party_size,
                          walk_m, r.to_dict())

    async def build_arc(
        self,
        from_idx: int,
        to_idx: int,
        origin: tuple[float, float],
        destination: tuple[float, float],
        allowed_modes: list[str],
        depart_at: datetime | None = None,
        party_size: int = 1,
        max_walking_m: float = 3000,
    ) -> Arc:
        """Evaluate every allowed mode, return the winner under the rule."""
        candidates: list[_Candidate] = []

        if "walking" in allowed_modes:
            c = await self._walking(origin, destination, depart_at)
            if c:
                candidates.append(c)

        for mode in ("auto", "cab", "own_car"):
            if mode in allowed_modes:
                c = await self._road(mode, origin, destination,
                                     depart_at, party_size)
                if c:
                    candidates.append(c)

        if "metro" in allowed_modes:
            c = self._metro(origin, destination, depart_at, party_size)
            if c:
                candidates.append(c)

        rejected: list[str] = []

        # Hard filter: walking cap. Rejected, never penalised.
        viable = []
        for c in candidates:
            if c.walk_m > max_walking_m:
                rejected.append(f"{c.mode}: {c.walk_m:.0f}m walk exceeds "
                                f"{max_walking_m:.0f}m limit")
            else:
                viable.append(c)

        if not viable:
            raise RoutingUnavailable(
                f"no viable mode for arc {from_idx}->{to_idx} "
                f"(considered {[c.mode for c in candidates]})")

        fastest = min(viable, key=lambda c: c.duration_s)
        threshold = fastest.duration_s * (1 + TIME_TOLERANCE)

        within = [c for c in viable if c.duration_s <= threshold]
        winner = min(within, key=lambda c: (c.cost_inr, c.duration_s))

        for c in viable:
            if c is winner:
                continue
            if c.duration_s > threshold:
                over = (c.duration_s / fastest.duration_s - 1) * 100
                rejected.append(f"{c.mode}: {over:.0f}% slower than fastest")
            else:
                rejected.append(f"{c.mode}: Rs {c.cost_inr} vs Rs {winner.cost_inr}")

        return Arc(
            from_idx=from_idx, to_idx=to_idx, mode=winner.mode,
            duration_s=winner.duration_s, raw_duration_s=winner.raw_duration_s,
            distance_m=winner.distance_m, cost_inr=winner.cost_inr,
            walk_m=winner.walk_m, rejected=rejected, detail=winner.detail,
        )

    async def build_matrix(
        self,
        points: list[tuple[float, float]],
        allowed_modes: list[str],
        depart_at: datetime | None = None,
        party_size: int = 1,
        max_walking_m: float = 3000,
    ) -> list[list[Arc | None]]:
        """N x N arcs. Feeds the CP-SAT optimizer in NQ-023.

        O(n^2) OSRM calls. At the 50-candidate cap that is 2,450 arcs, which
        is why NQ-023 must cut candidates before this is called.
        """
        n = len(points)
        arcs: list[list[Arc | None]] = [[None] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                try:
                    arcs[i][j] = await self.build_arc(
                        i, j, points[i], points[j], allowed_modes,
                        depart_at, party_size, max_walking_m)
                except RoutingUnavailable:
                    arcs[i][j] = None
        return arcs