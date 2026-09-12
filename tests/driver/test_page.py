"""Tests for the PageFacade and LocatorFacade page API of the prettyplay.driver cell."""

import inspect
import re
import threading
from collections.abc import Callable
from typing import Any, get_type_hints
from unittest import mock

import prettyplay.driver
import pytest
from playwright.sync_api import Error
from prettyplay.driver import DialogFacade, FrameFacade, LocatorFacade, PageFacade
from prettyplay.driver.page import _DialogRouter


class RecordingAssertions:
    """Collects both the locators ``expect`` received and the assertions applied."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []


class FakeExpectation:
    """Fake ``expect(...)`` result: records the received locator and the assertion."""

    def __init__(self, locator: "FakeLocator", assertions: list[tuple[Any, ...]]) -> None:
        self._locator = locator
        self._assertions = assertions
        assertions.append(("received", locator))

    def to_be_visible(self) -> None:
        self._assertions.append("to_be_visible")

    def to_contain_text(self, text: str) -> None:
        self._assertions.append(("to_contain_text", text))

    def to_be_enabled(self) -> None:
        self._assertions.append("to_be_enabled")

    def to_be_hidden(self) -> None:
        self._assertions.append("to_be_hidden")

    def to_have_value(self, value: str) -> None:
        self._assertions.append(("to_have_value", value))

    def to_be_checked(self) -> None:
        self._assertions.append("to_be_checked")

    def to_have_count(self, count: int) -> None:
        self._assertions.append(("to_have_count", count))

    def to_have_attribute(self, name: str, value: str) -> None:
        self._assertions.append(("to_have_attribute", name, value))


class FakePageExpectation:
    """Fake ``expect(page)`` result: records the received page and the assertion."""

    def __init__(self, receiver: Any, assertions: list[tuple[Any, ...]]) -> None:
        self._assertions = assertions
        assertions.append(("received", receiver))

    def to_have_url(self, url: str) -> None:
        self._assertions.append(("to_have_url", url))

    def to_have_title(self, title: Any) -> None:
        self._assertions.append(("to_have_title", title))


class FakeMouse:
    """Fake Playwright ``page.mouse``; records wheel calls."""

    def __init__(self) -> None:
        self.wheel_calls: list[tuple[int, int]] = []

    def wheel(self, delta_x: int, delta_y: int) -> None:
        self.wheel_calls.append((delta_x, delta_y))


class FakeElementHandle:
    """Fake ``element_handle()`` result: a serializable live handle."""

    def __init__(self, locator: "FakeLocator") -> None:
        self._locator = locator

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FakeElementHandle) and other._locator is self._locator

    def __hash__(self) -> int:
        return id(self._locator)


class FakeLocator:
    """Fake Playwright locator hidden behind the facade; records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.assertions: list[str] = []
        self.evaluate_calls: list[tuple[str, Any]] = []
        self.evaluate_args: list[Any] = []
        self.scroll_into_view_called = False
        self.element_handle_returns_self_locator = True
        self.fail_on_click = False

    def click(self, button: str = "left") -> None:
        self.calls.append(("click", button))
        if self.fail_on_click:
            raise AssertionError("element not stable")

    def dblclick(self) -> None:
        self.calls.append(("dblclick",))

    def fill(self, value: str) -> None:
        self.calls.append(("fill", value))

    def clear(self) -> None:
        self.calls.append(("clear",))

    def press(self, key: str) -> None:
        self.calls.append(("press", key))

    def check(self) -> None:
        self.calls.append(("check",))

    def uncheck(self) -> None:
        self.calls.append(("uncheck",))

    def hover(self) -> None:
        self.calls.append(("hover",))

    def select_option(self, value: str) -> None:
        self.calls.append(("select_option", value))

    def drag_to(self, target: "FakeLocator") -> None:
        self.calls.append(("drag_to", target))

    def set_input_files(self, path: str) -> None:
        self.calls.append(("set_input_files", path))

    def scroll_into_view_if_needed(self) -> None:
        self.calls.append(("scroll_into_view_if_needed",))
        self.scroll_into_view_called = True

    def element_handle(self) -> FakeElementHandle:
        self.calls.append(("element_handle",))
        return FakeElementHandle(self)

    def evaluate(self, script: str, arg: Any = None) -> None:
        self.calls.append(("evaluate", script, arg))
        self.evaluate_calls.append((script, arg))
        self.evaluate_args.append(arg)


class FakeDialog:
    """Fake Playwright dialog hidden behind the facade; records accept kwargs and dismiss."""

    def __init__(self, type: str = "alert", message: str = "", default_value: str = "") -> None:
        self.type = type
        self.message = message
        self.default_value = default_value
        self.calls: list[tuple[Any, ...]] = []

    def accept(self, **kwargs: Any) -> None:
        self.calls.append(("accept", kwargs))

    def dismiss(self) -> None:
        self.calls.append(("dismiss",))


class FakeEventContextManager:
    """Fake Playwright event context manager; arms on enter, resolves or times out on exit."""

    def __init__(self, event: str, value: Any = None, timeout: bool = False) -> None:
        self.event = event
        self.calls: list[str] = []
        self.value: Any = None  # the EventInfo.value mirror — filled at a successful exit
        self._value = value
        self._timeout = timeout

    def __enter__(self) -> "FakeEventContextManager":
        self.calls.append("__enter__")
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.calls.append("__exit__")
        if exc_val is not None:
            return  # a raising block cancels the waiter — no wait, no timeout
        if self._timeout:
            raise Error(f'Timeout 30000ms exceeded while waiting for event "{self.event}"')
        self.value = self._value


