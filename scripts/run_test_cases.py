from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.db import get_cursor
from src.search_engine import NcsSearchEngine

FAILED_CASES_CSV = ROOT_DIR / "reports" / "failed_test_cases.csv"


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_match(expected: str, actual: str) -> bool:
    """
    expected가 비어 있으면 검증 대상에서 제외한다.
    """
    expected = _safe_text(expected)
    actual = _safe_text(actual)
    if not expected:
        return True
    return expected == actual


def _load_test_cases(limit: int | None = None) -> list[dict[str, Any]]:
    sql = """
    SELECT
        test_case_id,
        input_text,
        input_type,
        expected_subcategory_code,
        expected_subcategory_name,
        expected_job_name,
        expected_unit_category_id,
        expected_unit_name,
        test_memo
    FROM T26_SEARCH_TEST_CASES
    ORDER BY test_case_id ASC
    """
    if limit is not None:
        sql += " LIMIT %s"

    with get_cursor() as (_, cur):
        if limit is not None:
            cur.execute(sql, (limit,))
        else:
            cur.execute(sql)
        return cur.fetchall() or []


def _evaluate_case(engine: NcsSearchEngine, case: dict[str, Any]) -> dict[str, Any]:
    bundle = engine.recommend(case["input_text"])
    bundle_dict = engine.bundle_to_dict(bundle)

    top_sub = (bundle_dict.get("subcategory_recommendations") or [{}])[0]
    top_job = (bundle_dict.get("job_recommendations") or [{}])[0]
    top_unit = (bundle_dict.get("unit_recommendations") or [{}])[0]

    subcategory_code_ok = _is_match(case["expected_subcategory_code"], top_sub.get("subcategory_code"))
    subcategory_name_ok = _is_match(case["expected_subcategory_name"], top_sub.get("subcategory_name"))
    job_name_ok = _is_match(case["expected_job_name"], top_job.get("job_name"))
    unit_category_ok = _is_match(case["expected_unit_category_id"], top_unit.get("unit_category_id"))
    unit_name_ok = _is_match(case["expected_unit_name"], top_unit.get("unit_name"))

    is_pass = all(
        [
            subcategory_code_ok,
            subcategory_name_ok,
            job_name_ok,
            unit_category_ok,
            unit_name_ok,
        ]
    )

    return {
        "test_case_id": case["test_case_id"],
        "input_type": case["input_type"],
        "input_text": case["input_text"],
        "pass": is_pass,
        "expected_subcategory_code": case["expected_subcategory_code"],
        "expected_subcategory_name": case["expected_subcategory_name"],
        "expected_job_name": case["expected_job_name"],
        "expected_unit_category_id": case["expected_unit_category_id"],
        "expected_unit_name": case["expected_unit_name"],
        "actual_subcategory_code": top_sub.get("subcategory_code"),
        "actual_subcategory_name": top_sub.get("subcategory_name"),
        "actual_job_name": top_job.get("job_name"),
        "actual_unit_category_id": top_unit.get("unit_category_id"),
        "actual_unit_name": top_unit.get("unit_name"),
        "keyword_score": float(bundle_dict.get("keyword_score") or 0.0),
        "dictionary_score": float(bundle_dict.get("dictionary_score") or 0.0),
        "mapping_score": float(bundle_dict.get("mapping_score") or 0.0),
        "vector_score": float(bundle_dict.get("vector_score") or 0.0),
        "final_score": float(bundle_dict.get("final_score") or 0.0),
        "matched_keywords": top_sub.get("matched_keywords") or "",
        "reason": top_sub.get("reason") or "",
        "check_subcategory_code": subcategory_code_ok,
        "check_subcategory_name": subcategory_name_ok,
        "check_job_name": job_name_ok,
        "check_unit_category_id": unit_category_ok,
        "check_unit_name": unit_name_ok,
        "test_memo": case["test_memo"],
    }


def run_test_cases(limit: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    engine = NcsSearchEngine()
    cases = _load_test_cases(limit=limit)
    rows = [_evaluate_case(engine, case) for case in cases]

    details_df = pd.DataFrame(rows)
    if details_df.empty:
        summary_df = pd.DataFrame(
            [
                {
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "pass_rate": 0.0,
                }
            ]
        )
        failed_df = details_df.copy()
        return summary_df, details_df, failed_df

    total = int(len(details_df))
    passed = int(details_df["pass"].sum())
    failed = int(total - passed)
    pass_rate = round((passed / total) * 100.0, 2) if total else 0.0

    summary_df = pd.DataFrame(
        [
            {
                "total": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": pass_rate,
            }
        ]
    )
    failed_df = details_df[details_df["pass"] == False].copy()  # noqa: E712
    return summary_df, details_df, failed_df


def main() -> None:
    limit = None
    if len(sys.argv) > 1:
        limit = int(sys.argv[1])

    summary_df, details_df, failed_df = run_test_cases(limit=limit)

    print("\n[검증 요약]")
    print(summary_df.to_string(index=False))

    print("\n[상세 결과]")
    display_columns = [
        "test_case_id",
        "input_type",
        "pass",
        "actual_subcategory_code",
        "actual_job_name",
        "actual_unit_category_id",
        "final_score",
        "reason",
    ]
    if details_df.empty:
        print("테스트 케이스가 없습니다.")
    else:
        print(details_df[display_columns].to_string(index=False))

    FAILED_CASES_CSV.parent.mkdir(parents=True, exist_ok=True)
    failed_df.to_csv(FAILED_CASES_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[실패 케이스 CSV] {FAILED_CASES_CSV}")


if __name__ == "__main__":
    main()
