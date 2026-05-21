from __future__ import annotations

import os
import re

from sqlalchemy import text

from app.db import get_connection


def _normalize_ksa_bucket(ksa_type: str) -> str:
    raw = str(ksa_type or "").strip()
    lower = raw.lower()
    if "지식" in raw or "knowledge" in lower or lower in {"k", "know"}:
        return "knowledge"
    if "기술" in raw or "skill" in lower or lower in {"s", "skills"}:
        return "skills"
    if "태도" in raw or "attitude" in lower or lower in {"a", "att"}:
        return "attitudes"
    return "other"


def _criteria_sort_key(criteria_no: str) -> tuple:
    parts = re.findall(r"\d+", str(criteria_no or ""))
    if not parts:
        return (9999,)
    return tuple(int(p) for p in parts)


def get_job_description(unit_category_id: str) -> dict | None:
    """
    NCS T11/T12/T13/T15 기반 직무기술서 데이터를 조합한다.
    """
    uid = unit_category_id.strip()
    if not uid:
        return None

    org_name = os.getenv("JOB_DESCRIPTION_ORG", "NCS Search")

    sql_meta = """
    SELECT
        unit_category_id,
        unit_name,
        subcategory_code,
        subcategory_name,
        minor_category_name,
        middle_category_name,
        major_category_name,
        base_year
    FROM T11_NCS_UNITS
    WHERE unit_category_id = :unit_category_id
    ORDER BY id_t11
    LIMIT 1
    """
    sql_definition = """
    SELECT unit_definition, level, base_year
    FROM T15_UNIT_DEFINITIONS
    WHERE unit_category_id = :unit_category_id
    ORDER BY id_t15
    LIMIT 1
    """
    sql_elements = """
    SELECT DISTINCT unit_element_id, unit_element_name
    FROM T11_NCS_UNITS
    WHERE unit_category_id = :unit_category_id
      AND coalesce(unit_element_id, '') <> ''
    ORDER BY unit_element_id
    """
    sql_criteria = """
    SELECT unit_element_id, criteria_no, criteria_text
    FROM T12_PERFORMANCE_CRITERIA
    WHERE unit_category_id = :unit_category_id
    ORDER BY unit_element_id, criteria_no
    """
    sql_ksa = """
    SELECT ksa_type, ksa_text
    FROM T13_KSA
    WHERE unit_category_id = :unit_category_id
    ORDER BY id_t13
    """

    with get_connection() as conn:
        meta = conn.execute(text(sql_meta), {"unit_category_id": uid}).mappings().first()
        if not meta:
            return None

        definition = conn.execute(text(sql_definition), {"unit_category_id": uid}).mappings().first()
        elements = conn.execute(text(sql_elements), {"unit_category_id": uid}).mappings().all()
        criteria_rows = conn.execute(text(sql_criteria), {"unit_category_id": uid}).mappings().all()
        ksa_rows = conn.execute(text(sql_ksa), {"unit_category_id": uid}).mappings().all()

    criteria_by_element: dict[str, list[dict]] = {}
    for row in criteria_rows:
        eid = str(row["unit_element_id"] or "")
        text_value = str(row["criteria_text"] or "").strip()
        if not eid or not text_value:
            continue
        criteria_by_element.setdefault(eid, []).append(
            {
                "criteria_no": str(row["criteria_no"] or "").strip(),
                "text": text_value,
            }
        )

    element_payload: list[dict] = []
    for element in elements:
        eid = str(element["unit_element_id"] or "")
        responsibilities = criteria_by_element.get(eid, [])
        responsibilities.sort(key=lambda item: _criteria_sort_key(item["criteria_no"]))
        element_payload.append(
            {
                "unit_element_id": eid,
                "unit_element_name": str(element["unit_element_name"] or "").strip(),
                "responsibilities": responsibilities,
            }
        )

    knowledge: list[str] = []
    skills: list[str] = []
    attitudes: list[str] = []
    other_ksa: list[str] = []

    for row in ksa_rows:
        text_value = str(row["ksa_text"] or "").strip()
        if not text_value:
            continue
        bucket = _normalize_ksa_bucket(str(row["ksa_type"] or ""))
        if bucket == "knowledge":
            knowledge.append(text_value)
        elif bucket == "skills":
            skills.append(text_value)
        elif bucket == "attitudes":
            attitudes.append(text_value)
        else:
            other_ksa.append(text_value)

    if other_ksa:
        knowledge.extend(other_ksa)

    base_year = str((definition or meta).get("base_year") or "").strip()
    development_date = f"{base_year}-01-01" if re.fullmatch(r"\d{4}", base_year) else None

    job_title = str(meta.get("subcategory_name") or meta.get("minor_category_name") or "").strip()

    return {
        "unit_category_id": str(meta["unit_category_id"]),
        "unit_name": str(meta.get("unit_name") or ""),
        "job_title": job_title,
        "subcategory_code": str(meta.get("subcategory_code") or ""),
        "subcategory_name": str(meta.get("subcategory_name") or ""),
        "major_category_name": str(meta.get("major_category_name") or ""),
        "middle_category_name": str(meta.get("middle_category_name") or ""),
        "minor_category_name": str(meta.get("minor_category_name") or ""),
        "job_purpose": str(definition.get("unit_definition") or "").strip() if definition else "",
        "level": str(definition.get("level") or meta.get("level") or "").strip() if definition else "",
        "development_date": development_date,
        "development_org": org_name,
        "elements": element_payload,
        "knowledge": knowledge,
        "skills": skills,
        "attitudes": attitudes,
    }
