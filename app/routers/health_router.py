from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from app.config import load_settings
from app.db import ping_db

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict:
    try:
        ping_db()
        settings = load_settings()
        return {
            "status": "ok",
            "database": "connected",
            "app_version": settings.app_version,
            "deploy_commit": os.getenv("RAILWAY_GIT_COMMIT_SHA", ""),
            "web_asset": "20260523-final",
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"DB health check failed: {exc}") from exc
