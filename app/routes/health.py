"""Health check endpoint for monitoring and orchestration."""
from fastapi import APIRouter
from sqlalchemy import text

from app.database import async_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    checks = {"status": "healthy", "version": "1.0.0"}

    # Database connectivity
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as exc:
        checks["status"] = "unhealthy"
        checks["database"] = f"error: {exc.__class__.__name__}"

    status_code = 200 if checks["status"] == "healthy" else 503
    return checks if status_code == 200 else checks  # FastAPI handles both
