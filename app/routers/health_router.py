from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db import ping_db

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict:
    try:
        ping_db()
        return {"status": "ok", "database": "connected"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"DB health check failed: {exc}") from exc
