from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    app_name: str
    app_version: str


def load_settings() -> Settings:
    """
    .env 파일에서 애플리케이션 설정을 읽는다.
    """
    load_dotenv()
    return Settings(
        db_host=os.getenv("DB_HOST", "localhost"),
        db_port=int(os.getenv("DB_PORT", "5432")),
        db_name=os.getenv("DB_NAME", "ncs_search"),
        db_user=os.getenv("DB_USER", "postgres"),
        db_password=os.getenv("DB_PASSWORD", "postgres"),
        app_name=os.getenv("APP_NAME", "NCS Search API"),
        app_version=os.getenv("APP_VERSION", "0.1.0"),
    )
