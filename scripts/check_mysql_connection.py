"""MySQL 연결 검증. Docker: docker compose run --rm api python scripts/check_mysql_connection.py"""

from __future__ import annotations

import asyncio
import sys

from app.services.db_service import get_db_pool


async def main() -> int:
    pool = None
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1 AS ok")
                row = await cur.fetchone()
                if row[0] != 1:
                    print("FAIL: SELECT 1 unexpected", row)
                    return 1
                await cur.execute("SELECT VERSION() AS v")
                ver = await cur.fetchone()
                await cur.execute(
                    "SELECT COUNT(*) AS c FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
                tc = await cur.fetchone()
        print("OK MySQL 연결 성공")
        print(f"  버전: {ver[0]}")
        print(f"  현재 DB 테이블 수: {tc[0]}")
        return 0
    except Exception as e:
        print("FAIL:", e, file=sys.stderr)
        return 1
    finally:
        if pool is not None:
            pool.close()
            await pool.wait_closed()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
