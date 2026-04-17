-- 파이프라인(save_shop_to_db)과 맞추기: 기존 shops 테이블에 없을 수 있는 컬럼 추가
-- MySQL 8: 이미 있으면 에러 나므로, 없을 때만 실행하거나 아래를 하나씩 실행하세요.

ALTER TABLE shops ADD COLUMN region VARCHAR(100) NULL AFTER floor;
ALTER TABLE shops ADD COLUMN congestion ENUM('low', 'medium', 'high') NULL AFTER status;
ALTER TABLE shops ADD COLUMN visit_tip TEXT NULL AFTER congestion;
