from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str


def load_db_config() -> DbConfig:
    """
    .env 파일에서 DB 접속 정보를 읽어 설정 객체로 반환한다.
    """
    load_dotenv()

    return DbConfig(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "ncs_search"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )
