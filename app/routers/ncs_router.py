from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.search_schema import ErrorResponse
from app.services.ncs_service import get_ncs_tree

router = APIRouter(prefix="/api/ncs", tags=["ncs"])


@router.get("/tree", responses={500: {"model": ErrorResponse}})
def ncs_tree() -> list[dict]:
    try:
        return get_ncs_tree()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"ncs tree lookup failed: {exc}") from exc
