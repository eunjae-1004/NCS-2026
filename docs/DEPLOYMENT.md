# NCS Search 배포 가이드 (회사 PostgreSQL + Railway)

구성 요소 간 관계와 테이블 맵은 **[SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md)** 를 먼저 보는 것이 좋습니다.

이 문서는 **회사 서버 PostgreSQL**을 DB로 두고, **Railway**에서 FastAPI + 웹 UI를 운영하는 절차를 정리합니다.  
(Vercel 없이 Railway 단독 — `app/main.py`가 `/`·`/static`·`/api`를 모두 제공)

---

## 1. 전체 아키텍처

```text
[사용자] → HTTPS → [Railway: uvicorn + FastAPI + web/]
                          ↓ TCP 5432 (방화벽: Railway egress IP만 허용)
                    [회사 서버 PostgreSQL]
```

| 구성요소 | 역할 |
|----------|------|
| GitHub | 소스 저장, push 시 Railway 자동 배포 |
| Railway | API + 웹 호스팅 (PostgreSQL 플러그인 **사용 안 함**) |
| 회사 DB | T11~T28 데이터 저장 |

---

## 2. 회사 PostgreSQL 서버 설정

### 2-1. 사전 확인

- PostgreSQL **14 이상** 권장 (현재 프로젝트는 표준 SQL + FTS + `pg_trgm` 사용)
- Railway(클라우드)에서 **회사 DB IP:포트로 TCP 연결 가능**해야 함
- DB가 **사내망 전용**이면 Railway는 붙을 수 없음 → VPN/공인 IP/프록시 필요

### 2-2. OS 방화벽 (회사 서버)

**5432 포트**를 열되, **전 세계(0.0.0.0/0) 개방은 금지**합니다.

1. Railway 서비스 배포 후 **Static Outbound IP** 확인  
   (Railway 대시보드 → Service → Settings → Networking)
2. 회사 방화벽/보안 그룹에 **해당 IP만** `5432` 허용

예 (Linux `ufw`):

```bash
sudo ufw allow from <RAILWAY_EGRESS_IP> to any port 5432 proto tcp
sudo ufw reload
```

### 2-3. PostgreSQL 설치 (Linux 예시, Ubuntu)

이미 설치되어 있으면 2-4로 이동합니다.

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable postgresql
sudo systemctl start postgresql
```

### 2-4. DB·계정 생성

`postgres` 슈퍼유저로 접속:

```bash
sudo -u postgres psql
```

SQL:

```sql
-- 운영 DB
CREATE DATABASE ncs_search
  ENCODING 'UTF8'
  LC_COLLATE 'ko_KR.UTF-8'
  LC_CTYPE 'ko_KR.UTF-8'
  TEMPLATE template0;
-- Windows/영문 서버면 LC_* 는 C 또는 en_US.UTF-8 로 조정

-- 전용 계정 (최소 권한)
CREATE USER ncs_app WITH PASSWORD '강력한_비밀번호_여기';

GRANT CONNECT ON DATABASE ncs_search TO ncs_app;
\c ncs_search
GRANT USAGE ON SCHEMA public TO ncs_app;
GRANT CREATE ON SCHEMA public TO ncs_app;  -- init_db 시 테이블 생성용, 이후 REVOKE 가능

-- init_db / 시드 완료 후 운영 최소 권한 예시:
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ncs_app;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ncs_app;
```

### 2-5. 외부 접속 허용 (`postgresql.conf`)

경로 예: `/etc/postgresql/16/main/postgresql.conf`

```ini
listen_addresses = '*'          # 또는 회사 공인 IP만
port = 5432
max_connections = 100           # Railway 동시 접속 고려해 조정
```

변경 후:

```bash
sudo systemctl restart postgresql
```

### 2-6. 클라이언트 인증 (`pg_hba.conf`)

경로 예: `/etc/postgresql/16/main/pg_hba.conf`

Railway egress IP만 허용 (예시):

```text
# TYPE  DATABASE     USER      ADDRESS               METHOD
host    ncs_search   ncs_app   <RAILWAY_EGRESS_IP>/32  scram-sha-256
```

로컬 개발 PC에서도 같은 DB를 쓸 경우, 사무실 고정 IP를 한 줄 더 추가합니다.

```text
host    ncs_search   ncs_app   <개발PC_공인IP>/32      scram-sha-256
```

적용:

```bash
sudo systemctl reload postgresql
```

### 2-7. SSL (회사 정책에 따라)

| 정책 | 조치 |
|------|------|
| SSL 필수 | 서버에 인증서 설정 후, Railway Variables에 SSL 관련 설정 추가 (아래 5-3 참고) |
| SSL 없음 | 내부망 전용이면 비활성 가능 (Railway ↔ DB 구간이 인터넷이면 SSL 권장) |

### 2-8. 확장 모듈 (`pg_trgm`)

검색 성능 스크립트 `scripts/optimize_db_indexes.py` 가 사용합니다.  
**슈퍼유저**로 한 번 실행:

```sql
\c ncs_search
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

