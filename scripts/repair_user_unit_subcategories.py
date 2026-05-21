"""
T30에 잘못 저장된 세분류를 T11 기준 메타로 일괄 수정합니다.

사용: .venv 활성화 후
  python scripts/repair_user_unit_subcategories.py
  python scripts/repair_user_unit_subcategories.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app.db import get_connection
from app.services.ncs_service import get_unit_ncs_meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="변경 없이 대상만 출력")
    args = parser.parse_args()

    with get_connection() as conn:
        rows = conn.execute(
            text(
                """
                SELECT selection_id, user_id, unit_category_id,
                       subcategory_code, subcategory_name
                FROM T30_USER_UNIT_SELECTIONS
                ORDER BY selection_id
                """
            )
        ).mappings().all()

    fixed = 0
    skipped = 0
    for row in rows:
        uid = str(row["unit_category_id"] or "").strip()
        meta = get_unit_ncs_meta(uid)
        if not meta or not meta.get("subcategory_code"):
            skipped += 1
            continue
        new_code = str(meta["subcategory_code"])
        new_name = str(meta.get("subcategory_name") or "")
        old_code = str(row.get("subcategory_code") or "")
        if old_code == new_code:
            continue
        fixed += 1
        print(
            f"[{row['selection_id']}] user={row['user_id']} {uid}: "
            f"{old_code} -> {new_code} ({new_name})"
        )
        if args.dry_run:
            continue
        with get_connection() as conn:
            conn.execute(
                text(
                    """
                    UPDATE T30_USER_UNIT_SELECTIONS
                    SET subcategory_code = :subcategory_code,
                        subcategory_name = :subcategory_name
                    WHERE selection_id = :selection_id
                    """
                ),
                {
                    "selection_id": row["selection_id"],
                    "subcategory_code": new_code,
                    "subcategory_name": new_name or None,
                },
            )
            conn.commit()

    print(f"완료: 수정 {fixed}건, 메타 없음/동일 {skipped + len(rows) - fixed}건")


if __name__ == "__main__":
    main()
