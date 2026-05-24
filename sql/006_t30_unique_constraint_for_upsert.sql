-- POST /api/me/units 에서 INSERT ... ON CONFLICT (user_id, unit_category_id) 를 씁니다.
-- T30에 이 UNIQUE 제약이 없으면 PostgreSQL 오류 → 브라우저에 "Internal server error" 로 보입니다.
-- (수동으로 테이블만 만든 경우 흔히 빠짐)

-- 이미 존재하면 오류 무시 가능: UNIQUE constraint ... already exists
ALTER TABLE t30_user_unit_selections
ADD CONSTRAINT uq_t30_user_unit UNIQUE (user_id, unit_category_id);

-- 위에서 "already exists" 오류가 나면 제약은 이미 있는 상태이므로 OK입니다.

-- 같은 (user_id, unit_category_id) 중복 행이 있으면 UNIQUE 추가 전에 중복부터 정리:
-- 예시:
-- DELETE FROM t30_user_unit_selections a
-- USING t30_user_unit_selections b
-- WHERE a.user_id = b.user_id
--   AND a.unit_category_id = b.unit_category_id
--   AND a.selection_id > b.selection_id;
