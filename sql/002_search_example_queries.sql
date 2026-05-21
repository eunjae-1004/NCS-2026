-- 자연어 검색 화면 예시 질문 (T28)
CREATE TABLE IF NOT EXISTS T28_SEARCH_EXAMPLE_QUERIES (
    example_id SERIAL PRIMARY KEY,
    example_text TEXT NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_t28_example_active_order
ON T28_SEARCH_EXAMPLE_QUERIES(is_active, display_order, example_id);

-- 기본 예시 (중복 실행 시 example_text 기준으로 건너뜀)
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
