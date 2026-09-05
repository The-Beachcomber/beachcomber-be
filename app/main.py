"""FastAPI 進入點。

契約以 openapi.yaml 為準；本檔產生的 /openapi.json 應與其等價，
差異請視為 bug，兩邊擇一修正。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import artifacts, health, meetings, transcript
from app.config import get_settings
from app.llm.prompts import question_prompt_template

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
log = logging.getLogger(__name__)

DESCRIPTION = """\
React 前端 ←→ 本層（中介）←→ Hermes-agent (LLM) → GCS

## 四個情境

1. `POST /api/meetings` — 建立 LLM 會話（同步）
2. `POST /api/meetings/{id}/transcript` — 逐字稿 → 建議問題（同步）
3. `POST /api/meetings/{id}/prototypes` — 全逐字稿 → 原型頁面（同步）
4. `POST /api/meetings/{id}/specs` — 選定角色 → 規格文件（同步）

## MVP 範圍

本版不收知識包／角色包（`.pak`）。領域知識、角色定義與分析方法皆已在
LLM 端設定完成，本層只負責會話、逐字稿與產出落檔。

前端不保存也不回傳「已問問題」，該狀態由本層持久化於儲存層，
作為後續問題產出的過濾依據。
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 提示詞讀不到就早點爆，不要等到 Demo 當下第一次呼叫才發現。
    question_prompt_template()
    s = get_settings()
    log.info("啟動完成 llm_mode=%s storage=%s", s.llm_mode, s.describe_storage_root())
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        lifespan=lifespan,
        title="Spec Agent Middleware",
        version="0.2.0",
        summary="需求規格化 Agent 的後端中介層",
        description=DESCRIPTION,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in (health.router, meetings.router, transcript.router, artifacts.router):
        app.include_router(router)
    return app


app = create_app()
