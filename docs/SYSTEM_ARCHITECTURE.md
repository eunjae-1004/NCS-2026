# NCS Search — 전체 시스템 구성 및 운영 프로세스

이 문서는 저장소 내 **실제 디렉터리·DB·배포·요청 흐름**을 한곳에서 파악할 수 있도록 정리합니다. 세부 플랫폼별 절차는 아래 「관련 문서」를 참고합니다.

---

## 관련 문서

| 문서 | 내용 |
|------|------|
| [README.md](../README.md) | 로컬 실행, 전처리, API smoke test |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Railway + **회사 PostgreSQL** (외부 DB) |
| [DEPLOYMENT_RAILWAY_DB.md](DEPLOYMENT_RAILWAY_DB.md) | **Railway PostgreSQL** 덤프/스키마/이전 |
| [DEPLOYMENT_RAILWAY_VERCEL.md](DEPLOYMENT_RAILWAY_VERCEL.md) | Railway API + **Vercel 정적 UI** 분리 시 CORS·URL |

---

## 1. 시스템 목적

- 사용자 입력(부서·직무·직무기술서·복합 문장)을 바탕으로 **세분류 → 직무 → NCS 능력단위**를 추천한다.
- **게스트**는 검색·기본 다운로드만 사용하고, **회원**은 JWT 기반으로 능력단위 구조도·선택 저장·엑셀 내보내기 등을 사용한다.
- NCS 원본은 `T11~T15`, 검색용 통합 인덱스는 `T25`, 로그는 `T28`, 회원·선택은 `T29~T30`에 둔다.

---

## 2. 런타임 아키텍처 (기본: Railway 단독)

현재 앱은 **한 프로세스**에서 정적 웹(`web/`)과 API를 함께 제공한다.

```mermaid
flowchart TB
  subgraph client [클라이언트]
    Browser[브라우저]
  end
  subgraph railway [Railway Service]
    Uvicorn[uvicorn app.main:app]
    Static[web/index.html, /static/*]
    API[/api/*]
    Uvicorn --> Static
    Uvicorn --> API
  end
  subgraph db [PostgreSQL]
    PG[(T11~T30)]
  end
  Browser -->|HTTPS| Uvicorn
  API -->|SQLAlchemy psycopg2| PG
```

- **진입점**: `app/main.py` — 라우터 등록, `/` → `web/index.html`, `/static` 마운트.
- **프로세스 시작**: `Procfile` 및 `railway.toml`의 `startCommand`와 `nixpacks.toml`의 `[start]`가 동일 목적(중복 정의는 의도적으로 플랫폼 호환용).

### 대안 구성

- **API만 Railway, DB는 회사 서버**: [DEPLOYMENT.md](DEPLOYMENT.md) — 방화벽·Static Egress IP 허용 필요.
- **UI는 Vercel, API는 Railway**: [DEPLOYMENT_RAILWAY_VERCEL.md](DEPLOYMENT_RAILWAY_VERCEL.md) — `app.js`의 API 베이스 URL·CORS 조정 필요.

---

## 3. 기술 스택

| 영역 | 기술 |
|------|------|
| API | Python 3, FastAPI, Uvicorn, Pydantic |
| DB 접속 | SQLAlchemy 2, psycopg2, 개별 연결은 `app/db.py`의 `get_connection()` |
| 인증 | JWT (`app/services/jwt_service.py`, `app/auth.py`) |
| 검색 | PostgreSQL FTS(`to_tsvector` 등), 사전·매핑 테이블(`T21~T24`) |
| 프론트 | 순수 HTML/CSS/JS (`web/index.html`, `web/static/app.js`) |
| 레거시 CLI/배치 | `src/search_engine.py`, `src/db.py`, `scripts/*` (전처리·평가) |

---

## 4. 디렉터리 구조(요약)

```text
app/                    # FastAPI 애플리케이션
  main.py               # 앱 조립, 정적 파일, 전역 예외 처리
  config.py             # DB_NAME, JWT 등 (.env)
  db.py                 # Engine + get_connection()
  auth.py               # Depends: 게스트/회원
  routers/              # HTTP 엔드포인트 (prefix별 분리)
  services/             # 비즈니스 로직·SQL
  schemas/              # 요청/응답 모델
web/                    # 브라우저 UI
  index.html
  static/ app.js, styles.css
sql/                    # 스키마·유지보수 SQL (아래 표 참고)
scripts/                # DB 초기화, T25 빌드, 스모크 테스트, 배포 보조
src/                    # 초기 검색 엔진·설정 (CLI·노트북과 연동)
notebooks/              # 전처리 실험용
docs/                   # 배포·본 아키텍처 문서
```

---

## 5. 데이터베이스 테이블 맵

| 구간 | 테이블 | 역할 |
|------|--------|------|
| NCS 원본 | `T11~T15` | 능력단위·요소·세분류 등 마스터 |
| 사전·매핑 | `T21~T24` | 부서/직무 동의어, 직무–능력단위 매핑 |
| 검색 인덱스 | `T25_NCS_SEARCH_INDEX` | 전처리 결과, FTS용 `search_vector` |
| 테스트 | `T26_SEARCH_TEST_CASES` | 자동 평가 입력 |
| 임베딩 준비 | `T27_NCS_EMBEDDINGS` | 확장용 텍스트 등 |
| 로그·예시 | `T28_*` | 검색 로그, 예시 질문 등 |
| 회원 | `T29_APP_USERS` | 가입·로그인 주체 |
| 선택 | `T30_USER_UNIT_SELECTIONS` | 회원별 저장 능력단위(upsert) |

