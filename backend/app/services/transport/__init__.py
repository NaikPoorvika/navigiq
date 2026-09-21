"""Transportation abstraction (ADR-022).

Transportation is DEFERRED in this version: no routing, ETAs, fares, traffic
or live-trip features. Core planning never imports a router; it asks the
configured TransportationProvider, which today is the Null provider and
contributes nothing but the honest note shown on every itinerary.

The OSRM-backed routing service and multi-modal arc builder from NQ-018..020
are preserved under app.services.routing so a future provider can wrap them
without redesigning the planner: the optimizer already accepts per-arc
durations and costs, and the planner only has to swap the constant
transition buffer for provider legs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

TRANSITION_NOTE = ("Transition buffers are included between stops. Actual transportation "
                   "time is not calculated in this version.")


@dataclass(frozen=True)
class Leg:
    duration_min: int
    distance_km: float
    cost_inr: int
    mode: str


@runtime_checkable
class TransportationProvider(Protocol):
    name: str
    enabled: bool

    async def leg(self, a: tuple[float, float], b: tuple[float, float]) -> Leg | None: ...

    def note(self) -> str: ...


class NullTransportationProvider:
    """Provides no legs. The planner uses transition buffers instead and never
    converts distance into time."""
    name = "none"
    enabled = False

    async def leg(self, a: tuple[float, float], b: tuple[float, float]) -> Leg | None:
        return None

    def note(self) -> str:
        return TRANSITION_NOTE


def get_transportation_provider() -> TransportationProvider:
    from app.config import settings
    if settings.TRANSPORTATION_PROVIDER not in ("null", "none", ""):
        raise RuntimeError(
            f"TRANSPORTATION_PROVIDER={settings.TRANSPORTATION_PROVIDER!r} is not available in "
            "this version; transportation is deferred (ADR-022)")
    return NullTransportationProvider()
