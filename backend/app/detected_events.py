"""Reading and reviewing stored Detected Events (plan detection itself is `plan_detection`)."""

from collections import defaultdict
from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.inbox import NotFoundError
from app.models import Chat, DetectedEvent, DetectedEventStatus, Message
from app.schemas import DetectedEventOut, detected_event_out


class NotPendingReviewError(Exception):
    """The Detected Event was already Confirmed or Dismissed (or is being confirmed)."""

    def __init__(self, event: DetectedEvent) -> None:
        if event.status is DetectedEventStatus.CONFIRMING:
            message = f"Detected Event {event.id} is being added to the calendar right now"
        else:
            message = f"Detected Event {event.id} is {event.status.value}, not pending_review"
        super().__init__(message)
        self.status = event.status


async def list_events(
    session: AsyncSession,
    *,
    statuses: Collection[DetectedEventStatus] = (),
    chat_id: int | None = None,
    starting_from: datetime | None = None,
) -> list[DetectedEvent]:
    """Detected Events, soonest first: of any of `statuses` (all when empty), of one Chat,
    starting at or after `starting_from`."""
    query = select(DetectedEvent).order_by(DetectedEvent.start_at, DetectedEvent.id)
    if statuses:
        query = query.where(DetectedEvent.status.in_(statuses))
    if chat_id is not None:
        query = query.where(DetectedEvent.chat_id == chat_id)
    if starting_from is not None:
        query = query.where(DetectedEvent.start_at >= starting_from)
    return list((await session.scalars(query)).all())


async def views(
    session: AsyncSession, events: Sequence[DetectedEvent], *, timezone: str
) -> dict[int, DetectedEventOut]:
    """The Detected Events as the API shows them (with their Chat and Anchor Message), by id."""
    if not events:
        return {}
    chat_ids = {event.chat_id for event in events}
    chats = {
        chat.id: chat for chat in await session.scalars(select(Chat).where(Chat.id.in_(chat_ids)))
    }
    anchor_ids = {event.anchor_message_id for event in events}
    anchors = {
        message.id: message
        for message in await session.scalars(select(Message).where(Message.id.in_(anchor_ids)))
    }
    on_calendar = await upcoming_calendar_entries(
        session, chat_ids, timezone=timezone, now=datetime.now(UTC)
    )
    return {
        event.id: detected_event_out(
            event,
            chats[event.chat_id],
            anchors[event.anchor_message_id],
            on_calendar.get(event.chat_id, ()),
        )
        for event in events
    }


async def upcoming_calendar_entries(
    session: AsyncSession, chat_ids: Collection[int], *, timezone: str, now: datetime
) -> dict[int, list[DetectedEvent]]:
    """Each Chat's Confirmed Detected Events (its Calendar Entries) that aren't over: whose
    start isn't past, or for an all-day one, whose last day isn't, soonest first."""
    tz = ZoneInfo(timezone)
    # Timed ones that start later; all-day ones are checked by their last (local) day below.
    confirmed = await session.scalars(
        select(DetectedEvent)
        .where(
            DetectedEvent.chat_id.in_(chat_ids),
            DetectedEvent.status == DetectedEventStatus.CONFIRMED,
            or_(
                DetectedEvent.start_at > now,
                DetectedEvent.all_day,
            ),
        )
        .order_by(DetectedEvent.start_at, DetectedEvent.id)
    )
    today = now.astimezone(tz).date()
    by_chat: defaultdict[int, list[DetectedEvent]] = defaultdict(list)
    for event in confirmed:
        last = event.end_at or event.start_at
        if (last.astimezone(tz).date() >= today) if event.all_day else event.start_at > now:
            by_chat[event.chat_id].append(event)
    return by_chat


async def view(session: AsyncSession, event: DetectedEvent, *, timezone: str) -> DetectedEventOut:
    return (await views(session, [event], timezone=timezone))[event.id]


async def anchored_on(
    session: AsyncSession, message_ids: Sequence[int]
) -> dict[int, list[DetectedEvent]]:
    """The Detected Events each of these Messages is the Anchor Message of, by Message id."""
    by_anchor: defaultdict[int, list[DetectedEvent]] = defaultdict(list)
    if message_ids:
        events = await session.scalars(
            select(DetectedEvent)
            .where(DetectedEvent.anchor_message_id.in_(message_ids))
            .order_by(DetectedEvent.start_at, DetectedEvent.id)
        )
        for event in events:
            by_anchor[event.anchor_message_id].append(event)
    return by_anchor


async def dismiss(session: AsyncSession, event_id: int) -> DetectedEvent:
    """Pending Review -> Dismissed, as one conditional update (ADR-0004), so it can't undo a
    Confirmed one. Raises NotFoundError, or NotPendingReviewError if it isn't pending."""
    dismissed = await session.execute(
        update(DetectedEvent)
        .where(
            DetectedEvent.id == event_id,
            DetectedEvent.status == DetectedEventStatus.PENDING_REVIEW,
        )
        .values(status=DetectedEventStatus.DISMISSED, updated_at=datetime.now(UTC))
    )
    event = await session.get(DetectedEvent, event_id, populate_existing=True)
    if event is None:
        raise NotFoundError(f"no Detected Event {event_id}")
    if dismissed.rowcount == 0:  # type: ignore[attr-defined]
        raise NotPendingReviewError(event)
    await session.commit()
    return event
