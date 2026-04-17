"""MySQL에 상점 데이터를 저장하는 서비스"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import aiomysql

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_tunnel_lock = threading.Lock()
_tunnel = None


def _parse_bastion(bastion: str, ssh_username: str) -> tuple[str, str]:
    bastion = bastion.strip()
    if not bastion:
        raise ValueError("MYSQL_SSH_BASTION 이 비어 있습니다")
    if "@" in bastion:
        user, _, host = bastion.partition("@")
        user = user.strip()
        host = host.strip()
        if ssh_username.strip():
            user = ssh_username.strip()
        if not user or not host:
            raise ValueError("MYSQL_SSH_BASTION 형식은 user@host 또는 host (+ MYSQL_SSH_USERNAME) 입니다")
        return user, host
    user = ssh_username.strip() or "ec2-user"
    return user, bastion


def ensure_mysql_ssh_tunnel() -> None:
    """베스천 SSH 터널을 띄운다. 이미 떠 있으면 무시."""
    global _tunnel

    settings = get_settings()
    if not settings.mysql_use_ssh_tunnel:
        return

    with _tunnel_lock:
        if _tunnel is not None:
            try:
                if _tunnel.is_active:
                    return
            except Exception:
                pass
            try:
                _tunnel.stop()
            except Exception:
                pass
            _tunnel = None

        if not settings.mysql_ssh_bastion.strip():
            raise ValueError("MYSQL_USE_SSH_TUNNEL=true 일 때 MYSQL_SSH_BASTION 이 필요합니다")
        key_path = settings.mysql_ssh_private_key.strip()
        if not key_path:
            raise ValueError("MYSQL_USE_SSH_TUNNEL=true 일 때 MYSQL_SSH_PRIVATE_KEY (PEM 경로) 가 필요합니다")

        key_path = str(Path(key_path).expanduser().resolve())
        if not Path(key_path).is_file():
            raise ValueError(f"MYSQL_SSH_PRIVATE_KEY 파일 없음: {key_path}")
        user, host = _parse_bastion(settings.mysql_ssh_bastion, settings.mysql_ssh_username)

        from sshtunnel import SSHTunnelForwarder

        key_pass = settings.mysql_ssh_private_key_password
        key_pass = key_pass if key_pass else None

        _tunnel = SSHTunnelForwarder(
            ssh_address_or_host=(host, settings.mysql_ssh_bastion_port),
            ssh_username=user,
            ssh_pkey=key_path,
            ssh_private_key_password=key_pass,
            remote_bind_address=(settings.mysql_host, settings.mysql_port),
            local_bind_address=("127.0.0.1", 0),
        )
        _tunnel.start()
        logger.info(
            "[mysql] SSH 터널 시작 | local=127.0.0.1:%s → %s:%s (via %s@%s:%s)",
            _tunnel.local_bind_port,
            settings.mysql_host,
            settings.mysql_port,
            user,
            host,
            settings.mysql_ssh_bastion_port,
        )


def stop_mysql_ssh_tunnel() -> None:
    """SSH 터널을 닫는다. 앱/파이프라인 종료 시 호출."""
    global _tunnel
    with _tunnel_lock:
        if _tunnel is not None:
            try:
                _tunnel.stop()
            except Exception as e:
                logger.warning("[mysql] SSH 터널 종료 중 경고: %s", e)
            finally:
                _tunnel = None
                logger.info("[mysql] SSH 터널 종료")


def get_effective_mysql_host_port() -> tuple[str, int]:
    """aiomysql 연결용 (host, port). 터널 사용 시 로컬 바인드 포트."""
    settings = get_settings()
    if settings.mysql_use_ssh_tunnel:
        ensure_mysql_ssh_tunnel()
        if _tunnel is None:
            raise RuntimeError("SSH 터널을 시작하지 못했습니다")
        return "127.0.0.1", _tunnel.local_bind_port
    return settings.mysql_host, settings.mysql_port


async def get_db_pool():
    """MySQL 커넥션 풀 생성"""
    settings = get_settings()
    host, port = get_effective_mysql_host_port()
    return await aiomysql.create_pool(
        host=host,
        port=port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        db=settings.mysql_database,
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

            await cur.execute(
                """
                INSERT INTO shops (name, address, px, py, floor, region_id, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    rdb_data["name"],
                    rdb_data["address"],
                    rdb_data["px"],
                    rdb_data["py"],
                    rdb_data.get("floor"),
                    region_id,
                    rdb_data.get("status", "unverified"),
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
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM shops WHERE name = %s", (name,))
            row = await cur.fetchone()
            return row is not None
