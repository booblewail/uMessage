"""The fixture Chats demo mode shows: Chats on all five Platforms, plus a Discord server
channel and a long-quiet Chat that First Import leaves out. Times are relative to now."""

from datetime import UTC, datetime, timedelta

from app.adapters.fakes import FakeMessageSource
from app.adapters.protocols import ChatKind, Platform, SourceChat, SourceMessage

YOU = "You"

# (source id, Platform, kind, title, [(sender, minutes ago, text), ...]); YOU marks
# Outbound Messages.
_Line = tuple[str, int, str]
_FIXTURES: list[tuple[str, Platform, ChatKind, str, list[_Line]]] = [
    (
        "demo-wa-climbing",
        Platform.WHATSAPP,
        ChatKind.GROUP,
        "Climbing crew",
        [
            ("Sam", 95, "Anyone up for the wall this week?"),
            (YOU, 90, "I'm in! After work?"),
            ("Lea", 12, "Thursday 7pm at Boulderhaus works for me"),
            ("Sam", 3, "Booked a slot for four of us"),
        ],
    ),
    (
        "demo-im-mum",
        Platform.IMESSAGE,
        ChatKind.ONE_TO_ONE,
        "Mum",
        [
            ("Mum", 26 * 60, "Did you get home safe?"),
            (YOU, 25 * 60, "Yes! Thanks for dinner"),
            ("Mum", 40, "Sunday lunch at ours, 1pm?"),
        ],
    ),
    (
        "demo-ig-priya",
        Platform.INSTAGRAM,
        ChatKind.ONE_TO_ONE,
        "Priya Shah",
        [
            ("Priya Shah", 180, "that gallery opening looked amazing"),
            (YOU, 170, "it was! you should come next time"),
            ("Priya Shah", 120, "deal, send me the next one"),
        ],
    ),
    (
        "demo-dc-jules",
        Platform.DISCORD,
        ChatKind.ONE_TO_ONE,
        "jules",
        [
            ("jules", 300, "gg last night"),
            (YOU, 295, "rematch friday?"),
            ("jules", 290, "friday 9pm, I'll bring snacks (virtually)"),
        ],
    ),
    (
        "demo-fb-flat",
        Platform.MESSENGER,
        ChatKind.GROUP,
        "Flat 4B",
        [
            ("Tom", 2 * 24 * 60, "Bins go out tonight"),
            (YOU, 2 * 24 * 60 - 5, "On it"),
            ("Ines", 8 * 60, "Landlord is coming Tuesday at 10 to look at the boiler"),
        ],
    ),
    (
        "demo-dc-raid",
        Platform.DISCORD,
        ChatKind.GROUP,
        "Raid night",
        [
            ("Mara", 26 * 60, "Raid reset is Wednesday"),
            (YOU, 25 * 60, "Count me in"),
        ],
    ),
    (
        "demo-wa-alex",
        Platform.WHATSAPP,
        ChatKind.ONE_TO_ONE,
        "Alex Kim",
        [
            ("Alex Kim", 6 * 24 * 60, "Here's the link to the photos from the wedding"),
            (YOU, 6 * 24 * 60 - 10, "Thank you!"),
        ],
    ),
    # Left out by First Import: a Discord server channel is not a Chat...
    (
        "demo-dc-server-general",
        Platform.DISCORD,
        ChatKind.SERVER_CHANNEL,
        "#general (Indie Hackers server)",
        [("mod-bot", 1, "Welcome to all the new folks!")],
    ),
    # ...and this Chat has been quiet for longer than First Import looks back.
    (
        "demo-wa-old-flatmate",
        Platform.WHATSAPP,
        ChatKind.ONE_TO_ONE,
        "Old flatmate",
        [("Old flatmate", 45 * 24 * 60, "Long time no see!")],
    ),
]


def demo_message_source(*, running: bool = True, now: datetime | None = None) -> FakeMessageSource:
    now = now or datetime.now(UTC)
    source = FakeMessageSource(running=running)
    for source_id, platform, kind, title, lines in _FIXTURES:
        messages = [
            SourceMessage(
                source_id=f"{source_id}-{index}",
                sender_name=sender,
                sent_at=now - timedelta(minutes=minutes_ago),
                text=text,
                outbound=sender == YOU,
            )
            for index, (sender, minutes_ago, text) in enumerate(lines, start=1)
        ]
        chat = SourceChat(
            source_id=source_id,
            platform=platform,
            kind=kind,
            title=title,
            last_activity=max(message.sent_at for message in messages),
        )
        source.add_chat(chat, messages)
    return source
