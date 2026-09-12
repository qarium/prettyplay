"""Tests for the DriverSession browser lifecycle of the prettyplay.driver cell."""

import asyncio
import inspect
import threading
from unittest import mock

import pytest
from playwright.sync_api import Error
from prettyplay.config import BrowserConfig, Config
from prettyplay.driver import DriverSession, PageFacade

IPHONE_13_DESCRIPTOR: dict[str, object] = {
    "viewport": {"width": 390, "height": 664},
    "user_agent": "ua",
    "has_touch": True,
    "is_mobile": True,
    "device_scale_factor": 3,
    "default_browser_type": "webkit",
}

PIXEL_7_DESCRIPTOR: dict[str, object] = {
    "viewport": {"width": 412, "height": 915},
    "user_agent": "ua-pixel",
    "has_touch": True,
    "is_mobile": True,
    "device_scale_factor": 2.625,
    "default_browser_type": "chromium",
}


class FakePlaywrightFactory:
    """Fake ``sync_playwright`` boundary: records launches, contexts and the driver stop.

    Mimics the real shape: ``sync_playwright()`` returns a context manager whose
    ``start()`` yields the driver; the driver holds the engine matrix, every
    ``launch()`` returns the one browser process of the run. Records the thread
    ident of every boundary call, so tests can prove the dedicated driver thread.
    """

    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.launches: list[str] = []
        self.launch_kwargs: list[dict] = []
        self.engine_starts: list[str] = []  # each engine start: launch or connect
        self.contexts: list[FakeContext] = []
        self.context_kwargs: list[dict] = []  # kwargs of every new_context call
        self.devices: dict[str, dict[str, object]] = {}  # the running device registry
        self.threads: list[int] = []  # thread ident of every boundary call
        self.chromium = FakeEngine("chromium", self)
        self.firefox = FakeEngine("firefox", self)
        self.webkit = FakeEngine("webkit", self)

    def __call__(self) -> "FakePlaywrightFactory":
        return self

    def start(self) -> "FakePlaywrightFactory":
        self.threads.append(threading.get_ident())
        self.start_calls += 1
        return self

    def stop(self) -> None:
        self.threads.append(threading.get_ident())
        self.stop_calls += 1


class FakeEngine:
    """Fake Playwright browser engine: records every launch and connect into the factory."""

    def __init__(self, name: str, factory: FakePlaywrightFactory) -> None:
        self.name = name
        self._factory = factory
        self.launch_calls: list[mock.Mock] = []
        self.connect_calls: list[str] = []
        self.connect_kwargs: list[dict] = []
        self._browser: FakeBrowser | None = None

    def launch(self, **kwargs: object) -> "FakeBrowser":
        self._factory.threads.append(threading.get_ident())
        self._factory.launches.append(self.name)
        self._factory.launch_kwargs.append(kwargs)
        self._factory.engine_starts.append(self.name)
        self.launch_calls.append(mock.Mock(kwargs=kwargs))

        if self._browser is None:
            self._browser = FakeBrowser(self._factory)

        return self._browser

    def connect(self, endpoint: str, **kwargs: object) -> "FakeBrowser":
        self._factory.threads.append(threading.get_ident())
        self.connect_calls.append(endpoint)
        self.connect_kwargs.append(kwargs)
        self._factory.engine_starts.append(self.name)

        if self._browser is None:
            self._browser = FakeBrowser(self._factory)

        return self._browser


class FakeBrowser:
    """Fake launched browser process shared by the whole run."""

    def __init__(self, factory: FakePlaywrightFactory) -> None:
        self._factory = factory
        self.close_calls = 0

    def new_context(self, **kwargs: object) -> "FakeContext":
        self._factory.threads.append(threading.get_ident())
        self._factory.context_kwargs.append(kwargs)
        context = FakeContext(self)
        self._factory.contexts.append(context)
        return context

    def close(self) -> None:
        self._factory.threads.append(threading.get_ident())
        self.close_calls += 1


class CrashingBrowser(FakeBrowser):
    """Fake browser whose close fails, as after a crash of the browser process."""

    def close(self) -> None:
        self._factory.threads.append(threading.get_ident())
        self.close_calls += 1
        raise Error("Target page, context or browser has been closed")


