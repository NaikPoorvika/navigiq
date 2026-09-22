"""Real photos for real places, from Wikidata and Wikimedia Commons.

  1. Ask Wikidata for every item near Bengaluru that has coordinates and a photo.
  2. Match each item to a POI: similar name AND close by. Never name alone -
     "Lalbagh" is also a nursing home and a bus stop.
  3. Ask Commons for an 800 px thumbnail plus the author and licence.
  4. Save image_url, image_credit, image_license, image_source_url,
     wikidata_id and wikidata_sitelinks on the matched POIs.

Free, no API key. Commons photos are mostly CC BY / CC BY-SA, so the CREDIT
IS REQUIRED wherever the photo is shown - the frontend displays it on every
image. Wikimedia asks every client to send a descriptive User-Agent.

Idempotent: re-running overwrites the same columns with the same values.

    python data/pipelines/wikidata_enrich.py --dry-run    # show matches only
    python data/pipelines/wikidata_enrich.py              # write to the database
    python data/pipelines/wikidata_enrich.py --refresh    # ignore the cache

Two sources, tried in order (or forced with --source):
  wdqs       the Wikidata Query Service - one query, the best data
  wikipedia  Wikipedia's GeoSearch API - a separate service, used when the
             query service is down or rate-limiting. Covers the area in 10 km
             circles, splitting any circle that hits the 500-result cap.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import time
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

DSN = os.environ.get(
    "PG_DSN", "postgresql://navigiq:navigiq_local_dev@localhost:5433/navigiq")

SPARQL_URL = "https://query.wikidata.org/sparql"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# The Wikidata answer is cached, so a dry run and the real run share ONE
# query. The query service can rate-limit to one request per minute.
CACHE = Path("data/cache/wikidata_items.json")
RETRIES = 4
# Wikimedia's User-Agent policy requires real contact details - a URL or an
# email - or requests are refused with 403. Set WIKIMEDIA_CONTACT to add
# your email; it is read from the environment so it isn't committed.
CONTACT = os.environ.get("WIKIMEDIA_CONTACT", "https://github.com/NaikPoorvika/navigiq")
USER_AGENT = f"NavigIQ/0.1 ({CONTACT}) python-httpx"

CENTRE_LON, CENTRE_LAT = 77.5946, 12.9716
RADIUS_KM = 60

# Match rules. Close-by needs a decent name match; farther needs a strong one.
# Parks and lakes are large, so their Wikidata point may sit 400+ m from ours.
NEAR_M, NEAR_SIM = 150, 0.45
FAR_M, FAR_SIM = 600, 0.60
THUMB_WIDTH = 800
COMMONS_BATCH = 50

SPARQL = f"""
SELECT ?item ?itemLabel ?coord ?image ?sitelinks
       (GROUP_CONCAT(DISTINCT ?alt; separator="|") AS ?alts)
