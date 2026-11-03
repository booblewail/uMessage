"""The fixture Chats demo mode shows: Chats on all five Platforms, plus a Discord server
channel and a long-quiet Chat that First Import leaves out. Times are relative to now.

`demo_trickle` then makes scripted Messages arrive every so often (one starts a new Chat), so
live updates can be seen.
"""

import asyncio
import itertools
import random
from datetime import UTC, datetime, timedelta

from app.adapters.fakes import YOU, FakeMessageSource
from app.adapters.protocols import ChatKind, Platform, SourceChat, SourceMessage

# (source id, Platform, kind, title, [(sender, minutes ago, text), ...]); YOU marks
# Outbound Messages.
_Line = tuple[str, int, str]


def _climbing_backstory() -> list[_Line]:
    """Three weeks of older climbing chat: more than First Import keeps (50 Messages), so
    scrolling back in "Climbing crew" fetches older Messages from the Message Source."""
    sessions = [
        ("Sam", "Wall tonight? Usual time?"),
        (YOU, "Yep, see you there"),
        ("Lea", "That new blue route is sandbagged"),
        ("Sam", "Anyone seen my brush? Left it by the auto-belays"),
        (YOU, "Got it, bringing it next time"),
        ("Lea", "Finally sent the overhang!"),
    ]
    lines: list[_Line] = []
    for number in range(78):
        sender, text = sessions[number % len(sessions)]
        lines.append((sender, 21 * 24 * 60 - number * 6 * 60, f"{text} (#{number + 1})"))
    return lines


_FIXTURES: list[tuple[str, Platform, ChatKind, str, list[_Line]]] = [
    (
        "demo-wa-climbing",
        Platform.WHATSAPP,
        ChatKind.GROUP,
        "Climbing crew",
        [
            *_climbing_backstory(),
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


# Who says what as demo mode's Messages trickle in, in order (then round again).
_NEW_CHAT = SourceChat(
    source_id="demo-ig-dana",
    platform=Platform.INSTAGRAM,
    kind=ChatKind.ONE_TO_ONE,
    title="Dana Ortiz",
    last_activity=datetime.now(UTC),
)
_TRICKLE: list[tuple[str, str, str]] = [
    ("demo-wa-climbing", "Lea", "Can someone bring a spare chalk bag?"),
    ("demo-im-mum", "Mum", "Dad says hi! Don't forget your umbrella"),
    (_NEW_CHAT.source_id, "Dana Ortiz", "hey!! long time, are you around this weekend?"),
    ("demo-ig-priya", "Priya Shah", "the next opening is on the 14th btw"),
    ("demo-fb-flat", "Tom", "Who finished the oat milk"),
    ("demo-dc-jules", "jules", "queue up in 5?"),
    ("demo-wa-alex", "Alex Kim", "Found a few more photos, sending now"),
    ("demo-dc-raid", "Mara", "Raid moved to 9pm"),
]


async def demo_trickle(source: FakeMessageSource, *, every_seconds: float) -> None:
    """Forever: wait about `every_seconds` (give or take a third), then a scripted Message
    arrives in the demo Message Source."""
    run = datetime.now(UTC).strftime("%Y%m%d%H%M%S")  # ids stay new across restarts
    for number in itertools.count(1):
        await asyncio.sleep(every_seconds * random.uniform(2 / 3, 4 / 3))
        chat_source_id, sender, text = _TRICKLE[(number - 1) % len(_TRICKLE)]
        message = SourceMessage(
            source_id=f"demo-live-{run}-{number}",
            sender_name=sender,
            sent_at=datetime.now(UTC),
            text=text,
            outbound=False,
        )
        if chat_source_id not in source.messages:
            source.add_chat(_NEW_CHAT, [message])
        else:
            source.receive(chat_source_id, message)
