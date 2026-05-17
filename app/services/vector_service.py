from __future__ import annotations


def vector_search(normalized_query: str, top_k: int) -> list[dict]:
    """
    향후 pgvector 검색 확장을 위한 자리.
    현재 단계에서는 실제 벡터 검색을 수행하지 않는다.
    """
    _ = (normalized_query, top_k)
    return []
