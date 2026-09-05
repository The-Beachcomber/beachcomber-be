"""錯誤型別。全部收斂成 FastAPI 預設的 `{"detail": ...}`，detail 為面向使用者的中文。"""

from __future__ import annotations

from fastapi import HTTPException


class MeetingNotFound(HTTPException):
    def __init__(self, meeting_id: str) -> None:
        super().__init__(status_code=404, detail=f"找不到會議 {meeting_id}")


class RoundNotFound(HTTPException):
    def __init__(self, meeting_id: str, bucket: str, n: int) -> None:
        super().__init__(
            status_code=404,
            detail=f"會議 {meeting_id} 的 {bucket} 沒有第 {n} 輪產出",
        )


class LLMUnavailable(HTTPException):
    def __init__(self, reason: str) -> None:
        super().__init__(status_code=502, detail=f"LLM 服務無法完成本次請求：{reason}")


class LLMBadOutput(HTTPException):
    """LLM 有回應，但不是規定的 JSON 形狀。"""

    def __init__(self, reason: str) -> None:
        super().__init__(status_code=502, detail=f"LLM 回傳格式不符合約定：{reason}")


class Unprocessable(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=422, detail=detail)
