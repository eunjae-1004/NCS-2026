from __future__ import annotations

import re


ACTION_SUFFIXES = ("수립", "작성", "관리", "운영", "기획", "분석", "평가", "검토", "개선")
ACTION_SYNONYMS = {
    "수립": ("수립", "작성"),
    "작성": ("작성", "수립"),
    "기획": ("기획", "수립"),
    "검토": ("검토", "분석"),
    "개선": ("개선", "보완"),
}


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


def _split_compound_action_token(token: str) -> list[str]:
    """
    공백 없이 붙여 쓴 업무명(예: 사업계획작성)을
    [사업계획, 작성] 형태로 분해해 검색 recall을 높인다.
    """
    for suffix in ACTION_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix) + 1:
            stem = token[: -len(suffix)]
            return [stem, suffix]
    return [token]


def _expand_action_synonyms(tokens: list[str]) -> list[str]:
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        for synonym in ACTION_SYNONYMS.get(token, ()):
            expanded.append(synonym)

    # 순서 유지 중복 제거
    seen: set[str] = set()
    out: list[str] = []
    for token in expanded:
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def build_query_variants(normalized_query: str) -> list[str]:
    """
    공백 없는 복합 질의의 검색 변형을 생성한다.
    예) 사업계획작성 -> ["사업계획작성", "사업계획 작성"]
    """
    variants = [normalized_query.strip()]
    raw_tokens = [token for token in normalized_query.split(" ") if token]
    if len(raw_tokens) == 1:
        split_tokens = _split_compound_action_token(raw_tokens[0])
        if len(split_tokens) >= 2:
            variants.append(" ".join(split_tokens))

    seen: set[str] = set()
    out: list[str] = []
    for item in variants:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def extract_keywords(normalized_query: str) -> list[str]:
    """
    단순 공백 분리 기반 키워드 추출.
    """
    raw_tokens = [token for token in normalized_query.split(" ") if token]

    split_tokens: list[str] = []
    for token in raw_tokens:
        split_tokens.extend(_split_compound_action_token(token))

    return _expand_action_synonyms(split_tokens)
