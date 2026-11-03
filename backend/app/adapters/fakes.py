"""In-memory adapters for tests and demo mode; tests steer them through their attributes."""

from app.adapters.protocols import BEEPER_DESKTOP, MessageSourceStatus


class FakeMessageSource:
    """Stands in for Beeper Desktop; set `running` to simulate it being open or closed."""

    def __init__(self, *, running: bool = True) -> None:
        self.running = running

    async def status(self) -> MessageSourceStatus:
        return MessageSourceStatus(name=BEEPER_DESKTOP, running=self.running)


class FakePlanModel:
    """Stands in for Gemini."""


class FakeCalendar:
    """Stands in for Google Calendar."""
