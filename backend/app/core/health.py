from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from app.db.session import engine

router = APIRouter()

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
