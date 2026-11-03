"""Interfaces the backend core uses to reach the outside world."""

from dataclasses import dataclass
from typing import Protocol

BEEPER_DESKTOP = "Beeper Desktop"


@dataclass(frozen=True, slots=True)
class MessageSourceStatus:
    """Whether the Message Source (Beeper Desktop) can be reached right now."""

    name: str
    running: bool


class MessageSource(Protocol):
    """Where Chats and Messages come from and where Outbound Messages go (Beeper Desktop).

    Later tickets add listing Chats, reading Messages and sending Messages.
    """

    async def status(self) -> MessageSourceStatus: ...


class PlanModel(Protocol):
    """Turns a window of Messages into a decision about a Detected Event (Gemini).

    Its operations arrive with the Detected Event tickets.
    """


class Calendar(Protocol):
    """Creates Calendar Entries for Confirmed Detected Events (Google Calendar).

    Its operations arrive with the Calendar Entry tickets.
    """
