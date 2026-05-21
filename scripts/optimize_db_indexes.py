from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db import get_connection


INDEX_SQLS = [
    # trigram extension for LIKE/ILIKE acceleration
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    # T25 text search acceleration
    """
    CREATE INDEX IF NOT EXISTS idx_t25_normalized_search_text_trgm
    ON T25_NCS_SEARCH_INDEX
    USING GIN (lower(normalized_search_text) gin_trgm_ops)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_t25_keyword_text_trgm
    ON T25_NCS_SEARCH_INDEX
    USING GIN (lower(keyword_text) gin_trgm_ops)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_t25_performance_criteria_text_trgm
    ON T25_NCS_SEARCH_INDEX
    USING GIN (lower(performance_criteria_text) gin_trgm_ops)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_t25_unit_name_trgm
    ON T25_NCS_SEARCH_INDEX
    USING GIN (lower(unit_name) gin_trgm_ops)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_t25_unit_element_name_trgm
    ON T25_NCS_SEARCH_INDEX
    USING GIN (lower(unit_element_name) gin_trgm_ops)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_t25_subcategory_name_trgm
    ON T25_NCS_SEARCH_INDEX
    USING GIN (lower(subcategory_name) gin_trgm_ops)
    """,
    # no-space expression acceleration for queries using replace(..., ' ', '')
    """
    CREATE INDEX IF NOT EXISTS idx_t25_normalized_search_text_nospace_trgm
    ON T25_NCS_SEARCH_INDEX
    USING GIN ((replace(lower(coalesce(normalized_search_text, '')), ' ', '')) gin_trgm_ops)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_t25_keyword_text_nospace_trgm
    ON T25_NCS_SEARCH_INDEX
    USING GIN ((replace(lower(coalesce(keyword_text, '')), ' ', '')) gin_trgm_ops)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_t25_performance_criteria_nospace_trgm
    ON T25_NCS_SEARCH_INDEX
    USING GIN ((replace(lower(coalesce(performance_criteria_text, '')), ' ', '')) gin_trgm_ops)
    """,
    # mapping/path lookups
    """
    CREATE INDEX IF NOT EXISTS idx_t24_job_active_weight
    ON T24_JOB_UNIT_MAPPING(standard_job_name, is_active, match_weight DESC, mapping_id ASC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_t24_unit_active_weight
    ON T24_JOB_UNIT_MAPPING(unit_category_id, is_active, match_weight DESC, mapping_id ASC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_t23_dept_active_weight
    ON T23_DEPARTMENT_JOB_MAPPING(standard_department_name, is_active, match_weight DESC, mapping_id ASC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_t25_unit_category_search_index
    ON T25_NCS_SEARCH_INDEX(unit_category_id, search_index_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_t25_subcategory_unit_element
    ON T25_NCS_SEARCH_INDEX(subcategory_code, unit_category_id, unit_element_id)
    """,
]


def run() -> None:
    with get_connection() as conn:
        for sql in INDEX_SQLS:
            conn.execute(text(sql))
    print("[OK] DB index optimization statements applied.")


if __name__ == "__main__":
    run()
