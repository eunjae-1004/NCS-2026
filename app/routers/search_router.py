from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.schemas.search_schema import (
    ErrorResponse,
    FullSearchResponse,
    JobRecommendation,
    QueryRequest,
    SearchExampleQuery,
    SubcategoryRecommendation,
    UnitRecommendation,
)
from app.services.example_query_service import list_search_example_queries
from app.services.search_service import search_full, search_jobs, search_subcategories, search_units

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get(
    "/examples",
    response_model=list[SearchExampleQuery],
    responses={500: {"model": ErrorResponse}},
)
def search_examples(response: Response, limit: int = 12) -> list[dict]:
    try:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return list_search_example_queries(limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"example query lookup failed: {exc}") from exc


@router.post("/full", response_model=FullSearchResponse, responses={500: {"model": ErrorResponse}})
def full_search(payload: QueryRequest) -> dict:
    try:
        return search_full(query=payload.query, top_k=payload.top_k)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"full search failed: {exc}") from exc


@router.post(
    "/subcategories",
    response_model=list[SubcategoryRecommendation],
    responses={500: {"model": ErrorResponse}},
)
def subcategories_search(payload: QueryRequest) -> list[dict]:
    try:
        return search_subcategories(query=payload.query, top_k=payload.top_k)["recommended_subcategories"]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"subcategory search failed: {exc}") from exc


@router.post("/jobs", response_model=list[JobRecommendation], responses={500: {"model": ErrorResponse}})
def jobs_search(payload: QueryRequest) -> list[dict]:
    try:
        return search_jobs(query=payload.query, top_k=payload.top_k)["recommended_jobs"]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"job search failed: {exc}") from exc


@router.post("/units", response_model=list[UnitRecommendation], responses={500: {"model": ErrorResponse}})
def units_search(payload: QueryRequest) -> list[dict]:
    try:
        return search_units(query=payload.query, top_k=payload.top_k)["recommended_units"]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"unit search failed: {exc}") from exc
