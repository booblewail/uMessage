import re
from datetime import date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app import calendar_entries, detected_events
from app.adapters.protocols import Calendar, CalendarUnavailableError
from app.config import Settings
from app.db import get_session
from app.dependencies import get_calendar, get_connections, get_install_id, get_settings
from app.inbox import NotFoundError
from app.models import DetectedEventStatus
from app.schemas import (
    ConfirmIn,
    DetectedEventOut,
    DetectedEventsOut,
    EventDetectedEvent,
)
from app.ws_manager import ConnectionManager

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]


def _statuses(values: list[str]) -> set[DetectedEventStatus]:
    """`status` may be repeated and/or comma-separated."""
    names = [name.strip() for value in values for name in value.split(",")]
    try:
        statuses = {DetectedEventStatus(name) for name in names}
    except ValueError as exc:
        allowed = ", ".join(member.value for member in DetectedEventStatus)
        raise _invalid_query("status", f"{exc}; a status is one of {allowed}") from exc
    return statuses


def _starting_from(value: str, timezone: str) -> datetime:
    """An ISO 8601 date and time (naive: in the user's time zone), or a date (its midnight)."""
    try:
        parsed = (
            datetime.combine(date.fromisoformat(value), time())
            if _DATE_ONLY.fullmatch(value)
            else datetime.fromisoformat(value)
        )
    except ValueError as exc:
        raise _invalid_query("from", f"{value!r} is not an ISO 8601 date or time") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo(timezone))


def _invalid_query(name: str, message: str) -> RequestValidationError:
    return RequestValidationError(
        [{"type": "value_error", "loc": ("query", name), "msg": message, "input": None}]
    )


_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")


@router.get("/events")
async def list_events(
    session: Session,
    settings: Annotated[Settings, Depends(get_settings)],
    status_: Annotated[
        list[str],
        Query(
            alias="status",
            description="Only these statuses: repeat it, or comma-separate them",
        ),
    ] = [],  # noqa: B006 (FastAPI copies query defaults)
    chat_id: Annotated[int | None, Query(alias="chatId")] = None,
    from_: Annotated[
        str | None,
        Query(
            alias="from",
            description="Only those starting at or after this ISO 8601 time (naive: in the "
            "user's time zone) or date (from its midnight)",
        ),
    ] = None,
) -> DetectedEventsOut:
    """Detected Events, soonest first, each with its Chat and Anchor Message; `status`,
    `chatId` and `from` narrow the list."""
    timezone = settings.user_timezone
    events = await detected_events.list_events(
        session,
        statuses=_statuses(status_),
        chat_id=chat_id,
        starting_from=_starting_from(from_, timezone) if from_ is not None else None,
    )
    views = await detected_events.views(session, events, timezone=timezone)
    return DetectedEventsOut(events=[views[event.id] for event in events])


@router.post("/events/{event_id}/dismiss")
async def dismiss_event(
    event_id: int,
    session: Session,
    settings: Annotated[Settings, Depends(get_settings)],
    connections: Annotated[ConnectionManager, Depends(get_connections)],
) -> DetectedEventOut:
    """Dismiss a Pending Review Detected Event (it never reaches the calendar); pushed as
    `EVENT_DETECTED` with change `updated`. 409 if it is already Confirmed or Dismissed."""
    try:
        event = await detected_events.dismiss(session, event_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except detected_events.NotPendingReviewError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    out = await detected_events.view(session, event, timezone=settings.user_timezone)
    await connections.broadcast(EventDetectedEvent(event=out, change="updated"))
    return out


@router.post(
    "/events/{event_id}/confirm",
    responses={
        409: {"description": "Already Confirmed or Dismissed, or being confirmed right now"},
        502: {"description": "The Calendar failed; it is still Pending Review"},
        503: {"description": "The Calendar isn't connected; it is still Pending Review"},
    },
)
async def confirm_event(
    event_id: int,
    session: Session,
    calendar: Annotated[Calendar, Depends(get_calendar)],
    settings: Annotated[Settings, Depends(get_settings)],
    connections: Annotated[ConnectionManager, Depends(get_connections)],
    install_id: Annotated[str, Depends(get_install_id)],
    edits: Annotated[ConfirmIn | None, Body()] = None,
) -> DetectedEventOut:
    """Put a Pending Review Detected Event on the user's calendar, with any edits: creates
    its Calendar Entry (once, however often this is called) and makes it Confirmed; pushed
    as `EVENT_DETECTED` with change `updated`, followed by the Chat's other Pending Review
    Detected Events (their `existingCalendarEntries` now name it)."""
    changes = (edits or ConfirmIn()).model_dump(exclude_unset=True)
    try:
        event = await calendar_entries.confirm(
            session,
            calendar,
            event_id,
            calendar_entries.Edits(**changes),
            install_id=install_id,
            timezone=settings.user_timezone,
            default_duration=timedelta(minutes=settings.default_plan_duration_minutes),
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except detected_events.NotPendingReviewError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except calendar_entries.InvalidEditsError as exc:
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("body", exc.field), "msg": str(exc), "input": None}]
        ) from exc
    except CalendarUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except calendar_entries.CalendarEntryFailedError as exc:
        detail = f"Couldn't create the Calendar Entry ({exc}); the plan is still pending review"
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail) from exc
    out = await detected_events.view(session, event, timezone=settings.user_timezone)
    await connections.broadcast(EventDetectedEvent(event=out, change="updated"))
    # The Chat's other pending plans now say it is on the calendar ("already on your calendar").
    others = await detected_events.list_events(
        session, statuses={DetectedEventStatus.PENDING_REVIEW}, chat_id=event.chat_id
    )
    views = await detected_events.views(session, others, timezone=settings.user_timezone)
    for other in others:
        await connections.broadcast(EventDetectedEvent(event=views[other.id], change="updated"))
    return out
