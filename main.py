from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import hermes

app = FastAPI(title="beachcomber-be")

# Wide open on purpose: this is a demo backend with no auth, called from
# whatever host the frontend happens to be on. The regex echoes the caller's
# Origin back instead of "*", because browsers reject a wildcard origin
# whenever the request carries credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Conversation memory so the frontend can keep sending only what it already has.
# This lives in process memory, which only holds together on Cloud Run when the
# service runs as a single instance (--min-instances=1 --max-instances=1);
# otherwise a request can land on an instance that never saw the earlier rounds.
MAX_TRACKED_MEETINGS = 200
_MEETINGS: dict[str, dict] = {}


def _blank_meeting() -> dict:
    return {"asked": [], "response_id": None, "round": 0, "transcript": "", "prototype_url": ""}


def _recall(meeting_id: str) -> dict:
    return _MEETINGS.get(meeting_id) or _blank_meeting()


def _remember(meeting_id: str, **updates) -> None:
    current = _MEETINGS.pop(meeting_id, None) or _blank_meeting()
    if len(_MEETINGS) >= MAX_TRACKED_MEETINGS:
        del _MEETINGS[next(iter(_MEETINGS))]
    current.update(updates)
    _MEETINGS[meeting_id] = current


@contextmanager
def _hermes_errors():
    try:
        yield
    except hermes.HermesBusy as exc:
        raise HTTPException(503, "hermes is rate limited, please retry") from exc
    except hermes.HermesNoPrototype as exc:
        raise HTTPException(502, f"hermes returned no prototype url: {exc}") from exc
    except hermes.HermesSpecFailed as exc:
        raise HTTPException(502, f"hermes could not produce specs: {exc}") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"hermes returned {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(504, "hermes request failed") from exc


SpecRole = Literal["pm", "eng", "ui", "qa"]


class TranscriptRequest(BaseModel):
    text: str


class SpecsRequest(BaseModel):
    roles: list[SpecRole]
    # Hermes rejects anything longer, so fail here with a clear 422 instead.
    transcript: str | None = Field(default=None, max_length=hermes.SPEC_TRANSCRIPT_LIMIT)
    prototype_url: str | None = None


class QuestionItem(BaseModel):
    entry_id: str
    question: str


class SpecItem(BaseModel):
    role: SpecRole
    spec: str


class PrototypeResponse(BaseModel):
    prototypes: str


class SpecsResponse(BaseModel):
    response: list[SpecItem]


class TranscriptResponse(BaseModel):
    round: int
    created_at: str
    path: str
    verified_count: int
    questions: list[QuestionItem]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/meetings/{meeting_id}/transcript", response_model=TranscriptResponse)
async def post_transcript(meeting_id: str, body: TranscriptRequest) -> TranscriptResponse:
    remembered = _recall(meeting_id)
    asked = remembered["asked"]

    with _hermes_errors():
        response_id, questions = await hermes.ask(body.text, asked, remembered["response_id"])

    round_number = remembered["round"] + 1
    _remember(
        meeting_id,
        asked=asked + questions,
        response_id=response_id,
        round=round_number,
        transcript=body.text,
    )

    return TranscriptResponse(
        round=round_number,
        created_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        path=f"meetings/{meeting_id}/transcript",
        # Hermes has no verification step, so there is no real number to report.
        verified_count=0,
        questions=[
            QuestionItem(entry_id=f"TKT-{i:03d}", question=q) for i, q in enumerate(questions, start=1)
        ],
    )


@app.post("/api/meetings/{meeting_id}/prototypes", response_model=PrototypeResponse)
async def post_prototype(meeting_id: str, body: TranscriptRequest) -> PrototypeResponse:
    # Reuses the interview thread so Hermes still sees the earlier rounds, but
    # deliberately leaves response_id alone -- the next follow-up round should
    # continue from the interview, not from the prototype output.
    remembered = _recall(meeting_id)

    with _hermes_errors():
        _, prototypes = await hermes.ask_prototype(body.text, remembered["response_id"])

    _remember(meeting_id, transcript=body.text, prototype_url=prototypes)

    return PrototypeResponse(prototypes=prototypes)


@app.post("/api/meetings/{meeting_id}/specs", response_model=SpecsResponse)
async def post_specs(meeting_id: str, body: SpecsRequest) -> SpecsResponse:
    remembered = _recall(meeting_id)
    transcript = body.transcript or remembered["transcript"]
    prototype_url = body.prototype_url or remembered["prototype_url"]

    if not transcript:
        raise HTTPException(
            422,
            "no transcript available: send `transcript` in the body, "
            "or call the transcript/prototypes endpoint for this meeting_id first",
        )

    with _hermes_errors():
        produced = await hermes.ask_specs(transcript, prototype_url)

    # Hermes always writes all four roles; the caller only gets the ones it asked
    # for, in the order it asked for them.
    by_role = {item.get("role"): item.get("spec", "") for item in produced}
    return SpecsResponse(
        response=[
            SpecItem(role=role, spec=by_role[role])
            for role in dict.fromkeys(body.roles)
            if role in by_role
        ]
    )
