from __future__ import annotations

from collections import defaultdict

from sqlalchemy import text

from app.db import get_connection

# 평가시 고려사항 항목(엑셀 「항목」)을 표시 섹션으로 묶는다.
_SECTION_HEADINGS = ("적용범위 및 관련 서류", "자료 및 관련 서류", "평가시 고려사항")


def _section_heading_for_item(item_name: str) -> str:
    name = str(item_name or "").strip()
    if "적용범위" in name:
        return _SECTION_HEADINGS[0]
    if "자료" in name:
        return _SECTION_HEADINGS[1]
    if "평가" in name and "고려" in name:
        return _SECTION_HEADINGS[2]
    # 기타 항목은 자체 텍스트로 표시하지 않고 → 마지막 섹션 뒤에 붙일 수 없으므로 "기타"
    return "기타 참고사항"


def evaluation_sections_dict(unit_category_id: str) -> dict[str, list[str]]:
    """
    능력단위별 T31 행을 UI 섹션(적용범위·자료·평가 고려 등)별 bullet 목록으로 변환한다.
    테이블이 없거나 오류 시 빈 dict.
    """
    uid = unit_category_id.strip()
    if not uid:
        return {}

    sql = """
    SELECT item_name, content_text
    FROM T31_UNIT_EVALUATION_CONSIDERATIONS
    WHERE unit_category_id = :unit_category_id
    ORDER BY excel_row_no NULLS LAST, id_t31 ASC
    """
    bullets_by_section: defaultdict[str, list[str]] = defaultdict(list)
    try:
        with get_connection() as conn:
            rows = conn.execute(text(sql), {"unit_category_id": uid}).mappings().all()
    except Exception:  # noqa: BLE001 — 테이블 미생성·권한 등
        return {}

    for row in rows:
        txt = str(row.get("content_text") or "").strip()
        if not txt:
            continue
        heading = _section_heading_for_item(str(row.get("item_name") or ""))
        if heading == "기타 참고사항":
            bullets_by_section[heading].append(
                f"{str(row.get('item_name') or '').strip()}: {txt}" if row.get("item_name") else txt
            )
        else:
            bullets_by_section[heading].append(txt)

    return {k: bullets_by_section[k] for k in bullets_by_section}


def evaluation_sections_for_response(unit_category_id: str) -> list[dict[str, str | list[str]]]:
    """JobDescriptionResponse.evaluation_sections 용: [{title, items}, ...] 고정 순서."""
    d = evaluation_sections_dict(unit_category_id)
    out: list[dict[str, str | list[str]]] = []
    for title in _SECTION_HEADINGS:
        items = d.get(title) or []
        if items:
            out.append({"title": title, "items": items})
    other = d.get("기타 참고사항") or []
    if other:
        out.append({"title": "기타 참고사항", "items": other})
    return out