`ncs_app` 에게 extension 생성 권한이 없으면, DBA가 위 명령만 실행합니다.

---

## 3. 스키마·데이터 적재 (개발 PC 또는 DB 서버)

### 3-1. 프로젝트 준비

```powershell
cd D:\Website\cursor\NCS_Search
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

### 3-2. `.env` (회사 DB 가리키기)

```env
DB_HOST=<회사_DB_IP_또는_호스트명>
DB_PORT=5432
DB_NAME=ncs_search
DB_USER=ncs_app
DB_PASSWORD=<비밀번호>
APP_NAME=NCS Search API
APP_VERSION=1.0.0
```

### 3-3. 연결 테스트

```powershell
python -c "from app.db import ping_db; ping_db(); print('OK')"
```

실패 시: 방화벽, `pg_hba.conf`, 비밀번호, `listen_addresses` 순으로 확인.

### 3-4. 스키마 생성

```powershell
python scripts/init_db.py
```

- 실행 파일: `sql/001_schema.sql` (T11~T28 테이블·인덱스·트리거)

### 3-5. 원본 NCS 데이터 (T11~T15)

README 기준, **원본 CSV/엑셀 적재는 별도 파이프라인**입니다.  
이미 로컬 DB에 데이터가 있다면 **3-7 덤프 복원**이 빠릅니다.

필수 테이블:

- `T11_NCS_UNITS`, `T12_PERFORMANCE_CRITERIA`, `T13_KSA`
- `T14_SUBCATEGORY_DEFINITIONS`, `T15_UNIT_DEFINITIONS`

### 3-6. 사전·인덱스·예시 (순서 중요)

```powershell
# T25 검색 인덱스 + T27 (T11~T15 필요)
python scripts/preprocess_ncs_index.py

# T21~T24, T26 최소 샘플 (없을 때)
python scripts/seed_minimum_dictionary_data.py

# 자연어 탭 예시 칩 (T28)
python scripts/seed_example_queries.py

# (선택) trigram 인덱스
python scripts/optimize_db_indexes.py
```

### 3-7. 로컬 DB → 회사 DB 이전 (이미 로컬에 전체 데이터가 있을 때)

로컬에서 덤프:

```powershell
pg_dump -h localhost -U postgres -d ncs_search -Fc -f ncs_search.dump
```

회사 DB로 복원 (스키마 비어 있거나 덮어쓸 때 주의):

```powershell
pg_restore -h <회사_DB_IP> -U ncs_app -d ncs_search -c ncs_search.dump
```

### 3-8. 데이터 검증 SQL

```sql
SELECT COUNT(*) FROM T11_NCS_UNITS;
SELECT COUNT(*) FROM T25_NCS_SEARCH_INDEX;
SELECT COUNT(*) FROM T21_DEPARTMENT_DICTIONARY;
SELECT example_text, description FROM T28_SEARCH_EXAMPLE_QUERIES WHERE is_active ORDER BY display_order;
```

---

## 4. 로컬에서 API·웹 최종 확인

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

다른 터미널:

```powershell
python scripts/smoke_test_api.py
```

브라우저: `http://127.0.0.1:8000/`

---

## 5. Railway 배포

### 5-1. GitHub 연결

