from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.search_schema import ErrorResponse
from app.services.ncs_service import export_basic_ncs_csv

router = APIRouter(prefix="/api/download", tags=["download"])


@router.get("/basic-ncs", responses={500: {"model": ErrorResponse}})
def download_basic_ncs() -> StreamingResponse:
    try:
        csv_io = export_basic_ncs_csv()
        return StreamingResponse(
            iter([csv_io.getvalue()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=basic_ncs.csv"},
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"basic ncs download failed: {exc}") from exc
