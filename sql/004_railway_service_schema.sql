-- =============================================================================
-- NCS Search — Railway PostgreSQL 서비스 운영용 통합 스키마
-- =============================================================================
-- 대상: Railway PostgreSQL (빈 DB에 최초 1회 실행)
-- 포함: 확장 모듈, 테이블(T11~T31), 인덱스, 트리거, 예시 질문 시드(선택)
--
-- 실행 방법 (Railway Query / psql):
--   psql "$DATABASE_URL" -f sql/004_railway_service_schema.sql
--
-- 스키마 적용 후 데이터 적재 (개발 PC에서 .env → Railway DB):
--   1) T11~T15 원본 적재 (CSV/덤프)
--   2) python scripts/preprocess_ncs_index.py   -- T25, T27
--   3) python scripts/seed_minimum_dictionary_data.py  -- T21~T24, T26(선택)
--   4) python scripts/seed_example_queries.py  -- T28 (본 파일 시드와 중복 가능)
--
-- 앱(Railway) 환경 변수:
--   DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
--   JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_MINUTES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 0. 확장 모듈 (검색 성능)
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- pgvector는 현재 FTS 검색만 사용 시 필수 아님. 벡터 검색 도입 시:
-- CREATE EXTENSION IF NOT EXISTS vector;

