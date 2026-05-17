from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.preprocess_ncs_index import (
    build_t25_dataframe,
    create_db_engine,
    fetch_source_tables,
    insert_t25,
    truncate_t25,
    update_t25_search_vector,
)
from src.db import get_cursor


def build_t25_index() -> None:
    # 전처리 표준 스크립트(preprocess_ncs_index.py)와 동일한 규칙으로 T25를 재생성한다.
    engine = create_db_engine()
    source = fetch_source_tables(engine)
    t25_df = build_t25_dataframe(source)
    truncate_t25(engine)
    inserted = insert_t25(engine, t25_df)
    update_t25_search_vector(engine)

    with get_cursor() as (_, cur):
        cur.execute("SELECT count(*) AS cnt FROM T25_NCS_SEARCH_INDEX")
        count_row = cur.fetchone() or {"cnt": 0}

    print(
        "[OK] T25_NCS_SEARCH_INDEX 재생성 완료. "
        f"inserted={inserted}, row_count={count_row['cnt']}"
    )


if __name__ == "__main__":
    build_t25_index()
