import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

import hermes
import main
from main import app

client = TestClient(app)
MEETING_ID = "2026_09_05_1530_AB12CD"


@pytest.fixture(autouse=True)
def force_mock(monkeypatch):
    # Tests must never depend on .env or hit the real Hermes.
    monkeypatch.setattr(hermes, "USE_MOCK", True)


@pytest.fixture(autouse=True)
def clear_memory():
    main._MEETINGS.clear()
    yield
    main._MEETINGS.clear()


@pytest.fixture
def spy(monkeypatch):
    """Records what the endpoint actually hands to Hermes."""
    calls = []
    counter = {"n": 0}

    async def fake_ask(transcript, asked_questions, previous_response_id=None):
        calls.append(
            {
                "transcript": transcript,
                "asked": list(asked_questions),
                "previous_response_id": previous_response_id,
            }
        )
        counter["n"] += 1
        n = counter["n"]
        return f"resp_{n}", [f"round{n}-q1", f"round{n}-q2"]

    monkeypatch.setattr(hermes, "ask", fake_ask)
    return calls


def envelope(text: str) -> dict:
    return {
        "id": "resp_abc123",
        "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}],
    }


def test_extracts_text_from_responses_envelope():
    assert hermes.extract_text(envelope("hello")) == "hello"


def test_extracts_empty_string_when_output_missing():
    assert hermes.extract_text({"id": "resp_1"}) == ""


def test_parses_bare_json():
    assert hermes.parse_questions('{"questions": ["Q1", "Q2"]}') == ["Q1", "Q2"]


def test_parses_json_wrapped_in_code_fence():
    assert hermes.parse_questions('```json\n{"questions": ["Q1"]}\n```') == ["Q1"]


def test_parses_empty_array_when_hermes_has_nothing_to_ask():
    assert hermes.parse_questions('{"questions": []}') == []


def test_returns_empty_list_when_hermes_returns_unparseable_text():
    assert hermes.parse_questions("抱歉，我無法回答") == []


def test_drops_non_string_and_blank_entries():
    assert hermes.parse_questions('{"questions": ["Q1", 42, "   ", null]}') == ["Q1"]


def test_prompt_keeps_json_example_and_fills_both_placeholders():
    prompt = hermes.build_prompt("客戶說要看毛利", ["之前問過的"])

    assert "客戶說要看毛利" in prompt
    assert "- 之前問過的" in prompt
    assert '"questions"' in prompt


def test_prompt_marks_first_round_when_nothing_asked_yet():
    assert "（尚未問過任何問題）" in hermes.build_prompt("逐字稿", [])


