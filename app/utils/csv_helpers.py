"""CSV 파싱 관련 순수 유틸리티 함수 모음."""

import re
from typing import Iterator
import pandas as pd
import io


# blog 컬럼에서 URL만 추출 (쉼표 외에도 공백/줄바꿈으로 구분된 경우 대응)
_URL_PATTERN = re.compile(r"https?://[^\s,]+")


def parse_blog_links(raw: str | None) -> list[str]:
    """
    blog 컬럼 원시값에서 링크 리스트를 추출한다.

    단순 콤마 분리 외에도, URL 패턴 기반으로 추출하여 오염된 데이터에 강건하게 동작한다.
    """
    if not raw or pd.isna(raw):
        return []
    urls = _URL_PATTERN.findall(str(raw))
    if urls:
        return urls
    # URL 패턴이 없으면 콤마 분리 폴백
    return [link.strip() for link in str(raw).split(",") if link.strip()]


def iter_csv_batches(
    file_bytes: bytes,
    batch_size: int = 100,
    encoding: str = "utf-8-sig",
) -> Iterator[pd.DataFrame]:
    """
    대용량 CSV를 메모리에 한 번에 올리지 않고 batch_size 행씩 청크로 읽어 yield한다.

    pandas read_csv의 chunksize 옵션을 활용하므로 내부적으로 스트리밍 방식으로 동작한다.
    파일 바이트를 BytesIO로 감싸 업로드 파일 객체와 호환되도록 한다.

    Usage:
        for chunk in iter_csv_batches(file_bytes, batch_size=200):
            process(chunk)
    """
    buffer = io.BytesIO(file_bytes)
    reader = pd.read_csv(
        buffer,
        encoding=encoding,
        dtype=str,          # 전처리 전까지 모든 컬럼을 문자열로 읽어 타입 오류 방지
        chunksize=batch_size,
        skip_blank_lines=True,
        on_bad_lines="warn",
    )
    for chunk in reader:
        chunk.columns = chunk.columns.str.strip()  # 컬럼명 공백 제거
        yield chunk


def normalize_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    """
    청크 단위 전처리:
    - px, py를 float으로 변환 (변환 실패 시 NaN → 해당 행 drop)
    - blog 컬럼을 리스트로 변환
    - 나머지 문자열 컬럼의 앞뒤 공백 제거
    """
    str_cols = [c for c in chunk.columns if c not in ("px", "py", "blog")]
    chunk[str_cols] = chunk[str_cols].apply(lambda col: col.str.strip())

    chunk["px"] = pd.to_numeric(chunk["px"], errors="coerce")
    chunk["py"] = pd.to_numeric(chunk["py"], errors="coerce")
    invalid_coords = chunk[["px", "py"]].isna().any(axis=1)
    if invalid_coords.any():
        # 실제 서비스에서는 로그를 남기거나 별도 에러 테이블로 분리할 것
        chunk = chunk[~invalid_coords].copy()

    if "blog" in chunk.columns:
        chunk["blog"] = chunk["blog"].apply(parse_blog_links)

    return chunk
