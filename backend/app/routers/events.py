from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import detected_events
from app.db import get_session
from app.dependencies import get_connections
from app.inbox import NotFoundError
from app.models import DetectedEventStatus
from app.schemas import DetectedEventOut, DetectedEventsOut, EventDetectedEvent, detected_event_out
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
