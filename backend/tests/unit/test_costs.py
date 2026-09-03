"""Tests for NQ-015 cost estimation."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.costs.estimator import (  # noqa: E402
    TransportMode,
    estimate_leg_cost,
    estimate_poi_cost,
    estimate_trip_cost,
    mode_overhead_min,
)


def test_walking_and_bike_are_free():
    assert estimate_leg_cost(TransportMode.WALKING, 3000, 2400) == 0
    assert estimate_leg_cost(TransportMode.BIKE, 5000, 1200) == 0


def test_auto_minimum_fare_applies_below_threshold():
    """Under 2 km the minimum fare applies, not per-km."""
    assert estimate_leg_cost(TransportMode.AUTO, 500, 200) == 30
    assert estimate_leg_cost(TransportMode.AUTO, 2000, 400) == 30


def test_auto_per_km_above_threshold():
    # 5 km = 30 + (5-2)*15 = 75
    assert estimate_leg_cost(TransportMode.AUTO, 5000, 900) == 75


def test_auto_night_multiplier():
    day = estimate_leg_cost(TransportMode.AUTO, 5000, 900, depart_min_of_day=14 * 60)
    night = estimate_leg_cost(TransportMode.AUTO, 5000, 900, depart_min_of_day=23 * 60)
    early = estimate_leg_cost(TransportMode.AUTO, 5000, 900, depart_min_of_day=2 * 60)
    assert night == pytest.approx(day * 1.5, abs=1)
    assert early == night, "02:00 is still night"


def test_cab_costs_more_than_auto():
    auto = estimate_leg_cost(TransportMode.AUTO, 6000, 1000)
    cab = estimate_leg_cost(TransportMode.CAB, 6000, 1000)
    assert cab > auto


def test_vehicle_modes_are_per_vehicle_not_per_person():
    """Four people share one auto - the fare must not quadruple."""
    solo = estimate_leg_cost(TransportMode.AUTO, 5000, 900, party_size=1)
    four = estimate_leg_cost(TransportMode.AUTO, 5000, 900, party_size=4)
    assert solo == four


def test_metro_is_per_person():
    solo = estimate_leg_cost(TransportMode.METRO, 5000, 900, party_size=1)
    four = estimate_leg_cost(TransportMode.METRO, 5000, 900, party_size=4)
    assert four == solo * 4


@pytest.mark.parametrize("km,expected", [(1, 10), (3, 20), (5, 30), (10, 50), (50, 90)])
def test_metro_distance_bands(km, expected):
    assert estimate_leg_cost(TransportMode.METRO, km * 1000, 600) == expected


def test_own_car_includes_parking():
    # 5 km = 5*8 + 40 = 80
    assert estimate_leg_cost(TransportMode.OWN_CAR, 5000, 900) == 80


def test_zero_distance_leg():
    for mode in TransportMode:
        assert estimate_leg_cost(mode, 0, 0) >= 0


def test_mode_overhead_is_nonzero_for_vehicles():
    assert mode_overhead_min(TransportMode.AUTO) > 0
    assert mode_overhead_min(TransportMode.CAB) > 0
    assert mode_overhead_min(TransportMode.METRO) > 0
    assert mode_overhead_min(TransportMode.WALKING) == 0


def test_unknown_poi_cost_falls_back_to_category_median_not_zero():
    """If unknown meant free, the optimizer would systematically prefer
    unpriced POIs over priced ones."""
    amount, basis = estimate_poi_cost(None, 300, party_size=1)
    assert amount == 300
    assert basis == "category_median"


def test_known_poi_cost_wins_over_category():
    amount, basis = estimate_poi_cost(150, 300, party_size=1)
    assert amount == 150
    assert basis == "poi_specific"


def test_poi_cost_multiplies_by_party_size():
    amount, _ = estimate_poi_cost(200, 300, party_size=3)
    assert amount == 600


def test_trip_total_reconciles_with_line_items():
    stops = [
        {"name": "Toit", "cost_estimate_inr": 900, "category_typical_inr": 800},
        {"name": "Cubbon Park", "cost_estimate_inr": 0, "category_typical_inr": 0},
        {"name": "Museum", "cost_estimate_inr": None, "category_typical_inr": 100},
    ]
    legs = [
        {"mode": "auto", "distance_m": 6000, "duration_s": 1000},
        {"mode": "walking", "distance_m": 800, "duration_s": 600},
    ]
    bd = estimate_trip_cost(stops, legs, party_size=1)
    assert bd.total_inr == sum(l.amount_inr for l in bd.lines)
    assert bd.unknown_count == 1, "museum cost was unknown"
    d = bd.to_dict()
    assert d["basis"] == "estimate"
    assert d["total_inr"] == bd.total_inr


def test_all_amounts_are_integers():
    """Money is integer rupees. Float drift across legs produces totals that
    do not reconcile with what the user is shown."""
    bd = estimate_trip_cost(
        [{"name": "x", "cost_estimate_inr": 333, "category_typical_inr": 0}],
        [{"mode": "auto", "distance_m": 3333, "duration_s": 777}],
    )
    for line in bd.lines:
        assert isinstance(line.amount_inr, int)
    assert isinstance(bd.total_inr, int)
