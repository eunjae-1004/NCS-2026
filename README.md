# NCS Search

**전체 시스템 구성·운영 흐름·SQL 적용 순서**는 **[docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md)** 에 정리되어 있습니다.

---

사용자가 부서명, 직무명, 직무 설명, 복합 문장을 입력하면  
세분류 -> 직무 -> 능력단위 순서로 추천하는 PostgreSQL 기반 검색 프로젝트입니다.

## 1) 현재 구현 범위

- PostgreSQL 기본 스키마: `T11~T15`, `T21~T28`
- 전처리/검색 인덱스 생성: `T25_NCS_SEARCH_INDEX`
  - `T11` 중심 통합
  - `T12`, `T13` 조인 키: `unit_element_id + unit_category_id`
  - `T14` 조인 키: `subcategory_code`
  - `T15` 조인 키: `unit_category_id`
- 검색 우선순위(초기 버전):
  1. 부서명 사전 매칭 (`T21`)
  2. 직무명 사전 매칭 (`T22`)
  3. 직무-능력단위 매핑 (`T24`)
  4. T25 키워드 검색
  5. PostgreSQL Full Text Search (`to_tsvector`, `websearch_to_tsquery` / `plainto_tsquery`)
  - 참고: 직무 사전 매칭은 부서 매칭 여부와 독립적으로 수행되며, 직무가 없을 때만 부서-직무 매핑(`T23`)을 fallback으로 사용
- 검색 로그 저장: `T28_SEARCH_RESULT_LOG`
- 임베딩 확장 준비 테이블: `T27_NCS_EMBEDDINGS` (현재 `embedding_text`만 사용)

## 2) 프로젝트 구조

- `sql/001_schema.sql`: 전체 테이블/인덱스/트리거
- `src/config.py`: `.env` 기반 DB 설정 로드
- `src/db.py`: DB 연결 유틸
- `src/search_engine.py`: 검색 로직 + 결과 로그 저장
- `scripts/init_db.py`: 스키마 생성
- `scripts/build_t25_index.py`: `preprocess_ncs_index.py`와 동일 규칙으로 `T25` 재생성
- `scripts/preprocess_ncs_index.py`: pandas + SQLAlchemy 기반 전처리/T25,T27 생성
- `scripts/recommend_cli.py`: CLI 검색 실행
- `scripts/run_test_cases.py`: `T26` 기반 자동 평가 실행
- `scripts/seed_minimum_dictionary_data.py`: `T21~T24`, `T26` 최소 샘플 데이터 생성
- `notebooks/ncs_preprocess_pipeline.ipynb`: 노트북 기반 전처리 실행 버전

## 3) 실행 순서

### 3-1. 가상환경 활성화

```powershell
  .\.venv\Scripts\Activate.ps1
```

### 3-2. 패키지 설치

```powershell
  python -m pip install -r requirements.txt
```

### 3-3. 환경변수 파일 생성

`.env.example`를 복사해 `.env`를 만들고 값을 채웁니다.

```powershell
  Copy-Item .env.example .env
```

### 3-4. DB 스키마 생성

```powershell
  python scripts/init_db.py
```

### 3-5. 원본 데이터 적재

현재 프로젝트는 원본 CSV/엑셀 적재 스크립트는 아직 포함하지 않습니다.  
먼저 `T11~T15`, `T21~T24`에 데이터를 넣어야 검색이 동작합니다.

### 3-6. 전처리 + 검색 인덱스(T25) 생성 + 임베딩 텍스트(T27) 생성

```powershell
  python scripts/preprocess_ncs_index.py
```

이 스크립트는 아래를 한 번에 수행합니다.

- `T11~T15` 로딩 (pandas)
- 규칙 기반 전처리
- `T25_NCS_SEARCH_INDEX` TRUNCATE 후 INSERT
- `search_vector` 생성 (`to_tsvector`)
- `T27_NCS_EMBEDDINGS` 임베딩 텍스트 생성
- 최종 출력
  - T25 row count
  - subcategory_code별 row count
  - 샘플 10건

### 3-7. (선택) 레거시 T25 빌드 스크립트

```powershell
  python scripts/build_t25_index.py
```

### 3-8. 검색 실행

```powershell
  python scripts/recommend_cli.py "총무팀 문서관리 담당자"
```

### 3-9. 최소 사전/매핑 샘플 데이터 생성(선택)

`T21~T24`, `T26`이 비어 있으면 아래 스크립트를 먼저 실행하세요.

```powershell
  python scripts/seed_minimum_dictionary_data.py
```

### 3-10. 테스트 케이스 자동 평가 실행

```powershell
  python scripts/run_test_cases.py
```

일부만 테스트하려면 아래처럼 개수를 넣을 수 있습니다.

```powershell
  python scripts/run_test_cases.py 20
```

실행 결과는 pandas DataFrame 형태로 출력되며, 실패 케이스는 아래 CSV로 저장됩니다.

- `reports/failed_test_cases.csv`

### 3-11. 노트북으로 전처리 실행(선택)

Jupyter 환경에서 아래 노트북을 열어 셀 순서대로 실행하세요.

