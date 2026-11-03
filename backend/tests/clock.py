"""A fake clock for plan detection's settle delay: time only passes when a test advances it."""

import asyncio


class FakeClock:
    """Stands in for `asyncio.sleep` in plan detection's settle timer.

    `sleep(seconds)` waits until `advance` has moved the clock at least that far; `sleeping`
    counts the sleeps waiting, i.e. the settle timers running.
    """

    def __init__(self) -> None:
        self.now = 0.0
        self._sleepers: list[tuple[float, asyncio.Future[None]]] = []

    async def sleep(self, seconds: float) -> None:
        sleeper = (self.now + seconds, asyncio.get_running_loop().create_future())
        self._sleepers.append(sleeper)
        try:
            await sleeper[1]
        finally:
            self._sleepers.remove(sleeper)

    @property
    def sleeping(self) -> int:
        return sum(1 for _, future in self._sleepers if not future.done())

    def advance(self, seconds: float) -> None:
        """Move the clock on; every sleep due by then wakes (earliest first)."""
        self.now += seconds
        for deadline, future in sorted(self._sleepers, key=lambda sleeper: sleeper[0]):
            if deadline <= self.now and not future.done():
                future.set_result(None)
