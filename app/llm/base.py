from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    """情境 2/3/4 共用的 LLM 介面。"""

    async def suggest_questions(self, transcript: str, asked: list[str]) -> list[str]:
        """回傳 LLM 本輪產出的問題（未過濾）。"""
        ...

    async def generate_prototype(self, transcript: str) -> str:
        """回傳原型頁面的 HTML 全文。"""
        ...

    async def generate_spec(self, role_id: str, transcript: str, questions: list[str]) -> str:
        """回傳單一角色規格文件的 HTML 全文。"""
        ...
