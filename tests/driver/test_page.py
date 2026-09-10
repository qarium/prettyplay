"""Tests for the PageFacade and LocatorFacade page API of the prettyplay.driver cell."""

import inspect
import threading
from typing import Any, get_type_hints
from unittest import mock

from prettyplay.driver import LocatorFacade, PageFacade


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

    def click(self) -> None:
        self.calls.append(("click",))
        if self.fail_on_click:
            raise AssertionError("element not stable")

    def fill(self, value: str) -> None:
        self.calls.append(("fill", value))

    def select_option(self, value: str) -> None:
        self.calls.append(("select_option", value))

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


class FakeContext:
    """Fake isolated browser context; ``close`` records the call."""

    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


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

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))
        self.url = url

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

    def locator(self, selector: str) -> FakeBodyLocator:
        self.calls.append(("locator", selector))
        return self._body

    def screenshot(self, full_page: bool = False) -> bytes:
        self.calls.append(("screenshot", full_page))
        return b"png-bytes"

    @property
    def context(self) -> FakeContext:
        return self._context


def make_page_facade(page: FakePage | None = None, context: FakeContext | None = None) -> PageFacade:
    """Build a PageFacade over fakes; the context defaults to the fake page's own."""
    page = page or FakePage()
    return PageFacade(page, context or page.context)


def make_locator_facade(locator: FakeLocator | None = None) -> LocatorFacade:
    """Build a LocatorFacade over a fake locator."""
    return LocatorFacade(locator or FakeLocator())


class TestPageFacadeContract:
    """Contract tests: facade import, method set, signatures, return types."""

    def test_page_facade_importable_from_facade(self) -> None:
        assert isinstance(PageFacade, type)

    def test_locator_facade_importable_from_facade(self) -> None:
        assert isinstance(LocatorFacade, type)

    def test_page_facade_surface_matches_contract(self) -> None:
        surface = [
            "open",
            "find_by_role",
            "find_by_label",
            "find_by_text",
            "find_by_attribute",
            "find_by_css",
            "find_by_xpath",
            "aria_snapshot",
            "screenshot",
            "url",
            "scroll_to_element",
            "scroll_down",
            "scroll_up",
            "scroll_to_bottom",
            "scroll_to_top",
            "scroll_into_view",
            "scroll_container_down",
            "scroll_container_up",
            "close",
        ]

        for name in surface:
            assert hasattr(PageFacade, name), name

    def test_universal_locators_declared_after_find_by_text(self) -> None:
        declared = [name for name in vars(PageFacade) if not name.startswith("_")]

        assert declared.index("find_by_text") < declared.index("find_by_attribute")
        assert declared.index("find_by_attribute") < declared.index("find_by_css")
        assert declared.index("find_by_css") < declared.index("find_by_xpath")

    def test_locator_facade_surface_matches_contract(self) -> None:
        surface = ["click", "fill", "select_option", "expect_visible", "expect_text", "expect_enabled"]

        for name in surface:
            assert hasattr(LocatorFacade, name), name

    def test_page_facade_signatures_match_contract(self) -> None:
        assert list(inspect.signature(PageFacade.open).parameters) == ["self", "url"]
        assert list(inspect.signature(PageFacade.find_by_role).parameters) == ["self", "role", "name"]
        assert list(inspect.signature(PageFacade.find_by_label).parameters) == ["self", "label"]
        assert list(inspect.signature(PageFacade.find_by_text).parameters) == ["self", "text"]
        assert list(inspect.signature(PageFacade.find_by_attribute).parameters) == ["self", "name", "value"]
        assert list(inspect.signature(PageFacade.find_by_css).parameters) == ["self", "selector"]
        assert list(inspect.signature(PageFacade.find_by_xpath).parameters) == ["self", "xpath"]
        assert list(inspect.signature(PageFacade.aria_snapshot).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.screenshot).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.close).parameters) == ["self"]

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
        assert list(inspect.signature(LocatorFacade.click).parameters) == ["self"]
        assert list(inspect.signature(LocatorFacade.fill).parameters) == ["self", "value"]
        assert list(inspect.signature(LocatorFacade.select_option).parameters) == ["self", "value"]
        assert list(inspect.signature(LocatorFacade.expect_visible).parameters) == ["self"]
        assert list(inspect.signature(LocatorFacade.expect_text).parameters) == ["self", "text"]
        assert list(inspect.signature(LocatorFacade.expect_enabled).parameters) == ["self"]

    def test_page_facade_annotations_match_contract(self) -> None:
        hints = get_type_hints(PageFacade.open)
        assert hints["url"] is str

        role_hints = get_type_hints(PageFacade.find_by_role)
        assert role_hints["role"] is str
        assert role_hints["name"] is str
        assert role_hints["return"] is LocatorFacade

        attribute_hints = get_type_hints(PageFacade.find_by_attribute)
        assert attribute_hints["name"] is str
        assert attribute_hints["value"] is str
        assert attribute_hints["return"] is LocatorFacade

        css_hints = get_type_hints(PageFacade.find_by_css)
        assert css_hints["selector"] is str
        assert css_hints["return"] is LocatorFacade

        xpath_hints = get_type_hints(PageFacade.find_by_xpath)
        assert xpath_hints["xpath"] is str
        assert xpath_hints["return"] is LocatorFacade

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
        facade = make_page_facade(page)

        assert isinstance(facade.open("https://example.com"), type(None))
        assert isinstance(facade.find_by_role("button", name="Войти"), LocatorFacade)
        assert isinstance(facade.find_by_label("Логин"), LocatorFacade)
        assert isinstance(facade.find_by_text("Добро пожаловать"), LocatorFacade)
        assert isinstance(facade.find_by_attribute("data-test-id", "submit"), LocatorFacade)
        assert isinstance(facade.find_by_css("form > button.primary"), LocatorFacade)
        assert isinstance(facade.find_by_xpath("//button[@type='submit']"), LocatorFacade)
        assert isinstance(facade.aria_snapshot(), str)
        assert isinstance(facade.screenshot(), bytes)
        assert isinstance(facade.url, str)
        assert facade.close() is None


