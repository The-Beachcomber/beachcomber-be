from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.store.base import BlobStore


@lru_cache
def get_blob_store() -> BlobStore:
    s = get_settings()
    if s.storage_backend == "gcs":
        from app.store.gcs import GCSBlobStore

        return GCSBlobStore(s.gcs_bucket, s.gcs_public_base_url)
    from app.store.local import LocalBlobStore

    return LocalBlobStore(s.storage_root)
