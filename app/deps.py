"""FastAPI 依賴注入。測試以 app.dependency_overrides 換掉這幾個。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Path

from app.errors import MeetingNotFound
from app.llm.base import LLMClient
from app.llm.factory import get_llm_client
from app.store.base import BlobStore
from app.store.factory import get_blob_store
from app.store.repository import MeetingRepository

MEETING_ID_PATTERN = r"^\d{4}_\d{2}_\d{2}_\d{4}_[0-9a-f]{8}$"


def get_store() -> BlobStore:
    return get_blob_store()


def get_repo(store: Annotated[BlobStore, Depends(get_store)]) -> MeetingRepository:
    return MeetingRepository(store)


def get_llm() -> LLMClient:
    return get_llm_client()


MeetingIdPath = Annotated[
    str,
    Path(
        description="格式 `${YYYY_MM_DD_HHMM}_${STASH}`",
        pattern=MEETING_ID_PATTERN,
        examples=["2026_09_05_1420_a3f9c2e1"],
    ),
]


def require_meeting(
    meeting_id: MeetingIdPath, repo: Annotated[MeetingRepository, Depends(get_repo)]
) -> dict:
    doc = repo.get_meeting(meeting_id)
    if doc is None:
        raise MeetingNotFound(meeting_id)
    return doc


Repo = Annotated[MeetingRepository, Depends(get_repo)]
Store = Annotated[BlobStore, Depends(get_store)]
LLM = Annotated[LLMClient, Depends(get_llm)]
CurrentMeeting = Annotated[dict, Depends(require_meeting)]
