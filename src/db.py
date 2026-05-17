from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from src.config import load_db_config


@contextmanager
def get_conn(autocommit: bool = False) -> Iterator[psycopg.Connection]:
    """
    psycopg 연결을 안전하게 열고 닫는다.
    """
    cfg = load_db_config()
    conn = psycopg.connect(
        host=cfg.host,
        port=cfg.port,
        dbname=cfg.dbname,
        user=cfg.user,
        password=cfg.password,
        autocommit=autocommit,
    )
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_cursor(autocommit: bool = False):
    """
    Dict 형태 row를 반환하는 커서를 제공한다.
    """
    with get_conn(autocommit=autocommit) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            yield conn, cur
