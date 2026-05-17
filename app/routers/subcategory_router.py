from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.search_schema import ErrorResponse, SubcategoryUnitsResponse
from app.services.search_service import get_units_by_subcategory

router = APIRouter(prefix="/api/subcategories", tags=["subcategories"])


@router.get(
    "/{subcategory_code}/units",
    response_model=SubcategoryUnitsResponse,
    responses={500: {"model": ErrorResponse}},
)
def subcategory_units(subcategory_code: str) -> dict:
    try:
        return get_units_by_subcategory(subcategory_code=subcategory_code)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"subcategory units lookup failed: {exc}") from exc
