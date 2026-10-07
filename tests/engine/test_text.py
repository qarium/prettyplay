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


class TestAriaSnapshotExclusion:
    """The bulky page-state section never reaches reports, renders or requests."""

    def test_failed_check_message_loses_the_trailing_aria_snapshot(self) -> None:
        message = (
            'Timed out 5000ms waiting for locator("li").first\n'
            "Actual value: hidden\n"
            'Call log:\n  - Expect "to_be_visible" ...\n\n'
            'Aria snapshot:\n- navigation:\n  - alert\n- banner:\n  - button "Войти"'
        )

        assert format_step_error(AssertionError(message)) == (
            'Timed out 5000ms waiting for locator("li").first\n'
            "Actual value: hidden\n"
            'Call log:\n  - Expect "to_be_visible" ...'
        )

    def test_message_without_the_section_passes_through_unchanged(self) -> None:
        message = 'Timed out 5000ms waiting for locator("li").first\nActual value: hidden'

        assert format_step_error(AssertionError(message)) == message

    def test_section_only_message_yields_the_empty_check_text(self) -> None:
        assert format_step_error(AssertionError("Aria snapshot:\n- banner:\n  - img")) == ""

    def test_typed_failure_also_loses_the_section(self) -> None:
        message = "click timeout\nAria snapshot:\n- banner:\n  - img"

        assert format_step_error(TimeoutError(message)) == "TimeoutError: click timeout"

    def test_indented_section_header_is_not_a_section_boundary(self) -> None:
        # an indented "Aria snapshot:" inside a Call log block is content, not the header
        message = "Call log:\n  - waiting\n    Aria snapshot:\n    - banner"

        assert format_step_error(AssertionError(message)) == message

    def test_header_with_trailing_spaces_still_bounds_the_section(self) -> None:
        assert format_step_error(AssertionError("hidden\nAria snapshot:  \n- banner")) == "hidden"
