from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from app.redis_client import redis_client
from app.config import settings

router = APIRouter(prefix="/system", tags=["System"])

api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)

async def verify_admin_key(api_key: str = Depends(api_key_header)):
    if not settings.ADMIN_KEY or api_key != settings.ADMIN_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return api_key

@router.post("/cache/clear", dependencies=[Depends(verify_admin_key)])
async def clear_cache():
    """
    Clears the entire Redis cache.
    Useful for resetting the application state or debugging.
    Requires X-Admin-Key header.
    """
    try:
        await redis_client.flushdb()
        return {"status": "success", "message": "Cache cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
