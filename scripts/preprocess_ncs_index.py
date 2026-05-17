from __future__ import annotations

import logging
import os
import re
import traceback
from dataclasses import dataclass
from typing import Callable, TypeVar

import pandas as pd
import psycopg2  # noqa: F401  # psycopg2 드라이버 사용 명시
from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine

T = TypeVar("T")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("ncs-preprocess")


@dataclass
class DbSettings:
    host: str
    port: str
    dbname: str
    user: str
    password: str


def run_step(step_name: str, fn: Callable[[], T]) -> T:
    """
    단계별 실행 공통 래퍼.
    오류가 나면 어떤 단계에서 실패했는지 상세 로그를 남긴다.
    """
    logger.info("[START] %s", step_name)
    try:
        result = fn()
        logger.info("[DONE] %s", step_name)
        return result
    except Exception as exc:
        logger.error("[ERROR] %s", step_name)
        logger.error("error_message=%s", str(exc))
        logger.error("traceback=\n%s", traceback.format_exc())
        raise


def load_db_settings() -> DbSettings:
    load_dotenv()
    return DbSettings(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "ncs_search"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )


def create_db_engine() -> Engine:
    cfg = load_db_settings()
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=cfg.user,
        password=cfg.password,
        host=cfg.host,
        port=int(cfg.port),
        database=cfg.dbname,
    )
    return create_engine(url, future=True)


def fetch_source_tables(engine: Engine) -> dict[str, pd.DataFrame]:
    def _read(query: str) -> pd.DataFrame:
        return pd.read_sql_query(text(query), con=engine)

    return {
        "t11": _read("SELECT * FROM T11_NCS_UNITS"),
        "t12": _read("SELECT * FROM T12_PERFORMANCE_CRITERIA"),
        "t13": _read("SELECT * FROM T13_KSA"),
        "t14": _read("SELECT * FROM T14_SUBCATEGORY_DEFINITIONS"),
        "t15": _read("SELECT * FROM T15_UNIT_DEFINITIONS"),
    }


def join_unique_text(values: pd.Series) -> str:
    cleaned = [str(v).strip() for v in values if pd.notna(v) and str(v).strip()]
    # 순서를 유지하면서 중복 제거
    dedup = list(dict.fromkeys(cleaned))
    return " ".join(dedup)


def preprocess_performance_criteria(t12: pd.DataFrame) -> pd.DataFrame:
    if t12.empty:
        return pd.DataFrame(
            columns=[
                "unit_element_id",
                "unit_category_id",
                "performance_criteria_text",
            ]
        )

    grouped = (
        t12.groupby(["unit_element_id", "unit_category_id"], dropna=False)["criteria_text"]
        .apply(join_unique_text)
        .reset_index(name="performance_criteria_text")
    )
    return grouped


def classify_ksa_type(raw_type: object) -> str:
    value = str(raw_type or "").strip().lower()
    if any(token in value for token in ["knowledge", "지식", "k"]):
        return "knowledge_text"
    if any(token in value for token in ["skill", "기술", "s"]):
        return "skill_text"
    if any(token in value for token in ["attitude", "태도", "a"]):
        return "attitude_text"
    # 분류 불명 값은 지식으로 우선 수용한다.
    return "knowledge_text"


def preprocess_ksa(t13: pd.DataFrame) -> pd.DataFrame:
    if t13.empty:
        return pd.DataFrame(
            columns=[
                "unit_element_id",
                "unit_category_id",
                "knowledge_text",
                "skill_text",
                "attitude_text",
            ]
        )

    work = t13.copy()
    work["ksa_bucket"] = work["ksa_type"].apply(classify_ksa_type)

    grouped = (
        work.groupby(["unit_element_id", "unit_category_id", "ksa_bucket"], dropna=False)["ksa_text"]
        .apply(join_unique_text)
        .reset_index()
    )

    pivot = grouped.pivot_table(
        index=["unit_element_id", "unit_category_id"],
        columns="ksa_bucket",
        values="ksa_text",
        aggfunc="first",
    ).reset_index()

    for col in ["knowledge_text", "skill_text", "attitude_text"]:
        if col not in pivot.columns:
            pivot[col] = ""

    return pivot[
        [
            "unit_element_id",
            "unit_category_id",
            "knowledge_text",
            "skill_text",
            "attitude_text",
        ]
    ]


def normalize_text(text_value: object) -> str:
    text_str = str(text_value or "")
    text_str = text_str.lower()
    text_str = re.sub(r"[^0-9a-zA-Z가-힣\s]", " ", text_str)
    text_str = re.sub(r"\s+", " ", text_str)
    return text_str.strip()


