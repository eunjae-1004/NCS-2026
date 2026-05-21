"""
T29/T30 회원·능력단위 저장 테이블 적용.

사용:
  python scripts/apply_user_auth_schema.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text

from app.db import get_connection

MIGRATION_SQL = (ROOT_DIR / "sql" / "003_user_auth.sql").read_text(encoding="utf-8")


def main() -> None:
    statements = [part.strip() for part in MIGRATION_SQL.split(";") if part.strip()]
    with get_connection() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
    print("[OK] T29/T30 회원 스키마 적용 완료")


if __name__ == "__main__":
    main()
