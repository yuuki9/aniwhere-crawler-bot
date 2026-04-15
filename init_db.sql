-- Aniwhere 데이터베이스 스키마

-- shops 테이블
CREATE TABLE IF NOT EXISTS shops (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    address VARCHAR(500) NOT NULL,
    px DECIMAL(10, 7) NOT NULL,
    py DECIMAL(10, 7) NOT NULL,
    floor VARCHAR(50),
    region VARCHAR(100),
    status ENUM('active', 'unverified', 'closed') DEFAULT 'unverified',
    congestion ENUM('low', 'medium', 'high'),
    visit_tip TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_region (region),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- shop_categories 테이블
CREATE TABLE IF NOT EXISTS shop_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    shop_id INT NOT NULL,
    category_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE,
    UNIQUE KEY unique_shop_category (shop_id, category_name),
    INDEX idx_category (category_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- shop_works 테이블
CREATE TABLE IF NOT EXISTS shop_works (
    id INT AUTO_INCREMENT PRIMARY KEY,
    shop_id INT NOT NULL,
    work_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE,
    UNIQUE KEY unique_shop_work (shop_id, work_name),
    INDEX idx_work (work_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- shop_links 테이블
CREATE TABLE IF NOT EXISTS shop_links (
    id INT AUTO_INCREMENT PRIMARY KEY,
    shop_id INT NOT NULL,
    link_type ENUM('blog', 'insta', 'x', 'place', 'homepage') NOT NULL,
    url VARCHAR(1000) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE,
    UNIQUE KEY unique_shop_link (shop_id, link_type, url(255)),
    INDEX idx_link_type (link_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
