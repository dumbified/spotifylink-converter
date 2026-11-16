"""Two small guards that keep the bot from doing the same work too often.

Both keep their notes in memory, which is fine for one small server. They
forget everything on restart; nothing here needs to survive one.
"""

import time
from collections import OrderedDict, deque
from collections.abc import Callable


class RecentIds:
    """Remembers the last N message IDs, to spot repeats.

    Meta re-sends a webhook if it thinks we did not receive it, so the same
    message can arrive twice. Without this the bot would reply twice.
    """

    def __init__(self, capacity: int = 1000) -> None:
        self._capacity = capacity
        # An OrderedDict remembers the order things were added, so the
        # oldest ID is always at the front, ready to be thrown out.
        self._ids: OrderedDict[str, None] = OrderedDict()

    def seen_before(self, message_id: str) -> bool:
        """Return True if this ID was seen already; otherwise remember it."""
        if message_id in self._ids:
            return True
        self._ids[message_id] = None
        if len(self._ids) > self._capacity:
            self._ids.popitem(last=False)  # drop the oldest
        return False


class RateLimiter:
    """Allows each sender at most `max_events` in any `window_seconds`.

    Every message makes the bot call Spotify, Apple and Meta. This stops a
    flood of messages (a bug, or someone misusing the bot) from turning into
    a flood of outgoing requests.
    """

    def __init__(
        self,
        max_events: int = 10,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_events = max_events
        self._window = window_seconds
        self._clock = clock  # replaceable, so tests can control time
        self._events: dict[str, deque[float]] = {}

    def allow(self, sender: str) -> bool:
        """Return True and count the event, or False if the sender is over the limit."""
        now = self._clock()
        times = self._events.setdefault(sender, deque())

        # Forget events that have slid out of the time window.
        while times and now - times[0] >= self._window:
            times.popleft()

        if len(times) >= self._max_events:
            return False
        times.append(now)
        return True
