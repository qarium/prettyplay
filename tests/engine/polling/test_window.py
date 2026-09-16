"""Tests for the SettleWindow of the prettyplay.engine.polling cell."""

import pytest
from prettyplay.engine.polling import SettleWindow
from prettyplay.engine.polling import window as window_module


class _MonotonicClock:
    """A fake monotonic clock advanced by assignment — no real sleeps."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now


def test_settle_window_constructs_and_exposes_the_contract_surface() -> None:
    """The window keeps its two public attributes and the enabled/method set."""
    window = SettleWindow(6.0, 0.5)

    assert window.timeout == 6.0
    assert window.delay == 0.5
    assert isinstance(window.enabled, bool)
    assert callable(window.start)
    assert callable(window.has_remaining)


@pytest.mark.parametrize(
    ("timeout", "expected_enabled"),
    [
        pytest.param(None, False, id="none-disabled"),
        pytest.param(0, False, id="zero-explicit-disable"),
        pytest.param(5.0, True, id="positive-enabled"),
    ],
)
def test_window_state_table(
    monkeypatch: pytest.MonkeyPatch,
    timeout: float | None,
    expected_enabled: bool,
) -> None:
    """The state table: disabled windows never allow a repetition; enabled ones expire at the boundary."""
    clock = _MonotonicClock()
    monkeypatch.setattr(window_module, "time", clock)
    window = SettleWindow(timeout, 0.5)

    assert window.enabled is expected_enabled
    # not started — no repetition is allowed yet, enabled or not
    assert window.has_remaining() is False

    window.start()
    if not expected_enabled:
        assert window.has_remaining() is False
        return

    clock.now = 2.0
    assert window.has_remaining() is True
    clock.now = 5.0  # the exact boundary — strict <
    assert window.has_remaining() is False
    clock.now = 6.0  # expired
    assert window.has_remaining() is False


def test_window_start_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the first start wins — a later start never shifts the window start."""
    clock = _MonotonicClock(1.0)
    monkeypatch.setattr(window_module, "time", clock)
    window = SettleWindow(5.0, 0.5)

    window.start()
    clock.now = 9.0
    window.start()

    assert window._started_at == 1.0


def test_settle_window_accepts_the_declared_tries_count() -> None:
    """The third contract parameter declares the count-bounded mode and stays exposed."""
    window = SettleWindow(None, 0.5, tries=3)

    assert window.tries == 3
    assert window.count_bounded is True


def test_settle_window_without_a_count_stays_time_bounded() -> None:
    """No declared count — the time-bounded mode of today, positionally and by default."""
    defaulted = SettleWindow(5.0, 0.5)
    explicit = SettleWindow(5.0, 0.5, None)

    assert defaulted.tries is None
    assert defaulted.count_bounded is False
    assert explicit.tries is None
    assert explicit.count_bounded is False


@pytest.mark.parametrize(
    ("timeout", "tries", "expected_enabled", "expected_count_bounded"),
    [
        pytest.param(None, 2, True, True, id="count-only-alive-on-default-configs"),
        pytest.param(0, 2, True, True, id="count-alive-despite-explicit-disable"),
        pytest.param(5.0, None, True, False, id="time-window"),
        pytest.param(5.0, 2, True, True, id="both-bounds-declared"),
        pytest.param(None, None, False, False, id="fully-disabled"),
        pytest.param(0, None, False, False, id="explicit-disable"),
    ],
)
def test_window_two_mode_state_table(
    timeout: float | None,
    tries: int | None,
    expected_enabled: bool,
    expected_count_bounded: bool,
) -> None:
    """The two-mode state table: a declared count enables the window even with polling disabled."""
    window = SettleWindow(timeout, 0.5, tries)

    assert window.enabled is expected_enabled
    assert window.count_bounded is expected_count_bounded
