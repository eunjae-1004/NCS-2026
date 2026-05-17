from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.preprocess_ncs_index import create_db_engine


def _load_base_pairs(engine, min_row_count: int, top_per_department: int) -> pd.DataFrame:
    sql = text(
        """
        WITH base AS (
            SELECT
                subcategory_name,
                unit_name,
                unit_category_id,
                count(*) AS row_count
            FROM T25_NCS_SEARCH_INDEX
            WHERE coalesce(subcategory_name, '') <> ''
              AND coalesce(unit_name, '') <> ''
              AND coalesce(unit_category_id, '') <> ''
            GROUP BY subcategory_name, unit_name, unit_category_id
            HAVING count(*) >= :min_row_count
        ),
        ranked AS (
            SELECT
                subcategory_name,
                unit_name,
                unit_category_id,
                row_count,
                row_number() OVER (
                    PARTITION BY subcategory_name
                    ORDER BY row_count DESC, unit_name
                ) AS rn,
                max(row_count) OVER (PARTITION BY subcategory_name) AS max_in_subcategory,
                max(row_count) OVER (PARTITION BY unit_name) AS max_in_job
            FROM base
        )
        SELECT
            subcategory_name,
            unit_name,
            unit_category_id,
            row_count,
            rn,
            max_in_subcategory,
            max_in_job
        FROM ranked
        WHERE rn <= :top_per_department
        ORDER BY subcategory_name, row_count DESC, unit_name
        """
    )
    return pd.read_sql_query(
        sql,
        con=engine,
        params={"min_row_count": min_row_count, "top_per_department": top_per_department},
    )


