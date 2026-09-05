from __future__ import annotations

from fastapi import APIRouter

from app.deps import LLM, CurrentMeeting, Repo
from app.schemas import QuestionsRound, Transcript, TranscriptRequest
from app.services import transcript as svc

router = APIRouter(tags=["transcript"])


@router.post(
    "/api/meetings/{meeting_id}/transcript",
    response_model=QuestionsRound,
    summary="情境 2 — 送出逐字稿，直接取回建議問題",
)
async def submit_transcript(
    meeting: CurrentMeeting, repo: Repo, llm: LLM, body: TranscriptRequest
) -> QuestionsRound:
    """同步呼叫 Hermes。已問問題由本層自 ledger 帶入，前端不需傳送也不需保存。"""
    return await svc.submit_transcript(repo, llm, meeting["meeting_id"], body.text)


@router.get(
    "/api/meetings/{meeting_id}/transcript",
    response_model=Transcript,
    summary="讀取全部逐字稿",
)
def get_transcript(meeting: CurrentMeeting, repo: Repo) -> Transcript:
    doc = repo.get_transcript(meeting["meeting_id"])
    return Transcript(segments=doc.get("segments", []), text=repo.joined_text(doc))
