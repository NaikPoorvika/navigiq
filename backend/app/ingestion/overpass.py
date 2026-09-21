"""Stage 1 - EXTRACT from OpenStreetMap via the Overpass API.

Queries are split by theme so each stays well inside Overpass limits. The
query radius is the envelope plus a 1 km margin: Overpass measures on a
sphere, NavigIQ on the WGS84 ellipsoid, and the precise inclusive filter is
applied afterwards in the geographic stage. Nothing near the boundary is lost
to the difference between the two models.

Ways and relations are returned with their centre and bounding box; the box
lets the mapping stage drop tiny unnamed-scale ponds (min_extent_m).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.ingestion.http import CachedClient

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
)

QUERY_MARGIN_KM = 1.0


@dataclass(frozen=True)
class QueryGroup:
    name: str
    selectors: tuple[str, ...]
    # Heavy groups are split into a tiles x tiles grid of bounding boxes
    # covering the envelope; results are merged and de-duplicated by id.
    tiles: int = 1


GROUPS: tuple[QueryGroup, ...] = (
    QueryGroup("food", (
        'nwr["amenity"~"^(cafe|restaurant|fast_food|ice_cream|food_court)$"]["name"]',
        'nwr["shop"~"^(coffee|tea|bakery|confectionery|pastry)$"]["name"]',
    )),
    QueryGroup("nightlife", (
        'nwr["amenity"~"^(bar|pub|biergarten|nightclub)$"]["name"]',
    )),
    QueryGroup("culture", (
        'nwr["tourism"~"^(museum|gallery|attraction|artwork|viewpoint|zoo|theme_park|'
        'aquarium|picnic_site|camp_site|wine_cellar|farm|agritourism)$"]["name"]',
        'nwr["historic"]["name"]',
        'nwr["heritage"]["name"]',
        'nwr["amenity"~"^(arts_centre|theatre|cinema|planetarium|library|marketplace|'
        'concert_hall|gaming_centre|gaming_lounge)$"]["name"]',
    )),
    QueryGroup("worship", (
        'nwr["amenity"="place_of_worship"]["name"]',
    )),
    QueryGroup("leisure", (
        'nwr["leisure"~"^(park|garden|nature_reserve|water_park|amusement_arcade|'
        'bowling_alley|escape_game|trampoline_park|miniature_golf|golf_course|'
        'horse_riding|ice_rink|stadium)$"]["name"]',
        'nwr["sport"~"^(karting|motor|climbing|paragliding|free_flying|zipline)$"]["name"]',
    )),
    # Nature is split four ways: as one query it exceeds the Overpass
    # gateway timeout (HTTP 504) over a 91 km radius.
    QueryGroup("nature_relief", (
        'nwr["natural"~"^(peak|hill|bare_rock|cave_entrance|cliff|waterfall)$"]["name"]',
        'nwr["waterway"~"^(waterfall|dam)$"]["name"]',
    )),
    QueryGroup("nature_water", (
        'nwr["natural"="water"]["name"]',
        'nwr["water"~"^(lake|reservoir)$"]["name"]',
    ), tiles=3),
    QueryGroup("nature_land", (
        'nwr["natural"="wood"]["name"]',
        'nwr["landuse"~"^(reservoir|forest|vineyard)$"]["name"]',
    ), tiles=2),
    QueryGroup("nature_protected", (
        'nwr["boundary"~"^(protected_area|national_park)$"]["name"]',
        'nwr["man_made"~"^(dam|observatory)$"]["name"]',
    )),
    QueryGroup("shopping", (
        'nwr["shop"~"^(mall|department_store|books|craft|handicraft|art|antiques)$"]["name"]',
        'nwr["craft"~"^(pottery|ceramics|winery|brewery)$"]["name"]',
        'nwr["place"="farm"]["name"]',
    )),
    QueryGroup("walking", (
        'way["highway"="pedestrian"]["name"]',
    )),
    QueryGroup("places", (
        'node["place"~"^(city|town|suburb|quarter|neighbourhood|village|locality|hamlet)$"]["name"]',
    )),
)


def envelope_bbox(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """South, west, north, east of a box enclosing the query circle."""
    import math
    r = radius_km + QUERY_MARGIN_KM
    dlat = r / 110.574
    dlon = r / (111.320 * math.cos(math.radians(lat)))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


def tile_boxes(lat: float, lon: float, radius_km: float, tiles: int) -> list[tuple]:
    s, w, n, e = envelope_bbox(lat, lon, radius_km)
    dy, dx = (n - s) / tiles, (e - w) / tiles
    return [(round(s + i * dy, 5), round(w + j * dx, 5), round(s + (i + 1) * dy, 5),
             round(w + (j + 1) * dx, 5)) for i in range(tiles) for j in range(tiles)]


def build_query(group: QueryGroup, lat: float, lon: float, radius_km: float,
                bbox: tuple | None = None) -> str:
    if bbox is not None:
        area = "({},{},{},{})".format(*bbox)
    else:
        radius_m = int((radius_km + QUERY_MARGIN_KM) * 1000)
        area = f"(around:{radius_m},{lat:.6f},{lon:.6f})"
    body = "".join(f"{sel}{area};" for sel in group.selectors)
    return f"[out:json][timeout:900][maxsize:1073741824];({body});out tags center bb qt;"


def _fetch_query(client: CachedClient, query: str, name: str) -> dict:
    last_exc: Exception | None = None
    for url in OVERPASS_URLS:
        try:
            return client.fetch_json(url, method="POST", data={"data": query},
                                     cache_as="overpass")
        except Exception as exc:  # noqa: BLE001 - try the next mirror
            last_exc = exc
    raise RuntimeError(f"overpass group {name} failed on all mirrors: {last_exc}")


def fetch_group(client: CachedClient, group: QueryGroup, lat: float, lon: float,
                radius_km: float) -> dict:
    if group.tiles <= 1:
        return _fetch_query(client, build_query(group, lat, lon, radius_km), group.name)
    merged: dict[str, dict] = {}
    base: dict = {}

    def fetch_box(box: tuple, depth: int) -> None:
        try:
            body = _fetch_query(client, build_query(group, lat, lon, radius_km, bbox=box),
                                f"{group.name}{box}")
        except RuntimeError:
            if depth >= 2:
                raise
            # A dense tile timed out: split it into quadrants and retry.
            s, w, n, e = box
            my, mx = round((s + n) / 2, 5), round((w + e) / 2, 5)
            for sub in ((s, w, my, mx), (s, mx, my, e), (my, w, n, mx), (my, mx, n, e)):
                fetch_box(sub, depth + 1)
            return
        base.setdefault("osm3s", body.get("osm3s", {}))
        for el in body.get("elements", []):
            merged.setdefault(f"{el['type']}/{el['id']}", el)

    for box in tile_boxes(lat, lon, radius_km, group.tiles):
        fetch_box(box, 0)
    return {"osm3s": base.get("osm3s", {}),
            "elements": [merged[k] for k in sorted(merged)]}


def element_to_record(el: dict, group: str) -> dict | None:
    """Flatten an Overpass element into the staging shape."""
    tags = el.get("tags") or {}
    if el["type"] == "node":
        lat, lon = el.get("lat"), el.get("lon")
        extent_m = None
    else:
        # With the `bb` modifier Overpass returns bounds but no centre; the
        # bounds midpoint (OSM geometry, not a guess) stands in for it.
        center = el.get("center") or {}
        bounds = el.get("bounds")
        lat, lon = center.get("lat"), center.get("lon")
        if (lat is None or lon is None) and bounds:
            lat = (bounds["minlat"] + bounds["maxlat"]) / 2
            lon = (bounds["minlon"] + bounds["maxlon"]) / 2
        extent_m = _bbox_diagonal_m(bounds) if bounds else None
    if lat is None or lon is None:
        return None
    return {
        "source": "osm",
        "source_ref": f"{el['type']}/{el['id']}",
        "osm_type": el["type"],
        "osm_id": el["id"],
        "lat": round(float(lat), 7),
        "lon": round(float(lon), 7),
        "extent_m": extent_m,
        "tags": tags,
        "query_group": group,
    }


def _bbox_diagonal_m(b: dict) -> float:
    from app.geo.distance import haversine_km
    return round(haversine_km(b["minlat"], b["minlon"], b["maxlat"], b["maxlon"]) * 1000, 1)
