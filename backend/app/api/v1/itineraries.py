"""Saved plans.

GET    /itineraries        the signed-in user's plans, newest first
GET    /itineraries/{id}   one plan, shaped exactly like a fresh /plan reply
DELETE /itineraries/{id}   remove a plan

A plan is shown as it was made: the stop's name, category and cost basis come
from the stored notes, and the TripSpec and weather from its snapshot - so a
POI renamed next month doesn't rewrite last week's plan.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db
from app.models.user import User

router = APIRouter()

ATTRIBUTION = "© OpenStreetMap contributors, ODbL"

_LIST = text("""
    SELECT i.id, i.created_at, i.status, i.mode,
           t.payload->>'date'              AS date,
           t.payload->'origin'->>'name'    AS origin_name,
           v.total_cost_inr, v.total_duration_min, v.total_walk_m,
           (SELECT count(*) FROM itinerary_stops s WHERE s.version_id = v.id) AS stop_count,
           (SELECT string_agg(COALESCE(s.notes->>'name', p.name), ' → ' ORDER BY s.seq)
              FROM itinerary_stops s JOIN pois p ON p.id = s.poi_id
             WHERE s.version_id = v.id) AS stops
    FROM itineraries i
    JOIN tripspecs t          ON t.id = i.tripspec_id
    JOIN itinerary_versions v ON v.id = i.current_version_id
    WHERE i.user_id = :uid
    ORDER BY i.created_at DESC
    LIMIT :limit
""")

_HEADER = text("""
    SELECT i.id, i.created_at, i.mode, t.payload AS spec, v.id AS version_id,
           v.total_cost_inr, v.total_duration_min, v.total_walk_m,
           ps.weather, ps.optimizer_status, ps.solve_ms
    FROM itineraries i
    JOIN tripspecs t          ON t.id = i.tripspec_id
    JOIN itinerary_versions v ON v.id = i.current_version_id
    LEFT JOIN plan_snapshots ps ON ps.version_id = v.id
    WHERE i.id = :id AND i.user_id = :uid
""")

_STOPS = text("""
    SELECT s.seq, s.poi_id,
           COALESCE(s.notes->>'name', p.name)     AS name,
           COALESCE(s.notes->>'category', '')     AS category,
           COALESCE(s.notes->>'cost_basis', 'category_estimate') AS cost_basis,
           s.notes->>'hours_verified'             AS hours_verified,
           s.arrive_min, s.depart_min, s.visit_minutes, s.cost_inr,
           s.mode_from_prev,
           COALESCE(s.travel_seconds_from_prev, 0) / 60 AS travel_minutes_from_prev,
           ST_Y(p.geom::geometry) AS lat, ST_X(p.geom::geometry) AS lon,
           p.image_url, p.image_credit, p.image_license, p.image_source_url
    FROM itinerary_stops s
    JOIN pois p ON p.id = s.poi_id
    WHERE s.version_id = :vid
    ORDER BY s.seq
""")


@router.get("")
async def list_itineraries(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
) -> dict:
    """The signed-in user's saved plans, newest first."""
    rows = (await db.execute(_LIST, {"uid": user.id, "limit": min(limit, 100)})).mappings().all()
    return {"count": len(rows), "itineraries": [dict(r) for r in rows]}


@router.get("/{itinerary_id}")
async def get_itinerary(
    itinerary_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
) -> dict:
    """One saved plan, shaped like a fresh /plan reply so the UI renders it
    with the same components."""
    header = (await db.execute(_HEADER, {"id": itinerary_id, "uid": user.id})).mappings().first()
    if header is None:
        # Not found and not yours are the same answer: a plan's existence is
        # not something another account should be able to test for.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "No such plan.", "details": None}},
        )

    stops = (await db.execute(_STOPS, {"vid": header["version_id"]})).mappings().all()
    spec = header["spec"] or {}
    origin = spec.get("origin") or {}

    return {
        "ok": True,
        "itinerary": {
            "itinerary_id": header["id"],
            "status": "saved",
            "mode": header["mode"],
            "total_cost_inr": header["total_cost_inr"],
            "total_duration_min": header["total_duration_min"],
            "total_walk_m": header["total_walk_m"],
            "cost_note": ("Food and entry costs are typical estimates for each "
                          "category, not the venue's actual prices."),
            "unsatisfied_must": [],
            "solve_ms": header["solve_ms"] or 0,
            "origin": {"name": origin.get("name"), "lat": origin.get("lat"),
                       "lon": origin.get("lon")},
            "stops": [
                {**{k: v for k, v in dict(s).items() if k != "hours_verified"},
                 "hours_verified": (None if s["hours_verified"] is None
                                    else s["hours_verified"] == "true")}
                for s in stops
            ],
        },
        "weather": header["weather"] or {"available": False, "heavy_rain_expected": False,
                                         "max_precip_mm": 0, "mean_temp_c": None,
                                         "condition": "unknown"},
        "spec": spec,
        "relaxations_applied": [],
        "semantic_warnings": [],
        "timings_ms": {},
        "attribution": ATTRIBUTION,
        "created_at": header["created_at"].isoformat(),
    }


@router.delete("/{itinerary_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_itinerary(
    itinerary_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
) -> Response:
    """Delete a saved plan. Versions, stops and the snapshot cascade with it."""
    row = (await db.execute(
        text("SELECT tripspec_id FROM itineraries WHERE id = :id AND user_id = :uid"),
        {"id": itinerary_id, "uid": user.id})).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "No such plan.", "details": None}},
        )

    await db.execute(text("DELETE FROM itineraries WHERE id = :id"), {"id": itinerary_id})
    # The request that produced it is only useful while the plan exists.
    await db.execute(
        text("""DELETE FROM tripspecs WHERE id = :tid
                AND NOT EXISTS (SELECT 1 FROM itineraries WHERE tripspec_id = :tid)"""),
        {"tid": row[0]})
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)