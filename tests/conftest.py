from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.deps import get_llm, get_store
from app.main import create_app
from app.store.local import LocalBlobStore


class RecordingLLM:
    """記下每次收到的 asked 清單，讓測試能斷言「已問問題確實被帶進 LLM」。"""

    def __init__(self, batches: list[list[str]]) -> None:
        self.batches = batches
        self.calls: list[list[str]] = []

    async def suggest_questions(self, transcript: str, asked: list[str]) -> list[str]:
        self.calls.append(list(asked))
        return self.batches[min(len(self.calls) - 1, len(self.batches) - 1)]

    async def generate_prototype(self, transcript: str) -> str:
        return "<h1>prototype</h1>"

    async def generate_spec(self, role_id: str, transcript: str, questions: list[str]) -> str:
        return f"<h1>{role_id}</h1>"


@pytest.fixture
def storage_root(tmp_path):
    return tmp_path / "storage"


@pytest.fixture
def llm():
    return RecordingLLM([["問題 A", "問題 B"], ["問題 A", "問題 C"]])


def build_client(storage_root, llm) -> TestClient:
    """每次呼叫都建立全新的 app 實例，共用同一個 storage root。

    用來模擬 Cloud Run 換容器：程序記憶體歸零，但儲存層還在。
    """
    app = create_app()
    app.dependency_overrides[get_store] = lambda: LocalBlobStore(storage_root)
    app.dependency_overrides[get_llm] = lambda: llm
    return TestClient(app)


@pytest.fixture
def client(storage_root, llm):
    with build_client(storage_root, llm) as c:
        yield c


@pytest.fixture
def anyio_backend():
    return "asyncio"
