from __future__ import annotations

from fastapi import APIRouter, Body

from app.deps import CurrentMeeting, Repo
from app.errors import RoundNotFound
from app.schemas import Bucket, CreateMeetingRequest, Meeting, MeetingCreated
from app.services import meetings as svc

router = APIRouter(tags=["meetings"])


@router.post(
    "/api/meetings",
    response_model=MeetingCreated,
    status_code=201,
    summary="情境 1 — 建立會議",
)
def create_meeting(repo: Repo, body: CreateMeetingRequest = Body(default=CreateMeetingRequest())) -> MeetingCreated:
    """MVP 不收知識包；領域知識已在 LLM 端設定完成，這裡只建立會話與落檔目錄。"""
    return svc.create_meeting(repo, body.title)


@router.get("/api/meetings/{meeting_id}", response_model=Meeting, summary="讀取會議")
def get_meeting(meeting: CurrentMeeting, repo: Repo) -> Meeting:
    return svc.read_meeting(repo, meeting)


@router.get(
    "/api/meetings/{meeting_id}/{bucket}/{n}",
    summary="讀取指定輪次的原始產出",
    responses={404: {"description": "會議、產出類型或輪次不存在"}},
)
def get_round(meeting: CurrentMeeting, repo: Repo, bucket: Bucket, n: int) -> dict:
    doc = repo.get_round(meeting["meeting_id"], bucket.value, n)
    if doc is None:
        raise RoundNotFound(meeting["meeting_id"], bucket.value, n)
    return doc
