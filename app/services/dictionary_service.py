from __future__ import annotations

from sqlalchemy import text

from app.db import get_connection


def detect_department(normalized_query: str) -> dict | None:
    sql = """
    SELECT standard_department_name, synonym_name
    FROM T21_DEPARTMENT_DICTIONARY
    WHERE is_active = TRUE
      AND :query LIKE '%%' || lower(synonym_name) || '%%'
    ORDER BY length(synonym_name) DESC
    LIMIT 1
    """
    with get_connection() as conn:
        row = conn.execute(text(sql), {"query": normalized_query}).mappings().first()
    return dict(row) if row else None


def detect_job(normalized_query: str) -> dict | None:
    sql = """
    SELECT standard_job_name, synonym_name
    FROM T22_JOB_DICTIONARY
    WHERE is_active = TRUE
      AND :query LIKE '%%' || lower(synonym_name) || '%%'
    ORDER BY length(synonym_name) DESC
    LIMIT 1
    """
    with get_connection() as conn:
        row = conn.execute(text(sql), {"query": normalized_query}).mappings().first()
    return dict(row) if row else None


def map_department_to_jobs(standard_department_name: str, top_k: int) -> list[dict]:
    sql = """
    SELECT standard_job_name, match_weight, mapping_reason
    FROM T23_DEPARTMENT_JOB_MAPPING
    WHERE is_active = TRUE
      AND standard_department_name = :dept
    ORDER BY match_weight DESC, mapping_id ASC
    LIMIT :top_k
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql), {"dept": standard_department_name, "top_k": top_k}).mappings().all()
    return [dict(row) for row in rows]


def map_job_to_units(standard_job_name: str, top_k: int) -> list[dict]:
    sql = """
    SELECT unit_category_id, unit_name, match_weight, mapping_reason
    FROM T24_JOB_UNIT_MAPPING
    WHERE is_active = TRUE
      AND standard_job_name = :job
    ORDER BY match_weight DESC, mapping_id ASC
    LIMIT :top_k
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql), {"job": standard_job_name, "top_k": top_k}).mappings().all()
    return [dict(row) for row in rows]
