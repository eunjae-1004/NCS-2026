from __future__ import annotations

import sys
from pathlib import Path

# 루트 경로를 import 경로에 추가해 src 모듈을 사용할 수 있게 한다.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.db import get_cursor


def run_schema() -> None:
    schema_path = ROOT_DIR / "sql" / "001_schema.sql"
    sql = schema_path.read_text(encoding="utf-8")

    with get_cursor() as (conn, cur):
        cur.execute(sql)
        conn.commit()

    print("[OK] 스키마 생성/갱신 완료:", schema_path)


if __name__ == "__main__":
    run_schema()
