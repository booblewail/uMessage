from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app import calendar_entries, detected_events
from app.adapters.protocols import Calendar, CalendarUnavailableError
from app.config import Settings
from app.db import get_session
from app.dependencies import get_calendar, get_connections, get_settings
from app.inbox import NotFoundError
from app.models import DetectedEventStatus
from app.schemas import (
    ConfirmIn,
    DetectedEventOut,
    DetectedEventsOut,
    EventDetectedEvent,
    detected_event_out,
)
from app.ws_manager import ConnectionManager

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/events")
async def list_events(
    session: Session,
    status_: Annotated[DetectedEventStatus | None, Query(alias="status")] = None,
    chat_id: Annotated[int | None, Query(alias="chatId")] = None,
) -> DetectedEventsOut:
    """Detected Events, soonest first; `status` and `chatId` narrow the list."""
    events = await detected_events.list_events(session, status=status_, chat_id=chat_id)
    return DetectedEventsOut(events=[detected_event_out(event) for event in events])


@router.post("/events/{event_id}/dismiss")
async def dismiss_event(
    event_id: int,
    session: Session,
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
    out = detected_event_out(event)
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
    edits: Annotated[ConfirmIn | None, Body()] = None,
) -> DetectedEventOut:
    """Put a Pending Review Detected Event on the user's calendar, with any edits: creates
    its Calendar Entry (once, however often this is called) and makes it Confirmed; pushed
    as `EVENT_DETECTED` with change `updated`."""
    changes = (edits or ConfirmIn()).model_dump(exclude_unset=True)
    try:
        event = await calendar_entries.confirm(
            session,
            calendar,
            event_id,
            calendar_entries.Edits(**changes),
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
    out = detected_event_out(event)
    await connections.broadcast(EventDetectedEvent(event=out, change="updated"))
    return out
