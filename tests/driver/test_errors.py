"""Tests for the fixed pollable map of the prettyplay.driver cell."""

import pytest
from playwright.sync_api import Error
from prettyplay.driver import is_pollable_failure


def test_is_pollable_failure_is_exported_and_returns_bool() -> None:
    """The facade export exists and maps one exception to a plain bool."""
    result = is_pollable_failure(Error("Timeout 10000ms exceeded"))

    assert isinstance(result, bool)
    assert result is True


@pytest.mark.parametrize(
    ("exc", "pollable"),
    [
        # timeout — locator, action, expectation or navigation wait
        (Error("Locator.click: Timeout 10000ms exceeded."), True),
        (Error("Timeout 30000ms exceeded."), True),
        (Error("Timeout 5s exceeded."), True),
        # element state
        (Error("element is not visible"), True),
        (Error("element is not enabled"), True),
        (Error("element is outside of the viewport"), True),
        (Error("element is not attached to the DOM"), True),
        # navigation / context
        (Error("Execution context was destroyed, most likely because of a navigation."), True),
        (Error("Target closed"), True),
        (Error("Frame has been detached."), True),
        (Error("Node is detached from document"), True),
        (Error("... was interrupted by another navigation to 'https://example.com' ..."), True),
        # failed expectation — a plain AssertionError that is not the ambiguity violation
        (AssertionError("Locator expected to be visible"), True),
        # locator ambiguity — deterministic, never pollable (checked before the AssertionError rule)
        (Error("strict mode violation: locator resolved to 2 elements"), False),
        (AssertionError("strict mode violation: locator resolved to 2 elements"), False),
        # Python-level errors of the step code — not driver errors at all
        (NameError("name 'paeg' is not defined"), False),
        (TypeError("unsupported operand type(s) for +: 'int' and 'str'"), False),
        # type + pattern, never pattern alone — a timeout-looking non-driver message stays False
        (RuntimeError("Timeout 10000ms exceeded."), False),
        # unrecognized driver kind — the conservative default
        (Error("something never seen before"), False),
    ],
)
def test_is_pollable_failure_map(exc: Exception, pollable: bool) -> None:
    """The fixed map decides on the exception type and message alone."""
    assert is_pollable_failure(exc) is pollable
