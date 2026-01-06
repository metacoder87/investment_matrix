from fastapi import APIRouter, Depends, HTTPException
from app.redis_client import redis_client

router = APIRouter(prefix="/system", tags=["System"])

@router.post("/cache/clear")
async def clear_cache():
    """
    Clears the entire Redis cache.
    Useful for resetting the application state or debugging.
    """
    try:
        await redis_client.flushdb()
        return {"status": "success", "message": "Cache cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
