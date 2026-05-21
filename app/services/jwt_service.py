from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.config import load_settings


def create_access_token(user_id: int, email: str) -> str:
    settings = load_settings()
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = load_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
