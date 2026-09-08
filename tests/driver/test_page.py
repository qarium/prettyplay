"""Tests for the PageFacade and LocatorFacade page API of the prettyplay.driver cell."""

import inspect
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


class FakeLocator:
    """Fake Playwright locator hidden behind the facade; records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.assertions: list[str] = []
        self.fail_on_click = False

    def click(self) -> None:
        self.calls.append(("click",))
        if self.fail_on_click:
            raise AssertionError("element not stable")

    def fill(self, value: str) -> None:
        self.calls.append(("fill", value))

    def select_option(self, value: str) -> None:
        self.calls.append(("select_option", value))


class FakeContext:
    """Fake isolated browser context; ``close`` records the call."""

    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


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
        self.locators: list[FakeLocator] = []
        self._context = FakeContext()
        self._body = FakeBodyLocator(snapshot)
        self._locator_factory = FakeLocator

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))
        self.url = url

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
            "aria_snapshot",
            "screenshot",
            "url",
            "close",
        ]

        for name in surface:
            assert hasattr(PageFacade, name), name

    def test_locator_facade_surface_matches_contract(self) -> None:
        surface = ["click", "fill", "select_option", "expect_visible", "expect_text", "expect_enabled"]

        for name in surface:
            assert hasattr(LocatorFacade, name), name

    def test_page_facade_signatures_match_contract(self) -> None:
        assert list(inspect.signature(PageFacade.open).parameters) == ["self", "url"]
        assert list(inspect.signature(PageFacade.find_by_role).parameters) == ["self", "role", "name"]
        assert list(inspect.signature(PageFacade.find_by_label).parameters) == ["self", "label"]
        assert list(inspect.signature(PageFacade.find_by_text).parameters) == ["self", "text"]
        assert list(inspect.signature(PageFacade.aria_snapshot).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.screenshot).parameters) == ["self"]
        assert list(inspect.signature(PageFacade.close).parameters) == ["self"]

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

    def test_no_raw_playwright_objects_escape(self) -> None:
        page = FakePage()
        facade = make_page_facade(page)

        assert isinstance(facade.open("https://example.com"), type(None))
        assert isinstance(facade.find_by_role("button", name="Войти"), LocatorFacade)
        assert isinstance(facade.find_by_label("Логин"), LocatorFacade)
        assert isinstance(facade.find_by_text("Добро пожаловать"), LocatorFacade)
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