def _build_candidates(base_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if base_df.empty:
        return {
            "t21": pd.DataFrame(
                columns=["standard_department_name", "synonym_name", "description", "is_active"]
            ),
            "t22": pd.DataFrame(
                columns=["standard_job_name", "synonym_name", "job_description", "is_active"]
            ),
            "t23": pd.DataFrame(
                columns=[
                    "standard_department_name",
                    "standard_job_name",
                    "match_weight",
                    "mapping_reason",
                    "is_active",
                ]
            ),
            "t24": pd.DataFrame(
                columns=[
                    "standard_job_name",
                    "unit_category_id",
                    "unit_name",
                    "match_weight",
                    "mapping_reason",
                    "is_active",
                ]
            ),
        }

    work = base_df.copy()
    work["standard_department_name"] = work["subcategory_name"].astype(str) + "팀"
    work["standard_job_name"] = work["unit_name"].astype(str)

    # 부서-직무 가중치: 같은 세분류 내 상대 빈도 기준
    work["t23_weight"] = (work["row_count"] / work["max_in_subcategory"]).clip(lower=0.5, upper=0.99)
    # 직무-능력단위 가중치: 직무 내 대표 빈도 기준
    work["t24_weight"] = (work["row_count"] / work["max_in_job"]).clip(lower=0.5, upper=0.99)

    t21 = pd.concat(
        [
            work[["standard_department_name"]]
            .assign(
                synonym_name=lambda d: d["standard_department_name"],
                description="T25 세분류명 기반 자동 생성",
                is_active=True,
            ),
            work[["standard_department_name", "subcategory_name"]]
            .rename(columns={"subcategory_name": "synonym_name"})
            .assign(description="T25 세분류명 기반 자동 생성", is_active=True),
        ],
        ignore_index=True,
    ).drop_duplicates(subset=["standard_department_name", "synonym_name"])

    t22 = work[["standard_job_name"]].assign(
        synonym_name=lambda d: d["standard_job_name"],
        job_description="T25 능력단위명 기반 자동 생성",
        is_active=True,
    ).drop_duplicates(subset=["standard_job_name", "synonym_name"])

    t23 = (
        work[
            [
                "standard_department_name",
                "standard_job_name",
                "t23_weight",
            ]
        ]
        .rename(columns={"t23_weight": "match_weight"})
        .assign(mapping_reason="T25 세분류-능력단위 공기반 자동 매핑", is_active=True)
        .drop_duplicates(subset=["standard_department_name", "standard_job_name"])
    )

    t24 = (
        work[
            [
                "standard_job_name",
                "unit_category_id",
                "unit_name",
                "t24_weight",
            ]
        ]
        .rename(columns={"t24_weight": "match_weight"})
        .assign(mapping_reason="T25 능력단위 빈도 기반 자동 매핑", is_active=True)
        .drop_duplicates(subset=["standard_job_name", "unit_category_id"])
    )

    return {"t21": t21, "t22": t22, "t23": t23, "t24": t24}


def _write_reports(candidates: dict[str, pd.DataFrame], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    for name, df in candidates.items():
        path = report_dir / f"{name}_candidates.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"[REPORT] {path} ({len(df)} rows)")


def _apply_candidates(engine, candidates: dict[str, pd.DataFrame]) -> None:
    sql_map = {
        "t21": text(
            """
            INSERT INTO T21_DEPARTMENT_DICTIONARY
            (standard_department_name, synonym_name, description, is_active)
            SELECT :standard_department_name, :synonym_name, :description, :is_active
            WHERE NOT EXISTS (
                SELECT 1
                FROM T21_DEPARTMENT_DICTIONARY
                WHERE standard_department_name = :standard_department_name
                  AND synonym_name = :synonym_name
            )
            """
        ),
        "t22": text(
            """
            INSERT INTO T22_JOB_DICTIONARY
            (standard_job_name, synonym_name, job_description, is_active)
            SELECT :standard_job_name, :synonym_name, :job_description, :is_active
            WHERE NOT EXISTS (
                SELECT 1
                FROM T22_JOB_DICTIONARY
                WHERE standard_job_name = :standard_job_name
                  AND synonym_name = :synonym_name
            )
            """
        ),
        "t23": text(
            """
            INSERT INTO T23_DEPARTMENT_JOB_MAPPING
            (standard_department_name, standard_job_name, match_weight, mapping_reason, is_active)
            SELECT :standard_department_name, :standard_job_name, :match_weight, :mapping_reason, :is_active
            WHERE NOT EXISTS (
                SELECT 1
                FROM T23_DEPARTMENT_JOB_MAPPING
                WHERE standard_department_name = :standard_department_name
                  AND standard_job_name = :standard_job_name
            )
            """
        ),
        "t24": text(
            """
            INSERT INTO T24_JOB_UNIT_MAPPING
            (standard_job_name, unit_category_id, unit_name, match_weight, mapping_reason, is_active)
            SELECT :standard_job_name, :unit_category_id, :unit_name, :match_weight, :mapping_reason, :is_active
            WHERE NOT EXISTS (
                SELECT 1
                FROM T24_JOB_UNIT_MAPPING
                WHERE standard_job_name = :standard_job_name
                  AND unit_category_id = :unit_category_id
            )
            """
        ),
    }

    with engine.begin() as conn:
        for name, df in candidates.items():
            if df.empty:
                print(f"[APPLY] {name}: 0 rows (skip)")
                continue
            payload = df.to_dict(orient="records")
            conn.execute(sql_map[name], payload)
            print(f"[APPLY] {name}: attempted {len(payload)} rows")


def main() -> None:
    parser = argparse.ArgumentParser(description="Expand T21~T24 candidates from T25 data.")
    parser.add_argument("--apply", action="store_true", help="Apply generated candidates to DB")
    parser.add_argument("--min-row-count", type=int, default=2, help="Minimum group row count")
    parser.add_argument("--top-per-department", type=int, default=30, help="Top jobs per department")
    args = parser.parse_args()

    engine = create_db_engine()
    base_df = _load_base_pairs(
        engine=engine,
        min_row_count=args.min_row_count,
        top_per_department=args.top_per_department,
    )
    print(f"[INFO] base pairs: {len(base_df)}")

    candidates = _build_candidates(base_df)
    report_dir = Path(__file__).resolve().parent.parent / "reports" / "mapping_candidates"
    _write_reports(candidates, report_dir)

    print(
        "[INFO] candidates counts: "
        f"T21={len(candidates['t21'])}, "
        f"T22={len(candidates['t22'])}, "
        f"T23={len(candidates['t23'])}, "
        f"T24={len(candidates['t24'])}"
    )

    if args.apply:
        _apply_candidates(engine, candidates)
        print("[OK] DB apply completed")
    else:
        print("[INFO] Preview only. Use --apply to insert into DB.")


if __name__ == "__main__":
    main()
