"""Plan detection: checking Chats for plans with the Plan Model, as new Messages arrive.

- Only Messages arriving live (`LiveUpdates`, and replies sent from uMessage) are looked at;
  First Import and scrolled-back history never are. Messages that arrive late (the laptop
  slept) are, and a plan whose start has passed by now is dropped.
- A new Message schedules a check of its Chat if the cheap pre-filter (`plan_prefilter`)
  lets it through, or if the Chat has a Pending Review Detected Event it might change
  ("actually make it 8"). The check runs once the Chat has been quiet for `settle_seconds`
  (since the last Message arrived): every new Message in the Chat restarts the wait, so a
  plan made over several Messages is read once, as a whole.
- A check sends the Chat's last `WINDOW` Messages, its Pending Review Detected Events, the
  user's time zone and now to the Plan Model. Its decision creates a Pending Review
  Detected Event anchored on the window's latest Message, or revises a Pending Review one
  (re-anchoring it there); either is pushed as `EVENT_DETECTED`. Decisions less confident
  than `confidence_threshold`, plans that have already started (all-day: whose day is
  over), and updates naming anything but a Pending Review Detected Event of that Chat
  change nothing; Confirmed and Dismissed ones are never touched (a conditional update).
- Excluded Chats are never sent (ADR-0005): they aren't scheduled, excluding a Chat cancels
  its scheduled check, a check re-reads the flag just before calling the Plan Model, and
  Messages stored while the Chat was excluded are left out of every window.
- At most `max_concurrent` Plan Model calls run at once, and one check per Chat at a time.
  A failing call is logged (and shown in `/api/status`) and changes nothing.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.protocols import (
    NewPlan,
    NoPlan,
    PendingPlan,
    PlanDecision,
    PlanDetails,
    PlanModel,
    PlanRequest,
    PlanWindowMessage,
)
from app.background import BackgroundTasks
from app.models import Chat, DetectedEvent, DetectedEventStatus, Message
from app.plan_prefilter import looks_like_plan
from app.schemas import EventDetectedEvent, detected_event_out
from app.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

# How many of a Chat's latest Messages the Plan Model reads.
WINDOW = 5

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class PlanDetectionStatus:
    enabled: bool
    reason: str | None  # why it is off
    last_error: str | None  # why the last Plan Model call failed, until one succeeds


@dataclass(frozen=True, slots=True)
class PlanTimes:
    """A plan's times resolved to UTC (all-day: local midnight of its first and last day)."""

    start: datetime
    end: datetime | None
    all_day: bool


def resolve_times(plan: PlanDetails, tz: ZoneInfo) -> PlanTimes:
    """Naive times are wall times in `tz`; aware ones are kept as the instant they name."""
    if plan.all_day:
        first = _local(plan.start, tz).date()
        last = _local(plan.end, tz).date() if plan.end else first
        return PlanTimes(
            start=_midnight(first, tz),
            end=_midnight(last, tz) if last > first else None,
            all_day=True,
        )
    start = _aware(plan.start, tz).astimezone(UTC)
    end = _aware(plan.end, tz).astimezone(UTC) if plan.end else None
    return PlanTimes(start=start, end=end if end and end > start else None, all_day=False)


def has_started(times: PlanTimes, now: datetime, tz: ZoneInfo) -> bool:
    if times.all_day:
        return (times.end or times.start).astimezone(tz).date() < now.astimezone(tz).date()
    return times.start <= now


def _aware(value: datetime, tz: ZoneInfo) -> datetime:
    return value.replace(tzinfo=tz) if value.tzinfo is None else value


def _local(value: datetime, tz: ZoneInfo) -> datetime:
    return value if value.tzinfo is None else value.astimezone(tz)


def _midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(), tzinfo=tz).astimezone(UTC)


