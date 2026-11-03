"""Builders for what the fake Plan Model decides, and for reading what it was sent."""

from datetime import date, datetime, time, timedelta

from app.adapters.fakes import FakePlanModel
from app.adapters.protocols import NewPlan, PlanDetails, PlanRequest, UpdatePlan


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
