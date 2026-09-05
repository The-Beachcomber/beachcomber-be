"""落檔抽象層。

Cloud Run 的容器檔案系統是暫時且每台獨立的（`/tmp` 還是記憶體），
所以正式環境用 GCS backend；`local` 只給本機開發與測試用。

`read_versioned` / `write_versioned` 提供樂觀鎖，讓「已問問題 ledger」
的 read-modify-write 在多台實例並存時不會互相覆蓋。
"""

from __future__ import annotations

from typing import Any, Protocol


class Conflict(Exception):
    """寫入時發現版本已被別人改掉。"""


class BlobStore(Protocol):
    def read_text(self, key: str) -> str | None: ...

    def write_text(self, key: str, text: str, *, content_type: str = "application/json") -> None: ...

    def list_keys(self, prefix: str) -> list[str]: ...

    def exists(self, key: str) -> bool: ...

    def public_url(self, key: str) -> str: ...

    def read_versioned(self, key: str) -> tuple[str | None, Any]:
        """回 (內容, 版本 token)。不存在時 (None, None)。"""
        ...

    def write_versioned(self, key: str, text: str, token: Any) -> None:
        """僅在版本仍為 token 時寫入，否則 raise Conflict。"""
        ...
