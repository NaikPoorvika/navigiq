"""Stage 5a - LINK OSM features to Wikidata by location + name (ADR-026).

OpenStreetMap around Bengaluru carries very few `wikidata` tags (measured:
under 1 % of features), so tag-based enrichment alone would leave famous
places without descriptions. Wikidata (CC0) records coordinates for notable
places. This stage asks the Wikidata Query Service for every item with an
English Wikipedia article inside the envelope, then links an OSM feature to
an item only when BOTH hold:

  * the normalised names match closely (token-set similarity >= 90, or an
    exact alias match), and
  * the item's coordinate is within the feature's reach (1.5 km for point
    features, up to 6 km for large areas such as lakes, parks and hills).

Settlements (villages, towns, neighbourhoods) are never linked to POIs.

Notable Wikidata items that match no OSM feature and whose type maps to a
NavigIQ category are ADDED as POIs (source "wikidata"), with Wikidata's own
coordinates - recorded data, not invented.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from app.geo.distance import haversine_km
from app.ingestion.http import CachedClient
from app.ingestion.normalize import normalize_name

SPARQL_URL = "https://query.wikidata.org/sparql"

QUERY = """
SELECT ?item ?itemLabel ?coord ?article ?type WHERE {{
  SERVICE wikibase:around {{
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:center "Point({lon} {lat})"^^geo:wktLiteral .
    bd:serviceParam wikibase:radius "{radius}" .
  }}
  ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> .
  OPTIONAL {{ ?item wdt:P31 ?type . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
"""

SETTLEMENT_TYPES = {
    "Q486972", "Q532", "Q3957", "Q515", "Q1549591", "Q123705", "Q2983893", "Q5119",
    "Q1637706", "Q15127012", "Q13212489", "Q7930989", "Q56436498", "Q1115575", "Q17305746",
    "Q1402592", "Q11753321", "Q2989398", "Q12813115", "Q4235563", "Q3685463", "Q4286337",
    "Q1187811", "Q15078955", "Q1266818", "Q105999732", "Q35145263",
}

# Wikidata type -> NavigIQ category, for items that match no OSM feature.
TYPE_CATEGORY = {
    "Q23397": "lake", "Q131681": "reservoir", "Q12323": "reservoir", "Q54050": "hill",
    "Q8502": "hill", "Q207326": "hill", "Q34038": "waterfall", "Q842402": "temple",
    "Q44539": "temple", "Q1370598": "temple", "Q57831": "fort", "Q1785071": "fort",
    "Q33506": "museum", "Q207694": "gallery", "Q22698": "park", "Q16560": "palace",
    "Q16970": "church", "Q2977": "church", "Q56242215": "church", "Q32815": "mosque",
    "Q1107656": "garden", "Q167346": "garden", "Q43501": "nature", "Q46169": "nature",
    "Q20268": "nature", "Q473972": "nature", "Q179049": "nature", "Q4989906": "monument",
    "Q575759": "monument", "Q839954": "history", "Q1081138": "heritage",
    "Q41176": "architecture", "Q15243209": "heritage", "Q2065736": "heritage",
    "Q11315": "mall", "Q330284": "market", "Q132510": "market", "Q24354": "entertainment",
    "Q194195": "entertainment", "Q2416723": "entertainment", "Q17350442": "entertainment",
    "Q4260475": "forest", "Q4421": "forest", "Q1006311": "forest",
    "Q5358913": "religious_site", "Q16748868": "religious_site",
    "Q79007": "walking_area", "Q11707": "restaurant", "Q30022": "cafe",
    "Q58621988": "temple", "Q1088552": "church", "Q1500350": "hill",
}
LARGE_CATEGORIES = {"lake", "reservoir", "park", "garden", "hill", "forest", "nature", "fort",
                    "waterfall", "palace", "walking_area", "neighborhood"}


@dataclass
class WDItem:
    qid: str
    label: str
    lat: float
    lon: float
    enwiki: str
    types: set[str] = field(default_factory=set)

    @property
    def settlement(self) -> bool:
        return bool(self.types & SETTLEMENT_TYPES)

    @property
    def category(self) -> str | None:
        for t in sorted(self.types):
            if t in TYPE_CATEGORY:
                return TYPE_CATEGORY[t]
        return None


_POINT = re.compile(r"Point\(([-\d.]+) ([-\d.]+)\)")


def fetch_items(client: CachedClient, lat: float, lon: float, radius_km: float) -> list[WDItem]:
    body = client.fetch_json(SPARQL_URL, params={
        "query": QUERY.format(lat=lat, lon=lon, radius=int(radius_km + 1)), "format": "json"})
    items: dict[str, WDItem] = {}
    for b in body.get("results", {}).get("bindings", []):
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        m = _POINT.match(b["coord"]["value"])
        if not m:
            continue
        title = b["article"]["value"].rsplit("/wiki/", 1)[-1]
        from urllib.parse import unquote
        title = unquote(title).replace("_", " ")
        it = items.setdefault(qid, WDItem(qid, b.get("itemLabel", {}).get("value", qid),
                                          float(m.group(2)), float(m.group(1)), title))
        if "type" in b:
            it.types.add(b["type"]["value"].rsplit("/", 1)[-1])
    return sorted(items.values(), key=lambda i: i.qid)


def _reach_km(category: str, extent_m: float | None) -> float:
    if category in LARGE_CATEGORIES:
        return max(1.5, min(6.0, (extent_m or 0) / 1000 * 0.8 + 1.0))
    return 1.5


# Words that may differ between an OSM name and a Wikidata label without the
# two being different places ("Lalbagh" vs "Lalbagh Botanical Gardens").
GENERIC_TOKENS = {
    "the", "of", "sri", "shri", "sree", "temple", "lake", "kere", "park", "garden", "gardens",
    "botanical", "tank", "hill", "hills", "betta", "fort", "palace", "museum", "bengaluru",
    "church", "masjid", "mosque", "gudi", "devasthana", "devasthanam", "swamy", "swami",
    "gallery", "market", "falls", "waterfall", "reservoir", "dam", "national", "state",
    "forest", "zoo", "karnataka", "india", "basilica", "cathedral", "memorial", "statue",
}
CATEGORY_GROUP = {
    **{c: "nature" for c in ("park", "garden", "lake", "nature", "hill", "viewpoint", "forest",
                             "waterfall", "reservoir")},
    **{c: "culture" for c in ("museum", "gallery", "science", "history", "heritage", "palace",
                              "fort", "monument", "architecture", "other")},
    **{c: "spiritual" for c in ("temple", "church", "mosque", "religious_site")},
    **{c: "food" for c in ("cafe", "restaurant", "street_food", "dessert", "nightlife")},
    **{c: "shopping" for c in ("shopping", "market", "mall")},
    **{c: "fun" for c in ("entertainment", "gaming", "activity", "adventure")},
    **{c: "explore" for c in ("walking_area", "neighborhood")},
}
COMMERCIAL_GROUPS = {"food", "shopping"}


def _tokens(s: str) -> set[str]:
    return set(s.split())


def name_score(a: str, b: str) -> float:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 100.0
    score = float(fuzz.token_sort_ratio(na, nb))
    ta, tb = _tokens(na), _tokens(nb)
    if (ta <= tb or tb <= ta) and (ta ^ tb) <= GENERIC_TOKENS:
        score = max(score, 96.0)
    return score


def _compatible(record_cat: str, item: WDItem) -> bool | None:
    """True/False when the item's type is known, None when it is not."""
    cat = item.category
    if cat is None or record_cat == "other":
        return None
    return CATEGORY_GROUP.get(cat) == CATEGORY_GROUP.get(record_cat) or cat == record_cat


def link(records: list[dict], items: list[WDItem]) -> dict:
    """Attach wikidata ids to OSM records, one-to-one, best match first.

    Every candidate (record, item) pair within reach is scored; pairs are then
    assigned greedily by (name score, type compatibility, closeness), so the
    garden named "Lalbagh Botanical Gardens" wins the Lalbagh item over a
    restaurant called "Lalbagh Grand" 100 m away.
    """
    grid: dict[tuple[int, int], list[WDItem]] = {}
    for it in items:
        if it.settlement:
            continue
        grid.setdefault((int(it.lat * 20), int(it.lon * 20)), []).append(it)
    pairs = []
    for idx, r in enumerate(records):
        if r.get("wikidata_id") or r.get("is_chain"):
            continue
        reach = _reach_km(r["category"], r.get("extent_m"))
        span = int(reach / 5.5) + 1
        gi, gj = int(r["lat"] * 20), int(r["lon"] * 20)
        names = [r["name"], *r.get("aliases", [])]
        for di in range(-span, span + 1):
            for dj in range(-span, span + 1):
                for it in grid.get((gi + di, gj + dj), ()):
                    d = haversine_km(r["lat"], r["lon"], it.lat, it.lon)
                    if d > reach:
                        continue
                    s = max(max(name_score(n, it.label) for n in names),
                            name_score(r["name"], it.enwiki))
                    comp = _compatible(r["category"], it)
                    if comp is False:
                        continue
                    group = CATEGORY_GROUP.get(r["category"])
                    threshold = 88.0 if comp else (97.0 if group in COMMERCIAL_GROUPS else 92.0)
                    if s < threshold:
                        continue
                    pairs.append((s, 1 if comp else 0, -d, idx, it))
    pairs.sort(key=lambda p: (p[0], p[1], p[2], -p[3]), reverse=True)
    # Items already claimed by an OSM wikidata tag are not available again.
    taken_items: set[str] = {r["wikidata_id"] for r in records if r.get("wikidata_id")}
    taken_records: set[int] = set()
    linked = 0
    for s, _, _, idx, it in pairs:
        if it.qid in taken_items or idx in taken_records:
            continue
        taken_items.add(it.qid)
        taken_records.add(idx)
        r = records[idx]
        r["wikidata_id"] = it.qid
        r["wikidata_linked_by"] = "name+location"
        r["wikidata_label"] = it.label
        linked += 1
    existing = {r.get("wikidata_id") for r in records}
    unmatched = [it for it in items if not it.settlement and it.qid not in existing]
    return {"linked": linked, "unmatched": unmatched}


def items_to_records(items: list[WDItem], cfg) -> list[dict]:
    """Notable, categorisable Wikidata items with no OSM counterpart."""
    from app.geo.regions import distance_from_center_km, in_envelope, region_bucket
    out = []
    for it in items:
        cat = it.category
        if cat is None or it.settlement:
            continue
        d = distance_from_center_km(it.lat, it.lon, cfg)
        if not in_envelope(d, cfg):
            continue
        name = it.label
        if re.fullmatch(r"Q\d+", name):
            continue
        out.append({
            "source": "wikidata", "source_ref": it.qid, "osm_type": "wikidata", "osm_id": 0,
            "lat": round(it.lat, 7), "lon": round(it.lon, 7), "extent_m": None,
            "tags": {"name": name, "wikidata": it.qid, "wikipedia": f"en:{it.enwiki}"},
            "query_group": "wikidata", "distance_from_center_km": round(d, 3),
            "region_bucket": region_bucket(d, cfg).value, "name": name,
            "name_normalized": normalize_name(name), "category": cat, "secondary": [],
            "rule_tags": [], "rule_index": None, "wikidata_id": it.qid, "aliases": [],
            "generic_name": False, "is_chain": False, "chain_key": None,
        })
    return out
