"""NQ-011b - Resolve a place name to coordinates.

The LLM must never produce coordinates (ADR-002). Extraction emits
origin: {"name": "Indiranagar"} with no lat/lon, and this resolves it.

TWO SOURCES, because a user can name either:
  places  - suburbs, neighbourhoods, villages. "Indiranagar", "Jayanagar"
  pois    - named destinations. "Cubbon Park", "Lalbagh", "Nandi Hills"

Searching only places resolves "Cubbon Park" to "Cubbonpet", a neighbourhood
a kilometre away - confidently wrong. An exact POI name therefore beats a
fuzzy place match.

RANKING MATTERS. 'Koramangala' matches two places at similarity 1.000: the
Bengaluru suburb and a village 45 km north.

CONFIDENCE MATTERS TOO. A low-confidence match is a clarifying question, not
a guess. There are two real Indiranagars 9 km apart.

DUPLICATES ARE NOT AMBIGUITY. OSM has "Nandi Hill" and "NandiHill" as separate
nodes at the same spot. Candidates within ~200 m are the same place and must
not trigger a clarifying question.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.region import CENTRE_LAT, CENTRE_LON
MAX_USEFUL_DISTANCE_KM = 60.0
MIN_SIMILARITY = 0.35

KIND_BONUS = {
    "suburb": 0.30, "neighbourhood": 0.25, "borough": 0.25,
    "city": 0.20, "town": 0.15, "quarter": 0.15,
    "locality": 0.05, "village": 0.0, "hamlet": 0.0,
}

# A named destination the user asked for by name is at least as good an
# answer as a neighbourhood. Applied to POI matches.
POI_BONUS = 0.20
EXACT_NAME_BONUS = 0.25

HIGH_CONFIDENCE_GAP = 0.30
MEDIUM_CONFIDENCE_GAP = 0.15

# ~200 m in degrees at Bengaluru's latitude. Closer than this, two candidates
# are the same place under different names.
SAME_PLACE_DEGREES = 0.002


def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


@dataclass
class PlaceMatch:
    name: str
    lat: float
    lon: float
    kind: str
    source: str                      # "place" | "poi"
    score: float
    similarity: float
    distance_from_centre_km: float

    def to_dict(self) -> dict:
        return {
            "name": self.name, "lat": self.lat, "lon": self.lon,
            "kind": self.kind, "source": self.source,
            "score": round(self.score, 3),
            "similarity": round(self.similarity, 3),
            "distance_from_centre_km": round(self.distance_from_centre_km, 1),
        }


@dataclass
class ResolveResult:
    query: str
    match: PlaceMatch | None
    alternatives: list[PlaceMatch]
    confidence: str                  # high | medium | low | none
    needs_clarification: bool

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "match": self.match.to_dict() if self.match else None,
            "alternatives": [a.to_dict() for a in self.alternatives],
            "confidence": self.confidence,
            "needs_clarification": self.needs_clarification,
        }


_PLACE_SQL = text("""
SELECT name, kind,
       ST_Y(geom::geometry) AS lat,
       ST_X(geom::geometry) AS lon,
       similarity(name_normalized, :q) AS sim,
       ST_Distance(geom, ST_SetSRID(ST_MakePoint(:clon, :clat), 4326)::geography)
           / 1000 AS dist_km,
       (name_normalized = :q) AS exact
FROM places
WHERE similarity(name_normalized, :q) >= :min_sim
ORDER BY sim DESC
LIMIT 30
""")

_POI_SQL = text("""
SELECT p.name, c.key AS kind,
       ST_Y(p.geom::geometry) AS lat,
       ST_X(p.geom::geometry) AS lon,
       similarity(p.name_normalized, :q) AS sim,
       ST_Distance(p.geom, ST_SetSRID(ST_MakePoint(:clon, :clat), 4326)::geography)
           / 1000 AS dist_km,
       (p.name_normalized = :q) AS exact
FROM pois p
JOIN poi_categories c ON c.id = p.primary_category
WHERE p.active AND similarity(p.name_normalized, :q) >= :min_sim
ORDER BY sim DESC
LIMIT 20
""")


def _score(row, source: str) -> PlaceMatch:
    proximity = 0.20 * max(0.0, 1 - (row.dist_km / MAX_USEFUL_DISTANCE_KM))
    bonus = POI_BONUS if source == "poi" else KIND_BONUS.get(row.kind, 0.0)
    score = (float(row.sim) + bonus + proximity
             + (EXACT_NAME_BONUS if row.exact else 0.0))
    return PlaceMatch(
        name=row.name, lat=float(row.lat), lon=float(row.lon),
        kind=row.kind, source=source, score=score,
        similarity=float(row.sim), distance_from_centre_km=float(row.dist_km),
    )


def _is_distinct(a: PlaceMatch, b: PlaceMatch) -> bool:
    """False when two candidates are the same place under different names."""
    return (abs(a.lat - b.lat) > SAME_PLACE_DEGREES
            or abs(a.lon - b.lon) > SAME_PLACE_DEGREES)


async def resolve_place(
    db: AsyncSession, query: str, limit: int = 5,
) -> ResolveResult:
    """Resolve a place or destination name to coordinates."""
    q = normalize_name(query)
    if not q:
        return ResolveResult(query, None, [], "none", True)

    params = {"q": q, "clat": CENTRE_LAT, "clon": CENTRE_LON,
              "min_sim": MIN_SIMILARITY}

    place_rows = (await db.execute(_PLACE_SQL, params)).all()
    poi_rows = (await db.execute(_POI_SQL, params)).all()

    scored = ([_score(r, "place") for r in place_rows]
              + [_score(r, "poi") for r in poi_rows])

    if not scored:
        return ResolveResult(query, None, [], "none", True)

    scored.sort(key=lambda m: m.score, reverse=True)
    best = scored[0]

    # Only candidates at genuinely different locations count as alternatives.
    distinct = [m for m in scored[1:] if _is_distinct(best, m)]
    gap = best.score - distinct[0].score if distinct else 1.0

    if gap >= HIGH_CONFIDENCE_GAP:
        confidence = "high"
    elif gap >= MEDIUM_CONFIDENCE_GAP:
        confidence = "medium"
    else:
        confidence = "low"

    return ResolveResult(
        query=query, match=best, alternatives=distinct[:limit],
        confidence=confidence,
        needs_clarification=confidence == "low",
    )