class FakeFrameLocator:
    """Fake Playwright frame locator hidden behind the facade; records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.locators: list[FakeLocator] = []
        self.frames: list[FakeFrameLocator] = []
        self._locator_factory = FakeLocator
        self._frame_factory = FakeFrameLocator

    def get_by_role(self, role: str, name: str | None = None) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("get_by_role", role, name))
        self.locators.append(locator)
        return locator

    def get_by_label(self, label: str) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("get_by_label", label))
        self.locators.append(locator)
        return locator

    def get_by_text(self, text: str) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("get_by_text", text))
        self.locators.append(locator)
        return locator

    def get_by_placeholder(self, placeholder: str) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("get_by_placeholder", placeholder))
        self.locators.append(locator)
        return locator

    def get_by_alt_text(self, alt: str) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("get_by_alt_text", alt))
        self.locators.append(locator)
        return locator

    def get_by_title(self, title: str) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("get_by_title", title))
        self.locators.append(locator)
        return locator

    def get_by_test_id(self, test_id: str) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("get_by_test_id", test_id))
        self.locators.append(locator)
        return locator

    def locator(self, selector: str) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("locator", selector))
        self.locators.append(locator)
        return locator

    def frame_locator(self, selector: str) -> "FakeFrameLocator":
        frame = self._frame_factory()
        self.calls.append(("frame_locator", selector))
        self.frames.append(frame)
        return frame


class FakeContext:
    """Fake isolated browser context; lists pages, records ``close`` and ``on``."""

    def __init__(self, pages: list["FakePage"] | None = None) -> None:
        self.close_calls = 0
        self.pages: list[FakePage] = pages if pages is not None else []
        self.on_calls: list[tuple[str, Any]] = []

    def close(self) -> None:
        self.close_calls += 1

    def on(self, event: str, handler: Any) -> None:
        self.on_calls.append((event, handler))


class DetachedLocator(FakeLocator):
    """Fake locator whose target detached: ``element_handle()`` resolves to ``None``."""

    def element_handle(self) -> None:
        self.calls.append(("element_handle",))


class FakeBodyLocator(FakeLocator):
    """Fake ``page.locator("body")``: yields the recorded aria snapshot."""

    def __init__(self, snapshot: str = "- heading Адреса") -> None:
        super().__init__()
        self._snapshot = snapshot

    def aria_snapshot(self) -> str:
        self.calls.append(("aria_snapshot",))
        return self._snapshot


class FakePage:
    """Fake Playwright page object hidden behind the facade; records every call."""

    def __init__(self, url: str = "about:blank", snapshot: str = "- heading Адреса") -> None:
        self.url = url
        self.calls: list[tuple[Any, ...]] = []
        self.evaluate_calls: list[tuple[str, Any]] = []
        self.locators: list[FakeLocator] = []
        self.mouse = FakeMouse()
        self._context = FakeContext()
        self._body = FakeBodyLocator(snapshot)
        self._locator_factory = FakeLocator
        self.dialog_value: FakeDialog | None = None
        self.dialog_timeout = False
        self.popup_value: FakePopupPage | None = None
        self.popup_timeout = False

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))
        self.url = url

    def go_back(self) -> None:
        self.calls.append(("go_back",))

    def go_forward(self) -> None:
        self.calls.append(("go_forward",))

    def reload(self) -> None:
        self.calls.append(("reload",))

    def wait_for_url(self, url: str) -> None:
        self.calls.append(("wait_for_url", url))

    def wait_for_load_state(self, state: str) -> None:
        self.calls.append(("wait_for_load_state", state))

    def bring_to_front(self) -> None:
        self.calls.append(("bring_to_front",))

    def evaluate(self, script: str, arg: Any = None) -> None:
        self.calls.append(("evaluate", script, arg))
        self.evaluate_calls.append((script, arg))

    def get_by_role(self, role: str, name: str | None = None) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("get_by_role", role, name))
        self.locators.append(locator)
        return locator

    def get_by_label(self, label: str) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("get_by_label", label))
        self.locators.append(locator)
        return locator

    def get_by_text(self, text: str) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("get_by_text", text))
        self.locators.append(locator)
        return locator

    def get_by_placeholder(self, placeholder: str) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("get_by_placeholder", placeholder))
        self.locators.append(locator)
        return locator

    def get_by_alt_text(self, alt: str) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("get_by_alt_text", alt))
        self.locators.append(locator)
        return locator

    def get_by_title(self, title: str) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("get_by_title", title))
        self.locators.append(locator)
        return locator

    def get_by_test_id(self, test_id: str) -> FakeLocator:
        locator = self._locator_factory()
        self.calls.append(("get_by_test_id", test_id))
        self.locators.append(locator)
        return locator

    def locator(self, selector: str) -> FakeLocator:
        self.calls.append(("locator", selector))
        if selector == "body":  # the aria-snapshot path of the existing tests
            return self._body
        locator = self._locator_factory()
        self.locators.append(locator)
        return locator

    def frame_locator(self, selector: str) -> FakeFrameLocator:
        self.calls.append(("frame_locator", selector))
        return FakeFrameLocator()

    def screenshot(self, full_page: bool = False) -> bytes:
        self.calls.append(("screenshot", full_page))
        return b"png-bytes"

    def expect_event(self, event: str) -> FakeEventContextManager:
        self.calls.append(("expect_event", event))
        return FakeEventContextManager(event, value=self.dialog_value, timeout=self.dialog_timeout)

    def expect_popup(self) -> FakeEventContextManager:
        self.calls.append(("expect_popup",))
        return FakeEventContextManager("popup", value=self.popup_value, timeout=self.popup_timeout)

    @property
    def context(self) -> FakeContext:
        return self._context


class FakePopupPage(FakePage):
    """Fake page opened as a popup of another page; carries its own context reference."""


class RecordingWorker:
    """Fake ``PlaywrightWorker``: records every marshaled callable, executes inline."""

    def __init__(self) -> None:
        self.calls: list[Callable[[], Any]] = []

    def run(self, fn: Callable[[], Any]) -> Any:
        self.calls.append(fn)
        return fn()


class ThreadedWorker:
    """Fake ``PlaywrightWorker``: runs every callable on a fresh thread; records the idents."""

    def __init__(self) -> None:
        self.idents: list[int] = []

    def run(self, fn: Callable[[], Any]) -> Any:
        outcome: dict[str, Any] = {}

        def target() -> None:
            outcome["ident"] = threading.get_ident()
            try:
                outcome["value"] = fn()
            except BaseException as error:  # exception propagates to the calling thread
                outcome["error"] = error

        thread = threading.Thread(target=target)
        thread.start()
        thread.join()
        self.idents.append(outcome["ident"])
        if "error" in outcome:
            raise outcome["error"]
        return outcome["value"]


def make_page_facade(page: FakePage | None = None, context: FakeContext | None = None) -> PageFacade:
    """Build a PageFacade over fakes; the context defaults to the fake page's own."""
    page = page or FakePage()
    return PageFacade(page, context or page.context)


def make_locator_facade(locator: FakeLocator | None = None) -> LocatorFacade:
    """Build a LocatorFacade over a fake locator."""
    return LocatorFacade(locator or FakeLocator())


def make_dialog_facade(dialog: FakeDialog | None = None) -> DialogFacade:
    """Build a DialogFacade over a fake dialog."""
    return DialogFacade(dialog or FakeDialog())


def make_frame_facade(frame_locator: FakeFrameLocator | None = None) -> FrameFacade:
    """Build a FrameFacade over a fake frame locator."""
    return FrameFacade(frame_locator or FakeFrameLocator())


