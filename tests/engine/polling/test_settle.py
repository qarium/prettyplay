"""Tests for the settle loop of the prettyplay.engine.polling cell."""

import importlib
import logging
from types import SimpleNamespace
from unittest import mock

import pytest
from playwright.sync_api import Error as PlaywrightError
from prettyplay.engine.polling import SettleWindow, settle
from prettyplay.engine.polling import window as window_module

from tests.engine.polling.test_window import _MonotonicClock

#: the settle module itself — the package facade re-exports the ``settle`` name as the function
SETTLE_MODULE = importlib.import_module("prettyplay.engine.polling.settle")


def _fake_page() -> SimpleNamespace:
    """A fake page facade — settle only forwards it to the execute routine."""
    return SimpleNamespace(
        aria_snapshot=mock.Mock(return_value="- heading: Pay"),
        screenshot=mock.Mock(return_value=b"png"),
    )


def _retries(caplog: pytest.LogCaptureFixture) -> list:
    """The settle_retry records captured so far."""
    return [record for record in caplog.records if record.getMessage() == "settle_retry"]


def test_settle_is_importable_and_callable_with_the_contract_parameters() -> None:
    """The facade exports settle; it runs with the four contract parameters."""
    result = settle(mock.Mock(), "CODE", _fake_page(), SettleWindow(None, 0.5))

    assert result is None


def test_settle_retries_pollable_failure_until_success(caplog: pytest.LogCaptureFixture) -> None:
    """A pollable failure is re-executed until the code works; every repetition logs settle_retry."""
    page = _fake_page()
    failure = PlaywrightError("Timeout 10000ms exceeded")
    execute = mock.Mock(side_effect=[failure, failure, None])
    window = SettleWindow(5.0, 0)

    with caplog.at_level(logging.INFO, logger="prettyplay"):
        settle(execute, "CODE", page, window)

    assert execute.call_count == 3
    assert execute.call_args_list == [
        mock.call("CODE", page),
        mock.call("CODE", page),
        mock.call("CODE", page),
    ]

    retries = _retries(caplog)

    assert [record.attempt for record in retries] == [1, 2]
    assert [record.error for record in retries] == ["Timeout 10000ms exceeded"] * 2
    assert all(record.levelno == logging.INFO for record in retries)


def test_settle_passes_code_and_page_to_execute() -> None:
    """The execute routine receives the code text and the page facade verbatim."""
    page = _fake_page()
    execute = mock.Mock()

    settle(execute, "CODE", page, SettleWindow(None, 0.5))

    execute.assert_called_once_with("CODE", page)


def test_settle_propagates_non_pollable_failure_immediately(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A non-pollable failure propagates as the identical object — one execution, no repetitions."""
    page = _fake_page()
    original = PlaywrightError("strict mode violation: locator resolved to 2 elements")
    execute = mock.Mock(side_effect=original)
    window = SettleWindow(5.0, 0)

    with (
        caplog.at_level(logging.INFO, logger="prettyplay"),
        pytest.raises(PlaywrightError) as excinfo,
    ):
        settle(execute, "CODE", page, window)

    assert excinfo.value is original
    assert execute.call_count == 1
    assert _retries(caplog) == []


def test_settle_disabled_window_single_execution(caplog: pytest.LogCaptureFixture) -> None:
    """A disabled window degenerates to one execution — even a pollable failure propagates."""
    page = _fake_page()
    original = PlaywrightError("Timeout 10000ms exceeded")
    execute = mock.Mock(side_effect=original)
    window = SettleWindow(None, 0)

    with (
        caplog.at_level(logging.INFO, logger="prettyplay"),
        pytest.raises(PlaywrightError) as excinfo,
    ):
        settle(execute, "CODE", page, window)

    assert excinfo.value is original
    assert execute.call_count == 1
    assert _retries(caplog) == []


def test_settle_never_intercepts_base_exception() -> None:
    """KeyboardInterrupt is a BaseException — it escapes the loop uncaught, never retried."""
    page = _fake_page()
    interrupt = KeyboardInterrupt()
    execute = mock.Mock(side_effect=interrupt)
    window = SettleWindow(5.0, 0)

    with pytest.raises(KeyboardInterrupt) as excinfo:
        settle(execute, "CODE", page, window)

    assert excinfo.value is interrupt
    assert execute.call_count == 1


def test_settle_sleeps_the_window_delay_between_repetitions(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every repetition pauses for the configured delay — never for the timeout, never zero-sleeps a positive one."""
    fake_time = mock.Mock()
    monkeypatch.setattr(SETTLE_MODULE, "time", fake_time)
    page = _fake_page()
    execute = mock.Mock(side_effect=[PlaywrightError("Timeout 10000ms exceeded"), None])
    window = SettleWindow(5.0, 0.25)

    with caplog.at_level(logging.INFO, logger="prettyplay"):
        settle(execute, "CODE", page, window)

    assert fake_time.sleep.call_args_list == [mock.call(0.25)]  # the delay, once per repetition


def test_settle_expired_window_propagates_the_pollable_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A pollable failure past the window horizon propagates — the window gates repetitions by time alone."""
    clock = _MonotonicClock()
    monkeypatch.setattr(window_module, "time", clock)
    page = _fake_page()
    original = PlaywrightError("Timeout 10000ms exceeded")

    def advance_and_fail(_code: str, _page: SimpleNamespace) -> None:
        clock.now += 3.0  # two executions outlive the 5-second horizon
        raise original

    execute = mock.Mock(side_effect=advance_and_fail)

    window = SettleWindow(5.0, 0)

    with (
        caplog.at_level(logging.INFO, logger="prettyplay"),
        pytest.raises(PlaywrightError) as excinfo,
    ):
        settle(execute, "CODE", page, window)

    assert excinfo.value is original
    assert execute.call_count == 2  # one repetition inside the window, then the horizon stops the loop
    retries = _retries(caplog)
    assert [record.attempt for record in retries] == [1]
