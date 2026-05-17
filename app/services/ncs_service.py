from __future__ import annotations

import csv
import io

from sqlalchemy import text

from app.db import get_connection


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
    ORDER BY
        major_category_name,
        middle_category_name,
        minor_category_name,
        subcategory_code
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

    return list(major_map.values())


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
