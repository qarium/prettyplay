"""Tests for the DriverSession browser lifecycle of the prettyplay.driver cell."""

from unittest import mock

from prettyplay.config import Config
from prettyplay.driver import DriverSession, PageFacade


class FakePlaywrightFactory:
    """Fake ``sync_playwright`` boundary: records launches, contexts and the driver stop.

    Mimics the real shape: ``sync_playwright()`` returns a context manager whose
    ``start()`` yields the driver; the driver holds the engine matrix, every
    ``launch()`` returns the one browser process of the run.
    """

    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.launches: list[str] = []
        self.contexts: list[FakeContext] = []
        self.chromium = FakeEngine("chromium", self)
        self.firefox = FakeEngine("firefox", self)
        self.webkit = FakeEngine("webkit", self)

    def __call__(self) -> "FakePlaywrightFactory":
        return self

    def start(self) -> "FakePlaywrightFactory":
        self.start_calls += 1
        return self

    def stop(self) -> None:
        self.stop_calls += 1


class FakeEngine:
    """Fake Playwright browser engine: records every launch into the factory."""

    def __init__(self, name: str, factory: FakePlaywrightFactory) -> None:
        self.name = name
        self._factory = factory
        self._browser: FakeBrowser | None = None

    def launch(self) -> "FakeBrowser":
        self._factory.launches.append(self.name)

        if self._browser is None:
            self._browser = FakeBrowser(self._factory)

        return self._browser


class FakeBrowser:
    """Fake launched browser process shared by the whole run."""

    def __init__(self, factory: FakePlaywrightFactory) -> None:
        self._factory = factory
        self.close_calls = 0

    def new_context(self) -> "FakeContext":
        context = FakeContext(self)
        self._factory.contexts.append(context)
        return context

    def close(self) -> None:
        self.close_calls += 1


class FakeContext:
    """Fake isolated browser context owning one page."""

    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.page = FakePage(self)
        self.close_calls = 0

    def new_page(self) -> "FakePage":
        return self.page

    def close(self) -> None:
        self.close_calls += 1


class FakePage:
    """Fake Playwright page object hidden behind the facade."""

    def __init__(self, context: FakeContext) -> None:
        self.context = context


class TestDriverSessionContract:
    """Contract tests: facade import, construction shape, lazy open, safe close."""

    def test_driver_session_importable_from_facade(self) -> None:
        assert isinstance(DriverSession, type)

    def test_constructor_takes_config_and_starts_nothing(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            DriverSession(Config(browser="chromium"))

        assert factory.start_calls == 0
        assert factory.launches == []

    def test_open_context_returns_page_facade(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))
            page = session.open_context()

        assert isinstance(page, PageFacade)

    def test_close_without_launch_is_noop(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))
            session.close()

        assert factory.start_calls == 0
        assert factory.stop_calls == 0

    def test_public_surface_matches_contract(self) -> None:
        session = DriverSession(Config())

        assert hasattr(session, "open_context")
        assert hasattr(session, "close")


class TestDriverSessionLogic:
    """Logic tests: single lazy launch, per-call isolated contexts, idempotent close."""

    def test_open_context_lazy_launch_single_browser(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))

            assert factory.start_calls == 0  # после конструктора: pw.start не вызывался

            page1 = session.open_context()
            page2 = session.open_context()

        assert factory.start_calls == 1
        assert factory.launches == ["chromium"]  # launches == 1
        assert page1 is not page2  # два результата — разные PageFacade
        assert len(factory.contexts) == 2  # контекстов создано 2

    def test_open_context_selects_engine_from_config(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="firefox"))
            session.open_context()

        assert factory.launches == ["firefox"]

    def test_close_stops_browser_and_driver(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="webkit"))
            session.open_context()
            session.close()

        assert factory.launches == ["webkit"]
        assert factory.contexts[0].browser.close_calls == 1
        assert factory.stop_calls == 1

    def test_close_is_idempotent(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))
            session.open_context()
            session.close()
            session.close()  # повторный close — no-op

        browser = factory.contexts[0].browser
        assert browser.close_calls == 1
        assert factory.stop_calls == 1

    def test_close_before_launch_is_noop(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))
            session.close()  # close() до запуска — no-op

        assert factory.start_calls == 0
        assert factory.stop_calls == 0

    def test_contexts_after_close_are_still_isolated(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))
            session.open_context()
            session.close()
            page = session.open_context()  # новый запуск после закрытия

        assert factory.start_calls == 2
        assert len(factory.launches) == 2
        assert isinstance(page, PageFacade)
