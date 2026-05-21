from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import load_settings
from app.services.example_query_service import list_search_example_queries
from app.routers.auth_router import router as auth_router
from app.routers.download_router import router as download_router
from app.routers.health_router import router as health_router
from app.routers.me_router import router as me_router
from app.routers.job_router import router as job_router
from app.routers.ncs_router import router as ncs_router
from app.routers.search_router import router as search_router
from app.routers.subcategory_router import router as subcategory_router
from app.routers.unit_router import router as unit_router
from app.utils.logger import get_logger

settings = load_settings()
logger = get_logger("ncs-api")
ROOT_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT_DIR / "web"
STATIC_DIR = WEB_DIR / "static"

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="NCS 추천 검색 API",
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(search_router)
app.include_router(subcategory_router)
app.include_router(job_router)
app.include_router(ncs_router)
app.include_router(unit_router)
app.include_router(download_router)


@app.get("/api/example-queries", tags=["search"])
def list_search_examples_alias(response: Response, limit: int = 12) -> list[dict]:
    """자연어 검색 예시 질문 (T28) — /api/search/examples 와 동일."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return list_search_example_queries(limit=limit)


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def web_root() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="웹앱 파일을 찾을 수 없습니다.")
    return FileResponse(
        str(index_path),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
