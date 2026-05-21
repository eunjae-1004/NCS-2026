from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_authenticated_member
from app.schemas.job_description_schema import JobDescriptionResponse
from app.schemas.search_schema import ErrorResponse
from app.services.job_description_service import get_job_description
from app.services.ncs_service import get_unit_structure

router = APIRouter(prefix="/api/units", tags=["units"])


@router.get(
    "/{unit_category_id}/structure",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def unit_structure(unit_category_id: str, _=Depends(require_authenticated_member)) -> dict:
    try:
        result = get_unit_structure(unit_category_id=unit_category_id)
        if not result:
            raise HTTPException(status_code=404, detail="해당 능력단위 구조를 찾을 수 없습니다.")
        return result
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"unit structure lookup failed: {exc}") from exc


@router.get(
    "/{unit_category_id}/job-description",
    response_model=JobDescriptionResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def unit_job_description(
    unit_category_id: str,
    _=Depends(require_authenticated_member),
) -> JobDescriptionResponse:
    try:
        result = get_job_description(unit_category_id=unit_category_id)
        if not result:
            raise HTTPException(status_code=404, detail="해당 능력단위 직무기술서를 찾을 수 없습니다.")
        return JobDescriptionResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"job description lookup failed: {exc}") from exc
