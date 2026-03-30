"""CSV 업로드 파일을 받아 ShopRecord 리스트로 변환하는 서비스 계층."""

import logging
from fastapi import UploadFile

from app.core.config import get_settings
from app.core.exceptions import CSVParseError, FileTooLargeError
from app.schemas.shop import ShopRecord
from app.utils.csv_helpers import iter_csv_batches, normalize_chunk

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"address", "name", "px", "py"}


async def parse_upload_to_records(file: UploadFile) -> list[ShopRecord]:
    """
    업로드된 CSV 파일을 검증하고 ShopRecord 리스트로 변환한다.

    대용량 파일을 고려해 iter_csv_batches로 청크 단위로 읽으며,
    각 청크를 normalize → Pydantic 검증 순서로 처리한다.
    """
    settings = get_settings()

    # 파일 크기 사전 검사 (Content-Length 헤더 기반 빠른 거부)
    max_bytes = settings.csv_max_file_size_mb * 1024 * 1024
    file_bytes = await file.read()
    if len(file_bytes) > max_bytes:
        raise FileTooLargeError(max_mb=settings.csv_max_file_size_mb)

    records: list[ShopRecord] = []
    parse_errors: list[str] = []

    try:
        for batch_idx, chunk in enumerate(
            iter_csv_batches(file_bytes, batch_size=settings.csv_batch_size)
        ):
            # 첫 청크에서 필수 컬럼 존재 여부 확인
            if batch_idx == 0:
                missing = REQUIRED_COLUMNS - set(chunk.columns)
                if missing:
                    raise CSVParseError(f"필수 컬럼이 없습니다: {missing}")

            chunk = normalize_chunk(chunk)

            for row_idx, row in chunk.iterrows():
                try:
                    record = ShopRecord(**row.to_dict())
                    records.append(record)
                except Exception as exc:
                    parse_errors.append(f"행 {row_idx}: {exc}")
                    logger.warning("행 파싱 실패 (row=%s): %s", row_idx, exc)

    except (CSVParseError, FileTooLargeError):
        raise
    except Exception as exc:
        raise CSVParseError(f"CSV 파일을 읽는 중 오류가 발생했습니다: {exc}") from exc

    if parse_errors:
        logger.warning("총 %d개 행에서 파싱 오류 발생", len(parse_errors))

    logger.info("CSV 파싱 완료: 총 %d건 (오류 %d건)", len(records), len(parse_errors))
    return records
