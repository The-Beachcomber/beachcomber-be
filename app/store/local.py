"""本機檔案系統 backend（開發、測試）。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.store.base import Conflict


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError(f"key 逃出 storage root：{key}")
        return p

    def read_text(self, key: str) -> str | None:
        p = self._path(key)
        if not p.is_file():
            return None
        return p.read_text(encoding="utf-8")

    def write_text(self, key: str, text: str, *, content_type: str = "application/json") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)

    def list_keys(self, prefix: str) -> list[str]:
        base = self._path(prefix)
        if not base.is_dir():
            return []
        root = self.root.resolve()
        return sorted(str(p.relative_to(root)).replace(os.sep, "/") for p in base.rglob("*") if p.is_file())

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def public_url(self, key: str) -> str:
        # as_uri() 會給正斜線，Windows 上才不會產出 file://D: 這種前端吃不下的網址
        return self._path(key).as_uri()

    def read_versioned(self, key: str) -> tuple[str | None, Any]:
        p = self._path(key)
        if not p.is_file():
            return None, None
        return p.read_text(encoding="utf-8"), p.stat().st_mtime_ns

    def write_versioned(self, key: str, text: str, token: Any) -> None:
        p = self._path(key)
        current = p.stat().st_mtime_ns if p.is_file() else None
        if current != token:
            raise Conflict(key)
        self.write_text(key, text)
