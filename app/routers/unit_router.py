from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_member
from app.schemas.search_schema import ErrorResponse
from app.services.ncs_service import get_unit_structure

router = APIRouter(prefix="/api/units", tags=["units"])


@router.get(
    "/{unit_category_id}/structure",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def unit_structure(unit_category_id: str, _: str = Depends(require_member)) -> dict:
    try:
        result = get_unit_structure(unit_category_id=unit_category_id)
        if not result:
            raise HTTPException(status_code=404, detail="해당 능력단위 구조를 찾을 수 없습니다.")
        return result
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"unit structure lookup failed: {exc}") from exc
