"""Stage 2b - GAZETTEER: localities, neighbourhoods and districts from OSM.

Every locality name and coordinate comes from an OSM place node; districts
come from OSM administrative boundaries (admin_level=5). Nothing is typed in
by hand - a curated alias only ever points at a name that already exists here.

Assignment rules (nearest named place, geodesic):
  neighborhood  nearest neighbourhood/quarter/suburb within 2 km
  locality      nearest suburb/town/city/village within 6 km; villages and
                hamlets carry a 1.5 km handicap so a town wins a near-tie
  district      point-in-polygon against assembled boundary relations
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LineString, Point
from shapely.ops import linemerge, polygonize, unary_union
from shapely.prepared import prep

from app.geo.distance import haversine_km
from app.ingestion.http import CachedClient
from app.ingestion.normalize import clean_display_name, normalize_name
from app.ingestion.overpass import OVERPASS_URLS

PLACE_IMPORTANCE = {"city": 1.0, "town": 0.8, "suburb": 0.7, "quarter": 0.55,
                    "neighbourhood": 0.5, "village": 0.35, "locality": 0.25, "hamlet": 0.15}
NEIGHBORHOOD_TYPES = {"neighbourhood", "quarter", "suburb"}
LOCALITY_TYPES = {"suburb", "town", "city", "village", "hamlet"}
LOCALITY_PENALTY_KM = {"village": 1.5, "hamlet": 2.5}


@dataclass
class PlaceRec:
    source_ref: str
    name: str
    name_normalized: str
    aliases: list[str]
    place_type: str
    lat: float
    lon: float
    importance: float


class PlaceIndex:
    """A simple grid index; ~10k places and ~20k POIs make this instant."""

    CELL_DEG = 0.05

    def __init__(self, places: list[PlaceRec]) -> None:
        self.places = places
        self.grid: dict[tuple[int, int], list[PlaceRec]] = {}
        for p in places:
            self.grid.setdefault(self._cell(p.lat, p.lon), []).append(p)

    def _cell(self, lat: float, lon: float) -> tuple[int, int]:
        return int(math.floor(lat / self.CELL_DEG)), int(math.floor(lon / self.CELL_DEG))

    def nearest(self, lat: float, lon: float, types: set[str], max_km: float,
                penalties: dict[str, float] | None = None) -> tuple[PlaceRec, float] | None:
        penalties = penalties or {}
        ci, cj = self._cell(lat, lon)
        span = int(math.ceil(max_km / (self.CELL_DEG * 111.0))) + 1
        best: tuple[PlaceRec, float, float] | None = None
        for di in range(-span, span + 1):
            for dj in range(-span, span + 1):
                for p in self.grid.get((ci + di, cj + dj), ()):
                    if p.place_type not in types:
                        continue
                    d = haversine_km(lat, lon, p.lat, p.lon)
                    if d > max_km:
                        continue
                    score = d + penalties.get(p.place_type, 0.0)
                    if best is None or score < best[2] or (
                            score == best[2] and p.source_ref < best[0].source_ref):
                        best = (p, d, score)
        return (best[0], best[1]) if best else None


def places_from_overpass(elements: list[dict]) -> list[PlaceRec]:
    out = []
    for el in elements:
        tags = el.get("tags") or {}
        name = tags.get("name:en") or tags.get("name")
        ptype = tags.get("place")
        if not name or ptype not in PLACE_IMPORTANCE or el.get("lat") is None:
            continue
        name = clean_display_name(name)
        aliases = sorted({clean_display_name(tags[k]) for k in ("name", "alt_name", "old_name",
                                                                "official_name")
                          if tags.get(k) and clean_display_name(tags[k]) != name})
        out.append(PlaceRec(
            source_ref=f"node/{el['id']}", name=name, name_normalized=normalize_name(name),
            aliases=aliases, place_type=ptype, lat=float(el["lat"]), lon=float(el["lon"]),
            importance=PLACE_IMPORTANCE[ptype],
        ))
    out.sort(key=lambda p: p.source_ref)
    return out


def assign_locality(index: PlaceIndex, lat: float, lon: float) -> tuple[str | None, str | None]:
    hood = index.nearest(lat, lon, NEIGHBORHOOD_TYPES, 2.0)
    loc = index.nearest(lat, lon, LOCALITY_TYPES, 6.0, LOCALITY_PENALTY_KM)
    return (loc[0].name if loc else None), (hood[0].name if hood else None)


# --- districts ------------------------------------------------------------------

def district_query(lat: float, lon: float, radius_km: float) -> str:
    r = int((radius_km + 5) * 1000)
    return (f'[out:json][timeout:600];rel["boundary"="administrative"]["admin_level"="5"]'
            f'(around:{r},{lat:.6f},{lon:.6f});out geom;')


def fetch_districts(client: CachedClient, lat: float, lon: float, radius_km: float) -> dict:
    last: Exception | None = None
    for url in OVERPASS_URLS:
        try:
            return client.fetch_json(url, method="POST",
                                     data={"data": district_query(lat, lon, radius_km)},
                                     cache_as="overpass")
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"district boundaries unavailable: {last}")


class DistrictIndex:
    def __init__(self, body: dict) -> None:
        self.districts: list[tuple[str, object, object]] = []
        for rel in body.get("elements", []):
            if rel.get("type") != "relation":
                continue
            tags = rel.get("tags") or {}
            name = tags.get("name:en") or tags.get("name")
            if not name:
                continue
            lines = []
            for m in rel.get("members", []):
                if m.get("type") == "way" and m.get("role") in ("outer", "") and m.get("geometry"):
                    coords = [(pt["lon"], pt["lat"]) for pt in m["geometry"]]
                    if len(coords) >= 2:
                        lines.append(LineString(coords))
            if not lines:
                continue
            polys = list(polygonize(linemerge(unary_union(lines))))
            if not polys:
                continue
            shape = unary_union(polys)
            name = clean_display_name(name).removesuffix(" district").removesuffix(" District")
            self.districts.append((name, prep(shape), shape))
        self.districts.sort(key=lambda d: d[0])

    def lookup(self, lat: float, lon: float) -> str | None:
        pt = Point(lon, lat)
        for name, prepared, _ in self.districts:
            if prepared.contains(pt):
                return name
        return None
