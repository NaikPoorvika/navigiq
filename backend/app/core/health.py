from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from app.db.session import engine
from app.core.redis import redis_client

router = APIRouter()

@router.get("/health")
async def health_check():
    status = {
        "status": "ok",
        "database": "unknown",
        "redis": "unknown"
    }
    
    # Check Database
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        status["database"] = "ok"
    except Exception as e:
        status["database"] = "error"
        status["status"] = "degraded"
        status["database_error"] = str(e)
        
    # Check Redis
    try:
        if await redis_client.ping():
            status["redis"] = "ok"
        else:
            status["redis"] = "error"
            status["status"] = "degraded"
    except Exception as e:
        status["redis"] = "error"
        status["status"] = "degraded"
        status["redis_error"] = str(e)
        
    return status
