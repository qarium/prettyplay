"""Tests for the error-text policy module of the prettyplay.engine cell."""

import inspect

from prettyplay.engine import text as text_module
from prettyplay.engine.text import format_step_error


class TestTextPolicyContract:
    """Contract tests: the full-text formatter replaces the truncation policy."""

    def test_format_step_error_is_importable_from_module(self) -> None:
        assert callable(format_step_error)

    def test_format_step_error_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(format_step_error).parameters.values())

        assert [parameter.name for parameter in parameters] == ["exc"]

    def test_truncation_policy_is_gone(self) -> None:
        assert not hasattr(text_module, "first_line_short")
        assert not hasattr(text_module, "SHORT_ERROR_LENGTH")


class TestTextPolicyLogic:
    """Logic tests: the typed full-text formatting rules."""

    def test_format_step_error_message_less_exceptions(self) -> None:
        # a failed check carries no prefix — the type is the semantics; "" for a bare assert
        assert format_step_error(AssertionError()) == ""
        assert format_step_error(AssertionError("expected visible")) == "expected visible"
        # an action failure carries the type; a message-less error yields the bare type name
        assert format_step_error(TimeoutError()) == "TimeoutError"
        assert format_step_error(TimeoutError("click timeout")) == "TimeoutError: click timeout"
