"""Reading and reviewing stored Detected Events (plan detection itself is `plan_detection`)."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.inbox import NotFoundError
from app.models import DetectedEvent, DetectedEventStatus


class NotPendingReviewError(Exception):
    """The Detected Event was already Confirmed or Dismissed."""

    def __init__(self, event: DetectedEvent) -> None:
        super().__init__(f"Detected Event {event.id} is {event.status.value}, not pending_review")
        self.status = event.status


async def list_events(
    session: AsyncSession,
    *,
    status: DetectedEventStatus | None = None,
    chat_id: int | None = None,
) -> list[DetectedEvent]:
    """Detected Events, soonest first, optionally of one status and/or Chat."""
    query = select(DetectedEvent).order_by(DetectedEvent.start_at, DetectedEvent.id)
    if status is not None:
        query = query.where(DetectedEvent.status == status)
    if chat_id is not None:
        query = query.where(DetectedEvent.chat_id == chat_id)
    return list((await session.scalars(query)).all())


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