class PlanDetection:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        plan_model: PlanModel | None,
        connections: ConnectionManager,
        tasks: BackgroundTasks,
        *,
        timezone: str,
        settle_seconds: float,
        confidence_threshold: float,
        max_concurrent: int,
        disabled_reason: str = "No Plan Model is configured",
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._plan_model = plan_model
        self._connections = connections
        self._tasks = tasks
        self._timezone = timezone
        self._tz = ZoneInfo(timezone)
        self._settle_seconds = settle_seconds
        self._threshold = confidence_threshold
        self._calls = asyncio.Semaphore(max_concurrent)
        self._disabled_reason = disabled_reason
        self._sleep = sleep
        self._timers: dict[int, asyncio.Task[None]] = {}  # Chat id -> its settle timer
        self._chat_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_error: str | None = None

    @property
    def status(self) -> PlanDetectionStatus:
        if self._plan_model is None:
            return PlanDetectionStatus(False, self._disabled_reason, None)
        return PlanDetectionStatus(True, None, self._last_error)

    async def message_arrived(self, chat_id: int, text: str) -> None:
        """A new Message was stored in Chat `chat_id` (live, not First Import or history)."""
        if self._plan_model is None:
            return
        if chat_id in self._timers:  # a check is waiting for the Chat to settle: restart it
            self._schedule(chat_id)
            return
        async with self._sessionmaker() as session:
            chat = await session.get(Chat, chat_id)
            if chat is None or chat.excluded:
                return
            if not looks_like_plan(text) and not await self._pending(session, chat_id):
                return
        self._schedule(chat_id)

    def chat_excluded(self, chat_id: int) -> None:
        """Chat `chat_id` became an Excluded Chat: drop its scheduled check."""
        if timer := self._timers.pop(chat_id, None):
            timer.cancel()

    def _schedule(self, chat_id: int) -> None:
        self.chat_excluded(chat_id)
        self._timers[chat_id] = self._tasks.start(
            self._settle_then_check(chat_id), name=f"plan-detection-chat-{chat_id}"
        )

    async def _settle_then_check(self, chat_id: int) -> None:
        await self._sleep(self._settle_seconds)
        if self._timers.get(chat_id) is asyncio.current_task():
            del self._timers[chat_id]  # from here on a new Message schedules another check
        await self.check(chat_id)

    async def check(self, chat_id: int) -> None:
        """Ask the Plan Model about the Chat's latest Messages and apply its decision."""
        assert self._plan_model is not None
        async with self._chat_locks[chat_id]:
            async with self._calls:
                async with self._sessionmaker() as session:
                    asked = await self._request(session, chat_id)
                if asked is None:
                    return
                request, anchor_id = asked
                try:
                    decision = await self._plan_model.decide(request)
                except Exception as exc:
                    logger.warning("Checking Chat %s for plans failed: %s", chat_id, exc)
                    logger.debug("Plan Model failure", exc_info=True)
                    self._last_error = str(exc) or type(exc).__name__
                    return
                self._last_error = None
            pushed = await self._apply(chat_id, anchor_id, request.now, decision)
        if pushed is not None:
            await self._connections.broadcast(pushed)

    async def _request(self, session: AsyncSession, chat_id: int) -> tuple[PlanRequest, int] | None:
        """What to ask about the Chat, and its latest Message (None: don't ask)."""
        chat = await session.get(Chat, chat_id)
        if chat is None or chat.excluded:
            return None
        newest_first = (
            await session.scalars(
                select(Message)
                .where(Message.chat_id == chat_id, ~Message.excluded_from_plans)
                .order_by(Message.sent_at.desc(), Message.id.desc())
                .limit(WINDOW)
            )
        ).all()
        if not newest_first:
            return None
        window = [
            PlanWindowMessage(m.sender_name, m.text, m.sent_at, outbound=m.outbound)
            for m in reversed(newest_first)
        ]
        pending = [
            PendingPlan(
                id=event.id,
                title=event.title,
                start=event.start_at,
                end=event.end_at,
                all_day=event.all_day,
                location=event.location,
            )
            for event in await self._pending(session, chat_id)
        ]
        request = PlanRequest(
            messages=window, pending=pending, timezone=self._timezone, now=datetime.now(UTC)
        )
        return request, newest_first[0].id

    async def _pending(self, session: AsyncSession, chat_id: int) -> list[DetectedEvent]:
        return list(
            (
                await session.scalars(
                    select(DetectedEvent)
                    .where(
                        DetectedEvent.chat_id == chat_id,
                        DetectedEvent.status == DetectedEventStatus.PENDING_REVIEW,
                    )
                    .order_by(DetectedEvent.start_at, DetectedEvent.id)
                )
            ).all()
        )

    async def _apply(
        self, chat_id: int, anchor_id: int, now: datetime, decision: PlanDecision
    ) -> EventDetectedEvent | None:
        if isinstance(decision, NoPlan):
            return None
        plan = decision.plan
        if plan.confidence < self._threshold:
            logger.info(
                "Chat %s: plan %r too uncertain (%.2f)", chat_id, plan.title, plan.confidence
            )
            return None
        times = resolve_times(plan, self._tz)
        if has_started(times, now, self._tz):
            logger.info("Chat %s: plan %r has already started", chat_id, plan.title)
            return None
        fields = {
            "anchor_message_id": anchor_id,
            "title": plan.title,
            "start_at": times.start,
            "end_at": times.end,
            "all_day": times.all_day,
            "location": plan.location,
            "confidence": plan.confidence,
        }
        async with self._sessionmaker() as session:
            if isinstance(decision, NewPlan):
                created = datetime.now(UTC)
                event = DetectedEvent(
                    chat_id=chat_id, **fields, created_at=created, updated_at=created
                )
                session.add(event)
                await session.commit()
                return EventDetectedEvent(event=detected_event_out(event), change="created")
            revised = await session.execute(
                update(DetectedEvent)
                .where(
                    DetectedEvent.id == decision.event_id,
                    DetectedEvent.chat_id == chat_id,
                    DetectedEvent.status == DetectedEventStatus.PENDING_REVIEW,
                )
                .values(**fields, updated_at=datetime.now(UTC))
            )
            if revised.rowcount == 0:  # type: ignore[attr-defined]
                logger.info(
                    "Chat %s: ignored an update to %s, which isn't Pending Review in it",
                    chat_id,
                    decision.event_id,
                )
                return None
            await session.commit()
            event = await session.get_one(DetectedEvent, decision.event_id)
            return EventDetectedEvent(event=detected_event_out(event), change="updated")
