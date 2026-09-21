"""Geography: the 90 km envelope (RELEASE-CRITICAL, section 83), region
buckets, and the distance functions they rest on."""
from __future__ import annotations

import math

import pytest
from hypothesis import given, settings as hsettings, strategies as st

from app.geo import haversine_km
from app.geo.distance import destination_point
from app.geo.regions import (
    BOUNDARY_TOLERANCE_KM, RegionBucket, destination_point_geodesic, distance_from_center_km, geo_config, geodesic_km,
    in_envelope, region_bucket,
)

CFG = geo_config()
BEARINGS = [0, 37, 90, 145, 180, 233, 270, 315]


@pytest.mark.parametrize("bearing", BEARINGS)
def test_89_9_km_is_included(bearing):
    lat, lon = destination_point_geodesic(CFG.center_lat, CFG.center_lon, bearing, 89.9)
    d = distance_from_center_km(lat, lon)
    assert in_envelope(d)
    assert region_bucket(d) == RegionBucket.NEARBY_ESCAPE


@pytest.mark.parametrize("bearing", BEARINGS)
def test_90_0_km_is_included_inclusive_rule(bearing):
    """Documented rule (data/config/geography.yaml): the boundary is inclusive."""
    lat, lon = destination_point_geodesic(CFG.center_lat, CFG.center_lon, bearing, 90.0)
    d = distance_from_center_km(lat, lon)
    assert abs(d - 90.0) < 1e-6
    assert in_envelope(d)
    assert region_bucket(d) == RegionBucket.NEARBY_ESCAPE


@pytest.mark.parametrize("bearing", BEARINGS)
def test_90_1_km_is_excluded(bearing):
    lat, lon = destination_point_geodesic(CFG.center_lat, CFG.center_lon, bearing, 90.1)
    d = distance_from_center_km(lat, lon)
    assert not in_envelope(d)
    assert region_bucket(d) is None


@pytest.mark.parametrize("km,bucket", [
    (0.0, RegionBucket.CITY_CORE), (14.999, RegionBucket.CITY_CORE),
    (15.0, RegionBucket.CITY_CORE), (15.001, RegionBucket.CITY),
    (30.0, RegionBucket.CITY), (30.01, RegionBucket.OUTSKIRTS),
    (60.0, RegionBucket.OUTSKIRTS), (60.01, RegionBucket.NEARBY_ESCAPE),
    (89.99, RegionBucket.NEARBY_ESCAPE),
])
def test_region_band_edges_are_inclusive_upper_bounds(km, bucket):
    assert region_bucket(km) == bucket


def test_negative_distance_is_rejected():
    with pytest.raises(ValueError):
        in_envelope(-0.1)


def test_haversine_basic_properties():
    assert haversine_km(12.97, 77.59, 12.97, 77.59) == 0
    a = haversine_km(12.97, 77.59, 13.37, 77.68)
    b = haversine_km(13.37, 77.68, 12.97, 77.59)
    assert a == pytest.approx(b)
    assert 40 < a < 50


@pytest.mark.parametrize("bad", [(91, 0, 0, 0), (0, 181, 0, 0), (float("nan"), 0, 0, 0),
                                 (0, 0, 0, float("inf"))])
def test_haversine_rejects_invalid_coordinates(bad):
    with pytest.raises(ValueError):
        haversine_km(*bad)


def test_haversine_close_to_geodesic_within_documented_bound():
    """Documented in app/geo/distance.py: up to ~0.55 % at this latitude. This
    is exactly why envelope decisions use the stored WGS84 geodesic, not haversine."""
    worst = 0.0
    for bearing in range(0, 360, 5):
        lat, lon = destination_point_geodesic(CFG.center_lat, CFG.center_lon, bearing, 80.0)
        h = haversine_km(CFG.center_lat, CFG.center_lon, lat, lon)
        worst = max(worst, abs(h - 80.0) / 80.0)
    assert worst < 0.0055


def test_spherical_destination_roundtrip():
    lat, lon = destination_point(12.97, 77.59, 45, 10.0)
    assert haversine_km(12.97, 77.59, lat, lon) == pytest.approx(10.0, rel=1e-6)


@given(st.floats(min_value=0, max_value=359.99), st.floats(min_value=0, max_value=200))
@hsettings(max_examples=200, deadline=None)
def test_envelope_decision_matches_distance(bearing, km):
    lat, lon = destination_point_geodesic(CFG.center_lat, CFG.center_lon, bearing, km)
    d = distance_from_center_km(lat, lon)
    assert math.isclose(d, km, abs_tol=1e-6)
    assert in_envelope(d) == (km <= 90.0 + BOUNDARY_TOLERANCE_KM)


def test_tolerance_is_centimetres_not_metres():
    assert BOUNDARY_TOLERANCE_KM <= 0.001
    assert in_envelope(90.0 + BOUNDARY_TOLERANCE_KM / 2)
    assert not in_envelope(90.0 + 0.01)


def test_geodesic_symmetry():
    assert geodesic_km(12.9, 77.5, 13.1, 77.7) == pytest.approx(geodesic_km(13.1, 77.7, 12.9, 77.5))