class TestPageFacadeContract:
    """Contract tests: facade import, method set, signatures, return types."""

    def test_page_facade_importable_from_facade(self) -> None:
        assert isinstance(PageFacade, type)

    def test_locator_facade_importable_from_facade(self) -> None:
        assert isinstance(LocatorFacade, type)

    def test_dialog_facade_importable_from_facade(self) -> None:
        assert isinstance(DialogFacade, type)

    def test_frame_facade_importable_from_facade(self) -> None:
        assert isinstance(FrameFacade, type)

    def test_driver_all_exports_match_contract(self) -> None:
        assert set(prettyplay.driver.__all__) == {
            "DriverSession",
            "DialogFacade",
            "FrameFacade",
            "LocatorFacade",
            "PageFacade",
        }

    def test_dialog_facade_surface_matches_contract(self) -> None:
        surface = ["type", "message", "default_value", "accept", "dismiss"]

        for name in surface:
            assert hasattr(DialogFacade, name), name

    def test_dialog_facade_signatures_match_contract(self) -> None:
        assert list(inspect.signature(DialogFacade.accept).parameters) == ["self", "prompt_text"]
        assert inspect.signature(DialogFacade.accept).parameters["prompt_text"].default == ""
        assert list(inspect.signature(DialogFacade.dismiss).parameters) == ["self"]

    def test_dialog_facade_annotations_match_contract(self) -> None:
        accept_hints = get_type_hints(DialogFacade.accept)
        assert accept_hints["prompt_text"] is str
        assert accept_hints["return"] is type(None)

        dismiss_hints = get_type_hints(DialogFacade.dismiss)
        assert dismiss_hints["return"] is type(None)

        assert get_type_hints(DialogFacade.type.fget)["return"] is str
        assert get_type_hints(DialogFacade.message.fget)["return"] is str
        assert get_type_hints(DialogFacade.default_value.fget)["return"] is str

    def test_frame_facade_surface_matches_contract(self) -> None:
        surface = [
            "get_by_role",
            "get_by_label",
            "get_by_text",
            "get_by_placeholder",
            "get_by_alt_text",
            "get_by_title",
            "get_by_test_id",
            "locator",
            "frame_locator",
        ]

        for name in surface:
            assert hasattr(FrameFacade, name), name

    def test_frame_facade_signatures_match_contract(self) -> None:
        assert list(inspect.signature(FrameFacade.get_by_role).parameters) == ["self", "role", "name"]
        assert inspect.signature(FrameFacade.get_by_role).parameters["name"].default == ""
        assert list(inspect.signature(FrameFacade.get_by_label).parameters) == ["self", "label"]
        assert list(inspect.signature(FrameFacade.get_by_text).parameters) == ["self", "text"]
        assert list(inspect.signature(FrameFacade.get_by_placeholder).parameters) == ["self", "placeholder"]
        assert list(inspect.signature(FrameFacade.get_by_alt_text).parameters) == ["self", "alt"]
        assert list(inspect.signature(FrameFacade.get_by_title).parameters) == ["self", "title"]
        assert list(inspect.signature(FrameFacade.get_by_test_id).parameters) == ["self", "test_id"]
        assert list(inspect.signature(FrameFacade.locator).parameters) == ["self", "selector"]
        assert list(inspect.signature(FrameFacade.frame_locator).parameters) == ["self", "selector"]

    def test_frame_facade_annotations_match_contract(self) -> None:
        role_hints = get_type_hints(FrameFacade.get_by_role)
        assert role_hints["role"] is str
        assert role_hints["name"] is str
        assert role_hints["return"] is LocatorFacade

        for member, parameter in (
            ("get_by_label", "label"),
            ("get_by_text", "text"),
            ("get_by_placeholder", "placeholder"),
            ("get_by_alt_text", "alt"),
            ("get_by_title", "title"),
            ("get_by_test_id", "test_id"),
            ("locator", "selector"),
        ):
            hints = get_type_hints(getattr(FrameFacade, member))
            assert hints[parameter] is str, member
            assert hints["return"] is LocatorFacade, member

        nested_hints = get_type_hints(FrameFacade.frame_locator)
        assert nested_hints["selector"] is str
        assert nested_hints["return"] is FrameFacade

    def test_retired_surface_is_gone(self) -> None:
        retired = (
            "open",
            "find_by_role",
            "find_by_label",
            "find_by_text",
            "find_by_attribute",
            "find_by_css",
            "find_by_xpath",
        )

        for name in retired:
            assert not hasattr(PageFacade, name), name  # deleted outright — no deprecation aliases

    def test_page_surface_matches_the_contract(self) -> None:
        expected = {
            "url",
            "pages",
            "goto",
            "go_back",
            "go_forward",
            "reload",
            "wait_for_url",
            "wait_for_load_state",
            "expect_url",
            "expect_title",
            "get_by_role",
            "get_by_label",
            "get_by_text",
            "get_by_placeholder",
            "get_by_alt_text",
            "get_by_title",
            "get_by_test_id",
            "locator",
            "expect_dialog",
            "expect_popup",
            "bring_to_front",
            "frame_locator",
            "aria_snapshot",
            "screenshot",
            "scroll_to_element",
            "scroll_down",
            "scroll_up",
            "scroll_to_bottom",
            "scroll_to_top",
            "scroll_into_view",
            "scroll_container_down",
            "scroll_container_up",
            "close",
        }
        public = {name for name in dir(PageFacade) if not name.startswith("_")}

        assert expected == public  # nothing extra, nothing missing

    def test_locator_facade_surface_matches_contract(self) -> None:
        surface = ["click", "fill", "select_option", "expect_visible", "expect_text", "expect_enabled"]

        for name in surface:
            assert hasattr(LocatorFacade, name), name

    def test_page_facade_signatures_match_contract(self) -> None:
        assert list(inspect.signature(PageFacade.goto).parameters) == ["self", "url"]
        assert list(inspect.signature(PageFacade.go_back).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.go_forward).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.reload).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.wait_for_url).parameters) == ["self", "url"]
        assert list(inspect.signature(PageFacade.wait_for_load_state).parameters) == ["self", "state"]
        assert list(inspect.signature(PageFacade.expect_url).parameters) == ["self", "url"]
        assert list(inspect.signature(PageFacade.expect_title).parameters) == ["self", "title"]
        assert list(inspect.signature(PageFacade.get_by_role).parameters) == ["self", "role", "name"]
        assert inspect.signature(PageFacade.get_by_role).parameters["name"].default == ""
        assert list(inspect.signature(PageFacade.get_by_label).parameters) == ["self", "label"]
        assert list(inspect.signature(PageFacade.get_by_text).parameters) == ["self", "text"]
        assert list(inspect.signature(PageFacade.get_by_placeholder).parameters) == ["self", "placeholder"]
        assert list(inspect.signature(PageFacade.get_by_alt_text).parameters) == ["self", "alt"]
        assert list(inspect.signature(PageFacade.get_by_title).parameters) == ["self", "title"]
        assert list(inspect.signature(PageFacade.get_by_test_id).parameters) == ["self", "test_id"]
        assert list(inspect.signature(PageFacade.locator).parameters) == ["self", "selector"]
        assert list(inspect.signature(PageFacade.bring_to_front).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.frame_locator).parameters) == ["self", "selector"]
        assert list(inspect.signature(PageFacade.aria_snapshot).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.screenshot).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.close).parameters) == ["self"]

    def test_capture_members_signatures_match_contract(self) -> None:
        assert list(inspect.signature(PageFacade.expect_dialog).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.expect_popup).parameters) == ["self"]
        assert get_type_hints(PageFacade.expect_dialog)["return"] is DialogFacade
        assert get_type_hints(PageFacade.expect_popup)["return"] is PageFacade

    def test_scroll_method_signatures_match_contract(self) -> None:
        assert list(inspect.signature(PageFacade.scroll_to_element).parameters) == ["self", "element"]
        assert list(inspect.signature(PageFacade.scroll_down).parameters) == ["self", "pixels"]
        assert list(inspect.signature(PageFacade.scroll_up).parameters) == ["self", "pixels"]
        assert list(inspect.signature(PageFacade.scroll_to_bottom).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.scroll_to_top).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.scroll_into_view).parameters) == ["self", "element", "container"]
        assert list(inspect.signature(PageFacade.scroll_container_down).parameters) == ["self", "container", "pixels"]
        assert list(inspect.signature(PageFacade.scroll_container_up).parameters) == ["self", "container", "pixels"]

    def test_locator_facade_signatures_match_contract(self) -> None:
        assert list(inspect.signature(LocatorFacade.click).parameters) == ["self", "button"]
        assert inspect.signature(LocatorFacade.click).parameters["button"].default == ""
        assert list(inspect.signature(LocatorFacade.fill).parameters) == ["self", "value"]
        assert list(inspect.signature(LocatorFacade.select_option).parameters) == ["self", "value"]
        assert list(inspect.signature(LocatorFacade.expect_visible).parameters) == ["self"]
        assert list(inspect.signature(LocatorFacade.expect_text).parameters) == ["self", "text"]
        assert list(inspect.signature(LocatorFacade.expect_enabled).parameters) == ["self"]

    def test_locator_facade_interaction_surface_matches_contract(self) -> None:
        surface = [
            "dblclick",
            "clear",
            "press",
            "check",
            "uncheck",
            "hover",
            "drag_to",
            "set_input_files",
            "expect_hidden",
            "expect_value",
            "expect_checked",
            "expect_count",
            "expect_attribute",
        ]

        for name in surface:
            assert hasattr(LocatorFacade, name), name

    def test_locator_facade_interaction_signatures_match_contract(self) -> None:
        assert list(inspect.signature(LocatorFacade.dblclick).parameters) == ["self"]
        assert list(inspect.signature(LocatorFacade.clear).parameters) == ["self"]
        assert list(inspect.signature(LocatorFacade.press).parameters) == ["self", "key"]
        assert list(inspect.signature(LocatorFacade.check).parameters) == ["self"]
        assert list(inspect.signature(LocatorFacade.uncheck).parameters) == ["self"]
        assert list(inspect.signature(LocatorFacade.hover).parameters) == ["self"]
        assert list(inspect.signature(LocatorFacade.drag_to).parameters) == ["self", "target"]
        assert list(inspect.signature(LocatorFacade.set_input_files).parameters) == ["self", "path"]
        assert list(inspect.signature(LocatorFacade.expect_hidden).parameters) == ["self"]
        assert list(inspect.signature(LocatorFacade.expect_value).parameters) == ["self", "value"]
        assert list(inspect.signature(LocatorFacade.expect_checked).parameters) == ["self"]
        assert list(inspect.signature(LocatorFacade.expect_count).parameters) == ["self", "count"]
        assert list(inspect.signature(LocatorFacade.expect_attribute).parameters) == ["self", "name", "value"]

    def test_locator_facade_interaction_annotations_match_contract(self) -> None:
        click_hints = get_type_hints(LocatorFacade.click)
        assert click_hints["button"] is str
        assert click_hints["return"] is type(None)

        press_hints = get_type_hints(LocatorFacade.press)
        assert press_hints["key"] is str
        assert press_hints["return"] is type(None)

        drag_hints = get_type_hints(LocatorFacade.drag_to)
        assert drag_hints["target"] is LocatorFacade
        assert drag_hints["return"] is type(None)

        files_hints = get_type_hints(LocatorFacade.set_input_files)
        assert files_hints["path"] is str
        assert files_hints["return"] is type(None)

        hidden_hints = get_type_hints(LocatorFacade.expect_hidden)
        assert hidden_hints["return"] is type(None)

        value_hints = get_type_hints(LocatorFacade.expect_value)
        assert value_hints["value"] is str
        assert value_hints["return"] is type(None)

        checked_hints = get_type_hints(LocatorFacade.expect_checked)
        assert checked_hints["return"] is type(None)

        count_hints = get_type_hints(LocatorFacade.expect_count)
        assert count_hints["count"] is int
        assert count_hints["return"] is type(None)

        attribute_hints = get_type_hints(LocatorFacade.expect_attribute)
        assert attribute_hints["name"] is str
        assert attribute_hints["value"] is str
        assert attribute_hints["return"] is type(None)

    def test_page_facade_annotations_match_contract(self) -> None:
        goto_hints = get_type_hints(PageFacade.goto)
        assert goto_hints["url"] is str
        assert goto_hints["return"] is type(None)

        wait_url_hints = get_type_hints(PageFacade.wait_for_url)
        assert wait_url_hints["url"] is str
        assert wait_url_hints["return"] is type(None)

        load_state_hints = get_type_hints(PageFacade.wait_for_load_state)
        assert load_state_hints["state"] is str
        assert load_state_hints["return"] is type(None)

        expect_url_hints = get_type_hints(PageFacade.expect_url)
        assert expect_url_hints["url"] is str
        assert expect_url_hints["return"] is type(None)

        expect_title_hints = get_type_hints(PageFacade.expect_title)
        assert expect_title_hints["title"] is str
        assert expect_title_hints["return"] is type(None)

        role_hints = get_type_hints(PageFacade.get_by_role)
        assert role_hints["role"] is str
        assert role_hints["name"] is str
        assert role_hints["return"] is LocatorFacade

        for member, parameter in (
            ("get_by_label", "label"),
            ("get_by_text", "text"),
            ("get_by_placeholder", "placeholder"),
            ("get_by_alt_text", "alt"),
            ("get_by_title", "title"),
            ("get_by_test_id", "test_id"),
            ("locator", "selector"),
        ):
            hints = get_type_hints(getattr(PageFacade, member))
            assert hints[parameter] is str, member
            assert hints["return"] is LocatorFacade, member

        frame_hints = get_type_hints(PageFacade.frame_locator)
        assert frame_hints["selector"] is str
        assert frame_hints["return"] is FrameFacade

        assert get_type_hints(PageFacade.url.fget)["return"] is str
        assert get_type_hints(PageFacade.pages.fget)["return"] == list[PageFacade]

    def test_scroll_method_annotations_match_contract(self) -> None:
        to_element = get_type_hints(PageFacade.scroll_to_element)
        assert to_element["element"] is LocatorFacade
        assert to_element["return"] is type(None)

        down = get_type_hints(PageFacade.scroll_down)
        assert down["pixels"] is int
        assert down["return"] is type(None)

        into_view = get_type_hints(PageFacade.scroll_into_view)
        assert into_view["element"] is LocatorFacade
        assert into_view["container"] is LocatorFacade
        assert into_view["return"] is type(None)

        container_down = get_type_hints(PageFacade.scroll_container_down)
        assert container_down["container"] is LocatorFacade
        assert container_down["pixels"] is int
        assert container_down["return"] is type(None)

    def test_no_raw_playwright_objects_escape(self) -> None:
        page = FakePage()
        facade = make_page_facade(page, FakeContext(pages=[page]))

        assert isinstance(facade.goto("https://example.com"), type(None))
        assert isinstance(facade.get_by_role("button", name="Войти"), LocatorFacade)
        assert isinstance(facade.get_by_label("Логин"), LocatorFacade)
        assert isinstance(facade.get_by_text("Добро пожаловать"), LocatorFacade)
        assert isinstance(facade.get_by_placeholder("Поиск"), LocatorFacade)
        assert isinstance(facade.get_by_alt_text("Логотип"), LocatorFacade)
        assert isinstance(facade.get_by_title("Закрыть"), LocatorFacade)
        assert isinstance(facade.get_by_test_id("submit"), LocatorFacade)
        assert isinstance(facade.locator("form > button.primary"), LocatorFacade)
        assert isinstance(facade.frame_locator("#frame"), FrameFacade)
        assert all(isinstance(wrapped, PageFacade) for wrapped in facade.pages)
        assert facade.bring_to_front() is None
        assert facade.go_back() is None
        assert isinstance(facade.aria_snapshot(), str)
        assert isinstance(facade.screenshot(), bytes)
        assert isinstance(facade.url, str)
        assert facade.close() is None


