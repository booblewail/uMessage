"""Confirming a Detected Event: its Calendar Entry is created exactly once (ADR-0004).

Confirming first claims the Detected Event with one conditional update (Pending Review ->
`confirming`), and only then asks the Calendar, so of two confirms at once (a double-click)
only one gets that far; the other is a conflict. Once the Calendar Entry exists it becomes
Confirmed; if the Calendar fails it is Pending Review again. A confirm cut short (the app
stopped mid-call) is released when the app next starts (`release_unfinished_confirms`).

The user may edit the plan while confirming (`Edits`); the Detected Event takes on what was
put on the calendar, including the default length given to a timed plan without an end.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum, auto
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.protocols import (
    Calendar,
    CalendarEntryRequest,
    CalendarUnavailableError,
    Platform,
)
from app.detected_events import NotPendingReviewError
from app.inbox import NotFoundError
from app.models import Chat, DetectedEvent, DetectedEventStatus, Message

logger = logging.getLogger(__name__)

# How many Messages (the Anchor Message and those just before it) a Calendar Entry quotes.
QUOTED_MESSAGES = 5

PLATFORM_NAMES = {
    Platform.IMESSAGE: "iMessage",
    Platform.INSTAGRAM: "Instagram",
    Platform.MESSENGER: "Messenger",
    Platform.WHATSAPP: "WhatsApp",
    Platform.DISCORD: "Discord",
}


class _Unset(Enum):
    UNSET = auto()


UNSET = _Unset.UNSET


@dataclass(frozen=True, slots=True)
class Edits:
    """What the user changed before confirming; anything left UNSET stays as detected.

    `start`/`end` are aware datetimes for a timed plan, dates (first and last day, inclusive)
    for an all-day one; `end` None means "no end" (a timed plan gets the default length).
    Changing `all_day` needs a `start` too.
    """

    title: str | _Unset = UNSET
    start: datetime | date | _Unset = UNSET
    end: datetime | date | _Unset | None = UNSET
    all_day: bool | _Unset = UNSET
    location: str | _Unset | None = UNSET


class CalendarEntryFailedError(Exception):
    """The Calendar didn't create the Calendar Entry (it raised something other than
    `CalendarUnavailableError`); the Detected Event is Pending Review again."""


class InvalidEditsError(ValueError):
    """The edited plan doesn't make sense; `field` is the edit at fault."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True, slots=True)
class _Plan:
    """The plan as it goes on the calendar, and as the Detected Event then stores it."""

    title: str
    all_day: bool
    entry_start: datetime | date
    entry_end: datetime | date
    start_at: datetime  # UTC; all-day: local midnight of the first day
    end_at: datetime | None  # UTC; all-day: local midnight of the last day (None: one day)
    location: str | None


