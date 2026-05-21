from __future__ import annotations

from typing import Any

import bcrypt
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import get_connection
from app.services.ncs_service import get_unit_ncs_meta


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))


def email_exists(email: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            text(
                """
                SELECT 1
                FROM T29_APP_USERS
                WHERE email = :email AND is_active = TRUE
                LIMIT 1
                """
            ),
            {"email": email},
        ).first()
    return row is not None


def create_user(
    *,
    email: str,
    password: str,
    full_name: str,
    company_name: str,
    department_name: str,
    phone: str | None = None,
) -> dict[str, Any]:
    with get_connection() as conn:
        try:
            row = conn.execute(
                text(
                    """
                    INSERT INTO T29_APP_USERS (
                        email, password_hash, full_name, phone,
                        company_name, department_name
                    )
                    VALUES (
                        :email, :password_hash, :full_name, :phone,
                        :company_name, :department_name
                    )
                    RETURNING user_id, email, full_name, phone,
                              company_name, department_name, created_at
                    """
                ),
                {
                    "email": email,
                    "password_hash": hash_password(password),
                    "full_name": full_name.strip(),
                    "phone": phone.strip() if phone else None,
                    "company_name": company_name.strip(),
                    "department_name": department_name.strip(),
                },
            ).mappings().first()
        except IntegrityError as exc:
            raise ValueError("이미 가입된 이메일입니다.") from exc
    if not row:
        raise RuntimeError("회원 생성에 실패했습니다.")
    return dict(row)


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            text(
                """
                SELECT user_id, email, password_hash, full_name, phone,
                       company_name, department_name, is_active, created_at
                FROM T29_APP_USERS
                WHERE email = :email
                LIMIT 1
                """
            ),
            {"email": email},
        ).mappings().first()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            text(
                """
                SELECT user_id, email, full_name, phone,
                       company_name, department_name, created_at
                FROM T29_APP_USERS
                WHERE user_id = :user_id AND is_active = TRUE
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        ).mappings().first()
    return dict(row) if row else None


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    user = get_user_by_email(email)
    if not user or not user.get("is_active"):
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    user.pop("password_hash", None)
    return user


def list_user_unit_selections(user_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            text(
                """
                SELECT selection_id, unit_category_id, unit_name,
                       subcategory_code, subcategory_name, created_at
                FROM T30_USER_UNIT_SELECTIONS
                WHERE user_id = :user_id
                ORDER BY created_at DESC, selection_id DESC
                """
            ),
            {"user_id": user_id},
        ).mappings().all()

        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            meta = get_unit_ncs_meta(str(item.get("unit_category_id") or ""))
            if not meta:
                result.append(item)
                continue

            item["unit_name"] = item.get("unit_name") or meta.get("unit_name")
            new_code = str(meta.get("subcategory_code") or "").strip()
            new_name = str(meta.get("subcategory_name") or "").strip()
            if new_code:
                old_code = str(item.get("subcategory_code") or "").strip()
                old_name = str(item.get("subcategory_name") or "").strip()
                if new_code != old_code or (new_name and new_name != old_name):
                    conn.execute(
                        text(
                            """
                            UPDATE T30_USER_UNIT_SELECTIONS
                            SET subcategory_code = :subcategory_code,
                                subcategory_name = :subcategory_name
                            WHERE selection_id = :selection_id
                            """
                        ),
                        {
                            "selection_id": item["selection_id"],
                            "subcategory_code": new_code,
                            "subcategory_name": new_name or None,
                        },
                    )
                item["subcategory_code"] = new_code
                if new_name:
                    item["subcategory_name"] = new_name
            result.append(item)
    return result


def _enrich_unit_selection_payload(payload: dict[str, Any]) -> dict[str, Any]:
    unit_category_id = str(payload.get("unit_category_id") or "").strip()
    if not unit_category_id:
        return payload

    meta = get_unit_ncs_meta(unit_category_id)
    if not meta:
        return payload

    enriched = dict(payload)
    enriched["unit_name"] = enriched.get("unit_name") or meta.get("unit_name")
    enriched["subcategory_code"] = meta.get("subcategory_code") or enriched.get("subcategory_code")
    enriched["subcategory_name"] = meta.get("subcategory_name") or enriched.get("subcategory_name")
    return enriched


def add_user_unit_selection(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    payload = _enrich_unit_selection_payload(payload)
    with get_connection() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO T30_USER_UNIT_SELECTIONS (
                    user_id, unit_category_id, unit_name,
                    subcategory_code, subcategory_name
                )
                VALUES (
                    :user_id, :unit_category_id, :unit_name,
                    :subcategory_code, :subcategory_name
                )
                ON CONFLICT (user_id, unit_category_id)
                DO UPDATE SET
                    unit_name = EXCLUDED.unit_name,
                    subcategory_code = EXCLUDED.subcategory_code,
                    subcategory_name = EXCLUDED.subcategory_name
                RETURNING selection_id, unit_category_id, unit_name,
                          subcategory_code, subcategory_name, created_at
                """
            ),
            {
                "user_id": user_id,
                "unit_category_id": payload["unit_category_id"],
                "unit_name": payload.get("unit_name"),
                "subcategory_code": payload.get("subcategory_code"),
                "subcategory_name": payload.get("subcategory_name"),
            },
        ).mappings().first()
    if not row:
        raise RuntimeError("능력단위 저장에 실패했습니다.")
    return dict(row)


def remove_user_unit_selection(user_id: int, unit_category_id: str) -> bool:
    with get_connection() as conn:
        result = conn.execute(
            text(
                """
                DELETE FROM T30_USER_UNIT_SELECTIONS
                WHERE user_id = :user_id AND unit_category_id = :unit_category_id
                """
            ),
            {"user_id": user_id, "unit_category_id": unit_category_id},
        )
    return result.rowcount > 0
