"""NQ-011b - Place resolution endpoint.

GET /places/resolve?q=Indiranagar

For NQ-029 (B1): the LLM extracts a place NAME; this turns it into
coordinates. Never let the model supply lat/lon directly (ADR-002).

Act on `confidence`, not just `match`:
  high    plan with it
  medium  plan with it, and say which place was assumed
  low     ask - `alternatives` lists the other candidates
  none    ask - nothing matched
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.region import in_region
from app.api.deps import get_db
from app.services.places.resolver import resolve_place

router = APIRouter()


@router.get("/resolve")
async def resolve(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await resolve_place(db, q, limit=limit)
    return {
        **result.to_dict(),
        "attribution": "(c) OpenStreetMap contributors, ODbL",
    }

@router.get("/nearest")
async def nearest_place(
    lat: float,
    lon: float,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The gazetteer place closest to a point - for "use my location".

    Returns a NAME only. The caller keeps its own coordinates: the nearest
    named place is for showing the user where they are, not for moving them
    to the middle of a neighbourhood.
    """
    if not in_region(lat, lon):
        return {"in_region": False, "place": None}

    row = (await db.execute(text("""
        SELECT name, kind,
               ST_Distance(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS distance_m
        FROM places
        WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 5000)
        ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
        LIMIT 1
    """), {"lat": lat, "lon": lon})).mappings().first()

    return {"in_region": True, "place": dict(row) if row else None}