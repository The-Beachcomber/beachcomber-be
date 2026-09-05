"""情境 2 — 逐字稿 → 建議問題（同步）。

一次呼叫做完六件事：

1. 逐字稿立即落檔（先落檔再叫 LLM：LLM 掛了也不能弄丟語音內容）
2. 從 ledger 讀出「已經問過的問題」
3. 帶著全文逐字稿與已問問題呼叫 Hermes
4. 用正規化指紋濾掉重複
5. 把存活的問題寫回 ledger —— 前端不保存問題，這裡是唯一的記憶
6. 本輪原始產出落檔供稽核，回傳過濾後的問題

第 5 步是這個服務存在的理由。Cloud Run 隨時可能換一台容器，所以 ledger
必須是持久化儲存上的物件，並以樂觀鎖 read-modify-write。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from app.llm.base import LLMClient
from app.schemas import Finding, QuestionsRound, StoredQuestionsRound
from app.services import questions as q
from app.store.repository import MeetingRepository, now_iso

log = logging.getLogger(__name__)

# 同一場會議在同一個實例內序列化，避免前端連點造成同一輪重複呼叫 LLM。
# 跨實例的競爭由 ledger 的樂觀鎖負責。
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def submit_transcript(
    repo: MeetingRepository, llm: LLMClient, meeting_id: str, text: str
) -> QuestionsRound:
    async with _locks[meeting_id]:
        transcript = repo.append_transcript(meeting_id, text)
        full_text = repo.joined_text(transcript)

        asked_before = q.asked_questions(repo.get_ledger(meeting_id))
        raw = await llm.suggest_questions(full_text, asked_before)
        log.info("meeting=%s LLM 產出 %d 題，已問 %d 題", meeting_id, len(raw), len(asked_before))

        round_no = repo.next_round(meeting_id, "questions")
        kept_holder: dict[str, list[str]] = {}

        def mutate(ledger: dict) -> dict:
            # 重試時會以重新讀到的 ledger 再跑一次，所以過濾放在這裡面。
            asked_now = q.asked_questions(ledger)
            kept, dropped = q.dedupe(raw, asked_now)
            kept_holder["kept"], kept_holder["dropped"] = kept, dropped
            ledger.setdefault("asked", []).extend(
                {"question": text_, "round": round_no, "at": now_iso()} for text_ in kept
            )
            return ledger

        repo.update_ledger(meeting_id, mutate)
        kept = kept_holder.get("kept", [])
        dropped = kept_holder.get("dropped", [])
        if dropped:
            log.info("meeting=%s 濾掉 %d 題重複問題", meeting_id, len(dropped))

        repo.save_round(
            meeting_id,
            "questions",
            round_no,
            StoredQuestionsRound(
                round=round_no,
                created_at=now_iso(),
                raw=raw,
                questions=[Finding(question=text_) for text_ in kept],
                dropped=dropped,
                asked_before=len(asked_before),
            ).model_dump(mode="json"),
        )
        return QuestionsRound(questions=[Finding(question=text_) for text_ in kept])