**설계 규약(요지)**  
- `T11` PK는 `id_t11`. `unit_element_id` 단독 UNIQUE는 쓰지 않는다.  
- `T12`·`T13` 조인은 원본 구조에 맞게 **복합 키(예: unit_element_id + unit_category_id)** 를 고려한다.  
- 키워드 검색 구조는 이후 pgvector 하이브리드로 확장 가능하게 유지한다.

---

## 6. HTTP API 라우터 맵

| Prefix | 파일 | 주요 기능 |
|--------|------|-----------|
| `GET /api/health` | `health_router.py` | DB ping, 버전·자산 태그 |
| `/api/auth/*` | `auth_router.py` | 회원가입, 로그인, 토큰 |
| `/api/me/*` | `me_router.py` | 내 능력단위 목록/매트릭/저장·삭제, 엑셀 |
| `/api/search/*` | `search_router.py` | 통합·세분류·직무·능력단위 검색 |
| `/api/subcategories/*` | `subcategory_router.py` | 세분류별 능력단위 |
| `/api/jobs/*` | `job_router.py` | 직무별 능력단위 |
| `/api/ncs/*` | `ncs_router.py` | 분류 트리 등 |
| `/api/units/*` | `unit_router.py` | 능력단위 구조도(회원 전용 헤더) |
| `/api/download/*` | `download_router.py` | 기본 NCS 다운로드 |

자세한 경로는 배포 후 `/docs`(Swagger)에서 확인한다.

---

## 7. 주요 사용자 프로세스

### 7.1 자연어 검색(게스트/회원 공통)

1. `web/static/app.js`가 `POST /api/search/full` 등 호출.
2. `search_service` 등이 `T21~T24`·`T25`를 사용해 후보 생성.
3. 선택 시 `log_service`가 `T28`에 로그 저장(설정에 따라).

### 7.2 회원 가입·로그인

1. `POST /api/auth/signup` → `T29`에 사용자 행 생성.
2. `POST /api/auth/login` → JWT 발급, 클라이언트에 보관.
3. 이후 `Authorization: Bearer …`로 보호 API 호출.

### 7.3 능력단위 구조도·선택 저장

1. 회원 모드에서 트리/매트릭 UI 로드 → `GET /api/me/units/matrix` 등.
2. 미선택 능력단위 클릭 시 `POST /api/me/units` — `T30`에 `ON CONFLICT (user_id, unit_category_id) DO UPDATE`.
3. DB 측면에서 **UNIQUE 제약**과 **SERIAL 시퀀스 정렬**(`sql/005`)이 맞지 않으면 저장 실패 → 운영 절차 참고.

---

## 8. 환경 변수

앱은 `app/config.py` 기준으로 아래를 읽는다(로컬은 `.env`, Railway는 Variables).

- **DB**: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`  
  - Railway가 **`DATABASE_URL` 하나만** 주는 경우가 많지만, 본 프로젝트는 **`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`** 를 읽어 `URL.create`로 연결한다. Variables에서 이름을 맞추거나 URL을 분해해 넣을 것.
- **JWT**: `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES`
- **기타**: `APP_NAME`, `APP_VERSION`, `JOB_DESCRIPTION_ORG` 등

샘플: [`.env.example`](../.env.example).

---

## 9. SQL 스크립트 적용 순서(참고)

| 파일 | 용도 |
|------|------|
| `001_schema.sql` | 초기 전체 스키마(로컬·이력용). Railway 통합본이 있으면 중복 적용 주의. |
| `002_search_example_queries.sql` | 검색 예시 쿼리(참고/시드) |
| `003_user_auth.sql` | 회원 스키마 증분(004에 흡수된 경우 생략 가능) |
| `004_railway_service_schema.sql` | **Railway 빈 DB 1회** 권장 통합 스키마 |
| `005_fix_serial_sequences_after_import.sql` | CSV/덤프 임포트 후 **SERIAL 시퀀스 정렬**(T28, T11, T25, T29, T30 등) |
| `006_t30_unique_constraint_for_upsert.sql` | `ON CONFLICT` 대상 UNIQUE가 없을 때만 추가 |

---

## 10. 개발·데이터 파이프라인(로컬)

1. `python scripts/init_db.py` 또는 `004`로 스키마 준비.
2. `T11~T15` 등 원본 데이터 적재.
3. `python scripts/preprocess_ncs_index.py` — `T25`·`T27` 생성.
4. `python scripts/seed_minimum_dictionary_data.py` — 사전·매핑 최소 시드(필요 시).
5. `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
6. `python scripts/smoke_test_api.py` — 헬스·검색 등 점검.

---

## 11. 배포 프로세스(Railway 요약)

1. GitHub 연동 후 push → 빌드(Nixpacks 등) → `uvicorn` 기동.
2. Health: `GET /api/health` (`railway.toml`의 `healthcheckPath`).
3. DB는 **Railway Postgres** 또는 **외부 Postgres** — 앱이 실제로 붙는 DB와 Variables가 일치해야 함.
4. 로컬에서 Railway DB로 작업 시: `.env.railway` 등(로컬 전용, **커밋 금지**).

---

## 12. 운영 시 자주 하는 작업

- **임포트 후 저장 오류**(능력단위 선택 등): `005` 실행으로 시퀀스 정렬.
- **upsert UNIQUE 오류 메시지**: `006` 또는 `004`에 포함된 UNIQUE 여부 확인.
- **품질 평가**: `scripts/evaluate_api_quality.py`, `scripts/run_test_cases.py` — 결과는 `reports/`(.gitignore).

---

## 변경 이력

- 레포지토리 루트에 있던 `1~5단계_*.txt`, `3단계_검증.txt`에 흩어져 있던 기획 메모는 본 문서의 §5·§7·§9에 흡수한 뒤 파일을 삭제하였다.
