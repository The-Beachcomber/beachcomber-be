from __future__ import annotations

from fastapi import APIRouter, Body

from app.deps import LLM, CurrentMeeting, Repo, Store
from app.errors import Unprocessable
from app.schemas import PrototypeAccepted, PrototypeRequest, SpecAccepted, SpecRoleForm
from app.services import artifacts as svc

router = APIRouter()


@router.post(
    "/api/meetings/{meeting_id}/prototypes",
    response_model=PrototypeAccepted,
    tags=["prototypes"],
    summary="情境 3 — 由全部逐字稿產出原型頁面",
)
async def generate_prototypes(
    meeting: CurrentMeeting,
    repo: Repo,
    store: Store,
    llm: LLM,
    body: PrototypeRequest = Body(default=PrototypeRequest()),
) -> PrototypeAccepted:
    """約 120 秒。建議正式 Demo 前先預作業，讓前端拿得到網址。"""
    return await svc.generate_prototypes(repo, store, llm, meeting["meeting_id"], body.text)


@router.post(
    "/api/meetings/{meeting_id}/specs",
    response_model=SpecAccepted,
    tags=["specs"],
    summary="情境 4 — 逐一產出指定角色的規格文件",
)
async def generate_specs(
    meeting: CurrentMeeting, repo: Repo, store: Store, llm: LLM, body: SpecRoleForm
) -> SpecAccepted:
    roles = body.role_ids()
    if not roles:
        raise Unprocessable("roles 不可為空，請以逗號分隔角色 id，例如 `pm,qa`")
    return await svc.generate_specs(repo, store, llm, meeting["meeting_id"], roles)