- `notebooks/ncs_preprocess_pipeline.ipynb`

## 4) 테스트 방법

## A. 스키마 생성 테스트

- 명령: `python scripts/init_db.py`
- 기대 결과: 오류 없이 완료 메시지 출력

## B. T25 생성 테스트

- 사전 조건: `T11~T15`에 데이터 존재
- 명령: `python scripts/preprocess_ncs_index.py`
- 기대 결과: `row_count`가 1 이상

## C. 검색 로직 테스트

- 사전 조건: `T21~T24`, `T25`에 데이터 존재
- 명령: `python scripts/recommend_cli.py "예시 입력"`
- 기대 결과:
  - `subcategory_recommendations` 존재
  - `unit_recommendations` 존재
  - `T28_SEARCH_RESULT_LOG`에 로그 1건 추가

## E. T26 자동 평가 테스트

- 명령: `python scripts/run_test_cases.py`
- 기대 결과:
  - `total`, `passed`, `failed`, `pass_rate`를 DataFrame으로 출력
  - 실패 케이스는 `reports/failed_test_cases.csv`에 저장

## D. Full Text Search 테스트

아래 SQL로 FTS 인덱스 동작 여부를 빠르게 확인할 수 있습니다.

```sql
  SELECT search_index_id, unit_name
  FROM T25_NCS_SEARCH_INDEX
  WHERE search_vector @@ websearch_to_tsquery('simple', '문서 관리')
  LIMIT 5;
```

## 5) 다음 단계(권장)

- `T26_SEARCH_TEST_CASES` 기반 자동 평가 스크립트 추가
- 추천 점수 체계 고도화(사전 가중치 + BM25 유사 점수)
- `T27` 기반 임베딩 생성 배치 추가
- pgvector 도입 후 하이브리드 검색(키워드 + 벡터) 확장

## 6) FastAPI 실행 (4단계)

### 6-1. API 앱 구조

- `app/main.py`: FastAPI 진입점
- `app/config.py`: `.env` 설정 로드
- `app/db.py`: SQLAlchemy 엔진/커넥션
- `app/schemas/search_schema.py`: Swagger용 요청/응답 스키마
- `app/services/normalize_service.py`: 입력 정규화
- `app/services/dictionary_service.py`: 부서/직무 동의어 탐지 + 매핑 조회
- `app/services/search_service.py`: 검색 로직(키워드 + FTS)
- `app/services/vector_service.py`: 향후 벡터 검색 확장용 스텁
- `app/services/log_service.py`: `T28_SEARCH_RESULT_LOG` 저장
- `app/services/ncs_service.py`: NCS 트리/구조도/다운로드 데이터 제공
- `app/routers/health_router.py`: `/api/health`
- `app/routers/search_router.py`: `/api/search/*`
- `app/routers/subcategory_router.py`: `/api/subcategories/*`
- `app/routers/job_router.py`: `/api/jobs/*`
- `app/routers/ncs_router.py`: `/api/ncs/*`
- `app/routers/unit_router.py`: `/api/units/*`
- `app/routers/download_router.py`: `/api/download/*`
- `web/index.html`: 2탭 웹앱 진입 화면
- `web/static/*`: 웹앱 스타일/스크립트

### 6-2. 서버 실행

```powershell
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### 6-3. API 목록

전체 라우터는 [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md) §6을 참고하세요. Swagger UI(`/docs`)에서 최신 목록을 확인할 수 있습니다.

**요약:**

- `GET /api/health`
- `/api/auth/*` (회원가입·로그인 등)
- `/api/me/*` (회원 능력단위·매트릭·엑셀)
- `POST /api/search/full` 및 검색 분해 API

### 6-4. 요청 예시

```json
{
  "query": "품질팀에서 불량 원인을 분석하고 개선대책을 수립한다",
  "top_k": 10
}
```

### 6-5. 최종 실테스트(권장)

서버를 실행한 뒤, 아래 스크립트로 핵심 API를 한 번에 점검할 수 있습니다.

```powershell
  python scripts/smoke_test_api.py
```

검증 항목:

- `/api/health`
- `/api/search/full`
- `/api/search/subcategories`
- `/api/search/jobs`
- `/api/search/units`
- `/api/subcategories/{subcategory_code}/units`

### 6-7. 웹앱 실행(5단계)

- 실행 후 `http://localhost:8000/` 접속
- 탭1: 분류 트리 기반 검색 + 세분류별 능력단위 조회
- 탭2: 자연어 검색 + 결과 상세 + 탭 간 점프
- 게스트/회원 모드 전환 지원
  - 게스트: 조회 + 기본 NCS 다운로드
  - 회원: 조회 + 다운로드 + 능력단위 구조도 조회

### 6-6. 검색 품질 평가(운영 준비)

`T26_SEARCH_TEST_CASES` 기준으로 API 정확도(Top1/Top5)를 점검합니다.

```powershell
  python scripts/evaluate_api_quality.py
```

생성 리포트:

- `reports/api_quality_summary.json`
- `reports/api_quality_details.csv`
- `reports/api_quality_failed.csv`
