from __future__ import annotations

from fastapi import Header, HTTPException


def get_user_mode(x_user_mode: str | None = Header(default="guest")) -> str:
    mode = (x_user_mode or "guest").strip().lower()
    if mode not in {"guest", "member"}:
        return "guest"
    return mode


def require_member(x_user_mode: str | None = Header(default="guest")) -> str:
    mode = get_user_mode(x_user_mode)
    if mode != "member":
        raise HTTPException(status_code=401, detail="회원 전용 기능입니다. 로그인 후 이용해주세요.")
    return mode
