from __future__ import annotations

from sqlalchemy import text

from app.db import get_connection
from app.services.dictionary_service import (
    detect_department,
    detect_job,
    map_department_to_jobs,
    map_job_to_units,
)
from app.services.log_service import save_search_log
from app.services.normalize_service import extract_keywords, normalize_query
from app.services.vector_service import vector_search

MIN_JOB_SCORE = 0.20


def _score_to_float(value: object) -> float:
    return float(value or 0.0)


def _extract_content_tokens(keywords: list[str], dept_synonym: str) -> list[str]:
    tokens: list[str] = []
    for token in keywords:
        if not token:
            continue
        if dept_synonym and (dept_synonym in token or token in dept_synonym):
            continue
        tokens.append(token)
    return tokens


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
    SELECT subcategory_code, subcategory_name
    FROM T25_NCS_SEARCH_INDEX
    WHERE unit_category_id = :unit_category_id
    ORDER BY search_index_id ASC
    LIMIT 1
    """
    with get_connection() as conn:
        row = conn.execute(text(sql), {"unit_category_id": unit_category_id}).mappings().first()
    return dict(row) if row else None


def _job_query_relevance(job_name: str, content_tokens: list[str]) -> float:
    """
    직무명이 질의 의도와 실제로 맞는지(T24->T25 근거) 점수화한다.
    """
    if not content_tokens:
        return 0.5

    sql = """
    WITH mapped AS (
        SELECT unit_category_id
        FROM T24_JOB_UNIT_MAPPING
        WHERE is_active = TRUE
          AND standard_job_name = :job_name
    )
    SELECT
        count(*) AS total_rows,
        sum(
            CASE
                WHEN lower(coalesce(t.unit_name, '')) LIKE '%%' || :token || '%%'
                  OR lower(coalesce(t.unit_element_name, '')) LIKE '%%' || :token || '%%'
                  OR lower(coalesce(t.keyword_text, '')) LIKE '%%' || :token || '%%'
                  OR lower(coalesce(t.performance_criteria_text, '')) LIKE '%%' || :token || '%%'
                  OR replace(lower(coalesce(t.unit_name, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
                  OR replace(lower(coalesce(t.unit_element_name, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
                  OR replace(lower(coalesce(t.keyword_text, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
                  OR replace(lower(coalesce(t.performance_criteria_text, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
                THEN 1 ELSE 0
            END
        ) AS hit_rows
    FROM mapped m
    JOIN T25_NCS_SEARCH_INDEX t
      ON t.unit_category_id = m.unit_category_id
    """
    sql_direct = """
    SELECT
        count(*) AS total_rows,
        sum(
            CASE
                WHEN lower(coalesce(t.unit_name, '')) LIKE '%%' || :token || '%%'
                  OR lower(coalesce(t.unit_element_name, '')) LIKE '%%' || :token || '%%'
                  OR lower(coalesce(t.keyword_text, '')) LIKE '%%' || :token || '%%'
                  OR lower(coalesce(t.performance_criteria_text, '')) LIKE '%%' || :token || '%%'
                  OR replace(lower(coalesce(t.unit_name, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
                  OR replace(lower(coalesce(t.unit_element_name, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
                  OR replace(lower(coalesce(t.keyword_text, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
                  OR replace(lower(coalesce(t.performance_criteria_text, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
                THEN 1 ELSE 0
            END
        ) AS hit_rows
    FROM T25_NCS_SEARCH_INDEX t
    WHERE t.unit_name = :job_name
    """
    total_hits = 0.0
    checked_tokens = 0
    with get_connection() as conn:
        for token in content_tokens:
            params = {
                "job_name": job_name,
                "token": token,
                "token_nospace": token.replace(" ", ""),
            }
            row = conn.execute(
                text(sql),
                params,
            ).mappings().first()
            total_rows = int(row["total_rows"] or 0) if row else 0
            hit_rows = int(row["hit_rows"] or 0) if row else 0
            if total_rows <= 0:
                # T24 매핑이 없는 직무명은 T25 직무명(unit_name) 자체에서 근거를 본다.
                row_direct = conn.execute(text(sql_direct), params).mappings().first()
                total_rows = int(row_direct["total_rows"] or 0) if row_direct else 0
                hit_rows = int(row_direct["hit_rows"] or 0) if row_direct else 0
                if total_rows <= 0:
                    continue
            total_hits += min(1.0, hit_rows / total_rows)
            checked_tokens += 1

    if checked_tokens == 0:
        return 0.0
    return total_hits / checked_tokens


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

    for rank, unit in enumerate(units, start=1):
        unit_category_id = str(unit.get("unit_category_id") or "")
        if not unit_category_id:
            continue

        sub = _lookup_subcategory_by_unit_category(unit_category_id)
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


def search_subcategories(query: str, top_k: int) -> dict:
    normalized = normalize_query(query)
    keywords = extract_keywords(normalized)
    keyword_str = " ".join(keywords)

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
        max(keyword_score) AS keyword_score,
        max(fts_score) AS fts_score
    FROM scored
    WHERE keyword_score > 0 OR fts_score > 0
    GROUP BY subcategory_code, subcategory_name
    ORDER BY (max(keyword_score) + max(fts_score)) DESC, subcategory_code
    LIMIT :top_k
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql), {"query": normalized, "top_k": top_k}).mappings().all()

    recs = []
    for row in rows:
        keyword_score = _score_to_float(row.get("keyword_score"))
        vector_score = 0.0
        final_score = max(keyword_score, _score_to_float(row.get("fts_score")))
        recs.append(
            {
                "subcategory_code": row["subcategory_code"],
                "subcategory_name": row["subcategory_name"],
                "keyword_score": keyword_score,
                "vector_score": vector_score,
                "final_score": final_score,
                "matched_keywords": keywords,
                "reason": "세분류명/세분류 키워드 및 FTS 매칭",
            }
        )

    return {
        "query": query,
        "normalized_query": normalized,
        "recommended_subcategories": recs,
        "_matched_keywords_str": keyword_str,
    }


def search_jobs(query: str, top_k: int) -> dict:
    normalized = normalize_query(query)
    normalized_nospace = normalized.replace(" ", "")
    keywords = extract_keywords(normalized)

    direct_job = detect_job(normalized)
    dept = detect_department(normalized)
    dept_synonym = str((dept or {}).get("synonym_name") or "")
    content_tokens = _extract_content_tokens(keywords, dept_synonym)

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
    unit_candidates = search_units(query=query, top_k=max(top_k * 3, 5))["recommended_units"]
    if unit_candidates:
        sql = """
        SELECT standard_job_name, match_weight
        FROM T24_JOB_UNIT_MAPPING
        WHERE is_active = TRUE
          AND unit_category_id = :unit_category_id
        ORDER BY match_weight DESC, mapping_id ASC
        LIMIT 3
        """
        with get_connection() as conn:
            for unit in unit_candidates:
                unit_score = _score_to_float(unit.get("final_score"))
                unit_category_id = str(unit.get("unit_category_id") or "")
                if not unit_category_id:
                    continue
                mapped_rows = conn.execute(
                    text(sql),
                    {"unit_category_id": unit_category_id},
                ).mappings().all()
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

    sql = """
    SELECT
        unit_name,
        sum(
            CASE
                WHEN lower(coalesce(unit_name, '')) LIKE '%%' || :token || '%%'
                  OR lower(coalesce(unit_element_name, '')) LIKE '%%' || :token || '%%'
                  OR lower(coalesce(subcategory_name, '')) LIKE '%%' || :token || '%%'
                  OR lower(coalesce(keyword_text, '')) LIKE '%%' || :token || '%%'
                  OR replace(lower(coalesce(unit_name, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
                  OR replace(lower(coalesce(unit_element_name, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
                  OR replace(lower(coalesce(subcategory_name, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
                  OR replace(lower(coalesce(keyword_text, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
                THEN 1 ELSE 0
            END
        ) AS direct_hit_count,
        sum(
            CASE
                WHEN lower(coalesce(performance_criteria_text, '')) LIKE '%%' || :token || '%%'
                  OR replace(lower(coalesce(performance_criteria_text, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
                THEN 1 ELSE 0
            END
        ) AS criteria_hit_count
    FROM T25_NCS_SEARCH_INDEX
    WHERE
        lower(coalesce(unit_name, '')) LIKE '%%' || :token || '%%'
        OR lower(coalesce(unit_element_name, '')) LIKE '%%' || :token || '%%'
        OR lower(coalesce(subcategory_name, '')) LIKE '%%' || :token || '%%'
        OR lower(coalesce(keyword_text, '')) LIKE '%%' || :token || '%%'
        OR lower(coalesce(performance_criteria_text, '')) LIKE '%%' || :token || '%%'
        OR replace(lower(coalesce(unit_name, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
        OR replace(lower(coalesce(unit_element_name, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
        OR replace(lower(coalesce(subcategory_name, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
        OR replace(lower(coalesce(keyword_text, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
        OR replace(lower(coalesce(performance_criteria_text, '')), ' ', '') LIKE '%%' || :token_nospace || '%%'
    GROUP BY unit_name
    ORDER BY direct_hit_count DESC, criteria_hit_count DESC, unit_name
    LIMIT 10
    """
    with get_connection() as conn:
        for token in tokens:
            rows = conn.execute(
                text(sql),
                {
                    "token": token,
                    "token_nospace": token.replace(" ", ""),
                },
            ).mappings().all()
            for row in rows:
                job_name = str(row["unit_name"])
                direct_hit = _score_to_float(row.get("direct_hit_count"))
                criteria_hit = _score_to_float(row.get("criteria_hit_count"))
                affinity = _name_token_affinity(job_name, content_tokens)
                # 수행준거 단독 매칭 + 낮은 토큰 친화도 후보는 제외한다.
                if direct_hit <= 0 and affinity < 0.2:
                    continue
                # 수행준거 단독 매칭 잡음 방지를 위해 criteria 가중치를 낮춘다.
                weighted_hit = direct_hit + (criteria_hit * 0.25)
                base_score = min(1.0, weighted_hit / 10.0)
                # 직무명 텍스트가 의도 토큰을 직접 포함하는지를 더 강하게 반영한다.
                score = min(1.0, affinity * 0.8 + base_score * 0.2)
                _put_candidate(
                    job_name=job_name,
                    score=score,
                    reason="T25 키워드+수행준거 매칭 기반 직무(능력단위명) 추정",
                )

    ranked_jobs = sorted(
        (
            {
                **item,
                "final_score": (
                    _score_to_float(item.get("final_score")) * 0.35
                    + _job_query_relevance(
                        str(item.get("job_name") or ""),
                        content_tokens,
                    )
                    * 0.65
                ),
                "keyword_score": (
                    _score_to_float(item.get("final_score")) * 0.35
                    + _job_query_relevance(
                        str(item.get("job_name") or ""),
                        content_tokens,
                    )
                    * 0.65
                ),
                "reason": f"{item.get('reason', '')} + 직무-능력단위 근거 반영".strip(),
            }
            for item in candidate_map.values()
        ),
        key=lambda item: _score_to_float(item.get("final_score")),
        reverse=True,
    )
    ranked_jobs = [item for item in ranked_jobs if _score_to_float(item.get("final_score")) >= MIN_JOB_SCORE]

    return {
        "query": query,
        "normalized_query": normalized,
        "recommended_jobs": ranked_jobs[:top_k],
        "_matched_keywords_str": " ".join(keywords) or normalized_nospace,
    }


def search_units(query: str, top_k: int) -> dict:
    normalized = normalize_query(query)
    normalized_nospace = normalized.replace(" ", "")
    keywords = extract_keywords(normalized)
    dept = detect_department(normalized)
    dept_synonym = str((dept or {}).get("synonym_name") or "")
    content_tokens = _extract_content_tokens(keywords, dept_synonym)

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
            (
                CASE WHEN lower(coalesce(unit_name, '')) LIKE '%%' || :query || '%%' THEN 0.35 ELSE 0 END
              + CASE WHEN lower(coalesce(unit_element_name, '')) LIKE '%%' || :query || '%%' THEN 0.35 ELSE 0 END
              + CASE WHEN lower(coalesce(keyword_text, '')) LIKE '%%' || :query || '%%' THEN 0.20 ELSE 0 END
              + CASE WHEN lower(coalesce(performance_criteria_text, '')) LIKE '%%' || :query || '%%' THEN 0.10 ELSE 0 END
              + CASE WHEN replace(lower(coalesce(unit_name, '')), ' ', '') LIKE '%%' || :query_nospace || '%%' THEN 0.15 ELSE 0 END
              + CASE WHEN replace(lower(coalesce(unit_element_name, '')), ' ', '') LIKE '%%' || :query_nospace || '%%' THEN 0.15 ELSE 0 END
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
           OR replace(lower(coalesce(normalized_search_text, '')), ' ', '') LIKE '%%' || :query_nospace || '%%'
           OR replace(lower(coalesce(keyword_text, '')), ' ', '') LIKE '%%' || :query_nospace || '%%'
           OR replace(lower(coalesce(performance_criteria_text, '')), ' ', '') LIKE '%%' || :query_nospace || '%%'
           OR search_vector @@ q.q_web
           OR search_vector @@ q.q_plain
    )
    SELECT
        unit_category_id,
        unit_name,
        unit_element_id,
        unit_element_name,
        keyword_score,
        fts_score
    FROM scored
    ORDER BY (keyword_score + fts_score) DESC, search_index_id ASC
    LIMIT :top_k
    """
    with get_connection() as conn:
        rows = conn.execute(
            text(sql),
            {"query": normalized, "query_nospace": normalized_nospace, "top_k": top_k},
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
                "keyword_score": keyword_score,
                "vector_score": 0.0,
                "final_score": final_score,
                "reason": "능력단위명/요소명/키워드 및 FTS 매칭",
            }
        )

    # 사전 경로가 잡히면 매핑 기반 능력단위를 우선 추가한다.
    job = detect_job(normalized)
    if job and recs:
        mapped_units = map_job_to_units(str(job["standard_job_name"]), top_k=top_k)
        mapped_unit_ids = {str(item["unit_category_id"]) for item in mapped_units}
        recs.sort(key=lambda x: 0 if x["unit_category_id"] in mapped_unit_ids else 1)
    elif job and not recs:
        mapped_units = map_job_to_units(str(job["standard_job_name"]), top_k=top_k)
        if mapped_units:
            sql_meta = """
            SELECT unit_category_id, unit_name, unit_element_id, unit_element_name
            FROM T25_NCS_SEARCH_INDEX
            WHERE unit_category_id = :unit_category_id
            ORDER BY search_index_id ASC
            LIMIT 1
            """
            with get_connection() as conn:
                for mapped in mapped_units:
                    meta = conn.execute(
                        text(sql_meta),
                        {"unit_category_id": mapped["unit_category_id"]},
                    ).mappings().first()
                    if not meta:
                        continue
                    score = _score_to_float(mapped.get("match_weight"))
                    recs.append(
                        {
                            "unit_category_id": meta["unit_category_id"],
                            "unit_name": meta["unit_name"],
                            "unit_element_id": meta["unit_element_id"],
                            "unit_element_name": meta["unit_element_name"],
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
        GROUP BY unit_category_id, unit_name, unit_element_id, unit_element_name
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

    return {
        "query": query,
        "normalized_query": normalized,
        "recommended_units": recs[:top_k],
        "_matched_keywords_str": " ".join(keywords),
    }


def search_full(query: str, top_k: int) -> dict:
    subcategory_result = search_subcategories(query, top_k)
    job_result = search_jobs(query, top_k)
    unit_result = search_units(query, top_k)
    normalized_query = subcategory_result["normalized_query"]
    keywords = extract_keywords(normalized_query)

    # 4단계에서는 vector 구조만 유지하고 실제 결과는 미사용한다.
    _ = vector_search(normalized_query, top_k)

    reconciled_subcategories = _merge_subcategory_with_unit_signals(
        subcategories=subcategory_result["recommended_subcategories"],
        units=unit_result["recommended_units"],
        keywords=keywords,
        top_k=top_k,
    )

    response = {
        "query": query,
        "normalized_query": normalized_query,
        "recommended_subcategories": reconciled_subcategories,
        "recommended_jobs": job_result["recommended_jobs"],
        "recommended_units": unit_result["recommended_units"],
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
        matched_keywords=subcategory_result.get("_matched_keywords_str", ""),
        recommendation_reason=(top_sub.get("reason") or top_unit.get("reason") or "API 검색 결과"),
    )
    return response


def get_units_by_subcategory(subcategory_code: str, top_k: int = 100) -> dict:
    sql = """
    SELECT
        subcategory_code,
        subcategory_name,
        unit_category_id,
        unit_name,
        unit_element_id,
        unit_element_name
    FROM T25_NCS_SEARCH_INDEX
    WHERE subcategory_code = :subcategory_code
    ORDER BY unit_category_id, unit_element_id
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
            "unit_element_id": row["unit_element_id"],
            "unit_element_name": row["unit_element_name"],
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
        "units": units,
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
        max(m.match_weight) AS max_weight
    FROM mapped m
    LEFT JOIN T25_NCS_SEARCH_INDEX t
        ON m.unit_category_id = t.unit_category_id
    GROUP BY
        m.standard_job_name,
        t.unit_category_id,
        coalesce(t.unit_name, m.mapped_unit_name),
        t.unit_element_id,
        t.unit_element_name
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