def build_subcategory_texts(merged: pd.DataFrame) -> pd.DataFrame:
    cols_for_subcategory = [
        "subcategory_name",
        "subcategory_definition",
        "unit_name",
        "unit_element_name",
        "performance_criteria_text",
        "knowledge_text",
        "skill_text",
        "attitude_text",
    ]

    agg_source = merged.copy()
    for col in cols_for_subcategory:
        if col not in agg_source.columns:
            agg_source[col] = ""
        agg_source[col] = agg_source[col].fillna("")

    subcategory_search = (
        agg_source.groupby("subcategory_code", dropna=False)[cols_for_subcategory]
        .agg(join_unique_text)
        .reset_index()
    )
    subcategory_search["subcategory_search_text"] = subcategory_search[cols_for_subcategory].agg(
        " ".join, axis=1
    )
    subcategory_search["subcategory_search_text"] = subcategory_search["subcategory_search_text"].apply(
        normalize_text
    )

    # 세분류명 + 대표 능력단위명(최대 3개) 중심 키워드 생성
    unit_names = (
        agg_source.groupby("subcategory_code", dropna=False)["unit_name"]
        .apply(lambda s: " ".join(list(dict.fromkeys([str(v).strip() for v in s if str(v).strip()]))[:3]))
        .reset_index(name="top_unit_names")
    )

    subcategory_keywords = (
        agg_source.groupby("subcategory_code", dropna=False)["subcategory_name"]
        .apply(join_unique_text)
        .reset_index(name="subcategory_name_for_keyword")
        .merge(unit_names, on="subcategory_code", how="left")
    )
    subcategory_keywords["subcategory_keyword_text"] = (
        subcategory_keywords["subcategory_name_for_keyword"].fillna("")
        + " "
        + subcategory_keywords["top_unit_names"].fillna("")
    ).apply(normalize_text)

    out = subcategory_search[["subcategory_code", "subcategory_search_text"]].merge(
        subcategory_keywords[["subcategory_code", "subcategory_keyword_text"]],
        on="subcategory_code",
        how="left",
    )
    return out


def build_t25_dataframe(source: dict[str, pd.DataFrame]) -> pd.DataFrame:
    t11 = source["t11"].copy()
    t12 = source["t12"]
    t13 = source["t13"]
    t14 = source["t14"].copy()
    t15 = source["t15"].copy()

    t12_agg = preprocess_performance_criteria(t12)
    t13_agg = preprocess_ksa(t13)

    merged = (
        t11.merge(
            t12_agg,
            on=["unit_element_id", "unit_category_id"],
            how="left",
        )
        .merge(
            t13_agg,
            on=["unit_element_id", "unit_category_id"],
            how="left",
        )
        .merge(
            t14[["subcategory_code", "subcategory_definition"]],
            on="subcategory_code",
            how="left",
        )
        .merge(
            t15[["unit_category_id", "unit_definition"]],
            on="unit_category_id",
            how="left",
        )
    )

    text_cols = [
        "major_category_name",
        "middle_category_name",
        "minor_category_name",
        "subcategory_name",
        "unit_name",
        "unit_element_name",
        "unit_definition",
        "subcategory_definition",
        "performance_criteria_text",
        "knowledge_text",
        "skill_text",
        "attitude_text",
    ]
    for col in text_cols:
        if col not in merged.columns:
            merged[col] = ""
        merged[col] = merged[col].fillna("")

    merged["integrated_search_text"] = merged[text_cols].agg(" ".join, axis=1)
    merged["normalized_search_text"] = merged["integrated_search_text"].apply(normalize_text)

    # 핵심 키워드(세분류명, 능력단위명, 능력단위요소명)
    merged["keyword_text"] = (
        merged["subcategory_name"].fillna("")
        + " "
        + merged["unit_name"].fillna("")
        + " "
        + merged["unit_element_name"].fillna("")
    ).apply(normalize_text)

    subcategory_text_df = build_subcategory_texts(merged)
    merged = merged.merge(subcategory_text_df, on="subcategory_code", how="left")
    merged["subcategory_search_text"] = merged["subcategory_search_text"].fillna("")
    merged["subcategory_keyword_text"] = merged["subcategory_keyword_text"].fillna("")

    t25 = pd.DataFrame(
        {
            "id_t11": merged["id_t11"],
            "unit_category_id": merged["unit_category_id"],
            "unit_element_id": merged["unit_element_id"],
            "subcategory_code": merged["subcategory_code"],
            "major_category_name": merged["major_category_name"],
            "middle_category_name": merged["middle_category_name"],
            "minor_category_name": merged["minor_category_name"],
            "subcategory_name": merged["subcategory_name"],
            "unit_name": merged["unit_name"],
            "unit_element_name": merged["unit_element_name"],
            "unit_definition": merged["unit_definition"],
            "subcategory_definition": merged["subcategory_definition"],
            "performance_criteria_text": merged["performance_criteria_text"],
            "knowledge_text": merged["knowledge_text"],
            "skill_text": merged["skill_text"],
            "attitude_text": merged["attitude_text"],
            "integrated_search_text": merged["integrated_search_text"],
            "normalized_search_text": merged["normalized_search_text"],
            "keyword_text": merged["keyword_text"],
            "subcategory_search_text": merged["subcategory_search_text"],
            "subcategory_keyword_text": merged["subcategory_keyword_text"],
            "base_year": merged.get("base_year", ""),
        }
    )
    return t25


