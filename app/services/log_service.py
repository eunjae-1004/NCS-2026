from __future__ import annotations

from sqlalchemy import text

from app.db import get_connection


def save_search_log(
    *,
    input_text: str,
    normalized_input_text: str,
    search_type: str,
    recommended_subcategory_code: str | None,
    recommended_subcategory_name: str | None,
    recommended_job_name: str | None,
    recommended_unit_category_id: str | None,
    recommended_unit_name: str | None,
    keyword_score: float,
    vector_score: float,
    final_score: float,
    matched_keywords: str,
    recommendation_reason: str,
) -> None:
    sql = """
    INSERT INTO T28_SEARCH_RESULT_LOG (
        input_text,
        normalized_input_text,
        search_type,
        recommended_subcategory_code,
        recommended_subcategory_name,
        recommended_job_name,
        recommended_unit_category_id,
        recommended_unit_name,
        keyword_score,
        vector_score,
        final_score,
        matched_keywords,
        recommendation_reason
    ) VALUES (
        :input_text,
        :normalized_input_text,
        :search_type,
        :recommended_subcategory_code,
        :recommended_subcategory_name,
        :recommended_job_name,
        :recommended_unit_category_id,
        :recommended_unit_name,
        :keyword_score,
        :vector_score,
        :final_score,
        :matched_keywords,
        :recommendation_reason
    )
    """
    params = {
        "input_text": input_text,
        "normalized_input_text": normalized_input_text,
        "search_type": search_type,
        "recommended_subcategory_code": recommended_subcategory_code,
        "recommended_subcategory_name": recommended_subcategory_name,
        "recommended_job_name": recommended_job_name,
        "recommended_unit_category_id": recommended_unit_category_id,
        "recommended_unit_name": recommended_unit_name,
        "keyword_score": keyword_score,
        "vector_score": vector_score,
        "final_score": final_score,
        "matched_keywords": matched_keywords,
        "recommendation_reason": recommendation_reason,
    }
    with get_connection() as conn:
        conn.execute(text(sql), params)
