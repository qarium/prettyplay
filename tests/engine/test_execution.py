"""Tests for the run_step_code execution routine of the prettyplay.engine cell."""

import inspect
import sys
from collections.abc import Callable

import pytest
from prettyplay.driver import PageFacade
from prettyplay.engine import run_step_code

#: the generated import header — executes on the calling thread, inert without a Playwright session
GENERATED_HEADER_CODE = "from playwright.sync_api import expect\n\n\ndef step(page):\n    assert page is not None\n"


class RawPage:
    """The genuine-page stand-in handed to the step function inside the run primitive."""

    def __init__(self) -> None:
        self.seen_failures: list[BaseException] = []

    def remember(self, failure: BaseException) -> None:
        self.seen_failures.append(failure)


class RecordingHandle:
    """Minimal PageFacade-shaped fake: ``run`` records the action and executes it against the raw page."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Callable[[RawPage], object]]] = []
        self.raw = RawPage()

    def run(self, action: Callable[[RawPage], object]) -> object:
        self.calls.append(("run", action))

        return action(self.raw)


class TestRunStepCodeContract:
    """Contract tests: facade import, exact signature of the routine."""

    def test_run_step_code_importable_from_facade(self) -> None:
        assert callable(run_step_code)

    def test_signature_matches_contract(self) -> None:
        signature = inspect.signature(run_step_code)
        parameters = list(signature.parameters.values())

        assert [parameter.name for parameter in parameters] == ["code", "page"]
        assert parameters[0].annotation in (str, "str")
        assert parameters[1].annotation in (PageFacade, PageFacade.__name__)
        assert signature.return_annotation in (None, "None")


class TestRunStepCodeLogic:
    """Logic tests: the run primitive as the single boundary, exception identity, isolation."""

    def test_run_step_code_runs_the_whole_step_through_the_run_primitive(self) -> None:
        handle = RecordingHandle()

        assert run_step_code(GENERATED_HEADER_CODE, handle) is None  # the outcome of the unit is not the routine's

        assert len(handle.calls) == 1  # one run unit — the whole step-function call
        kind, action = handle.calls[0]
        assert kind == "run"
        assert callable(action)
        assert action.__name__ == "step"  # the resolved namespace["step"] itself — no wrapper built here

    def test_run_step_code_propagates_step_failures_untouched(self) -> None:
        handle = RecordingHandle()
        code = (
            "def step(page):\n"
            "    try:\n"
            "        raise AssertionError('boom')\n"
            "    except AssertionError as failure:\n"
            "        page.remember(failure)\n"
            "        raise\n"
        )

        with pytest.raises(AssertionError, match="boom") as caught:
            run_step_code(code, handle)

        assert len(handle.raw.seen_failures) == 1
        assert caught.value is handle.raw.seen_failures[0]  # identity preserved — the very object raised inside

    def test_syntax_error_propagates_outward(self) -> None:
        handle = RecordingHandle()

        with pytest.raises(SyntaxError):
            run_step_code("def step(page):\n    page.goto(\n", handle)

        assert handle.calls == []  # the compile failure happens on the calling thread — no run unit at all

    def test_code_without_step_function_raises_outward(self) -> None:
        handle = RecordingHandle()

        with pytest.raises(KeyError):
            run_step_code("def other(page):\n    pass\n", handle)

        assert handle.calls == []  # the resolution failure happens on the calling thread — no run unit at all

    def test_namespace_is_isolated_between_calls(self) -> None:
        first = RecordingHandle()
        second = RecordingHandle()

        run_step_code("MARKER = 'first'\n\ndef step(page):\n    assert MARKER == 'first'\n", first)

        with pytest.raises(NameError):  # the first code's MARKER did not leak into the second namespace
            run_step_code("def step(page):\n    assert MARKER == 'first'\n", second)

    def test_step_module_not_registered_in_sys_modules(self) -> None:
        run_step_code("def step(page):\n    assert page is not None\n", RecordingHandle())

        assert "<prettyplay-step>" not in sys.modules
        assert [name for name in sys.modules if "prettyplay-step" in name] == []
