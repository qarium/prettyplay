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
