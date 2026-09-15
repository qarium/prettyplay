"""Tests for the StepAttempt record of the prettyplay.engine cell."""

import inspect

import pytest
from prettyplay.engine import StepAttempt
from prettyplay.engine.attempts import (
    OUTCOME_COMPLIANCE_BLOCKED,
    OUTCOME_EXECUTION_FAILED,
    OUTCOME_FAILED_CHECK,
    OUTCOME_ORIGINAL,
    OUTCOME_REJECTED,
    _read_url,
)
from pydantic import ValidationError


class UrlPage:
    """Fake page facade boundary: the scripted URL value, or the failure a dead page raises."""

    def __init__(self, url: str | Exception) -> None:
        """Keep the URL script — a value to return or an exception to raise."""
        self._url = url

    @property
    def url(self) -> str:
        """Return the scripted URL, or raise the scripted failure."""
        if isinstance(self._url, Exception):
            raise self._url
        return self._url


class TestStepAttemptContract:
    """Contract tests: facade import and the frozen five-field record shape."""

    def test_step_attempt_is_importable_from_facade(self) -> None:
        assert callable(StepAttempt)

    def test_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(StepAttempt).parameters.values())

        assert [parameter.name for parameter in parameters] == [
            "code",
            "error",
            "outcome",
            "url_before",
            "url_after",
        ]
        assert all(parameter.kind == inspect.Parameter.KEYWORD_ONLY for parameter in parameters)
        assert all(parameter.default == "" for parameter in parameters)

    def test_render_is_a_method_of_the_record(self) -> None:
        assert callable(StepAttempt(code="def step(page) -> None:\n    ...\n").render)

    def test_record_is_frozen(self) -> None:
        attempt = StepAttempt(code="def step(page) -> None:\n    ...\n")

        with pytest.raises(ValidationError):
            attempt.code = "def step(page) -> None:\n    page.goto('https://a.example')\n"

    def test_outcome_labels_are_the_closed_contract_set(self) -> None:
        assert OUTCOME_ORIGINAL == "original cached code"
        assert OUTCOME_FAILED_CHECK == "failed check"
        assert OUTCOME_EXECUTION_FAILED == "execution failed"
        assert OUTCOME_COMPLIANCE_BLOCKED == "compliance blocked"
        assert OUTCOME_REJECTED == "rejected by the engineer, not executed"


class TestStepAttemptRender:
    """Logic tests: the pinned verbatim record format."""

    def test_render_renders_every_field_verbatim(self) -> None:
        record = StepAttempt(
            code="def step(page) -> None:\n    page.goto('https://a.example')\n",
            error="TimeoutError: click timed out",
            outcome=OUTCOME_EXECUTION_FAILED,
            url_before="https://a.example",
            url_after="https://b.example",
        ).render()

        assert record == (
            "execution failed\n"
            "url: https://a.example -> https://b.example\n"
            "code:\n"
            "def step(page) -> None:\n"
            "    page.goto('https://a.example')\n"
            "error:\n"
            "TimeoutError: click timed out"
        )

    def test_render_starts_the_error_marker_on_its_own_line(self) -> None:
        record = StepAttempt(
            code="def step(page) -> None:\n    ...",  # no terminating newline
            error="RuntimeError: boom",
            outcome=OUTCOME_EXECUTION_FAILED,
            url_before="https://a.example",
            url_after="https://b.example",
        ).render()

        assert record == (
            "execution failed\n"
            "url: https://a.example -> https://b.example\n"
            "code:\n"
            "def step(page) -> None:\n"
            "    ...\n"  # the separating newline the code text itself lacks
            "error:\n"
            "RuntimeError: boom"
        )

    def test_render_omits_error_part_when_error_empty(self) -> None:
        record = StepAttempt(
            code="def step(page) -> None:\n    ...",
            error="",
            outcome=OUTCOME_REJECTED,
            url_before="u",
            url_after="u",
        ).render()

        assert record == (
            "rejected by the engineer, not executed\nurl: u -> u\ncode:\ndef step(page) -> None:\n    ..."
        )
        assert "error:" not in record

    def test_render_keeps_the_empty_url_pair_visible(self) -> None:
        record = StepAttempt(
            code="def step(page) -> None:\n    ...",
            error="TimeoutError: click timed out",
            outcome=OUTCOME_FAILED_CHECK,
            url_before="",
            url_after="",
        ).render()

        assert record.splitlines()[0] == "failed check"
        assert record.splitlines()[1] == "url:  -> "


class TestReadUrl:
    """Logic tests: the guarded URL read brackets the attempts of every engine loop."""

    def test_read_url_returns_the_page_url(self) -> None:
        assert _read_url(UrlPage("https://a.example")) == "https://a.example"

    def test_read_url_degrades_a_failed_read_to_the_empty_string(self) -> None:
        assert _read_url(UrlPage(RuntimeError("page crashed"))) == ""