WHERE {{
  SERVICE wikibase:around {{
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:center "Point({CENTRE_LON} {CENTRE_LAT})"^^geo:wktLiteral .
    bd:serviceParam wikibase:radius "{RADIUS_KM}" .
  }}
  ?item wdt:P18 ?image ;
        wikibase:sitelinks ?sitelinks .
  OPTIONAL {{ ?item skos:altLabel ?alt . FILTER(LANG(?alt) = "en") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
GROUP BY ?item ?itemLabel ?coord ?image ?sitelinks
"""


# ---------------------------------------------------------------- pure helpers

def normalize(name: str) -> str:
    """Same normalisation as load_pois.py: unaccent, lower, collapse spaces."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def trigrams(s: str) -> set[str]:
    """pg_trgm-style trigrams, so scores line up with the database's."""
    out: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", s.lower()):
        padded = f"  {word} "
        out.update(padded[i:i + 3] for i in range(len(padded) - 2))
    return out


def similarity(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def parse_point(wkt: str) -> tuple[float, float] | None:
    """'Point(77.59 12.97)' -> (lat, lon)."""
    m = re.match(r"Point\(\s*([-\d.]+)\s+([-\d.]+)\s*\)", wkt)
    return (float(m.group(2)), float(m.group(1))) if m else None


def commons_filename(image_url: str) -> str:
    """'.../Special:FilePath/Lal%20Bagh.jpg' -> 'Lal Bagh.jpg'."""
    return unquote(image_url.rsplit("/", 1)[-1]).replace("_", " ")


def strip_html(value: str, limit: int = 120) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", "", value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass
class Item:
    qid: str
    labels: list[str]
    lat: float
    lon: float
    filename: str
    sitelinks: int


@dataclass
class Poi:
    id: int
    name_normalized: str
    lat: float
    lon: float


# Words that carry no identity - half of Wikidata's labels end in the city name.
NON_IDENTIFYING = {"bangalore", "bengaluru", "karnataka", "india", "the", "of", "and", "in"}

# Local-language words mapped to the English word for the same kind of place,
# so "Dodda Ganeshana Gudi" and "Dodda Ganesha Temple" agree on what they are.
SYNONYMS = {"gudi": "temple", "devasthana": "temple", "kere": "lake", "tank": "lake",
            "betta": "hill", "masjid": "mosque", "cathedral": "church", "basilica": "church"}

# Words that say what KIND of place something is.
PLACE_TYPES = {"temple", "church", "mosque", "dargah", "fort", "palace", "lake", "park",
               "garden", "museum", "gallery", "mall", "market", "statue", "memorial",
               "school", "college", "university", "hospital", "stadium", "library",
               "tomb", "hill", "bridge", "planetarium"}

# Words that mark an AREA or TRANSPORT feature rather than a place to visit.
AREA_WORDS = {"nagar", "layout", "station", "metro", "road", "circle", "cross", "block",
              "stage", "phase", "colony", "village", "city", "town", "junction",
              "flyover", "depot", "bus", "stop"}


def name_words(s: str) -> set[str]:
    """Identifying words: normalised, singular, synonyms unified."""
    out = set()
    for w in re.findall(r"[a-z0-9]+", normalize(s)):
        if len(w) < 2 or w in NON_IDENTIFYING:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]                       # gardens -> garden, stones -> stone
        out.add(SYNONYMS.get(w, w))
    return out


def label_head(label: str) -> str:
    """'Gopalan Arcade Mall, Rajarajeshwari Nagar' -> 'Gopalan Arcade Mall'.
    After the comma, Wikidata labels say WHERE the place is, not what it is."""
    return label.split(",", 1)[0]


def names_only_part(label: str, poi_name: str) -> bool:
    """True when the Wikidata name covers only PART of the POI's name.

    'Yelahanka' is wholly inside 'Yelahanka Lake': the item is the area the
    lake is named after, not the lake. A label with no identifying words left
    ('Bengaluru') is the city itself - never a POI.
    """
    label_w, poi_w = name_words(label), name_words(poi_name)
    if not label_w:
        return True
    # A label that names a KIND of place ('Mysore Lancers memorial') is a place
    # in its own right, even if the POI's name is longer. Only a bare name
    # ('Yelahanka') inside a longer one is the area the POI is named after.
    return label_w < poi_w and not (label_w & PLACE_TYPES)


def conflicting_kind(label: str, poi_name: str) -> bool:
    """True when the two names describe different KINDS of place.

    - The label has an area or transport word the POI lacks:
      'Rajarajeshwari Nagar' is a neighbourhood, not a temple.
    - Both say what kind of place they are, and the label adds a kind the
      POI doesn't have: 'Fort Church' is not 'Bangalore Fort'.
    """
    label_w, poi_w = name_words(label_head(label)), name_words(poi_name)
    if (label_w & AREA_WORDS) - poi_w:
        return True
    poi_types = poi_w & PLACE_TYPES
    return bool(poi_types) and bool((label_w & PLACE_TYPES) - poi_types)


def rejects(label: str, poi_name: str) -> bool:
    return names_only_part(label, poi_name) or conflicting_kind(label, poi_name)


def accept(sim: float, dist_m: float) -> bool:
    return (dist_m <= NEAR_M and sim >= NEAR_SIM) or (dist_m <= FAR_M and sim >= FAR_SIM)


class Grid:
    """~1 km cells, so each item only compares against nearby POIs."""

    CELL = 0.01

    def __init__(self, pois: list[Poi]) -> None:
        self.cells: dict[tuple[int, int], list[Poi]] = defaultdict(list)
        for p in pois:
            self.cells[self._key(p.lat, p.lon)].append(p)

    def _key(self, lat: float, lon: float) -> tuple[int, int]:
        return int(lat / self.CELL), int(lon / self.CELL)

    def near(self, lat: float, lon: float) -> list[Poi]:
        ky, kx = self._key(lat, lon)
        return [p for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                for p in self.cells.get((ky + dy, kx + dx), [])]


def best_match(item: Item, grid: Grid) -> tuple[Poi, float, float] | None:
    """Best POI for a Wikidata item, or None if nothing passes the rules."""
    best: tuple[Poi, float, float] | None = None
    for p in grid.near(item.lat, item.lon):
        dist = haversine_m(item.lat, item.lon, p.lat, p.lon)
        if dist > FAR_M:
            continue
        # Only labels that name the WHOLE place count.
        scores = [similarity(normalize(label), p.name_normalized)
                  for label in item.labels
                  if not rejects(label, p.name_normalized)]
        if not scores:
            continue
        sim = max(scores)
        if not accept(sim, dist):
            continue
        # Prefer the stronger name match; break ties by distance.
        if best is None or (sim, -dist) > (best[1], -best[2]):
            best = (p, sim, dist)
    return best


def assign(items: list[Item], grid: Grid) -> dict[int, tuple[Item, float, float]]:
    """One photo per POI. If several items match a POI, keep the most notable."""
    chosen: dict[int, tuple[Item, float, float]] = {}
    for item in items:
        m = best_match(item, grid)
        if m is None:
            continue
        poi, sim, dist = m
        current = chosen.get(poi.id)
        if current is None or (item.sitelinks, sim) > (current[0].sitelinks, current[1]):
            chosen[poi.id] = (item, sim, dist)
    return chosen


# ---------------------------------------------------------------- network + db

def get_with_retry(client, url: str, params: dict):
    """GET that waits out rate limits (429) and brief outages (5xx)."""
    for attempt in range(RETRIES):
        r = client.get(url, params=params)
        if r.status_code in (429, 500, 502, 503, 504) and attempt < RETRIES - 1:
            wait = int(r.headers.get("Retry-After", "0") or 0) or 65
            print(f"  {r.status_code} from {url.split('/')[2]} - waiting {wait}s, then retrying")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError("unreachable")


def items_from_wdqs() -> list[Item]:
    import httpx

    with httpx.Client(headers={"User-Agent": USER_AGENT,
                               "Accept": "application/sparql-results+json"},
                      timeout=120.0) as client:
        r = get_with_retry(client, SPARQL_URL, {"query": SPARQL, "format": "json"})
    by_qid: dict[str, Item] = {}
    for b in r.json()["results"]["bindings"]:
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        point = parse_point(b["coord"]["value"])
        if point is None or qid in by_qid:
            continue
        label = b.get("itemLabel", {}).get("value", "")
        if not label or re.fullmatch(r"Q\d+", label):
            continue  # no English label
        alts = [a for a in b.get("alts", {}).get("value", "").split("|") if a]
        by_qid[qid] = Item(
            qid=qid, labels=[label, *alts], lat=point[0], lon=point[1],
            filename=commons_filename(b["image"]["value"]),
            sitelinks=int(b.get("sitelinks", {}).get("value", 0)),
        )
    return list(by_qid.values())


# ------------------------------------------------ Wikipedia GeoSearch fallback

GEO_RADIUS_M = 10_000      # GeoSearch maximum
GEO_LIMIT = 500            # GeoSearch maximum per query
MIN_RADIUS_M = 1_000

PageFetcher = Callable[[float, float, int], dict]


def merge_pages(into: dict, pages: dict) -> None:
    """Merge one continuation batch into the running page set."""
    for pid, page in pages.items():
        merged = into.setdefault(pid, {})
        for k, v in page.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k].update(v)
            elif k not in merged:
                merged[k] = v


def cover(lat: float, lon: float, radius_m: int, fetch: PageFetcher,
          out: dict, depth: int = 0) -> None:
    """Collect pages around a point. A circle that hits the result cap may be
    missing pages, so it is split into four smaller circles."""
    pages = fetch(lat, lon, radius_m)
    merge_pages(out, pages)
    if len(pages) >= GEO_LIMIT and radius_m // 2 >= MIN_RADIUS_M:
        half = radius_m / 2
        dlat = half / 111_320
        dlon = half / (111_320 * math.cos(math.radians(lat)))
        for sy in (-1, 1):
            for sx in (-1, 1):
                # radius x 0.75 of the parent: the four circles overlap and
                # cover the parent's square.
                cover(lat + sy * dlat, lon + sx * dlon, int(radius_m * 0.75),
                      fetch, out, depth + 1)


def grid_points(radius_km: float) -> list[tuple[float, float]]:
    """Circle centres covering a square of +/- radius_km around the centre."""
    step_km = GEO_RADIUS_M / 1000 * 1.4     # 10 km circles, spaced to overlap
    n = math.ceil(radius_km / step_km)
    pts = []
    for iy in range(-n, n + 1):
        for ix in range(-n, n + 1):
            pts.append((CENTRE_LAT + iy * step_km / 111.32,
                        CENTRE_LON + ix * step_km / (111.32 * math.cos(math.radians(CENTRE_LAT)))))
    return pts


def items_from_pages(pages: dict) -> list[Item]:
    """Wikipedia pages with coordinates AND a lead image become Items."""
    out: dict[str, Item] = {}
    for pid, page in pages.items():
        coords = page.get("coordinates") or []
        image = page.get("pageimage")
        title = page.get("title")
        if not coords or not image or not title:
            continue
        qid = (page.get("pageprops") or {}).get("wikibase_item") or f"enwiki:{pid}"
        if qid in out:
            continue
        out[qid] = Item(qid=qid, labels=[title], lat=float(coords[0]["lat"]),
                        lon=float(coords[0]["lon"]),
                        filename=image.replace("_", " "), sitelinks=0)
    return list(out.values())


def items_from_wikipedia() -> list[Item]:
    import httpx

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0) as client:
        calls = 0

        def fetch(lat: float, lon: float, radius_m: int) -> dict:
            nonlocal calls
            params = {
                "action": "query", "format": "json", "generator": "geosearch",
                "ggscoord": f"{lat:.5f}|{lon:.5f}", "ggsradius": str(radius_m),
                "ggslimit": str(GEO_LIMIT), "prop": "coordinates|pageimages|pageprops",
                "piprop": "name", "pilimit": "50", "ppprop": "wikibase_item",
                "colimit": "500",
            }
            pages: dict = {}
            cont: dict = {}
            while True:          # follow continuation for pageimages (50 per batch)
                r = get_with_retry(client, WIKIPEDIA_API, {**params, **cont})
                calls += 1
                data = r.json()
                merge_pages(pages, data.get("query", {}).get("pages", {}))
                if "continue" not in data:
                    return pages
                cont = data["continue"]
                time.sleep(0.1)

        found: dict = {}
        points = grid_points(RADIUS_KM)
        for i, (lat, lon) in enumerate(points, 1):
            cover(lat, lon, GEO_RADIUS_M, fetch, found)
            print(f"\r  Wikipedia GeoSearch: area {i}/{len(points)}, "
                  f"{len(found):,} pages, {calls} requests", end="", flush=True)
        print()
        items = items_from_pages(found)

        # Notability: count sitelinks through the Wikidata API (not the query service).
        qids = [it.qid for it in items if it.qid.startswith("Q")]
        links: dict[str, int] = {}
        for i in range(0, len(qids), 50):
            r = get_with_retry(client, WIKIDATA_API, {
                "action": "wbgetentities", "format": "json", "props": "sitelinks",
                "ids": "|".join(qids[i:i + 50]),
            })
            for qid, ent in r.json().get("entities", {}).items():
                links[qid] = len(ent.get("sitelinks", {}))
            time.sleep(0.2)
        for it in items:
            it.sitelinks = links.get(it.qid, 0)
        return items


def fetch_items(source: str = "auto", refresh: bool = False) -> list[Item]:
    """Items from the cache, else the query service, else Wikipedia."""
    if CACHE.exists() and not refresh:
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
        print(f"  using cached answer from {cached['source']} "
              f"({cached['fetched_at']}); --refresh to fetch again")
        return [Item(**d) for d in cached["items"]]

    items: list[Item] | None = None
    used = source
    if source in ("auto", "wdqs"):
        try:
            items = items_from_wdqs()
            used = "wdqs"
        except Exception as exc:  # noqa: BLE001
            if source == "wdqs":
                raise
            print(f"  Wikidata query service unavailable ({type(exc).__name__}) "
                  "- falling back to Wikipedia GeoSearch")
    if items is None:
        items = items_from_wikipedia()
        used = "wikipedia"

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({
        "source": used, "fetched_at": time.strftime("%Y-%m-%d %H:%M"),
        "items": [asdict(i) for i in items],
    }, ensure_ascii=False), encoding="utf-8")
    return items


def fetch_image_info(filenames: list[str], width: int = THUMB_WIDTH) -> dict[str, dict]:
    """Thumbnail URL, author and licence for each Commons file."""
    import httpx

    out: dict[str, dict] = {}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0) as client:
        for i in range(0, len(filenames), COMMONS_BATCH):
            batch = filenames[i:i + COMMONS_BATCH]
            r = get_with_retry(client, COMMONS_API, {
                "action": "query", "format": "json", "prop": "imageinfo",
                "iiprop": "url|extmetadata", "iiurlwidth": str(width),
                "iiextmetadatafilter": "Artist|LicenseShortName",
                "titles": "|".join(f"File:{f}" for f in batch),
            })
            data = r.json().get("query", {})
            renamed = {n["to"]: n["from"] for n in data.get("normalized", [])}
            for page in data.get("pages", {}).values():
                info = (page.get("imageinfo") or [None])[0]
                if not info:
                    continue
                title = renamed.get(page["title"], page["title"])
                meta = info.get("extmetadata", {})
                out[title.removeprefix("File:").replace("_", " ")] = {
                    "url": info.get("thumburl") or info.get("url"),
                    "credit": strip_html(meta.get("Artist", {}).get("value", "")) or "Wikimedia Commons",
                    "license": strip_html(meta.get("LicenseShortName", {}).get("value", ""), 40),
                    "source": info.get("descriptionurl"),
                }
            time.sleep(0.5)  # be polite to Commons
    return out


