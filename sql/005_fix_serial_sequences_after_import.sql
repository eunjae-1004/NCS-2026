-- CSV Import 후 SERIAL 시퀀스 재정렬 (Railway / pgAdmin에서 1회 실행)
-- 증상: T28 로그 INSERT 시 log_id already exists, 회원가입 id 중복 등

SELECT setval(
  pg_get_serial_sequence('t28_search_result_log', 'log_id'),
  COALESCE((SELECT MAX(log_id) FROM t28_search_result_log), 1)
);

SELECT setval(
  pg_get_serial_sequence('t11_ncs_units', 'id_t11'),
  COALESCE((SELECT MAX(id_t11) FROM t11_ncs_units), 1)
);

SELECT setval(
  pg_get_serial_sequence('t25_ncs_search_index', 'search_index_id'),
  COALESCE((SELECT MAX(search_index_id) FROM t25_ncs_search_index), 1)
);

SELECT setval(
  pg_get_serial_sequence('t29_app_users', 'user_id'),
  COALESCE((SELECT MAX(user_id) FROM t29_app_users), 1)
);

SELECT setval(
  pg_get_serial_sequence('t30_user_unit_selections', 'selection_id'),
  COALESCE((SELECT MAX(selection_id) FROM t30_user_unit_selections), 1)
);
