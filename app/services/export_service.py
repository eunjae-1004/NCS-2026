from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from urllib.parse import quote

import pandas as pd
from sqlalchemy import text

from app.db import get_connection
from app.services.job_description_service import get_job_description
from app.services.unit_matrix_service import get_user_units_matrix
from app.services.user_service import get_user_by_id, list_user_unit_selections

_SELECTED_CASE = """
CASE WHEN t30.unit_category_id IS NOT NULL THEN 'Y' ELSE 'N' END AS selected_yn
"""


def _sort_y_first_choice(df: pd.DataFrame, col: str = "선택여부") -> pd.DataFrame:
    if df.empty or col not in df.columns:
        return df
    return df.sort_values(by=col, ascending=False, kind="stable")


def _dedupe_dataframe(df: pd.DataFrame, subset: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    cols = [c for c in subset if c in df.columns]
    if not cols:
        return df
    out = _sort_y_first_choice(df.copy())
    return out.drop_duplicates(subset=cols, keep="first")


def _empty_workbook(message: str) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame([{"안내": message}]).to_excel(writer, sheet_name="안내", index=False)
    buffer.seek(0)
    return buffer.getvalue()


def _resolve_export_scope(user_id: int) -> tuple[list[str], set[str]]:
    """
    저장한 능력단위가 속한 세분류 코드 목록과, 선택된 unit_category_id 집합을 반환.
    """
    selections = list_user_unit_selections(user_id)
    selected_ids = {str(item["unit_category_id"]) for item in selections if item.get("unit_category_id")}
    if not selected_ids:
        raise ValueError("저장한 능력단위가 없습니다. 먼저 능력단위를 저장해 주세요.")

    sql = """
    SELECT DISTINCT subcategory_code
    FROM T11_NCS_UNITS
    WHERE unit_category_id = ANY(:unit_ids)
      AND coalesce(subcategory_code, '') <> ''
    ORDER BY subcategory_code
    """
    with get_connection() as conn:
        sub_codes = [
            str(code)
            for code in conn.execute(text(sql), {"unit_ids": list(selected_ids)}).scalars().all()
        ]
    if not sub_codes:
        raise ValueError("저장 능력단위의 세분류를 확인할 수 없습니다.")
    return sub_codes, selected_ids


def _count_units_in_subcategories(sub_codes: list[str]) -> int:
    sql = """
    SELECT COUNT(DISTINCT unit_category_id)
    FROM T11_NCS_UNITS
    WHERE subcategory_code = ANY(:sub_codes)
      AND coalesce(unit_category_id, '') <> ''
    """
    with get_connection() as conn:
        return int(conn.execute(text(sql), {"sub_codes": sub_codes}).scalar() or 0)


def _list_unit_ids_in_subcategories(sub_codes: list[str]) -> list[str]:
    sql = """
    SELECT DISTINCT unit_category_id
    FROM T11_NCS_UNITS
    WHERE subcategory_code = ANY(:sub_codes)
      AND coalesce(unit_category_id, '') <> ''
    ORDER BY unit_category_id
    """
    with get_connection() as conn:
        return [str(row) for row in conn.execute(text(sql), {"sub_codes": sub_codes}).scalars().all()]


def _fetch_selected_definition_rows(user_id: int) -> pd.DataFrame:
    """
    회원이 저장한 능력단위만 — 세분류·능력단위 정의 포함(요약 다운로드용).
    """
    sql = """
    SELECT
        t30.unit_category_id,
        COALESCE(NULLIF(trim(t30.unit_name), ''), ui.unit_name) AS unit_name,
        COALESCE(NULLIF(trim(t30.subcategory_code), ''), ui.subcategory_code) AS subcategory_code,
        COALESCE(NULLIF(trim(t30.subcategory_name), ''), ui.subcategory_name) AS subcategory_name,
        ui.minor_category_name,
        ui.middle_category_name,
        ui.major_category_name,
        ui.level AS level,
        (
            SELECT td.subcategory_definition
            FROM T14_SUBCATEGORY_DEFINITIONS td
            WHERE td.subcategory_code = COALESCE(
                NULLIF(trim(t30.subcategory_code), ''),
                ui.subcategory_code
            )
            ORDER BY td.id_t14 DESC NULLS LAST
            LIMIT 1
        ) AS subcategory_definition,
        (
            SELECT udp.unit_definition
            FROM T15_UNIT_DEFINITIONS udp
            WHERE udp.unit_category_id = t30.unit_category_id
            ORDER BY udp.id_t15 DESC NULLS LAST
            LIMIT 1
        ) AS unit_definition,
        t30.created_at AS saved_at
    FROM T30_USER_UNIT_SELECTIONS t30
    LEFT JOIN LATERAL (
        SELECT
            unit_name,
            subcategory_code,
            subcategory_name,
            minor_category_name,
            middle_category_name,
            major_category_name,
            level
        FROM T11_NCS_UNITS t11_ui
        WHERE t11_ui.unit_category_id = t30.unit_category_id
        ORDER BY t11_ui.id_t11 ASC
        LIMIT 1
    ) ui ON TRUE
    WHERE t30.user_id = :user_id
    ORDER BY COALESCE(ui.subcategory_code, t30.subcategory_code),
             t30.unit_category_id
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql), {"user_id": user_id}).mappings().all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(row) for row in rows]).rename(
        columns={
            "unit_category_id": "능력단위분류번호",
            "unit_name": "능력단위명",
            "subcategory_code": "세분류코드",
            "subcategory_name": "세분류명",
            "minor_category_name": "소분류명",
            "middle_category_name": "중분류명",
            "major_category_name": "대분류명",
            "level": "수준",
            "subcategory_definition": "세분류정의",
            "unit_definition": "능력단위정의",
            "saved_at": "저장일시",
        }
    )


def _fetch_elements(user_id: int, sub_codes: list[str]) -> pd.DataFrame:
    sql = f"""
    SELECT DISTINCT
        {_SELECTED_CASE},
        t11.unit_category_id,
        t11.unit_name,
        t11.unit_element_id,
        t11.unit_element_name,
        t11.subcategory_code,
        t11.subcategory_name,
        (
            SELECT td.subcategory_definition
            FROM T14_SUBCATEGORY_DEFINITIONS td
            WHERE td.subcategory_code = t11.subcategory_code
            ORDER BY td.id_t14 DESC NULLS LAST
            LIMIT 1
        ) AS subcategory_definition,
        (
            SELECT udp.unit_definition
            FROM T15_UNIT_DEFINITIONS udp
            WHERE udp.unit_category_id = t11.unit_category_id
            ORDER BY udp.id_t15 DESC NULLS LAST
            LIMIT 1
        ) AS unit_definition,
        t11.minor_category_name,
        t11.middle_category_name,
        t11.major_category_name,
        t11.level,
        t11.base_year,
        t30.created_at AS saved_at
    FROM T11_NCS_UNITS t11
    LEFT JOIN T30_USER_UNIT_SELECTIONS t30
        ON t30.unit_category_id = t11.unit_category_id
       AND t30.user_id = :user_id
    WHERE t11.subcategory_code = ANY(:sub_codes)
      AND coalesce(t11.unit_element_id, '') <> ''
    ORDER BY t11.subcategory_code, t11.unit_category_id, t11.unit_element_id
    """
    with get_connection() as conn:
        rows = conn.execute(
            text(sql),
            {"user_id": user_id, "sub_codes": sub_codes},
        ).mappings().all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(row) for row in rows]).rename(
        columns={
            "selected_yn": "선택여부",
            "unit_category_id": "능력단위분류번호",
            "unit_name": "능력단위명",
            "unit_element_id": "능력단위요소ID",
            "unit_element_name": "능력단위요소명",
            "subcategory_code": "세분류코드",
            "subcategory_name": "세분류명",
            "subcategory_definition": "세분류정의",
            "unit_definition": "능력단위정의",
            "minor_category_name": "소분류명",
            "middle_category_name": "중분류명",
            "major_category_name": "대분류명",
            "level": "수준",
            "base_year": "기준연도",
            "saved_at": "저장일시",
        }
    )


def _fetch_criteria(user_id: int, sub_codes: list[str]) -> pd.DataFrame:
    sql = f"""
    SELECT
        {_SELECTED_CASE},
        (
            SELECT DISTINCT t11.subcategory_code
            FROM T11_NCS_UNITS t11
            WHERE t11.unit_category_id = t12.unit_category_id
            LIMIT 1
        ) AS subcategory_code,
        (
            SELECT DISTINCT t11.subcategory_name
            FROM T11_NCS_UNITS t11
            WHERE t11.unit_category_id = t12.unit_category_id
            LIMIT 1
        ) AS subcategory_name,
        t12.unit_category_id,
        (
            SELECT DISTINCT t11.unit_name
            FROM T11_NCS_UNITS t11
            WHERE t11.unit_category_id = t12.unit_category_id
            LIMIT 1
        ) AS unit_name,
        t12.unit_element_id,
        (
            SELECT DISTINCT t11.unit_element_name
            FROM T11_NCS_UNITS t11
            WHERE t11.unit_category_id = t12.unit_category_id
              AND t11.unit_element_id = t12.unit_element_id
            LIMIT 1
        ) AS unit_element_name,
        t12.criteria_no,
        t12.criteria_text,
        t12.base_year
    FROM T12_PERFORMANCE_CRITERIA t12
    INNER JOIN T11_NCS_UNITS t11_scope
        ON t11_scope.unit_category_id = t12.unit_category_id
       AND t11_scope.subcategory_code = ANY(:sub_codes)
    LEFT JOIN T30_USER_UNIT_SELECTIONS t30
        ON t30.unit_category_id = t12.unit_category_id
       AND t30.user_id = :user_id
    ORDER BY subcategory_code, t12.unit_category_id, t12.unit_element_id, t12.criteria_no
    """
    with get_connection() as conn:
        rows = conn.execute(
            text(sql),
            {"user_id": user_id, "sub_codes": sub_codes},
        ).mappings().all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(row) for row in rows]).rename(
        columns={
            "selected_yn": "선택여부",
            "subcategory_code": "세분류코드",
            "subcategory_name": "세분류명",
            "unit_category_id": "능력단위분류번호",
            "unit_name": "능력단위명",
            "unit_element_id": "능력단위요소ID",
            "unit_element_name": "능력단위요소명",
            "criteria_no": "수행준거번호",
            "criteria_text": "수행준거내용",
            "base_year": "기준연도",
        }
    )
    return _dedupe_dataframe(
        df,
        [
            "세분류코드",
            "세분류명",
            "능력단위분류번호",
            "능력단위명",
            "능력단위요소ID",
            "능력단위요소명",
            "수행준거번호",
            "수행준거내용",
            "기준연도",
        ],
    )


def _fetch_ksa(user_id: int, sub_codes: list[str]) -> pd.DataFrame:
    sql = f"""
    SELECT
        {_SELECTED_CASE},
        (
            SELECT DISTINCT t11.subcategory_code
            FROM T11_NCS_UNITS t11
            WHERE t11.unit_category_id = t13.unit_category_id
            LIMIT 1
        ) AS subcategory_code,
        (
            SELECT DISTINCT t11.subcategory_name
            FROM T11_NCS_UNITS t11
            WHERE t11.unit_category_id = t13.unit_category_id
            LIMIT 1
        ) AS subcategory_name,
        t13.unit_category_id,
        (
            SELECT DISTINCT t11.unit_name
            FROM T11_NCS_UNITS t11
            WHERE t11.unit_category_id = t13.unit_category_id
            LIMIT 1
        ) AS unit_name,
        t13.unit_element_id,
        t13.ksa_type,
        t13.ksa_text,
        t13.base_year
    FROM T13_KSA t13
    INNER JOIN T11_NCS_UNITS t11_scope
        ON t11_scope.unit_category_id = t13.unit_category_id
       AND t11_scope.subcategory_code = ANY(:sub_codes)
    LEFT JOIN T30_USER_UNIT_SELECTIONS t30
        ON t30.unit_category_id = t13.unit_category_id
       AND t30.user_id = :user_id
    ORDER BY subcategory_code, t13.unit_category_id, t13.unit_element_id, t13.id_t13
    """
    with get_connection() as conn:
        rows = conn.execute(
            text(sql),
            {"user_id": user_id, "sub_codes": sub_codes},
        ).mappings().all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(row) for row in rows]).rename(
        columns={
            "selected_yn": "선택여부",
            "subcategory_code": "세분류코드",
            "subcategory_name": "세분류명",
            "unit_category_id": "능력단위분류번호",
            "unit_name": "능력단위명",
            "unit_element_id": "능력단위요소ID",
            "ksa_type": "KSA구분",
            "ksa_text": "KSA내용",
            "base_year": "기준연도",
        }
    )
    return _dedupe_dataframe(
        df,
        [
            "세분류코드",
            "세분류명",
            "능력단위분류번호",
            "능력단위명",
            "능력단위요소ID",
            "KSA구분",
            "KSA내용",
            "기준연도",
        ],
    )


def _fetch_t31_evaluation_sheet(sub_codes: list[str]) -> pd.DataFrame:
    """T31 평가시 주의사항(스코프 내 모든 능력단위). 테이블 미적용 시 빈 DataFrame."""
    sql = """
    SELECT
        t31.unit_category_id,
        COALESCE(NULLIF(trim(t31.unit_name), ''), (
            SELECT DISTINCT t11.unit_name
            FROM T11_NCS_UNITS t11
            WHERE t11.unit_category_id = t31.unit_category_id
            LIMIT 1
        )) AS unit_name,
        t31.item_name AS item_name,
        t31.content_text AS content_text,
        t31.excel_row_no AS excel_row_no
    FROM T31_UNIT_EVALUATION_CONSIDERATIONS t31
    INNER JOIN (
        SELECT DISTINCT unit_category_id
        FROM T11_NCS_UNITS
        WHERE subcategory_code = ANY(:sub_codes)
          AND coalesce(unit_category_id, '') <> ''
    ) scope ON scope.unit_category_id = t31.unit_category_id
    ORDER BY t31.unit_category_id, t31.excel_row_no NULLS LAST, t31.id_t31
    """
    try:
        with get_connection() as conn:
            rows = conn.execute(text(sql), {"sub_codes": sub_codes}).mappings().all()
    except Exception:  # noqa: BLE001 — T31 미생성·스키마 차이
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(row) for row in rows])
    return _dedupe_dataframe(
        df.rename(
            columns={
                "unit_category_id": "능력단위분류번호",
                "unit_name": "능력단위명",
                "item_name": "항목",
                "content_text": "내용",
                "excel_row_no": "원본번호",
            }
        ),
        ["능력단위분류번호", "항목", "내용"],
    )


def _build_job_summary_rows(sub_codes: list[str], selected_ids: set[str]) -> list[dict]:
    rows: list[dict] = []
    for unit_id in _list_unit_ids_in_subcategories(sub_codes):
        data = get_job_description(unit_id)
        if not data:
            continue
        rows.append(
            {
                "선택여부": "Y" if unit_id in selected_ids else "N",
                "능력단위분류번호": data["unit_category_id"],
                "능력단위명": data["unit_name"],
                "직무": data.get("job_title") or "",
                "세분류코드": data.get("subcategory_code") or "",
                "세분류명": data.get("subcategory_name") or "",
                "대분류명": data.get("major_category_name") or "",
                "중분류명": data.get("middle_category_name") or "",
                "소분류명": data.get("minor_category_name") or "",
                "수준": data.get("level") or "",
                "직무목적": data.get("job_purpose") or "",
                "개발날짜": data.get("development_date") or "",
                "개발기관": data.get("development_org") or "",
                "요소수": len(data.get("elements") or []),
                "지식건수": len(data.get("knowledge") or []),
                "기술건수": len(data.get("skills") or []),
                "태도건수": len(data.get("attitudes") or []),
            }
        )
    return rows


def _build_matrix_rows(user_id: int) -> list[dict]:
    matrix = get_user_units_matrix(user_id)
    rows: list[dict] = []
    for unit in matrix.get("units") or []:
        rows.append(
            {
                "세분류코드": unit.get("subcategory_code") or "",
                "세분류명": unit.get("subcategory_name") or "",
                "수준": unit.get("level") or "",
                "능력단위분류번호": unit.get("unit_category_id") or "",
                "능력단위명": unit.get("unit_name") or "",
                "선택여부": "Y" if unit.get("selected") else "N",
            }
        )
    return rows


def _build_meta_rows(
    user: dict,
    sub_codes: list[str],
    selected_count: int,
    total_unit_count: int,
    element_count: int,
) -> list[dict]:
    now = datetime.now(timezone.utc).astimezone()
    return [
        {"항목": "생성일시", "값": now.strftime("%Y-%m-%d %H:%M:%S")},
        {"항목": "이메일", "값": user.get("email") or ""},
        {"항목": "이름", "값": user.get("full_name") or ""},
        {"항목": "기업명", "값": user.get("company_name") or ""},
        {"항목": "부서명", "값": user.get("department_name") or ""},
        {"항목": "표시세분류수", "값": len(sub_codes)},
        {"항목": "표시세분류코드", "값": ", ".join(sub_codes)},
        {"항목": "세분류내전체능력단위수", "값": total_unit_count},
        {"항목": "내가선택한능력단위수", "값": selected_count},
        {"항목": "능력단위요소행수", "값": element_count},
        {"항목": "개발기관표기", "값": os.getenv("JOB_DESCRIPTION_ORG", "NCS Search")},
        {
            "항목": "데이터범위",
            "값": "모든 시트: 저장 능력단위가 속한 세분류 전체, 선택여부 Y/N=내 선택",
        },
        {
            "항목": "데이터출처",
            "값": "T11/T12/T13/T14/T15/T31, T30(선택여부·선택_정의요약·평가시주의사항)",
        },
    ]


def build_export_content_disposition(ascii_filename: str, display_filename: str | None = None) -> str:
    """HTTP 헤더용 파일명 (latin-1 제한 회피: ASCII filename + UTF-8 filename*)."""
    safe_ascii = "".join(ch for ch in ascii_filename if ord(ch) < 128) or "ncs_units_export.xlsx"
    if display_filename and display_filename != safe_ascii:
        encoded = quote(display_filename, safe="")
        return f"attachment; filename=\"{safe_ascii}\"; filename*=UTF-8''{encoded}"
    return f'attachment; filename="{safe_ascii}"'


def _export_filenames(user: dict) -> tuple[str, str]:
    date_tag = datetime.now().strftime("%Y%m%d")
    company = str(user.get("company_name") or "").strip()
    ascii_filename = f"ncs_units_export_{date_tag}.xlsx"
    display_filename = f"NCS_능력단위_{company}_{date_tag}.xlsx" if company else ascii_filename
    return ascii_filename, display_filename


def build_user_units_excel(user_id: int) -> tuple[bytes, str, str]:
    """
    저장한 능력단위 기준으로 엑셀을 만든다.

    - **선택_정의요약**: 내가 선택한 능력단위만 행으로, T14 세분류정의·T15 능력단위정의 포함.
    - **선택요소_상세** 이하: 저장 능력단위가 속한 세분류의 전체 요소·준거 등(선택여부 Y/N).
      상세 시트에도 동일 정의 컬럼을 붙인다.
    - **수행준거 / KSA**: 수준 컬럼 제외, 동일 행은 중복 제거(선택여부 Y 우선).
    - **평가시주의사항**: 스코프 내 T31(미적재 시 안내 시트만).
    """
    sub_codes, selected_ids = _resolve_export_scope(user_id)
    user = get_user_by_id(user_id) or {}

    df_selected_defs = _fetch_selected_definition_rows(user_id)
    df_elements = _fetch_elements(user_id, sub_codes)
    df_criteria = _fetch_criteria(user_id, sub_codes)
    df_ksa = _fetch_ksa(user_id, sub_codes)
    df_eval_sheet = _fetch_t31_evaluation_sheet(sub_codes)
    df_jobs = pd.DataFrame(_build_job_summary_rows(sub_codes, selected_ids))
    df_matrix = pd.DataFrame(_build_matrix_rows(user_id))
    total_units = _count_units_in_subcategories(sub_codes)
    df_meta = pd.DataFrame(
        _build_meta_rows(user, sub_codes, len(selected_ids), total_units, len(df_elements))
    )

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        sheets: list[tuple[str, pd.DataFrame]] = [
            ("선택_정의요약", df_selected_defs),
            ("선택요소_상세", df_elements),
            ("수행준거", df_criteria),
            ("KSA", df_ksa),
            ("평가시주의사항", df_eval_sheet),
            ("직무기술서_요약", df_jobs),
            ("구조도_매핑", df_matrix),
            ("다운로드_정보", df_meta),
        ]
        for sheet_name, frame in sheets:
            if frame.empty:
                pd.DataFrame([{"안내": "해당 데이터가 없습니다."}]).to_excel(
                    writer, sheet_name=sheet_name, index=False
                )
            else:
                frame.to_excel(writer, sheet_name=sheet_name, index=False)

    buffer.seek(0)
    ascii_filename, display_filename = _export_filenames(user)
    return buffer.getvalue(), ascii_filename, display_filename
