"""不呼叫 Hermes 的假 client。

用途有二：前端在 LLM 還沒好之前就能平行開發；Demo 當天 Hermes 掛掉時
把 LLM_MODE 切成 mock 就能繼續走完流程。

輸出刻意做成「每輪不同、且會重複前一輪的一題」，用來驗證中介層的去重真的有效。
"""

from __future__ import annotations

_POOL = [
    "這次黑客松的評分表裡，「完成度」的定義是什麼？是現場跑通完整流程，還是有 demo 影片即可？",
    "主題選定後，36 小時內要交付到哪個程度才算可驗收？請給一個具體的驗收條件。",
    "團隊四個人的技術棧分布是什麼？有沒有人沒碰過前端，會影響題目可行性？",
    "「AI 會議助理」這個題目需要真實的語音輸入嗎？還是可以用預錄逐字稿？",
    "評審現場的網路與裝置條件是什麼？需不需要準備離線備援？",
    "如果主題最後沒選定，誰有最終決定權？決定的時間點卡在哪一天？",
]


class MockClient:
    def __init__(self) -> None:
        self._cursor = 0

    async def suggest_questions(self, transcript: str, asked: list[str]) -> list[str]:
        start = self._cursor
        self._cursor = min(self._cursor + 2, len(_POOL))
        batch = _POOL[start : self._cursor]
        if asked:
            # 刻意重複最後一題，讓中介層的去重看得出有在作用
            batch = [asked[-1], *batch]
        return batch

    async def generate_prototype(self, transcript: str) -> str:
        return (
            "<!doctype html><meta charset='utf-8'><title>黑客松主題選擇流程</title>"
            "<h1>黑客松主題選擇流程</h1><p>mock 原型頁面</p>"
        )

    async def generate_spec(self, role_id: str, transcript: str, questions: list[str]) -> str:
        items = "".join(f"<li>{q}</li>" for q in questions)
        return (
            f"<!doctype html><meta charset='utf-8'><title>{role_id} 規格</title>"
            f"<h1>{role_id} 規格文件</h1><ul>{items}</ul>"
        )