class FakeContext:
    """Fake isolated browser context; every page joins through the page event.

    Records ``on(event, handler)`` registrations and fires the registered
    ``"page"`` handlers for every page it opens — the main page of
    ``new_page()`` and a popup alike, exactly like the Playwright context.
    """

    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.close_calls = 0
        self.pages: list[FakePage] = []
        self.events: list[tuple[str, object]] = []  # every on(event, handler) registration
        self.page_handlers: list[object] = []  # the handlers registered on("page", …)

    def on(self, event: str, handler: object) -> None:
        self.browser._factory.threads.append(threading.get_ident())
        self.events.append((event, handler))
        if event == "page":
            self.page_handlers.append(handler)

    def new_page(self) -> "FakePage":
        self.browser._factory.threads.append(threading.get_ident())
        page = FakePage(self)
        self.pages.append(page)
        for handler in self.page_handlers:  # the context page event fires for every page
            handler(page)
        return page

    def close(self) -> None:
        self.browser._factory.threads.append(threading.get_ident())
        self.close_calls += 1


class FakePage:
    """Fake Playwright page object hidden behind the facade.

    Records every call together with its thread ident; ``goto_error`` replays
    a failure scenario of the navigation.
    """

    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.goto_error: Exception | None = None
        self.events: list[tuple[str, object]] = []  # every on(event, handler) registration
        self.dialog_handlers: list[object] = []  # the handlers registered on("dialog", …)

    def on(self, event: str, handler: object) -> None:
        self.context.browser._factory.threads.append(threading.get_ident())
        self.events.append((event, handler))
        if event == "dialog":
            self.dialog_handlers.append(handler)

    @property
    def url(self) -> str:
        self.context.browser._factory.threads.append(threading.get_ident())
        return "about:blank"

    def goto(self, url: str) -> None:
        self.context.browser._factory.threads.append(threading.get_ident())
        if self.goto_error is not None:
            raise self.goto_error

    def get_by_role(self, role: str, name: str | None = None) -> "FakeLocator":
        self.context.browser._factory.threads.append(threading.get_ident())
        return FakeLocator(self.context.browser._factory)

    def get_by_label(self, label: str) -> "FakeLocator":
        self.context.browser._factory.threads.append(threading.get_ident())
        return FakeLocator(self.context.browser._factory)

    def get_by_text(self, text: str) -> "FakeLocator":
        self.context.browser._factory.threads.append(threading.get_ident())
        return FakeLocator(self.context.browser._factory)

    def locator(self, selector: str) -> "FakeSnapshotLocator":
        self.context.browser._factory.threads.append(threading.get_ident())
        return FakeSnapshotLocator(self.context.browser._factory)

    def screenshot(self, full_page: bool = True) -> bytes:
        self.context.browser._factory.threads.append(threading.get_ident())
        return b"png"


class FakeLocator:
    """Fake Playwright locator hidden behind the facade; records thread idents."""

    def __init__(self, factory: FakePlaywrightFactory) -> None:
        self._factory = factory
        self.fail_on_click = False

    def click(self, button: str = "left") -> None:
        self._factory.threads.append(threading.get_ident())
        if self.fail_on_click:
            raise AssertionError("element not stable")

    def fill(self, value: str) -> None:
        self._factory.threads.append(threading.get_ident())

    def select_option(self, value: str) -> None:
        self._factory.threads.append(threading.get_ident())


class FakeSnapshotLocator:
    """Fake ``page.locator("body")``: yields the recorded aria snapshot."""

    def __init__(self, factory: FakePlaywrightFactory) -> None:
        self._factory = factory

    def aria_snapshot(self) -> str:
        self._factory.threads.append(threading.get_ident())
        return "- heading Пример"


class FakeDialog:
    """Fake Playwright dialog dispatched to a registered routing handler; records the resolution."""

    def __init__(self, message: str = "Продолжить?") -> None:
        self.message = message
        self.calls: list[tuple[str, ...]] = []

    def accept(self) -> None:
        self.calls.append(("accept",))

    def dismiss(self) -> None:
        self.calls.append(("dismiss",))


