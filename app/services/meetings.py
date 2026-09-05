"""情境 1 — 會議建立與讀取。"""

from __future__ import annotations

import secrets
from datetime import datetime

from app.schemas import Meeting, MeetingCreated, Rounds
from app.store.repository import MeetingRepository, now_iso

DEFAULT_TITLE = "未命名需求會議"


def new_meeting_id(at: datetime | None = None) -> str:
    """`${YYYY_MM_DD_HHMM}_${STASH}` — 時間為會議建立時間，之後不重算。"""
    at = at or datetime.now()
    return f"{at:%Y_%m_%d_%H%M}_{secrets.token_hex(4)}"


def new_session_id() -> str:
    """Hermes 的 chat/completions 是無狀態的，session id 由本層自行維護。

    契約上它就不是主鍵：LLM 端重啟時本層可以換一個新的，前端無須感知。
    """
    return f"sess_{secrets.token_hex(8)}"


def create_meeting(repo: MeetingRepository, title: str) -> MeetingCreated:
    meeting_id = new_meeting_id()
    doc = {
        "meeting_id": meeting_id,
        "llm_session_id": new_session_id(),
        "created_at": now_iso(),
        "title": title.strip() or DEFAULT_TITLE,
    }
    repo.create_meeting(doc)
    return MeetingCreated(**doc)


def read_meeting(repo: MeetingRepository, doc: dict) -> Meeting:
    meeting_id = doc["meeting_id"]
    transcript = repo.get_transcript(meeting_id)
    return Meeting(
        meeting_id=meeting_id,
        llm_session_id=doc["llm_session_id"],
        created_at=doc["created_at"],
        title=doc["title"],
        transcript_segments=len(transcript.get("segments", [])),
        rounds=Rounds(**repo.list_rounds(meeting_id)),
        jobs=[],
    )
