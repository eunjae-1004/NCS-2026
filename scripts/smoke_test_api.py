from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any


BASE_URL = "http://127.0.0.1:8000"


def _get(path: str) -> tuple[int, dict[str, Any]]:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=15) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _get_raw(path: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(f"{BASE_URL}{path}", headers=headers or {}, method="GET")
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.status, response.read()


def _post(path: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> tuple[int, Any]:
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=req_headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_smoke_test() -> None:
    sample_payload = {"query": "총무팀 문서관리 담당자", "top_k": 3}

    status, health = _get("/api/health")
    _assert(status == 200, "health status must be 200")
    _assert(health.get("status") == "ok", "health.status must be 'ok'")

    status, full = _post("/api/search/full", sample_payload)
    _assert(status == 200, "full search status must be 200")
    _assert("recommended_subcategories" in full, "full response missing recommended_subcategories")
    _assert("recommended_jobs" in full, "full response missing recommended_jobs")
    _assert("recommended_units" in full, "full response missing recommended_units")

    status, subcategories = _post("/api/search/subcategories", sample_payload)
    _assert(status == 200, "subcategory search status must be 200")
    _assert(isinstance(subcategories, list), "subcategory response must be list")

    status, jobs = _post("/api/search/jobs", sample_payload)
    _assert(status == 200, "job search status must be 200")
    _assert(isinstance(jobs, list), "job response must be list")

    status, units = _post("/api/search/units", sample_payload)
    _assert(status == 200, "unit search status must be 200")
    _assert(isinstance(units, list), "unit response must be list")
    if units:
        _assert("unit_category_id" in units[0], "unit item missing unit_category_id")
        _assert("unit_element_id" in units[0], "unit item missing unit_element_id")

    status, checklist = _get("/api/subcategories/02020101/units")
    _assert(status == 200, "subcategory units status must be 200")
    _assert("units" in checklist, "subcategory units response missing units")

    status, ncs_tree = _get("/api/ncs/tree")
    _assert(status == 200, "ncs tree status must be 200")
    _assert(isinstance(ncs_tree, list), "ncs tree response must be list")

    status, examples = _get("/api/search/examples?limit=12")
    _assert(status == 200, "search examples status must be 200")
    _assert(isinstance(examples, list), "search examples response must be list")
    _assert(len(examples) > 0, "search examples must not be empty")

    status, bulk = _get("/api/subcategories/units-by-patterns?codes=020201,020203")
    _assert(status == 200, "units-by-patterns status must be 200")
    _assert(isinstance(bulk.get("subcategories"), list), "bulk response missing subcategories")
    _assert(len(bulk.get("subcategories") or []) > 0, "bulk subcategories must not be empty")
    _assert(len(bulk.get("units") or []) > 0, "bulk units must not be empty")

    if units:
        unit_category_id = units[0].get("unit_category_id")
        if unit_category_id:
            try:
                _get_raw(f"/api/units/{unit_category_id}/structure")
                raise AssertionError("guest unit structure should not return 200")
            except urllib.error.HTTPError as exc:
                _assert(exc.code == 401, "guest unit structure must return 401")

            test_email = "smoke_test_user@example.local"
            test_password = "smoke_test_pass_123"
            try:
                _post(
                    "/api/auth/register",
                    {
                        "email": test_email,
                        "password": test_password,
                        "full_name": "스모크테스트",
                        "company_name": "테스트회사",
                        "department_name": "테스트팀",
                    },
                )
            except urllib.error.HTTPError:
                pass

            status, auth = _post(
                "/api/auth/login",
                {"email": test_email, "password": test_password},
            )
            _assert(status == 200, "auth login status must be 200")
            token = auth.get("access_token")
            _assert(bool(token), "auth login must return access_token")

            status, structure_raw = _get_raw(
                f"/api/units/{unit_category_id}/structure",
                headers={"Authorization": f"Bearer {token}"},
            )
            _assert(status == 200, "logged-in unit structure status must be 200")
            structure = json.loads(structure_raw.decode("utf-8"))
            _assert("elements" in structure, "unit structure response missing elements")

            status, saved = _post(
                "/api/me/units",
                {
                    "unit_category_id": unit_category_id,
                    "unit_name": units[0].get("unit_name"),
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            _assert(status == 200, "save user unit status must be 200")
            _assert(saved.get("unit_category_id") == unit_category_id, "saved unit id mismatch")

    status, csv_raw = _get_raw("/api/download/basic-ncs")
    _assert(status == 200, "basic ncs download status must be 200")
    _assert(csv_raw.startswith(b"subcategory_code"), "basic ncs csv header mismatch")

    print("[OK] API smoke test passed.")
    print(
        json.dumps(
            {
                "health": health,
                "full_top_subcategory": (full.get("recommended_subcategories") or [{}])[0],
                "job_count": len(jobs),
                "unit_count": len(units),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        run_smoke_test()
    except urllib.error.URLError as exc:
        print(f"[ERROR] API connection failed: {exc}")
        print("먼저 서버를 실행하세요: uvicorn app.main:app --host 0.0.0.0 --port 8000")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Smoke test failed: {exc}")
        sys.exit(1)
