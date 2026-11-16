"""Tests for duplicate detection and rate limiting."""

from musiclink.whatsapp.limits import RateLimiter, RecentIds


def test_recent_ids_spots_repeats():
    recent = RecentIds()
    assert not recent.seen_before("a")
    assert recent.seen_before("a")
    assert not recent.seen_before("b")


def test_recent_ids_forgets_the_oldest_when_full():
    recent = RecentIds(capacity=2)
    recent.seen_before("a")
    recent.seen_before("b")
    recent.seen_before("c")  # pushes "a" out
    assert recent.seen_before("b")
    assert recent.seen_before("c")
    assert not recent.seen_before("a")


class FakeClock:
    """A clock the test moves by hand, so nothing has to really wait."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_rate_limiter_blocks_after_the_limit():
    limiter = RateLimiter(max_events=3, window_seconds=60, clock=FakeClock())
    assert [limiter.allow("me") for _ in range(5)] == [True, True, True, False, False]


def test_rate_limiter_counts_each_sender_separately():
    limiter = RateLimiter(max_events=1, window_seconds=60, clock=FakeClock())
    assert limiter.allow("me")
    assert limiter.allow("someone else")
    assert not limiter.allow("me")


def test_rate_limiter_allows_again_after_the_window():
    clock = FakeClock()
    limiter = RateLimiter(max_events=2, window_seconds=60, clock=clock)
    assert limiter.allow("me")
    assert limiter.allow("me")
    assert not limiter.allow("me")

    clock.now += 59
    assert not limiter.allow("me")
    clock.now += 1  # the first two events are now 60 seconds old
    assert limiter.allow("me")
