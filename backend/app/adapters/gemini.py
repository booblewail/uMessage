"""The Plan Model backed by Google's Gemini API (ADR-0005), through the `google-genai` SDK.

One `generate_content` call per check: fixed rules as the system instruction, the Chat's
window as JSON in the contents, and a structured JSON answer in `GeminiDecision`'s schema
(`response_json_schema`, which this SDK version takes alongside `response_mime_type`).
Times go out in the user's time zone with their offset and weekday, so relative dates can be
resolved against each Message's own time; they come back as ISO 8601 local times.
"""

import json
import logging
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.adapters.protocols import (
    NewPlan,
    NoPlan,
    PlanDecision,
    PlanDetails,
    PlanRequest,
    UpdatePlan,
)

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """\
You read the latest messages of one chat from the user's messaging inbox and decide whether \
they contain a plan the user would attend at a specific date and time, so it can be offered \
for their calendar.

What counts as a plan:
- Something the user would attend or take part in, at an agreed date (and usually a time): \
a dinner, drinks, a call, an appointment, a meeting, a trip, a game night.
- It may be assembled over several messages from several people: "Dinner Friday?" / \
"Keen" / "7:30pm at Chaco Bar" is one plan (dinner, Friday 7:30pm, Chaco Bar). The user's \
own messages are marked from_user; a plan proposed by someone else that the user hasn't \
turned down still counts.

What does not count (decide "nothing"):
- Deadlines and reminders ("rent is due Friday", "submit the form by 5pm").
- Other people's happenings the user isn't going to ("my sister's wedding was lovely", \
"Sam has a dentist appointment at 3").
- Vague intentions without an agreed day ("we should get coffee sometime", "let's catch up \
soon"), unanswered open questions with no day, plans that were cancelled, and past events.
- Small talk, logistics without a plan, or anything you are unsure about.

Deciding between "nothing", "new" and "update":
- You are given the chat's current Pending Review plans (pending_review_plans), each with an \
id. These are plans already found in this chat and waiting for the user's review.
- If the messages change one of those plans (a new time, day, place or title, e.g. \
"actually make it 8"), decide "update" with that plan's id as event_id, and give the whole \
revised plan (every field, not just what changed).
- If the messages describe a different plan from every pending one, decide "new".
- If the latest messages merely repeat or confirm a pending plan without changing it, or \
contain no plan, decide "nothing". Never repeat a pending plan as "new".

Dates and times:
- Every message has its own sent_at time, in the user's time zone with its UTC offset and \
weekday. Resolve relative dates ("tonight", "Friday", "tomorrow at 7", "next week") against \
the sent_at of the message that said them, not against now: "tomorrow" in a message sent \
yesterday means today.
- "now" is the current time, so you can tell what has already passed.
- Give start (and end, if one was said) as ISO 8601 local date-times in the user's time zone \
including the UTC offset, e.g. 2026-11-06T19:30:00+11:00. If no end was mentioned, end is \
null; never invent one.
- For an all-day plan (a date but no time, e.g. "beach day Saturday", a trip), set all_day \
to true and give start (and end, the last day, if it spans several days) as dates like \
2026-11-07. A plan with a time of day ("Friday evening" is not a time) is not all-day; \
if there is no agreed time and it isn't an all-day kind of thing, decide "nothing".
- Use 24-hour clock reasoning: "7:30" in an evening social context means 19:30.

Fields:
- reason: one short sentence explaining your decision.
- title: short and specific, as it would read in a calendar ("Dinner with Ana at Chaco \
Bar"), in the language of the chat. Use names from the chat; don't use "the user".
- location: the place if one was named, else null.
- confidence: 0 to 1, how sure you are that this is a plan the user will attend at that \
time. Use low values when the plan is tentative or the time is a guess.
- For "nothing", set event_id, title, start, end and location to null, all_day to false \
and confidence to 0.
"""


class GeminiDecision(BaseModel):
    """The JSON Gemini answers with (also its response schema)."""

    reason: str = Field(description="One short sentence explaining the decision")
    action: Literal["nothing", "new", "update"] = Field(
        description="nothing: no new or changed plan; new: a plan that isn't pending; "
        "update: a change to the pending plan event_id"
    )
    event_id: int | None = Field(description="For update: the id of the pending plan")
    title: str | None = Field(description="Short calendar title")
    start: str | None = Field(
        description="ISO 8601 local date-time with UTC offset (2026-11-06T19:30:00+11:00), "
        "or a date (2026-11-07) when all_day"
    )
    end: str | None = Field(description="Like start; null if the chat didn't say")
    all_day: bool = Field(description="True for a plan on a date with no time of day")
    location: str | None = Field(description="The place, if one was named")
    confidence: float = Field(ge=0, le=1, description="0-1: how sure this is a plan")


class GeminiPlanModel:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: genai.Client | None = None,
        temperature: float | None = None,
    ) -> None:
        """`temperature` None keeps Gemini's default (recommended for Gemini 3 models)."""
        self._client = client or genai.Client(api_key=api_key)
        self._model = model
        self._temperature = temperature

    async def decide(self, request: PlanRequest) -> PlanDecision:
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt(request),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_json_schema=GeminiDecision.model_json_schema(),
                temperature=self._temperature,
            ),
        )
        decision = GeminiDecision.model_validate_json(response.text or "")
        logger.debug("Gemini decided %s: %s", decision.action, decision.reason)
        return to_decision(decision)


def prompt(request: PlanRequest) -> str:
    """The contents of the request: one line saying what to do, then the Chat as JSON."""
    tz = ZoneInfo(request.timezone)

    def local(value: datetime | None) -> str | None:
        if value is None:
            return None
        value = value.astimezone(tz)
        return f"{value.isoformat(timespec='seconds')} ({value:%A})"

    chat = {
        "user_time_zone": request.timezone,
        "now": local(request.now),
        "pending_review_plans": [
            {
                "id": plan.id,
                "title": plan.title,
                "start": local(plan.start),
                "end": local(plan.end),
                "all_day": plan.all_day,
                "location": plan.location,
            }
            for plan in request.pending
        ],
        "messages": [
            {
                "sender": message.sender_name,
                "from_user": message.outbound,
                "sent_at": local(message.sent_at),
                "text": message.text,
            }
            for message in request.messages
        ],
    }
    return "Decide about this chat (messages oldest first, the latest last):\n" + json.dumps(
        chat, ensure_ascii=False, indent=2
    )


def to_decision(answer: GeminiDecision) -> PlanDecision:
    """Map Gemini's answer onto a decision; an incomplete plan is no plan."""
    if answer.action == "nothing":
        return NoPlan()
    title = (answer.title or "").strip()
    start = _parse(answer.start)
    if not title or start is None or (answer.action == "update" and answer.event_id is None):
        logger.warning("Gemini answered an incomplete %s plan; ignoring it", answer.action)
        return NoPlan()
    plan = PlanDetails(
        title=title,
        start=start,
        end=_parse(answer.end),
        all_day=answer.all_day,
        location=(answer.location or "").strip() or None,
        confidence=answer.confidence,
    )
    if answer.action == "update":
        assert answer.event_id is not None
        return UpdatePlan(answer.event_id, plan)
    return NewPlan(plan)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        logger.warning("Gemini answered a time that isn't ISO 8601: %r", value)
        return None
