from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import CurrentUser, require_authenticated_member
from app.schemas.search_schema import ErrorResponse
from app.schemas.user_schema import (
    AuthTokenResponse,
    EmailExistsResponse,
    LoginRequest,
    RegisterRequest,
    UserProfileResponse,
)
from app.services.jwt_service import create_access_token
from app.services.user_service import authenticate_user, create_user, email_exists, get_user_by_email

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _profile_from_row(row: dict) -> UserProfileResponse:
    return UserProfileResponse(
        user_id=int(row["user_id"]),
        email=str(row["email"]),
        full_name=str(row["full_name"]),
        phone=row.get("phone"),
        company_name=str(row["company_name"]),
        department_name=str(row["department_name"]),
        created_at=row.get("created_at"),
    )


def _token_response(row: dict) -> AuthTokenResponse:
    user = _profile_from_row(row)
    token = create_access_token(user.user_id, user.email)
    return AuthTokenResponse(access_token=token, user=user)


@router.get(
    "/email-exists",
    response_model=EmailExistsResponse,
    responses={400: {"model": ErrorResponse}},
)
def check_email_exists(email: str = Query(..., min_length=5, max_length=255)) -> EmailExistsResponse:
    normalized = email.strip().lower()
    if "@" not in normalized:
        raise HTTPException(status_code=400, detail="올바른 이메일 형식이 아닙니다.")
    return EmailExistsResponse(email=normalized, exists=email_exists(normalized))


@router.post(
    "/register",
    response_model=AuthTokenResponse,
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def register(payload: RegisterRequest) -> AuthTokenResponse:
    if email_exists(payload.email):
        raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다. 로그인해 주세요.")
    try:
        row = create_user(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            company_name=payload.company_name,
            department_name=payload.department_name,
            phone=payload.phone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _token_response(row)


@router.post(
    "/login",
    response_model=AuthTokenResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def login(payload: LoginRequest) -> AuthTokenResponse:
    existing = get_user_by_email(payload.email)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail="가입 이력이 없는 이메일입니다. 회원가입을 진행해 주세요.",
        )
    if not existing.get("is_active"):
        raise HTTPException(status_code=401, detail="비활성화된 계정입니다.")

    user = authenticate_user(payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다.")
    return _token_response(user)


@router.get("/me", response_model=UserProfileResponse, responses={401: {"model": ErrorResponse}})
def me(current_user: CurrentUser = Depends(require_authenticated_member)) -> UserProfileResponse:
    return UserProfileResponse(
        user_id=current_user.user_id,
        email=current_user.email,
        full_name=current_user.full_name,
        phone=current_user.phone,
        company_name=current_user.company_name,
        department_name=current_user.department_name,
    )
