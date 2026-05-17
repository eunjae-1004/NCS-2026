from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine

from app.config import load_settings


def create_db_engine() -> Engine:
    """
    SQLAlchemy Engine을 생성한다.
    """
    cfg = load_settings()
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=cfg.db_user,
        password=cfg.db_password,
        host=cfg.db_host,
        port=cfg.db_port,
        database=cfg.db_name,
    )
    return create_engine(url, pool_pre_ping=True, future=True)


engine = create_db_engine()


@contextmanager
def get_connection() -> Iterator:
    """
    SQL 실행용 커넥션 컨텍스트를 제공한다.
    """
    with engine.begin() as conn:
        yield conn


def ping_db() -> bool:
    with get_connection() as conn:
        conn.execute(text("SELECT 1"))
    return True
