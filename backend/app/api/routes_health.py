from datetime import UTC, datetime

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "battleship-backend",
        "ts": datetime.now(tz=UTC).isoformat(),
    }
