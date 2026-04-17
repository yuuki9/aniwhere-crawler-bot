"""로컬 CSV 파일에서 ShopRecord 목록을 로드한다."""

import csv
import logging
from pathlib import Path

from app.schemas.shop import ShopRecord

logger = logging.getLogger(__name__)


def load_shop_records_from_csv(path: Path) -> list[ShopRecord]:
    """
    UTF-8 BOM 허용. 필수: address, name, px, py.
    blog 미존재 시 빈 값으로 간주한다.
    """
    path = Path(path)
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []
        records: list[ShopRecord] = []
        for raw in reader:
            row = {k.strip(): (raw.get(k) or "").strip() for k in raw if k}
            if "blog" not in row:
                row["blog"] = ""
            for opt in ("insta", "x", "place", "homepage"):
                if opt not in row:
                    row[opt] = ""
            try:
                records.append(ShopRecord(**row))
            except Exception as exc:
                logger.warning("[csv] 행 스킵: %s", exc)
        logger.info(
            "[csv] 로드 완료 | path=%s | 유효_행=%s",
            path.resolve(),
            len(records),
        )
        return records
