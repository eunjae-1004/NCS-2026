<#
.SYNOPSIS
  NCS Search DB 덤프/복원/검증 (로컬 또는 회사 DB <-> Railway PostgreSQL)

.EXAMPLE
  $env:PGSSLMODE = "require"
  .\scripts\migrate_db.ps1 -Action dump -SourceEnvFile .env
  .\scripts\migrate_db.ps1 -Action restore -TargetEnvFile .env.railway
  .\scripts\migrate_db.ps1 -Action verify -TargetEnvFile .env.railway
#>
param(
    [ValidateSet("dump", "restore", "verify")]
    [string]$Action = "dump",

    [string]$SourceEnvFile = ".env",
    [string]$TargetEnvFile = ".env.railway",
    [string]$DumpFile = "backups\ncs_search.dump",
    [switch]$DataOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Read-DbEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "환경 파일이 없습니다: $Path (Railway 값은 .env.railway 로 복사하세요)"
    }
    $map = @{}
    Get-Content $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { return }
        if ($line -match "^([^=]+)=(.*)$") {
            $map[$Matches[1].Trim()] = $Matches[2].Trim()
        }
    }
    foreach ($key in @("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")) {
        if (-not $map.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($map[$key])) {
            throw "$Path 에 $key 가 없습니다."
        }
    }
    return @{
        Host     = $map["DB_HOST"]
        Port     = $map["DB_PORT"]
        Name     = $map["DB_NAME"]
        User     = $map["DB_USER"]
        Password = $map["DB_PASSWORD"]
    }
}

function Test-PgTools {
    foreach ($cmd in @("pg_dump", "pg_restore", "psql")) {
        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
            throw "PostgreSQL 클라이언트 '$cmd' 를 찾을 수 없습니다. PATH에 bin 폴더를 추가하세요."
        }
    }
}

function Set-PgSslModeForHost {
    param([string]$HostName)
    # Railway 공개 URL은 SSL 필수. 회사/로컬 DB(1.218.x 등)는 SSL 미지원인 경우가 많음.
    if ($HostName -match 'railway\.(app|internal)') {
        $env:PGSSLMODE = 'require'
        Write-Host "[INFO] PGSSLMODE=require ($HostName)"
    }
    else {
        Remove-Item Env:PGSSLMODE -ErrorAction SilentlyContinue
        Write-Host "[INFO] PGSSLMODE=(없음, SSL 비강제) ($HostName)"
    }
}

function Clear-PgLibpqEnv {
    # 시스템/Railway 등에서 남은 libpq 변수가 -h/-U 보다 우선하는 경우 방지
    foreach ($name in @("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGPASSWORD", "PGSSLMODE", "PGSERVICE", "PGSERVICEFILE")) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
}

function Invoke-PgCommand {
    param(
        [string]$Exe,
        [string[]]$PgArgs
    )
    & $Exe @PgArgs
    if ($LASTEXITCODE -ne 0) {
        throw "$Exe 실패 (exit code $LASTEXITCODE)"
    }
}

function Invoke-Verify {
    param($Db)
    $env:PGPASSWORD = $Db.Password
    Set-PgSslModeForHost -HostName $Db.Host
    $sql = @"
SELECT 'T11_NCS_UNITS' AS table_name, COUNT(*)::text AS row_count FROM T11_NCS_UNITS
UNION ALL SELECT 'T25_NCS_SEARCH_INDEX', COUNT(*)::text FROM T25_NCS_SEARCH_INDEX
UNION ALL SELECT 'T21_DEPARTMENT_DICTIONARY', COUNT(*)::text FROM T21_DEPARTMENT_DICTIONARY
UNION ALL SELECT 'T29_APP_USERS', COUNT(*)::text FROM T29_APP_USERS
UNION ALL SELECT 'T30_USER_UNIT_SELECTIONS', COUNT(*)::text FROM T30_USER_UNIT_SELECTIONS
ORDER BY 1;
"@
    Write-Host "[VERIFY] $($Db.Host):$($Db.Port)/$($Db.Name)"
    Invoke-PgCommand -Exe "psql" -PgArgs @("-h", $Db.Host, "-p", $Db.Port, "-U", $Db.User, "-d", $Db.Name, "-c", $sql)
}

Test-PgTools

switch ($Action) {
    "dump" {
        $src = Read-DbEnv -Path $SourceEnvFile
        Clear-PgLibpqEnv
        $dir = Split-Path -Parent $DumpFile
        if ($dir -and -not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
        $env:PGPASSWORD = $src.Password
        Set-PgSslModeForHost -HostName $src.Host
        $pgDumpArgs = @(
            "-h", $src.Host,
            "-p", $src.Port,
            "-U", $src.User,
            "-d", $src.Name,
            "-Fc",
            "--no-owner",
            "--no-acl",
            "-f", $DumpFile
        )
        if ($DataOnly) { $pgDumpArgs += "--data-only" }
        Write-Host "[DUMP] $($src.Host):$($src.Port)/$($src.Name) user=$($src.User) -> $DumpFile"
        Invoke-PgCommand -Exe "pg_dump" -PgArgs $pgDumpArgs
        Write-Host "[OK] 덤프 완료: $DumpFile"
    }
    "restore" {
        if (-not (Test-Path $DumpFile)) {
            throw "덤프 파일이 없습니다: $DumpFile"
        }
        $tgt = Read-DbEnv -Path $TargetEnvFile
        Clear-PgLibpqEnv
        $env:PGPASSWORD = $tgt.Password
        Set-PgSslModeForHost -HostName $tgt.Host
        $pgRestoreArgs = @(
            "-h", $tgt.Host,
            "-p", $tgt.Port,
            "-U", $tgt.User,
            "-d", $tgt.Name,
            "--no-owner",
            "--no-acl",
            "--verbose",
            $DumpFile
        )
        if ($DataOnly) {
            $pgRestoreArgs = @("-h", $tgt.Host, "-p", $tgt.Port, "-U", $tgt.User, "-d", $tgt.Name, "--no-owner", "--no-acl", "--verbose", "--data-only", $DumpFile)
        }
        Write-Host "[RESTORE] $DumpFile -> $($tgt.Host):$($tgt.Port)/$($tgt.Name) user=$($tgt.User)"
        Invoke-PgCommand -Exe "pg_restore" -PgArgs $pgRestoreArgs
        Write-Host "[OK] 복원 완료"
        Invoke-Verify -Db $tgt
    }
    "verify" {
        $tgt = Read-DbEnv -Path $TargetEnvFile
        Clear-PgLibpqEnv
        $env:PGPASSWORD = $tgt.Password
        Invoke-Verify -Db $tgt
    }
}
