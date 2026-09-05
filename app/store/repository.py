"""會議資料存取。

落檔配置（key 相對於 STORAGE_ROOT 或 GCS bucket 根目錄）::

    meetings/{meeting_id}/meeting.json          會議 metadata
    meetings/{meeting_id}/transcript.json       逐字稿全部片段（append-only）
    meetings/{meeting_id}/questions/ledger.json 已問問題（跨輪累積，過濾用）
    meetings/{meeting_id}/questions/round-0001.json
    meetings/{meeting_id}/prototypes/round-0001.json
    meetings/{meeting_id}/specs/round-0001.json

ledger.json 是情境 2 過濾重複問題的唯一依據。前端不回傳已問問題，
所以它必須活得比單一 Cloud Run 容器久 —— 這是它落 GCS 而非放記憶體的原因。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from app.store.base import BlobStore, Conflict

MEETING_ID_RE = re.compile(r"^\d{4}_\d{2}_\d{2}_\d{4}_[0-9a-f]{8}$")
_ROUND_KEY_RE = re.compile(r"/(questions|prototypes|specs)/round-(\d{4})\.json$")

MAX_WRITE_RETRIES = 5


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(tzinfo=None).isoformat(timespec="seconds")


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


class MeetingRepository:
    def __init__(self, store: BlobStore) -> None:
        self.store = store

    # ---- key 組裝 -------------------------------------------------------

    @staticmethod
    def meeting_prefix(meeting_id: str) -> str:
        return f"meetings/{meeting_id}"

    def meeting_key(self, meeting_id: str) -> str:
        return f"{self.meeting_prefix(meeting_id)}/meeting.json"

    def transcript_key(self, meeting_id: str) -> str:
        return f"{self.meeting_prefix(meeting_id)}/transcript.json"

    def ledger_key(self, meeting_id: str) -> str:
        return f"{self.meeting_prefix(meeting_id)}/questions/ledger.json"

    def round_key(self, meeting_id: str, bucket: str, n: int) -> str:
        return f"{self.meeting_prefix(meeting_id)}/{bucket}/round-{n:04d}.json"

    # ---- 會議 -----------------------------------------------------------

    def create_meeting(self, meeting: dict) -> None:
        self.store.write_text(self.meeting_key(meeting["meeting_id"]), _dumps(meeting))

    def get_meeting(self, meeting_id: str) -> dict | None:
        raw = self.store.read_text(self.meeting_key(meeting_id))
        return json.loads(raw) if raw else None

    def exists(self, meeting_id: str) -> bool:
        return self.store.exists(self.meeting_key(meeting_id))

    # ---- 逐字稿 ---------------------------------------------------------

    def get_transcript(self, meeting_id: str) -> dict:
        raw = self.store.read_text(self.transcript_key(meeting_id))
        return json.loads(raw) if raw else {"segments": []}

    def append_transcript(self, meeting_id: str, text: str) -> dict:
        """附加一段逐字稿，回傳附加後的完整逐字稿。"""
        key = self.transcript_key(meeting_id)
        for _ in range(MAX_WRITE_RETRIES):
            raw, token = self.store.read_versioned(key)
            doc = json.loads(raw) if raw else {"segments": []}
            doc["segments"].append(
                {"seq": len(doc["segments"]) + 1, "text": text, "at": now_iso()}
            )
            try:
                self.store.write_versioned(key, _dumps(doc), token)
            except Conflict:
                continue
            return doc
        raise RuntimeError(f"逐字稿寫入重試 {MAX_WRITE_RETRIES} 次仍衝突：{meeting_id}")

    @staticmethod
    def joined_text(transcript: dict) -> str:
        return "\n".join(seg["text"] for seg in transcript.get("segments", []))

    # ---- 輪次 -----------------------------------------------------------

    def next_round(self, meeting_id: str, bucket: str) -> int:
        return max(self.list_rounds(meeting_id).get(bucket, [0]) or [0]) + 1

    def list_rounds(self, meeting_id: str) -> dict[str, list[int]]:
        rounds: dict[str, list[int]] = {"questions": [], "prototypes": [], "specs": []}
        for key in self.store.list_keys(self.meeting_prefix(meeting_id)):
            m = _ROUND_KEY_RE.search(key.replace("\\", "/"))
            if m:
                rounds[m.group(1)].append(int(m.group(2)))
        return {k: sorted(v) for k, v in rounds.items()}

    def save_round(self, meeting_id: str, bucket: str, n: int, payload: dict) -> str:
        key = self.round_key(meeting_id, bucket, n)
        payload = {**payload, "path": key}
        self.store.write_text(key, _dumps(payload))
        return key

    def get_round(self, meeting_id: str, bucket: str, n: int) -> dict | None:
        raw = self.store.read_text(self.round_key(meeting_id, bucket, n))
        return json.loads(raw) if raw else None

    # ---- 已問問題 ledger -------------------------------------------------

    def get_ledger(self, meeting_id: str) -> dict:
        raw = self.store.read_text(self.ledger_key(meeting_id))
        return json.loads(raw) if raw else {"meeting_id": meeting_id, "asked": []}

    def update_ledger(self, meeting_id: str, mutate) -> dict:
        """read-modify-write，帶樂觀鎖重試。

        `mutate(ledger) -> ledger` 會在每次重試時以「重新讀到的最新 ledger」
        再跑一遍，所以過濾邏輯必須放進 mutate 裡，不能先算好再寫。
        """
        key = self.ledger_key(meeting_id)
        for _ in range(MAX_WRITE_RETRIES):
            raw, token = self.store.read_versioned(key)
            ledger = json.loads(raw) if raw else {"meeting_id": meeting_id, "asked": []}
            updated = mutate(ledger)
            updated["updated_at"] = now_iso()
            try:
                self.store.write_versioned(key, _dumps(updated), token)
            except Conflict:
                continue
            return updated
        raise RuntimeError(f"ledger 寫入重試 {MAX_WRITE_RETRIES} 次仍衝突：{meeting_id}")
