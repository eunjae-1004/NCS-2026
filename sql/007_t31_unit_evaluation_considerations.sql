-- =============================================================================
-- T31 능력단위 「평가 시 고려사항」 원천 테이블
-- =============================================================================
-- 출처 엑셀: 평가시유의사항.xlsx (시트명: 평가시고려사항)
--   열 매핑: 번호 → excel_row_no
--           능력단위분류번호 → unit_category_id
--           능력단위명 → unit_name
--           항목 → item_name
--           값 → content_text
--
-- 선행 조건:
--   - public.set_updated_at() 함수 존재 (sql/004 또는 001 에서 생성)
--
-- 적용 예:
--   psql "$DATABASE_URL" -f sql/007_t31_unit_evaluation_considerations.sql
--
-- 참고: T11.unit_category_id 는 테이블 내 비유일(요소 행 중복)이므로 FK 는 두지 않음.
-- =============================================================================

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

COMMENT ON COLUMN T31_UNIT_EVALUATION_CONSIDERATIONS.excel_row_no IS '원본 엑셀 「번호」 열';
COMMENT ON COLUMN T31_UNIT_EVALUATION_CONSIDERATIONS.unit_category_id IS '원본 「능력단위분류번호」';
COMMENT ON COLUMN T31_UNIT_EVALUATION_CONSIDERATIONS.unit_name IS '원본 「능력단위명」';
COMMENT ON COLUMN T31_UNIT_EVALUATION_CONSIDERATIONS.item_name IS '원본 「항목」 (구분)';
COMMENT ON COLUMN T31_UNIT_EVALUATION_CONSIDERATIONS.content_text IS '원본 「값」 (내용)';

CREATE INDEX IF NOT EXISTS idx_t31_unit_category_id
    ON T31_UNIT_EVALUATION_CONSIDERATIONS(unit_category_id);

CREATE INDEX IF NOT EXISTS idx_t31_unit_item
    ON T31_UNIT_EVALUATION_CONSIDERATIONS(unit_category_id, item_name);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_t31_updated_at') THEN
        CREATE TRIGGER trg_t31_updated_at
            BEFORE UPDATE ON T31_UNIT_EVALUATION_CONSIDERATIONS
            FOR EACH ROW
            EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
