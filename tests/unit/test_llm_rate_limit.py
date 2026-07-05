"""Unit tests for the LLM per-provider rate limiter (dark-engine audit item 48).

Hermetic and instantaneous: clock/sleep are injected fakes, so no test here
consumes real wall-clock time even when exercising the "must wait" path.
"""

from __future__ import annotations

from applicant.adapters.llm.rate_limit import LLMRateLimiter


class _FakeClock:
    """A manually-advanced monotonic clock stand-in."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _never_called(*_args, **_kwargs):
    raise AssertionError("clock/sleep must not be called when the limiter is disabled")


# --- "0 disables" ------------------------------------------------------------
def test_zero_limit_disables_with_zero_overhead():
    limiter = LLMRateLimiter(0, 60.0, clock=_never_called, sleep=_never_called)
    assert limiter.enabled is False
    # Admits every call, and never touches clock/sleep (byte-identical to no gate).
    for _ in range(50):
        assert limiter.acquire("provider|https://x") is True


def test_none_limit_disables():
    limiter = LLMRateLimiter(None, 60.0, clock=_never_called, sleep=_never_called)
    assert limiter.enabled is False
    assert limiter.acquire("k") is True


def test_none_period_disables():
    limiter = LLMRateLimiter(30, None, clock=_never_called, sleep=_never_called)
    assert limiter.enabled is False
    assert limiter.acquire("k") is True


def test_negative_limit_disables():
    limiter = LLMRateLimiter(-1, 60.0, clock=_never_called, sleep=_never_called)
    assert limiter.enabled is False


# --- admits up to N, gates N+1 ------------------------------------------------
def test_admits_up_to_limit_then_gates_next():
    clock = _FakeClock()
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        # Do NOT advance the clock: simulate the window still being full after the
        # wait (e.g. a burst that keeps re-filling) so the retry still fails.

    limiter = LLMRateLimiter(2, 100.0, clock=clock, sleep=fake_sleep)
    assert limiter.enabled is True
    assert limiter.acquire("k") is True
    assert limiter.acquire("k") is True
    # Third call within the window: over the limit -> gated, even after one bounded
    # wait (clock didn't advance in this fake, so the retry still finds no room).
    assert limiter.acquire("k") is False
    assert sleep_calls == [100.0]


def test_gate_is_per_key_not_global():
    clock = _FakeClock()
    limiter = LLMRateLimiter(1, 100.0, clock=clock, sleep=lambda s: None)
    assert limiter.acquire("openai|https://a") is True
    # A DIFFERENT key (different provider/endpoint) has its own budget.
    assert limiter.acquire("openai|https://b") is True
    # The first key is still exhausted.
    assert limiter.acquire("openai|https://a") is False


# --- bounded wait, then succeeds ----------------------------------------------
def test_waits_bounded_by_period_then_admits():
    clock = _FakeClock()
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        clock.advance(seconds)  # simulate real time passing during the wait

    limiter = LLMRateLimiter(1, 10.0, clock=clock, sleep=fake_sleep)
    assert limiter.acquire("k") is True  # t=0, consumes the only slot
    assert limiter.acquire("k") is True  # must wait for the window to roll, then admit
    assert sleep_calls == [10.0]  # exactly the window period -- never more
    assert clock.t == 10.0


def test_wait_is_never_longer_than_the_configured_period():
    clock = _FakeClock()
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    limiter = LLMRateLimiter(1, 5.0, clock=clock, sleep=fake_sleep)
    limiter.acquire("k")
    limiter.acquire("k")  # gated -> exactly one bounded wait attempt
    assert len(sleep_calls) == 1  # never a retry loop
    assert 0.0 <= sleep_calls[0] <= 5.0  # bounded by the period -- never unbounded


def test_never_hangs_single_wait_per_acquire_call():
    """Structural proof there is no internal retry loop: sleep is called at most once
    per ``acquire``, however many times the caller invokes ``acquire`` itself."""
    clock = _FakeClock()
    sleep_call_count = {"n": 0}

    def fake_sleep(seconds: float) -> None:
        sleep_call_count["n"] += 1

    limiter = LLMRateLimiter(1, 1000.0, clock=clock, sleep=fake_sleep)
    for _ in range(5):
        limiter.acquire("k")
    # 5 acquire() calls, limit=1: the 1st admits immediately (no sleep); each of the
    # remaining 4 triggers AT MOST one sleep call -- never more per call.
    assert sleep_call_count["n"] <= 4


# --- reset ---------------------------------------------------------------------
def test_reset_clears_one_key_or_all():
    clock = _FakeClock()
    limiter = LLMRateLimiter(1, 100.0, clock=clock, sleep=lambda s: None)
    assert limiter.acquire("k") is True
    assert limiter.acquire("k") is False
    limiter.reset("k")
    assert limiter.acquire("k") is True

    assert limiter.acquire("j") is True
    assert limiter.acquire("j") is False
    limiter.reset()  # clear everything
    assert limiter.acquire("j") is True
