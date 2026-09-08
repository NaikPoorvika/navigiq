"""NQ-019 - Routing service.

Wraps self-hosted OSRM with retries, a circuit breaker, Redis caching and
the static time-of-day traffic multiplier.

TWO DURATIONS ARE ALWAYS RETURNED:
  raw_duration_s      - what OSRM computed (free-flow)
  duration_s          - after the traffic multiplier and mode overhead

The UI and the validator both need to distinguish these. Presenting the
adjusted figure as if it were measured would be dishonest; presenting the
raw figure would produce itineraries that are systematically too tight.

SRM HAS NO LIVE TRAFFIC AND NO TRANSIT. NavigIQ has no public transit support (ADR-020).

ON FAILURE: raises RoutingUnavailable. The planner must NOT substitute a
guessed distance into a delivered itinerary - an honest error beats a
confident fiction. Haversine is used only for the feasibility lower bound
in NQ-022, never for a plan shown to a user.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import lru_cache
from pathlib import Path

import httpx
import yaml

CONFIG_PATH = (Path(__file__).resolve().parents[4]
               / "data" / "config" / "traffic_factors.yaml")

OSRM_CAR_URL = "http://localhost:5000"
OSRM_FOOT_URL = "http://localhost:5001"

TIMEOUT_S = 4.0
MAX_RETRIES = 2
BREAKER_THRESHOLD = 5        # consecutive failures before opening
BREAKER_RESET_S = 60
CACHE_TTL_S = 86_400         # geometry is static; the time bucket is in the key
MAX_MATRIX_POINTS = 60


class RoutingMode(str, Enum):
    DRIVING = "driving"
    WALKING = "walking"
    CYCLING = "cycling"


class RoutingUnavailable(RuntimeError):
    """OSRM is unreachable or returned no route. Never swallowed."""


@dataclass
class Route:
    distance_m: float
    duration_s: float           # adjusted
    raw_duration_s: float       # as OSRM returned it
    traffic_factor: float
    overhead_s: int
    geometry: str | None
    mode: str

    def to_dict(self) -> dict:
        return {
            "distance_m": round(self.distance_m, 1),
            "duration_s": round(self.duration_s, 1),
            "raw_duration_s": round(self.raw_duration_s, 1),
            "traffic_factor_applied": round(self.traffic_factor, 3),
            "overhead_s": self.overhead_s,
            "geometry": self.geometry,
            "mode": self.mode,
            "basis": "estimate",
        }


@dataclass
class Matrix:
    durations: list[list[float]]        # adjusted, seconds
    distances: list[list[float]]
    raw_durations: list[list[float]]
    traffic_factor: float
    mode: str


@lru_cache(maxsize=1)
def _config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def area_class(lat: float, lon: float) -> str:
    cfg = _config()["area_boundaries"]
    km = _haversine_km((lat, lon), (cfg["centre_lat"], cfg["centre_lon"]))
    if km <= cfg["core_radius_km"]:
        return "core"
    if km <= cfg["ring_radius_km"]:
        return "ring"
    return "outer"


def traffic_factor(
    mode: str,
    depart_at: datetime | None,
    lat: float | None = None,
    lon: float | None = None,
) -> float:
    """Static multiplier. NOT a traffic model - see traffic_factors.yaml."""
    cfg = _config()

    if mode in cfg["unaffected_modes"] or mode == RoutingMode.WALKING.value:
        return 1.0
    if depart_at is None:
        return 1.0

    minute = depart_at.hour * 60 + depart_at.minute
    is_weekend = depart_at.weekday() >= 5
    key = "weekend" if is_weekend else "weekday"

    factor = 1.0
    for b in cfg["buckets"]:
        if b["start"] <= minute < b["end"]:
            factor = float(b[key])
            break

    if lat is not None and lon is not None:
        factor *= cfg["area_multipliers"][area_class(lat, lon)]

    if mode in ("cycling", "bike"):
        # Bicycles are slowed by congestion, but far less than cars.
        factor = 1.0 + (factor - 1.0) * cfg["bike_dampening"]

    return round(factor, 3)


def _time_bucket(depart_at: datetime | None) -> str:
    """Cache key component. Without it, peak and off-peak collapse into one
    wrong answer."""
    if depart_at is None:
        return "none"
    minute = depart_at.hour * 60 + depart_at.minute
    day = "we" if depart_at.weekday() >= 5 else "wd"
    for b in _config()["buckets"]:
        if b["start"] <= minute < b["end"]:
            return f"{day}:{b['name']}"
    return f"{day}:unknown"


class _Breaker:
    """Opens after repeated failures so a dead OSRM does not cost every
    request a full timeout."""

    def __init__(self) -> None:
        self.failures = 0
        self.opened_at: float | None = None

    def is_open(self, now: float) -> bool:
        if self.opened_at is None:
            return False
        if now - self.opened_at >= BREAKER_RESET_S:
            self.opened_at = None
            self.failures = 0
            return False
        return True

    def record_failure(self, now: float) -> None:
        self.failures += 1
        if self.failures >= BREAKER_THRESHOLD:
            self.opened_at = now

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None


class RoutingService:
    def __init__(
        self,
        car_url: str = OSRM_CAR_URL,
        foot_url: str = OSRM_FOOT_URL,
        cache=None,
    ) -> None:
        self.urls = {
            RoutingMode.DRIVING.value: car_url,
            RoutingMode.CYCLING.value: car_url,   # no bike graph built
            RoutingMode.WALKING.value: foot_url,
        }
        self.cache = cache          # any object with get/set; None disables
        self._breakers: dict[str, _Breaker] = {}

    def _breaker(self, mode: str) -> _Breaker:
        return self._breakers.setdefault(mode, _Breaker())

    async def _call(self, mode: str, path: str, params: dict) -> dict:
        import time
        now = time.monotonic()
        breaker = self._breaker(mode)

        if breaker.is_open(now):
            raise RoutingUnavailable(f"OSRM circuit open for {mode}")

        base = self.urls.get(mode)
        if base is None:
            raise RoutingUnavailable(f"no OSRM profile for mode {mode}")

        last: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                    r = await client.get(f"{base}{path}", params=params)
                    r.raise_for_status()
                    data = r.json()
                if data.get("code") != "Ok":
                    raise RoutingUnavailable(
                        f"OSRM returned {data.get('code')}: "
                        f"{data.get('message', '')}")
                breaker.record_success()
                return data
            except RoutingUnavailable:
                breaker.record_success()   # a NoRoute is a valid answer
                raise
            except Exception as exc:       # noqa: BLE001
                last = exc
                if attempt == MAX_RETRIES:
                    breaker.record_failure(now)

        raise RoutingUnavailable(f"OSRM unreachable for {mode}: {last}")

    async def get_route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        mode: str = RoutingMode.DRIVING.value,
        depart_at: datetime | None = None,
        overhead_s: int = 0,
        include_geometry: bool = True,
    ) -> Route:
        """One leg. origin/destination are (lat, lon)."""
        key = (f"route:{mode}:{origin[0]:.5f},{origin[1]:.5f}:"
               f"{destination[0]:.5f},{destination[1]:.5f}:"
               f"{_time_bucket(depart_at)}:{int(include_geometry)}")

        cached = await self._cache_get(key)
        if cached is None:
            coords = f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
            data = await self._call(
                mode, f"/route/v1/{mode}/{coords}",
                {"overview": "simplified" if include_geometry else "false",
                 "geometries": "polyline"},
            )
            route = data["routes"][0]
            cached = {
                "distance_m": route["distance"],
                "raw_duration_s": route["duration"],
                "geometry": route.get("geometry") if include_geometry else None,
            }
            await self._cache_set(key, cached)

        # Use the leg midpoint, not the origin: a trip from ring into core hits
        # core congestion at the destination end.
        mid_lat = (origin[0] + destination[0]) / 2
        mid_lon = (origin[1] + destination[1]) / 2
        factor = traffic_factor(mode, depart_at, mid_lat, mid_lon)
        raw = cached["raw_duration_s"]
        return Route(
            distance_m=cached["distance_m"],
            duration_s=raw * factor + overhead_s,
            raw_duration_s=raw,
            traffic_factor=factor,
            overhead_s=overhead_s,
            geometry=cached["geometry"],
            mode=mode,
        )

    async def get_matrix(
        self,
        points: list[tuple[float, float]],
        mode: str = RoutingMode.DRIVING.value,
        depart_at: datetime | None = None,
    ) -> Matrix:
        """N x N durations and distances. Feeds the CP-SAT optimizer."""
        if len(points) > MAX_MATRIX_POINTS:
            raise ValueError(
                f"{len(points)} points exceeds MAX_MATRIX_POINTS "
                f"({MAX_MATRIX_POINTS}); OSRM is started with "
                f"--max-table-size 100")

        coords = ";".join(f"{lon},{lat}" for lat, lon in points)
        data = await self._call(
            mode, f"/table/v1/{mode}/{coords}",
            {"annotations": "duration,distance"},
        )

        raw = data["durations"]
        centre_lat = sum(p[0] for p in points) / len(points)
        centre_lon = sum(p[1] for p in points) / len(points)
        factor = traffic_factor(mode, depart_at, centre_lat, centre_lon)

        return Matrix(
            durations=[[(v or 0.0) * factor for v in row] for row in raw],
            distances=data.get("distances")
                      or [[0.0] * len(points) for _ in points],
            raw_durations=raw,
            traffic_factor=factor,
            mode=mode,
        )

    # --- cache: degrades to a no-op, never raises into a request ----------

    async def _cache_get(self, key: str) -> dict | None:
        if self.cache is None:
            return None
        try:
            raw = await self.cache.get(key)
            return json.loads(raw) if raw else None
        except Exception:   # noqa: BLE001
            return None

    async def _cache_set(self, key: str, value: dict) -> None:
        if self.cache is None:
            return
        try:
            await self.cache.set(key, json.dumps(value), ex=CACHE_TTL_S)
        except Exception:   # noqa: BLE001
            pass

