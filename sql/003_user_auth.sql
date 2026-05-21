-- =====================================================
-- 회원 및 개인 능력단위 저장 (T29, T30)
-- =====================================================

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

CREATE INDEX IF NOT EXISTS idx_t29_email_active
ON T29_APP_USERS(email)
WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_t30_user_id
ON T30_USER_UNIT_SELECTIONS(user_id);

CREATE INDEX IF NOT EXISTS idx_t30_unit_category_id
ON T30_USER_UNIT_SELECTIONS(unit_category_id);
