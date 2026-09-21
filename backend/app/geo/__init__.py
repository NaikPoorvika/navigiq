"""Geography: geodesic distance, the Bengaluru discovery envelope, region
buckets and adaptive search radii (ADR-023).

Pure functions only - no database access - so every boundary rule is unit
testable. PostGIS performs the same computation in SQL (ST_Distance on
geography) and the two are cross-checked by an integration test.
"""
from .distance import EARTH_RADIUS_KM, haversine_km
from .regions import (
    RegionBucket,
    GeoConfig,
    geo_config,
    in_envelope,
    region_bucket,
    distance_from_center_km,
)

__all__ = [
    "EARTH_RADIUS_KM",
    "GeoConfig",
    "RegionBucket",
    "distance_from_center_km",
    "geo_config",
    "haversine_km",
    "in_envelope",
    "region_bucket",
]