class TestPageFacadeLogic:
    """Logic tests: delegation of every PageFacade method to the wrapped page."""

    def test_open_delegates_to_goto(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        facade.open("https://example.com")

        assert page.calls == [("goto", "https://example.com")]

    def test_find_by_role_delegates_with_name_kwarg(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        element = facade.find_by_role("button", name="Войти")

        assert page.calls == [("get_by_role", "button", "Войти")]
        assert isinstance(element, LocatorFacade)

    def test_find_by_label_and_text_delegate(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        by_label = facade.find_by_label("Логин")
        by_text = facade.find_by_text("Добро пожаловать")

        assert page.calls == [("get_by_label", "Логин"), ("get_by_text", "Добро пожаловать")]
        assert isinstance(by_label, LocatorFacade)
        assert isinstance(by_text, LocatorFacade)

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
        # close() закрывает только контекст; browser остаётся жив (контракт фасада)
        page = FakePage()
        facade = make_page_facade(page)
        facade.close()

        assert page.context.close_calls == 1
        assert page.calls == []  # браузерных вызовов не было — только context.close()


class TestUniversalLocatorLogic:
    """Logic tests: the attribute, CSS and XPath locating methods of the page facade."""

    def test_find_by_attribute_builds_css_attribute_selector(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        element = facade.find_by_attribute("data-test-id", "submit-button")

        assert page.calls == [("locator", '[data-test-id="submit-button"]')]
        assert isinstance(element, LocatorFacade)

    def test_find_by_css_passes_selector_verbatim(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        element = facade.find_by_css("form > button.primary")

        assert page.calls == [("locator", "form > button.primary")]
        assert isinstance(element, LocatorFacade)

    def test_find_by_xpath_applies_xpath_engine_prefix(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        element = facade.find_by_xpath("*[@id='main']")

        assert page.calls == [("locator", "xpath=*[@id='main']")]
        assert isinstance(element, LocatorFacade)

    def test_find_by_attribute_escapes_quotes_and_backslashes(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        element = facade.find_by_attribute("data-test-id", 'a"b\\c')

        assert page.calls == [('locator', '[data-test-id="a\\"b\\\\c"]')]
        assert isinstance(element, LocatorFacade)

    def test_universal_locators_never_raise_eagerly(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        for element in (
            facade.find_by_attribute("data-qa", "login"),
            facade.find_by_css("#missing"),
            facade.find_by_xpath("//never-resolves"),
        ):
            assert isinstance(element, LocatorFacade)


class TestPageFacadeScrollLogic:
    """Logic tests: delegation of every scroll method to the Playwright primitives."""

    def test_scroll_primitives_delegate_to_playwright(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)
        element = facade.find_by_text("Fifth card")
        container = facade.find_by_role("list", name="Recommendations")
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
        element = facade.find_by_text("Fifth card")
        container = facade.find_by_role("region", name="Carousel")
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
        element = facade.find_by_text("Detached card")
        container = facade.find_by_role("region", name="Carousel")

        facade.scroll_into_view(element, container)

        # the resolved handle reaches the container evaluation as-is — the page fails the render
        assert container._locator.evaluate_args == [None]
        assert ("element_handle",) in element._locator.calls

    def test_scroll_to_element_uses_nearest_scrollable_ancestor_primitive(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)
        element = facade.find_by_text("Load more")

        facade.scroll_to_element(element)

        assert element._locator.calls == [("scroll_into_view_if_needed",)]
        assert page.calls == [("get_by_text", "Load more")]  # nothing else touched the page

    def test_scroll_methods_never_sleep(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)
        element = facade.find_by_text("Footer")
        container = facade.find_by_role("list", name="Results")

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

        assert element._locator.calls == [("click",), ("fill", "user"), ("select_option", "RU")]

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

    def test_failed_expectation_raises_assertion_error(self) -> None:
        # неуспешное ожидание бросает AssertionError (идёт в классификацию), не глотается
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

        with mock.patch("prettyplay.driver.page.expect", return_value=FakeExpectation(FakeLocator(), [])):
            assert element.click() is None
            assert element.fill("x") is None
            assert element.select_option("x") is None
            assert element.expect_visible() is None
            assert element.expect_text("x") is None
            assert element.expect_enabled() is None


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

        facade.open("https://example.com")

        assert seen_threads == [threading.get_ident()]  # прямой путь: тот же поток
