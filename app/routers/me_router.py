from __future__ import annotations

from sqlalchemy.exc import IntegrityError, ProgrammingError

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.auth import CurrentUser, require_authenticated_member
from app.schemas.search_schema import ErrorResponse, SuggestedMinorCategoryResponse, UnitMatrixResponse
from app.services.unit_matrix_service import get_user_units_matrix, suggest_minor_category_for_user
from app.schemas.user_schema import (
    UserUnitSelectionListResponse,
    UserUnitSelectionRequest,
    UserUnitSelectionResponse,
)
from app.services.export_service import build_export_content_disposition, build_user_units_excel
from app.services.user_service import (
    add_user_unit_selection,
    list_user_unit_selections,
    remove_user_unit_selection,
)
from app.utils.logger import get_logger

router = APIRouter(prefix="/api/me", tags=["me"])
_log = get_logger("ncs-me-router")


def _selection_response(row: dict) -> UserUnitSelectionResponse:
    return UserUnitSelectionResponse(
        selection_id=int(row["selection_id"]),
        unit_category_id=str(row["unit_category_id"]),
        unit_name=row.get("unit_name"),
        subcategory_code=row.get("subcategory_code"),
        subcategory_name=row.get("subcategory_name"),
        created_at=row.get("created_at"),
    )


@router.get(
    "/units/matrix",
    response_model=UnitMatrixResponse,
    responses={401: {"model": ErrorResponse}},
)
def my_units_matrix(
    current_user: CurrentUser = Depends(require_authenticated_member),
) -> UnitMatrixResponse:
    data = get_user_units_matrix(current_user.user_id)
    return UnitMatrixResponse(**data)


@router.get(
    "/units/suggested-minor",
    response_model=SuggestedMinorCategoryResponse,
    responses={401: {"model": ErrorResponse}},
)
def suggested_minor_category(
    current_user: CurrentUser = Depends(require_authenticated_member),
) -> SuggestedMinorCategoryResponse:
    minor = suggest_minor_category_for_user(current_user.user_id)
    return SuggestedMinorCategoryResponse(minor_category_name=minor)


@router.get(
    "/units",
    response_model=UserUnitSelectionListResponse,
    responses={401: {"model": ErrorResponse}},
)
def list_my_units(
    current_user: CurrentUser = Depends(require_authenticated_member),
) -> UserUnitSelectionListResponse:
    rows = list_user_unit_selections(current_user.user_id)
    items = [_selection_response(row) for row in rows]
    return UserUnitSelectionListResponse(items=items, total=len(items))


@router.post(
    "/units",
    response_model=UserUnitSelectionResponse,
    responses={401: {"model": ErrorResponse}},
)
def save_my_unit(
    payload: UserUnitSelectionRequest,
    current_user: CurrentUser = Depends(require_authenticated_member),
) -> UserUnitSelectionResponse:
    if current_user.user_id <= 0:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        row = add_user_unit_selection(
            current_user.user_id,
            {
                "unit_category_id": payload.unit_category_id.strip(),
                "unit_name": payload.unit_name,
                "subcategory_code": payload.subcategory_code,
                "subcategory_name": payload.subcategory_name,
            },
        )
    except IntegrityError as exc:
        pgmsg = getattr(getattr(exc, "orig", None), "pgerror", None) or str(exc)
        _log.warning("save_my_unit integrity/FK 또는 PK 오류: %s", pgmsg)
        raise HTTPException(
            status_code=409,
            detail=(
                "DB 무결성 제약으로 저장할 수 없습니다. CSV 임포트 후에는 "
                "PostgreSQL에서 sql/005_fix_serial_sequences_after_import.sql(특히 T29·T30)을 "
                "실행했는지 확인하거나, 로그인 사용자와 T29 회원 행 일치 여부를 확인해 주세요."
            ),
        ) from exc
    except ProgrammingError as exc:
        pgmsg = getattr(getattr(exc, "orig", None), "pgerror", None) or str(exc)
        lowered = pgmsg.lower()
        if (
            "on conflict" in lowered
            or "unique or exclusion constraint" in lowered
            or "42p10" in lowered
        ):
            _log.warning("T30 ON CONFLICT error (missing UNIQUE?): %s", pgmsg)
            raise HTTPException(
                status_code=500,
                detail=(
                    "DB에 T30(user_id, unit_category_id) UNIQUE 제약이 없어 저장할 수 없습니다. "
                    "Railway Postgres에서 sql/006_t30_unique_constraint_for_upsert.sql 을 실행하세요."
                ),
            ) from exc
        _log.exception("save_my_unit DB error")
        raise HTTPException(
            status_code=500,
            detail="능력단위 저장 중 DB 오류가 발생했습니다. 관리자에게 문의하세요.",
        ) from exc

    return _selection_response(row)


@router.get(
    "/units/export",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def export_my_units_excel(
    current_user: CurrentUser = Depends(require_authenticated_member),
) -> Response:
    try:
        content, ascii_filename, display_filename = build_user_units_excel(current_user.user_id)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": build_export_content_disposition(
                    ascii_filename, display_filename
                ),
                "Cache-Control": "no-store",
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"엑셀 다운로드 실패: {exc}") from exc


@router.delete(
    "/units/{unit_category_id}",
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def delete_my_unit(
    unit_category_id: str,
    current_user: CurrentUser = Depends(require_authenticated_member),
) -> dict:
    if current_user.user_id <= 0:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    removed = remove_user_unit_selection(current_user.user_id, unit_category_id)
    if not removed:
        raise HTTPException(status_code=404, detail="저장된 능력단위를 찾을 수 없습니다.")
    return {"ok": True, "unit_category_id": unit_category_id}
