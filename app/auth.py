from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.jwt_service import decode_access_token
from app.services.user_service import get_user_by_id

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    email: str
    full_name: str
    phone: str | None
    company_name: str
    department_name: str


def _to_current_user(row: dict[str, Any]) -> CurrentUser:
    return CurrentUser(
        user_id=int(row["user_id"]),
        email=str(row["email"]),
        full_name=str(row["full_name"]),
        phone=row.get("phone"),
        company_name=str(row["company_name"]),
        department_name=str(row["department_name"]),
    )


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_user_mode: str | None = Header(default=None),
) -> CurrentUser | None:
    """
    JWT Bearer 우선. 레거시 X-User-Mode: member 는 개발/테스트 호환용(실제 사용자 없음).
    """
    if credentials and credentials.scheme.lower() == "bearer" and credentials.credentials:
        try:
            payload = decode_access_token(credentials.credentials)
            user_id = int(payload.get("sub", 0))
        except (jwt.PyJWTError, TypeError, ValueError):
            raise HTTPException(status_code=401, detail="로그인이 만료되었거나 유효하지 않습니다.") from None

        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=401, detail="사용자를 찾을 수 없습니다.")
        return _to_current_user(user)

    mode = (x_user_mode or "").strip().lower()
    if mode == "member":
        return CurrentUser(
            user_id=0,
            email="legacy-member@local",
            full_name="레거시 회원",
            phone=None,
            company_name="-",
            department_name="-",
        )
    return None


def require_member(user: CurrentUser | None = Depends(get_optional_user)) -> CurrentUser:
    if user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


def require_authenticated_member(user: CurrentUser = Depends(require_member)) -> CurrentUser:
    if user.user_id <= 0:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user