class TestPageFacadeLogic:
    """Logic tests: delegation of every PageFacade method to the wrapped page."""

    def test_navigation_members_delegate_to_playwright(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        facade.goto("https://example.com")
        facade.go_back()
        facade.go_forward()
        facade.reload()
        facade.wait_for_url("**/dashboard")
        facade.wait_for_load_state("networkidle")

        assert page.calls == [
            ("goto", "https://example.com"),
            ("go_back",),
            ("go_forward",),
            ("reload",),
            ("wait_for_url", "**/dashboard"),
            ("wait_for_load_state", "networkidle"),
        ]

    def test_get_by_family_delegates_and_wraps(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        by_role = facade.get_by_role("button", name="Sign in")
        by_label = facade.get_by_label("Username")
        by_text = facade.get_by_text("Welcome")
        by_placeholder = facade.get_by_placeholder("Search")
        by_alt_text = facade.get_by_alt_text("Logo")
        by_title = facade.get_by_title("Close")
        by_test_id = facade.get_by_test_id("submit")
        by_selector = facade.locator("form > button")

        assert page.calls == [
            ("get_by_role", "button", "Sign in"),
            ("get_by_label", "Username"),
            ("get_by_text", "Welcome"),
            ("get_by_placeholder", "Search"),
            ("get_by_alt_text", "Logo"),
            ("get_by_title", "Close"),
            ("get_by_test_id", "submit"),
            ("locator", "form > button"),
        ]

        elements = (by_role, by_label, by_text, by_placeholder, by_alt_text, by_title, by_test_id, by_selector)
        for element in elements:
            assert isinstance(element, LocatorFacade)

        for element, located in zip(elements, page.locators, strict=True):
            assert element._locator is located  # each wraps the fake locator it asked for

    def test_get_by_role_empty_name_matches_by_role_alone(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        facade.get_by_role("button")
        facade.get_by_role("button", name="")

        assert page.calls == [("get_by_role", "button", None), ("get_by_role", "button", None)]  # no name kwarg

    def test_expect_title_builds_a_contains_pattern(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)
        assertions: list[tuple[Any, ...]] = []

        recorder = lambda receiver: FakePageExpectation(receiver, assertions)  # noqa: E731
        with mock.patch("prettyplay.driver.page.expect", side_effect=recorder):
            facade.expect_title("Dashboard")

        assert assertions[0] == ("received", page)  # the receiver is the wrapped page
        kind, pattern = assertions[1]
        assert kind == "to_have_title"
        assert pattern.pattern == ".*Dashboard.*"  # the escaped input between .* bookends
        assert pattern.flags & re.DOTALL

    def test_expect_title_with_regex_metacharacters(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)
        assertions: list[tuple[Any, ...]] = []

        recorder = lambda receiver: FakePageExpectation(receiver, assertions)  # noqa: E731
        with mock.patch("prettyplay.driver.page.expect", side_effect=recorder):
            facade.expect_title("C++ (2026)")

        pattern = assertions[1][1]
        assert pattern.pattern == f".*{re.escape('C++ (2026)')}.*"  # metacharacters escaped
        assert pattern.search("Report C++ (2026) edition")  # the title is matched literally — contains semantics
        assert pattern.search("C+ 2026") is None  # must not turn into an accidental regex

    def test_expect_url_uses_glob_string(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)
        assertions: list[tuple[Any, ...]] = []

        recorder = lambda receiver: FakePageExpectation(receiver, assertions)  # noqa: E731
        with mock.patch("prettyplay.driver.page.expect", side_effect=recorder):
            facade.expect_url("**/dashboard")

        assert assertions == [("received", page), ("to_have_url", "**/dashboard")]  # the glob string verbatim

    def test_pages_property_wraps_context_pages(self) -> None:
        main = FakePage()
        popup = FakePage()
        context = FakeContext(pages=[main, popup])
        facade = make_page_facade(main, context)
        worker = RecordingWorker()
        facade._worker = worker

        result = facade.pages

        assert len(result) == 2
        assert all(isinstance(wrapped, PageFacade) for wrapped in result)
        assert all(wrapped._worker is worker for wrapped in result)  # the session worker, inherited
        assert [wrapped._page for wrapped in result] == [main, popup]

    def test_aria_snapshot_delegates_to_body_locator(self) -> None:
        page = FakePage(snapshot="- heading Профиль")
        facade = make_page_facade(page)

        snapshot = facade.aria_snapshot()

        assert page.calls == [("locator", "body")]
        assert page._body.calls == [("aria_snapshot",)]
        assert snapshot == "- heading Профиль"

    def test_screenshot_requests_full_page_and_returns_bytes(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        image = facade.screenshot()

        assert page.calls == [("screenshot", True)]
        assert image == b"png-bytes"

    def test_url_property_reads_the_page(self) -> None:
        page = FakePage(url="https://example.com/login")
        facade = make_page_facade(page)

        assert facade.url == "https://example.com/login"

    def test_close_closes_context_not_browser(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        facade.close()

        assert page.context.close_calls == 1

    def test_close_leaves_page_usable_for_other_tests(self) -> None:
        # close() closes only the context; the browser serves the next test's context
        page = FakePage()
        facade = make_page_facade(page)
        facade.close()

        next_page = FakePage()
        next_facade = make_page_facade(next_page)
        next_facade.goto("https://example.com/next")

        assert page.context.close_calls == 1
        assert page.calls == []  # no page calls — only context.close()
        assert next_page.calls == [("goto", "https://example.com/next")]  # the browser still works


class TestUniversalLocatorLogic:
    """Logic tests: the verbatim selector pass-through of the universal locating method."""

    def test_locator_passes_selectors_verbatim(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        selectors = (
            "form > button.primary",
            "//button[@type='submit']",
            "xpath=*[@id='main']",
            "[data-qa='row'] > input",
        )

        for selector in selectors:
            element = facade.locator(selector)
            assert isinstance(element, LocatorFacade)

        assert [call for call in page.calls if call[0] == "locator"] == [
            ("locator", "form > button.primary"),
            ("locator", "//button[@type='submit']"),
            ("locator", "xpath=*[@id='main']"),  # the explicit engine prefix stays a selector form
            ("locator", "[data-qa='row'] > input"),
        ]  # byte-identical — no facade-side sniffing or rewriting


class TestPageFacadeScrollLogic:
    """Logic tests: delegation of every scroll method to the Playwright primitives."""

    def test_scroll_primitives_delegate_to_playwright(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)
        element = facade.get_by_text("Fifth card")
        container = facade.get_by_role("list", name="Recommendations")
        fake_element = element._locator
        fake_container = container._locator

        facade.scroll_down(600)
        facade.scroll_up(300)
        facade.scroll_to_bottom()
        facade.scroll_to_top()
        facade.scroll_to_element(element)
        facade.scroll_into_view(element, container)
        facade.scroll_container_down(container, 400)
        facade.scroll_container_up(container, 200)

        assert page.mouse.wheel_calls == [(0, 600), (0, -300)]
        assert page.evaluate_calls[0][0].startswith("window.scrollTo(0, document.body.scrollHeight)")
        assert page.evaluate_calls[1][0].startswith("window.scrollTo(0, 0)")
        assert fake_element.scroll_into_view_called is True
        assert fake_element.calls == [("scroll_into_view_if_needed",), ("element_handle",)]
        assert fake_container.evaluate_calls[-3] == (
            "(el, target) => {\n"
            "    const cr = el.getBoundingClientRect();\n"
            "    const tr = target.getBoundingClientRect();\n"
            "    el.scrollTop += tr.top - cr.top - (el.clientHeight - tr.height) / 2;\n"
            "}",
            FakeElementHandle(fake_element),
        )
        assert fake_container.evaluate_args[-1] == 200
        assert "scrollTop -=" in fake_container.evaluate_calls[-1][0]
        assert fake_container.evaluate_args[-2] == 400
        assert "scrollTop +=" in fake_container.evaluate_calls[-2][0]
        assert "scrollTop +=" in fake_container.evaluate_calls[-3][0]
        assert "getBoundingClientRect" in fake_container.evaluate_calls[-3][0]

    def test_scroll_into_view_passes_live_handle_of_the_target(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)
        element = facade.get_by_text("Fifth card")
        container = facade.get_by_role("region", name="Carousel")
        fake_element = element._locator
        fake_container = container._locator

        facade.scroll_into_view(element, container)

        script, arg = fake_container.evaluate_calls[0]
        assert ("element_handle",) in fake_element.calls
        assert isinstance(arg, FakeElementHandle)
        assert arg._locator is fake_element  # the live handle of the target, not the locator
        assert "getBoundingClientRect" in script
        assert "el.scrollTop" in script

    def test_scroll_into_view_passes_none_handle_of_a_detached_target(self) -> None:
        page = FakePage()
        page._locator_factory = DetachedLocator  # the element handle resolves to None
        facade = make_page_facade(page)
        element = facade.get_by_text("Detached card")
        container = facade.get_by_role("region", name="Carousel")

        facade.scroll_into_view(element, container)

        # the resolved handle reaches the container evaluation as-is — the page fails the render
        assert container._locator.evaluate_args == [None]
        assert ("element_handle",) in element._locator.calls

    def test_scroll_to_element_uses_nearest_scrollable_ancestor_primitive(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)
        element = facade.get_by_text("Load more")

        facade.scroll_to_element(element)

        assert element._locator.calls == [("scroll_into_view_if_needed",)]
        assert page.calls == [("get_by_text", "Load more")]  # nothing else touched the page

    def test_scroll_methods_never_sleep(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)
        element = facade.get_by_text("Footer")
        container = facade.get_by_role("list", name="Results")

        with mock.patch("time.sleep") as sleep:
            facade.scroll_down(600)
            facade.scroll_up(300)
            facade.scroll_to_bottom()
            facade.scroll_to_top()
            facade.scroll_to_element(element)
            facade.scroll_into_view(element, container)
            facade.scroll_container_down(container, 400)
            facade.scroll_container_up(container, 200)

        assert sleep.call_count == 0  # the scrolled state is awaited by locators, never by a delay


class TestLocatorFacadeLogic:
    """Logic tests: delegation of every LocatorFacade method to the wrapped locator."""

    def test_click_fills_select_delegate(self) -> None:
        element = make_locator_facade(FakeLocator())

        element.click()
        element.fill("user")
        element.select_option("RU")

        assert element._locator.calls == [("click", "left"), ("fill", "user"), ("select_option", "RU")]

    @pytest.mark.parametrize(
        ("action", "expected"),
        [
            (lambda element: element.dblclick(), ("dblclick",)),
            (lambda element: element.clear(), ("clear",)),
            (lambda element: element.press("Control+A"), ("press", "Control+A")),
            (lambda element: element.check(), ("check",)),
            (lambda element: element.uncheck(), ("uncheck",)),
            (lambda element: element.hover(), ("hover",)),
            (lambda element: element.select_option("red"), ("select_option", "red")),
            (lambda element: element.set_input_files("avatar.png"), ("set_input_files", "avatar.png")),
        ],
    )
    def test_element_action_family_delegates(self, action: Callable[["LocatorFacade"], None], expected: tuple) -> None:
        element = make_locator_facade(FakeLocator())

        action(element)

        assert element._locator.calls == [expected]  # each mirror call recorded with exact args

    def test_click_maps_button_values(self) -> None:
        element = make_locator_facade(FakeLocator())

        element.click()
        element.click("")
        element.click("right")
        element.click("middle")

        assert element._locator.calls == [
            ("click", "left"),  # the empty button means the left mouse button
            ("click", "left"),
            ("click", "right"),
            ("click", "middle"),
        ]

    def test_drag_to_receives_the_target_locator(self) -> None:
        source = make_locator_facade(FakeLocator())
        target = make_locator_facade(FakeLocator())

        source.drag_to(target)

        # the raw target locator crosses facade-to-facade inside the boundary module, never out
        assert source._locator.calls == [("drag_to", target._locator)]

    def test_expectations_apply_assertions_through_expect(self) -> None:
        locator = FakeLocator()
        element = make_locator_facade(locator)
        assertions = RecordingAssertions()

        recorder = lambda loc: FakeExpectation(loc, assertions.calls)  # noqa: E731
        with mock.patch("prettyplay.driver.page.expect", side_effect=recorder):
            element.expect_visible()
            element.expect_text("Добро пожаловать")
            element.expect_enabled()

        assert assertions.calls == [
            ("received", locator),
            "to_be_visible",
            ("received", locator),
            ("to_contain_text", "Добро пожаловать"),
            ("received", locator),
            "to_be_enabled",
        ]

    def test_expectations_receive_the_wrapped_locator(self) -> None:
        locator = FakeLocator()
        element = make_locator_facade(locator)
        assertions = RecordingAssertions()

        recorder = lambda loc: FakeExpectation(loc, assertions.calls)  # noqa: E731
        with mock.patch("prettyplay.driver.page.expect", side_effect=recorder):
            element.expect_visible()

        assert assertions.calls[0] == ("received", locator)
        assert assertions.calls[0][1] is locator

    def test_expectation_family_uses_the_full_set(self) -> None:
        locator = FakeLocator()
        element = make_locator_facade(locator)
        assertions = RecordingAssertions()

        recorder = lambda loc: FakeExpectation(loc, assertions.calls)  # noqa: E731
        with mock.patch("prettyplay.driver.page.expect", side_effect=recorder):
            element.expect_visible()
            element.expect_text("Добро пожаловать")
            element.expect_enabled()
            element.expect_hidden()
            element.expect_value("user")
            element.expect_checked()
            element.expect_count(3)
            element.expect_attribute("href", "/docs")

        # the eight expectation members map onto their to_* assertions with exact args
        assert assertions.calls == [
            ("received", locator),
            "to_be_visible",
            ("received", locator),
            ("to_contain_text", "Добро пожаловать"),
            ("received", locator),
            "to_be_enabled",
            ("received", locator),
            "to_be_hidden",
            ("received", locator),
            ("to_have_value", "user"),
            ("received", locator),
            "to_be_checked",
            ("received", locator),
            ("to_have_count", 3),
            ("received", locator),
            ("to_have_attribute", "href", "/docs"),
        ]

    def test_failed_expectation_raises_assertion_error(self) -> None:
        # a failed wait raises AssertionError (goes to classification), not swallowed
        element = make_locator_facade(FakeLocator())

        class ExplodingExpectation:
            def to_be_visible(self) -> None:
                raise AssertionError("locator expected to be visible")

        with mock.patch("prettyplay.driver.page.expect", return_value=ExplodingExpectation()):
            try:
                element.expect_visible()
            except AssertionError:
                pass
            else:
                raise AssertionError("expect_visible must propagate AssertionError")

    def test_locator_actions_never_return_raw_objects(self) -> None:
        element = make_locator_facade(FakeLocator())
        target = make_locator_facade(FakeLocator())

        with mock.patch("prettyplay.driver.page.expect", return_value=FakeExpectation(FakeLocator(), [])):
            assert element.click() is None
            assert element.dblclick() is None
            assert element.fill("x") is None
            assert element.clear() is None
            assert element.press("Enter") is None
            assert element.check() is None
            assert element.uncheck() is None
            assert element.hover() is None
            assert element.select_option("x") is None
            assert element.drag_to(target) is None
            assert element.set_input_files("avatar.png") is None
            assert element.expect_visible() is None
            assert element.expect_text("x") is None
            assert element.expect_enabled() is None
            assert element.expect_hidden() is None
            assert element.expect_value("x") is None
            assert element.expect_checked() is None
            assert element.expect_count(1) is None
            assert element.expect_attribute("href", "/x") is None


class TestFacadeThreadingBoundary:
    """Threading boundary: a hand-built facade without a worker calls Playwright inline."""

    def test_facade_without_worker_calls_inline_in_current_thread(self) -> None:
        page = FakePage()
        seen_threads: list[int] = []
        original_goto = page.goto

        def recording_goto(url: str) -> None:
            seen_threads.append(threading.get_ident())
            original_goto(url)

        page.goto = recording_goto  # type: ignore[method-assign]
        facade = make_page_facade(page)

        facade.goto("https://example.com")

        assert seen_threads == [threading.get_ident()]  # direct path: the same thread


class TestDialogFacadeLogic:
    """Logic tests: delegation of every DialogFacade member to the wrapped dialog."""

    def test_dialog_facade_members(self) -> None:
        fake = FakeDialog(type="prompt", message="Name?", default_value="Ann")
        dialog = make_dialog_facade(fake)

        assert dialog.type == "prompt"
        assert dialog.message == "Name?"
        assert dialog.default_value == "Ann"

        dialog.accept("Bob")
        dialog.dismiss()

        assert fake.calls == [("accept", {"prompt_text": "Bob"}), ("dismiss",)]

    def test_dialog_facade_marshals_through_the_inherited_worker(self) -> None:
        fake = FakeDialog()
        dialog = make_dialog_facade(fake)
        worker = RecordingWorker()
        dialog._worker = worker

        message = dialog.message
        dialog.dismiss()

        assert message == ""

        assert len(worker.calls) == 2  # every property read and action rides the driver thread
        assert fake.calls == [("dismiss",)]

    def test_dialog_actions_never_return_raw_objects(self) -> None:
        dialog = make_dialog_facade(FakeDialog())

        assert dialog.accept("Bob") is None
        assert dialog.accept() is None
        assert dialog.dismiss() is None
        assert isinstance(dialog.type, str)
        assert isinstance(dialog.message, str)
        assert isinstance(dialog.default_value, str)


class TestFrameFacadeLogic:
    """Logic tests: delegation of every FrameFacade member to the wrapped frame locator."""

    def test_frame_facade_family_and_nesting(self) -> None:
        fake = FakeFrameLocator()
        worker = RecordingWorker()
        frame = make_frame_facade(fake)
        frame._worker = worker

        by_role = frame.get_by_role("button", name="Pay")
        by_test_id = frame.get_by_test_id("pay")
        by_selector = frame.locator("#x")
        nested = frame.frame_locator("#inner")
        frame.get_by_role("button")  # the empty-name variant matches by role alone

        assert fake.calls == [
            ("get_by_role", "button", "Pay"),
            ("get_by_test_id", "pay"),
            ("locator", "#x"),
            ("frame_locator", "#inner"),
            ("get_by_role", "button", None),  # no name kwarg reaches Playwright
        ]
        assert isinstance(by_role, LocatorFacade)
        assert by_role._locator is fake.locators[0]  # wraps exactly the located raw locator
        assert by_role._worker is worker  # the located element inherits the driver thread
        assert isinstance(by_test_id, LocatorFacade)
        assert by_test_id._worker is worker
        assert isinstance(by_selector, LocatorFacade)
        assert by_selector._worker is worker
        assert isinstance(nested, FrameFacade)  # nested frames chain
        assert nested._frame_locator is fake.frames[0]
        assert nested._worker is worker

    @pytest.mark.parametrize(
        ("member", "parameter", "value"),
        [
            ("get_by_label", "label", "Username"),
            ("get_by_text", "text", "Welcome"),
            ("get_by_placeholder", "placeholder", "Search"),
            ("get_by_alt_text", "alt", "Logo"),
            ("get_by_title", "title", "Close"),
            ("get_by_test_id", "test_id", "submit"),
        ],
    )
    def test_frame_get_by_family_delegates(self, member: str, parameter: str, value: str) -> None:
        fake = FakeFrameLocator()
        frame = make_frame_facade(fake)

        element = getattr(frame, member)(value)

        assert fake.calls == [(member, value)]  # the mirror call recorded with the verbatim argument
        assert isinstance(element, LocatorFacade)
        assert element._locator is fake.locators[0]

    def test_frame_locator_passes_selectors_verbatim(self) -> None:
        fake = FakeFrameLocator()
        frame = make_frame_facade(fake)

        for selector in ("form > button.primary", "//button[@type='submit']", "[data-qa='row'] > input"):
            element = frame.locator(selector)
            assert isinstance(element, LocatorFacade)

        assert [call for call in fake.calls if call[0] == "locator"] == [
            ("locator", "form > button.primary"),
            ("locator", "//button[@type='submit']"),
            ("locator", "[data-qa='row'] > input"),
        ]  # no facade-side selector sniffing or rewriting

    def test_nested_frame_locating_inherits_the_worker(self) -> None:
        fake = FakeFrameLocator()
        worker = RecordingWorker()
        frame = make_frame_facade(fake)
        frame._worker = worker

        nested = frame.frame_locator("#inner")
        element = nested.get_by_text("Nested label")

        assert fake.frames[0].calls == [("get_by_text", "Nested label")]
        assert element._worker is worker  # actions on frame content behave like page content
        assert nested._worker is worker

    def test_frame_facade_without_worker_runs_inline(self) -> None:
        fake = FakeFrameLocator()
        frame = make_frame_facade(fake)

        assert frame._worker is None
        element = frame.get_by_label("Username")

        assert fake.calls == [("get_by_label", "Username")]  # hand-built scope: inline, no worker
        assert element._worker is None


class TestDialogAndPopupCaptures:
    """Logic tests: the expect_dialog/expect_popup captures resolve at block exit."""

    def test_expect_dialog_yields_usable_dialog_facade(self) -> None:
        page = FakePage()
        page.dialog_value = FakeDialog(type="confirm", message="Delete?", default_value="")
        facade = make_page_facade(page)

        with facade.expect_dialog() as dialog:
            facade.get_by_role("button", name="Delete").click()

        assert dialog.message == "Delete?"
        assert dialog.type == "confirm"
        assert dialog.default_value == ""
        dialog.accept()

        assert page.calls == [("expect_event", "dialog"), ("get_by_role", "button", "Delete")]
        assert page.locators[0].calls == [("click", "left")]  # the block action ran while armed
        assert page.dialog_value.calls == [("accept", {})]  # accept without a prompt_text kwarg
        assert facade._router.capture_page is None  # the claim cleared at exit

    def test_expect_dialog_timeout_names_the_event(self) -> None:
        page = FakePage()
        page.dialog_timeout = True
        facade = make_page_facade(page)

        with pytest.raises(Error) as info, facade.expect_dialog():
            pass

        assert 'event "dialog"' in str(info.value)  # actionable — names the awaited event
        assert not isinstance(info.value, AssertionError)  # an action failure, never a failed check
        assert facade._router.capture_page is None  # cleared in the finally

    def test_expect_popup_yields_bound_page_facade(self) -> None:
        page = FakePage()
        popup_page = FakePopupPage(url="https://docs.example.com")
        page.popup_value = popup_page
        worker = RecordingWorker()
        facade = make_page_facade(page)
        facade._worker = worker

        with facade.expect_popup() as popup:
            facade.get_by_role("link", name="Open docs").click()
        popup.bring_to_front()

        assert isinstance(popup, PageFacade)
        assert popup._worker is worker  # bound to the opener's driver thread
        assert popup._page is popup_page  # wraps the raw popup page — never returns it
        assert popup_page.calls == [("bring_to_front",)]

    def test_expect_popup_timeout_names_the_event(self) -> None:
        page = FakePage()
        page.popup_timeout = True
        worker = RecordingWorker()
        facade = make_page_facade(page)
        facade._worker = worker

        with pytest.raises(Error) as info, facade.expect_popup() as popup:
            pass

        assert 'event "popup"' in str(info.value)  # actionable — names the awaited event
        assert not isinstance(info.value, AssertionError)  # an action failure, never a failed check
        with pytest.raises(AttributeError, match="resolves at the end of the with-block"):
            _ = popup.url  # the shell stays uninitialized — the guard covers any post-catch access

    def test_new_members_marshal_to_the_driver_thread(self) -> None:
        page = FakePage()
        page.dialog_value = FakeDialog(type="alert", message="Hi")
        context = FakeContext(pages=[page])
        worker = ThreadedWorker()
        facade = make_page_facade(page, context)
        facade._worker = worker
        assertions: list[tuple[Any, ...]] = []

        recorder = lambda receiver: FakePageExpectation(receiver, assertions)  # noqa: E731
        with mock.patch("prettyplay.driver.page.expect", side_effect=recorder):
            facade.goto("https://example.com")
            facade.expect_url("**/dashboard")
            frame = facade.frame_locator("#frame")
            listed = facade.pages
            with facade.expect_dialog() as dialog:
                pass
            dialog.accept("Bob")

        assert frame._worker is worker
        assert all(wrapped._worker is worker for wrapped in listed)
        # one marshaled unit per call: goto, expect_url, frame_locator, pages, capture enter, capture exit, accept
        assert len(worker.idents) == 7
        assert all(ident != threading.get_ident() for ident in worker.idents)  # never the calling thread

    def test_hand_built_facade_runs_inline(self) -> None:
        page = FakePage()
        page.dialog_value = FakeDialog(message="Saved")
        facade = make_page_facade(page)

        assert facade._worker is None
        element = facade.locator("#save")
        frame = facade.frame_locator("#frame")
        with facade.expect_dialog() as dialog:
            pass

        assert dialog.message == "Saved"
        assert page.calls == [("locator", "#save"), ("frame_locator", "#frame"), ("expect_event", "dialog")]
        assert element._worker is None  # no worker required anywhere on the path
        assert frame._worker is None
        assert facade._router is not None  # lazily created default router
        assert facade._router.accept_dialogs is False

    def test_popup_capture_and_pages_agree(self) -> None:
        main = FakePage()
        popup_page = FakePopupPage()
        main.popup_value = popup_page
        context = FakeContext(pages=[main, popup_page])
        worker = RecordingWorker()
        router = _DialogRouter(accept_dialogs=True)
        facade = make_page_facade(main, context)
        facade._worker = worker
        facade._router = router

        with facade.expect_popup() as captured:
            pass
        listed = facade.pages

        assert len(listed) == 2
        assert isinstance(captured, PageFacade)
        assert captured._page is popup_page
        assert listed[1]._page is popup_page  # the same raw page, wrapped independently
        assert captured is not listed[1]
        for wrapped in (captured, *listed):
            assert wrapped._worker is worker  # the session worker, inherited
            assert wrapped._router is router  # the shared context router

    def test_popup_capture_claims_through_the_shared_router(self) -> None:
        main = FakePage()
        popup_page = FakePopupPage()
        context = FakeContext(pages=[main, popup_page])
        router = _DialogRouter(accept_dialogs=True)
        popup = PageFacade(popup_page, context)
        popup._router = router

        handler = router.handle_for(popup_page)  # what the context page-event wiring registers
        event = FakeDialog(type="confirm", message="Leave?")
        popup_page.dialog_value = event  # the waiter resolves the same dialog the handler saw

        with popup.expect_dialog() as dialog:
            handler(event)  # dispatched while the capture is armed

        assert event.calls == []  # the handler claimed it — neither accept nor dismiss fired
        assert dialog.message == "Leave?"
        dialog.accept()
        assert event.calls == [("accept", {})]  # the facade resolves the dialog exactly once
        assert router.capture_page is None  # cleared after the block

    def test_access_before_block_resolution_raises_actionable(self) -> None:
        page = FakePage()
        page.dialog_value = FakeDialog(message="Hi")
        facade = make_page_facade(page)

        with (
            pytest.raises(AttributeError, match="resolves at the end of the with-block") as info,
            facade.expect_dialog() as dialog,
        ):
            _ = dialog.message  # pre-resolution access

        assert not isinstance(info.value, AssertionError)  # an access guard, never a failed check

    def test_dialog_block_exception_cancels_the_waiter_and_propagates(self) -> None:
        page = FakePage()
        page.dialog_value = FakeDialog(message="Hi")
        facade = make_page_facade(page)
        capture = facade.expect_dialog()

        with pytest.raises(RuntimeError, match="boom"), capture as dialog:
            raise RuntimeError("boom")  # the triggering action itself failed

        assert capture._cm.calls == ["__enter__", "__exit__"]  # the waiter exited — cancelled, no wait
        assert page.dialog_value.calls == []  # cancelled without a timeout: the dialog never resolved
        assert facade._router.capture_page is None  # the claim cleared on the exception path too
        with pytest.raises(AttributeError, match="resolves at the end of the with-block"):
            _ = dialog.message  # the shell stays uninitialized — the guard covers later access

    def test_popup_block_exception_cancels_the_waiter_and_propagates(self) -> None:
        page = FakePage()
        page.popup_value = FakePopupPage(url="https://docs.example.com")
        facade = make_page_facade(page)
        capture = facade.expect_popup()

        with pytest.raises(RuntimeError, match="boom"), capture as popup:
            raise RuntimeError("boom")  # the opening action itself failed

        assert capture._cm.calls == ["__enter__", "__exit__"]  # the waiter exited — cancelled, no wait
        with pytest.raises(AttributeError, match="resolves at the end of the with-block"):
            _ = popup.url  # the shell stays uninitialized — the guard covers later access

    def test_initialized_page_facade_missing_attribute_gets_the_regular_text(self) -> None:
        facade = make_page_facade(FakePage())

        with pytest.raises(AttributeError, match="object has no attribute 'find_by_role'"):
            facade.find_by_role("button", name="Delete")  # a retired name on an initialized facade

    def test_initialized_dialog_facade_missing_attribute_gets_the_regular_text(self) -> None:
        facade = make_dialog_facade(FakeDialog(message="Hi"))

        with pytest.raises(AttributeError, match="object has no attribute 'send_keys'"):
            facade.send_keys("Hi")  # a plain typo on an initialized facade
