from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.search_schema import ErrorResponse, JobUnitsResponse
from app.services.search_service import get_units_by_job_name

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get(
    "/{job_name}/units",
    response_model=JobUnitsResponse,
    responses={500: {"model": ErrorResponse}},
)
def job_units(job_name: str) -> dict:
    try:
        return get_units_by_job_name(job_name=job_name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"job units lookup failed: {exc}") from exc
