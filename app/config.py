"""執行環境設定。全部由環境變數注入，Cloud Run 上以 --set-env-vars 提供。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    llm_mode: Literal["mock", "hermes"] = "mock"
    hermes_base_url: str = "https://hackathon-hermes-heh26wyhpq-de.a.run.app"
    hermes_api_key: str = ""
    hermes_model: str = ""
    hermes_timeout_seconds: float = 120.0
    hermes_json_mode: bool = False

    # 儲存
    storage_backend: Literal["local", "gcs"] = "local"
    storage_root: Path = REPO_ROOT / "storage"
    gcs_bucket: str = ""
    gcs_public_base_url: str = ""

    # 其他
    cors_origins: str = "*"
    prompt_doc: Path = REPO_ROOT / "docs" / "LLM.md"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def chat_completions_url(self) -> str:
        return f"{self.hermes_base_url.rstrip('/')}/v1/chat/completions"

    def describe_storage_root(self) -> str:
        """回給 /api/health 的 storage_root。"""
        if self.storage_backend == "gcs":
            return f"gs://{self.gcs_bucket}"
        return str(self.storage_root.resolve())


@lru_cache
def get_settings() -> Settings:
    return Settings()
