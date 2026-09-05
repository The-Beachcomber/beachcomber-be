"""Hermes-agent client（OpenAI 相容的 /v1/chat/completions）。"""

from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import Settings
from app.errors import LLMBadOutput, LLMUnavailable
from app.llm import prompts

log = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _strip_fence(text: str) -> str:
    """模型偶爾會把 JSON 包在 markdown code fence 裡，提示詞已禁止但仍要防。"""
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text.strip()


def parse_questions(content: str) -> list[str]:
    """把 LLM 回應解析成問題字串陣列。形狀不符就拋 502，不猜、不補。"""
    try:
        payload = json.loads(_strip_fence(content))
    except json.JSONDecodeError as exc:
        raise LLMBadOutput(f"不是合法 JSON（{exc.msg}）") from exc
    if not isinstance(payload, dict) or "questions" not in payload:
        raise LLMBadOutput("缺少 questions 欄位")
    questions = payload["questions"]
    if not isinstance(questions, list) or any(not isinstance(q, str) for q in questions):
        raise LLMBadOutput("questions 必須是字串陣列")
    return [q.strip() for q in questions if q.strip()]


class HermesClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport  # 測試用；正式執行為 None，走真實網路

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.hermes_api_key:
            headers["Authorization"] = f"Bearer {self.settings.hermes_api_key}"
        return headers

    async def _chat(self, prompt: str, *, json_mode: bool = False) -> str:
        payload: dict = {"messages": [{"role": "user", "content": prompt}]}
        if self.settings.hermes_model:
            payload["model"] = self.settings.hermes_model
        if json_mode and self.settings.hermes_json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(
                timeout=self.settings.hermes_timeout_seconds, transport=self._transport
            ) as client:
                resp = await client.post(
                    self.settings.chat_completions_url, json=payload, headers=self._headers()
                )
        except httpx.TimeoutException as exc:
            raise LLMUnavailable(f"逾時（{self.settings.hermes_timeout_seconds:.0f} 秒）") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"連線失敗（{exc}）") from exc

        if resp.status_code >= 400:
            log.warning("hermes %s: %s", resp.status_code, resp.text[:500])
            raise LLMUnavailable(f"回應 HTTP {resp.status_code}")

        try:
            body = resp.json()
            return body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMBadOutput(f"chat/completions 回應結構不如預期（{exc}）") from exc

    async def suggest_questions(self, transcript: str, asked: list[str]) -> list[str]:
        prompt = prompts.render_question_prompt(transcript, asked)
        return parse_questions(await self._chat(prompt, json_mode=True))

    async def generate_prototype(self, transcript: str) -> str:
        return await self._chat(prompts.render_prototype_prompt(transcript))

    async def generate_spec(self, role_id: str, transcript: str, questions: list[str]) -> str:
        return await self._chat(prompts.render_spec_prompt(role_id, transcript, questions))
