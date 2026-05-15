"""MySQL에 상점 데이터를 저장하는 서비스"""

from __future__ import annotations

import json
import logging

import aiomysql
from pymysql.err import IntegrityError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

WORK_NAME_MAX_LEN = 100
WORK_TITLE_MAX_LEN = 512
WORK_URL_MAX_LEN = 1024


def _truncate_str(value: object | None, max_len: int) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:max_len]


def _popularity_int(value: object | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _display_name_for_work(media: dict) -> str:
    """스펙: COALESCE(korean, romaji, english, native); `name` 컬럼 길이 제한 적용."""
    title = media.get("title") if isinstance(media.get("title"), dict) else {}
    order = (
        str(media.get("koreanTitle") or "").strip(),
        str(title.get("romaji") or "").strip(),
        str(title.get("english") or "").strip(),
        str(title.get("native") or "").strip(),
    )
    for part in order:
        if part:
            return part[:WORK_NAME_MAX_LEN]
    aid = media.get("id")
    if aid is not None:
        return f"anilist:{aid}"[:WORK_NAME_MAX_LEN]
    return "unknown"[:WORK_NAME_MAX_LEN]


def _fallback_work_name(base: str, anilist_id: int) -> str:
    suffix = f" [{anilist_id}]"
    room = WORK_NAME_MAX_LEN - len(suffix)
    head = (base[:room] if room > 0 else "").rstrip()
    return (head + suffix)[:WORK_NAME_MAX_LEN]


async def upsert_work_anilist_catalog(pool: aiomysql.Pool, media: dict) -> int:
    """
    AniList(+TMDB 보강) 1건을 `works`에 반영한다.
    우선 `anilist_id` 매칭 → 없으면 동일 `name`이면서 `anilist_id` NULL 인 레거시 행 갱신 → 그 외 INSERT.
    """
    aid_raw = media.get("id")
    if aid_raw is None:
        raise ValueError("media 에 AniList id 가 없습니다")
    anilist_id = int(aid_raw)

    title = media.get("title") if isinstance(media.get("title"), dict) else {}
    title_romaji = _truncate_str(title.get("romaji"), WORK_TITLE_MAX_LEN)
    title_english = _truncate_str(title.get("english"), WORK_TITLE_MAX_LEN)
    title_native = _truncate_str(title.get("native"), WORK_TITLE_MAX_LEN)
    korean_title = _truncate_str(media.get("koreanTitle"), WORK_TITLE_MAX_LEN)

    genres_raw = media.get("genres") or []
    if not isinstance(genres_raw, list):
        genres_raw = []
    genres_list = [str(g).strip() for g in genres_raw if isinstance(g, str) and str(g).strip()]
    genres_json = json.dumps(genres_list, ensure_ascii=False) if genres_list else None

    cover = media.get("coverImage") if isinstance(media.get("coverImage"), dict) else {}
    cover_url = _truncate_str(cover.get("extraLarge") or cover.get("large"), WORK_URL_MAX_LEN)
    tmdb_logo_url = _truncate_str(media.get("tmdbLogoUrl"), WORK_URL_MAX_LEN)
    popularity = _popularity_int(media.get("popularity"))

    name = _display_name_for_work(media)

    update_sql = """
        UPDATE works SET
            name = %s,
            title_romaji = %s,
            title_english = %s,
            title_native = %s,
            korean_title = %s,
            genres = %s,
            cover_url = %s,
            tmdb_logo_url = %s,
            popularity = %s,
            anilist_synced_at = UTC_TIMESTAMP(6)
        WHERE id = %s
    """
    params_tail = (
        name,
        title_romaji,
        title_english,
        title_native,
        korean_title,
        genres_json,
        cover_url,
        tmdb_logo_url,
        popularity,
    )

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id FROM works WHERE anilist_id = %s",
                (anilist_id,),
            )
            row = await cur.fetchone()
            if row:
                wid = int(row[0])
                await cur.execute(update_sql, (*params_tail, wid))
                logger.debug("[mysql] works UPDATE by anilist_id | id=%s anilist_id=%s", wid, anilist_id)
                return wid

            await cur.execute(
                "SELECT id, anilist_id FROM works WHERE name = %s LIMIT 1",
                (name,),
            )
            row = await cur.fetchone()
            if row:
                wid = int(row[0])
                existing_aid = row[1]
                if existing_aid is None:
                    await cur.execute(
                        """
                        UPDATE works SET
                            anilist_id = %s,
                            name = %s,
                            title_romaji = %s,
                            title_english = %s,
                            title_native = %s,
                            korean_title = %s,
                            genres = %s,
                            cover_url = %s,
                            tmdb_logo_url = %s,
                            popularity = %s,
                            anilist_synced_at = UTC_TIMESTAMP(6)
                        WHERE id = %s
                        """,
                        (
                            anilist_id,
                            *params_tail,
                            wid,
                        ),
                    )
                    logger.info(
                        "[mysql] works 레거시 행에 anilist_id 부여 | id=%s anilist_id=%s name=%r",
                        wid,
                        anilist_id,
                        name,
                    )
                    return wid
                if int(existing_aid) == anilist_id:
                    await cur.execute(update_sql, (*params_tail, wid))
                    return wid

                name = _fallback_work_name(name, anilist_id)

            insert_sql = """
                INSERT INTO works (
                    name, anilist_id, title_romaji, title_english, title_native,
                    korean_title, genres, cover_url, tmdb_logo_url, popularity,
                    anilist_synced_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6)
                )
            """
            insert_params = (
                name,
                anilist_id,
                title_romaji,
                title_english,
                title_native,
                korean_title,
                genres_json,
                cover_url,
                tmdb_logo_url,
                popularity,
            )
            try:
                await cur.execute(insert_sql, insert_params)
                new_id = int(cur.lastrowid)
                logger.debug("[mysql] works INSERT | id=%s anilist_id=%s", new_id, anilist_id)
                return new_id
            except IntegrityError:
                await cur.execute(
                    "SELECT id FROM works WHERE anilist_id = %s",
                    (anilist_id,),
                )
                row_race = await cur.fetchone()
                if row_race:
                    wid = int(row_race[0])
                    await cur.execute(update_sql, (*params_tail, wid))
                    logger.debug(
                        "[mysql] works INSERT 경합 → UPDATE by anilist_id | id=%s",
                        wid,
                    )
                    return wid
                name2 = _fallback_work_name(_display_name_for_work(media), anilist_id)
                await cur.execute(
                    insert_sql,
                    (
                        name2,
                        anilist_id,
                        title_romaji,
                        title_english,
                        title_native,
                        korean_title,
                        genres_json,
                        cover_url,
                        tmdb_logo_url,
                        popularity,
                    ),
                )
                new_id = int(cur.lastrowid)
                logger.info(
                    "[mysql] works INSERT (유니크 충돌 후 보조 이름) | id=%s anilist_id=%s name=%r",
                    new_id,
                    anilist_id,
                    name2,
                )
                return new_id


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
