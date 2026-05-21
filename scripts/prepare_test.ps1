# NCS_Search 테스트 환경 준비 스크립트
# 사용: .\scripts\prepare_test.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> 가상환경 확인/생성" -ForegroundColor Cyan
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    python -m venv .venv
}

Write-Host "==> 가상환경 활성화 및 패키지 설치" -ForegroundColor Cyan
& ".\.venv\Scripts\Activate.ps1"
python -m pip install -U pip -q
pip install -r requirements.txt -q

if (-not (Test-Path ".\.env")) {
    Write-Host "[WARN] .env 파일이 없습니다. .env.example 을 참고해 .env 를 만드세요." -ForegroundColor Yellow
    exit 1
}

Write-Host "==> DB 연결 확인" -ForegroundColor Cyan
python -c "from app.db import ping_db; ping_db(); print('[OK] DB 연결 성공')"

Write-Host "==> 예시 질문(T28) 시드" -ForegroundColor Cyan
python scripts/seed_example_queries.py

Write-Host "==> 회원 스키마(T29/T30) 적용" -ForegroundColor Cyan
python scripts/apply_user_auth_schema.py

Write-Host ""
Write-Host "==> 준비 완료" -ForegroundColor Green
Write-Host "서버 실행:" -ForegroundColor Yellow
Write-Host "  python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
Write-Host "스모크 테스트 (서버 실행 후 다른 터미널):" -ForegroundColor Yellow
Write-Host "  python scripts/smoke_test_api.py"
Write-Host "웹 UI:" -ForegroundColor Yellow
Write-Host "  http://127.0.0.1:8000/"
