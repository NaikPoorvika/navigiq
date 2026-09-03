"""NQ-016 - POI endpoints.

Public reference data. Auth is added in NQ-025 when user-scoped exclusions
(previously-visited POIs) enter the search.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.poi.search import (
    MAX_LIMIT,
    MAX_RADIUS_KM,
    get_poi_detail,
    search_pois,
)

router = APIRouter()


@router.get("/search")
async def search(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(3.0, gt=0, le=MAX_RADIUS_KM),
    category: list[str] | None = Query(None),
    open_at: datetime | None = Query(None),
    max_cost_inr: int | None = Query(None, ge=0),
    exclude_id: list[int] | None = Query(None),
    limit: int = Query(20, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = await search_pois(
        db, lat=lat, lon=lon, radius_km=radius_km,
        categories=category, open_at=open_at,
        max_cost_inr=max_cost_inr, exclude_ids=exclude_id, limit=limit,
    )
    return {
        "count": len(rows),
        "results": [r.to_dict() for r in rows],
        "attribution": "(c) OpenStreetMap contributors, ODbL",
    }


@router.get("/categories")
async def categories(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(text("""
        SELECT c.key, c.display_name, c.default_visit_minutes,
               c.is_indoor, c.typical_cost_inr, c.meal_category,
               count(p.id) AS poi_count
        FROM poi_categories c
        LEFT JOIN pois p ON p.primary_category = c.id AND p.active
        GROUP BY c.id ORDER BY c.id
    """))).all()
    return {
        "categories": [
            {
                "key": r.key,
                "display_name": r.display_name,
                "default_visit_minutes": r.default_visit_minutes,
                "is_indoor": r.is_indoor,
                "typical_cost_inr": r.typical_cost_inr,
                "meal_category": r.meal_category,
                "poi_count": r.poi_count,
            }
            for r in rows
        ]
    }


@router.get("/{poi_id}")
async def detail(poi_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    poi = await get_poi_detail(db, poi_id)
    if poi is None:
        raise HTTPException(status_code=404, detail="POI not found")
    poi["attribution"] = "(c) OpenStreetMap contributors, ODbL"
    return poi


@router.get("/{poi_id}/nearby")
async def nearby(
    poi_id: int,
    radius_km: float = Query(1.0, gt=0, le=5),
    category: list[str] | None = Query(None),
    limit: int = Query(10, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
) -> dict:
    poi = await get_poi_detail(db, poi_id)
    if poi is None:
        raise HTTPException(status_code=404, detail="POI not found")

    rows = await search_pois(
        db, lat=poi["lat"], lon=poi["lon"], radius_km=radius_km,
        categories=category, exclude_ids=[poi_id], limit=limit,
    )
    return {
        "origin": {"id": poi["id"], "name": poi["name"]},
        "count": len(rows),
        "results": [r.to_dict() for r in rows],
    }
