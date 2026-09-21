from fastapi import APIRouter

from app.api.v1.assistant import me_extra, router as assistant_router
from app.api.v1.auth import me_router, router as auth_router
from app.api.v1.plans import router as plans_router
from app.api.v1.pois import collections_router, router as pois_router
from app.core.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(me_router, prefix="/me", tags=["me"])
api_router.include_router(me_extra, prefix="/me", tags=["me"])
api_router.include_router(pois_router, prefix="/pois", tags=["pois"])
api_router.include_router(collections_router, prefix="/collections", tags=["discovery"])
api_router.include_router(plans_router, prefix="/plans", tags=["plans"])
api_router.include_router(assistant_router, tags=["assistant"])


@api_router.get("/")
async def root() -> dict:
    return {"message": "NavigIQ API v1"}
