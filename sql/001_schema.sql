-- =====================================================
-- NCS Search System Schema
-- PostgreSQL 기준 스키마
-- =====================================================

-- updated_at 자동 갱신 트리거 함수
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- 1. T11_NCS_UNITS
-- =====================================================
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

-- =====================================================
-- 2. T12_PERFORMANCE_CRITERIA
-- =====================================================
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

-- =====================================================
-- 3. T13_KSA
-- =====================================================
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

-- =====================================================
-- 4. T14_SUBCATEGORY_DEFINITIONS
-- =====================================================
CREATE TABLE IF NOT EXISTS T14_SUBCATEGORY_DEFINITIONS (
    id_t14 SERIAL PRIMARY KEY,

    subcategory_code VARCHAR(50),
    subcategory_name VARCHAR(100),
    subcategory_definition TEXT,

    base_year VARCHAR(10),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- 5. T15_UNIT_DEFINITIONS
-- =====================================================
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

-- =====================================================
-- 6. T21_DEPARTMENT_DICTIONARY
-- =====================================================
CREATE TABLE IF NOT EXISTS T21_DEPARTMENT_DICTIONARY (
    department_id SERIAL PRIMARY KEY,

    standard_department_name VARCHAR(100) NOT NULL,
    synonym_name VARCHAR(100) NOT NULL,

    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- 7. T22_JOB_DICTIONARY
-- =====================================================
CREATE TABLE IF NOT EXISTS T22_JOB_DICTIONARY (
    job_id SERIAL PRIMARY KEY,

    standard_job_name VARCHAR(100) NOT NULL,
    synonym_name VARCHAR(100) NOT NULL,

    job_description TEXT,
    is_active BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- 8. T23_DEPARTMENT_JOB_MAPPING
-- =====================================================
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

-- =====================================================
-- 9. T24_JOB_UNIT_MAPPING
-- =====================================================
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

-- =====================================================
-- 10. T25_NCS_SEARCH_INDEX
-- =====================================================
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

-- =====================================================
-- 11. T26_SEARCH_TEST_CASES
-- =====================================================
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

-- =====================================================
-- 12. T27_NCS_EMBEDDINGS
-- =====================================================
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

-- =====================================================
-- 13. T28_SEARCH_RESULT_LOG
-- =====================================================
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

-- =====================================================
-- 14. 인덱스 생성
-- =====================================================

-- T11
CREATE INDEX IF NOT EXISTS idx_t11_unit_element_id
ON T11_NCS_UNITS(unit_element_id);

CREATE INDEX IF NOT EXISTS idx_t11_unit_category_id
ON T11_NCS_UNITS(unit_category_id);

CREATE INDEX IF NOT EXISTS idx_t11_unit_element_category
ON T11_NCS_UNITS(unit_element_id, unit_category_id);

CREATE INDEX IF NOT EXISTS idx_t11_subcategory_code
ON T11_NCS_UNITS(subcategory_code);

CREATE INDEX IF NOT EXISTS idx_t11_unit_name
ON T11_NCS_UNITS(unit_name);

-- T12
CREATE INDEX IF NOT EXISTS idx_t12_unit_element_id
ON T12_PERFORMANCE_CRITERIA(unit_element_id);

CREATE INDEX IF NOT EXISTS idx_t12_unit_category_id
ON T12_PERFORMANCE_CRITERIA(unit_category_id);

CREATE INDEX IF NOT EXISTS idx_t12_unit_element_category
ON T12_PERFORMANCE_CRITERIA(unit_element_id, unit_category_id);

-- T13
CREATE INDEX IF NOT EXISTS idx_t13_unit_element_id
ON T13_KSA(unit_element_id);

CREATE INDEX IF NOT EXISTS idx_t13_unit_category_id
ON T13_KSA(unit_category_id);

CREATE INDEX IF NOT EXISTS idx_t13_unit_element_category
ON T13_KSA(unit_element_id, unit_category_id);

-- T14
CREATE INDEX IF NOT EXISTS idx_t14_subcategory_code
ON T14_SUBCATEGORY_DEFINITIONS(subcategory_code);

-- T15
CREATE INDEX IF NOT EXISTS idx_t15_unit_category_id
ON T15_UNIT_DEFINITIONS(unit_category_id);

-- T21~T24
CREATE INDEX IF NOT EXISTS idx_t21_synonym_name
ON T21_DEPARTMENT_DICTIONARY(synonym_name);

CREATE INDEX IF NOT EXISTS idx_t22_synonym_name
ON T22_JOB_DICTIONARY(synonym_name);

CREATE INDEX IF NOT EXISTS idx_t23_department_name
ON T23_DEPARTMENT_JOB_MAPPING(standard_department_name);

CREATE INDEX IF NOT EXISTS idx_t23_job_name
ON T23_DEPARTMENT_JOB_MAPPING(standard_job_name);

CREATE INDEX IF NOT EXISTS idx_t24_job_name
ON T24_JOB_UNIT_MAPPING(standard_job_name);

CREATE INDEX IF NOT EXISTS idx_t24_unit_category_id
ON T24_JOB_UNIT_MAPPING(unit_category_id);

-- T25
CREATE INDEX IF NOT EXISTS idx_t25_id_t11
ON T25_NCS_SEARCH_INDEX(id_t11);

CREATE INDEX IF NOT EXISTS idx_t25_unit_category_id
ON T25_NCS_SEARCH_INDEX(unit_category_id);

CREATE INDEX IF NOT EXISTS idx_t25_unit_element_id
ON T25_NCS_SEARCH_INDEX(unit_element_id);

CREATE INDEX IF NOT EXISTS idx_t25_unit_element_category
ON T25_NCS_SEARCH_INDEX(unit_element_id, unit_category_id);

CREATE INDEX IF NOT EXISTS idx_t25_subcategory_code
ON T25_NCS_SEARCH_INDEX(subcategory_code);

CREATE INDEX IF NOT EXISTS idx_t25_subcategory_name
ON T25_NCS_SEARCH_INDEX(subcategory_name);

CREATE INDEX IF NOT EXISTS idx_t25_unit_name
ON T25_NCS_SEARCH_INDEX(unit_name);

CREATE INDEX IF NOT EXISTS idx_t25_search_vector
ON T25_NCS_SEARCH_INDEX
USING GIN(search_vector);

-- T27
CREATE INDEX IF NOT EXISTS idx_t27_search_index_id
ON T27_NCS_EMBEDDINGS(search_index_id);

CREATE INDEX IF NOT EXISTS idx_t27_id_t11
ON T27_NCS_EMBEDDINGS(id_t11);

CREATE INDEX IF NOT EXISTS idx_t27_unit_element_category
ON T27_NCS_EMBEDDINGS(unit_element_id, unit_category_id);

-- updated_at 트리거
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
END $$;
