"""Tests for the StepHooks callback contract of the prettyplay.reporting cell."""

import inspect

from prettyplay.reporting import StepHooks

EVENT_SIGNATURES: dict[str, list[tuple[str, type]]] = {
    "on_step_started": [("step_text", str), ("step_type", str)],
    "on_step_passed": [("step_text", str), ("step_type", str)],
    "on_step_failed": [("step_text", str), ("step_type", str), ("error", str)],
    "on_step_verdict": [("step_text", str), ("category", str), ("explanation", str), ("recommendation", str)],
    "on_generation_started": [("step_text", str), ("attempt", int)],
    "on_healing_started": [("step_text", str), ("category", str)],
    "on_healed": [("step_text", str), ("explanation", str)],
    "on_cache_saved": [("step_text", str), ("filename", str)],
    "on_cache_skipped": [("step_text", str), ("reason", str)],
}

SAMPLE_VALUES: dict[type, object] = {str: "value", int: 1}


class TestStepHooksContract:
    """Contract tests: facade import, the exact nine-method surface, no-op bodies."""

    def test_step_hooks_importable_from_facade(self) -> None:
        assert isinstance(StepHooks, type)

    def test_step_hooks_constructs_without_arguments(self) -> None:
        assert StepHooks() is not None

    def test_all_nine_methods_declared_with_exact_signatures(self) -> None:
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


class RecordingHooks(StepHooks):
    """Overrides the verdict event and records every argument it receives."""

    def __init__(self) -> None:
        self.verdict_calls: list[tuple[str, str, str, str]] = []

    def on_step_verdict(self, step_text: str, category: str, explanation: str, recommendation: str) -> None:
        self.verdict_calls.append((step_text, category, explanation, recommendation))


class TestStepVerdictLogic:
    """Logic tests: the verdict event no-op base and the four-field payload delivery."""

    def test_verdict_base_is_no_op(self) -> None:
        assert StepHooks().on_step_verdict("s", "incurable", "e", "rec") is None

    def test_recording_subclass_receives_four_string_fields(self) -> None:
        hooks = RecordingHooks()
        hooks.on_step_verdict("click Sign in", "product_defect", "the total shows 90", "file a bug")
        assert hooks.verdict_calls == [("click Sign in", "product_defect", "the total shows 90", "file a bug")]
        assert all(isinstance(value, str) for value in hooks.verdict_calls[0])
