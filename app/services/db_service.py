"""MySQL에 상점 데이터를 저장하는 서비스"""

from __future__ import annotations

import logging

import aiomysql

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def get_db_pool():
    """MySQL 커넥션 풀 생성"""
    settings = get_settings()
    return await aiomysql.create_pool(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_username,
        password=settings.db_password,
        db=settings.db_name,
        autocommit=True,
    )


async def _resolve_region_id(cur: aiomysql.Cursor, region: str | None) -> int | None:
    """regions.name 과 일치할 때만 region_id (aniwhere_schema)."""
    if region is None:
        return None
    name = str(region).strip()
    if not name:
        return None
    await cur.execute("SELECT id FROM regions WHERE name = %s", (name,))
    row = await cur.fetchone()
    return int(row[0]) if row else None


def _normalize_visit_tip(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _normalize_sells_ichiban_kuji(value: object) -> int | None:
    """1=취급, 0=미취급, NULL=미확인 (shops.sells_ichiban_kuji)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)) and value in (0, 1):
        return int(value)
    s = str(value).strip().lower()
    if not s or s in ("null", "none", "unknown", "미확인"):
        return None
    if s in ("1", "true", "yes", "y", "취급"):
        return 1
    if s in ("0", "false", "no", "n", "미취급"):
        return 0
    return None


async def _ensure_category_id(cur: aiomysql.Cursor, label: str) -> int:
    v = str(label).strip()
    if not v:
        raise ValueError("category 빈 문자열")
    await cur.execute("SELECT id FROM categories WHERE name = %s", (v,))
    row = await cur.fetchone()
    if row:
        return int(row[0])
    await cur.execute("INSERT INTO categories (name) VALUES (%s)", (v,))
    return int(cur.lastrowid)


async def _ensure_work_id(cur: aiomysql.Cursor, label: str) -> int:
    v = str(label).strip()
    if not v:
        raise ValueError("work 빈 문자열")
    await cur.execute("SELECT id FROM works WHERE name = %s", (v,))
    row = await cur.fetchone()
    if row:
        return int(row[0])
    await cur.execute("INSERT INTO works (name) VALUES (%s)", (v,))
    return int(cur.lastrowid)


async def get_shop_id_by_name(pool: aiomysql.Pool, name: str) -> int | None:
    """shops.name 일치 시 PK(id). Chroma 문서 id는 이 값을 문자열로 쓴다."""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM shops WHERE name = %s", (name,))
            row = await cur.fetchone()
            return int(row[0]) if row else None


async def update_shop_in_db(pool: aiomysql.Pool, shop_id: int, rdb_data: dict) -> None:
    """
    기존 shop_id 행을 rdb_data로 덮어쓴다. Chroma upsert 시 동일 shop_id를 쓰면 PK·문서 id가 일치한다.
    """
    shop_name = rdb_data.get("name")
    logger.info(
        "[mysql] UPDATE shops 시작 | shop_id=%s | name=%r | categories=%s | works=%s",
        shop_id,
        shop_name,
        len(rdb_data.get("categories") or []),
        len(rdb_data.get("works") or []),
    )
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            region_id = await _resolve_region_id(cur, rdb_data.get("region"))
            sells_ichiban = _normalize_sells_ichiban_kuji(rdb_data.get("sells_ichiban_kuji"))
            visit_tip = _normalize_visit_tip(rdb_data.get("visit_tip"))

            await cur.execute(
                """
                UPDATE shops
                SET name=%s, address=%s, px=%s, py=%s, floor=%s, region_id=%s, status=%s,
                    sells_ichiban_kuji=%s, visit_tip=%s
                WHERE id=%s
                """,
                (
                    rdb_data["name"],
                    rdb_data["address"],
                    rdb_data["px"],
                    rdb_data["py"],
                    rdb_data.get("floor"),
                    region_id,
                    rdb_data.get("status", "unverified"),
                    sells_ichiban,
                    visit_tip,
                    shop_id,
                ),
            )

            await cur.execute("DELETE FROM shop_categories WHERE shop_id = %s", (shop_id,))
            await cur.execute("DELETE FROM shop_works WHERE shop_id = %s", (shop_id,))
            await cur.execute("DELETE FROM shop_links WHERE shop_id = %s", (shop_id,))

            for category in rdb_data.get("categories") or []:
                if not str(category).strip():
                    continue
                cid = await _ensure_category_id(cur, str(category))
                await cur.execute(
                    "INSERT IGNORE INTO shop_categories (shop_id, category_id) VALUES (%s, %s)",
                    (shop_id, cid),
                )

            for work in rdb_data.get("works") or []:
                if not str(work).strip():
                    continue
                wid = await _ensure_work_id(cur, str(work))
                await cur.execute(
                    "INSERT IGNORE INTO shop_works (shop_id, work_id) VALUES (%s, %s)",
                    (shop_id, wid),
                )

            for link in rdb_data.get("links") or []:
                await cur.execute(
                    "INSERT INTO shop_links (shop_id, type, url) VALUES (%s, %s, %s)",
                    (shop_id, link["type"], link["url"]),
                )

            logger.info(
                "[mysql] UPDATE 완료 | shop_id=%s | name=%r | categories=%s links=%s",
                shop_id,
                shop_name,
                len(rdb_data.get("categories") or []),
                len(rdb_data.get("links") or []),
            )


async def save_shop_to_db(pool: aiomysql.Pool, rdb_data: dict) -> int:
    """
    RDB 데이터를 MySQL에 저장 (D:\\aniwhere-project\\aniwhere_schema.sql 동일 형식).

    반환: shop_id
    """
    shop_name = rdb_data.get("name")
    logger.info(
        "[mysql] INSERT shops 시작 | name=%r | categories=%s | works=%s",
        shop_name,
        len(rdb_data.get("categories") or []),
        len(rdb_data.get("works") or []),
    )
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            region_id = await _resolve_region_id(cur, rdb_data.get("region"))
            sells_ichiban = _normalize_sells_ichiban_kuji(rdb_data.get("sells_ichiban_kuji"))
            visit_tip = _normalize_visit_tip(rdb_data.get("visit_tip"))

            await cur.execute(
                """
                INSERT INTO shops (name, address, px, py, floor, region_id, status, sells_ichiban_kuji, visit_tip)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    rdb_data["name"],
                    rdb_data["address"],
                    rdb_data["px"],
                    rdb_data["py"],
                    rdb_data.get("floor"),
                    region_id,
                    rdb_data.get("status", "unverified"),
                    sells_ichiban,
                    visit_tip,
                ),
            )
            shop_id = int(cur.lastrowid)

            for category in rdb_data.get("categories") or []:
                if not str(category).strip():
                    continue
                cid = await _ensure_category_id(cur, str(category))
                await cur.execute(
                    "INSERT IGNORE INTO shop_categories (shop_id, category_id) VALUES (%s, %s)",
                    (shop_id, cid),
                )

            for work in rdb_data.get("works") or []:
                if not str(work).strip():
                    continue
                wid = await _ensure_work_id(cur, str(work))
                await cur.execute(
                    "INSERT IGNORE INTO shop_works (shop_id, work_id) VALUES (%s, %s)",
                    (shop_id, wid),
                )

            for link in rdb_data.get("links") or []:
                await cur.execute(
                    "INSERT INTO shop_links (shop_id, type, url) VALUES (%s, %s, %s)",
                    (shop_id, link["type"], link["url"]),
                )

            logger.info(
                "[mysql] INSERT 완료 | shop_id=%s | name=%r | categories=%s links=%s",
                shop_id,
                shop_name,
                len(rdb_data.get("categories") or []),
                len(rdb_data.get("links") or []),
            )
            return shop_id


async def upsert_shop_details(
    pool: aiomysql.Pool,
    shop_id: int,
    *,
    description: str | None,
    raw_crawl_text: str | None,
) -> None:
    """shop_details 1행 (shop_id 기준 upsert, aniwhere_schema)."""
    desc = description if (description and str(description).strip()) else None
    raw = raw_crawl_text if (raw_crawl_text and str(raw_crawl_text).strip()) else None
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO shop_details (shop_id, description, raw_crawl_text, crawled_at)
                VALUES (%s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    description = VALUES(description),
                    raw_crawl_text = VALUES(raw_crawl_text),
                    crawled_at = VALUES(crawled_at)
                """,
                (shop_id, desc, raw),
            )
    logger.info(
        "[mysql] shop_details upsert | shop_id=%s | description_chars=%s | raw_crawl_chars=%s",
        shop_id,
        len(desc) if desc else 0,
        len(raw) if raw else 0,
    )


async def shop_exists_by_name(pool: aiomysql.Pool, name: str) -> bool:
    """동일 상점명이 이미 shops 테이블에 있으면 True."""
    return (await get_shop_id_by_name(pool, name)) is not None
