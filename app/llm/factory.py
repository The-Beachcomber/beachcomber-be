from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.llm.base import LLMClient


@lru_cache
def get_llm_client() -> LLMClient:
    s = get_settings()
    if s.llm_mode == "hermes":
        from app.llm.hermes import HermesClient

        return HermesClient(s)
    from app.llm.mock import MockClient

    return MockClient()
