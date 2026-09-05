"""HermesClient 對 /v1/chat/completions 的實際請求形狀。"""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.errors import LLMUnavailable
from app.llm.hermes import HermesClient


def client_with(handler, **overrides) -> HermesClient:
    settings = Settings(
        llm_mode="hermes",
        hermes_base_url="https://hermes.example",
        hermes_api_key="k-123",
        hermes_timeout_seconds=5,
        **overrides,
    )
    return HermesClient(settings, transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_request_shape_and_prompt_substitution():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"questions": ["甲"]}'}}]})

    out = await client_with(handler).suggest_questions("逐字稿內容", ["已問過的問題"])

    assert out == ["甲"]
    assert seen["url"] == "https://hermes.example/v1/chat/completions"
    assert seen["auth"] == "Bearer k-123"

    prompt = seen["body"]["messages"][0]["content"]
    assert "{{TRANSCRIPT}}" not in prompt and "{{ASKED_QUESTIONS}}" not in prompt
    assert "逐字稿內容" in prompt
    assert "1. 已問過的問題" in prompt
    assert "產品需求釐清主持人" in prompt, "docs/LLM.md 的提示詞必須完整帶入"
    # 未設定 HERMES_MODEL 時不送 model 欄位，交給閘道自己決定
    assert "model" not in seen["body"]


@pytest.mark.anyio
async def test_model_included_when_configured():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"questions": []}'}}]})

    await client_with(handler, hermes_model="hermes-pro").suggest_questions("t", [])
    assert seen["body"]["model"] == "hermes-pro"


@pytest.mark.anyio
async def test_upstream_error_becomes_502():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(LLMUnavailable) as exc:
        await client_with(handler).suggest_questions("t", [])
    assert exc.value.status_code == 502


@pytest.mark.anyio
async def test_timeout_becomes_502():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LLMUnavailable):
        await client_with(handler).suggest_questions("t", [])