class TestDriverSessionContract:
    """Contract tests: facade import, construction shape, lazy open, safe close."""

    def test_driver_session_importable_from_facade(self) -> None:
        assert isinstance(DriverSession, type)

    def test_constructor_takes_config_and_starts_nothing(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            DriverSession(Config(browser=BrowserConfig(name="chromium")))

        assert factory.start_calls == 0
        assert factory.launches == []

    def test_open_context_returns_page_facade(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            page = session.open_context()
            session.close()

        assert isinstance(page, PageFacade)

    def test_open_context_attaches_the_shared_dialog_router(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            page = session.open_context()
            router = page._router
            worker = page._worker
            session.close()

        assert isinstance(page, PageFacade)
        assert router is not None  # the shared dialog router of the context
        assert router.accept_dialogs is False  # the browser-group setting read once
        assert worker is not None  # the driver-thread attachment still holds

    def test_close_without_launch_is_noop(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            session.close()

        assert factory.start_calls == 0
        assert factory.stop_calls == 0

    def test_public_surface_matches_contract(self) -> None:
        session = DriverSession(Config())

        assert hasattr(session, "open_context")
        assert hasattr(session, "close")

    def test_launch_engine_passes_headless_and_channel(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="msedge", headless=False)))
            session.open_context()
            session.close()

        assert factory.launches == ["chromium"]  # the channel launches via the chromium engine
        assert factory.launch_kwargs == [{"headless": False, "channel": "msedge"}]

    def test_launch_engine_default_config_headless_only(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config())
            session.open_context()
            session.close()

        assert factory.launches == ["chromium"]
        assert factory.launch_kwargs == [{"headless": True}]


class TestDriverSessionLogic:
    """Logic tests: single lazy launch, per-call isolated contexts, idempotent close."""

    def test_open_context_lazy_launch_single_browser(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))

            assert factory.start_calls == 0  # after the constructor: pw.start not called

            page1 = session.open_context()
            page2 = session.open_context()
            session.close()

        assert factory.start_calls == 1
        assert factory.launches == ["chromium"]  # launches == 1
        assert page1 is not page2  # two results — different PageFacade instances
        assert len(factory.contexts) == 2  # 2 contexts created

    def test_open_context_selects_engine_from_config(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="firefox")))
            session.open_context()
            session.close()

        assert factory.launches == ["firefox"]

    def test_launch_passes_headless_and_channel(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="msedge", headless=False)))
            session.open_context()
            session.close()

        assert factory.launches == ["chromium"]  # chrome/msedge go through chromium
        assert factory.chromium.launch_calls[0].kwargs == {"headless": False, "channel": "msedge"}

        factory = FakePlaywrightFactory()
        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config())
            session.open_context()
            session.close()

        assert factory.chromium.launch_calls[0].kwargs == {"headless": True}

    def test_channel_launch_without_installed_browser_propagates_loudly(self) -> None:
        factory = FakePlaywrightFactory()
        # Playwright's native Error names the distribution and the install remedy
        factory.chromium = FailingEngine("chromium", factory, Error("Chromium distribution 'chrome' is not found"))

        def open_context() -> None:
            session = DriverSession(Config(browser=BrowserConfig(name="chrome")))
            session.open_context()

        with (
            mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory),
            pytest.raises(Error, match="is not found"),
        ):
            open_context()

    def test_close_stops_browser_and_driver(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="webkit")))
            session.open_context()
            session.close()

        assert factory.launches == ["webkit"]
        assert factory.contexts[0].browser.close_calls == 1
        assert factory.stop_calls == 1

    def test_close_is_idempotent(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            session.open_context()
            session.close()
            session.close()  # a repeated close — no-op

        browser = factory.contexts[0].browser
        assert browser.close_calls == 1
        assert factory.stop_calls == 1

    def test_close_stops_driver_even_when_browser_close_fails(self) -> None:
        factory = FakePlaywrightFactory()
        factory.chromium._browser = CrashingBrowser(factory)  # a crashed browser process

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            session.open_context()

            with pytest.raises(Error, match="has been closed"):
                session.close()  # the failing browser.close does not hide the error

        assert factory.stop_calls == 1  # playwright.stop not skipped — no driver process leak
        worker = session._worker
        assert worker is None or worker._thread is None  # the worker thread is joined

    def test_close_before_launch_is_noop(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            session.close()  # close() before launch — no-op

        assert factory.start_calls == 0
        assert factory.stop_calls == 0

    def test_contexts_after_close_are_still_isolated(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            session.open_context()
            session.close()
            page = session.open_context()  # a fresh start after close
            session.close()

        assert factory.start_calls == 2
        assert len(factory.launches) == 2
        assert isinstance(page, PageFacade)

    def test_failed_launch_stops_driver_and_retries_cleanly(self) -> None:
        factory = FakePlaywrightFactory()
        factory.chromium = FailingEngine("chromium", factory, RuntimeError("browser binary missing"))
        session = DriverSession(Config(browser=BrowserConfig(name="chromium")))

        with (
            mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory),
            pytest.raises(RuntimeError, match="browser binary missing"),
        ):
            session.open_context()

        assert factory.stop_calls == 1  # driver stopped — no process leak

        factory.chromium = FakeEngine("chromium", factory)  # the retry starts cleanly
        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            page = session.open_context()
            session.close()

        assert factory.start_calls == 2
        assert factory.stop_calls == 2  # no extra stops
        assert isinstance(page, PageFacade)


class FailingEngine:
    """Fake engine whose launch always fails, mimicking a missing browser binary."""

    def __init__(self, name: str, factory: FakePlaywrightFactory, error: Exception) -> None:
        self.name = name
        self._factory = factory
        self._error = error

    def launch(self, **kwargs: object) -> "FakeBrowser":
        self._factory.threads.append(threading.get_ident())
        self._factory.launches.append(self.name)
        raise self._error

    def connect(self, endpoint: str, **kwargs: object) -> "FakeBrowser":
        self._factory.threads.append(threading.get_ident())
        self._factory.engine_starts.append(self.name)
        raise self._error


class TestDriverSessionConnect:
    """Logic tests: the remote ws endpoint branch of the engine start."""

    def test_session_connects_over_ws_endpoint_when_set(self) -> None:
        factory = FakePlaywrightFactory()
        endpoint = "ws://ci-grid:3000/playwright/firefox"

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="firefox", endpoint=endpoint)))
            page = session.open_context()
            session.close()

        assert factory.firefox.connect_calls == [endpoint]
        assert factory.launches == []  # no local launch happened
        assert factory.firefox.connect_kwargs == [{}]  # headless is not passed
        assert isinstance(page, PageFacade)

    def test_session_connect_maps_channels_to_chromium(self) -> None:
        factory = FakePlaywrightFactory()
        endpoint = "ws://ci-grid:3000/playwright/chromium"

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chrome", endpoint=endpoint)))
            session.open_context()
            session.close()

        assert factory.chromium.connect_calls == [endpoint]
        assert factory.launches == []
        assert factory.launch_kwargs == []  # channel= never appeared
        assert factory.firefox.connect_calls == []  # chromium is what got connected

    def test_session_failed_connect_cleans_up_for_retry(self) -> None:
        factory = FakePlaywrightFactory()
        # the raw Playwright error carries only the OS cause — no URL, like the real driver
        factory.firefox = FailingEngine("firefox", factory, Error("websocket connect timeout"))
        session = DriverSession(Config(browser=BrowserConfig(name="firefox", endpoint="ws://dead:1")))

        with (
            mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory),
            pytest.raises(Error, match="ws://dead:1") as excinfo,
        ):
            session.open_context()

        assert "websocket connect timeout" in str(excinfo.value)  # the cause is visible in the message
        assert isinstance(excinfo.value.__cause__, Error)  # the original error is chained
        assert excinfo.value.__cause__.args[0] == "websocket connect timeout"

        worker = session._worker
        assert worker is None or worker._thread is None  # the worker thread is joined

        assert factory.stop_calls == 1  # driver stopped — no process leak

        factory.firefox = FakeEngine("firefox", factory)  # the retry starts cleanly
        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            page = session.open_context()
            session.close()

        assert factory.start_calls == 2
        assert len(factory.engine_starts) == 2  # the second attempt counts as a new engine start
        assert isinstance(page, PageFacade)


