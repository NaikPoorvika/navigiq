from fastapi import APIRouter
from app.core.health import router as health_router
from app.api.v1.auth import router as auth_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])

@api_router.get("/")
async def root():
    return {"message": "NavigIQ API v1"}
