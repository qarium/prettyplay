"""Regression tests of the example's console log formatter."""

import logging
import runpy
import sys
from pathlib import Path
from unittest import mock

import pytest

EXAMPLE_CONFTEST = Path(__file__).resolve().parents[2] / "example" / "conftest.py"
STEP_CODE = "def step(page) -> None:\n    page.goto('https://example.test')\n\n"


@pytest.fixture(scope="module")
def formatter_type() -> type[logging.Formatter]:
    """Load the actual formatter without Allure or global handler side effects.

    Returns:
        The formatter class declared in the example configuration.
    """
    logger = logging.getLogger("prettyplay")

    with (
        mock.patch.dict(sys.modules, {"allure": mock.Mock()}),
        mock.patch.object(logger, "addHandler"),
        mock.patch.object(logger, "setLevel"),
    ):
        namespace = runpy.run_path(str(EXAMPLE_CONFTEST))

    return namespace["EventFormatter"]


class TestEventFormatter:
    """Readable console output retains the complete structured log record."""

    @pytest.mark.parametrize(
        ("event", "message", "args", "context"),
        [
            (
                "step_candidate_code",
                "candidate code (attempt %d):\n%s",
                (1, STEP_CODE),
                {"attempt": 1, "code": STEP_CODE},
            ),
            ("step_cached_code", "cached code (replay):\n%s", (STEP_CODE,), {"code": STEP_CODE}),
            ("step_results_declared", "saves into: %s", ("video_title",), {"declarations": ("video_title",)}),
            ("step_inputs", "inputs: %s", ("query = 'vibe coding'",), {"inputs": {"query": "vibe coding"}}),
            ("step_captured", "captured: %s", ("video_title = 'Title'",), {"captures": {"video_title": "Title"}}),
        ],
    )
    def test_execution_context_prints_once_without_removing_metadata(
        self,
        formatter_type: type[logging.Formatter],
        event: str,
        message: str,
        args: tuple[int | str, ...],
        context: dict[str, object],
    ) -> None:
        """Keep readable messages and metadata intact across multiple handlers.

        Args:
            formatter_type: The production example formatter class.
            event: The execution-context event identifier.
            message: The human-readable message template.
            args: The formatting arguments of the message.
            context: The event's structured fields.
        """
        record = logging.makeLogRecord(
            {"msg": message, "args": args, "levelname": "INFO", "event": event, "step_text": "Save title", **context}
        )
        formatter = formatter_type("%(levelname)s %(message)s")
        expected = f"INFO {record.getMessage()}"

        assert formatter.format(record) == expected
        assert formatter.format(record) == expected
        assert record.msg == message
        assert record.args == args
        assert record.event == event
        assert record.step_text == "Save title"
        for key, value in context.items():
            assert getattr(record, key) == value

        structured_output = logging.Formatter("%(event)s | %(step_text)s").format(record)
        assert structured_output == f"{event} | Save title"

    @pytest.mark.parametrize(
        ("message", "context", "payload"),
        [
            (
                "on_step_started",
                {"step_type": "action", "step_text": "Open page"},
                "step_text='Open page' step_type='action'",
            ),
            (
                "generation_request",
                {"step_text": "Open page", "request_ms": 123},
                "request_ms=123 step_text='Open page'",
            ),
            (
                "step_execution",
                {"step_text": "Open page", "attempt": 1, "execution_ms": 54},
                "attempt=1 execution_ms=54 step_text='Open page'",
            ),
            (
                "compliance findings passed",
                {"step_text": "Open page", "findings": ["low instruction"]},
                "findings=['low instruction'] step_text='Open page'",
            ),
            (
                "verdict skipped",
                {"event": "verdict_skipped", "reason": "llm_unavailable"},
                "event='verdict_skipped' reason='llm_unavailable'",
            ),
            (
                "cache sweep failed on close",
                {"event": "cache_sweep_failed", "cleanup": True},
                "cleanup=True event='cache_sweep_failed'",
            ),
            (
                "hook call failed",
                {"event": "on_step_started", "hook": "BrokenHook"},
                "event='on_step_started' hook='BrokenHook'",
            ),
            ("custom event", {"event": "custom_event", "code": STEP_CODE}, f"code={STEP_CODE!r} event='custom_event'"),
        ],
    )
    def test_other_events_keep_sorted_context(
        self, formatter_type: type[logging.Formatter], message: str, context: dict[str, object], payload: str
    ) -> None:
        """Preserve the existing console payload of unrelated records.

        Args:
            formatter_type: The production example formatter class.
            message: The event's existing message.
            context: The event's structured fields.
            payload: The expected sorted payload suffix.
        """
        record = logging.makeLogRecord({"msg": message, "args": (), **context})

        assert formatter_type("%(message)s").format(record) == f"{message} | {payload}"

    def test_plain_message_keeps_no_payload_suffix(self, formatter_type: type[logging.Formatter]) -> None:
        """Ignore reserved and private fields when the record has no public context.

        Args:
            formatter_type: The production example formatter class.
        """
        record = logging.makeLogRecord({"msg": "plain message", "args": (), "levelname": "INFO", "_private": "hidden"})

        assert formatter_type("%(levelname)s %(message)s").format(record) == "INFO plain message"

    @pytest.mark.parametrize("event", [None, ["step_cached_code"], {"name": "step_cached_code"}])
    def test_non_string_event_keeps_its_payload(self, formatter_type: type[logging.Formatter], event: object) -> None:
        """Preserve arbitrary extra fields instead of assuming a hashable event name.

        Args:
            formatter_type: The production example formatter class.
            event: A non-string context value supplied by another logger consumer.
        """
        record = logging.makeLogRecord({"msg": "custom message", "args": (), "event": event})

        assert formatter_type("%(message)s").format(record) == f"custom message | event={event!r}"

    @pytest.mark.parametrize("event", ["step_cached_code", "cache_sweep_failed"])
    def test_traceback_and_stack_info_are_preserved(self, formatter_type: type[logging.Formatter], event: str) -> None:
        """Preserve diagnostic details on both console-formatting paths.

        Args:
            formatter_type: The production example formatter class.
            event: The event identifier selecting the formatting path.
        """
        try:
            raise RuntimeError("original error")
        except RuntimeError:
            record = logging.makeLogRecord(
                {
                    "msg": "failed",
                    "args": (),
                    "event": event,
                    "exc_info": sys.exc_info(),
                    "stack_info": "Stack trace context",
                }
            )

        rendered = formatter_type("%(message)s").format(record)

        assert "Traceback (most recent call last):" in rendered
        assert "RuntimeError: original error" in rendered
        assert "Stack trace context" in rendered
        if event == "step_cached_code":
            assert " | " not in rendered
        else:
            assert rendered.endswith(" | event='cache_sweep_failed'")
