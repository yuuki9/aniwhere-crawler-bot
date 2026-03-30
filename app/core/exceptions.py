from fastapi import HTTPException, status


class CSVParseError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


class FileTooLargeError(HTTPException):
    def __init__(self, max_mb: int):
        super().__init__(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {max_mb}MB.",
        )


class GeminiServiceError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Gemini API error: {detail}")
