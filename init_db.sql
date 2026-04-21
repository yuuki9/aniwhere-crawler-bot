-- =============================================
-- Aniwhere DB Schema (MySQL)
-- =============================================
-- 로컬 Docker MySQL 초기화용. 원본: aniwhere-project/aniwhere_schema.sql (내용 동기화)

CREATE DATABASE IF NOT EXISTS aniwhere DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE aniwhere;

CREATE TABLE regions (
    id         SMALLINT     NOT NULL AUTO_INCREMENT,
    name       VARCHAR(50)  NOT NULL COMMENT '지역명 (홍대, 강남, 신촌 등)',
    city       VARCHAR(50)  NOT NULL DEFAULT '서울',
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_regions_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE shops (
    id         BIGINT        NOT NULL AUTO_INCREMENT,
    name       VARCHAR(100)  NOT NULL COMMENT '상점명',
    address    VARCHAR(255)  NOT NULL COMMENT '도로명 주소',
    px         DECIMAL(10,7) NOT NULL COMMENT '경도',
    py         DECIMAL(10,7) NOT NULL COMMENT '위도',
    floor      VARCHAR(20)   DEFAULT NULL COMMENT '층수 (2층, 지하1층)',
    region_id  SMALLINT      DEFAULT NULL,
    status     ENUM('active','closed','unverified') NOT NULL DEFAULT 'unverified',
    sells_ichiban_kuji TINYINT(1) DEFAULT NULL COMMENT '제일복권(이치방쿠지) 취급: 1=취급, 0=미취급, NULL=미확인',
    visit_tip  TEXT          DEFAULT NULL COMMENT '방문 팁 요약 (정제 파이프라인)',
    created_at DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_shops_region (region_id),
    KEY idx_shops_location (px, py),
    CONSTRAINT fk_shops_region FOREIGN KEY (region_id) REFERENCES regions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE shop_details (
    id             BIGINT    NOT NULL AUTO_INCREMENT,
    shop_id        BIGINT    NOT NULL,
    description    TEXT      DEFAULT NULL COMMENT 'Knowledge Base용 자연어 요약',
    raw_crawl_text LONGTEXT  DEFAULT NULL COMMENT '크롤링 원문 보관',
    crawled_at     DATETIME  DEFAULT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_shop_details_shop (shop_id),
    CONSTRAINT fk_shop_details_shop FOREIGN KEY (shop_id) REFERENCES shops (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE categories (
    id   SMALLINT    NOT NULL AUTO_INCREMENT,
    name VARCHAR(50) NOT NULL COMMENT '가챠, 피규어, 굿즈, 랜덤박스 등',
    PRIMARY KEY (id),
    UNIQUE KEY uq_categories_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE shop_categories (
    shop_id     BIGINT   NOT NULL,
    category_id SMALLINT NOT NULL,
    PRIMARY KEY (shop_id, category_id),
    CONSTRAINT fk_sc_shop     FOREIGN KEY (shop_id)     REFERENCES shops (id)      ON DELETE CASCADE,
    CONSTRAINT fk_sc_category FOREIGN KEY (category_id) REFERENCES categories (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE works (
    id   INT          NOT NULL AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL COMMENT '귀멸의 칼날, 주술회전 등',
    PRIMARY KEY (id),
    UNIQUE KEY uq_works_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE shop_works (
    shop_id BIGINT NOT NULL,
    work_id INT    NOT NULL,
    PRIMARY KEY (shop_id, work_id),
    CONSTRAINT fk_sw_shop FOREIGN KEY (shop_id) REFERENCES shops (id) ON DELETE CASCADE,
    CONSTRAINT fk_sw_work FOREIGN KEY (work_id) REFERENCES works (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE shop_links (
    id      BIGINT       NOT NULL AUTO_INCREMENT,
    shop_id BIGINT       NOT NULL,
    type    ENUM('blog','insta','x','place','homepage') NOT NULL,
    url     VARCHAR(500) NOT NULL,
    PRIMARY KEY (id),
    KEY idx_shop_links_shop (shop_id),
    CONSTRAINT fk_sl_shop FOREIGN KEY (shop_id) REFERENCES shops (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- =============================================
-- 확장용 테이블
-- =============================================

CREATE TABLE users (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    provider    ENUM('kakao','naver','google') NOT NULL,
    provider_id VARCHAR(100) NOT NULL,
    nickname    VARCHAR(50)  DEFAULT NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_provider (provider, provider_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE user_bookmarks (
    user_id    BIGINT   NOT NULL,
    shop_id    BIGINT   NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, shop_id),
    CONSTRAINT fk_ub_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_ub_shop FOREIGN KEY (shop_id) REFERENCES shops (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE shop_reviews (
    id         BIGINT    NOT NULL AUTO_INCREMENT,
    shop_id    BIGINT    NOT NULL,
    user_id    BIGINT    NOT NULL,
    rating     TINYINT   NOT NULL CHECK (rating BETWEEN 1 AND 5),
    content    TEXT      DEFAULT NULL,
    created_at DATETIME  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_reviews_shop (shop_id),
    KEY idx_reviews_user (user_id),
    CONSTRAINT fk_rv_shop FOREIGN KEY (shop_id) REFERENCES shops (id) ON DELETE CASCADE,
    CONSTRAINT fk_rv_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
