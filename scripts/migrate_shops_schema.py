"""shops 테이블을 aniwhere_schema.sql 과 맞춤 (idempotent). docker compose run --rm api python scripts/migrate_shops_schema.py"""

from __future__ import annotations

import asyncio
import sys

import aiomysql

from app.core.config import get_settings


async def _col_exists(cur: aiomysql.Cursor, table: str, column: str) -> bool:
    await cur.execute(
        """
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        (table, column),
    )
    row = await cur.fetchone()
    return bool(row and row[0])


async def _after_for_new_column(cur: aiomysql.Cursor, candidates: tuple[str, ...]) -> str:
    for name in candidates:
        if await _col_exists(cur, "shops", name):
            return name
    return ""


async def main() -> int:
    s = get_settings()
    conn = await aiomysql.connect(
        host=s.db_host,
        port=s.db_port,
        user=s.db_username,
        password=s.db_password,
        db=s.db_name,
        autocommit=True,
    )
    try:
        async with conn.cursor() as cur:
            if not await _col_exists(cur, "shops", "sells_ichiban_kuji"):
                after = await _after_for_new_column(cur, ("status",))
                pos = f" AFTER {after}" if after else ""
                await cur.execute(
                    f"""
                    ALTER TABLE shops ADD COLUMN sells_ichiban_kuji TINYINT(1) DEFAULT NULL
                    COMMENT %s{pos}
                    """.strip(),
                    ("제일복권(이치방쿠지) 취급: 1=취급, 0=미취급, NULL=미확인",),
                )
                print("OK added sells_ichiban_kuji")
            else:
                print("OK sells_ichiban_kuji already exists")

            if not await _col_exists(cur, "shops", "visit_tip"):
                after = await _after_for_new_column(cur, ("sells_ichiban_kuji", "status"))
                pos = f" AFTER {after}" if after else ""
                await cur.execute(
                    f"""
                    ALTER TABLE shops ADD COLUMN visit_tip TEXT DEFAULT NULL
                    COMMENT %s{pos}
                    """.strip(),
                    ("방문 팁 요약 (정제 파이프라인)",),
                )
                print("OK added visit_tip")
            else:
                print("OK visit_tip already exists")

            if await _col_exists(cur, "shops", "congestion"):
                await cur.execute("ALTER TABLE shops DROP COLUMN congestion")
                print("OK dropped congestion")
            else:
                print("OK no congestion column")

        print("migrate_shops_schema: done")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
