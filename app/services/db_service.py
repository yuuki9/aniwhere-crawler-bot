"""MySQL에 상점 데이터를 저장하는 서비스"""

import aiomysql
from app.core.config import get_settings

settings = get_settings()


async def get_db_pool():
    """MySQL 커넥션 풀 생성"""
    return await aiomysql.create_pool(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        db=settings.mysql_database,
        autocommit=True,
    )


async def save_shop_to_db(pool: aiomysql.Pool, rdb_data: dict) -> int:
    """
    RDB 데이터를 MySQL에 저장
    
    반환: shop_id
    """
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 1. shops 테이블 저장
            await cur.execute("""
                INSERT INTO shops (name, address, px, py, floor, region, status, congestion, visit_tip)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                rdb_data["name"],
                rdb_data["address"],
                rdb_data["px"],
                rdb_data["py"],
                rdb_data.get("floor"),
                rdb_data.get("region"),
                rdb_data.get("status", "unverified"),
                rdb_data.get("congestion"),
                rdb_data.get("visit_tip"),
            ))
            shop_id = cur.lastrowid
            
            # 2. categories 저장
            for category in rdb_data.get("categories", []):
                await cur.execute("""
                    INSERT INTO shop_categories (shop_id, category_name)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE category_name=category_name
                """, (shop_id, category))
            
            # 3. works 저장
            for work in rdb_data.get("works", []):
                await cur.execute("""
                    INSERT INTO shop_works (shop_id, work_name)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE work_name=work_name
                """, (shop_id, work))
            
            # 4. links 저장
            for link in rdb_data.get("links", []):
                await cur.execute("""
                    INSERT INTO shop_links (shop_id, link_type, url)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE url=url
                """, (shop_id, link["type"], link["url"]))
            
            return shop_id


async def shop_exists_by_name(pool: aiomysql.Pool, name: str) -> bool:
    """동일 상점명이 이미 shops 테이블에 있으면 True."""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM shops WHERE name = %s", (name,))
            row = await cur.fetchone()
            return row is not None
