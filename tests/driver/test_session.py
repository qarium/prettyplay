"""Tests for the DriverSession browser lifecycle of the prettyplay.driver cell."""

import asyncio
import threading
from unittest import mock

import pytest
from playwright.sync_api import Error
from prettyplay.config import Config
from prettyplay.driver import DriverSession, PageFacade


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
        self.contexts: list[FakeContext] = []
        self.threads: list[int] = []  # идентификаторы потока каждого граничного вызова
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
    """Fake Playwright browser engine: records every launch into the factory."""

    def __init__(self, name: str, factory: FakePlaywrightFactory) -> None:
        self.name = name
        self._factory = factory
        self._browser: FakeBrowser | None = None

    def launch(self) -> "FakeBrowser":
        self._factory.threads.append(threading.get_ident())
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
        self._factory.threads.append(threading.get_ident())
        context = FakeContext(self)
        self._factory.contexts.append(context)
        return context

    def close(self) -> None:
        self._factory.threads.append(threading.get_ident())
        self.close_calls += 1


class FakeContext:
    """Fake isolated browser context owning one page."""

    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.page = FakePage(self)
        self.close_calls = 0

    def new_page(self) -> "FakePage":
        self.browser._factory.threads.append(threading.get_ident())
        return self.page

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

    def click(self) -> None:
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

    def test_failed_launch_stops_driver_and_retries_cleanly(self) -> None:
        factory = FakePlaywrightFactory()
        factory.chromium = FailingEngine("chromium", factory, RuntimeError("browser binary missing"))
        session = DriverSession(Config(browser="chromium"))

        with (
            mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory),
            pytest.raises(RuntimeError, match="browser binary missing"),
        ):
            session.open_context()

        assert factory.stop_calls == 1  # драйвер остановлен — процесс не течёт

        factory.chromium = FakeEngine("chromium", factory)  # повторная попытка запускается чисто
        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            page = session.open_context()

        assert factory.start_calls == 2
        assert factory.stop_calls == 1  # лишних стопов нет
        assert isinstance(page, PageFacade)


class FailingEngine:
    """Fake engine whose launch always fails, mimicking a missing browser binary."""

    def __init__(self, name: str, factory: FakePlaywrightFactory, error: Exception) -> None:
        self.name = name
        self._factory = factory
        self._error = error

    def launch(self) -> "FakeBrowser":
        self._factory.threads.append(threading.get_ident())
        self._factory.launches.append(self.name)
        raise self._error


class TestDriverSessionWorkerThread:
    """Behavior tests: the Playwright session lives in a dedicated driver thread.

    Note: several older tests open a context without closing the session, so
    daemon worker threads of previous tests may still linger in the process —
    assertions must target the thread object of THIS session, never the global
    thread enumeration.
    """

    def test_playwright_lifecycle_runs_in_dedicated_thread(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))
            page = session.open_context()
            page.open("https://example.com")
            session.close()

        main_thread = threading.get_ident()
        assert factory.threads, "граничные вызовы обязаны случиться"
        assert all(ident != main_thread for ident in factory.threads)  # ни один — не в главном
        assert len(set(factory.threads)) == 1  # всё в одном выделенном потоке

    def test_facade_calls_execute_in_worker_thread(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))
            page = session.open_context()

            assert page.url == "about:blank"
            page.open("https://example.com")
            page.find_by_role("button", name="Войти").click()
            page.find_by_label("Логин").fill("user")
            page.find_by_text("Добро пожаловать").select_option("one")
            assert page.aria_snapshot() == "- heading Пример"
            assert page.screenshot() == b"png"
            session.close()

        worker_idents = set(factory.threads)
        assert threading.get_ident() not in worker_idents  # вызовы фасада — не в потоке теста
        assert len(worker_idents) == 1

    def test_open_context_leaves_no_running_loop_in_caller_thread(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))
            session.open_context()
            session.close()

        # regression guard for the IPython bug: no running loop may remain in the caller thread
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()

    def test_worker_exception_propagates_with_type_and_message(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))
            page = session.open_context()

            page._page.goto_error = AssertionError("элемент не стабилен")  # type: ignore[attr-defined]

            with pytest.raises(AssertionError, match="элемент не стабилен"):
                page.open("https://example.com")

            session.close()

    def test_close_joins_worker_thread(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))
            session.open_context()
            worker = session._worker._thread  # проверяем поток этой сессии

            assert worker is not None
            assert worker.is_alive()
            session.close()

            assert not worker.is_alive()  # поток воркера завершён

    def test_close_without_launch_keeps_thread_count(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))
            before = threading.active_count()
            session.close()

        assert threading.active_count() == before

    def test_facade_after_close_raises_stopped_driver(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))
            page = session.open_context()
            session.close()

            # deadlock guard: once stopped, the facade fails fast instead of waiting
            with pytest.raises(Error, match="Event loop is closed"):
                page.open("https://example.com")

    def test_reopen_after_close_runs_in_new_worker_thread(self) -> None:
        factory = FakePlaywrightFactory()

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))
            session.open_context()
            first = session._worker._thread  # поток этой сессии
            session.close()

            page = session.open_context()
            second = session._worker._thread  # поток этой сессии
            page.open("https://example.com")
            session.close()

        assert not first.is_alive()  # поток первого воркера завершён
        assert second is not first  # объект потока новый
        assert not second.is_alive()
        assert factory.start_calls == 2

    def test_failed_driver_start_closes_worker_for_clean_retry(self) -> None:
        factory = FakePlaywrightFactory()
        real_start = factory.start

        def failing_start() -> FakePlaywrightFactory:
            raise RuntimeError("driver start failed")

        with mock.patch("prettyplay.driver.session.sync_playwright", return_value=factory):
            session = DriverSession(Config(browser="chromium"))
            before = threading.active_count()

            factory.start = failing_start  # type: ignore[method-assign]
            with pytest.raises(RuntimeError, match="driver start failed"):
                session.open_context()

            factory.start = real_start  # type: ignore[method-assign]
            assert threading.active_count() == before  # воркер неудачного запуска остановлен

            page = session.open_context()  # повтор стартует из чистого состояния
            page.open("https://example.com")
            session.close()

        assert factory.start_calls == 1  # успешный старт ровно один
        assert len(factory.contexts) == 1