def test_post_transcript_returns_contract_the_frontend_expects():
    response = client.post(f"/api/meetings/{MEETING_ID}/transcript", json={"text": "逐字稿內容"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"round", "created_at", "path", "verified_count", "questions"}
    assert body["questions"][0]["entry_id"] == "TKT-001"
    assert body["created_at"].endswith("Z")
    assert body["path"] == f"meetings/{MEETING_ID}/transcript"


def test_post_transcript_ignores_extra_fields_the_frontend_might_still_send():
    response = client.post(
        f"/api/meetings/{MEETING_ID}/transcript",
        json={"text": "逐字稿", "asked_questions": ["問過的"], "previous_response_id": "resp_abc123"},
    )

    assert response.status_code == 200
    assert "response_id" not in response.json()


def test_post_transcript_rejects_body_without_text():
    assert client.post(f"/api/meetings/{MEETING_ID}/transcript", json={}).status_code == 422


def test_detects_rate_limit_from_error_body_even_on_http_200():
    body = {"error": {"message": "Too many concurrent runs (max 1)", "code": "rate_limit_exceeded"}}

    assert hermes.is_rate_limited(200, body) is True


def test_detects_rate_limit_from_http_429():
    assert hermes.is_rate_limited(429, {}) is True


def test_normal_response_is_not_rate_limited():
    assert hermes.is_rate_limited(200, {"id": "resp_1", "output": []}) is False


def post(meeting_id=MEETING_ID, **body):
    return client.post(f"/api/meetings/{meeting_id}/transcript", json={"text": "逐字稿", **body})


def test_first_round_sends_no_history(spy):
    post()

    assert spy[0]["asked"] == []
    assert spy[0]["previous_response_id"] is None


def test_second_round_replays_previous_questions_without_frontend_help(spy):
    post()
    post()

    # The frontend sent only { text } both times; round 2 must still carry round 1.
    assert spy[1]["asked"] == ["round1-q1", "round1-q2"]
    assert spy[1]["previous_response_id"] == "resp_1"


def test_history_accumulates_across_rounds(spy):
    post()
    post()
    post()

    assert spy[2]["asked"] == ["round1-q1", "round1-q2", "round2-q1", "round2-q2"]


def test_round_counts_real_calls_not_payload_size(spy):
    assert post().json()["round"] == 1
    assert post().json()["round"] == 2
    assert post().json()["round"] == 3


def test_memory_is_per_meeting(spy):
    post(meeting_id="meeting-a")
    post(meeting_id="meeting-b")

    assert spy[1]["asked"] == []


def test_frontend_cannot_override_backend_memory(spy):
    post()
    post(asked_questions=["前端硬送的"], previous_response_id="resp_frontend")

    # Those fields are backend-internal now, so a stray payload must not steer Hermes.
    assert spy[1]["asked"] == ["round1-q1", "round1-q2"]
    assert spy[1]["previous_response_id"] == "resp_1"


def test_memory_evicts_oldest_meeting_past_the_cap(spy):
    for i in range(main.MAX_TRACKED_MEETINGS + 5):
        post(meeting_id=f"meeting-{i}")

    assert len(main._MEETINGS) == main.MAX_TRACKED_MEETINGS
    assert "meeting-0" not in main._MEETINGS
    assert f"meeting-{main.MAX_TRACKED_MEETINGS + 4}" in main._MEETINGS


def post_prototype(meeting_id=MEETING_ID, text="逐字稿"):
    return client.post(f"/api/meetings/{meeting_id}/prototypes", json={"text": text})


def test_prototype_returns_the_url_string_the_frontend_expects():
    body = post_prototype().json()

    assert list(body) == ["prototypes"]
    assert body["prototypes"] == hermes.MOCK_PROTOTYPE_URL


def test_prototype_does_not_disturb_the_interview_thread(spy, monkeypatch):
    async def fake_ask_prototype(transcript, previous_response_id=None):
        return "", hermes.MOCK_PROTOTYPE_URL

    monkeypatch.setattr(hermes, "ask_prototype", fake_ask_prototype)
    post()
    post_prototype()

    # /v1/prototypes returns no id, so the interview keeps its own parent.
    assert main._MEETINGS[MEETING_ID]["response_id"] == "resp_1"


def test_prototype_payload_without_a_url_raises_rather_than_leaking_error_text(monkeypatch):
    # Hermes really does answer this way; it must never reach the frontend as a link.
    async def fake_post_prototype(transcript):
        return {"error": "No reply: the model returned empty content"}

    monkeypatch.setattr(hermes, "_post_prototype", fake_post_prototype)
    monkeypatch.setattr(hermes, "USE_MOCK", False)

    with pytest.raises(hermes.HermesNoPrototype):
        asyncio.run(hermes.ask_prototype("逐字稿"))


def test_prototype_endpoint_reports_502_when_hermes_returns_no_url(monkeypatch):
    async def fake_ask_prototype(transcript, previous_response_id=None):
        raise hermes.HermesNoPrototype("⚠️ No reply: the model returned empty content")

    monkeypatch.setattr(hermes, "ask_prototype", fake_ask_prototype)

    response = post_prototype()

    assert response.status_code == 502
    assert "no prototype url" in response.json()["detail"]


def test_prototype_uses_a_longer_timeout_than_question_answering():
    assert hermes.PROTOTYPE_TIMEOUT > hermes.TIMEOUT


def post_specs(meeting_id=MEETING_ID, **body):
    return client.post(f"/api/meetings/{meeting_id}/specs", json={"roles": ["pm"], **body})


def test_specs_returns_the_shape_the_frontend_expects():
    response = post_specs(roles=["pm", "ui", "eng", "qa"], transcript="逐字稿")

    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["response"]
    assert [item["role"] for item in body["response"]] == ["pm", "ui", "eng", "qa"]
    assert all(set(item) == {"role", "spec"} for item in body["response"])


def test_spec_values_are_urls_because_SpecViewer_iframes_them():
    for item in post_specs(roles=["pm", "ui", "eng", "qa"], transcript="逐字稿").json()["response"]:
        assert item["spec"].startswith("https://")
        assert item["spec"].endswith(f"/{item['role']}.md")


def test_specs_returns_only_the_requested_roles():
    # Hermes always produces all four; the caller asked for one.
    body = post_specs(roles=["qa"], transcript="逐字稿").json()

    assert [item["role"] for item in body["response"]] == ["qa"]


def test_specs_keeps_the_requested_order_not_hermes_order():
    body = post_specs(roles=["qa", "pm"], transcript="逐字稿").json()

    assert [item["role"] for item in body["response"]] == ["qa", "pm"]
    assert hermes.SPEC_ROLES[:2] == ("pm", "ui")


def test_specs_rejects_an_unknown_role():
    assert post_specs(roles=["backend"], transcript="逐字稿").status_code == 422


def test_specs_deduplicates_repeated_roles():
    body = post_specs(roles=["qa", "pm", "qa"], transcript="逐字稿").json()

    assert [item["role"] for item in body["response"]] == ["qa", "pm"]


def test_specs_accepts_an_empty_role_list():
    assert post_specs(roles=[], transcript="逐字稿").json()["response"] == []


def test_specs_falls_back_to_the_remembered_transcript(spy):
    # The frontend sends only { roles }, exactly as lib/api/spec.ts does today.
    post()

    assert post_specs(roles=["pm"]).status_code == 200


def test_specs_422_when_no_transcript_anywhere():
    response = post_specs(roles=["pm"])

    assert response.status_code == 422
    assert "no transcript available" in response.json()["detail"]


def test_specs_rejects_a_transcript_over_the_hermes_limit():
    too_long = "字" * (hermes.SPEC_TRANSCRIPT_LIMIT + 1)

    assert post_specs(roles=["pm"], transcript=too_long).status_code == 422


def test_specs_passes_transcript_and_prototype_url_through(monkeypatch):
    seen = {}

    async def fake_ask_specs(transcript, prototype_url=""):
        seen["transcript"] = transcript
        seen["prototype_url"] = prototype_url
        return [{"role": r, "spec": f"https://x/{r}.md"} for r in hermes.SPEC_ROLES]

    monkeypatch.setattr(hermes, "ask_specs", fake_ask_specs)
    post_specs(roles=["pm"], transcript="request 帶的", prototype_url="https://example.com/x.html")

    assert seen["transcript"] == "request 帶的"
    assert seen["prototype_url"] == "https://example.com/x.html"


def test_prototype_url_is_remembered_for_later_spec_calls(monkeypatch):
    seen = {}

    async def fake_ask_specs(transcript, prototype_url=""):
        seen["prototype_url"] = prototype_url
        return [{"role": r, "spec": f"https://x/{r}.md"} for r in hermes.SPEC_ROLES]

    monkeypatch.setattr(hermes, "ask_specs", fake_ask_specs)
    post_prototype()
    post_specs(roles=["pm"], transcript="逐字稿")

    assert seen["prototype_url"] == hermes.MOCK_PROTOTYPE_URL


def test_specs_endpoint_reports_502_when_hermes_rejects_the_request(monkeypatch):
    async def fake_ask_specs(transcript, prototype_url=""):
        raise hermes.HermesSpecFailed("transcript is required")

    monkeypatch.setattr(hermes, "ask_specs", fake_ask_specs)

    response = post_specs(roles=["pm"], transcript="逐字稿")

    assert response.status_code == 502
    assert "could not produce specs" in response.json()["detail"]


def test_specs_uses_its_own_endpoint_not_the_conversational_one():
    assert hermes.SPECS_ENDPOINT_PATH == "/v1/specs"
    assert hermes.SPECS_ENDPOINT_PATH != hermes.ENDPOINT_PATH
