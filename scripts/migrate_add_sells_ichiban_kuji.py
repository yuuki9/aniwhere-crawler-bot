"""shops.sells_ichiban_kuji 컬럼 추가 (.env MySQL). docker compose run --rm api python scripts/migrate_add_sells_ichiban_kuji.py"""

from __future__ import annotations

import asyncio
import sys

import aiomysql

from app.core.config import get_settings

COL = "sells_ichiban_kuji"
COMMENT = "제일복권(이치방쿠지) 취급: 1=취급, 0=미취급, NULL=미확인"
_AFTER_CANDIDATES = ("status",)


async def _column_exists(cur: aiomysql.Cursor, table: str, column: str) -> bool:
    await cur.execute(
        """
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        (table, column),
    )
    row = await cur.fetchone()
    return bool(row and row[0])


async def _after_clause(cur: aiomysql.Cursor) -> str:
    for name in _AFTER_CANDIDATES:
        if await _column_exists(cur, "shops", name):
            return f"AFTER {name}"
    return ""


async def main() -> int:
    s = get_settings()
    conn = await aiomysql.connect(
        host=s.mysql_host,
        port=s.mysql_port,
        user=s.mysql_user,
        password=s.mysql_password,
        db=s.mysql_database,
        autocommit=True,
    )
    try:
        async with conn.cursor() as cur:
            if await _column_exists(cur, "shops", COL):
                print(f"OK {COL} already exists — skip ALTER")
                return 0
            after = await _after_clause(cur)
            sql = (
                f"ALTER TABLE shops ADD COLUMN {COL} TINYINT(1) DEFAULT NULL COMMENT %s {after}".strip()
            )
            await cur.execute(sql, (COMMENT,))
            print(f"OK {COL} added to shops ({after or 'end'})")
            return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
