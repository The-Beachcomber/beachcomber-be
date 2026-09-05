"""GCS backend（Cloud Run 正式環境）。

用 generation precondition 做樂觀鎖：`if_generation_match=0` 代表「只在物件
還不存在時建立」，帶既有 generation 則代表「只在沒被別人改過時覆寫」。
"""

from __future__ import annotations

from typing import Any

from app.store.base import Conflict


class GCSBlobStore:
    def __init__(self, bucket_name: str, public_base_url: str = "") -> None:
        from google.cloud import storage  # 延遲載入，local 模式不需要憑證

        if not bucket_name:
            raise ValueError("STORAGE_BACKEND=gcs 但未設定 GCS_BUCKET")
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)
        self.bucket_name = bucket_name
        self.public_base_url = public_base_url.rstrip("/")

    def read_text(self, key: str) -> str | None:
        blob = self._bucket.blob(key)
        if not blob.exists():
            return None
        return blob.download_as_text(encoding="utf-8")

    def write_text(self, key: str, text: str, *, content_type: str = "application/json") -> None:
        self._bucket.blob(key).upload_from_string(text, content_type=f"{content_type}; charset=utf-8")

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(b.name for b in self._client.list_blobs(self._bucket, prefix=prefix))

    def exists(self, key: str) -> bool:
        return self._bucket.blob(key).exists()

    def public_url(self, key: str) -> str:
        if self.public_base_url:
            return f"{self.public_base_url}/{key}"
        return f"https://storage.googleapis.com/{self.bucket_name}/{key}"

    def read_versioned(self, key: str) -> tuple[str | None, Any]:
        blob = self._bucket.get_blob(key)
        if blob is None:
            return None, None
        return blob.download_as_text(encoding="utf-8"), blob.generation

    def write_versioned(self, key: str, text: str, token: Any) -> None:
        from google.api_core.exceptions import PreconditionFailed

        blob = self._bucket.blob(key)
        try:
            blob.upload_from_string(
                text,
                content_type="application/json; charset=utf-8",
                if_generation_match=0 if token is None else int(token),
            )
        except PreconditionFailed as exc:  # 有人先寫了
            raise Conflict(key) from exc
