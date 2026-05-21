from __future__ import annotations

from sqlalchemy import text

from app.db import get_connection

_ORG_SUFFIXES = ("팀", "부", "과", "실", "처", "본부")


def strip_org_suffix(name: str) -> str:
    """총무팀 -> 총무, 품질관리팀 -> 품질관리"""
    value = name.strip()
    if not value:
        return value
    for suffix in _ORG_SUFFIXES:
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)].strip()
    return value


def detect_department(normalized_query: str) -> dict | None:
    names = detect_department_names(normalized_query, max_departments=1)
    return names[0] if names else None


def detect_department_names(normalized_query: str, max_departments: int = 25) -> list[dict]:
    """
    질의에 맞는 부서(표준명) 목록을 반환한다.
    - 먼저 질의 문자열에 동의어가 포함되는 경우(예: 총무팀)
    - 없으면 조직 접미어 제거 stem으로 동의어/표준명 부분 일치(예: 품질팀 -> 품질)
    """
    query = normalized_query.strip()
    if not query:
        return []

    sql_exact = """
    SELECT standard_department_name, synonym_name
    FROM T21_DEPARTMENT_DICTIONARY
    WHERE is_active = TRUE
      AND :query LIKE '%%' || lower(synonym_name) || '%%'
    ORDER BY length(synonym_name) DESC
    LIMIT 1
    """
    stem = strip_org_suffix(query.replace(" ", ""))
    sql_stem = """
    SELECT
        standard_department_name,
        max(length(synonym_name)) AS synonym_len
    FROM T21_DEPARTMENT_DICTIONARY
    WHERE is_active = TRUE
      AND (
        lower(synonym_name) LIKE '%%' || :stem || '%%'
        OR lower(standard_department_name) LIKE '%%' || :stem || '%%'
      )
    GROUP BY standard_department_name
    ORDER BY synonym_len DESC, standard_department_name
    LIMIT :max_departments
    """
    with get_connection() as conn:
        exact = conn.execute(text(sql_exact), {"query": query}).mappings().first()
        if exact:
            return [dict(exact)]

        if len(stem) < 2:
            return []

        rows = conn.execute(
            text(sql_stem),
            {"stem": stem.lower(), "max_departments": max_departments},
        ).mappings().all()

    return [
        {
            "standard_department_name": row["standard_department_name"],
            "synonym_name": stem,
        }
        for row in rows
        if row.get("standard_department_name")
    ]


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
