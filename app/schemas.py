"""Pydantic 模型 — 對應 openapi.yaml 的 components.schemas。

契約以 openapi.yaml 為準，這裡是它的 Python 投影；改動請兩邊一起改。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Bucket(str, Enum):
    questions = "questions"
    prototypes = "prototypes"
    specs = "specs"


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    llm_mode: Literal["mock", "hermes"]
    storage_root: str


class Finding(BaseModel):
    """顯示給前端的單一建議問題。"""

    question: str


# ---- 情境 1：建立會議 ----------------------------------------------------


class CreateMeetingRequest(BaseModel):
    title: str = ""


class MeetingCreated(BaseModel):
    meeting_id: str
    llm_session_id: str
    title: str


class Rounds(BaseModel):
    questions: list[int] = Field(default_factory=list)
    prototypes: list[int] = Field(default_factory=list)
    specs: list[int] = Field(default_factory=list)


class Meeting(BaseModel):
    meeting_id: str
    llm_session_id: str
    created_at: datetime
    title: str
    transcript_segments: int
    rounds: Rounds
    jobs: list[dict] = Field(default_factory=list)


# ---- 情境 2：逐字稿 → 建議問題 -------------------------------------------


class TranscriptRequest(BaseModel):
    text: str


class TranscriptSegment(BaseModel):
    seq: int
    text: str
    at: datetime


class Transcript(BaseModel):
    segments: list[TranscriptSegment]
    text: str


class QuestionsRound(BaseModel):
    questions: list[Finding]


# ---- 情境 3：原型頁面 ----------------------------------------------------


class PrototypeRequest(BaseModel):
    text: str = ""


class PrototypeAccepted(BaseModel):
    prototypes: str


class PrototypeItem(BaseModel):
    page_id: str
    label: str | None = None
    url: str
    findings: list[Finding] = Field(default_factory=list)


class PrototypesRound(BaseModel):
    round: int
    created_at: datetime
    path: str | None = None
    items: list[PrototypeItem]
    findings: list[Finding]
    urls: list[str]


# ---- 情境 4：角色規格文件 ------------------------------------------------


class SpecRoleForm(BaseModel):
    roles: str = Field(description="逗號分隔的 role_id", examples=["pm,qa"])

    def role_ids(self) -> list[str]:
        return [r.strip() for r in self.roles.split(",") if r.strip()]


class SpecResult(BaseModel):
    role: str = Field(description="角色 id", examples=["ui"])
    spec: str = Field(description="該角色規格文件的 HTML 網址", examples=["…/ui.html"])


class SpecAccepted(BaseModel):
    data: list[SpecResult]


class SpecItem(BaseModel):
    role_id: str
    label: str
    url: str
    owned_atoms: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    blocking_notices: list[Finding] = Field(default_factory=list)


class SpecsRound(BaseModel):
    round: int
    created_at: datetime
    path: str | None = None
    items: list[SpecItem]
    urls: list[str]


class StoredQuestionsRound(BaseModel):
    """questions 落檔內容。比回應多帶稽核欄位，供事後回讀。"""

    round: int
    created_at: datetime
    raw: list[str] = Field(description="LLM 本輪原始輸出，未過濾")
    questions: list[Finding] = Field(description="過濾重複後、實際回給前端的問題")
    dropped: list[str] = Field(default_factory=list, description="被判定為重複而丟棄的")
    asked_before: int = Field(description="本輪呼叫 LLM 時帶入的已問問題數")
