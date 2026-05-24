# railway up 배포 보조 스크립트 — UTF-8 (BOM 권장)
<#
.SYNOPSIS
  GitHub 자동 배포가 안 될 때, 로컬 최신 코드를 Railway에 직접 업로드합니다.

.EXAMPLE
  railway login
  cd d:\Website\cursor\NCS_Search
  .\scripts\deploy_railway_from_local.ps1
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command railway -ErrorAction SilentlyContinue)) {
    throw "Railway CLI가 없습니다. https://docs.railway.com/guides/cli"
}

Write-Host "==> Railway 로그인 확인" -ForegroundColor Cyan
railway whoami

Write-Host "==> 프로젝트 연결 (처음 한 번: railway link 로 API 서비스 선택)" -ForegroundColor Cyan
if (-not (Test-Path "$Root\.railway")) {
    railway link
}

Write-Host "==> 로컬 코드 배포 (GitHub 우회)" -ForegroundColor Cyan
railway up --detach

Write-Host ""
Write-Host "배포 후 확인:" -ForegroundColor Green
Write-Host "  https://ncs-2026-production.up.railway.app/api/health"
Write-Host "  web_asset 가 20260523-final 이면 성공"
