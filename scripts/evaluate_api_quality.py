from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.search_service import search_full
from src.db import get_cursor

REPORT_DIR = ROOT_DIR / "reports"
DETAIL_CSV = REPORT_DIR / "api_quality_details.csv"
FAILED_CSV = REPORT_DIR / "api_quality_failed.csv"
SUMMARY_JSON = REPORT_DIR / "api_quality_summary.json"


def _safe(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _load_cases(limit: int | None = None) -> list[dict[str, Any]]:
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


def _contains_expected(expected: str, candidates: list[str]) -> bool:
    e = _safe(expected)
    if not e:
        return True
    return e in {_safe(c) for c in candidates}


def evaluate(limit: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    cases = _load_cases(limit=limit)
    rows: list[dict[str, Any]] = []
    for case in cases:
        result = search_full(query=case["input_text"], top_k=5)
        sub = result.get("recommended_subcategories") or []
        jobs = result.get("recommended_jobs") or []
        units = result.get("recommended_units") or []

        top_sub = sub[0] if sub else {}
        top_job = jobs[0] if jobs else {}
        top_unit = units[0] if units else {}

        sub_codes = [_safe(x.get("subcategory_code")) for x in sub]
        job_names = [_safe(x.get("job_name")) for x in jobs]
        unit_ids = [_safe(x.get("unit_category_id")) for x in units]

        top1_sub_ok = (_safe(case["expected_subcategory_code"]) == _safe(top_sub.get("subcategory_code"))) or (
            not _safe(case["expected_subcategory_code"])
        )
        top1_job_ok = (_safe(case["expected_job_name"]) == _safe(top_job.get("job_name"))) or (
            not _safe(case["expected_job_name"])
        )
        top1_unit_ok = (_safe(case["expected_unit_category_id"]) == _safe(top_unit.get("unit_category_id"))) or (
            not _safe(case["expected_unit_category_id"])
        )

        top5_sub_ok = _contains_expected(case["expected_subcategory_code"], sub_codes)
        top5_job_ok = _contains_expected(case["expected_job_name"], job_names)
        top5_unit_ok = _contains_expected(case["expected_unit_category_id"], unit_ids)

        rows.append(
            {
                "test_case_id": case["test_case_id"],
                "input_type": case["input_type"],
                "input_text": case["input_text"],
                "expected_subcategory_code": case["expected_subcategory_code"],
                "expected_job_name": case["expected_job_name"],
                "expected_unit_category_id": case["expected_unit_category_id"],
                "top1_sub_ok": top1_sub_ok,
                "top1_job_ok": top1_job_ok,
                "top1_unit_ok": top1_unit_ok,
                "top5_sub_ok": top5_sub_ok,
                "top5_job_ok": top5_job_ok,
                "top5_unit_ok": top5_unit_ok,
                "actual_top1_subcategory_code": top_sub.get("subcategory_code"),
                "actual_top1_job_name": top_job.get("job_name"),
                "actual_top1_unit_category_id": top_unit.get("unit_category_id"),
                "actual_jobs": " | ".join(job_names),
                "actual_units": " | ".join(unit_ids),
                "test_memo": case["test_memo"],
            }
        )

    details = pd.DataFrame(rows)
    if details.empty:
        summary = pd.DataFrame(
            [
                {
                    "total_cases": 0,
                    "top1_sub_accuracy": 0.0,
                    "top1_job_accuracy": 0.0,
                    "top1_unit_accuracy": 0.0,
                    "top5_sub_hit_rate": 0.0,
                    "top5_job_hit_rate": 0.0,
                    "top5_unit_hit_rate": 0.0,
                }
            ]
        )
        return summary, details

    summary = pd.DataFrame(
        [
            {
                "total_cases": int(len(details)),
                "top1_sub_accuracy": round(float(details["top1_sub_ok"].mean() * 100), 2),
                "top1_job_accuracy": round(float(details["top1_job_ok"].mean() * 100), 2),
                "top1_unit_accuracy": round(float(details["top1_unit_ok"].mean() * 100), 2),
                "top5_sub_hit_rate": round(float(details["top5_sub_ok"].mean() * 100), 2),
                "top5_job_hit_rate": round(float(details["top5_job_ok"].mean() * 100), 2),
                "top5_unit_hit_rate": round(float(details["top5_unit_ok"].mean() * 100), 2),
            }
        ]
    )
    return summary, details


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    summary_df, details_df = evaluate(limit=limit)
    failed_df = details_df[
        ~(
            details_df.get("top1_sub_ok", pd.Series([], dtype=bool))
            & details_df.get("top1_job_ok", pd.Series([], dtype=bool))
            & details_df.get("top1_unit_ok", pd.Series([], dtype=bool))
        )
    ].copy()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    details_df.to_csv(DETAIL_CSV, index=False, encoding="utf-8-sig")
    failed_df.to_csv(FAILED_CSV, index=False, encoding="utf-8-sig")

    summary_obj = summary_df.iloc[0].to_dict()
    SUMMARY_JSON.write_text(json.dumps(summary_obj, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n[API 품질 요약]")
    print(summary_df.to_string(index=False))
    print(f"\n[DETAIL] {DETAIL_CSV}")
    print(f"[FAILED] {FAILED_CSV}")
    print(f"[SUMMARY] {SUMMARY_JSON}")


if __name__ == "__main__":
    main()
