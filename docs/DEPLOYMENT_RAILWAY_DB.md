# Railway PostgreSQL — 스키마 적용 및 기존 DB 데이터 이전

배포·런타임 관점의 전체 그림은 **[SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md)** 를 참고하세요.

로컬/회사 PostgreSQL에 쌓인 데이터를 **Railway PostgreSQL**로 옮기는 절차입니다.

---

## 1. 준비물

| 항목 | 설명 |
|------|------|
| PostgreSQL 클라이언트 | `pg_dump`, `pg_restore`, `psql` (PostgreSQL 설치 시 포함) |
| 기존 DB | 로컬 `ncs_search` 또는 회사 서버 DB |
| Railway DB | 빈 PostgreSQL 서비스 + **Connect** 탭의 접속 정보 |
| 스키마 SQL | `sql/004_railway_service_schema.sql` (빈 DB에 스키마만 먼저 넣을 때) |

PowerShell에서 클라이언트 확인:

```powershell
pg_dump --version
```

---

## 2. 이전 방식 선택

### A. 전체 덤프·복원 (권장 — 기존 DB가 이미 완전히 동작할 때)

기존 DB에 **T11~T30, T25 인덱스, 회원·저장 데이터**가 모두 있으면 한 번에 복사합니다.

```text
[기존 DB] --pg_dump--> ncs_search.dump --pg_restore--> [Railway DB]
```

- Railway DB는 **비어 있어야** 합니다 (스키마도 덤프에 포함).
- `004_railway_service_schema.sql`은 **실행하지 않거나**, 복원 후 중복만 없으면 됩니다.

### B. 스키마 먼저 + 데이터만 복원

Railway에 이미 `004_railway_service_schema.sql`을 실행한 경우:

```text
[기존 DB] --pg_dump --data-only--> dump --pg_restore --data-only--> [Railway]
```

- 테이블 구조는 Railway에 맞춰 두고 **행만** 이전합니다.
- 시퀀스(`SERIAL`)는 덤프에 `setval`이 포함되도록 **전체 덤프**에서 `--data-only`를 쓰는 편이 안전합니다.

### C. 원본만 있고 T25가 없을 때

T11~T15만 기존 DB/CSV에 있고 검색 인덱스가 없다면:

1. Railway에 스키마 적용 (`004` 또는 `pg_restore`)
2. T11~T15 데이터 적재 (덤프 또는 CSV)
3. 로컬 `.env.railway`를 Railway로 맞춘 뒤:

```powershell
python scripts/preprocess_ncs_index.py
python scripts/seed_minimum_dictionary_data.py
python scripts/optimize_db_indexes.py
```

---

## 3. 환경 파일 구성

프로젝트 루트에 **소스**와 **대상** 두 개의 env 파일을 둡니다.

### `.env` (기존 DB — 소스)

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ncs_search
DB_USER=postgres
DB_PASSWORD=로컬비밀번호
```

### `.env.railway` (Railway — 대상)

Railway → PostgreSQL → **Variables** 또는 **Connect**에서 복사:

```env
DB_HOST=containers-us-west-xxx.railway.app
DB_PORT=14974
DB_NAME=railway
DB_USER=postgres
DB_PASSWORD=Railway에서_복사한_값
```

> `.env.railway`는 git에 올리지 마세요. `.gitignore`에 추가 권장.

Railway **공개 프록시**로 접속할 때는 SSL이 필요합니다. PowerShell:

```powershell
$env:PGSSLMODE = "require"
```

---

## 4. 스크립트로 이전 (Windows)

프로젝트 루트에서:

```powershell
.\.venv\Scripts\Activate.ps1
$env:PGSSLMODE = "require"

# 1) 기존 DB → 덤프 파일
.\scripts\migrate_db.ps1 -Action dump -SourceEnvFile .env -DumpFile backups\ncs_search.dump

# 2) Railway 빈 DB로 복원 (전체)
.\scripts\migrate_db.ps1 -Action restore -TargetEnvFile .env.railway -DumpFile backups\ncs_search.dump

