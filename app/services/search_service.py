from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import text

from app.db import get_connection
from app.services.dictionary_service import (
    detect_department,
    detect_department_names,
    detect_job,
    map_department_to_jobs,
    map_job_to_units,
    strip_org_suffix,
)
from app.services.log_service import save_search_log
from app.services.normalize_service import build_query_variants, extract_keywords, normalize_query
from app.services.vector_service import vector_search

MIN_JOB_SCORE = 0.20
PAYROLL_INTENT_HINTS = {
    "급여계산",
    "급여 지급",
    "급여지급",
    "급여 정산",
    "4대보험",
    "원천징수",
    "연말정산",
    "인건비",
    "임금",
}
PAYROLL_CONTEXT_TERMS = {
    "급여계산",
    "급여지급",
    "4대보험",
    "원천징수",
    "연말정산",
    "인사",
    "근태",
    "임금",
    "세액",
    "공제",
    "급여대장",
}
LIVESTOCK_FEEDING_TERMS = {
    "사료",
    "급여할 수 있다",
    "한우",
    "축산",
    "입식",
    "송아지",
    "tmr",
    "tmf",
    "비육",
}


def _score_to_float(value: object) -> float:
    return float(value or 0.0)


def _contains_any(text: str, terms: set[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _is_payroll_intent(normalized_query: str, keywords: list[str]) -> bool:
    text = f"{normalized_query} {' '.join(keywords)}".lower()
    if _contains_any(text, PAYROLL_INTENT_HINTS):
        return True
    return "급여" in text and ("계산" in text or "지급" in text)


def _payroll_domain_penalty(text: str, payroll_intent: bool) -> float:
    if not payroll_intent:
        return 1.0
    if _contains_any(text, LIVESTOCK_FEEDING_TERMS) and not _contains_any(text, PAYROLL_CONTEXT_TERMS):
        # "급여계산" 의도인데 "사료 급여" 문맥이면 강하게 감점한다.
        return 0.02
    return 1.0


def _department_text_tokens(dept: dict | None) -> list[str]:
    if not dept:
        return []
    candidates = [
        str(dept.get("standard_department_name") or ""),
        str(dept.get("synonym_name") or ""),
    ]
    tokens: list[str] = []
    for candidate in candidates:
        lowered = candidate.lower().strip()
        if not lowered:
            continue
        tokens.append(lowered)
        # "총무팀" -> "총무" 같이 조직 접미어를 제거한 토큰도 함께 본다.
        stripped = lowered
        for suffix in ("팀", "부", "과", "실", "처", "본부"):
            if stripped.endswith(suffix) and len(stripped) > len(suffix):
                stripped = stripped[: -len(suffix)].strip()
                break
        if stripped and stripped not in tokens:
            tokens.append(stripped)
        # "총무·인사" 같은 표기는 분리 토큰도 함께 본다.
        for part in lowered.replace("·", "/").replace("-", "/").split("/"):
            part = part.strip()
            if part and part not in tokens:
                tokens.append(part)
    return tokens


def _department_affinity_multiplier(text: str, dept_tokens: list[str]) -> float:
    if not dept_tokens:
        return 1.0
    lowered = text.lower()
    if any(token in lowered for token in dept_tokens):
        return 1.15
    return 0.7


def _task_focus_multiplier(text: str, content_tokens: list[str]) -> float:
    """
    부서 매칭이 있어도 업무 의도 토큰(예: 사업계획, 수립)과의 일치도가 낮으면 감점한다.
    """
    if not content_tokens:
        return 1.0
    affinity = _name_token_affinity(text, content_tokens)
    if affinity < 0.2:
        return 0.3
    if affinity < 0.5:
        return 0.75
    return 1.1


def _extract_content_tokens(keywords: list[str], dept_synonym: str) -> list[str]:
    tokens: list[str] = []
    for token in keywords:
        if not token:
            continue
        if dept_synonym and (dept_synonym in token or token in dept_synonym):
            continue
        tokens.append(token)
    return tokens


def _looks_like_department_query(normalized: str) -> bool:
    compact = normalized.replace(" ", "")
    return any(compact.endswith(suffix) for suffix in ("팀", "부", "과", "실", "처", "본부")) and len(compact) >= 3


def _has_ncs_minor_category_exact_match(normalized_query: str) -> bool:
    """NCS 소분류명(예: 품질관리, 코드 020402*)과 질의가 일치하는지 확인한다."""
    query = normalized_query.strip().lower()
    if len(query) < 2:
        return False
    sql = """
    SELECT 1
    FROM T25_NCS_SEARCH_INDEX
    WHERE lower(coalesce(minor_category_name, '')) = :query
    LIMIT 1
    """
    with get_connection() as conn:
        row = conn.execute(text(sql), {"query": query}).mappings().first()
    return row is not None


def _ncs_minor_category_query_term(normalized_query: str) -> str | None:
    """
    질의 또는 조직 접미어 제거 stem이 NCS 소분류명과 일치하면 해당 명칭을 반환한다.
    예) 품질관리 -> 품질관리, 품질관리팀 -> 품질관리
    """
    compact = normalized_query.strip().replace(" ", "")
    if len(compact) < 2:
        return None
    if _has_ncs_minor_category_exact_match(compact):
        return compact
    stem = strip_org_suffix(compact)
    if (
        stem
        and stem != compact
        and len(stem) >= 2
        and _has_ncs_minor_category_exact_match(stem)
    ):
        return stem
    return None


def _build_units_from_ncs_minor_category(normalized_query: str, top_k: int) -> list[dict]:
    """
    NCS 소분류(minor_category_name)와 질의가 정확히 일치할 때 해당 분류의 능력단위를 반환한다.
    예) 품질관리 -> 02040201(QM/QC관리) 등
    """
    query = normalized_query.strip().lower()
    limit = max(top_k * 3, 20)
    sql = """
    SELECT DISTINCT ON (unit_category_id)
        unit_category_id,
        unit_name,
        unit_element_id,
        unit_element_name,
        major_category_name,
        middle_category_name,
        minor_category_name,
        subcategory_code,
        subcategory_name
    FROM T25_NCS_SEARCH_INDEX
    WHERE lower(coalesce(minor_category_name, '')) = :query
    ORDER BY unit_category_id, search_index_id ASC
    LIMIT :limit
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql), {"query": query, "limit": limit}).mappings().all()

    recs: list[dict] = []
    for meta in rows:
        recs.append(
            {
                "unit_category_id": meta["unit_category_id"],
                "unit_name": meta["unit_name"],
                "unit_element_id": meta["unit_element_id"],
                "unit_element_name": meta["unit_element_name"],
                "major_category_name": meta.get("major_category_name"),
                "middle_category_name": meta.get("middle_category_name"),
                "minor_category_name": meta.get("minor_category_name"),
                "subcategory_code": meta.get("subcategory_code"),
                "subcategory_name": meta.get("subcategory_name"),
                "keyword_score": 1.0,
                "vector_score": 0.0,
                "final_score": 1.0,
                "reason": f"NCS 소분류 '{meta.get('minor_category_name')}' 직접 매칭",
            }
        )
    return recs


def _merge_unit_recommendations(primary: list[dict], secondary: list[dict], top_k: int) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in primary + secondary:
        unit_category_id = str(item.get("unit_category_id") or "")
        if not unit_category_id:
            continue
        prev = merged.get(unit_category_id)
        if prev is None or _score_to_float(item.get("final_score")) > _score_to_float(prev.get("final_score")):
            merged[unit_category_id] = item
    return sorted(
        merged.values(),
        key=lambda row: _score_to_float(row.get("final_score")),
        reverse=True,
    )[:top_k]


def _is_department_only_query(
    normalized: str,
    content_tokens: list[str],
    dept: dict | None,
) -> bool:
    """질의가 부서명만 포함하고 업무 키워드는 없을 때 (예: 총무팀, 품질팀)."""
    if _ncs_minor_category_query_term(normalized):
        return False
    if dept and not content_tokens:
        return True
    if not _looks_like_department_query(normalized):
        return False
    stem = strip_org_suffix(normalized.replace(" ", ""))
    task_tokens = [
        token
        for token in content_tokens
        if not (stem and (stem in token or token in stem))
    ]
    return not task_tokens


def _build_units_from_department(
    standard_department_name: str,
    dept_synonym: str,
    top_k: int,
) -> list[dict]:
    """
    부서-직무(T23)·직무-능력단위(T24) 매핑으로 해당 부서 소속 능력단위 후보를 구성한다.
    """
    limit_units = max(top_k * 3, 20)
    sql_weights = """
    WITH dept_jobs AS (
        SELECT standard_job_name, match_weight AS job_weight
        FROM T23_DEPARTMENT_JOB_MAPPING
        WHERE is_active = TRUE
          AND standard_department_name = :dept
        ORDER BY match_weight DESC, mapping_id ASC
        LIMIT :limit_jobs
    )
    SELECT
        m.unit_category_id,
        max(m.match_weight * dj.job_weight) AS mapping_score
    FROM T24_JOB_UNIT_MAPPING m
    JOIN dept_jobs dj
      ON dj.standard_job_name = m.standard_job_name
    WHERE m.is_active = TRUE
    GROUP BY m.unit_category_id
    ORDER BY mapping_score DESC, m.unit_category_id
    LIMIT :limit_units
    """
    sql_meta_bulk = """
    SELECT DISTINCT ON (unit_category_id)
        unit_category_id,
        unit_name,
        unit_element_id,
        unit_element_name,
        major_category_name,
        middle_category_name,
        minor_category_name,
        subcategory_code,
        subcategory_name
    FROM T25_NCS_SEARCH_INDEX
    WHERE unit_category_id = ANY(:unit_category_ids)
    ORDER BY unit_category_id, search_index_id ASC
    """
    with get_connection() as conn:
        weight_rows = conn.execute(
            text(sql_weights),
            {
                "dept": standard_department_name,
                "limit_jobs": limit_units,
                "limit_units": limit_units,
            },
        ).mappings().all()
        if not weight_rows:
            return []

        score_by_unit = {
            str(row["unit_category_id"]): _score_to_float(row.get("mapping_score"))
            for row in weight_rows
            if row.get("unit_category_id")
        }
        unit_ids = sorted(score_by_unit.keys())
        meta_rows = conn.execute(
            text(sql_meta_bulk),
            {"unit_category_ids": unit_ids},
        ).mappings().all()

    recs: list[dict] = []
    for meta in meta_rows:
        unit_category_id = str(meta.get("unit_category_id") or "")
        if not unit_category_id:
            continue
        base_score = score_by_unit.get(unit_category_id, 0.75)
        affinity = _name_token_affinity(
            f"{meta['unit_name']} {meta['unit_element_name']}",
            [],
        )
        final_score = base_score * (0.6 + affinity * 0.4)
        recs.append(
            {
                "unit_category_id": meta["unit_category_id"],
                "unit_name": meta["unit_name"],
                "unit_element_id": meta["unit_element_id"],
                "unit_element_name": meta["unit_element_name"],
                "major_category_name": meta.get("major_category_name"),
                "middle_category_name": meta.get("middle_category_name"),
                "minor_category_name": meta.get("minor_category_name"),
                "subcategory_code": meta.get("subcategory_code"),
                "subcategory_name": meta.get("subcategory_name"),
                "keyword_score": base_score,
                "vector_score": 0.0,
                "final_score": final_score,
                "reason": f"부서 '{dept_synonym}' 매핑 기반 능력단위 추천",
            }
        )

    recs.sort(key=lambda item: _score_to_float(item.get("final_score")), reverse=True)
    return recs[:limit_units]


def _build_units_from_departments(
    department_names: list[str],
    label: str,
    top_k: int,
) -> list[dict]:
    """여러 부서(예: 품질 stem에 매칭된 부서들)의 능력단위를 합친다."""
    merged: dict[str, dict] = {}
    per_dept_limit = max(top_k, 8)
    for dept_name in department_names:
        for item in _build_units_from_department(dept_name, label, per_dept_limit):
            unit_category_id = str(item.get("unit_category_id") or "")
            if not unit_category_id:
                continue
            prev = merged.get(unit_category_id)
            if prev is None or _score_to_float(item.get("final_score")) > _score_to_float(prev.get("final_score")):
                merged[unit_category_id] = item

    out = sorted(merged.values(), key=lambda row: _score_to_float(row.get("final_score")), reverse=True)
    return out[: max(top_k * 3, 20)]


def _build_units_from_text_stem(stem: str, top_k: int) -> list[dict]:
    """
    T21에 부서가 없을 때 T25 텍스트에서 stem(예: 경영지원)이 포함된 능력단위를 찾는다.
    """
    if len(stem) < 2:
        return []

    limit = max(top_k * 3, 20)
    sql = """
    SELECT DISTINCT ON (unit_category_id)
        unit_category_id,
        unit_name,
        unit_element_id,
        unit_element_name,
        major_category_name,
        middle_category_name,
        minor_category_name,
        subcategory_code,
        subcategory_name
    FROM T25_NCS_SEARCH_INDEX
    WHERE lower(coalesce(unit_name, '')) LIKE '%%' || :stem || '%%'
       OR lower(coalesce(unit_element_name, '')) LIKE '%%' || :stem || '%%'
       OR lower(coalesce(subcategory_name, '')) LIKE '%%' || :stem || '%%'
       OR lower(coalesce(keyword_text, '')) LIKE '%%' || :stem || '%%'
       OR lower(coalesce(normalized_search_text, '')) LIKE '%%' || :stem || '%%'
    ORDER BY unit_category_id, search_index_id ASC
    LIMIT :limit
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql), {"stem": stem.lower(), "limit": limit}).mappings().all()

    recs: list[dict] = []
    for meta in rows:
        text_blob = " ".join(
            [
                str(meta.get("unit_name") or ""),
                str(meta.get("unit_element_name") or ""),
                str(meta.get("subcategory_name") or ""),
            ]
        ).lower()
        hit_score = 0.75 if stem.lower() in text_blob else 0.55
        recs.append(
            {
                "unit_category_id": meta["unit_category_id"],
                "unit_name": meta["unit_name"],
                "unit_element_id": meta["unit_element_id"],
                "unit_element_name": meta["unit_element_name"],
                "major_category_name": meta.get("major_category_name"),
                "middle_category_name": meta.get("middle_category_name"),
                "minor_category_name": meta.get("minor_category_name"),
                "subcategory_code": meta.get("subcategory_code"),
                "subcategory_name": meta.get("subcategory_name"),
                "keyword_score": hit_score,
                "vector_score": 0.0,
                "final_score": hit_score,
                "reason": f"부서 키워드 '{stem}' 텍스트 매칭 기반 능력단위 추천",
            }
        )
    recs.sort(key=lambda item: _score_to_float(item.get("final_score")), reverse=True)
    return recs[:limit]