1. [Railway](https://railway.app) 로그인
2. **New Project** → **Deploy from GitHub repo** → `NCS_Search` 선택
3. **PostgreSQL 플러그인은 추가하지 않음**

### 5-2. 서비스 설정

| 항목 | 값 |
|------|-----|
| Root Directory | `/` (레포 루트) |
| Builder | Nixpacks (기본) 또는 Dockerfile |

**Start Command** (Variables에 `PORT` 자동 주입):

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

**Watch Paths** (선택): `app/`, `web/`, `requirements.txt`

### 5-3. Environment Variables

Railway → Service → **Variables**:

| Key | Value |
|-----|--------|
| `DB_HOST` | 회사 DB IP/호스트 |
| `DB_PORT` | `5432` |
| `DB_NAME` | `ncs_search` |
| `DB_USER` | `ncs_app` |
| `DB_PASSWORD` | (비밀번호, Secret) |
| `APP_NAME` | `NCS Search API` |
| `APP_VERSION` | `1.0.0` |

SSL 필수인 경우 (코드에 SSL 지원 추가 후):

| Key | 예시 |
|-----|------|
| `DB_SSLMODE` | `require` |

> 현재 `app/db.py`는 SSL 옵션 미지원. SSL 오류 시 `app/db.py`에 `connect_args={"sslmode": "require"}` 추가 필요.

### 5-4. 네트워킹

1. **Generate Domain** → `https://xxxx.up.railway.app` 발급
2. **Static Outbound IP** 활성화 → 회사 DB 방화벽에 등록
3. (선택) Custom Domain + HTTPS

### 5-5. 배포 후 점검

```text
GET https://<railway-domain>/api/health
     → {"status":"ok","database":"connected"}

GET https://<railway-domain>/
     → 웹 UI

GET https://<railway-domain>/api/search/examples?limit=12
     → 예시 질문 JSON
```

`scripts/smoke_test_api.py` 의 `BASE_URL`을 Railway URL로 바꿔 실행해도 됩니다.

### 5-6. GitHub 자동 배포

- `main` 브랜치 push → Production 자동 배포
- **PR Preview**는 운영 DB를 건드리지 않도록 비활성화 권장

---

## 6. 운영·보안 체크리스트

- [ ] DB 비밀번호는 Railway Variables만, Git 커밋 금지
- [ ] `pg_hba` / 방화벽: Railway egress IP만 허용
- [ ] `ncs_app` 슈퍼유저 권한 제거
- [ ] 정기 `pg_dump` 백업 (회사 서버 cron)
- [ ] 배포 후 `/api/health` 모니터링
- [ ] UI 변경 시 `index.html`의 `?v=` 쿼리 버전 갱신 (캐시 방지)

---

## 7. 장애 대응

| 증상 | 원인 | 조치 |
|------|------|------|
| `/api/health` 500 | DB 연결 실패 | Variables, 방화벽, `pg_hba`, SSL |
| 예시 칩 없음 | T28 비어 있음 | `python scripts/seed_example_queries.py` |
| 검색 결과 빈약 | T25/T21 없음 | `preprocess_ncs_index.py`, 사전 데이터 |
| 로컬 OK, Railway만 실패 | IP 미허용 | Railway Static IP → 방화벽 등록 |
| 예전 UI | 캐시 | Ctrl+F5, `styles.css?v=` bump |

---

## 8. 역할 분담 요약

| 단계 | 담당 | 도구 |
|------|------|------|
| PostgreSQL 설치·방화벽 | 인프라/DBA | OS, `ufw`, `pg_hba` |
| 스키마·데이터 | 개발 | `init_db.py`, 덤프, `preprocess` |
| 앱 배포 | 개발 | GitHub → Railway |
| 모니터링 | 운영 | `/api/health`, 로그 |

---

## 9. 관련 파일

- `sql/001_schema.sql` — 전체 스키마
- `sql/002_search_example_queries.sql` — T28 시드
- `scripts/init_db.py` — 스키마 적용
- `scripts/preprocess_ncs_index.py` — T25/T27
- `scripts/seed_example_queries.py` — T28
- `scripts/smoke_test_api.py` — API 스모크 테스트
- `.env.example` — 환경 변수 템플릿
