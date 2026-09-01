from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config import settings

router = APIRouter()

# Create engine for health check probe. 
# In a real app this might be shared, but for early NQ-004 we test connectivity here directly.
engine = create_async_engine(settings.DATABASE_URL, echo=False)

@router.get("/health")
async def health_check():
    status = {
        "status": "ok",
        "database": "unknown",
        "version": "0.1.0"
    }
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            status["database"] = "connected"
    except Exception as e:
        status["database"] = "unreachable"
        raise HTTPException(status_code=503, detail=status)
    
    return status
