from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.db import get_cursor


def _pick_target_unit() -> dict | None:
    """
    매핑에 사용할 대표 능력단위를 고른다.
    가능하면 '문서' 키워드가 포함된 단위를 우선 선택한다.
    """
    with get_cursor() as (_, cur):
        cur.execute(
            """
            SELECT unit_category_id, unit_name, subcategory_code, subcategory_name
            FROM T11_NCS_UNITS
            WHERE unit_name IS NOT NULL
              AND unit_name <> ''
              AND lower(unit_name) LIKE '%문서%'
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if row:
            return row

        cur.execute(
            """
            SELECT unit_category_id, unit_name, subcategory_code, subcategory_name
            FROM T11_NCS_UNITS
            WHERE unit_name IS NOT NULL
              AND unit_name <> ''
            ORDER BY id_t11 ASC
            LIMIT 1
            """
        )
        return cur.fetchone()


def seed_data() -> None:
    target = _pick_target_unit()
    if not target:
        raise RuntimeError("T11_NCS_UNITS 데이터가 없어 시드를 생성할 수 없습니다.")

    unit_category_id = target["unit_category_id"]
    unit_name = target["unit_name"]

    with get_cursor() as (conn, cur):
        # 반복 실행 시 중복 방지를 위해 기존 샘플을 먼저 삭제한다.
        cur.execute(
            """
            DELETE FROM T21_DEPARTMENT_DICTIONARY
            WHERE standard_department_name IN ('총무팀', '인사팀')
            """
        )
        cur.execute(
            """
            DELETE FROM T22_JOB_DICTIONARY
            WHERE standard_job_name IN ('문서관리담당자', '총무담당자')
            """
        )
        cur.execute(
            """
            DELETE FROM T23_DEPARTMENT_JOB_MAPPING
            WHERE standard_department_name IN ('총무팀', '인사팀')
               OR standard_job_name IN ('문서관리담당자', '총무담당자')
            """
        )
        cur.execute(
            """
            DELETE FROM T24_JOB_UNIT_MAPPING
            WHERE standard_job_name IN ('문서관리담당자', '총무담당자')
            """
        )
        cur.execute(
            """
            DELETE FROM T26_SEARCH_TEST_CASES
            WHERE input_text IN ('총무팀 문서관리 담당자', '인사팀 문서관리 직무')
            """
        )

        # T21: 부서 동의어
        cur.execute(
            """
            INSERT INTO T21_DEPARTMENT_DICTIONARY
            (standard_department_name, synonym_name, description)
            VALUES
            ('총무팀', '총무팀', '샘플 부서 동의어'),
            ('총무팀', '총무', '샘플 부서 동의어'),
            ('인사팀', '인사팀', '샘플 부서 동의어'),
            ('인사팀', '인사', '샘플 부서 동의어')
            """
        )

        # T22: 직무 동의어
        cur.execute(
            """
            INSERT INTO T22_JOB_DICTIONARY
            (standard_job_name, synonym_name, job_description)
            VALUES
            ('문서관리담당자', '문서관리 담당자', '샘플 직무 동의어'),
            ('문서관리담당자', '문서관리', '샘플 직무 동의어'),
            ('총무담당자', '총무 담당자', '샘플 직무 동의어'),
            ('총무담당자', '총무', '샘플 직무 동의어')
            """
        )

        # T23: 부서-직무 매핑
        cur.execute(
            """
            INSERT INTO T23_DEPARTMENT_JOB_MAPPING
            (standard_department_name, standard_job_name, match_weight, mapping_reason)
            VALUES
            ('총무팀', '문서관리담당자', 0.95, '총무팀-문서관리 기본 매핑'),
            ('인사팀', '문서관리담당자', 0.80, '인사팀 문서업무 보조 매핑')
            """
        )

        # T24: 직무-능력단위 매핑 (실데이터에서 선택한 unit_category_id 연결)
        cur.execute(
            """
            INSERT INTO T24_JOB_UNIT_MAPPING
            (standard_job_name, unit_category_id, unit_name, match_weight, mapping_reason)
            VALUES
            (%s, %s, %s, 0.97, '샘플 직무-능력단위 매핑'),
            ('총무담당자', %s, %s, 0.88, '샘플 직무-능력단위 매핑')
            """,
            ("문서관리담당자", unit_category_id, unit_name, unit_category_id, unit_name),
        )

        # T26: 검색 테스트 케이스
        cur.execute(
            """
            INSERT INTO T26_SEARCH_TEST_CASES (
                input_text,
                input_type,
                expected_job_name,
                expected_unit_category_id,
                expected_unit_name,
                test_memo
            ) VALUES
            ('총무팀 문서관리 담당자', '복합문장', '문서관리담당자', %s, %s, '사전+매핑 검증'),
            ('인사팀 문서관리 직무', '복합문장', '문서관리담당자', %s, %s, '사전+매핑 검증')
            """,
            (unit_category_id, unit_name, unit_category_id, unit_name),
        )

        conn.commit()

    print("[OK] 최소 사전/매핑/테스트 데이터 시드 완료")
    print(f"[INFO] 매핑 unit_category_id={unit_category_id}, unit_name={unit_name}")


if __name__ == "__main__":
    seed_data()
