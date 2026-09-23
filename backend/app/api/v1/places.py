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