def viewport_params(width: int, height: int) -> dict:
    """The expected new_context kwargs of a WxH-shaped screen value."""
    return {"viewport": {"width": width, "height": height}}


SCREEN_MODE_MATRIX = [
    # (case, name, screen, headless, endpoint, expected launch kwargs, expected new_context kwargs)
    # expected launch kwargs None — the remote connect path (connect, no launch)
    ("empty-headed", "chromium", "", False, "", {"headless": False}, {}),
    ("empty-headless", "chromium", "", True, "", {"headless": True}, {}),
    ("empty-remote", "chromium", "", False, "ws://grid:3000", None, {}),
    ("wxh-headed", "chromium", "1280x720", False, "", {"headless": False}, viewport_params(1280, 720)),
    ("wxh-headless", "chromium", "1280x720", True, "", {"headless": True}, viewport_params(1280, 720)),
    ("wxh-remote", "chromium", "1280x720", False, "ws://grid:3000", None, viewport_params(1280, 720)),
    ("device-headed", "chromium", "iPhone 13", False, "", {"headless": False}, dict(IPHONE_13_DESCRIPTOR)),
    ("device-headless", "chromium", "iPhone 13", True, "", {"headless": True}, dict(IPHONE_13_DESCRIPTOR)),
    ("device-remote", "chromium", "iPhone 13", False, "ws://grid:3000", None, dict(IPHONE_13_DESCRIPTOR)),
    (
        "fullscreen-chromium-headed",
        "chromium",
        "fullscreen",
        False,
        "",
        {"headless": False, "args": ["--start-maximized"]},
        {"no_viewport": True},
    ),
    (
        "fullscreen-chrome-channel",
        "chrome",
        "fullscreen",
        False,
        "",
        {"headless": False, "channel": "chrome", "args": ["--start-maximized"]},
        {"no_viewport": True},
    ),
    ("fullscreen-headless", "chromium", "fullscreen", True, "", {"headless": True}, viewport_params(1920, 1080)),
    ("fullscreen-remote", "chromium", "fullscreen", False, "ws://grid:3000", None, viewport_params(1920, 1080)),
    ("fullscreen-firefox-headed", "firefox", "fullscreen", False, "", {"headless": False}, {"no_viewport": True}),
    ("fullscreen-webkit-headed", "webkit", "fullscreen", False, "", {"headless": False}, {"no_viewport": True}),
]


