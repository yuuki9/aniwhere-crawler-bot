-- 상점 데이터만 재구축할 때 참고용 스크립트.
-- 실행 전 백업 필수. `works` 테이블은 건드리지 않는다.
-- 실제 배포 스키마(FK 순서, 테이블 유무)는 저장소의 aniwhere_schema.sql 등과 반드시 대조하세요.

SET FOREIGN_KEY_CHECKS = 0;

TRUNCATE TABLE shop_works;
TRUNCATE TABLE shop_categories;
TRUNCATE TABLE shop_links;
TRUNCATE TABLE shop_details;
TRUNCATE TABLE shops;

SET FOREIGN_KEY_CHECKS = 1;
