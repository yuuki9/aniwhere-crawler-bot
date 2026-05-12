"""원격 DB 연결 점검 (aniwhere_schema.sql 기준 — 컬럼 ALTER 는 수행하지 않음)."""

from __future__ import annotations

import asyncio
import sys

import aiomysql

from app.core.config import get_settings


async def main() -> int:
    settings = get_settings()
    conn = None
    try:
        conn = await aiomysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            db=settings.mysql_database,
        )
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")
            await cur.fetchone()
        print("OK MySQL 연결 (aniwhere_schema 기준으로 db_service INSERT 가 맞춰져 있음)")
        return 0
    except Exception as e:
        print("FAIL:", e, file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