class TestDriverSessionScreenModesContract:
    """Contract tests: the open_context signature and the resolved context parameters."""

    def test_open_context_signature_unchanged_no_parameters(self) -> None:
        parameters = [name for name in inspect.signature(DriverSession.open_context).parameters if name != "self"]
        assert parameters == []

    @pytest.mark.parametrize(
        ("screen", "expected_params"),
        [
            ("", {}),
            ("1280x720", {"viewport": {"width": 1280, "height": 720}}),
            ("iPhone 13", dict(IPHONE_13_DESCRIPTOR)),
            ("fullscreen", {"no_viewport": True}),
        ],
        ids=["empty", "wxh", "device", "fullscreen-local-headed"],
    )
    def test_every_resolution_path_ends_in_new_context_with_params(self, screen: str, expected_params: dict) -> None:
        factory = FakePlaywrightFactory()
        factory.devices = {"iPhone 13": IPHONE_13_DESCRIPTOR, "Pixel 7": PIXEL_7_DESCRIPTOR}

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(screen=screen, headless=False)))
            page = session.open_context()
            session.close()

        assert isinstance(page, PageFacade)
        assert factory.context_kwargs == [expected_params]
        assert threading.get_ident() not in set(factory.threads)  # the resolution ran in the worker


class TestDriverSessionScreenModes:
    """Logic tests: the screen-mode matrix of the context creation and unknown devices."""

    @pytest.mark.parametrize(
        "mode",
        SCREEN_MODE_MATRIX,
        ids=[row[0] for row in SCREEN_MODE_MATRIX],
    )
    def test_open_context_screen_modes(self, mode: tuple) -> None:
        _, name, screen, headless, endpoint, expected_launch, expected_context = mode
        factory = FakePlaywrightFactory()
        factory.devices = {"iPhone 13": IPHONE_13_DESCRIPTOR, "Pixel 7": PIXEL_7_DESCRIPTOR}

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(
                Config(browser=BrowserConfig(name=name, screen=screen, headless=headless, endpoint=endpoint))
            )
            page = session.open_context()
            session.close()

        assert isinstance(page, PageFacade)
        assert factory.context_kwargs == [expected_context]

        if expected_launch is None:  # the remote connect path
            assert factory.launches == []
            assert factory.chromium.connect_calls == [endpoint]
        else:
            assert factory.launch_kwargs == [expected_launch]
            assert factory.chromium.connect_calls == []

    def test_open_context_unknown_device_fails_loudly(self) -> None:
        factory = FakePlaywrightFactory()
        factory.devices = {"iPhone 13": IPHONE_13_DESCRIPTOR, "Pixel 7": PIXEL_7_DESCRIPTOR}

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(screen="iPhon 13")))
            with pytest.raises(Error) as excinfo:
                session.open_context()
            session.close()

        message = str(excinfo.value)
        assert "iPhon" in message  # the unknown value itself is named
        assert "iPhone 13" in message  # the close-name suggestion from the registry
        assert factory.contexts == []  # no context was created


