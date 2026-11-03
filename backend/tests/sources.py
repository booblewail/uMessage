"""Builders for what the fake Message Source holds: Chats and Messages as Beeper reports them."""

from datetime import UTC, datetime, timedelta

from app.adapters.protocols import ChatKind, Platform, SourceChat, SourceMessage


def a_chat(
    source_id: str,
    *,
    platform: Platform = Platform.WHATSAPP,
    kind: ChatKind = ChatKind.ONE_TO_ONE,
    title: str | None = None,
    active_ago: timedelta = timedelta(minutes=1),
) -> SourceChat:
    return SourceChat(
        source_id=source_id,
        platform=platform,
        kind=kind,
        title=title or f"Chat {source_id}",
        last_activity=datetime.now(UTC) - active_ago,
    )


def a_message(
    source_id: str,
    *,
    sender: str = "Ana",
    ago: timedelta = timedelta(minutes=5),
    at: datetime | None = None,
    text: str | None = None,
    outbound: bool = False,
) -> SourceMessage:
    return SourceMessage(
        source_id=source_id,
        sender_name="You" if outbound else sender,
        sent_at=at or datetime.now(UTC) - ago,
        text=text or f"Message {source_id}",
        outbound=outbound,
    )


def messages_minutes_apart(prefix: str, count: int) -> list[SourceMessage]:
    """`count` Messages one minute apart; `<prefix>-1` is the oldest, `<prefix>-<count>` newest."""
    return [
        a_message(f"{prefix}-{n}", ago=timedelta(minutes=count - n + 1))
        for n in range(1, count + 1)
    ]
