"""Tests for the run_step_code execution routine of the prettyplay.engine cell."""

import inspect
import sys

import pytest
from prettyplay.driver import PageFacade
from prettyplay.engine import run_step_code


class FakePage:
    """Fake page facade boundary: records every facade call of the step code."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def open(self, url: str) -> None:
        self.calls.append(("open", url))

    def find_by_role(self, role: str, name: str) -> "FakeLocator":
        self.calls.append(("find_by_role", role, name))
        return FakeLocator(self.calls)

    def find_by_label(self, label: str) -> "FakeLocator":
        self.calls.append(("find_by_label", label))
        return FakeLocator(self.calls)

    def find_by_text(self, text: str) -> "FakeLocator":
        self.calls.append(("find_by_text", text))
        return FakeLocator(self.calls)

    def aria_snapshot(self) -> str:
        self.calls.append(("aria_snapshot",))
        return "- snapshot"

    def screenshot(self) -> bytes:
        self.calls.append(("screenshot",))
        return b"png"


class FakeLocator:
    """Fake located element: records the element API calls of the step code."""

    def __init__(self, calls: list[tuple[str, ...]]) -> None:
        self._calls = calls

    def click(self) -> None:
        self._calls.append(("click",))

    def fill(self, value: str) -> None:
        self._calls.append(("fill", value))

    def select_option(self, value: str) -> None:
        self._calls.append(("select_option", value))

    def expect_visible(self) -> None:
        self._calls.append(("expect_visible",))

    def expect_text(self, text: str) -> None:
        self._calls.append(("expect_text", text))

    def expect_enabled(self) -> None:
        self._calls.append(("expect_enabled",))


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
    """Logic tests: fixed-form execution, exception propagation, isolation."""

    def test_run_step_code_executes_fixed_form(self) -> None:
        page = FakePage()

        run_step_code("def step(page) -> None:\n    page.open('https://example.com')\n", page)

        assert page.calls == [("open", "https://example.com")]

    def test_step_code_works_through_locator_api(self) -> None:
        page = FakePage()
        code = (
            "def step(page) -> None:\n"
            "    page.find_by_role('button', name='Войти').click()\n"
            "    page.find_by_label('Логин').fill('user')\n"
        )

        run_step_code(code, page)

        assert page.calls == [
            ("find_by_role", "button", "Войти"),
            ("click",),
            ("find_by_label", "Логин"),
            ("fill", "user"),
        ]

    def test_assertion_failure_propagates_as_is(self) -> None:
        page = FakePage()
        code = "def step(page) -> None:\n    raise AssertionError('x')\n"

        with pytest.raises(AssertionError, match="x"):
            run_step_code(code, page)

    def test_arbitrary_exception_propagates_unswallowed(self) -> None:
        page = FakePage()
        code = "def step(page) -> None:\n    page.open('https://example.com')\n    raise ValueError('boom')\n"

        with pytest.raises(ValueError, match="boom"):
            run_step_code(code, page)

        assert page.calls == [("open", "https://example.com")]

    def test_syntax_error_propagates_outward(self) -> None:
        with pytest.raises(SyntaxError):
            run_step_code("def step(page) -> None:\n    page.open(\n", FakePage())

    def test_code_without_step_function_raises_outward(self) -> None:
        with pytest.raises(KeyError):
            run_step_code("def other(page) -> None:\n    page.open('https://example.com')\n", FakePage())

    def test_namespace_is_isolated_between_calls(self) -> None:
        first = FakePage()
        second = FakePage()

        run_step_code("MARKER = 'first'\n\ndef step(page) -> None:\n    page.open(MARKER)\n", first)

        assert first.calls == [("open", "first")]

        with pytest.raises(NameError):  # the first code's MARKER did not leak into the second namespace
            run_step_code("def step(page) -> None:\n    page.open(MARKER)\n", second)

    def test_step_module_not_registered_in_sys_modules(self) -> None:
        run_step_code("def step(page) -> None:\n    page.open('https://example.com')\n", FakePage())

        assert "<prettyplay-step>" not in sys.modules
        assert [name for name in sys.modules if "prettyplay-step" in name] == []