async def confirm(
    session: AsyncSession,
    calendar: Calendar,
    event_id: int,
    edits: Edits,
    *,
    timezone: str,
    default_duration: timedelta,
) -> DetectedEvent:
    """Create the Detected Event's Calendar Entry and make it Confirmed.

    Raises NotFoundError, NotPendingReviewError (it is Confirmed, Dismissed or being
    confirmed), InvalidEditsError, CalendarUnavailableError or CalendarEntryFailedError (it
    is then Pending Review again).
    """
    claimed = await session.execute(
        update(DetectedEvent)
        .where(
            DetectedEvent.id == event_id,
            DetectedEvent.status == DetectedEventStatus.PENDING_REVIEW,
        )
        .values(status=DetectedEventStatus.CONFIRMING)
    )
    event = await session.get(DetectedEvent, event_id, populate_existing=True)
    if event is None:
        raise NotFoundError(f"no Detected Event {event_id}")
    if claimed.rowcount == 0:  # type: ignore[attr-defined]
        raise NotPendingReviewError(event)
    await session.commit()  # the claim is visible to every other request from here on
    try:
        plan = _apply_edits(event, edits, ZoneInfo(timezone), default_duration)
        request = CalendarEntryRequest(
            title=plan.title,
            start=plan.entry_start,
            end=plan.entry_end,
            timezone=timezone,
            location=plan.location,
            description=await _quote_chat(session, event),
        )
        try:
            entry_id = await calendar.create_entry(request)
        except CalendarUnavailableError:
            raise
        except Exception as exc:
            logger.warning("Creating the Calendar Entry for %s failed: %r", event_id, exc)
            raise CalendarEntryFailedError(str(exc) or type(exc).__name__) from exc
    except Exception:
        await _set_status(session, event_id, DetectedEventStatus.PENDING_REVIEW)
        raise
    await session.execute(
        update(DetectedEvent)
        .where(DetectedEvent.id == event_id, DetectedEvent.status == DetectedEventStatus.CONFIRMING)
        .values(
            status=DetectedEventStatus.CONFIRMED,
            calendar_entry_id=entry_id,
            title=plan.title,
            all_day=plan.all_day,
            start_at=plan.start_at,
            end_at=plan.end_at,
            location=plan.location,
            updated_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return await session.get_one(DetectedEvent, event_id, populate_existing=True)


async def release_unfinished_confirms(session: AsyncSession) -> int:
    """Make Detected Events left mid-confirm (the app stopped while asking the Calendar)
    Pending Review again. Only call it before any confirm can be running (at startup)."""
    released = await session.execute(
        update(DetectedEvent)
        .where(DetectedEvent.status == DetectedEventStatus.CONFIRMING)
        .values(status=DetectedEventStatus.PENDING_REVIEW)
    )
    await session.commit()
    count: int = released.rowcount  # type: ignore[attr-defined]
    if count:
        logger.warning("%d Detected Event(s) left mid-confirm are Pending Review again", count)
    return count


async def _set_status(session: AsyncSession, event_id: int, to: DetectedEventStatus) -> None:
    await session.rollback()
    await session.execute(
        update(DetectedEvent)
        .where(DetectedEvent.id == event_id, DetectedEvent.status == DetectedEventStatus.CONFIRMING)
        .values(status=to)
    )
    await session.commit()


def _apply_edits(
    event: DetectedEvent, edits: Edits, tz: ZoneInfo, default_duration: timedelta
) -> _Plan:
    title = event.title if edits.title is UNSET else edits.title
    location = event.location if edits.location is UNSET else edits.location
    all_day = event.all_day if edits.all_day is UNSET else edits.all_day
    switched = all_day != event.all_day
    if switched and edits.start is UNSET:
        raise InvalidEditsError("start", "changing allDay needs a start too")
    if all_day:
        first = (
            _day(edits.start, "start")
            if edits.start is not UNSET
            else _local_day(event.start_at, tz)
        )
        if edits.end is not UNSET:
            last = first if edits.end is None else _day(edits.end, "end")
        elif switched or event.end_at is None:
            last = first
        else:
            last = _local_day(event.end_at, tz)
        if last < first:
            raise InvalidEditsError("end", "end must be on or after start")
        return _Plan(
            title=title,
            all_day=True,
            entry_start=first,
            entry_end=last,
            start_at=_midnight(first, tz),
            end_at=_midnight(last, tz) if last > first else None,
            location=location,
        )
    start = _instant(edits.start, "start") if edits.start is not UNSET else event.start_at
    if edits.end is not UNSET:
        end = None if edits.end is None else _instant(edits.end, "end")
    else:
        end = None if switched else event.end_at
    if end is not None and end <= start:
        raise InvalidEditsError("end", "end must be after start")
    end = end or start + default_duration
    return _Plan(
        title=title,
        all_day=False,
        entry_start=start,
        entry_end=end,
        start_at=start.astimezone(UTC),
        end_at=end.astimezone(UTC),
        location=location,
    )


def _day(value: datetime | date, field: str) -> date:
    if isinstance(value, datetime):
        raise InvalidEditsError(field, f"an all-day plan's {field} is a date (YYYY-MM-DD)")
    return value


def _instant(value: datetime | date, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise InvalidEditsError(field, f"a timed plan's {field} needs a date and time")
    if value.tzinfo is None:
        raise InvalidEditsError(field, f"{field} needs a time zone (an offset or Z)")
    return value


def _local_day(value: datetime, tz: ZoneInfo) -> date:
    return value.astimezone(tz).date()


def _midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(), tzinfo=tz).astimezone(UTC)


async def _quote_chat(session: AsyncSession, event: DetectedEvent) -> str:
    """ "From WhatsApp chat 'Climbing crew':" and the Anchor Message with the few before it."""
    chat = await session.get_one(Chat, event.chat_id)
    anchor = await session.get_one(Message, event.anchor_message_id)
    newest_first = (
        await session.scalars(
            select(Message)
            .where(
                Message.chat_id == chat.id,
                ~Message.excluded_from_plans,
                or_(
                    Message.sent_at < anchor.sent_at,
                    and_(Message.sent_at == anchor.sent_at, Message.id <= anchor.id),
                ),
            )
            .order_by(Message.sent_at.desc(), Message.id.desc())
            .limit(QUOTED_MESSAGES)
        )
    ).all()
    lines = [f"From {PLATFORM_NAMES[chat.platform]} chat '{chat.title}':"]
    for message in reversed(newest_first):
        text = message.text.replace("\r\n", "\n").split("\n")
        lines.append(f"> {message.sender_name}: {text[0]}")
        lines.extend(f"> {line}" for line in text[1:])
    return "\n".join(lines)
