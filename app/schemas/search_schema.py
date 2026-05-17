from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="사용자 입력 문장")
    top_k: int = Field(10, ge=1, le=30, description="반환할 추천 개수")


class SubcategoryRecommendation(BaseModel):
    subcategory_code: str
    subcategory_name: str
    keyword_score: float
    vector_score: float
    final_score: float
    matched_keywords: list[str]
    reason: str


class JobRecommendation(BaseModel):
    job_name: str
    keyword_score: float
    vector_score: float
    final_score: float
    reason: str


class UnitRecommendation(BaseModel):
    unit_category_id: str
    unit_name: str
    unit_element_id: str
    unit_element_name: str
    keyword_score: float
    vector_score: float
    final_score: float
    reason: str


class FullSearchResponse(BaseModel):
    query: str
    normalized_query: str
    recommended_subcategories: list[SubcategoryRecommendation]
    recommended_jobs: list[JobRecommendation]
    recommended_units: list[UnitRecommendation]


class SubcategoryUnitsResponse(BaseModel):
    subcategory_code: str
    subcategory_name: str | None
    units: list[UnitRecommendation]


class JobUnitsResponse(BaseModel):
    job_name: str
    units: list[UnitRecommendation]


class ErrorResponse(BaseModel):
    detail: str
