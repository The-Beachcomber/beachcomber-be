"""情境 3 / 4 — 原型頁面與角色規格文件。

兩者形狀相同：叫 LLM 產 HTML → 落到 GCS → 回可直接渲染的公開網址。
"""

from __future__ import annotations

import asyncio
import logging

from app.llm.base import LLMClient
from app.schemas import (
    PrototypeAccepted,
    PrototypeItem,
    PrototypesRound,
    SpecAccepted,
    SpecItem,
    SpecResult,
    SpecsRound,
)
from app.services import questions as q
from app.store.base import BlobStore
from app.store.repository import MeetingRepository, now_iso

log = logging.getLogger(__name__)


def _publish(store: BlobStore, key: str, html: str) -> str:
    store.write_text(key, html, content_type="text/html")
    return store.public_url(key)


async def generate_prototypes(
    repo: MeetingRepository, store: BlobStore, llm: LLMClient, meeting_id: str, text: str
) -> PrototypeAccepted:
    full_text = text.strip() or repo.joined_text(repo.get_transcript(meeting_id))
    round_no = repo.next_round(meeting_id, "prototypes")

    html = await llm.generate_prototype(full_text)
    key = f"{repo.meeting_prefix(meeting_id)}/prototypes/round-{round_no:04d}/index.html"
    url = _publish(store, key, html)

    repo.save_round(
        meeting_id,
        "prototypes",
        round_no,
        PrototypesRound(
            round=round_no,
            created_at=now_iso(),
            items=[PrototypeItem(page_id="P-01", label="黑客松主題選擇流程", url=url)],
            findings=[],
            urls=[url],
        ).model_dump(mode="json"),
    )
    return PrototypeAccepted(prototypes=url)


async def generate_specs(
    repo: MeetingRepository, store: BlobStore, llm: LLMClient, meeting_id: str, roles: list[str]
) -> SpecAccepted:
    full_text = repo.joined_text(repo.get_transcript(meeting_id))
    asked = q.asked_questions(repo.get_ledger(meeting_id))
    round_no = repo.next_round(meeting_id, "specs")

    async def one(role_id: str) -> SpecResult:
        html = await llm.generate_spec(role_id, full_text, asked)
        key = f"{repo.meeting_prefix(meeting_id)}/specs/round-{round_no:04d}/{role_id}.html"
        return SpecResult(role=role_id, spec=_publish(store, key, html))

    # 每個角色各一次 LLM 呼叫，併發跑，總時間才不會隨角色數線性增加。
    results = await asyncio.gather(*(one(r) for r in roles))

    repo.save_round(
        meeting_id,
        "specs",
        round_no,
        SpecsRound(
            round=round_no,
            created_at=now_iso(),
            items=[SpecItem(role_id=r.role, label=r.role, url=r.spec) for r in results],
            urls=[r.spec for r in results],
        ).model_dump(mode="json"),
    )
    return SpecAccepted(data=list(results))
