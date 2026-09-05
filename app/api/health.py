from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.schemas import Health

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=Health, summary="存活檢查")
def health() -> Health:
    s = get_settings()
    return Health(status="ok", llm_mode=s.llm_mode, storage_root=s.describe_storage_root())