class TestDriverSessionWorkerThread:
    """Behavior tests: the Playwright session lives in a dedicated driver thread.

    Every test closes its session, so no worker thread outlives its test —
    assertions may rely on the worker of THIS session alone.
    """

    def test_playwright_lifecycle_runs_in_dedicated_thread(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            page = session.open_context()
            page.goto("https://example.com")
            session.close()

        main_thread = threading.get_ident()
        assert factory.threads, "граничные вызовы обязаны случиться"
        assert all(ident != main_thread for ident in factory.threads)  # none in the main thread
        assert len(set(factory.threads)) == 1  # all in one dedicated thread

    def test_facade_calls_execute_in_worker_thread(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            page = session.open_context()

            assert page.url == "about:blank"
            page.goto("https://example.com")
            page.get_by_role("button", name="Войти").click()
            page.get_by_label("Логин").fill("user")
            page.get_by_text("Добро пожаловать").select_option("one")
            assert page.aria_snapshot() == "- heading Пример"
            assert page.screenshot() == b"png"
            session.close()

        worker_idents = set(factory.threads)
        assert threading.get_ident() not in worker_idents  # facade calls — not in the test thread
        assert len(worker_idents) == 1

    def test_open_context_leaves_no_running_loop_in_caller_thread(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            session.open_context()
            session.close()

        # regression guard for the IPython bug: no running loop may remain in the caller thread
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()

    def test_worker_exception_propagates_with_type_and_message(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            page = session.open_context()

            page._page.goto_error = AssertionError("элемент не стабилен")  # type: ignore[attr-defined]

            with pytest.raises(AssertionError, match="элемент не стабилен"):
                page.goto("https://example.com")

            session.close()

    def test_close_joins_worker_thread(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            session.open_context()
            worker = session._worker._thread  # check this session's thread

            assert worker is not None
            assert worker.is_alive()
            session.close()

            assert not worker.is_alive()  # the worker thread is finished

    def test_close_without_launch_keeps_thread_count(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            before = threading.active_count()
            session.close()

        assert threading.active_count() == before

    def test_facade_after_close_raises_stopped_driver(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            page = session.open_context()
            session.close()

            # deadlock guard: once stopped, the facade fails fast instead of waiting
            with pytest.raises(Error, match="Event loop is closed"):
                page.goto("https://example.com")

    def test_reopen_after_close_runs_in_new_worker_thread(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            session.open_context()
            first = session._worker._thread  # this session's thread
            session.close()

            page = session.open_context()
            second = session._worker._thread  # this session's thread
            page.goto("https://example.com")
            session.close()

        assert not first.is_alive()  # the first worker's thread is finished
        assert second is not first  # the thread object is new
        assert not second.is_alive()
        assert factory.start_calls == 2

    def test_failed_driver_start_closes_worker_for_clean_retry(self) -> None:
        factory = FakePlaywrightFactory()
        real_start = factory.start

        def failing_start() -> FakePlaywrightFactory:
            raise RuntimeError("driver start failed")

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium")))
            before = threading.active_count()

            factory.start = failing_start  # type: ignore[method-assign]
            with pytest.raises(RuntimeError, match="driver start failed"):
                session.open_context()

            factory.start = real_start  # type: ignore[method-assign]
            assert threading.active_count() == before  # the failed-launch worker is stopped

            page = session.open_context()  # the retry starts from a clean state
            page.goto("https://example.com")
            session.close()

        assert factory.start_calls == 1  # exactly one successful start
        assert len(factory.contexts) == 1


class TestDriverSessionDialogWiring:
    """Logic tests: the dialog routing wiring of open_context — contract step 4.

    Every page of the context — the open_context page and every later popup —
    carries exactly one dialog handler registered through the context page
    event; the uncaptured dialogs route by the ``accept_dialogs`` setting.
    """

    def test_open_context_registers_dialog_routing(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium", accept_dialogs=False)))
            facade = session.open_context()
            session.close()

        context = factory.contexts[0]
        assert [event for event, _ in context.events] == ["page"]  # exactly one page wiring

        main_page = context.pages[0]
        assert [event for event, _ in main_page.events] == ["dialog"]  # one registration, through the event

        dialog = FakeDialog()
        main_page.dialog_handlers[0](dialog)  # an uncaptured dialog fires on the main page

        assert dialog.calls == [("dismiss",)]  # accept_dialogs False → the explicit dismiss
        assert facade._router is not None  # the router is attached to the returned facade
        assert facade._router.accept_dialogs is False

    @pytest.mark.parametrize(
        ("accept_dialogs", "expected"),
        [(True, ("accept",)), (False, ("dismiss",))],
        ids=["accept", "dismiss"],
    )
    def test_popup_pages_route_dialogs_through_the_context_wiring(self, accept_dialogs: bool, expected: tuple) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium", accept_dialogs=accept_dialogs)))
            session.open_context()
            session.close()

        context = factory.contexts[0]
        popup = context.new_page()  # a popup joins the context — the page wiring fires for it too

        assert [event for event, _ in popup.events] == ["dialog"]  # exactly one handler
        main_handler = context.pages[0].dialog_handlers[0]
        popup_handler = popup.dialog_handlers[0]
        assert popup_handler is not main_handler  # a different closure bound to the popup page

        dialog = FakeDialog()
        popup_handler(dialog)  # an uncaptured dialog fires on the popup

        assert dialog.calls == [expected]  # the setting routes it

    def test_dialog_router_accepts_when_setting_on(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium", accept_dialogs=True)))
            session.open_context()
            session.close()

        dialog = FakeDialog()
        factory.contexts[0].pages[0].dialog_handlers[0](dialog)

        assert dialog.calls == [("accept",)]  # accept called, dismiss not

    def test_dialog_router_skips_only_for_a_capture_on_the_same_page(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser=BrowserConfig(name="chromium", accept_dialogs=False)))
            facade = session.open_context()
            session.close()

        context = factory.contexts[0]
        main_page = context.pages[0]
        popup = context.new_page()
        handler = main_page.dialog_handlers[0]
        router = facade._router
        assert router is not None

        router.capture_page = popup  # a capture armed on the popup — not this handler's page
        routed = FakeDialog()
        handler(routed)
        assert routed.calls == [("dismiss",)]  # the main-page dialog still routes by the setting

        router.capture_page = main_page  # a capture armed on this handler's own page
        claimed = FakeDialog()
        handler(claimed)
        assert claimed.calls == []  # the capture claims it — neither accept nor dismiss
