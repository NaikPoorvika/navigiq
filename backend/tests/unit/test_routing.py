"""Tests for NQ-019 routing service.

Pure-function tests for the traffic model. OSRM-dependent tests are marked
and skipped when the container is not running, so the suite stays green
without infrastructure.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.routing.service import (  # noqa: E402
    RoutingService,
    RoutingUnavailable,
    area_class,
    traffic_factor,
)

INDIRANAGAR = (12.9784, 77.6408)
CUBBON = (12.9716, 77.5946)
LALBAGH = (12.9489, 77.5867)

SAT_1800 = datetime(2026, 9, 5, 18, 0)
TUE_0900 = datetime(2026, 9, 8, 9, 0)
TUE_1400 = datetime(2026, 9, 8, 14, 0)
TUE_0300 = datetime(2026, 9, 8, 3, 0)


def _osrm_up() -> bool:
    try:
        r = httpx.get("http://localhost:5000/route/v1/driving/"
                      "77.6408,12.9784;77.5946,12.9716?overview=false",
                      timeout=2.0)
        return r.json().get("code") == "Ok"
    except Exception:  # noqa: BLE001
        return False


needs_osrm = pytest.mark.skipif(not _osrm_up(), reason="OSRM not running")


# --- traffic factor: pure, always runs -----------------------------------

def test_no_departure_time_means_no_adjustment():
    """Without a time we have no basis for an assumption, so apply none."""
    assert traffic_factor("driving", None) == 1.0


def test_walking_is_never_adjusted():
    assert traffic_factor("walking", TUE_0900, *INDIRANAGAR) == 1.0





def test_weekday_peak_exceeds_weekend_peak():
    wd = traffic_factor("driving", TUE_0900, *CUBBON)
    we = traffic_factor("driving", datetime(2026, 9, 5, 9, 0), *CUBBON)
    assert wd > we


def test_peak_exceeds_midday():
    assert (traffic_factor("driving", TUE_0900, *CUBBON)
            > traffic_factor("driving", TUE_1400, *CUBBON))


def test_night_is_faster_than_free_flow():
    """Empty roads at 03:00 beat the speed-limit estimate."""
    assert traffic_factor("driving", TUE_0300, *CUBBON) < 1.0


def test_core_is_worse_than_outer():
    core = traffic_factor("driving", TUE_0900, *CUBBON)
    outer = traffic_factor("driving", TUE_0900, 13.3702, 77.6835)
    assert core > outer


def test_cycling_is_dampened_relative_to_driving():
    """Bicycles are slowed by congestion, but far less than cars."""
    car = traffic_factor("driving", TUE_0900, *CUBBON)
    bike = traffic_factor("cycling", TUE_0900, *CUBBON)
    assert 1.0 < bike < car


@pytest.mark.parametrize("point,expected", [
    (CUBBON, "core"),
    (INDIRANAGAR, "ring"),
    ((13.3702, 77.6835), "outer"),
])
def test_area_classification(point, expected):
    assert area_class(*point) == expected


# --- OSRM-dependent ------------------------------------------------------

@needs_osrm
async def test_route_returns_plausible_values():
    r = await RoutingService().get_route(INDIRANAGAR, CUBBON)
    assert 5000 < r.distance_m < 9000, f"{r.distance_m}m"
    assert 300 < r.raw_duration_s < 900
    assert r.geometry


@needs_osrm
async def test_raw_and_adjusted_are_both_reported():
    """The UI must be able to say 'estimated' honestly, and the validator
    needs the unmodified figure."""
    r = await RoutingService().get_route(INDIRANAGAR, CUBBON, depart_at=TUE_0900)
    assert r.adjusted_is_slower if hasattr(r, "adjusted_is_slower") \
        else r.duration_s > r.raw_duration_s
    assert r.traffic_factor > 1.0
    d = r.to_dict()
    assert d["basis"] == "estimate"
    assert "raw_duration_s" in d and "traffic_factor_applied" in d


@needs_osrm
async def test_overhead_is_added_on_top():
    svc = RoutingService()
    a = await svc.get_route(INDIRANAGAR, CUBBON)
    b = await svc.get_route(INDIRANAGAR, CUBBON, overhead_s=300)
    assert b.duration_s == pytest.approx(a.duration_s + 300, abs=1)


@needs_osrm
async def test_walking_uses_the_foot_profile():
    """A walking leg must be slower than the same distance driven."""
    r = await RoutingService().get_route(INDIRANAGAR, (12.9760, 77.6350),
                                         mode="walking")
    speed_kmh = (r.distance_m / 1000) / (r.duration_s / 3600)
    assert 3.0 < speed_kmh < 7.0, f"{speed_kmh:.1f} km/h is not walking pace"


@needs_osrm
async def test_matrix_shape_and_diagonal():
    m = await RoutingService().get_matrix([INDIRANAGAR, CUBBON, LALBAGH])
    assert len(m.durations) == 3 and all(len(r) == 3 for r in m.durations)
    assert all(m.durations[i][i] == 0 for i in range(3))


@needs_osrm
async def test_matrix_is_asymmetric():
    """One-way roads mean A->B and B->A differ. A symmetric matrix would
    mean the routing engine is not being consulted properly."""
    m = await RoutingService().get_matrix([INDIRANAGAR, CUBBON])
    assert m.durations[0][1] != m.durations[1][0]


@needs_osrm
async def test_matrix_rejects_oversized_request():
    """OSRM is started with --max-table-size 100. Exceeding it silently
    truncates, which surfaces later as an optimizer bug."""
    points = [(12.97 + i * 0.001, 77.59) for i in range(61)]
    with pytest.raises(ValueError, match="MAX_MATRIX_POINTS"):
        await RoutingService().get_matrix(points)


async def test_unreachable_osrm_raises_rather_than_guessing():
    """THE rule: never substitute an estimated distance into a delivered
    itinerary. An honest error beats a confident fiction."""
    svc = RoutingService(car_url="http://localhost:59999")
    with pytest.raises(RoutingUnavailable):
        await svc.get_route(INDIRANAGAR, CUBBON)


async def test_unknown_mode_raises():
    with pytest.raises(RoutingUnavailable, match="no OSRM profile"):
        await RoutingService().get_route(INDIRANAGAR, CUBBON, mode="teleport")
