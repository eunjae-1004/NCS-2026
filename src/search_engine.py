from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from src.db import get_cursor

FINAL_SCORE_WEIGHTS = {
    "keyword": 0.45,
    "dictionary": 0.25,
    "mapping": 0.30,
    "vector": 0.00,  # 3단계에서는 벡터 검색 미사용
}


def normalize_text(text: str) -> str:
    """
    검색 품질을 높이기 위한 입력 정규화.
    """
    lowered = text.lower().strip()
    return re.sub(r"\s+", " ", lowered)


@dataclass
class SearchResult:
    search_type: str
    subcategory_code: str | None
    subcategory_name: str | None
    job_name: str | None
    unit_category_id: str | None
    unit_name: str | None
    keyword_score: float
    dictionary_score: float
    mapping_score: float
    vector_score: float
    final_score: float
    matched_keywords: str
    recommendation_reason: str


@dataclass
class SubcategoryRecommendation:
    subcategory_code: str | None
    subcategory_name: str | None
    score: float
    matched_keywords: str
    reason: str


@dataclass
class UnitRecommendation:
    unit_category_id: str | None
    unit_name: str | None
    unit_element_id: str | None
    unit_element_name: str | None
    score: float
    reason: str


@dataclass
class RecommendationBundle:
    input_text: str
    normalized_input_text: str
    search_type: str
    keyword_score: float
    dictionary_score: float
    mapping_score: float
    vector_score: float
    final_score: float
    subcategory_recommendations: list[SubcategoryRecommendation]
    job_recommendations: list[dict[str, Any]]
    unit_recommendations: list[UnitRecommendation]


