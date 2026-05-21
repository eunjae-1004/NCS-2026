from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.db import get_connection

logger = logging.getLogger(__name__)

_DEFAULT_EXAMPLES = [
    {"example_id": 0, "example_text": "근태관리 업무", "display_order": 1, "description": None},
    {"example_id": 0, "example_text": "회의 준비", "display_order": 2, "description": None},
    {"example_id": 0, "example_text": "고객 비대면 상담", "display_order": 3, "description": None},
    {"example_id": 0, "example_text": "자동차 조립공정 작업", "display_order": 4, "description": None},
]


def list_search_example_queries(limit: int = 20) -> list[dict]:
    """
    자연어 검색 화면에 노출할 예시 질문 목록을 반환한다.
    T28 테이블이 없거나 비어 있으면 기본 예시를 반환한다.

    description 컬럼: 콤마 구분 분류 코드(예: 020201,020203)를 넣으면
    해당 세분류(또는 prefix에 속한 세분류) 능력단위 전체를 조회한다.
    """
    safe_limit = max(1, min(limit, 50))
    sql = """
    SELECT example_id, example_text, display_order, description
    FROM T28_SEARCH_EXAMPLE_QUERIES
    WHERE is_active = TRUE
    ORDER BY display_order ASC, example_id ASC
    LIMIT :limit
    """
    try:
        with get_connection() as conn:
            rows = conn.execute(text(sql), {"limit": safe_limit}).mappings().all()
    except ProgrammingError as exc:
        if "t28_search_example_queries" in str(exc).lower():
            logger.warning("T28_SEARCH_EXAMPLE_QUERIES 없음 — 기본 예시 사용")
            return [dict(item) for item in _DEFAULT_EXAMPLES[:safe_limit]]
        raise

    if not rows:
        logger.warning("T28_SEARCH_EXAMPLE_QUERIES 비어 있음 — 기본 예시 사용")
        return [dict(item) for item in _DEFAULT_EXAMPLES[:safe_limit]]

    return [dict(row) for row in rows]