def _name_token_affinity(name: str, content_tokens: list[str]) -> float:
    if not content_tokens:
        return 0.5
    lowered = name.lower()
    matched = 0
    for token in content_tokens:
        # 2글자 prefix 매칭은 오탐이 많아 전체 토큰 포함 매칭만 사용한다.
        if token in lowered:
            matched += 1
    return matched / len(content_tokens)


def _lookup_subcategory_by_unit_category(unit_category_id: str) -> dict | None:
    sql = """
    SELECT
        subcategory_code,
        subcategory_name,
        major_category_name,
        middle_category_name,
        minor_category_name
    FROM T25_NCS_SEARCH_INDEX
    WHERE unit_category_id = :unit_category_id
    ORDER BY search_index_id ASC
    LIMIT 1
    """
    with get_connection() as conn:
        row = conn.execute(text(sql), {"unit_category_id": unit_category_id}).mappings().first()
    return dict(row) if row else None


def _lookup_ncs_hierarchy_by_job_name(job_name: str) -> dict:
    sql_direct = """
    SELECT
        major_category_name,
        middle_category_name,
        minor_category_name,
        subcategory_code,
        subcategory_name
    FROM T25_NCS_SEARCH_INDEX
    WHERE unit_name = :job_name
    ORDER BY search_index_id ASC
    LIMIT 1
    """
    sql_mapped = """
    WITH mapped AS (
        SELECT unit_category_id, match_weight
        FROM T24_JOB_UNIT_MAPPING
        WHERE is_active = TRUE
          AND standard_job_name = :job_name
        ORDER BY match_weight DESC, mapping_id ASC
        LIMIT 1
    )
    SELECT
        t.major_category_name,
        t.middle_category_name,
        t.minor_category_name,
        t.subcategory_code,
        t.subcategory_name
    FROM mapped m
    JOIN T25_NCS_SEARCH_INDEX t
      ON t.unit_category_id = m.unit_category_id
    ORDER BY t.search_index_id ASC
    LIMIT 1
    """
    with get_connection() as conn:
        direct = conn.execute(text(sql_direct), {"job_name": job_name}).mappings().first()
        if direct:
            return dict(direct)
        mapped = conn.execute(text(sql_mapped), {"job_name": job_name}).mappings().first()
        if mapped:
            return dict(mapped)
    return {}


def _lookup_ncs_hierarchy_map_by_job_names(job_names: list[str]) -> dict[str, dict]:
    unique_names = sorted({name.strip() for name in job_names if name and name.strip()})
    if not unique_names:
        return {}

    sql_direct = """
    SELECT DISTINCT ON (t.unit_name)
        t.unit_name AS job_name,
        t.major_category_name,
        t.middle_category_name,
        t.minor_category_name,
        t.subcategory_code,
        t.subcategory_name
    FROM T25_NCS_SEARCH_INDEX t
    WHERE t.unit_name = ANY(:job_names)
    ORDER BY t.unit_name, t.search_index_id ASC
    """
    results: dict[str, dict] = {}
    with get_connection() as conn:
        direct_rows = conn.execute(text(sql_direct), {"job_names": unique_names}).mappings().all()
        for row in direct_rows:
            job_name = str(row.get("job_name") or "").strip()
            if not job_name:
                continue
            results[job_name] = {
                "major_category_name": row.get("major_category_name"),
                "middle_category_name": row.get("middle_category_name"),
                "minor_category_name": row.get("minor_category_name"),
                "subcategory_code": row.get("subcategory_code"),
                "subcategory_name": row.get("subcategory_name"),
            }

        missing_names = [name for name in unique_names if name not in results]
        if not missing_names:
            return results

        sql_mapped = """
        WITH candidate AS (
            SELECT DISTINCT ON (m.standard_job_name)
                m.standard_job_name AS job_name,
                m.unit_category_id
            FROM T24_JOB_UNIT_MAPPING m
            WHERE m.is_active = TRUE
              AND m.standard_job_name = ANY(:job_names)
            ORDER BY m.standard_job_name, m.match_weight DESC, m.mapping_id ASC
        )
        SELECT DISTINCT ON (c.job_name)
            c.job_name,
            t.major_category_name,
            t.middle_category_name,
            t.minor_category_name,
            t.subcategory_code,
            t.subcategory_name
        FROM candidate c
        JOIN T25_NCS_SEARCH_INDEX t
          ON t.unit_category_id = c.unit_category_id
        ORDER BY c.job_name, t.search_index_id ASC
        """
        mapped_rows = conn.execute(text(sql_mapped), {"job_names": missing_names}).mappings().all()
        for row in mapped_rows:
            job_name = str(row.get("job_name") or "").strip()
            if not job_name:
                continue
            results[job_name] = {
                "major_category_name": row.get("major_category_name"),
                "middle_category_name": row.get("middle_category_name"),
                "minor_category_name": row.get("minor_category_name"),
                "subcategory_code": row.get("subcategory_code"),
                "subcategory_name": row.get("subcategory_name"),
            }
    return results


