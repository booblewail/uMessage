"""Contract test of the Gemini Plan Model: the request it makes through the google-genai SDK
(the SDK call is replaced, nothing goes over the network) and how it reads the answers."""

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from google import genai
from google.genai import types

from app.adapters.gemini import GeminiDecision, GeminiPlanModel
from app.adapters.protocols import (
    NewPlan,
    NoPlan,
    PendingPlan,
    PlanDetails,
    PlanRequest,
    PlanWindowMessage,
    UpdatePlan,
)

SYDNEY_OFFSET = timezone(timedelta(hours=11))
NOW = datetime(2026, 11, 3, 3, 0, tzinfo=UTC)  # Tuesday 14:00 in Sydney

REQUEST = PlanRequest(
    messages=[
        PlanWindowMessage("Ana", "Dinner Friday?", NOW - timedelta(minutes=3), outbound=False),
        PlanWindowMessage("You", "Keen", NOW - timedelta(minutes=2), outbound=True),
        PlanWindowMessage("Ana", "7:30pm at Chaco Bar", NOW - timedelta(minutes=1), outbound=False),
    ],
    pending=[
        PendingPlan(
            id=42,
            title="Climbing at Boulderhaus",
            start=datetime(2026, 11, 5, 8, 0, tzinfo=UTC),
            end=None,
            all_day=False,
            location="Boulderhaus",
        )
    ],
    timezone="Australia/Sydney",
    now=NOW,
)


class RecordedGemini:
    """Replaces `client.aio.models.generate_content`: records each call, answers `answer`."""

    def __init__(self, answer: dict[str, Any] | str) -> None:
        self.answer = answer if isinstance(answer, str) else json.dumps(answer)
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> types.GenerateContentResponse:
        self.calls.append(kwargs)
        return types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(role="model", parts=[types.Part(text=self.answer)]),
                    finish_reason=types.FinishReason.STOP,
                )
            ]
        )


def answer(**fields: Any) -> dict[str, Any]:
    """An answer shaped like Gemini's (every field of the schema present)."""
    base: dict[str, Any] = {
        "reason": "They agreed on dinner on Friday at 7:30pm at Chaco Bar.",
        "action": "nothing",
        "event_id": None,
        "title": None,
        "start": None,
        "end": None,
        "all_day": False,
        "location": None,
        "confidence": 0.0,
    }
    return {**base, **fields}


def plan_model_answering(
    monkeypatch: pytest.MonkeyPatch, reply: dict[str, Any] | str
) -> tuple[GeminiPlanModel, RecordedGemini]:
    client = genai.Client(api_key="test-gemini-key")
    recorded = RecordedGemini(reply)
    monkeypatch.setattr(client.aio.models, "generate_content", recorded.generate_content)
    model = GeminiPlanModel(api_key="test-gemini-key", model="gemini-test-flash", client=client)
    return model, recorded


async def test_it_asks_the_configured_model_for_json_in_the_decision_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, gemini = plan_model_answering(monkeypatch, answer())

    await model.decide(REQUEST)

    [call] = gemini.calls
    assert call["model"] == "gemini-test-flash"
    config: types.GenerateContentConfig = call["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == GeminiDecision.model_json_schema()
    assert config.response_schema is None  # the SDK takes one or the other
    instructions = str(config.system_instruction)
    for rule in ("would attend", "deadline", "update", "nothing", "offset", "Pending Review"):
        assert rule.lower() in instructions.lower(), rule


async def test_it_sends_the_window_pending_plans_time_zone_and_now(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, gemini = plan_model_answering(monkeypatch, answer())

    await model.decide(REQUEST)

    sent = json.loads(gemini.calls[0]["contents"].split("\n", 1)[1])
    assert sent["user_time_zone"] == "Australia/Sydney"
    assert sent["now"] == "2026-11-03T14:00:00+11:00 (Tuesday)"
    assert sent["messages"] == [
        {
            "sender": "Ana",
            "from_user": False,
            "sent_at": "2026-11-03T13:57:00+11:00 (Tuesday)",
            "text": "Dinner Friday?",
        },
        {
            "sender": "You",
            "from_user": True,
            "sent_at": "2026-11-03T13:58:00+11:00 (Tuesday)",
            "text": "Keen",
        },
        {
            "sender": "Ana",
            "from_user": False,
            "sent_at": "2026-11-03T13:59:00+11:00 (Tuesday)",
            "text": "7:30pm at Chaco Bar",
        },
    ]
    assert sent["pending_review_plans"] == [
        {
            "id": 42,
            "title": "Climbing at Boulderhaus",
            "start": "2026-11-05T19:00:00+11:00 (Thursday)",
            "end": None,
            "all_day": False,
            "location": "Boulderhaus",
        }
    ]


async def test_a_new_plan_is_read_with_its_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    model, _ = plan_model_answering(
        monkeypatch,
        answer(
            action="new",
            title="Dinner at Chaco Bar",
            start="2026-11-06T19:30:00+11:00",
            location="Chaco Bar",
            confidence=0.92,
        ),
    )

    decision = await model.decide(REQUEST)

    assert decision == NewPlan(
        PlanDetails(
            title="Dinner at Chaco Bar",
            start=datetime(2026, 11, 6, 19, 30, tzinfo=SYDNEY_OFFSET),
            end=None,
            all_day=False,
            location="Chaco Bar",
            confidence=0.92,
        )
    )


async def test_an_update_names_the_pending_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    model, _ = plan_model_answering(
        monkeypatch,
        answer(
            action="update",
            event_id=42,
            title="Climbing at Boulderhaus",
            start="2026-11-05T20:00:00",  # a local wall time without an offset
            end="2026-11-05T22:00:00",
            location="Boulderhaus",
            confidence=0.8,
        ),
    )

    decision = await model.decide(REQUEST)

    assert decision == UpdatePlan(
        42,
        PlanDetails(
            title="Climbing at Boulderhaus",
            start=datetime(2026, 11, 5, 20, 0),
            end=datetime(2026, 11, 5, 22, 0),
            all_day=False,
            location="Boulderhaus",
            confidence=0.8,
        ),
    )


async def test_an_all_day_plan_is_read_as_its_date(monkeypatch: pytest.MonkeyPatch) -> None:
    model, _ = plan_model_answering(
        monkeypatch,
        answer(action="new", title="Beach day", start="2026-11-07", all_day=True, confidence=0.7),
    )

    decision = await model.decide(REQUEST)

    assert isinstance(decision, NewPlan)
    assert (decision.plan.start, decision.plan.all_day) == (datetime(2026, 11, 7), True)


@pytest.mark.parametrize(
    "reply",
    [
        answer(),
        answer(action="new", title="Dinner", start=None, confidence=0.9),
        answer(action="new", title="", start="2026-11-06T19:30:00+11:00", confidence=0.9),
        answer(action="new", title="Dinner", start="Friday evening", confidence=0.9),
        answer(action="update", event_id=None, title="Dinner", start="2026-11-06", confidence=1),
    ],
    ids=["nothing", "no-start", "no-title", "unreadable-start", "update-without-id"],
)
async def test_nothing_or_an_incomplete_plan_is_no_plan(
    monkeypatch: pytest.MonkeyPatch, reply: dict[str, Any]
) -> None:
    model, _ = plan_model_answering(monkeypatch, reply)

    assert await model.decide(REQUEST) == NoPlan()


async def test_an_answer_that_isnt_the_schema_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    model, _ = plan_model_answering(monkeypatch, "Sure! Here is the plan: dinner")

    with pytest.raises(ValueError):
        await model.decide(REQUEST)
