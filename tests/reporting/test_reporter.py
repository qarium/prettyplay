"""Tests for the StepReporter visibility point of the prettyplay.reporting cell."""

import inspect
import logging

from prettyplay.reporting import StepHooks, StepReporter


class TestStepReporterContract:
    """Contract tests: facade import, construction shape, hooks-by-reference, emit signature."""

    def test_step_reporter_importable_from_facade(self) -> None:
        assert isinstance(StepReporter, type)

    def test_constructs_with_empty_hooks_list(self) -> None:
        reporter = StepReporter(hooks=[])

        assert reporter.hooks == []

    def test_hooks_is_public_list_kept_by_reference(self) -> None:
        hooks: list[StepHooks] = []
        reporter = StepReporter(hooks=hooks)

        assert isinstance(reporter.hooks, list)
        assert reporter.hooks is hooks  # add_hooks appends to the same list

        hooks.append(StepHooks())
        assert len(reporter.hooks) == 1

    def test_emit_signature_is_event_and_payload(self) -> None:
        parameters = list(inspect.signature(StepReporter.emit).parameters.values())[1:]  # drop self

        assert [parameter.name for parameter in parameters] == ["event", "payload"]


class RecordingHook(StepHooks):
    """Hook recording every received event into a shared ``calls`` list tagged with a name."""

    def __init__(self, name: str, calls: list[tuple[str, str, tuple[object, ...]]]) -> None:
        self.name = name
        self.calls = calls

    def _record(self, event: str, *values: object) -> None:
        self.calls.append((self.name, event, values))

    def on_step_started(self, step_text: str, step_type: str) -> None:
        self._record("on_step_started", step_text, step_type)

    def on_step_passed(self, step_text: str, step_type: str) -> None:
        self._record("on_step_passed", step_text, step_type)

    def on_step_failed(self, step_text: str, step_type: str, error: str) -> None:
        self._record("on_step_failed", step_text, step_type, error)

    def on_generation_started(self, step_text: str, attempt: int) -> None:
        self._record("on_generation_started", step_text, attempt)

    def on_healing_started(self, step_text: str, category: str) -> None:
        self._record("on_healing_started", step_text, category)

    def on_healed(self, step_text: str, explanation: str) -> None:
        self._record("on_healed", step_text, explanation)

    def on_cache_saved(self, step_text: str, filename: str) -> None:
        self._record("on_cache_saved", step_text, filename)

    def on_cache_skipped(self, step_text: str, reason: str) -> None:
        self._record("on_cache_skipped", step_text, reason)


class RaisingHook(StepHooks):
    """Hook blowing up on on_step_passed to prove a raising hook never breaks the run."""

    def on_step_passed(self, step_text: str, step_type: str) -> None:
        raise RuntimeError("hook exploded")


class KwargsCapturingHook(StepHooks):
    """Hook capturing raw kwargs to prove hooks get original keys, not sanitized ones."""

    def __init__(self) -> None:
        self.received: dict[str, object] = {}

    def on_cache_saved(self, step_text: str, filename: str) -> None:
        self.received = {"step_text": step_text, "filename": filename}


class TestStepReporterLogic:
    """Logic tests: ordered fan-out, logger records, raising-hook isolation, sanitization."""

    def test_emit_dispatches_event_to_hooks_in_order(self, caplog) -> None:
        calls: list[tuple[str, str, tuple[object, ...]]] = []
        h1 = RecordingHook("h1", calls)
        h2 = RecordingHook("h2", calls)
        reporter = StepReporter(hooks=[h1, h2])

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            reporter.emit("on_step_started", {"step_text": "открыть страницу", "step_type": "action"})

        assert calls == [
            ("h1", "on_step_started", ("открыть страницу", "action")),
            ("h2", "on_step_started", ("открыть страницу", "action")),
        ]

        info_records = [record for record in caplog.records if record.levelno == logging.INFO]
        assert len(info_records) == 1
        record = info_records[0]
        assert record.name == "prettyplay"
        assert record.message == "on_step_started"
        assert record.step_text == "открыть страницу"

    def test_raising_hook_is_skipped_and_logged(self, caplog) -> None:
        calls: list[tuple[str, str, tuple[object, ...]]] = []
        h1 = RaisingHook()
        h2 = RecordingHook("h2", calls)
        reporter = StepReporter(hooks=[h1, h2])

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            reporter.emit("on_step_passed", {"step_text": "s", "step_type": "action"})

        assert calls == [("h2", "on_step_passed", ("s", "action"))]  # h2 received the event

        warnings = [
            record
            for record in caplog.records
            if record.levelno == logging.WARNING and record.message == "hook call failed"
        ]
        assert len(warnings) == 1  # caplog holds a WARNING from the prettyplay logger
        assert warnings[0].name == "prettyplay"

    def test_reserved_log_key_is_sanitized_but_hook_gets_original(self, caplog) -> None:
        hook = KwargsCapturingHook()
        reporter = StepReporter(hooks=[hook])

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            # filename is reserved by LogRecord — without the ctx_ prefix it would be a KeyError
            reporter.emit("on_cache_saved", {"step_text": "s", "filename": "abc.py"})

        info_records = [record for record in caplog.records if record.levelno == logging.INFO]
        assert len(info_records) == 1
        assert info_records[0].ctx_filename == "abc.py"  # sanitized: ctx_filename
        assert hook.received == {"step_text": "s", "filename": "abc.py"}  # original kwargs

    def test_empty_hooks_list_logs_only(self, caplog) -> None:
        reporter = StepReporter(hooks=[])

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            reporter.emit("on_step_started", {"step_text": "s", "step_type": "action"})

        assert reporter.hooks == []
        assert [record.message for record in caplog.records] == ["on_step_started"]

    def test_cache_skipped_logs_at_warning(self, caplog) -> None:
        reporter = StepReporter(hooks=[])

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            reporter.emit("on_cache_skipped", {"step_text": "s", "reason": "read-only cache"})

        assert [record.message for record in caplog.records] == ["on_cache_skipped"]
        assert caplog.records[0].levelno == logging.WARNING

    def test_generation_attempt_payload_flows_as_int(self, caplog) -> None:
        calls: list[tuple[str, str, tuple[object, ...]]] = []
        hook = RecordingHook("h1", calls)
        reporter = StepReporter(hooks=[hook])

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            reporter.emit("on_generation_started", {"step_text": "s", "attempt": 2})

        assert calls == [("h1", "on_generation_started", ("s", 2))]
        assert caplog.records[-1].attempt == 2
