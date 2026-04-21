"""로컬 CSV 파일에서 ShopRecord 목록을 로드한다."""

import csv
import io
import logging
from pathlib import Path

from app.schemas.shop import ShopRecord

logger = logging.getLogger(__name__)

_CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp949", "euc-kr")


def _decode_csv_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in _CSV_ENCODINGS:
        try:
            text = raw.decode(enc)
            if enc not in ("utf-8-sig", "utf-8"):
                logger.info("[csv] 인코딩=%s | path=%s", enc, path)
            return text
        except UnicodeDecodeError:
            continue
    logger.warning("[csv] 인코딩 폴백=utf-8(replace) | path=%s", path)
    return raw.decode("utf-8", errors="replace")


def load_shop_records_from_csv(path: Path) -> list[ShopRecord]:
    """
    UTF-8 / CP949 등 자동 시도. 필수: address, name, px, py.
    blog 미존재 시 빈 값으로 간주한다.
    """
    path = Path(path)
    text = _decode_csv_text(path)
    with io.StringIO(text, newline="") as f:
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
