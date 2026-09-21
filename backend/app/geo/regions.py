"""The Bengaluru discovery envelope and its region buckets (ADR-023).

`distance_from_center_km` is the AUTHORITATIVE envelope distance: a WGS84
ellipsoidal geodesic (Karney's algorithm via geographiclib), the same model
PostGIS uses for ST_Distance on geography. The pipeline stores it per POI and
every envelope/bucket decision reads the stored value, so Python and SQL can
never disagree about whether a place is inside 90 km.

Boundary rule (documented in data/config/geography.yaml): inclusive.
  89.9 km -> inside     90.0 km -> inside     90.1 km -> outside
A 10 cm tolerance absorbs floating-point noise and the 7-decimal (~1 cm)
precision at which coordinates are stored, so a place at exactly 90.0 km is
not excluded by rounding. (Found by tests/unit/test_ingestion.py.)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

import yaml
from geographiclib.geodesic import Geodesic

from app.core.paths import config_path

BOUNDARY_TOLERANCE_KM = 1e-4


class RegionBucket(str, Enum):
    CITY_CORE = "CITY_CORE"
    CITY = "CITY"
    OUTSKIRTS = "OUTSKIRTS"
    NEARBY_ESCAPE = "NEARBY_ESCAPE"


@dataclass(frozen=True)
class GeoConfig:
    center_lat: float
    center_lon: float
    radius_km: float
    bands: tuple[tuple[RegionBucket, float], ...]
    adaptive: dict
    scope_buckets: dict
    planning: dict


@lru_cache(maxsize=1)
def geo_config() -> GeoConfig:
    from app.config import settings

    raw = yaml.safe_load(config_path("geography.yaml").read_text(encoding="utf-8"))
    bands = tuple((RegionBucket(b["bucket"]), float(b["max_km"]))
                  for b in raw["region_bands"])
    if [b for b, _ in bands] != list(RegionBucket):
        raise ValueError("region_bands must list every bucket in order")
    if any(later <= earlier for (_, earlier), (_, later) in zip(bands, bands[1:])):
        raise ValueError("region_bands must be strictly increasing")
    return GeoConfig(
        center_lat=settings.BENGALURU_CENTER_LAT,
        center_lon=settings.BENGALURU_CENTER_LON,
        radius_km=settings.BENGALURU_DISCOVERY_RADIUS_KM,
        bands=bands,
        adaptive=raw["adaptive_radius_km"],
        scope_buckets={k: [RegionBucket(v) for v in vs]
                       for k, vs in raw["scope_buckets"].items()},
        planning=raw["planning"],
    )


def geodesic_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """WGS84 ellipsoidal distance in km."""
    return Geodesic.WGS84.Inverse(lat1, lon1, lat2, lon2, Geodesic.DISTANCE)["s12"] / 1000.0


def distance_from_center_km(lat: float, lon: float,
                            cfg: GeoConfig | None = None) -> float:
    cfg = cfg or geo_config()
    return geodesic_km(cfg.center_lat, cfg.center_lon, lat, lon)


def in_envelope(distance_km: float, cfg: GeoConfig | None = None) -> bool:
    """Inclusive: exactly the configured radius is inside."""
    cfg = cfg or geo_config()
    if distance_km < 0:
        raise ValueError("distance must be non-negative")
    return distance_km <= cfg.radius_km + BOUNDARY_TOLERANCE_KM


def region_bucket(distance_km: float, cfg: GeoConfig | None = None) -> RegionBucket | None:
    """Bucket for a distance, or None when outside the envelope.

    Band upper bounds are inclusive: 15.0 km is CITY_CORE, 15.001 is CITY.
    The envelope radius caps the last band even if the YAML says otherwise.
    """
    cfg = cfg or geo_config()
    if not in_envelope(distance_km, cfg):
        return None
    for bucket, max_km in cfg.bands:
        if distance_km <= max_km + BOUNDARY_TOLERANCE_KM:
            return bucket
    # Radius configured wider than the last band: still inside the envelope.
    return cfg.bands[-1][0]


def destination_point_geodesic(lat: float, lon: float, bearing_deg: float,
                               distance_km: float) -> tuple[float, float]:
    """Exact WGS84 destination - used to build boundary test fixtures."""
    r = Geodesic.WGS84.Direct(lat, lon, bearing_deg, distance_km * 1000.0)
    return r["lat2"], r["lon2"]
