"""
T28_SEARCH_EXAMPLE_QUERIES 테이블 생성 및 기본 예시 질문 시드.

사용:
  python scripts/seed_example_queries.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text

from app.db import get_connection

MIGRATION_SQL = (ROOT_DIR / "sql" / "002_search_example_queries.sql").read_text(encoding="utf-8")


def main() -> None:
    statements = [part.strip() for part in MIGRATION_SQL.split(";") if part.strip()]
    with get_connection() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
    print("[OK] T28_SEARCH_EXAMPLE_QUERIES 시드 완료")


if __name__ == "__main__":
    main()
