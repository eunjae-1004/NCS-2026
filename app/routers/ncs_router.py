from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import CurrentUser, get_optional_user
from app.schemas.search_schema import ErrorResponse, UnitMatrixResponse
from app.services.ncs_service import get_ncs_tree, get_unit_ncs_meta
from app.services.unit_matrix_service import get_units_matrix, list_minor_categories

router = APIRouter(prefix="/api/ncs", tags=["ncs"])


@router.get("/unit-meta/{unit_category_id}", responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
def unit_ncs_meta(unit_category_id: str) -> dict:
    try:
        meta = get_unit_ncs_meta(unit_category_id)
        if not meta:
            raise HTTPException(status_code=404, detail="해당 능력단위 메타를 찾을 수 없습니다.")
        return meta
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"unit meta lookup failed: {exc}") from exc


@router.get("/tree", responses={500: {"model": ErrorResponse}})
def ncs_tree() -> list[dict]:
    try:
        return get_ncs_tree()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"ncs tree lookup failed: {exc}") from exc


@router.get("/minor-categories", responses={500: {"model": ErrorResponse}})
def minor_categories() -> list[str]:
    try:
        return list_minor_categories()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"minor categories lookup failed: {exc}") from exc


@router.get("/units-matrix", response_model=UnitMatrixResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
def units_matrix(
    minor_category_name: str = Query(..., min_length=1, description="소분류명"),
    user: CurrentUser | None = Depends(get_optional_user),
) -> UnitMatrixResponse:
    try:
        user_id = user.user_id if user and user.user_id > 0 else None
        data = get_units_matrix(minor_category_name.strip(), user_id=user_id)
        if not data["units"]:
            raise HTTPException(status_code=404, detail="해당 소분류에 능력단위가 없습니다.")
        return UnitMatrixResponse(**data)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"units matrix lookup failed: {exc}") from exc
