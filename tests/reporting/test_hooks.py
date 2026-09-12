"""Tests for the StepHooks callback contract of the prettyplay.reporting cell."""

import inspect
import logging

from prettyplay.reporting import StepHooks, StepReporter

EVENT_SIGNATURES: dict[str, list[tuple[str, type]]] = {
    "on_step_started": [("step_text", str), ("step_type", str)],
    "on_step_passed": [("step_text", str), ("step_type", str)],
    "on_step_failed": [("step_text", str), ("step_type", str), ("error", str)],
    "on_step_verdict": [("step_text", str), ("category", str), ("explanation", str), ("recommendation", str)],
    "on_step_finished": [("step_text", str), ("step_type", str), ("outcome", str)],
    "on_generation_started": [("step_text", str), ("attempt", int)],
    "on_healing_started": [("step_text", str), ("category", str)],
    "on_healed": [("step_text", str), ("explanation", str)],
    "on_cache_saved": [("step_text", str), ("filename", str)],
    "on_cache_skipped": [("step_text", str), ("reason", str)],
}

SAMPLE_VALUES: dict[type, object] = {str: "value", int: 1}


class TestStepHooksContract:
    """Contract tests: facade import, the exact ten-method surface, no-op bodies."""

    def test_step_hooks_importable_from_facade(self) -> None:
        assert isinstance(StepHooks, type)

    def test_step_hooks_constructs_without_arguments(self) -> None:
        assert StepHooks() is not None

    def test_all_ten_methods_declared_with_exact_signatures(self) -> None:
        for event, expected in EVENT_SIGNATURES.items():
            method = getattr(StepHooks, event, None)
            assert callable(method), f"missing method: {event}"

            parameters = list(inspect.signature(method).parameters.values())[1:]  # drop self
            assert len(parameters) == len(expected), f"wrong parameter count: {event}"
            for parameter, (name, annotation) in zip(parameters, expected, strict=True):
                assert parameter.name == name, f"{event}: unexpected parameter {parameter.name}"
                assert parameter.annotation in (annotation, annotation.__name__), (
                    f"{event}.{name}: annotation {parameter.annotation!r} != {annotation.__name__}"
                )

    def test_base_methods_are_no_ops(self) -> None:
        hooks = StepHooks()
        for event, expected in EVENT_SIGNATURES.items():
            kwargs = {name: SAMPLE_VALUES[annotation] for name, annotation in expected}
            assert getattr(hooks, event)(**kwargs) is None, f"{event} is not a no-op"

    def test_on_step_finished_callable_no_op_with_three_arguments(self) -> None:
        hooks = StepHooks()

        assert callable(getattr(hooks, "on_step_finished", None))
        assert hooks.on_step_finished("s", "action", "passed") is None

    def test_on_step_finished_sits_between_verdict_and_generation_started(self) -> None:
        source_order = [name for name in vars(StepHooks) if not name.startswith("_")]

        assert (
            source_order.index("on_step_verdict")
            < source_order.index("on_step_finished")
            < source_order.index("on_generation_started")
        ), source_order


class RecordingHooks(StepHooks):
    """Overrides the verdict event and records every argument it receives."""

    def __init__(self) -> None:
        self.verdict_calls: list[tuple[str, str, str, str]] = []

    def on_step_verdict(self, step_text: str, category: str, explanation: str, recommendation: str) -> None:
        self.verdict_calls.append((step_text, category, explanation, recommendation))


class FinishedRecordingHooks(StepHooks):
    """Overrides the closing event and records every argument it receives."""

    def __init__(self) -> None:
        self.finished_calls: list[tuple[str, str, str]] = []

    def on_step_finished(self, step_text: str, step_type: str, outcome: str) -> None:
        self.finished_calls.append((step_text, step_type, outcome))


class TestStepVerdictLogic:
    """Logic tests: the verdict event no-op base and the four-field payload delivery."""

    def test_verdict_base_is_no_op(self) -> None:
        assert StepHooks().on_step_verdict("s", "incurable", "e", "rec") is None

    def test_verdict_event_dispatches_the_four_string_fields_to_the_hook(self) -> None:
        hooks = RecordingHooks()

        StepReporter(hooks=[hooks]).emit(
            "on_step_verdict",
            {
                "step_text": "click Sign in",
                "category": "product_defect",
                "explanation": "the total shows 90",
                "recommendation": "file a bug",
            },
        )

        assert hooks.verdict_calls == [("click Sign in", "product_defect", "the total shows 90", "file a bug")]
        assert all(isinstance(value, str) for value in hooks.verdict_calls[0])


class TestStepFinishedLogic:
    """Logic tests: the closing event payload delivery and its step-lifecycle INFO record."""

    def test_finished_base_is_no_op(self) -> None:
        assert StepHooks().on_step_finished("s", "action", "failed") is None

    def test_finished_event_dispatches_the_three_string_fields_to_the_hook(self, caplog) -> None:
        hooks = FinishedRecordingHooks()

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            StepReporter(hooks=[hooks]).emit(
                "on_step_finished",
                {"step_text": "s", "step_type": "action", "outcome": "passed"},
            )

        assert hooks.finished_calls == [("s", "action", "passed")]
        assert all(isinstance(value, str) for value in hooks.finished_calls[0])

        info_records = [record for record in caplog.records if record.levelno == logging.INFO]
        assert len(info_records) == 1
        assert info_records[0].name == "prettyplay"
        assert info_records[0].message == "on_step_finished"