def truncate_t25(engine: Engine) -> None:
    with engine.begin() as conn:
        # T27이 T25를 참조하므로 CASCADE로 처리한다.
        conn.execute(text("TRUNCATE TABLE T25_NCS_SEARCH_INDEX RESTART IDENTITY CASCADE"))


def insert_t25(engine: Engine, t25_df: pd.DataFrame) -> int:
    t25_df.to_sql(
        "t25_ncs_search_index",
        con=engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=3000,
    )
    return len(t25_df)


def update_t25_search_vector(engine: Engine) -> None:
    sql = """
    UPDATE T25_NCS_SEARCH_INDEX
    SET search_vector = to_tsvector(
        'simple',
        coalesce(normalized_search_text, '') || ' ' ||
        coalesce(keyword_text, '') || ' ' ||
        coalesce(subcategory_keyword_text, '')
    ),
    updated_at = CURRENT_TIMESTAMP
    """
    with engine.begin() as conn:
        conn.execute(text(sql))


def build_t27_embeddings(engine: Engine, max_text_length: int = 3000) -> int:
    """
    향후 임베딩 모델 연결을 고려해 독립 함수로 분리.
    현재는 벡터 생성 없이 embedding_text만 저장한다.
    """
    src = pd.read_sql_query(
        text(
            """
            SELECT
                search_index_id,
                id_t11,
                unit_category_id,
                unit_element_id,
                subcategory_code,
                integrated_search_text,
                base_year
            FROM T25_NCS_SEARCH_INDEX
            """
        ),
        con=engine,
    )

    if src.empty:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE T27_NCS_EMBEDDINGS RESTART IDENTITY"))
        return 0

    src["embedding_text"] = src["integrated_search_text"].fillna("").astype(str).str.slice(0, max_text_length)
    out = pd.DataFrame(
        {
            "search_index_id": src["search_index_id"],
            "id_t11": src["id_t11"],
            "unit_category_id": src["unit_category_id"],
            "unit_element_id": src["unit_element_id"],
            "subcategory_code": src["subcategory_code"],
            "embedding_target_type": "integrated_search_text",
            "embedding_model": "pending_model_selection",
            "embedding_text": src["embedding_text"],
            "base_year": src["base_year"],
        }
    )

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE T27_NCS_EMBEDDINGS RESTART IDENTITY"))

    out.to_sql(
        "t27_ncs_embeddings",
        con=engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=3000,
    )
    return len(out)


def print_final_outputs(engine: Engine) -> None:
    t25_count = pd.read_sql_query(text("SELECT count(*) AS cnt FROM T25_NCS_SEARCH_INDEX"), con=engine)
    logger.info("T25 row count: %s", int(t25_count.iloc[0]["cnt"]))

    subcategory_counts = pd.read_sql_query(
        text(
            """
            SELECT subcategory_code, count(*) AS row_count
            FROM T25_NCS_SEARCH_INDEX
            GROUP BY subcategory_code
            ORDER BY row_count DESC, subcategory_code
            """
        ),
        con=engine,
    )
    logger.info("subcategory_code별 row count (상위 20개):\n%s", subcategory_counts.head(20).to_string(index=False))

    sample_10 = pd.read_sql_query(
        text(
            """
            SELECT
                search_index_id,
                subcategory_code,
                subcategory_name,
                unit_category_id,
                unit_name,
                unit_element_name
            FROM T25_NCS_SEARCH_INDEX
            ORDER BY search_index_id
            LIMIT 10
            """
        ),
        con=engine,
    )
    logger.info("샘플 데이터 10건:\n%s", sample_10.to_string(index=False))


def run_preprocess(build_embeddings: bool = True, max_text_length: int = 3000) -> None:
    engine = run_step("DB 엔진 생성", create_db_engine)
    source = run_step("원본 테이블 로딩(T11~T15)", lambda: fetch_source_tables(engine))
    t25_df = run_step("T25 DataFrame 생성", lambda: build_t25_dataframe(source))
    run_step("T25 TRUNCATE", lambda: truncate_t25(engine))
    inserted = run_step("T25 INSERT", lambda: insert_t25(engine, t25_df))
    logger.info("T25 inserted rows: %s", inserted)
    run_step("T25 search_vector 업데이트", lambda: update_t25_search_vector(engine))

    if build_embeddings:
        embedded = run_step(
            "T27 임베딩 텍스트 생성",
            lambda: build_t27_embeddings(engine, max_text_length=max_text_length),
        )
        logger.info("T27 inserted rows: %s", embedded)

    run_step("최종 출력(건수/샘플)", lambda: print_final_outputs(engine))


if __name__ == "__main__":
    run_preprocess(build_embeddings=True, max_text_length=3000)
