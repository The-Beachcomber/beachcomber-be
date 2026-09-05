"""建議問題的去重。

提示詞已經要求 LLM 不要重問，但那是「盡力而為」；由於前端不保存也不回傳
已問問題，中介層是唯一能保證不重複的地方，所以這裡再擋一次。

比對用正規化指紋而非原字串：全形/半形、標點、空白、大小寫差異都視為相同。
語意層級的相似（換句話說問同一件事）交給 LLM 判斷，這裡不做，避免誤殺。
"""

from __future__ import annotations

import re
import unicodedata

_STRIP_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def fingerprint(question: str) -> str:
    normalized = unicodedata.normalize("NFKC", question).casefold()
    return _STRIP_RE.sub("", normalized)


def dedupe(candidates: list[str], asked: list[str]) -> tuple[list[str], list[str]]:
    """回傳 (保留, 丟棄)。同批次內部的重複也會被丟掉。"""
    seen = {fingerprint(q) for q in asked}
    kept: list[str] = []
    dropped: list[str] = []
    for q in candidates:
        fp = fingerprint(q)
        if not fp or fp in seen:
            dropped.append(q)
            continue
        seen.add(fp)
        kept.append(q)
    return kept, dropped


def asked_questions(ledger: dict) -> list[str]:
    return [entry["question"] for entry in ledger.get("asked", [])]
