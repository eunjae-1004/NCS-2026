from __future__ import annotations

import re


def normalize_query(text: str) -> str:
    """
    검색용 입력 정규화:
    - 소문자 변환
    - 특수문자 제거
    - 다중 공백 축소
    """
    value = text.lower().strip()
    value = re.sub(r"[^0-9a-zA-Z가-힣\s]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def extract_keywords(normalized_query: str) -> list[str]:
    """
    단순 공백 분리 기반 키워드 추출.
    """
    return [token for token in normalized_query.split(" ") if token]
