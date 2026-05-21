from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255, description="로그인 이메일")
    password: str = Field(..., min_length=8, max_length=128, description="비밀번호")
    full_name: str = Field(..., min_length=1, max_length=100, description="이름")
    phone: str | None = Field(None, max_length=30, description="연락처(선택)")
    company_name: str = Field(..., min_length=1, max_length=200, description="기업명")
    department_name: str = Field(..., min_length=1, max_length=200, description="부서명")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("올바른 이메일 형식이 아닙니다.")
        return email


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class UserProfileResponse(BaseModel):
    user_id: int
    email: str
    full_name: str
    phone: str | None = None
    company_name: str
    department_name: str
    created_at: datetime | None = None


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfileResponse


class EmailExistsResponse(BaseModel):
    email: str
    exists: bool


class UserUnitSelectionRequest(BaseModel):
    unit_category_id: str = Field(..., min_length=1, max_length=50)
    unit_name: str | None = Field(None, max_length=200)
    subcategory_code: str | None = Field(None, max_length=50)
    subcategory_name: str | None = Field(None, max_length=100)


class UserUnitSelectionResponse(BaseModel):
    selection_id: int
    unit_category_id: str
    unit_name: str | None = None
    subcategory_code: str | None = None
    subcategory_name: str | None = None
    created_at: datetime | None = None


class UserUnitSelectionListResponse(BaseModel):
    items: list[UserUnitSelectionResponse]
    total: int
