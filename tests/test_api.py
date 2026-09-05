from __future__ import annotations

import pytest

from app.errors import LLMBadOutput
from app.llm.hermes import parse_questions
from app.services.questions import dedupe, fingerprint
from tests.conftest import build_client


def create_meeting(client, title="黑客松主題選擇會議") -> str:
    r = client.post("/api/meetings", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["meeting_id"]


# ---- 情境 1 --------------------------------------------------------------


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["llm_mode"] in {"mock", "hermes"}


def test_create_meeting_needs_no_pack(client):
    """MVP 不收 .pak：不帶 body 也要能建立會議。"""
    r = client.post("/api/meetings")
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "未命名需求會議"
    assert body["llm_session_id"].startswith("sess_")


def test_get_meeting_404(client):
    assert client.get("/api/meetings/2026_09_05_1420_deadbeef").status_code == 404


def test_meeting_id_pattern_rejected(client):
    assert client.get("/api/meetings/not-a-meeting-id").status_code == 422


# ---- 情境 2：問題儲存與過濾（本專案的核心） -------------------------------


def test_asked_questions_are_carried_into_next_llm_call(client, llm):
    mid = create_meeting(client)

    first = client.post(f"/api/meetings/{mid}/transcript", json={"text": "我們的主題該怎麼選？"})
    assert [q["question"] for q in first.json()["questions"]] == ["問題 A", "問題 B"]
    assert llm.calls[0] == [], "第一輪沒有已問問題"

    second = client.post(f"/api/meetings/{mid}/transcript", json={"text": "評分標準是什麼？"})
    # 前端沒有回傳任何問題，已問清單必須由中介層自己補上
    assert llm.calls[1] == ["問題 A", "問題 B"]
    # LLM 又吐了一次「問題 A」，中介層要把它擋掉
    assert [q["question"] for q in second.json()["questions"]] == ["問題 C"]


def test_ledger_survives_container_restart(storage_root, llm):
    """Cloud Run 換容器後，已問問題不能消失。"""
    with build_client(storage_root, llm) as c1:
        mid = create_meeting(c1)
        c1.post(f"/api/meetings/{mid}/transcript", json={"text": "第一段"})

    # 全新的 app 實例＝全新的程序記憶體，只有儲存層是共用的
    with build_client(storage_root, llm) as c2:
        c2.post(f"/api/meetings/{mid}/transcript", json={"text": "第二段"})

    assert llm.calls[1] == ["問題 A", "問題 B"]


def test_transcript_accumulates(client):
    mid = create_meeting(client)
    client.post(f"/api/meetings/{mid}/transcript", json={"text": "第一段"})
    client.post(f"/api/meetings/{mid}/transcript", json={"text": "第二段"})

    body = client.get(f"/api/meetings/{mid}/transcript").json()
    assert [s["seq"] for s in body["segments"]] == [1, 2]
    assert body["text"] == "第一段\n第二段"
    assert client.get(f"/api/meetings/{mid}").json()["transcript_segments"] == 2


def test_questions_round_is_auditable(client):
    """落檔要留下 LLM 原始輸出與被丟掉的問題，事後才查得出為什麼少了一題。"""
    mid = create_meeting(client)
    client.post(f"/api/meetings/{mid}/transcript", json={"text": "第一段"})
    client.post(f"/api/meetings/{mid}/transcript", json={"text": "第二段"})

    round2 = client.get(f"/api/meetings/{mid}/questions/2").json()
    assert round2["raw"] == ["問題 A", "問題 C"]
    assert round2["dropped"] == ["問題 A"]
    assert round2["asked_before"] == 2
    assert client.get(f"/api/meetings/{mid}").json()["rounds"]["questions"] == [1, 2]


def test_round_404(client):
    mid = create_meeting(client)
    assert client.get(f"/api/meetings/{mid}/questions/9").status_code == 404


# ---- 去重規則 -------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("要保存逐字稿嗎?", "要保存逐字稿嗎？"),
        ("評分標準是什麼", " 評分標準是什麼 "),
        ("Demo 需要網路嗎", "demo需要網路嗎"),
    ],
)
def test_fingerprint_treats_as_same(a, b):
    assert fingerprint(a) == fingerprint(b)


def test_dedupe_drops_within_batch():
    kept, dropped = dedupe(["同一題", "同一題", "另一題"], [])
    assert kept == ["同一題", "另一題"]
    assert dropped == ["同一題"]


# ---- Hermes 回應解析 ------------------------------------------------------


def test_parse_questions_strips_code_fence():
    assert parse_questions('```json\n{"questions": ["甲", "乙"]}\n```') == ["甲", "乙"]


@pytest.mark.parametrize(
    "bad", ["不是 JSON", '{"foo": 1}', '{"questions": "不是陣列"}', '{"questions": [1, 2]}']
)
def test_parse_questions_rejects_bad_shape(bad):
    with pytest.raises(LLMBadOutput):
        parse_questions(bad)


# ---- 情境 3 / 4 -----------------------------------------------------------


def test_prototypes_returns_url(client):
    mid = create_meeting(client)
    client.post(f"/api/meetings/{mid}/transcript", json={"text": "第一段"})
    url = client.post(f"/api/meetings/{mid}/prototypes", json={"text": ""}).json()["prototypes"]
    assert url.endswith("/prototypes/round-0001/index.html")


def test_specs_one_url_per_role(client):
    mid = create_meeting(client)
    body = client.post(f"/api/meetings/{mid}/specs", json={"roles": "pm,ui"}).json()
    # 契約欄位名為 role / spec，且與請求的 roles 同順序
    assert [d["role"] for d in body["data"]] == ["pm", "ui"]
    assert all(d["spec"].endswith(".html") for d in body["data"])
    assert body["data"][1]["spec"].endswith("/ui.html")


def test_specs_rejects_empty_roles(client):
    mid = create_meeting(client)
    assert client.post(f"/api/meetings/{mid}/specs", json={"roles": " "}).status_code == 422