# 3) 건수 검증
.\scripts\migrate_db.ps1 -Action verify -TargetEnvFile .env.railway
```

이미 Railway에 `004` 스키마를 적용했다면 **데이터만**:

```powershell
.\scripts\migrate_db.ps1 -Action dump -SourceEnvFile .env -DumpFile backups\ncs_data_only.dump -DataOnly
.\scripts\migrate_db.ps1 -Action restore -TargetEnvFile .env.railway -DumpFile backups\ncs_data_only.dump -DataOnly
```

---

## 5. 수동 명령 (스크립트 없이)

### 5-1. 덤프 (로컬 → 파일)

```powershell
$env:PGPASSWORD = "로컬비밀번호"
pg_dump -h localhost -p 5432 -U postgres -d ncs_search `
  -Fc --no-owner --no-acl `
  -f backups\ncs_search.dump
```

### 5-2. 복원 (파일 → Railway)

```powershell
$env:PGSSLMODE = "require"
$env:PGPASSWORD = "Railway비밀번호"
pg_restore -h <RAILWAY_HOST> -p <PORT> -U postgres -d railway `
  --no-owner --no-acl --verbose `
  backups\ncs_search.dump
```

오류 `already exists`가 나오면 Railway가 비어 있지 않은 상태입니다.  
빈 DB를 새로 만들거나, `-c` 없이 **데이터만** 덤프/복원하세요.

### 5-3. Railway에 스키마만 먼저

```powershell
$env:PGSSLMODE = "require"
$env:PGPASSWORD = "Railway비밀번호"
psql -h <HOST> -p <PORT> -U postgres -d railway -f sql/004_railway_service_schema.sql
```

---

## 6. 복원 후 검증 SQL

Railway Query 또는 `psql`에서:

```sql
SELECT 'T11' AS t, COUNT(*) FROM T11_NCS_UNITS
UNION ALL SELECT 'T25', COUNT(*) FROM T25_NCS_SEARCH_INDEX
UNION ALL SELECT 'T21', COUNT(*) FROM T21_DEPARTMENT_DICTIONARY
UNION ALL SELECT 'T29', COUNT(*) FROM T29_APP_USERS
UNION ALL SELECT 'T30', COUNT(*) FROM T30_USER_UNIT_SELECTIONS;
```

기대:

- T11, T25: 0이 아니어야 검색·구조도 동작
- T29, T30: 회원/저장 단위를 쓰던 경우 0이 아님

로컬에서 API 연결 테스트 (`.env`를 Railway로 잠시 바꾸거나 `.env.railway` 로드):

```powershell
# .env를 Railway 값으로 맞춘 뒤
python -c "from app.db import ping_db; ping_db(); print('OK')"
python scripts/smoke_test_api.py
```

---

## 7. Railway 앱 환경 변수

앱 서비스 **Variables** (PostgreSQL 서비스와 동일 프로젝트면 **Reference** 가능):

| Key | 값 |
|-----|-----|
| `DB_HOST` | Railway PG 호스트 |
| `DB_PORT` | Railway PG 포트 |
| `DB_NAME` | `railway` 등 |
| `DB_USER` | `postgres` |
| `DB_PASSWORD` | Connect 탭 비밀번호 |
| `JWT_SECRET` | 운영용 긴 랜덤 문자열 |

`password authentication failed` → 비밀번호가 Connect 탭과 다름. **Reset** 후 Variables 전부 갱신.

---

## 8. 자주 하는 실수

| 증상 | 원인 | 해결 |
|------|------|------|
| authentication failed | 잘못된 비밀번호/호스트 | Railway Connect 값 그대로 복사 |
| SSL required | 공개 URL | `$env:PGSSLMODE = "require"` |
| relation already exists | 스키마 중복 적용 | 빈 DB에 복원하거나 `-DataOnly` |
| T25=0, 검색 안 됨 | T25 미생성 | `preprocess_ncs_index.py` 실행 |
| 로그인만 실패 | JWT/회원만 누락 | T29/T30 덤프 포함 여부 확인 |

---

## 9. 관련 파일

| 파일 | 용도 |
|------|------|
| `sql/004_railway_service_schema.sql` | 빈 Railway DB 스키마 |
| `scripts/migrate_db.ps1` | dump / restore / verify |
| `docs/DEPLOYMENT.md` | 회사 DB + Railway 앱 배포 |
| `scripts/preprocess_ncs_index.py` | T25/T27 재생성 |
