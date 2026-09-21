"""Great-circle distance.

Haversine on a sphere of the IUGG mean radius. Against the WGS84 ellipsoid
(what PostGIS geography uses) the error at Bengaluru's latitude is up to about
0.55 % - roughly 0.5 km at the 90 km envelope edge (measured in
tests/unit/test_geo.py). Boundary decisions that must agree with the database are
therefore made in SQL, and this function is used for in-memory ranking,
clustering and plan coherence.
"""
from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    for value, lo, hi, name in ((lat1, -90, 90, "lat1"), (lat2, -90, 90, "lat2"),
                                (lon1, -180, 180, "lon1"), (lon2, -180, 180, "lon2")):
        if not (isinstance(value, (int, float)) and math.isfinite(value)
                and lo <= value <= hi):
            raise ValueError(f"{name} out of range: {value!r}")
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def destination_point(lat: float, lon: float, bearing_deg: float,
                      distance_km: float) -> tuple[float, float]:
    """The point `distance_km` from (lat, lon) along `bearing_deg`.

    Used by tests to construct points at an exact distance from the centre
    (89.9 / 90.0 / 90.1 km) rather than hand-typing coordinates.
    """
    d = distance_km / EARTH_RADIUS_KM
    b = math.radians(bearing_deg)
    p1 = math.radians(lat)
    l1 = math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d)
                   + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180
