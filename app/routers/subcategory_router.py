from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from app.schemas.search_schema import BulkSubcategoryUnitsResponse, ErrorResponse, SubcategoryUnitsResponse
from app.services.search_service import get_units_by_subcategory, get_units_by_subcategory_patterns

router = APIRouter(prefix="/api/subcategories", tags=["subcategories"])


@router.get(
    "/units-by-patterns",
    response_model=BulkSubcategoryUnitsResponse,
    responses={500: {"model": ErrorResponse}},
)
def subcategory_units_by_patterns(codes: str) -> dict:
    """
  codes: 콤마 구분 분류 코드 (예: 020201,020203)
  6자리는 세분류 코드 prefix, 8자리는 세분류 코드 exact 로 해석한다.
    """
    try:
        patterns = list(dict.fromkeys(re.findall(r"\d{6,8}", codes)))
        if not patterns:
            raise HTTPException(status_code=400, detail="codes 파라미터가 비어 있습니다.")
        return get_units_by_subcategory_patterns(patterns)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"subcategory bulk units lookup failed: {exc}",
        ) from exc


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