def _deduplicate_units_by_category(units: list[dict], top_k: int) -> list[dict]:
    """
    능력단위 탭은 '능력단위(unit_category_id)' 기준으로 보여주는 것이 자연스럽다.
    동일 능력단위의 여러 요소(unit_element_id)가 섞여 들어오면 사용자에게 중복으로 보이므로
    unit_category_id 단위로 대표 1건만 남긴다.
    """
    best_by_unit: dict[str, dict] = {}
    for item in units:
        unit_category_id = str(item.get("unit_category_id") or "")
        if not unit_category_id:
            continue
        current = best_by_unit.get(unit_category_id)
        if current is None:
            best_by_unit[unit_category_id] = item
            continue

        current_score = _score_to_float(current.get("final_score"))
        new_score = _score_to_float(item.get("final_score"))
        if new_score > current_score:
            best_by_unit[unit_category_id] = item
            continue
        if new_score == current_score:
            # 동점이면 unit_element_id가 작은(대표성이 높은) 항목을 우선 채택한다.
            current_el = str(current.get("unit_element_id") or "")
            new_el = str(item.get("unit_element_id") or "")
            if new_el and (not current_el or new_el < current_el):
                best_by_unit[unit_category_id] = item

    deduped = sorted(
        best_by_unit.values(),
        key=lambda row: _score_to_float(row.get("final_score")),
        reverse=True,
    )
    return deduped[:top_k]


def _derive_subcategories_from_units(units: list[dict], keywords: list[str], top_k: int) -> list[dict]:
    by_code: dict[str, dict] = {}
    for unit in units:
        code = str(unit.get("subcategory_code") or "")
        if not code:
            continue
        score = _score_to_float(unit.get("final_score"))
        existing = by_code.get(code)
        if existing is None:
            by_code[code] = {
                "subcategory_code": code,
                "subcategory_name": unit.get("subcategory_name"),
                "major_category_name": unit.get("major_category_name"),
                "middle_category_name": unit.get("middle_category_name"),
                "minor_category_name": unit.get("minor_category_name"),
                "keyword_score": score,
                "vector_score": 0.0,
                "final_score": score,
                "matched_keywords": keywords,
                "reason": "능력단위 추천 결과 기반 세분류 보강",
            }
            continue
        existing["keyword_score"] = max(_score_to_float(existing.get("keyword_score")), score)
        existing["final_score"] = max(_score_to_float(existing.get("final_score")), score)

    return sorted(by_code.values(), key=lambda row: _score_to_float(row.get("final_score")), reverse=True)[:top_k]


def _derive_jobs_from_units(units: list[dict], top_k: int) -> list[dict]:
    by_name: dict[str, dict] = {}
    for unit in units:
        job_name = str(unit.get("unit_name") or "").strip()
        if not job_name:
            continue
        score = _score_to_float(unit.get("final_score"))
        existing = by_name.get(job_name)
        if existing is None:
            by_name[job_name] = {
                "job_name": job_name,
                "major_category_name": unit.get("major_category_name"),
                "middle_category_name": unit.get("middle_category_name"),
                "minor_category_name": unit.get("minor_category_name"),
                "subcategory_code": unit.get("subcategory_code"),
                "subcategory_name": unit.get("subcategory_name"),
                "keyword_score": score,
                "vector_score": 0.0,
                "final_score": score,
                "reason": "능력단위 검색 결과를 직무 후보로 직접 반영",
            }
            continue
        existing["keyword_score"] = max(_score_to_float(existing.get("keyword_score")), score)
        existing["final_score"] = max(_score_to_float(existing.get("final_score")), score)

    return sorted(by_name.values(), key=lambda row: _score_to_float(row.get("final_score")), reverse=True)[:top_k]


