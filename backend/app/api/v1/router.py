from fastapi import APIRouter
from app.core.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.pois import router as pois_router
from app.api.v1.plan import router as plan_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(pois_router, prefix="/pois", tags=["pois"])
api_router.include_router(plan_router, prefix="/plan", tags=["planning"])

@api_router.get("/")
async def root():
    return {"message": "NavigIQ API v1"}




