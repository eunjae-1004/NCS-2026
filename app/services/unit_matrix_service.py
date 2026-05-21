from __future__ import annotations

from sqlalchemy import text

from app.db import get_connection
from app.services.ncs_service import get_unit_ncs_meta
from app.services.user_service import list_user_unit_selections


def suggest_minor_category_for_user(user_id: int) -> str | None:
    """저장된 능력단위가 많은 소분류(분야)를 반환한다."""
    sql = """
    SELECT t11.minor_category_name, COUNT(*) AS cnt, MAX(t30.created_at) AS last_saved
    FROM T30_USER_UNIT_SELECTIONS t30
    INNER JOIN T11_NCS_UNITS t11 ON t11.unit_category_id = t30.unit_category_id
    WHERE t30.user_id = :user_id
      AND coalesce(t11.minor_category_name, '') <> ''
    GROUP BY t11.minor_category_name
    ORDER BY cnt DESC, last_saved DESC
    LIMIT 1
    """
    with get_connection() as conn:
        row = conn.execute(text(sql), {"user_id": user_id}).mappings().first()
    if row:
        return str(row["minor_category_name"])

    fallback_sql = """
    SELECT t11.minor_category_name, COUNT(*) AS cnt
    FROM T30_USER_UNIT_SELECTIONS t30
    INNER JOIN T11_NCS_UNITS t11 ON t11.subcategory_code = t30.subcategory_code
    WHERE t30.user_id = :user_id
      AND coalesce(t11.minor_category_name, '') <> ''
    GROUP BY t11.minor_category_name
    ORDER BY cnt DESC
    LIMIT 1
    """
    with get_connection() as conn:
        row = conn.execute(text(fallback_sql), {"user_id": user_id}).mappings().first()
    return str(row["minor_category_name"]) if row else None


def list_minor_categories() -> list[str]:
    sql = """
    SELECT DISTINCT minor_category_name
    FROM T11_NCS_UNITS
    WHERE coalesce(minor_category_name, '') <> ''
    ORDER BY minor_category_name
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql)).scalars().all()
    return [str(name) for name in rows]


def get_user_units_matrix(user_id: int) -> dict:
    """
    회원이 저장한 능력단위가 있는 세분류만 열로 구성한 구조도 데이터.
    각 세분류 열에는 해당 세분류의 전체 능력단위를 표시한다.
    """
    selections = list_user_unit_selections(user_id)
    if not selections:
        return _empty_matrix_response()

    selected_ids: set[str] = set()
    subcategory_map: dict[str, str] = {}

    for item in selections:
        unit_id = str(item.get("unit_category_id") or "").strip()
        if unit_id:
            selected_ids.add(unit_id)

        meta = get_unit_ncs_meta(unit_id) if unit_id else None
        sub_code = str((meta or item).get("subcategory_code") or "").strip()
        sub_name = str((meta or item).get("subcategory_name") or "").strip()
        if sub_code:
            subcategory_map[sub_code] = sub_name or sub_code

    sub_codes = sorted(subcategory_map.keys())
    if not sub_codes:
        return _empty_matrix_response()

    sql = """
    SELECT DISTINCT ON (unit_category_id)
        subcategory_code,
        subcategory_name,
        unit_category_id,
        unit_name,
        level
    FROM T11_NCS_UNITS
    WHERE subcategory_code = ANY(:sub_codes)
      AND coalesce(unit_category_id, '') <> ''
    ORDER BY unit_category_id, id_t11
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql), {"sub_codes": sub_codes}).mappings().all()

    level_set: set[int] = set()
    units: list[dict] = []
    name_by_code = dict(subcategory_map)

    for row in rows:
        sub_code = str(row["subcategory_code"] or "").strip()
        if not sub_code:
            continue
        sub_name = str(row["subcategory_name"] or name_by_code.get(sub_code) or sub_code)
        name_by_code[sub_code] = sub_name

        level_raw = str(row["level"] or "").strip()
        level_num = _parse_level(level_raw)
        if level_num is not None:
            level_set.add(level_num)

        unit_id = str(row["unit_category_id"] or "").strip()
        units.append(
            {
                "subcategory_code": sub_code,
                "subcategory_name": sub_name,
                "unit_category_id": unit_id,
                "unit_name": str(row["unit_name"] or ""),
                "level": level_raw or str(level_num or ""),
                "level_num": level_num,
                "selected": unit_id in selected_ids,
            }
        )

    subcategories = [
        {"subcategory_code": code, "subcategory_name": name_by_code[code]}
        for code in sub_codes
    ]
    levels = [str(level) for level in sorted(level_set, reverse=True)]

    return {
        "minor_category_name": None,
        "subcategories": subcategories,
        "levels": levels,
        "units": units,
        "total_units": len(units),
    }


def _empty_matrix_response() -> dict:
    return {
        "minor_category_name": None,
        "subcategories": [],
        "levels": [],
        "units": [],
        "total_units": 0,
    }


def get_units_matrix(minor_category_name: str, user_id: int | None = None) -> dict:
    sql = """
    SELECT DISTINCT ON (unit_category_id)
        subcategory_code,
        subcategory_name,
        unit_category_id,
        unit_name,
        level
    FROM T11_NCS_UNITS
    WHERE minor_category_name = :minor_category_name
      AND coalesce(subcategory_code, '') <> ''
      AND coalesce(unit_category_id, '') <> ''
    ORDER BY unit_category_id, id_t11
    """
    with get_connection() as conn:
        rows = conn.execute(
            text(sql),
            {"minor_category_name": minor_category_name},
        ).mappings().all()

    selected_ids: set[str] = set()
    if user_id and user_id > 0:
        for item in list_user_unit_selections(user_id):
            selected_ids.add(str(item["unit_category_id"]))

    subcategory_map: dict[str, str] = {}
    level_set: set[int] = set()
    units: list[dict] = []

    for row in rows:
        sub_code = str(row["subcategory_code"] or "").strip()
        if not sub_code:
            continue
        sub_name = str(row["subcategory_name"] or sub_code)
        subcategory_map[sub_code] = sub_name

        level_raw = str(row["level"] or "").strip()
        level_num = _parse_level(level_raw)
        if level_num is not None:
            level_set.add(level_num)

        unit_id = str(row["unit_category_id"] or "").strip()
        units.append(
            {
                "subcategory_code": sub_code,
                "subcategory_name": sub_name,
                "unit_category_id": unit_id,
                "unit_name": str(row["unit_name"] or ""),
                "level": level_raw or str(level_num or ""),
                "level_num": level_num,
                "selected": unit_id in selected_ids,
            }
        )

    subcategories = [
        {"subcategory_code": code, "subcategory_name": subcategory_map[code]}
        for code in sorted(subcategory_map.keys())
    ]
    levels = [str(level) for level in sorted(level_set, reverse=True)]

    return {
        "minor_category_name": minor_category_name,
        "subcategories": subcategories,
        "levels": levels,
        "units": units,
        "total_units": len(units),
    }


def _parse_level(value: str) -> int | None:
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None
