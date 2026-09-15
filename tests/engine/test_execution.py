"""Tests for the run_step_code execution routine of the prettyplay.engine cell."""

import inspect
import logging
import sys
from collections.abc import Callable

import pytest
from playwright.sync_api import Error
from prettyplay.driver import PageFacade
from prettyplay.driver.page import _DialogRouter
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


class FakeStockWaiter:
    """Fake stock event waiter of ``expect_event``/``expect_popup``: fed by the page event.

    The page hands the fired event's payload to the armed waiter inside the
    ``with`` block; ``value`` stays readable after the block, as with the
    stock waiter.
    """

    def __init__(self) -> None:
        self._payload: object = None
        self._delivered = False

    def deliver(self, payload: object) -> None:
        """Hand the fired event's payload to the armed waiter."""
        self._payload = payload
        self._delivered = True

    def __enter__(self) -> "FakeStockWaiter":
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        return None  # the payload stays readable after the block

    @property
    def value(self) -> object:
        """The event payload; reading before the event fired fails loudly."""
        assert self._delivered, "value read before the event fired"
        return self._payload


class FakeStepDialog:
    """Fake Playwright dialog of a step capture; mirrors the driver's handled-state guard."""

    def __init__(self, message: str) -> None:
        self.message = message
        self.state = "open"
        self.accept_calls = 0

    def accept(self, prompt_text: str | None = None) -> None:
        if self.state != "open":
            raise Error("Cannot accept dialog which is already handled!")
        self.state = "accepted"
        self.accept_calls += 1


class FakeCloseContext:
    """Fake isolated browser context behind a capture page."""

    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeDialogCapturePage:
    """Fake genuine page of the taught dialog capture: the Delete click fires the dialog.

    The fired dialog dispatches to the registered routing handler (the router
    records it) and to the armed stock capture alike — exactly the interplay of
    the runtime wiring with the prompt-taught idiom.
    """

    def __init__(self, router: _DialogRouter) -> None:
        self._router = router
        self.dialog = FakeStepDialog("Delete?")
        self._armed: FakeStockWaiter | None = None
        self.calls: list[tuple[str, ...]] = []
        self.context = FakeCloseContext()

    def expect_event(self, event: str) -> FakeStockWaiter:
        self.calls.append(("expect_event", event))
        self._armed = FakeStockWaiter()
        return self._armed

    def get_by_role(self, role: str, name: str | None = None) -> "FakeDialogButton":
        self.calls.append(("get_by_role", role, name))
        return FakeDialogButton(self)

    def fire_dialog(self) -> None:
        """Dispatch the dialog event to the routing handler and the armed capture."""
        self._router.record(self.dialog)
        if self._armed is not None:
            self._armed.deliver(self.dialog)


class FakeDialogButton:
    """Fake located button: the click fires the page's dialog event."""

    def __init__(self, page: FakeDialogCapturePage) -> None:
        self._page = page

    def click(self) -> None:
        self._page.calls.append(("click",))
        self._page.fire_dialog()


class FakePopupPage:
    """Fake popup page: ``bring_to_front`` records; the popup fires one unclaimed dialog."""

    def __init__(self, router: _DialogRouter) -> None:
        self._router = router
        self.dialog = FakeStepDialog("Leave the site?")
        self.front_calls = 0

    def bring_to_front(self) -> None:
        self.front_calls += 1
        self._router.record(self.dialog)  # the popup's own dialog — no capture armed for it


class FakePopupCapturePage:
    """Fake genuine page of the taught popup capture: the docs link opens the popup."""

    def __init__(self, popup: FakePopupPage) -> None:
        self._popup = popup
        self._armed: FakeStockWaiter | None = None
        self.calls: list[tuple[str, ...]] = []
        self.context = FakeCloseContext()

    def expect_popup(self) -> FakeStockWaiter:
        self.calls.append(("expect_popup",))
        self._armed = FakeStockWaiter()
        return self._armed

    def get_by_role(self, role: str, name: str | None = None) -> "FakePopupLink":
        self.calls.append(("get_by_role", role, name))
        return FakePopupLink(self)

    def open_popup(self) -> None:
        """Dispatch the popup event to the armed capture."""
        assert self._armed is not None, "the popup fired with no capture armed"
        self._armed.deliver(self._popup)


class FakePopupLink:
    """Fake located link: the click opens the page's popup."""

    def __init__(self, page: FakePopupCapturePage) -> None:
        self._page = page

    def click(self) -> None:
        self._page.calls.append(("click",))
        self._page.open_popup()


def capture_handle(page: object) -> PageFacade:
    """Build a hand-built PageFacade over a capture page; the context is the page's own."""
    return PageFacade(page, page.context)  # type: ignore[attr-defined]


class TestRunStepCodeStockCaptures:
    """Logic tests: the CHEAT_SHEET-taught dialog/popup capture forms run as step code."""

    def test_taught_dialog_capture_resolves_once_through_the_router_interplay(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        router = _DialogRouter(accept_dialogs=True)
        page = FakeDialogCapturePage(router)
        handle = capture_handle(page)
        handle._router = router  # the session wiring: the routing handler records into the shared router
        code = (
            "def step(page) -> None:\n"
            "    with page.expect_event('dialog') as info:\n"
            "        page.get_by_role('button', name='Delete').click()\n"
            "    dialog = info.value\n"
            "    assert dialog.message == 'Delete?'\n"
            "    dialog.accept()\n"
        )

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            run_step_code(code, handle)

        assert page.calls == [
            ("expect_event", "dialog"),
            ("get_by_role", "button", "Delete"),
            ("click",),
        ]
        assert page.dialog.accept_calls == 1  # resolved exactly once — by the capture, never the router
        assert page.dialog.state == "accepted"
        assert router._pending == []  # the recorded entry drained through the already-handled skip
        assert [record for record in caplog.records if record.levelno >= logging.WARNING] == []  # the skip is silent

    def test_taught_popup_capture_opens_the_popup_and_the_router_takes_its_dialog(self) -> None:
        router = _DialogRouter(accept_dialogs=True)
        popup = FakePopupPage(router)
        page = FakePopupCapturePage(popup)
        handle = capture_handle(page)
        handle._router = router
        code = (
            "def step(page) -> None:\n"
            "    with page.expect_popup() as popup_info:\n"
            "        page.get_by_role('link', name='Open docs').click()\n"
            "    popup = popup_info.value\n"
            "    popup.bring_to_front()\n"
        )

        run_step_code(code, handle)

        assert page.calls == [
            ("expect_popup",),
            ("get_by_role", "link", "Open docs"),
            ("click",),
        ]
        assert popup.front_calls == 1  # the taught flow reached the popup page itself
        assert popup.dialog.state == "accepted"  # the popup's unclaimed dialog — the unit-tail resolver took it
        assert popup.dialog.accept_calls == 1
        assert router._pending == []