-- -----------------------------------------------------------------------------
-- 1. 공통 함수
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------------------------
-- 2. NCS 원본 (T11~T15)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS T11_NCS_UNITS (
    id_t11 SERIAL PRIMARY KEY,
    unit_element_id VARCHAR(50),
    subclass_code VARCHAR(50),
    subcategory_code VARCHAR(50),
    unit_category_id VARCHAR(50),
    major_category_name VARCHAR(100),
    middle_category_name VARCHAR(100),
    minor_category_name VARCHAR(100),
    subcategory_name VARCHAR(100),
    unit_name VARCHAR(200),
    unit_element_name VARCHAR(200),
    level VARCHAR(20),
    base_year VARCHAR(10),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS T12_PERFORMANCE_CRITERIA (
    id_t12 SERIAL PRIMARY KEY,
    unit_category_id VARCHAR(50),
    unit_element_id VARCHAR(50),
    criteria_no VARCHAR(20),
    criteria_text TEXT,
    base_year VARCHAR(10),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS T13_KSA (
    id_t13 SERIAL PRIMARY KEY,
    unit_category_id VARCHAR(50),
    unit_element_id VARCHAR(50),
    ksa_type VARCHAR(20),
    ksa_text TEXT,
    base_year VARCHAR(10),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS T14_SUBCATEGORY_DEFINITIONS (
    id_t14 SERIAL PRIMARY KEY,
    subcategory_code VARCHAR(50),
    subcategory_name VARCHAR(100),
    subcategory_definition TEXT,
    base_year VARCHAR(10),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS T15_UNIT_DEFINITIONS (
    id_t15 SERIAL PRIMARY KEY,
    unit_category_id VARCHAR(50),
    unit_name VARCHAR(200),
    unit_definition TEXT,
    level VARCHAR(20),
    base_year VARCHAR(10),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- 3. 사전·매핑 (T21~T24)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS T21_DEPARTMENT_DICTIONARY (
    department_id SERIAL PRIMARY KEY,
    standard_department_name VARCHAR(100) NOT NULL,
    synonym_name VARCHAR(100) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS T22_JOB_DICTIONARY (
    job_id SERIAL PRIMARY KEY,
    standard_job_name VARCHAR(100) NOT NULL,
    synonym_name VARCHAR(100) NOT NULL,
    job_description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS T23_DEPARTMENT_JOB_MAPPING (
    mapping_id SERIAL PRIMARY KEY,
    standard_department_name VARCHAR(100) NOT NULL,
    standard_job_name VARCHAR(100) NOT NULL,
    match_weight NUMERIC(5,2) DEFAULT 1.00,
    mapping_reason TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS T24_JOB_UNIT_MAPPING (
    mapping_id SERIAL PRIMARY KEY,
    standard_job_name VARCHAR(100) NOT NULL,
    unit_category_id VARCHAR(50),
    unit_name VARCHAR(200),
    match_weight NUMERIC(5,2) DEFAULT 1.00,
    mapping_reason TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- 4. 검색 인덱스·로그 (T25, T26, T27, T28)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS T25_NCS_SEARCH_INDEX (
    search_index_id SERIAL PRIMARY KEY,
    id_t11 INTEGER,
    unit_category_id VARCHAR(50),
    unit_element_id VARCHAR(50),
    subcategory_code VARCHAR(50),
    major_category_name VARCHAR(100),
    middle_category_name VARCHAR(100),
    minor_category_name VARCHAR(100),
    subcategory_name VARCHAR(100),
    unit_name VARCHAR(200),
    unit_element_name VARCHAR(200),
    unit_definition TEXT,
    subcategory_definition TEXT,
    performance_criteria_text TEXT,
    knowledge_text TEXT,
    skill_text TEXT,
    attitude_text TEXT,
    integrated_search_text TEXT,
    normalized_search_text TEXT,
    keyword_text TEXT,
    subcategory_search_text TEXT,
    subcategory_keyword_text TEXT,
    search_vector tsvector,
    base_year VARCHAR(10),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_t25_t11
        FOREIGN KEY (id_t11)
        REFERENCES T11_NCS_UNITS(id_t11)
        ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS T26_SEARCH_TEST_CASES (
    test_case_id SERIAL PRIMARY KEY,
    input_text TEXT NOT NULL,
    input_type VARCHAR(50),
    expected_subcategory_code VARCHAR(50),
    expected_subcategory_name VARCHAR(100),
    expected_job_name VARCHAR(100),
    expected_unit_category_id VARCHAR(50),
    expected_unit_name VARCHAR(200),
    test_memo TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS T28_SEARCH_EXAMPLE_QUERIES (
    example_id SERIAL PRIMARY KEY,
    example_text TEXT NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS T27_NCS_EMBEDDINGS (
    embedding_id SERIAL PRIMARY KEY,
    search_index_id INTEGER,
    id_t11 INTEGER,
    unit_category_id VARCHAR(50),
    unit_element_id VARCHAR(50),
    subcategory_code VARCHAR(50),
    embedding_target_type VARCHAR(50),
    embedding_model VARCHAR(100),
    embedding_text TEXT,
    base_year VARCHAR(10),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_t27_search_index
        FOREIGN KEY (search_index_id)
        REFERENCES T25_NCS_SEARCH_INDEX(search_index_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_t27_t11
        FOREIGN KEY (id_t11)
        REFERENCES T11_NCS_UNITS(id_t11)
        ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS T28_SEARCH_RESULT_LOG (
    log_id SERIAL PRIMARY KEY,
    input_text TEXT NOT NULL,
    normalized_input_text TEXT,
    search_type VARCHAR(50),
    recommended_subcategory_code VARCHAR(50),
    recommended_subcategory_name VARCHAR(100),
    recommended_job_name VARCHAR(100),
    recommended_unit_category_id VARCHAR(50),
    recommended_unit_name VARCHAR(200),
    keyword_score NUMERIC(6,4),
    vector_score NUMERIC(6,4),
    final_score NUMERIC(6,4),
    matched_keywords TEXT,
    recommendation_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- 5. 회원·개인 능력단위 저장 (T29, T30) — 웹 서비스 필수
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS T29_APP_USERS (
    user_id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    phone VARCHAR(30),
    company_name VARCHAR(200) NOT NULL,
    department_name VARCHAR(200) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_t29_email UNIQUE (email)
);

CREATE TABLE IF NOT EXISTS T30_USER_UNIT_SELECTIONS (
    selection_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    unit_category_id VARCHAR(50) NOT NULL,
    unit_name VARCHAR(200),
    subcategory_code VARCHAR(50),
    subcategory_name VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_t30_user
        FOREIGN KEY (user_id)
        REFERENCES T29_APP_USERS(user_id)
        ON DELETE CASCADE,
    CONSTRAINT uq_t30_user_unit UNIQUE (user_id, unit_category_id)
);

-- -----------------------------------------------------------------------------
-- 5b. 능력단위 평가 시 고려사항 (T31) — 엑셀 평가시유의사항.xlsx
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS T31_UNIT_EVALUATION_CONSIDERATIONS (
    id_t31 SERIAL PRIMARY KEY,
    excel_row_no INTEGER,
    unit_category_id VARCHAR(50) NOT NULL,
    unit_name VARCHAR(200),
    item_name VARCHAR(150) NOT NULL,
    content_text TEXT,
    source_sheet_name VARCHAR(100) NOT NULL DEFAULT '평가시고려사항',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE T31_UNIT_EVALUATION_CONSIDERATIONS IS
    'NCS 능력단위별 평가 시 고려사항(엑셀 평가시유의사항·시트 평가시고려사항)';

-- -----------------------------------------------------------------------------
-- 6. 기본 인덱스
-- -----------------------------------------------------------------------------

-- T11
CREATE INDEX IF NOT EXISTS idx_t11_unit_element_id ON T11_NCS_UNITS(unit_element_id);
CREATE INDEX IF NOT EXISTS idx_t11_unit_category_id ON T11_NCS_UNITS(unit_category_id);
CREATE INDEX IF NOT EXISTS idx_t11_unit_element_category ON T11_NCS_UNITS(unit_element_id, unit_category_id);
CREATE INDEX IF NOT EXISTS idx_t11_subcategory_code ON T11_NCS_UNITS(subcategory_code);
CREATE INDEX IF NOT EXISTS idx_t11_unit_name ON T11_NCS_UNITS(unit_name);

-- T12
CREATE INDEX IF NOT EXISTS idx_t12_unit_element_id ON T12_PERFORMANCE_CRITERIA(unit_element_id);
CREATE INDEX IF NOT EXISTS idx_t12_unit_category_id ON T12_PERFORMANCE_CRITERIA(unit_category_id);
CREATE INDEX IF NOT EXISTS idx_t12_unit_element_category ON T12_PERFORMANCE_CRITERIA(unit_element_id, unit_category_id);

-- T13
CREATE INDEX IF NOT EXISTS idx_t13_unit_element_id ON T13_KSA(unit_element_id);
CREATE INDEX IF NOT EXISTS idx_t13_unit_category_id ON T13_KSA(unit_category_id);
CREATE INDEX IF NOT EXISTS idx_t13_unit_element_category ON T13_KSA(unit_element_id, unit_category_id);

-- T14, T15
CREATE INDEX IF NOT EXISTS idx_t14_subcategory_code ON T14_SUBCATEGORY_DEFINITIONS(subcategory_code);
CREATE INDEX IF NOT EXISTS idx_t15_unit_category_id ON T15_UNIT_DEFINITIONS(unit_category_id);

-- T21~T24
CREATE INDEX IF NOT EXISTS idx_t21_synonym_name ON T21_DEPARTMENT_DICTIONARY(synonym_name);
CREATE INDEX IF NOT EXISTS idx_t22_synonym_name ON T22_JOB_DICTIONARY(synonym_name);
CREATE INDEX IF NOT EXISTS idx_t23_department_name ON T23_DEPARTMENT_JOB_MAPPING(standard_department_name);
CREATE INDEX IF NOT EXISTS idx_t23_job_name ON T23_DEPARTMENT_JOB_MAPPING(standard_job_name);
CREATE INDEX IF NOT EXISTS idx_t24_job_name ON T24_JOB_UNIT_MAPPING(standard_job_name);
CREATE INDEX IF NOT EXISTS idx_t24_unit_category_id ON T24_JOB_UNIT_MAPPING(unit_category_id);

-- T25
CREATE INDEX IF NOT EXISTS idx_t25_id_t11 ON T25_NCS_SEARCH_INDEX(id_t11);
CREATE INDEX IF NOT EXISTS idx_t25_unit_category_id ON T25_NCS_SEARCH_INDEX(unit_category_id);
CREATE INDEX IF NOT EXISTS idx_t25_unit_element_id ON T25_NCS_SEARCH_INDEX(unit_element_id);
CREATE INDEX IF NOT EXISTS idx_t25_unit_element_category ON T25_NCS_SEARCH_INDEX(unit_element_id, unit_category_id);
CREATE INDEX IF NOT EXISTS idx_t25_subcategory_code ON T25_NCS_SEARCH_INDEX(subcategory_code);
CREATE INDEX IF NOT EXISTS idx_t25_subcategory_name ON T25_NCS_SEARCH_INDEX(subcategory_name);
CREATE INDEX IF NOT EXISTS idx_t25_unit_name ON T25_NCS_SEARCH_INDEX(unit_name);
CREATE INDEX IF NOT EXISTS idx_t25_search_vector ON T25_NCS_SEARCH_INDEX USING GIN(search_vector);

-- T27, T28
CREATE INDEX IF NOT EXISTS idx_t27_search_index_id ON T27_NCS_EMBEDDINGS(search_index_id);
CREATE INDEX IF NOT EXISTS idx_t27_id_t11 ON T27_NCS_EMBEDDINGS(id_t11);
CREATE INDEX IF NOT EXISTS idx_t27_unit_element_category ON T27_NCS_EMBEDDINGS(unit_element_id, unit_category_id);
CREATE INDEX IF NOT EXISTS idx_t28_example_active_order ON T28_SEARCH_EXAMPLE_QUERIES(is_active, display_order, example_id);

-- T29, T30
CREATE INDEX IF NOT EXISTS idx_t29_email_active ON T29_APP_USERS(email) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_t30_user_id ON T30_USER_UNIT_SELECTIONS(user_id);
CREATE INDEX IF NOT EXISTS idx_t30_unit_category_id ON T30_USER_UNIT_SELECTIONS(unit_category_id);

-- T31
CREATE INDEX IF NOT EXISTS idx_t31_unit_category_id ON T31_UNIT_EVALUATION_CONSIDERATIONS(unit_category_id);
CREATE INDEX IF NOT EXISTS idx_t31_unit_item ON T31_UNIT_EVALUATION_CONSIDERATIONS(unit_category_id, item_name);

-- -----------------------------------------------------------------------------
-- 7. 검색 성능 인덱스 (trigram, scripts/optimize_db_indexes.py 와 동일)
-- -----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_t25_normalized_search_text_trgm
    ON T25_NCS_SEARCH_INDEX USING GIN (lower(normalized_search_text) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_t25_keyword_text_trgm
    ON T25_NCS_SEARCH_INDEX USING GIN (lower(keyword_text) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_t25_performance_criteria_text_trgm
    ON T25_NCS_SEARCH_INDEX USING GIN (lower(performance_criteria_text) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_t25_unit_name_trgm
    ON T25_NCS_SEARCH_INDEX USING GIN (lower(unit_name) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_t25_unit_element_name_trgm
    ON T25_NCS_SEARCH_INDEX USING GIN (lower(unit_element_name) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_t25_subcategory_name_trgm
    ON T25_NCS_SEARCH_INDEX USING GIN (lower(subcategory_name) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_t25_normalized_search_text_nospace_trgm
    ON T25_NCS_SEARCH_INDEX
    USING GIN ((replace(lower(coalesce(normalized_search_text, '')), ' ', '')) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_t25_keyword_text_nospace_trgm
    ON T25_NCS_SEARCH_INDEX
    USING GIN ((replace(lower(coalesce(keyword_text, '')), ' ', '')) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_t25_performance_criteria_nospace_trgm
    ON T25_NCS_SEARCH_INDEX
    USING GIN ((replace(lower(coalesce(performance_criteria_text, '')), ' ', '')) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_t24_job_active_weight
    ON T24_JOB_UNIT_MAPPING(standard_job_name, is_active, match_weight DESC, mapping_id ASC);

CREATE INDEX IF NOT EXISTS idx_t24_unit_active_weight
    ON T24_JOB_UNIT_MAPPING(unit_category_id, is_active, match_weight DESC, mapping_id ASC);

CREATE INDEX IF NOT EXISTS idx_t23_dept_active_weight
    ON T23_DEPARTMENT_JOB_MAPPING(standard_department_name, is_active, match_weight DESC, mapping_id ASC);

CREATE INDEX IF NOT EXISTS idx_t25_unit_category_search_index
    ON T25_NCS_SEARCH_INDEX(unit_category_id, search_index_id);

CREATE INDEX IF NOT EXISTS idx_t25_subcategory_unit_element
    ON T25_NCS_SEARCH_INDEX(subcategory_code, unit_category_id, unit_element_id);

-- -----------------------------------------------------------------------------
-- 8. updated_at 트리거
-- -----------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_t11_updated_at') THEN
        CREATE TRIGGER trg_t11_updated_at BEFORE UPDATE ON T11_NCS_UNITS
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_t12_updated_at') THEN
        CREATE TRIGGER trg_t12_updated_at BEFORE UPDATE ON T12_PERFORMANCE_CRITERIA
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_t13_updated_at') THEN
        CREATE TRIGGER trg_t13_updated_at BEFORE UPDATE ON T13_KSA
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_t14_updated_at') THEN
        CREATE TRIGGER trg_t14_updated_at BEFORE UPDATE ON T14_SUBCATEGORY_DEFINITIONS
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_t15_updated_at') THEN
        CREATE TRIGGER trg_t15_updated_at BEFORE UPDATE ON T15_UNIT_DEFINITIONS
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_t21_updated_at') THEN
        CREATE TRIGGER trg_t21_updated_at BEFORE UPDATE ON T21_DEPARTMENT_DICTIONARY
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_t22_updated_at') THEN
        CREATE TRIGGER trg_t22_updated_at BEFORE UPDATE ON T22_JOB_DICTIONARY
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_t23_updated_at') THEN
        CREATE TRIGGER trg_t23_updated_at BEFORE UPDATE ON T23_DEPARTMENT_JOB_MAPPING
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_t24_updated_at') THEN
        CREATE TRIGGER trg_t24_updated_at BEFORE UPDATE ON T24_JOB_UNIT_MAPPING
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_t25_updated_at') THEN
        CREATE TRIGGER trg_t25_updated_at BEFORE UPDATE ON T25_NCS_SEARCH_INDEX
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_t28_example_updated_at') THEN
        CREATE TRIGGER trg_t28_example_updated_at BEFORE UPDATE ON T28_SEARCH_EXAMPLE_QUERIES
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_t29_updated_at') THEN
        CREATE TRIGGER trg_t29_updated_at BEFORE UPDATE ON T29_APP_USERS
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_t31_updated_at') THEN
        CREATE TRIGGER trg_t31_updated_at BEFORE UPDATE ON T31_UNIT_EVALUATION_CONSIDERATIONS
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 9. 자연어 검색 예시 질문 시드 (선택, 중복 실행 안전)
-- -----------------------------------------------------------------------------

INSERT INTO T28_SEARCH_EXAMPLE_QUERIES (example_text, display_order, description)
SELECT v.example_text, v.display_order, v.description
FROM (
    VALUES
        ('근태관리 업무', 1, NULL),
        ('회의 준비', 2, '02020302'),
        ('고객 비대면 상담', 3, NULL),
        ('자동차 조립공정 작업', 4, NULL)
) AS v(example_text, display_order, description)
WHERE NOT EXISTS (
    SELECT 1
    FROM T28_SEARCH_EXAMPLE_QUERIES e
    WHERE e.example_text = v.example_text
);

-- -----------------------------------------------------------------------------
-- 10. 적용 확인 (선택)
-- -----------------------------------------------------------------------------
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema = 'public' AND table_name LIKE 't%'
-- ORDER BY table_name;
