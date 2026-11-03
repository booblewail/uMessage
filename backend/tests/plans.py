"""Builders for what the fake Plan Model decides, and for reading what it was sent."""

from datetime import date, datetime, time, timedelta
from typing import Any

from app.adapters.fakes import FakeMessageSource, FakePlanModel
from app.adapters.protocols import NewPlan, PlanDetails, PlanRequest, UpdatePlan
from app.config import Settings
from tests.clock import FakeClock
from tests.sources import a_message
from tests.ws import WebSocketSession


def a_plan(
    title: str = "Dinner",
    *,
    start: datetime,
    end: datetime | None = None,
    all_day: bool = False,
    location: str | None = None,
    confidence: float = 0.9,
) -> PlanDetails:
    return PlanDetails(
        title=title,
        start=start,
        end=end,
        all_day=all_day,
        location=location,
        confidence=confidence,
    )


def new_plan(title: str = "Dinner", **details: object) -> NewPlan:
    return NewPlan(a_plan(title, **details))  # type: ignore[arg-type]


def update_plan(event_id: int, title: str = "Dinner", **details: object) -> UpdatePlan:
    return UpdatePlan(event_id, a_plan(title, **details))  # type: ignore[arg-type]


def days_ahead(days: int, at: time = time(19, 30)) -> datetime:
    """A naive local wall time `days` from today (how the Plan Model may give a time)."""
    return datetime.combine(date.today() + timedelta(days=days), at)


def window_texts(request: PlanRequest) -> list[str]:
    return [message.text for message in request.messages]


def texts_sent(plan_model: FakePlanModel) -> list[list[str]]:
    """The window of Message texts sent in each Plan Model call so far."""
    return [window_texts(call) for call in plan_model.calls]


async def detect(
    socket: WebSocketSession,
    source: FakeMessageSource,
    clock: FakeClock,
    settings: Settings,
    chat: str,
    text: str,
    *,
    sender: str = "Ana",
) -> dict[str, Any]:
    """A Message `text` arrives in Chat `chat`, the Chat settles, and the Plan Model's next
    scripted decision is applied: returns the Detected Event pushed over `socket`."""
    message = a_message(f"{chat}-{text}", sender=sender, text=text, ago=timedelta(seconds=1))
    source.receive(chat, message)
    await socket.receive_until("NEW_MESSAGE")
    clock.advance(settings.plan_settle_seconds)
    return (await socket.receive_until("EVENT_DETECTED"))["event"]