def _department_preferred_sets(standard_department_name: str, top_k: int = 30) -> tuple[set[str], set[str], set[str]]:
    """
    부서가 명확할 때 해당 부서와 강하게 연결된 직무/능력단위/세분류 코드를 반환한다.
    """
    sql = """
    WITH preferred_jobs AS (
        SELECT standard_job_name
        FROM T23_DEPARTMENT_JOB_MAPPING
        WHERE is_active = TRUE
          AND standard_department_name = :dept
        ORDER BY match_weight DESC, mapping_id ASC
        LIMIT :top_k
    ),
    preferred_units AS (
        SELECT m.standard_job_name, m.unit_category_id
        FROM T24_JOB_UNIT_MAPPING m
        JOIN preferred_jobs j
          ON j.standard_job_name = m.standard_job_name
        WHERE m.is_active = TRUE
    ),
    unit_subcategories AS (
        SELECT DISTINCT ON (t.unit_category_id)
            t.unit_category_id,
            t.subcategory_code
        FROM T25_NCS_SEARCH_INDEX t
        JOIN preferred_units u
          ON u.unit_category_id = t.unit_category_id
        ORDER BY t.unit_category_id, t.search_index_id ASC
    )
    SELECT
        u.standard_job_name,
        u.unit_category_id,
        us.subcategory_code
    FROM preferred_units u
    LEFT JOIN unit_subcategories us
      ON us.unit_category_id = u.unit_category_id
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql), {"dept": standard_department_name, "top_k": top_k}).mappings().all()

    preferred_jobs = {str(row.get("standard_job_name") or "") for row in rows if row.get("standard_job_name")}
    preferred_unit_ids = {str(row.get("unit_category_id") or "") for row in rows if row.get("unit_category_id")}
    preferred_subcategory_codes = {str(row.get("subcategory_code") or "") for row in rows if row.get("subcategory_code")}
    return preferred_jobs, preferred_unit_ids, preferred_subcategory_codes


def _batch_job_query_relevance(job_names: list[str], content_tokens: list[str]) -> dict[str, float]:
    """
    각 직무명에 대해 단건 `_job_query_relevance`와 동일한 근거 점수를, DB 왕복을 최소화해 계산한다.
    """
    uniq_names = sorted({str(name).strip() for name in job_names if str(name).strip()})
    if not uniq_names:
        return {}

    if not content_tokens:
        return {name: 0.5 for name in uniq_names}

    token_values = sorted({token.strip() for token in content_tokens if token and token.strip()})
    if not token_values:
        return {name: 0.0 for name in uniq_names}

    sql_mapped = """
    WITH token_table AS (
        SELECT
            token,
            replace(token, ' ', '') AS token_nospace
        FROM unnest(cast(:tokens as text[])) AS token
    ),
    mapped AS (
        SELECT m.standard_job_name AS job_name, m.unit_category_id
        FROM T24_JOB_UNIT_MAPPING m
        WHERE m.is_active = TRUE
          AND m.standard_job_name = ANY(:job_names)
    ),
    stats AS (
        SELECT
            m.job_name,
            tt.token,
            count(*) AS total_rows,
            sum(
                CASE
                    WHEN lower(coalesce(t.unit_name, '')) LIKE '%%' || tt.token || '%%'
                      OR lower(coalesce(t.unit_element_name, '')) LIKE '%%' || tt.token || '%%'
                      OR lower(coalesce(t.keyword_text, '')) LIKE '%%' || tt.token || '%%'
                      OR lower(coalesce(t.performance_criteria_text, '')) LIKE '%%' || tt.token || '%%'
                      OR replace(lower(coalesce(t.unit_name, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
                      OR replace(lower(coalesce(t.unit_element_name, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
                      OR replace(lower(coalesce(t.keyword_text, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
                      OR replace(lower(coalesce(t.performance_criteria_text, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
                    THEN 1 ELSE 0
                END
            ) AS hit_rows
        FROM mapped m
        CROSS JOIN token_table tt
        JOIN T25_NCS_SEARCH_INDEX t
          ON t.unit_category_id = m.unit_category_id
        GROUP BY m.job_name, tt.token
    )
    SELECT
        job_name,
        avg(LEAST(1.0, hit_rows::float / NULLIF(total_rows, 0))) AS relevance,
        count(*)::int AS checked_tokens
    FROM stats
    WHERE total_rows > 0
    GROUP BY job_name
    """
    sql_direct = """
    WITH token_table AS (
        SELECT
            token,
            replace(token, ' ', '') AS token_nospace
        FROM unnest(cast(:tokens as text[])) AS token
    ),
    stats AS (
        SELECT
            j.job_name AS job_name,
            tt.token,
            count(*) AS total_rows,
            sum(
                CASE
                    WHEN lower(coalesce(t.unit_name, '')) LIKE '%%' || tt.token || '%%'
                      OR lower(coalesce(t.unit_element_name, '')) LIKE '%%' || tt.token || '%%'
                      OR lower(coalesce(t.keyword_text, '')) LIKE '%%' || tt.token || '%%'
                      OR lower(coalesce(t.performance_criteria_text, '')) LIKE '%%' || tt.token || '%%'
                      OR replace(lower(coalesce(t.unit_name, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
                      OR replace(lower(coalesce(t.unit_element_name, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
                      OR replace(lower(coalesce(t.keyword_text, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
                      OR replace(lower(coalesce(t.performance_criteria_text, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
                    THEN 1 ELSE 0
                END
            ) AS hit_rows
        FROM unnest(cast(:job_names as text[])) AS j(job_name)
        CROSS JOIN token_table tt
        JOIN T25_NCS_SEARCH_INDEX t
          ON t.unit_name = j.job_name
        GROUP BY j.job_name, tt.token
    )
    SELECT
        job_name,
        avg(LEAST(1.0, hit_rows::float / NULLIF(total_rows, 0))) AS relevance,
        count(*)::int AS checked_tokens
    FROM stats
    WHERE total_rows > 0
    GROUP BY job_name
    """
    out: dict[str, float] = {}
    mapped_ok: set[str] = set()
    with get_connection() as conn:
        mapped_rows = conn.execute(
            text(sql_mapped),
            {"job_names": uniq_names, "tokens": token_values},
        ).mappings().all()
        for row in mapped_rows:
            name = str(row.get("job_name") or "").strip()
            cnt = int(row.get("checked_tokens") or 0)
            if name and cnt > 0:
                out[name] = _score_to_float(row.get("relevance"))
                mapped_ok.add(name)

        need_direct = [n for n in uniq_names if n not in mapped_ok]
        if need_direct:
            direct_rows = conn.execute(
                text(sql_direct),
                {"job_names": need_direct, "tokens": token_values},
            ).mappings().all()
            for row in direct_rows:
                name = str(row.get("job_name") or "").strip()
                cnt = int(row.get("checked_tokens") or 0)
                if name and cnt > 0:
                    out.setdefault(name, _score_to_float(row.get("relevance")))

    return {name: out.get(name, 0.0) for name in uniq_names}


def _job_query_relevance(job_name: str, content_tokens: list[str]) -> float:
    """
    직무명이 질의 의도와 실제로 맞는지(T24->T25 근거) 점수화한다.
    """
    if not content_tokens:
        return 0.5
    scored = _batch_job_query_relevance([job_name], content_tokens)
    return float(scored.get(str(job_name).strip(), 0.0))


def _bulk_lookup_subcategory_by_unit_category_ids(unit_category_ids: list[str]) -> dict[str, dict]:
    ids = sorted({uid for uid in unit_category_ids if uid})
    if not ids:
        return {}
    sql = """
    SELECT DISTINCT ON (unit_category_id)
        unit_category_id,
        subcategory_code,
        subcategory_name,
        major_category_name,
        middle_category_name,
        minor_category_name
    FROM T25_NCS_SEARCH_INDEX
    WHERE unit_category_id = ANY(:unit_category_ids)
    ORDER BY unit_category_id, search_index_id ASC
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql), {"unit_category_ids": ids}).mappings().all()
    return {str(row["unit_category_id"]): dict(row) for row in rows if row.get("unit_category_id")}


def _merge_subcategory_with_unit_signals(
    subcategories: list[dict],
    units: list[dict],
    keywords: list[str],
    top_k: int,
) -> list[dict]:
    """
    능력단위 추천 결과를 세분류 랭킹에 반영해 full 응답의 일관성을 높인다.
    """
    merged = [dict(item) for item in subcategories]
    for item in merged:
        item["_unit_signal_score"] = 0.0

    index_by_code = {
        str(item.get("subcategory_code")): idx
        for idx, item in enumerate(merged)
        if item.get("subcategory_code")
    }

    bulk_sub = _bulk_lookup_subcategory_by_unit_category_ids(
        [str(unit.get("unit_category_id") or "") for unit in units],
    )

    for rank, unit in enumerate(units, start=1):
        unit_category_id = str(unit.get("unit_category_id") or "")
        if not unit_category_id:
            continue

        sub = bulk_sub.get(unit_category_id)
        if not sub:
            continue

        subcategory_code = str(sub["subcategory_code"])
        # 상위 능력단위일수록 세분류 신호를 강하게 반영한다.
        rank_weight = 1.0 / rank
        signal_boost = _score_to_float(unit.get("final_score")) * rank_weight
        if subcategory_code in index_by_code:
            rec = merged[index_by_code[subcategory_code]]
            rec["_unit_signal_score"] = max(_score_to_float(rec.get("_unit_signal_score")), signal_boost)
            rec["final_score"] = _score_to_float(rec.get("final_score")) + (signal_boost * 0.25)
            rec["reason"] = f"{rec.get('reason', '')} + 능력단위 매핑 신호 반영".strip()
            continue

        merged.append(
            {
                "subcategory_code": subcategory_code,
                "subcategory_name": str(sub["subcategory_name"]),
                "major_category_name": sub.get("major_category_name"),
                "middle_category_name": sub.get("middle_category_name"),
                "minor_category_name": sub.get("minor_category_name"),
                "keyword_score": 0.0,
                "vector_score": 0.0,
                "final_score": signal_boost * 0.25,
                "_unit_signal_score": signal_boost,
                "matched_keywords": keywords,
                "reason": "능력단위 추천 결과 기반 세분류 보강",
            }
        )
        index_by_code[subcategory_code] = len(merged) - 1

    # 우선순위 규칙:
    # 1) 능력단위 코드로 추론된 세분류 신호 점수
    # 2) 기존 텍스트/FTS 기반 점수
    merged.sort(
        key=lambda item: (
            _score_to_float(item.get("_unit_signal_score")),
            _score_to_float(item.get("final_score")),
        ),
        reverse=True,
    )
    out = []
    seen_codes: set[str] = set()
    for item in merged:
        code = str(item.get("subcategory_code") or "")
        if code and code in seen_codes:
            continue
        if code:
            seen_codes.add(code)
        cleaned = dict(item)
        cleaned.pop("_unit_signal_score", None)
        out.append(cleaned)
        if len(out) >= top_k:
            break
    return out


def search_subcategories(query: str, top_k: int, precomputed_units: list[dict] | None = None) -> dict:
    normalized = normalize_query(query)
    query_variants = build_query_variants(normalized)
    match_query = query_variants[1] if len(query_variants) > 1 else normalized
    keywords = extract_keywords(normalized)
    keyword_str = " ".join(keywords)
    payroll_intent = _is_payroll_intent(normalized, keywords)
    dept = detect_department(normalized)
    dept_synonym = str((dept or {}).get("synonym_name") or "")
    dept_tokens = _department_text_tokens(dept)
    content_tokens = _extract_content_tokens(keywords, dept_synonym)
    preferred_subcategory_codes: set[str] = set()
    if dept:
        _, _, preferred_subcategory_codes = _department_preferred_sets(
            str(dept["standard_department_name"]),
            top_k=max(top_k * 3, 20),
        )
    unit_signal_units = (
        precomputed_units
        if precomputed_units is not None
        else search_units(query=query, top_k=max(top_k, 5))["recommended_units"]
    )

    # 성능 우선 경로: 능력단위 결과에서 세분류를 바로 파생한다.
    # 품질은 full 엔드포인트와 동일한 신호를 쓰므로 탭 간 일관성도 유지된다.
    if unit_signal_units:
        fast_recs = _derive_subcategories_from_units(
            units=unit_signal_units,
            keywords=keywords,
            top_k=max(top_k * 2, top_k),
        )
        adjusted_fast = []
        for row in fast_recs:
            context_text = " ".join(
                [
                    str(row.get("subcategory_name") or ""),
                    str(row.get("major_category_name") or ""),
                    str(row.get("middle_category_name") or ""),
                    str(row.get("minor_category_name") or ""),
                ]
            )
            adjusted = dict(row)
            adjusted["final_score"] = _score_to_float(adjusted.get("final_score")) * _payroll_domain_penalty(
                context_text, payroll_intent
            )
            adjusted["final_score"] = _score_to_float(adjusted.get("final_score")) * _department_affinity_multiplier(
                context_text, dept_tokens
            )
            if str(adjusted.get("subcategory_code") or "") in preferred_subcategory_codes:
                adjusted["final_score"] = _score_to_float(adjusted.get("final_score")) + 0.35
            adjusted_fast.append(adjusted)
        adjusted_fast.sort(key=lambda item: _score_to_float(item.get("final_score")), reverse=True)
        return {
            "query": query,
            "normalized_query": normalized,
            "recommended_subcategories": adjusted_fast[:top_k],
            "_matched_keywords_str": keyword_str,
        }

    sql = """
    WITH q AS (
        SELECT
            websearch_to_tsquery('simple', :query) AS q_web,
            plainto_tsquery('simple', :query) AS q_plain
    ),
    scored AS (
        SELECT
            subcategory_code,
            subcategory_name,
            major_category_name,
            middle_category_name,
            minor_category_name,
            (
                CASE WHEN lower(coalesce(subcategory_name, '')) LIKE '%%' || :query || '%%' THEN 0.5 ELSE 0 END
              + CASE WHEN lower(coalesce(subcategory_keyword_text, '')) LIKE '%%' || :query || '%%' THEN 0.5 ELSE 0 END
            ) AS keyword_score,
            GREATEST(
                ts_rank(search_vector, q.q_web),
                ts_rank(search_vector, q.q_plain)
            ) AS fts_score
        FROM T25_NCS_SEARCH_INDEX
        CROSS JOIN q
    )
    SELECT
        subcategory_code,
        subcategory_name,
        max(major_category_name) AS major_category_name,
        max(middle_category_name) AS middle_category_name,
        max(minor_category_name) AS minor_category_name,
        max(keyword_score) AS keyword_score,
        max(fts_score) AS fts_score
    FROM scored
    WHERE keyword_score > 0 OR fts_score > 0
    GROUP BY subcategory_code, subcategory_name
    ORDER BY (max(keyword_score) + max(fts_score)) DESC, subcategory_code
    LIMIT :top_k
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql), {"query": match_query, "top_k": top_k}).mappings().all()

    recs = []
    for row in rows:
        keyword_score = _score_to_float(row.get("keyword_score"))
        vector_score = 0.0
        base_score = max(keyword_score, _score_to_float(row.get("fts_score")))
        affinity = _name_token_affinity(
            f"{row['subcategory_name']} "
            f"{row.get('major_category_name') or ''} "
            f"{row.get('middle_category_name') or ''} "
            f"{row.get('minor_category_name') or ''}",
            content_tokens,
        )
        # 세분류명 계층과 무관한 FTS 단독 매칭은 점수를 낮춰 오탐 노출을 줄인다.
        if keyword_score <= 0 and affinity <= 0:
            final_score = base_score * 0.3
        else:
            final_score = base_score * (0.6 + affinity * 0.4)
        context_text = " ".join(
            [
                str(row.get("subcategory_name") or ""),
                str(row.get("major_category_name") or ""),
                str(row.get("middle_category_name") or ""),
                str(row.get("minor_category_name") or ""),
            ]
        )
        final_score *= _payroll_domain_penalty(context_text, payroll_intent)
        final_score *= _department_affinity_multiplier(context_text, dept_tokens)
        if str(row.get("subcategory_code") or "") in preferred_subcategory_codes:
            final_score += 0.35
        recs.append(
            {
                "subcategory_code": row["subcategory_code"],
                "subcategory_name": row["subcategory_name"],
                "major_category_name": row.get("major_category_name"),
                "middle_category_name": row.get("middle_category_name"),
                "minor_category_name": row.get("minor_category_name"),
                "keyword_score": keyword_score,
                "vector_score": vector_score,
                "final_score": final_score,
                "matched_keywords": keywords,
                "reason": "세분류명/세분류 키워드 및 FTS 매칭",
            }
        )

    # 0점대(실질 매칭 없음) 후보는 제거해 fallback 토큰 검색으로 넘어가게 한다.
    recs = [item for item in recs if _score_to_float(item.get("final_score")) > 0.01]

    recs.sort(key=lambda item: _score_to_float(item.get("final_score")), reverse=True)

    # subcategory 단독 검색도 full 검색과 일관되게 능력단위 신호를 반영한다.
    recs = _merge_subcategory_with_unit_signals(
        subcategories=recs,
        units=unit_signal_units,
        keywords=keywords,
        top_k=top_k,
    )

    return {
        "query": query,
        "normalized_query": normalized,
        "recommended_subcategories": recs,
        "_matched_keywords_str": keyword_str,
    }


def search_jobs(query: str, top_k: int, precomputed_units: list[dict] | None = None) -> dict:
    normalized = normalize_query(query)
    query_variants = build_query_variants(normalized)
    match_query = query_variants[1] if len(query_variants) > 1 else normalized
    normalized_nospace = match_query.replace(" ", "")
    keywords = extract_keywords(normalized)
    payroll_intent = _is_payroll_intent(normalized, keywords)

    direct_job = detect_job(normalized)
    dept = detect_department(normalized)
    dept_synonym = str((dept or {}).get("synonym_name") or "")
    dept_tokens = _department_text_tokens(dept)
    content_tokens = _extract_content_tokens(keywords, dept_synonym)
    preferred_jobs: set[str] = set()
    if dept:
        preferred_jobs, _, _ = _department_preferred_sets(
            str(dept["standard_department_name"]),
            top_k=max(top_k * 3, 20),
        )

    candidate_map: dict[str, dict] = {}

    def _put_candidate(job_name: str, score: float, reason: str) -> None:
        existing = candidate_map.get(job_name)
        if existing is None or score > _score_to_float(existing.get("final_score")):
            candidate_map[job_name] = {
                "job_name": job_name,
                "keyword_score": score,
                "vector_score": 0.0,
                "final_score": score,
                "reason": reason,
            }

    if direct_job:
        job_name = str(direct_job["standard_job_name"])
        synonym = str(direct_job.get("synonym_name") or "")
        # 문장 내 토큰 대비 동의어가 포괄하는 비율로 사전 점수를 보정한다.
        matched_tokens = sum(1 for token in keywords if synonym and (synonym in token or token in synonym))
        coverage = (matched_tokens / len(keywords)) if keywords else 1.0
        direct_score = 0.55 + (0.45 * coverage)
        direct_score *= 0.7 + (_name_token_affinity(job_name, content_tokens) * 0.3)
        _put_candidate(
            job_name=job_name,
            score=direct_score,
            reason=f"직무 동의어 '{synonym}' 매칭",
        )

    if dept:
        for mapped in map_department_to_jobs(str(dept["standard_department_name"]), top_k=top_k):
            job_name = str(mapped["standard_job_name"])
            score = _score_to_float(mapped.get("match_weight"))
            # 부서 매핑 점수는 문맥 반영 후보와 공존하도록 완만하게 반영한다.
            affinity = _name_token_affinity(job_name, content_tokens)
            _put_candidate(
                job_name=job_name,
                score=score * 0.75 * (0.55 + affinity * 0.45),
                reason=f"부서 '{dept['synonym_name']}' 기반 직무 매핑",
            )

    # 능력단위 검색 결과를 T24로 역매핑해 직무 후보를 보강한다(항상 실행).
    unit_candidates = (
        precomputed_units
        if precomputed_units is not None
        else search_units(query=query, top_k=max(top_k * 2, 8))["recommended_units"]
    )
    if unit_candidates:
        sql = """
        SELECT
            unit_category_id,
            standard_job_name,
            match_weight
        FROM (
            SELECT
                unit_category_id,
                standard_job_name,
                match_weight,
                ROW_NUMBER() OVER (
                    PARTITION BY unit_category_id
                    ORDER BY match_weight DESC, mapping_id ASC
                ) AS rn
            FROM T24_JOB_UNIT_MAPPING
            WHERE is_active = TRUE
              AND unit_category_id = ANY(:unit_category_ids)
        ) ranked
        WHERE rn <= 3
        ORDER BY unit_category_id, match_weight DESC
        """
        unit_ids = sorted({str(unit.get("unit_category_id") or "") for unit in unit_candidates if unit.get("unit_category_id")})
        mapped_by_unit: dict[str, list[dict]] = {}
        with get_connection() as conn:
            if unit_ids:
                mapped_rows = conn.execute(
                    text(sql),
                    {"unit_category_ids": unit_ids},
                ).mappings().all()
                for mapped in mapped_rows:
                    key = str(mapped.get("unit_category_id") or "")
                    if not key:
                        continue
                    mapped_by_unit.setdefault(key, []).append(dict(mapped))

        for unit in unit_candidates:
            unit_score = _score_to_float(unit.get("final_score"))
            unit_category_id = str(unit.get("unit_category_id") or "")
            if not unit_category_id:
                continue
            mapped_rows = mapped_by_unit.get(unit_category_id, [])
            if not mapped_rows:
                # T24 매핑이 비어 있으면 능력단위명을 직무 후보로 직접 반영한다.
                direct_job_name = str(unit.get("unit_name") or "")
                if direct_job_name:
                    affinity = _name_token_affinity(direct_job_name, content_tokens)
                    direct_score = unit_score * (0.7 + affinity * 0.3)
                    _put_candidate(
                        job_name=direct_job_name,
                        score=direct_score,
                        reason="능력단위 검색 결과를 직무 후보로 직접 반영",
                    )
                continue
            for mapped in mapped_rows:
                job_name = str(mapped["standard_job_name"])
                mapping_weight = _score_to_float(mapped.get("match_weight"))
                combined = max(unit_score * 0.7 + mapping_weight * 0.3, mapping_weight * 0.5)
                affinity = _name_token_affinity(job_name, content_tokens)
                combined *= 0.55 + affinity * 0.45
                _put_candidate(
                    job_name=job_name,
                    score=combined,
                    reason="능력단위 검색 결과를 직무-능력단위 매핑(T24)으로 역추론",
                )

    # T25 텍스트(키워드+수행준거) 기반 직무(능력단위명) 추론도 항상 병합한다.
    tokens = [token for token in keywords if len(token) >= 2]
    if not tokens and normalized:
        tokens = [normalized]

    sql_job_tokens_bulk = """
    WITH token_table AS (
        SELECT
            ord AS token_ord,
            token,
            replace(token, ' ', '') AS token_nospace
        FROM unnest(cast(:tokens as text[])) WITH ORDINALITY AS t(token, ord)
    ),
    hits AS (
        SELECT
            tt.token_ord,
            tt.token,
            t.unit_name,
            sum(
                CASE
                    WHEN lower(coalesce(t.unit_name, '')) LIKE '%%' || tt.token || '%%'
                      OR lower(coalesce(t.unit_element_name, '')) LIKE '%%' || tt.token || '%%'
                      OR lower(coalesce(t.subcategory_name, '')) LIKE '%%' || tt.token || '%%'
                      OR lower(coalesce(t.keyword_text, '')) LIKE '%%' || tt.token || '%%'
                      OR replace(lower(coalesce(t.unit_name, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
                      OR replace(lower(coalesce(t.unit_element_name, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
                      OR replace(lower(coalesce(t.subcategory_name, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
                      OR replace(lower(coalesce(t.keyword_text, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
                    THEN 1 ELSE 0
                END
            ) AS direct_hit_count,
            sum(
                CASE
                    WHEN lower(coalesce(t.performance_criteria_text, '')) LIKE '%%' || tt.token || '%%'
                      OR replace(lower(coalesce(t.performance_criteria_text, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
                    THEN 1 ELSE 0
                END
            ) AS criteria_hit_count
        FROM token_table tt
        INNER JOIN T25_NCS_SEARCH_INDEX t ON (
            lower(coalesce(t.unit_name, '')) LIKE '%%' || tt.token || '%%'
            OR lower(coalesce(t.unit_element_name, '')) LIKE '%%' || tt.token || '%%'
            OR lower(coalesce(t.subcategory_name, '')) LIKE '%%' || tt.token || '%%'
            OR lower(coalesce(t.keyword_text, '')) LIKE '%%' || tt.token || '%%'
            OR lower(coalesce(t.performance_criteria_text, '')) LIKE '%%' || tt.token || '%%'
            OR replace(lower(coalesce(t.unit_name, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
            OR replace(lower(coalesce(t.unit_element_name, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
            OR replace(lower(coalesce(t.subcategory_name, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
            OR replace(lower(coalesce(t.keyword_text, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
            OR replace(lower(coalesce(t.performance_criteria_text, '')), ' ', '') LIKE '%%' || tt.token_nospace || '%%'
        )
        GROUP BY tt.token_ord, tt.token, t.unit_name
    ),
    ranked AS (
        SELECT
            h.*,
            ROW_NUMBER() OVER (
                PARTITION BY h.token_ord
                ORDER BY h.direct_hit_count DESC, h.criteria_hit_count DESC, h.unit_name
            ) AS rn
        FROM hits h
    )
    SELECT
        token_ord,
        token,
        unit_name,
        direct_hit_count,
        criteria_hit_count
    FROM ranked
    WHERE rn <= 10
    ORDER BY token_ord, rn
    """
    rows_by_ord: dict[int, list] = defaultdict(list)
    with get_connection() as conn:
        bulk_rows = conn.execute(text(sql_job_tokens_bulk), {"tokens": tokens}).mappings().all()
        for row in bulk_rows:
            rows_by_ord[int(row["token_ord"])].append(row)

    for ti, _tok in enumerate(tokens):
        for row in rows_by_ord.get(ti + 1, []):
            job_name = str(row["unit_name"])
            direct_hit = _score_to_float(row.get("direct_hit_count"))
            criteria_hit = _score_to_float(row.get("criteria_hit_count"))
            affinity = _name_token_affinity(job_name, content_tokens)
            if direct_hit <= 0 and affinity < 0.2:
                continue
            weighted_hit = direct_hit + (criteria_hit * 0.25)
            base_score = min(1.0, weighted_hit / 10.0)
            score = min(1.0, affinity * 0.8 + base_score * 0.2)
            _put_candidate(
                job_name=job_name,
                score=score,
                reason="T25 키워드+수행준거 매칭 기반 직무(능력단위명) 추정",
            )

    job_hierarchy_map = _lookup_ncs_hierarchy_map_by_job_names(list(candidate_map.keys()))
    job_relevance_map = _batch_job_query_relevance(list(candidate_map.keys()), content_tokens)

    ranked_jobs = sorted(
        (
            {
                **item,
                "major_category_name": job_hierarchy_map.get(str(item.get("job_name") or ""), {}).get("major_category_name"),
                "middle_category_name": job_hierarchy_map.get(str(item.get("job_name") or ""), {}).get("middle_category_name"),
                "minor_category_name": job_hierarchy_map.get(str(item.get("job_name") or ""), {}).get("minor_category_name"),
                "subcategory_code": job_hierarchy_map.get(str(item.get("job_name") or ""), {}).get("subcategory_code"),
                "subcategory_name": job_hierarchy_map.get(str(item.get("job_name") or ""), {}).get("subcategory_name"),
                "final_score": (
                    _score_to_float(item.get("final_score")) * 0.35
                    + _score_to_float(job_relevance_map.get(str(item.get("job_name") or ""), 0.0)) * 0.65
                ),
                "keyword_score": (
                    _score_to_float(item.get("final_score")) * 0.35
                    + _score_to_float(job_relevance_map.get(str(item.get("job_name") or ""), 0.0)) * 0.65
                ),
                "reason": f"{item.get('reason', '')} + 직무-능력단위 근거 반영".strip(),
            }
            for item in candidate_map.values()
        ),
        key=lambda item: _score_to_float(item.get("final_score")),
        reverse=True,
    )
    adjusted_jobs = []
    for item in ranked_jobs:
        context_text = " ".join(
            [
                str(item.get("job_name") or ""),
                str(item.get("major_category_name") or ""),
                str(item.get("middle_category_name") or ""),
                str(item.get("minor_category_name") or ""),
                str(item.get("subcategory_name") or ""),
            ]
        )
        penalty = _payroll_domain_penalty(context_text, payroll_intent)
        adjusted = dict(item)
        adjusted["final_score"] = _score_to_float(item.get("final_score")) * penalty
        adjusted["keyword_score"] = _score_to_float(item.get("keyword_score")) * penalty
        dept_mult = _department_affinity_multiplier(context_text, dept_tokens)
        task_mult = _task_focus_multiplier(str(item.get("job_name") or ""), content_tokens)
        adjusted["final_score"] = _score_to_float(adjusted.get("final_score")) * dept_mult
        adjusted["keyword_score"] = _score_to_float(adjusted.get("keyword_score")) * dept_mult
        adjusted["final_score"] = _score_to_float(adjusted.get("final_score")) * task_mult
        adjusted["keyword_score"] = _score_to_float(adjusted.get("keyword_score")) * task_mult
        if str(item.get("job_name") or "") in preferred_jobs and task_mult >= 0.75:
            adjusted["final_score"] = _score_to_float(adjusted.get("final_score")) + 0.25
            adjusted["keyword_score"] = _score_to_float(adjusted.get("keyword_score")) + 0.25
        adjusted_jobs.append(adjusted)

    ranked_jobs = [
        item
        for item in sorted(adjusted_jobs, key=lambda row: _score_to_float(row.get("final_score")), reverse=True)
        if _score_to_float(item.get("final_score")) >= MIN_JOB_SCORE
    ]

    return {
        "query": query,
        "normalized_query": normalized,
        "recommended_jobs": ranked_jobs[:top_k],
        "_matched_keywords_str": " ".join(keywords) or normalized_nospace,
    }


def search_units(query: str, top_k: int) -> dict:
    normalized = normalize_query(query)
    query_variants = build_query_variants(normalized)
    match_query = query_variants[1] if len(query_variants) > 1 else normalized
    normalized_nospace = match_query.replace(" ", "")
    keywords = extract_keywords(normalized)
    payroll_intent = _is_payroll_intent(normalized, keywords)
    dept = detect_department(normalized)
    dept_synonym = str((dept or {}).get("synonym_name") or "")
    dept_tokens = _department_text_tokens(dept)
    content_tokens = _extract_content_tokens(keywords, dept_synonym)
    preferred_unit_ids: set[str] = set()
    preferred_subcategory_codes: set[str] = set()
    if dept:
        _, preferred_unit_ids, preferred_subcategory_codes = _department_preferred_sets(
            str(dept["standard_department_name"]),
            top_k=max(top_k * 3, 20),
        )

    sql = """
    WITH q AS (
        SELECT
            websearch_to_tsquery('simple', :query) AS q_web,
            plainto_tsquery('simple', :query) AS q_plain
    ),
    scored AS (
        SELECT
            unit_category_id,
            unit_name,
            unit_element_id,
            unit_element_name,
            major_category_name,
            middle_category_name,
            minor_category_name,
            subcategory_code,
            subcategory_name,
            (
                CASE WHEN lower(coalesce(unit_name, '')) LIKE '%%' || :query || '%%' THEN 0.35 ELSE 0 END
              + CASE WHEN lower(coalesce(unit_element_name, '')) LIKE '%%' || :query || '%%' THEN 0.35 ELSE 0 END
              + CASE WHEN lower(coalesce(minor_category_name, '')) LIKE '%%' || :query || '%%' THEN 0.45 ELSE 0 END
              + CASE WHEN lower(coalesce(subcategory_name, '')) LIKE '%%' || :query || '%%' THEN 0.30 ELSE 0 END
              + CASE WHEN lower(coalesce(keyword_text, '')) LIKE '%%' || :query || '%%' THEN 0.20 ELSE 0 END
              + CASE WHEN lower(coalesce(performance_criteria_text, '')) LIKE '%%' || :query || '%%' THEN 0.10 ELSE 0 END
              + CASE WHEN replace(lower(coalesce(unit_name, '')), ' ', '') LIKE '%%' || :query_nospace || '%%' THEN 0.15 ELSE 0 END
              + CASE WHEN replace(lower(coalesce(unit_element_name, '')), ' ', '') LIKE '%%' || :query_nospace || '%%' THEN 0.15 ELSE 0 END
              + CASE WHEN replace(lower(coalesce(minor_category_name, '')), ' ', '') LIKE '%%' || :query_nospace || '%%' THEN 0.20 ELSE 0 END
              + CASE WHEN replace(lower(coalesce(subcategory_name, '')), ' ', '') LIKE '%%' || :query_nospace || '%%' THEN 0.15 ELSE 0 END
              + CASE WHEN replace(lower(coalesce(keyword_text, '')), ' ', '') LIKE '%%' || :query_nospace || '%%' THEN 0.10 ELSE 0 END
              + CASE WHEN replace(lower(coalesce(performance_criteria_text, '')), ' ', '') LIKE '%%' || :query_nospace || '%%' THEN 0.10 ELSE 0 END
            ) AS keyword_score,
            GREATEST(
                ts_rank(search_vector, q.q_web),
                ts_rank(search_vector, q.q_plain)
            ) AS fts_score,
            search_index_id
        FROM T25_NCS_SEARCH_INDEX
        CROSS JOIN q
        WHERE lower(coalesce(normalized_search_text, '')) LIKE '%%' || :query || '%%'
           OR lower(coalesce(keyword_text, '')) LIKE '%%' || :query || '%%'
           OR lower(coalesce(performance_criteria_text, '')) LIKE '%%' || :query || '%%'
           OR lower(coalesce(minor_category_name, '')) LIKE '%%' || :query || '%%'
           OR lower(coalesce(subcategory_name, '')) LIKE '%%' || :query || '%%'
           OR replace(lower(coalesce(normalized_search_text, '')), ' ', '') LIKE '%%' || :query_nospace || '%%'
           OR replace(lower(coalesce(keyword_text, '')), ' ', '') LIKE '%%' || :query_nospace || '%%'
           OR replace(lower(coalesce(performance_criteria_text, '')), ' ', '') LIKE '%%' || :query_nospace || '%%'
           OR replace(lower(coalesce(minor_category_name, '')), ' ', '') LIKE '%%' || :query_nospace || '%%'
           OR replace(lower(coalesce(subcategory_name, '')), ' ', '') LIKE '%%' || :query_nospace || '%%'
           OR search_vector @@ q.q_web
           OR search_vector @@ q.q_plain
    )
    SELECT
        unit_category_id,
        unit_name,
        unit_element_id,
        unit_element_name,
        major_category_name,
        middle_category_name,
        minor_category_name,
        subcategory_code,
        subcategory_name,
        keyword_score,
        fts_score
    FROM scored
    ORDER BY (keyword_score + fts_score) DESC, search_index_id ASC
    LIMIT :top_k
    """
    with get_connection() as conn:
        rows = conn.execute(
            text(sql),
            {"query": match_query, "query_nospace": normalized_nospace, "top_k": top_k},
        ).mappings().all()

    recs = []
    for row in rows:
        keyword_score = _score_to_float(row.get("keyword_score"))
        base_score = max(keyword_score, _score_to_float(row.get("fts_score")))
        affinity = _name_token_affinity(
            f"{row['unit_name']} {row['unit_element_name']}",
            content_tokens,
        )
        final_score = base_score * (0.6 + affinity * 0.4)
        recs.append(
            {
                "unit_category_id": row["unit_category_id"],
                "unit_name": row["unit_name"],
                "unit_element_id": row["unit_element_id"],
                "unit_element_name": row["unit_element_name"],
                "major_category_name": row.get("major_category_name"),
                "middle_category_name": row.get("middle_category_name"),
                "minor_category_name": row.get("minor_category_name"),
                "subcategory_code": row.get("subcategory_code"),
                "subcategory_name": row.get("subcategory_name"),
                "keyword_score": keyword_score,
                "vector_score": 0.0,
                "final_score": final_score,
                "reason": "능력단위명/요소명/키워드 및 FTS 매칭",
            }
        )

    minor_term = _ncs_minor_category_query_term(normalized)
    if minor_term:
        ncs_minor_recs = _build_units_from_ncs_minor_category(minor_term, top_k)
        if ncs_minor_recs:
            recs = _merge_unit_recommendations(ncs_minor_recs, recs, top_k)

    # 부서명만 검색한 경우(예: 총무팀, 품질팀) T23→T24 매핑 능력단위를 우선 노출한다.
    if _is_department_only_query(normalized, content_tokens, dept):
        label = dept_synonym or strip_org_suffix(normalized.replace(" ", "")) or normalized
        dept_matches = detect_department_names(normalized)
        if dept_matches:
            dept_names = [str(item["standard_department_name"]) for item in dept_matches]
            dept_recs = _build_units_from_departments(dept_names, label, top_k)
        else:
            stem = strip_org_suffix(normalized.replace(" ", ""))
            dept_recs = _build_units_from_text_stem(stem, top_k)
        if dept_recs:
            recs = dept_recs

    # 사전 경로가 잡히면 매핑 기반 능력단위를 우선 추가한다.
    job = detect_job(normalized)
    if job and recs:
        mapped_units = map_job_to_units(str(job["standard_job_name"]), top_k=top_k)
        mapped_unit_ids = {str(item["unit_category_id"]) for item in mapped_units}
        recs.sort(key=lambda x: 0 if x["unit_category_id"] in mapped_unit_ids else 1)
    elif job and not recs:
        mapped_units = map_job_to_units(str(job["standard_job_name"]), top_k=top_k)
        if mapped_units:
            ids_for_meta = [str(m["unit_category_id"]) for m in mapped_units if m.get("unit_category_id")]
            bulk_meta_map: dict[str, dict] = {}
            sql_meta_bulk = """
            SELECT DISTINCT ON (unit_category_id)
                unit_category_id,
                unit_name,
                unit_element_id,
                unit_element_name,
                major_category_name,
                middle_category_name,
                minor_category_name,
                subcategory_code,
                subcategory_name
            FROM T25_NCS_SEARCH_INDEX
            WHERE unit_category_id = ANY(:unit_category_ids)
            ORDER BY unit_category_id, search_index_id ASC
            """
            with get_connection() as conn:
                if ids_for_meta:
                    meta_rows = conn.execute(
                        text(sql_meta_bulk),
                        {"unit_category_ids": sorted(set(ids_for_meta))},
                    ).mappings().all()
                    for meta in meta_rows:
                        uid = str(meta.get("unit_category_id") or "")
                        if uid:
                            bulk_meta_map[uid] = dict(meta)

            for mapped in mapped_units:
                meta = bulk_meta_map.get(str(mapped["unit_category_id"]) or "")
                if not meta:
                    continue
                score = _score_to_float(mapped.get("match_weight"))
                recs.append(
                    {
                        "unit_category_id": meta["unit_category_id"],
                        "unit_name": meta["unit_name"],
                        "unit_element_id": meta["unit_element_id"],
                        "unit_element_name": meta["unit_element_name"],
                        "major_category_name": meta.get("major_category_name"),
                        "middle_category_name": meta.get("middle_category_name"),
                        "minor_category_name": meta.get("minor_category_name"),
                        "subcategory_code": meta.get("subcategory_code"),
                        "subcategory_name": meta.get("subcategory_name"),
                        "keyword_score": score,
                        "vector_score": 0.0,
                        "final_score": score * (0.6 + _name_token_affinity(
                            f"{meta['unit_name']} {meta['unit_element_name']}",
                            content_tokens,
                        ) * 0.4),
                        "reason": f"직무 '{job['standard_job_name']}' 매핑 기반 추천",
                    }
                )

    # 그래도 결과가 비어 있으면 토큰 단위 매칭으로 능력단위를 추정한다.
    if not recs:
        fallback_tokens = [token for token in content_tokens if len(token) >= 2]
        if not fallback_tokens and normalized:
            fallback_tokens = [normalized]

        sql_fallback = """
        SELECT
            unit_category_id,
            unit_name,
            unit_element_id,
            unit_element_name,
            major_category_name,
            middle_category_name,
            minor_category_name,
            subcategory_code,
            subcategory_name,
            count(*) AS hit_count
        FROM T25_NCS_SEARCH_INDEX
        WHERE lower(coalesce(unit_name, '')) LIKE '%%' || :token || '%%'
           OR lower(coalesce(unit_element_name, '')) LIKE '%%' || :token || '%%'
           OR lower(coalesce(keyword_text, '')) LIKE '%%' || :token || '%%'
           OR lower(coalesce(performance_criteria_text, '')) LIKE '%%' || :token || '%%'
           OR replace(lower(coalesce(unit_name, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
           OR replace(lower(coalesce(unit_element_name, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
           OR replace(lower(coalesce(keyword_text, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
           OR replace(lower(coalesce(performance_criteria_text, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
        GROUP BY
            unit_category_id,
            unit_name,
            unit_element_id,
            unit_element_name,
            major_category_name,
            middle_category_name,
            minor_category_name,
            subcategory_code,
            subcategory_name
        ORDER BY hit_count DESC
        LIMIT 12
        """
        score_map: dict[tuple[str, str], dict] = {}
        with get_connection() as conn:
            for token in fallback_tokens:
                fallback_rows = conn.execute(
                    text(sql_fallback),
                    {"token": token, "token_nospace": token.replace(" ", "")},
                ).mappings().all()
                for row in fallback_rows:
                    key = (str(row["unit_category_id"]), str(row["unit_element_id"]))
                    base = min(1.0, _score_to_float(row.get("hit_count")) / 10.0)
                    affinity = _name_token_affinity(
                        f"{row['unit_name']} {row['unit_element_name']}",
                        content_tokens,
                    )
                    score = max(base, min(1.0, 0.4 + affinity * 0.6))
                    prev = score_map.get(key)
                    if prev and _score_to_float(prev.get("final_score")) >= score:
                        continue
                    score_map[key] = {
                        "unit_category_id": row["unit_category_id"],
                        "unit_name": row["unit_name"],
                        "unit_element_id": row["unit_element_id"],
                        "unit_element_name": row["unit_element_name"],
                        "major_category_name": row.get("major_category_name"),
                        "middle_category_name": row.get("middle_category_name"),
                        "minor_category_name": row.get("minor_category_name"),
                        "subcategory_code": row.get("subcategory_code"),
                        "subcategory_name": row.get("subcategory_name"),
                        "keyword_score": score,
                        "vector_score": 0.0,
                        "final_score": score,
                        "reason": "T25 키워드+수행준거 토큰 매칭 기반 능력단위 추정",
                    }

        recs = sorted(
            score_map.values(),
            key=lambda item: _score_to_float(item.get("final_score")),
            reverse=True,
        )

    adjusted_recs = []
    for item in recs:
        context_text = " ".join(
            [
                str(item.get("unit_name") or ""),
                str(item.get("unit_element_name") or ""),
                str(item.get("major_category_name") or ""),
                str(item.get("middle_category_name") or ""),
                str(item.get("minor_category_name") or ""),
                str(item.get("subcategory_name") or ""),
                str(item.get("reason") or ""),
            ]
        )
        penalty = _payroll_domain_penalty(context_text, payroll_intent)
        adjusted = dict(item)
        adjusted["final_score"] = _score_to_float(item.get("final_score")) * penalty
        adjusted["keyword_score"] = _score_to_float(item.get("keyword_score")) * penalty
        dept_mult = _department_affinity_multiplier(context_text, dept_tokens)
        task_mult = _task_focus_multiplier(
            f"{item.get('unit_name') or ''} {item.get('unit_element_name') or ''}",
            content_tokens,
        )
        adjusted["final_score"] = _score_to_float(adjusted.get("final_score")) * dept_mult
        adjusted["keyword_score"] = _score_to_float(adjusted.get("keyword_score")) * dept_mult
        adjusted["final_score"] = _score_to_float(adjusted.get("final_score")) * task_mult
        adjusted["keyword_score"] = _score_to_float(adjusted.get("keyword_score")) * task_mult
        unit_category_id = str(item.get("unit_category_id") or "")
        subcategory_code = str(item.get("subcategory_code") or "")
        if unit_category_id and unit_category_id in preferred_unit_ids and task_mult >= 0.75:
            adjusted["final_score"] = _score_to_float(adjusted.get("final_score")) + 0.35
            adjusted["keyword_score"] = _score_to_float(adjusted.get("keyword_score")) + 0.35
        elif subcategory_code and subcategory_code in preferred_subcategory_codes and task_mult >= 0.75:
            adjusted["final_score"] = _score_to_float(adjusted.get("final_score")) + 0.2
            adjusted["keyword_score"] = _score_to_float(adjusted.get("keyword_score")) + 0.2
        adjusted_recs.append(adjusted)

    deduped_recs = _deduplicate_units_by_category(adjusted_recs, top_k=top_k)
    if payroll_intent:
        deduped_recs = [item for item in deduped_recs if _score_to_float(item.get("final_score")) >= 0.05]

    return {
        "query": query,
        "normalized_query": normalized,
        "recommended_units": deduped_recs,
        "_matched_keywords_str": " ".join(keywords),
    }


def search_full(query: str, top_k: int) -> dict:
    unit_result = search_units(query, top_k)
    units = unit_result["recommended_units"]
    normalized_query = unit_result["normalized_query"]
    keywords = extract_keywords(normalized_query)

    # 성능 최적화: full 응답은 units 결과를 기준으로 jobs/subcategories를 파생한다.
    # (기존 jobs/subcategories 개별 계산은 유지되며, 각 단일 엔드포인트에서 사용 가능)
    fast_subcategories = _derive_subcategories_from_units(units=units, keywords=keywords, top_k=top_k)
    fast_jobs = _derive_jobs_from_units(units=units, top_k=top_k)

    # 4단계에서는 vector 구조만 유지하고 실제 결과는 미사용한다.
    _ = vector_search(normalized_query, top_k)

    response = {
        "query": query,
        "normalized_query": normalized_query,
        "recommended_subcategories": fast_subcategories,
        "recommended_jobs": fast_jobs,
        "recommended_units": units,
    }

    top_sub = (response["recommended_subcategories"] or [{}])[0]
    top_job = (response["recommended_jobs"] or [{}])[0]
    top_unit = (response["recommended_units"] or [{}])[0]
    save_search_log(
        input_text=query,
        normalized_input_text=normalized_query,
        search_type="api_full",
        recommended_subcategory_code=top_sub.get("subcategory_code"),
        recommended_subcategory_name=top_sub.get("subcategory_name"),
        recommended_job_name=top_job.get("job_name"),
        recommended_unit_category_id=top_unit.get("unit_category_id"),
        recommended_unit_name=top_unit.get("unit_name"),
        keyword_score=_score_to_float(top_sub.get("keyword_score") or top_unit.get("keyword_score")),
        vector_score=0.0,
        final_score=_score_to_float(top_sub.get("final_score") or top_unit.get("final_score")),
        matched_keywords=unit_result.get("_matched_keywords_str", ""),
        recommendation_reason=(top_sub.get("reason") or top_unit.get("reason") or "API 검색 결과"),
    )
    return response


def extract_code_patterns(raw: str) -> list[str]:
    """콤마·공백·마침표 등으로 구분된 6~8자리 분류 코드를 추출한다."""
    return list(dict.fromkeys(re.findall(r"\d{6,8}", str(raw or ""))))


def resolve_subcategory_codes(code_patterns: list[str]) -> list[str]:
    """
    description 등에 적힌 분류 코드(6~8자리)를 세분류 코드(8자리) 목록으로 확장한다.
    - 8자리이고 DB에 있으면 해당 세분류만
    - 그 외 숫자 코드는 subcategory_code LIKE '{pattern}%' 로 매칭
    """
    resolved: set[str] = set()
    patterns: list[str] = []
    for item in code_patterns:
        patterns.extend(extract_code_patterns(str(item)))
    patterns = list(dict.fromkeys(patterns))
    if not patterns:
        return []

    sql_exact = """
    SELECT DISTINCT subcategory_code
    FROM T25_NCS_SEARCH_INDEX
    WHERE subcategory_code = :code
    """
    sql_prefix = """
    SELECT DISTINCT subcategory_code
    FROM T25_NCS_SEARCH_INDEX
    WHERE subcategory_code LIKE :prefix
    ORDER BY subcategory_code
    """
    with get_connection() as conn:
        for pattern in patterns:
            if not pattern.isdigit():
                continue
            if len(pattern) >= 8:
                row = conn.execute(text(sql_exact), {"code": pattern}).mappings().first()
                if row and row.get("subcategory_code"):
                    resolved.add(str(row["subcategory_code"]))
                    continue
            prefix = f"{pattern}%"
            rows = conn.execute(text(sql_prefix), {"prefix": prefix}).mappings().all()
            for row in rows:
                code = str(row.get("subcategory_code") or "").strip()
                if code:
                    resolved.add(code)
    return sorted(resolved)


def get_units_by_subcategory(subcategory_code: str, top_k: int = 100) -> dict:
    sql = """
    SELECT DISTINCT ON (unit_category_id)
        subcategory_code,
        subcategory_name,
        major_category_name,
        middle_category_name,
        minor_category_name,
        unit_category_id,
        unit_name,
        unit_definition,
        unit_element_id,
        unit_element_name
    FROM T25_NCS_SEARCH_INDEX
    WHERE subcategory_code = :subcategory_code
    ORDER BY unit_category_id, search_index_id ASC
    LIMIT :top_k
    """
    with get_connection() as conn:
        rows = conn.execute(
            text(sql),
            {"subcategory_code": subcategory_code, "top_k": top_k},
        ).mappings().all()

    units = [
        {
            "unit_category_id": row["unit_category_id"],
            "unit_name": row["unit_name"],
            "unit_definition": row.get("unit_definition"),
            "unit_element_id": row["unit_element_id"],
            "unit_element_name": row["unit_element_name"],
            "major_category_name": row.get("major_category_name"),
            "middle_category_name": row.get("middle_category_name"),
            "minor_category_name": row.get("minor_category_name"),
            "subcategory_code": row.get("subcategory_code"),
            "subcategory_name": row.get("subcategory_name"),
            "keyword_score": 1.0,
            "vector_score": 0.0,
            "final_score": 1.0,
            "reason": "세분류 코드 기반 체크리스트 조회",
        }
        for row in rows
    ]
    return {
        "subcategory_code": subcategory_code,
        "subcategory_name": rows[0]["subcategory_name"] if rows else None,
        "major_category_name": rows[0].get("major_category_name") if rows else None,
        "middle_category_name": rows[0].get("middle_category_name") if rows else None,
        "minor_category_name": rows[0].get("minor_category_name") if rows else None,
        "units": units,
    }


def get_units_by_subcategory_patterns(
    code_patterns: list[str],
    units_per_subcategory: int = 500,
) -> dict:
    """
    콤마로 구분된 분류 코드(예: 020201,020203)에 해당하는 세분류별 능력단위 전체를 반환한다.
    """
    patterns: list[str] = []
    for item in code_patterns:
        patterns.extend(extract_code_patterns(str(item)))
    patterns = list(dict.fromkeys(patterns))
    resolved_codes = resolve_subcategory_codes(patterns)

    if not resolved_codes:
        return {
            "requested_patterns": patterns,
            "resolved_subcategory_codes": [],
            "subcategories": [],
            "units": [],
        }

    sql = """
    SELECT DISTINCT ON (subcategory_code, unit_category_id)
        subcategory_code,
        subcategory_name,
        major_category_name,
        middle_category_name,
        minor_category_name,
        unit_category_id,
        unit_name,
        unit_definition,
        unit_element_id,
        unit_element_name
    FROM T25_NCS_SEARCH_INDEX
    WHERE subcategory_code = ANY(:codes)
    ORDER BY subcategory_code, unit_category_id, search_index_id ASC
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql), {"codes": resolved_codes}).mappings().all()

    grouped: dict[str, list[dict]] = defaultdict(list)
    seen_unit_ids: set[str] = set()
    merged_units: list[dict] = []

    for row in rows:
        sub_code = str(row.get("subcategory_code") or "")
        unit_id = str(row.get("unit_category_id") or "")
        if not sub_code or not unit_id:
            continue
        unit = {
            "unit_category_id": unit_id,
            "unit_name": row["unit_name"],
            "unit_definition": row.get("unit_definition"),
            "unit_element_id": row["unit_element_id"],
            "unit_element_name": row["unit_element_name"],
            "major_category_name": row.get("major_category_name"),
            "middle_category_name": row.get("middle_category_name"),
            "minor_category_name": row.get("minor_category_name"),
            "subcategory_code": sub_code,
            "subcategory_name": row.get("subcategory_name"),
            "keyword_score": 1.0,
            "vector_score": 0.0,
            "final_score": 1.0,
            "reason": "예시 분류 코드 조회",
        }
        if len(grouped[sub_code]) < units_per_subcategory:
            grouped[sub_code].append(unit)
        if unit_id not in seen_unit_ids:
            seen_unit_ids.add(unit_id)
            merged_units.append(unit)

    subcategories: list[dict] = []
    for sub_code in resolved_codes:
        units = grouped.get(sub_code) or []
        if not units:
            continue
        first = units[0]
        subcategories.append(
            {
                "subcategory_code": sub_code,
                "subcategory_name": first.get("subcategory_name"),
                "major_category_name": first.get("major_category_name"),
                "middle_category_name": first.get("middle_category_name"),
                "minor_category_name": first.get("minor_category_name"),
                "units": units,
            }
        )

    return {
        "requested_patterns": patterns,
        "resolved_subcategory_codes": resolved_codes,
        "subcategories": subcategories,
        "units": merged_units,
    }


def get_units_by_job_name(job_name: str, top_k: int = 100) -> dict:
    """
    직무명(표준직무명) 기준으로 매핑된 능력단위/요소를 반환한다.
    """
    sql = """
    WITH mapped AS (
        SELECT
            standard_job_name,
            unit_category_id,
            unit_name AS mapped_unit_name,
            match_weight
        FROM T24_JOB_UNIT_MAPPING
        WHERE is_active = TRUE
          AND standard_job_name = :job_name
    )
    SELECT
        m.standard_job_name,
        t.unit_category_id,
        coalesce(t.unit_name, m.mapped_unit_name) AS unit_name,
        t.unit_element_id,
        t.unit_element_name,
        t.major_category_name,
        t.middle_category_name,
        t.minor_category_name,
        t.subcategory_code,
        t.subcategory_name,
        max(m.match_weight) AS max_weight
    FROM mapped m
    LEFT JOIN T25_NCS_SEARCH_INDEX t
        ON m.unit_category_id = t.unit_category_id
    GROUP BY
        m.standard_job_name,
        t.unit_category_id,
        coalesce(t.unit_name, m.mapped_unit_name),
        t.unit_element_id,
        t.unit_element_name,
        t.major_category_name,
        t.middle_category_name,
        t.minor_category_name,
        t.subcategory_code,
        t.subcategory_name
    ORDER BY max_weight DESC, t.unit_category_id, t.unit_element_id
    LIMIT :top_k
    """
    with get_connection() as conn:
        rows = conn.execute(
            text(sql),
            {"job_name": job_name, "top_k": top_k},
        ).mappings().all()

    units = []
    for row in rows:
        if not row["unit_category_id"]:
            continue
        units.append(
            {
                "unit_category_id": row["unit_category_id"],
                "unit_name": row["unit_name"] or "",
                "unit_element_id": row["unit_element_id"] or "",
                "unit_element_name": row["unit_element_name"] or "",
                "major_category_name": row.get("major_category_name"),
                "middle_category_name": row.get("middle_category_name"),
                "minor_category_name": row.get("minor_category_name"),
                "subcategory_code": row.get("subcategory_code"),
                "subcategory_name": row.get("subcategory_name"),
                "keyword_score": _score_to_float(row.get("max_weight")),
                "vector_score": 0.0,
                "final_score": _score_to_float(row.get("max_weight")),
                "reason": "직무-능력단위 매핑(T24) 기반 체크리스트 조회",
            }
        )

    return {
        "job_name": job_name,
        "units": units,
    }