def load_pois() -> list[Poi]:
    import psycopg

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, name_normalized, ST_Y(geom::geometry), ST_X(geom::geometry)
            FROM pois WHERE active
        """)
        return [Poi(r[0], r[1], r[2], r[3]) for r in cur.fetchall()]


def main() -> None:
    ap = argparse.ArgumentParser(description="Wikidata / Commons photo enrichment")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="ignore the cached answer")
    ap.add_argument("--source", choices=["auto", "wdqs", "wikipedia"], default="auto")
    args = ap.parse_args()

    print("finding photographed places near Bengaluru…")
    items = fetch_items(args.source, args.refresh)
    print(f"  {len(items):,} items with a photo and an English label")

    pois = load_pois()
    print(f"  {len(pois):,} POIs loaded")
    chosen = assign(items, Grid(pois))
    print(f"  {len(chosen):,} POIs matched")

    names = {p.id: p.name_normalized for p in pois}
    print("\nmost notable matches:")
    for poi_id, (item, sim, dist) in sorted(chosen.items(), key=lambda kv: -kv[1][0].sitelinks)[:25]:
        print(f"  {names[poi_id][:34]:<36} <- {item.labels[0][:32]:<34} "
              f"sim {sim:.2f}  {dist:>4.0f} m  {item.sitelinks:>3} links")

    review = CACHE.parent / "matches.csv"
    review.parent.mkdir(parents=True, exist_ok=True)
    with review.open("w", encoding="utf-8-sig", newline="") as f:
        import csv
        w = csv.writer(f)
        w.writerow(["poi_id", "poi_name", "wikidata_label", "qid", "similarity", "distance_m", "sitelinks"])
        for poi_id, (item, sim, dist) in sorted(chosen.items(), key=lambda kv: -kv[1][0].sitelinks):
            w.writerow([poi_id, names[poi_id], item.labels[0], item.qid,
                        f"{sim:.2f}", f"{dist:.0f}", item.sitelinks])
    print(f"\nall {len(chosen)} matches written to {review} - open it to review")

    if args.dry_run:
        print("--dry-run: nothing written to the database")
        return

    print("\nasking Commons for thumbnails and credits…")
    info = fetch_image_info(sorted({item.filename for item, _, _ in chosen.values()}))

    import psycopg

    written = 0
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        for poi_id, (item, _, _) in chosen.items():
            meta = info.get(item.filename)
            if not meta or not meta["url"]:
                continue
            cur.execute("""
                UPDATE pois SET image_url = %s, image_credit = %s, image_license = %s,
                       image_source_url = %s, wikidata_id = %s, wikidata_sitelinks = %s
                WHERE id = %s
            """, (meta["url"], meta["credit"], meta["license"] or None, meta["source"],
                  item.qid, item.sitelinks, poi_id))
            written += 1
        conn.commit()
    print(f"wrote photos for {written:,} POIs")


if __name__ == "__main__":
    main()
