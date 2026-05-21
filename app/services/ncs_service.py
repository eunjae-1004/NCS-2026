from __future__ import annotations

import csv
import io

from sqlalchemy import text

from app.db import get_connection


def get_unit_ncs_meta(unit_category_id: str) -> dict | None:
    """
    능력단위 ID 기준 세분류·계층 메타 (T11 우선, T25 보조).
    """
    uid = unit_category_id.strip()
    if not uid:
        return None

    sql_t11 = """
    SELECT
        unit_category_id,
        unit_name,
        subcategory_code,
        subcategory_name,
        major_category_name,
        middle_category_name,
        minor_category_name
    FROM T11_NCS_UNITS
    WHERE unit_category_id = :unit_category_id
    ORDER BY id_t11
    LIMIT 1
    """
    with get_connection() as conn:
        row = conn.execute(text(sql_t11), {"unit_category_id": uid}).mappings().first()
        if row:
            return dict(row)

        sql_t25 = """
        SELECT
            unit_category_id,
            unit_name,
            subcategory_code,
            subcategory_name,
            major_category_name,
            middle_category_name,
            minor_category_name
        FROM T25_NCS_SEARCH_INDEX
        WHERE unit_category_id = :unit_category_id
        ORDER BY search_index_id ASC
        LIMIT 1
        """
        row = conn.execute(text(sql_t25), {"unit_category_id": uid}).mappings().first()
    return dict(row) if row else None


def get_ncs_tree() -> list[dict]:
    sql = """
    SELECT DISTINCT
        major_category_name,
        middle_category_name,
        minor_category_name,
        subcategory_code,
        subcategory_name
    FROM T25_NCS_SEARCH_INDEX
    WHERE coalesce(major_category_name, '') <> ''
      AND coalesce(middle_category_name, '') <> ''
      AND coalesce(minor_category_name, '') <> ''
      AND coalesce(subcategory_code, '') <> ''
      AND coalesce(subcategory_name, '') <> ''
    ORDER BY subcategory_code
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql)).mappings().all()

    major_map: dict[str, dict] = {}
    middle_map: dict[tuple[str, str], dict] = {}
    minor_map: dict[tuple[str, str, str], dict] = {}

    for row in rows:
        major = row["major_category_name"]
        middle = row["middle_category_name"]
        minor = row["minor_category_name"]
        sub_code = row["subcategory_code"]
        sub_name = row["subcategory_name"]

        if major not in major_map:
            major_map[major] = {"code": major, "name": major, "children": []}

        middle_key = (major, middle)
        if middle_key not in middle_map:
            middle_node = {"code": middle, "name": middle, "children": []}
            middle_map[middle_key] = middle_node
            major_map[major]["children"].append(middle_node)

        minor_key = (major, middle, minor)
        if minor_key not in minor_map:
            minor_node = {"code": minor, "name": minor, "children": []}
            minor_map[minor_key] = minor_node
            middle_map[middle_key]["children"].append(minor_node)

        minor_map[minor_key]["children"].append({"code": sub_code, "name": sub_name})

    tree = list(major_map.values())
    _sort_ncs_tree_by_code(tree)
    return tree


def _ncs_tree_sort_key(node: dict) -> str:
    """대/중/소/세 계층을 세분류 코드(subcategory_code) 기준 오름차순으로 정렬한다."""
    code = str(node.get("code") or "").strip()
    if code.isdigit():
        return code.zfill(8)
    children = node.get("children") or []
    if children:
        return min(_ncs_tree_sort_key(child) for child in children)
    return code


def _sort_ncs_tree_by_code(nodes: list[dict]) -> None:
    nodes.sort(key=_ncs_tree_sort_key)
    for node in nodes:
        children = node.get("children")
        if children:
            _sort_ncs_tree_by_code(children)


def get_unit_structure(unit_category_id: str) -> dict | None:
    sql = """
    SELECT
        unit_category_id,
        unit_name,
        subcategory_code,
        subcategory_name,
        unit_element_id,
        unit_element_name,
        performance_criteria_text
    FROM T25_NCS_SEARCH_INDEX
    WHERE unit_category_id = :unit_category_id
    ORDER BY unit_element_id
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql), {"unit_category_id": unit_category_id}).mappings().all()

    if not rows:
        return None

    elements = []
    for row in rows:
        criteria = str(row["performance_criteria_text"] or "").strip()
        criteria_items = [item.strip() for item in criteria.split(".") if item.strip()][:3]
        elements.append(
            {
                "unit_element_id": row["unit_element_id"],
                "unit_element_name": row["unit_element_name"],
                "performance_criteria": criteria_items,
            }
        )

    return {
        "unit_category_id": rows[0]["unit_category_id"],
        "unit_name": rows[0]["unit_name"],
        "subcategory_code": rows[0]["subcategory_code"],
        "subcategory_name": rows[0]["subcategory_name"],
        "elements": elements,
    }


def export_basic_ncs_csv() -> io.StringIO:
    sql = """
    SELECT
        subcategory_code,
        subcategory_name,
        unit_category_id,
        unit_name,
        unit_element_id,
        unit_element_name
    FROM T25_NCS_SEARCH_INDEX
    ORDER BY subcategory_code, unit_category_id, unit_element_id
    """
    with get_connection() as conn:
        rows = conn.execute(text(sql)).mappings().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "subcategory_code",
            "subcategory_name",
            "unit_category_id",
            "unit_name",
            "unit_element_id",
            "unit_element_name",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["subcategory_code"],
                row["subcategory_name"],
                row["unit_category_id"],
                row["unit_name"],
                row["unit_element_id"],
                row["unit_element_name"],
            ]
        )
    output.seek(0)
    return output