class NcsSearchEngine:
    """
    요구된 우선순위에 맞춰 키워드 검색을 수행한다.
    1) 부서 사전 -> 2) 직무 사전 -> 3) 직무-능력단위 매핑 -> 4) T25 키워드 -> 5) FTS
    """

    @staticmethod
    def _compute_final_score(
        keyword_score: float,
        dictionary_score: float,
        mapping_score: float,
        vector_score: float,
    ) -> float:
        return (
            keyword_score * FINAL_SCORE_WEIGHTS["keyword"]
            + dictionary_score * FINAL_SCORE_WEIGHTS["dictionary"]
            + mapping_score * FINAL_SCORE_WEIGHTS["mapping"]
            + vector_score * FINAL_SCORE_WEIGHTS["vector"]
        )

    def search(self, input_text: str) -> SearchResult:
        normalized = normalize_text(input_text)

        # 1. 부서명 사전 매칭
        dept_match = self._match_department(normalized)

        # 2. 직무명 사전 매칭 (부서 매칭과 독립)
        job_match = self._match_job(normalized)

        # 부서가 매칭되었고 직무가 직접 매칭되지 않은 경우에만 부서-직무 매핑 사용
        if not job_match and dept_match:
            job_match = self._map_department_to_job(dept_match["standard_department_name"])

        if job_match:
            # 3. 직무-능력단위 매핑
            mapped = self._map_job_to_unit(job_match["standard_job_name"])
            if mapped:
                subcategory = self._lookup_subcategory_by_unit_category(mapped.get("unit_category_id"))
                matched_keywords = " ".join(
                    filter(
                        None,
                        [
                            (dept_match or {}).get("synonym_name", ""),
                            job_match.get("synonym_name", ""),
                        ],
                    )
                ).strip()
                result = SearchResult(
                    search_type="dictionary_mapping",
                    subcategory_code=(subcategory or {}).get("subcategory_code"),
                    subcategory_name=(subcategory or {}).get("subcategory_name"),
                    job_name=job_match["standard_job_name"],
                    unit_category_id=mapped.get("unit_category_id"),
                    unit_name=mapped.get("unit_name"),
                    keyword_score=0.0,
                    dictionary_score=1.0,
                    mapping_score=float(mapped.get("match_weight") or 0.9),
                    vector_score=0.0,
                    final_score=self._compute_final_score(
                        keyword_score=0.0,
                        dictionary_score=1.0,
                        mapping_score=float(mapped.get("match_weight") or 0.9),
                        vector_score=0.0,
                    ),
                    matched_keywords=matched_keywords,
                    recommendation_reason="부서/직무 사전 및 매핑 테이블 기반 추천",
                )
                self._log_result(input_text, normalized, result)
                return result

        # 4. T25 키워드 검색
        keyword_result = self._search_t25_keyword(normalized)
        if keyword_result:
            self._log_result(input_text, normalized, keyword_result)
            return keyword_result

        # 5. PostgreSQL Full Text Search
        fts_result = self._search_t25_fts(normalized)
        if fts_result:
            self._log_result(input_text, normalized, fts_result)
            return fts_result

        # 검색 실패도 로그로 남긴다.
        empty = SearchResult(
            search_type="no_match",
            subcategory_code=None,
            subcategory_name=None,
            job_name=None,
            unit_category_id=None,
            unit_name=None,
            keyword_score=0.0,
            dictionary_score=0.0,
            mapping_score=0.0,
            vector_score=0.0,
            final_score=0.0,
            matched_keywords="",
            recommendation_reason="일치 결과 없음",
        )
        self._log_result(input_text, normalized, empty)
        return empty

    def recommend(self, input_text: str) -> RecommendationBundle:
        """
        요구사항의 결과 구조(세분류 -> 직무 -> 능력단위)로 반환한다.
        """
        result = self.search(input_text)
        normalized = normalize_text(input_text)

        subcategory_recs: list[SubcategoryRecommendation] = []
        if result.subcategory_code or result.subcategory_name:
            subcategory_recs.append(
                SubcategoryRecommendation(
                    subcategory_code=result.subcategory_code,
                    subcategory_name=result.subcategory_name,
                    score=result.final_score,
                    matched_keywords=result.matched_keywords,
                    reason=result.recommendation_reason,
                )
            )

        grouped_recs = self._top_subcategory_recommendations(normalized, limit=3)
        existing_codes = {rec.subcategory_code for rec in subcategory_recs}
        for rec in grouped_recs:
            if rec.subcategory_code in existing_codes:
                continue
            subcategory_recs.append(rec)
            if len(subcategory_recs) >= 3:
                break

        if not subcategory_recs:
            subcategory_recs = grouped_recs[:3]

        job_recs: list[dict[str, Any]] = []
        if result.job_name:
            job_recs.append(
                {
                    "job_name": result.job_name,
                    "score": result.final_score,
                    "reason": "부서/직무 사전 및 매핑 결과",
                }
            )
        else:
            inferred_job = self._infer_job_from_input(normalized)
            if inferred_job:
                job_recs.append(inferred_job)

        unit_recs = self._top_unit_recommendations(normalized, limit=3)
        if not unit_recs and result.unit_category_id:
            # 단건 결과만 있는 경우 fallback
            unit_meta = self._lookup_unit_meta(result.unit_category_id)
            unit_recs = [
                UnitRecommendation(
                    unit_category_id=result.unit_category_id,
                    unit_name=result.unit_name,
                    unit_element_id=(unit_meta or {}).get("unit_element_id"),
                    unit_element_name=(unit_meta or {}).get("unit_element_name"),
                    score=result.final_score,
                    reason=result.recommendation_reason,
                )
            ]

        return RecommendationBundle(
            input_text=input_text,
            normalized_input_text=normalized,
            search_type=result.search_type,
            keyword_score=result.keyword_score,
            dictionary_score=result.dictionary_score,
            mapping_score=result.mapping_score,
            vector_score=result.vector_score,
            final_score=result.final_score,
            subcategory_recommendations=subcategory_recs,
            job_recommendations=job_recs,
            unit_recommendations=unit_recs,
        )

    @staticmethod
    def bundle_to_dict(bundle: RecommendationBundle) -> dict[str, Any]:
        """
        API/CLI 출력에 바로 사용할 수 있게 dataclass를 dict로 변환한다.
        """
        return asdict(bundle)

    def _match_department(self, normalized_text: str) -> dict[str, Any] | None:
        sql = """
        SELECT standard_department_name, synonym_name
        FROM T21_DEPARTMENT_DICTIONARY
        WHERE is_active = TRUE
          AND %s LIKE '%%' || lower(synonym_name) || '%%'
        ORDER BY length(synonym_name) DESC
        LIMIT 1
        """
        with get_cursor() as (_, cur):
            cur.execute(sql, (normalized_text,))
            return cur.fetchone()

    def _match_job(self, normalized_text: str) -> dict[str, Any] | None:
        sql = """
        SELECT standard_job_name, synonym_name
        FROM T22_JOB_DICTIONARY
        WHERE is_active = TRUE
          AND %s LIKE '%%' || lower(synonym_name) || '%%'
        ORDER BY length(synonym_name) DESC
        LIMIT 1
        """
        with get_cursor() as (_, cur):
            cur.execute(sql, (normalized_text,))
            return cur.fetchone()

    def _map_department_to_job(self, standard_department_name: str) -> dict[str, Any] | None:
        sql = """
        SELECT standard_job_name, match_weight, mapping_reason
        FROM T23_DEPARTMENT_JOB_MAPPING
        WHERE is_active = TRUE
          AND standard_department_name = %s
        ORDER BY match_weight DESC, mapping_id ASC
        LIMIT 1
        """
        with get_cursor() as (_, cur):
            cur.execute(sql, (standard_department_name,))
            return cur.fetchone()

    def _map_job_to_unit(self, standard_job_name: str) -> dict[str, Any] | None:
        sql = """
        SELECT unit_category_id, unit_name, match_weight, mapping_reason
        FROM T24_JOB_UNIT_MAPPING
        WHERE is_active = TRUE
          AND standard_job_name = %s
        ORDER BY match_weight DESC, mapping_id ASC
        LIMIT 1
        """
        with get_cursor() as (_, cur):
            cur.execute(sql, (standard_job_name,))
            return cur.fetchone()

    def _lookup_subcategory_by_unit_category(self, unit_category_id: str | None) -> dict[str, Any] | None:
        if not unit_category_id:
            return None
        sql = """
        SELECT subcategory_code, subcategory_name
        FROM T25_NCS_SEARCH_INDEX
        WHERE unit_category_id = %s
        ORDER BY search_index_id ASC
        LIMIT 1
        """
        with get_cursor() as (_, cur):
            cur.execute(sql, (unit_category_id,))
            return cur.fetchone()

    def _lookup_unit_meta(self, unit_category_id: str | None) -> dict[str, Any] | None:
        if not unit_category_id:
            return None
        sql = """
        SELECT unit_name, unit_element_id, unit_element_name
        FROM T25_NCS_SEARCH_INDEX
        WHERE unit_category_id = %s
        ORDER BY search_index_id ASC
        LIMIT 1
        """
        with get_cursor() as (_, cur):
            cur.execute(sql, (unit_category_id,))
            return cur.fetchone()

    def _infer_job_from_input(self, normalized_text: str) -> dict[str, Any] | None:
        sql = """
        SELECT standard_job_name, synonym_name
        FROM T22_JOB_DICTIONARY
        WHERE is_active = TRUE
          AND %s LIKE '%%' || lower(synonym_name) || '%%'
        ORDER BY length(synonym_name) DESC
        LIMIT 1
        """
        with get_cursor() as (_, cur):
            cur.execute(sql, (normalized_text,))
            row = cur.fetchone()

        if not row:
            return None

        return {
            "job_name": row["standard_job_name"],
            "score": 0.7,
            "reason": f"입력문장에서 직무 동의어('{row['synonym_name']}') 매칭",
        }

    def _search_t25_keyword(self, normalized_text: str) -> SearchResult | None:
        sql = """
        SELECT
            subcategory_code,
            subcategory_name,
            unit_category_id,
            unit_name,
            -- 간단한 키워드 점수: 일치 여부 기반 가중치
            (
                CASE WHEN lower(coalesce(subcategory_name, '')) LIKE '%%' || %s || '%%' THEN 0.40 ELSE 0 END
              + CASE WHEN lower(coalesce(unit_name, '')) LIKE '%%' || %s || '%%' THEN 0.40 ELSE 0 END
              + CASE WHEN lower(coalesce(keyword_text, '')) LIKE '%%' || %s || '%%' THEN 0.20 ELSE 0 END
            ) AS keyword_score
        FROM T25_NCS_SEARCH_INDEX
        WHERE lower(coalesce(normalized_search_text, '')) LIKE '%%' || %s || '%%'
           OR lower(coalesce(keyword_text, '')) LIKE '%%' || %s || '%%'
           OR lower(coalesce(subcategory_keyword_text, '')) LIKE '%%' || %s || '%%'
        ORDER BY keyword_score DESC, search_index_id ASC
        LIMIT 1
        """
        with get_cursor() as (_, cur):
            cur.execute(
                sql,
                (normalized_text, normalized_text, normalized_text, normalized_text, normalized_text, normalized_text),
            )
            row = cur.fetchone()

        if not row:
            return None

        score = float(row["keyword_score"] or 0.0)
        return SearchResult(
            search_type="keyword",
            subcategory_code=row.get("subcategory_code"),
            subcategory_name=row.get("subcategory_name"),
            job_name=None,
            unit_category_id=row.get("unit_category_id"),
            unit_name=row.get("unit_name"),
            keyword_score=score,
            dictionary_score=0.0,
            mapping_score=0.0,
            vector_score=0.0,
            final_score=self._compute_final_score(
                keyword_score=score,
                dictionary_score=0.0,
                mapping_score=0.0,
                vector_score=0.0,
            ),
            matched_keywords=normalized_text,
            recommendation_reason="T25 통합 키워드 검색 일치",
        )

    def _search_t25_fts(self, normalized_text: str) -> SearchResult | None:
        # websearch_to_tsquery를 우선 사용하고, 실패 시 plainto_tsquery로 대체한다.
        sql = """
        WITH q AS (
            SELECT
                websearch_to_tsquery('simple', %s) AS q_web,
                plainto_tsquery('simple', %s) AS q_plain
        )
        SELECT
            t.subcategory_code,
            t.subcategory_name,
            t.unit_category_id,
            t.unit_name,
            GREATEST(
                ts_rank(t.search_vector, q.q_web),
                ts_rank(t.search_vector, q.q_plain)
            ) AS rank_score
        FROM T25_NCS_SEARCH_INDEX t
        CROSS JOIN q
        WHERE t.search_vector @@ q.q_web
           OR t.search_vector @@ q.q_plain
        ORDER BY rank_score DESC, t.search_index_id ASC
        LIMIT 1
        """
        with get_cursor() as (_, cur):
            cur.execute(sql, (normalized_text, normalized_text))
            row = cur.fetchone()

        if not row:
            return None

        score = float(row["rank_score"] or 0.0)
        return SearchResult(
            search_type="fts",
            subcategory_code=row.get("subcategory_code"),
            subcategory_name=row.get("subcategory_name"),
            job_name=None,
            unit_category_id=row.get("unit_category_id"),
            unit_name=row.get("unit_name"),
            keyword_score=score,
            dictionary_score=0.0,
            mapping_score=0.0,
            vector_score=0.0,
            final_score=self._compute_final_score(
                keyword_score=score,
                dictionary_score=0.0,
                mapping_score=0.0,
                vector_score=0.0,
            ),
            matched_keywords=normalized_text,
            recommendation_reason="PostgreSQL Full Text Search 일치",
        )

    def _top_subcategory_recommendations(self, normalized_text: str, limit: int = 3) -> list[SubcategoryRecommendation]:
        """
        세분류 단위로 점수를 집계해 Top N 추천을 반환한다.
        """
        sql = """
        WITH q AS (
            SELECT
                websearch_to_tsquery('simple', %s) AS q_web,
                plainto_tsquery('simple', %s) AS q_plain
        ),
        scored AS (
            SELECT
                t.subcategory_code,
                t.subcategory_name,
                (
                    CASE WHEN lower(coalesce(t.subcategory_name, '')) LIKE '%%' || %s || '%%' THEN 0.40 ELSE 0 END
                  + CASE WHEN lower(coalesce(t.unit_name, '')) LIKE '%%' || %s || '%%' THEN 0.40 ELSE 0 END
                  + CASE WHEN lower(coalesce(t.keyword_text, '')) LIKE '%%' || %s || '%%' THEN 0.20 ELSE 0 END
                ) AS keyword_score,
                GREATEST(
                    ts_rank(t.search_vector, q.q_web),
                    ts_rank(t.search_vector, q.q_plain)
                ) AS fts_score
            FROM T25_NCS_SEARCH_INDEX t
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
        LIMIT %s
        """
        with get_cursor() as (_, cur):
            cur.execute(
                sql,
                (
                    normalized_text,
                    normalized_text,
                    normalized_text,
                    normalized_text,
                    normalized_text,
                    limit,
                ),
            )
            rows = cur.fetchall() or []

        out: list[SubcategoryRecommendation] = []
        for row in rows:
            keyword_score = float(row.get("keyword_score") or 0.0)
            fts_score = float(row.get("fts_score") or 0.0)
            score = self._compute_final_score(
                keyword_score=max(keyword_score, fts_score),
                dictionary_score=0.0,
                mapping_score=0.0,
                vector_score=0.0,
            )
            out.append(
                SubcategoryRecommendation(
                    subcategory_code=row.get("subcategory_code"),
                    subcategory_name=row.get("subcategory_name"),
                    score=score,
                    matched_keywords=normalized_text,
                    reason="세분류 groupby 기반 Top 추천",
                )
            )
        return out

    def _top_unit_recommendations(self, normalized_text: str, limit: int = 3) -> list[UnitRecommendation]:
        sql = """
        WITH q AS (
            SELECT
                websearch_to_tsquery('simple', %s) AS q_web,
                plainto_tsquery('simple', %s) AS q_plain
        )
        SELECT
            unit_category_id,
            unit_name,
            unit_element_id,
            unit_element_name,
            GREATEST(
                ts_rank(search_vector, q.q_web),
                ts_rank(search_vector, q.q_plain)
            ) AS score
        FROM T25_NCS_SEARCH_INDEX
        CROSS JOIN q
        WHERE search_vector @@ q.q_web
           OR search_vector @@ q.q_plain
        ORDER BY score DESC, search_index_id ASC
        LIMIT %s
        """
        with get_cursor() as (_, cur):
            cur.execute(sql, (normalized_text, normalized_text, limit))
            rows = cur.fetchall() or []

        return [
            UnitRecommendation(
                unit_category_id=row.get("unit_category_id"),
                unit_name=row.get("unit_name"),
                unit_element_id=row.get("unit_element_id"),
                unit_element_name=row.get("unit_element_name"),
                score=float(row.get("score") or 0.0),
                reason="FTS 기반 능력단위 추천",
            )
            for row in rows
        ]

    def vector_search(self, normalized_text: str, limit: int = 3) -> list[dict[str, Any]]:
        """
        향후 pgvector/외부 임베딩 API 연동을 위한 확장 포인트.
        3단계에서는 실제 벡터 검색을 수행하지 않고 빈 결과를 반환한다.
        """
        _ = (normalized_text, limit)
        return []

    def _log_result(self, raw_text: str, normalized_text: str, result: SearchResult) -> None:
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
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """
        with get_cursor() as (conn, cur):
            cur.execute(
                sql,
                (
                    raw_text,
                    normalized_text,
                    result.search_type,
                    result.subcategory_code,
                    result.subcategory_name,
                    result.job_name,
                    result.unit_category_id,
                    result.unit_name,
                    result.keyword_score,
                    result.vector_score,
                    result.final_score,
                    result.matched_keywords,
                    result.recommendation_reason,
                ),
            )
            conn.commit()
