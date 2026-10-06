"""Lifecycle owner of the Playwright sync driver and the browser process of one test."""

from __future__ import annotations

import difflib
import queue
import re
import threading
from collections.abc import Callable
from typing import TypeVar, cast

from playwright.sync_api import Browser, BrowserContext, Error, Page, Playwright, sync_playwright

from ..config import Config
from .page import PageFacade, _DialogRouter

_T = TypeVar("_T")


class _Task:
    """One unit of work crossing from the caller thread into the driver thread.

    Attributes:
        fn: the callable executed by the worker pump.
        done: set once fn returned or raised in the worker thread.
        result: the return value of fn; ``None`` until done.
        error: the exception fn raised, if any.
    """

    __slots__ = ("done", "error", "fn", "result")

    def __init__(self, fn: Callable[[], object]) -> None:
        """Bind the callable; the outcome slots fill when the pump finishes.

        Args:
            fn: the callable executed by the worker pump.
        """
        self.fn = fn
        self.done = threading.Event()
        self.error: BaseException | None = None
        self.result: object = None


class PlaywrightWorker:
    """The dedicated thread where the Playwright sync session lives — keeping the asyncio marker off the caller thread.

    Attributes:
        _tasks: the queue feeding the pump thread; ``None`` is the stop sentinel.
        _thread: the pump thread; ``None`` before start and after close.
    """

    def __init__(self) -> None:
        """Prepare the task queue; no thread exists yet."""
        self._tasks: queue.SimpleQueue[Callable[[], object] | None] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Spawn the pump thread; it serves queued tasks until close."""
        thread = threading.Thread(target=self._pump, name="prettyplay-playwright", daemon=True)
        thread.start()
        self._thread = thread

    def run(self, fn: Callable[[], _T]) -> _T:
        """Execute one callable in the driver thread and block for its outcome.

        Args:
            fn: the callable to execute; it must touch the Playwright objects
                owned by the worker thread only.

        Returns:
            Whatever ``fn`` returns.

        Raises:
            Error: the worker is not running (stopped or never started) — the
                same message Playwright itself raises on a stopped driver; or
                the call arrives from the worker's own pump thread — code
                running inside a driver-thread unit (a ``run_on_page``
                action, step code) crossed the boundary again, a unit the
                busy pump could never serve; the loud error replaces the
                silent deadlock of both threads.
        """
        if self._thread is None:
            raise Error("Event loop is closed! Is Playwright already stopped?")

        if threading.current_thread() is self._thread:
            raise Error(
                "re-entrant crossing of the driver thread: code running inside a "
                "driver-thread unit called back into the worker — an action inside "
                "run_on_page (or step code) must use the genuine Page directly, "
                "never the prettyplay test object, whose every call marshals into "
                "the same worker and could never be served"
            )

        task = _Task(fn)
        self._tasks.put(task)

        task.done.wait()

        if task.error is not None:
            raise task.error

        return cast(_T, task.result)

    def close(self) -> None:
        """Stop the pump thread and wait for its exit; idempotent."""
        thread = self._thread
        if thread is None:
            return

        self._tasks.put(None)
        thread.join()
        self._thread = None

    def _pump(self) -> None:
        """Serve queued tasks one by one until the stop sentinel arrives."""
        while True:
            task = self._tasks.get()
            if task is None:
                return

            try:
                task.result = task.fn()
            except BaseException as error:  # exception propagates to the caller's thread
                task.error = error
            finally:
                task.done.set()


class DriverSession:
    """Owns the Playwright sync driver and one browser process for one test.

    Attributes:
        _config: project settings; the ``browser`` group selects the engine of
            the matrix, its ``screen`` sets the size mode of every context,
            and its ``endpoint`` switches the start to a remote ws connect.
        _playwright: the started Playwright driver; ``None`` until first start.
        _browser: the connected or launched browser process; ``None`` until first start.
        _worker: the thread owning the Playwright session; ``None`` until first start.
    """

    def __init__(self, config: Config) -> None:
        """Keep the config; nothing is started yet.

        Args:
            config: project settings; the ``browser`` group selects the engine.
        """
        self._config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._worker: PlaywrightWorker | None = None

    def open_context(self) -> PageFacade:
        """Open a fresh isolated context with one page wrapped into the handle.

        Returns:
            The page handle of a fresh isolated context — the driver and the
            browser start lazily on the first call; the dialog router is
            registered before ``new_page()``: every page of the context,
            popups included, registers exactly one handler.

        Raises:
            Error: the ``screen`` value names a device absent from the
                registry of the running Playwright.
        """
        if self._browser is None:
            self._launch()

        worker = self._worker
        browser = self._browser

        def open_isolated() -> tuple[Page, BrowserContext, _DialogRouter]:
            """Open one fresh isolated context with one page in the driver thread.

            Returns:
                The page, its context and the dialog router registered
                before the first page event.
            """
            params = self._screen_context_params()
            context: BrowserContext = browser.new_context(**params)
            router = _DialogRouter(self._config.browser.accept_dialogs)
            # registered before new_page: the first page fires the event and registers once
            context.on("page", lambda opened: opened.on("dialog", router.record))
            page = context.new_page()
            return page, context, router

        page, context, router = worker.run(open_isolated)

        facade = PageFacade(page, context)
        facade._worker = worker  # handle calls marshal into the driver thread
        facade._router = router  # the shared router records every dialog of every page of the context
        return facade

    def _screen_context_params(self) -> dict[str, object]:
        """Resolve the screen setting of the browser group into context parameters.

        Returns:
            The ``new_context`` keyword arguments — resolved inside the
            driver thread against the registry of the running Playwright:
            empty keeps the default, ``fullscreen`` follows the window or
            pins a viewport, a WxH value is a fixed viewport, anything else
            is a device name.

        Raises:
            Error: the value names no device of the running registry; the
                message carries the closest registry names.
        """
        group = self._config.browser
        screen = group.screen

        if screen == "":
            return {}

        if screen == "fullscreen":
            if group.endpoint == "" and not group.headless:
                return {"no_viewport": True}  # the viewport follows the window
            return {"viewport": {"width": 1920, "height": 1080}}  # no window exists there

        match = re.fullmatch(r"(\d+)x(\d+)", screen)
        if match is not None:
            return {"viewport": {"width": int(match.group(1)), "height": int(match.group(2))}}

        devices = self._playwright.devices  # the registry of the running Playwright
        if screen in devices:
            return dict(devices[screen])

        close = difflib.get_close_matches(screen, devices, n=3, cutoff=0.5)
        suggestion = f" — closest names: {', '.join(close)}" if close else ""
        raise Error(f"unknown screen device {screen!r}: not in the playwright device registry{suggestion}")

    def close(self) -> None:
        """Stop the browser, the Playwright driver and the worker; idempotent; a failing close never skips the rest."""
        worker = self._worker
        if worker is None:
            return

        try:
            if self._browser is not None:
                worker.run(self._browser.close)
        finally:
            self._browser = None

            try:
                if self._playwright is not None:
                    worker.run(self._playwright.stop)
            finally:
                self._playwright = None
                worker.close()
                self._worker = None

    def _launch(self) -> None:
        """Start the driver thread, the Playwright session and the browser.

        Raises:
            Exception: whatever the engine start raises — on a launch or
                connect failure the driver is stopped and the worker closed
                before the error propagates, so a retry starts from a clean
                state.
        """
        worker = PlaywrightWorker()
        worker.start()

        try:
            playwright = worker.run(lambda: sync_playwright().start())
        except BaseException:
            worker.close()
            raise

        try:
            browser = worker.run(lambda: self._launch_engine(playwright))
        except BaseException:
            # a browser that failed to start leaves no driver process alive
            worker.run(playwright.stop)
            worker.close()
            raise

        self._worker = worker
        self._playwright = playwright
        self._browser = browser

    def _launch_engine(self, playwright: Playwright) -> Browser:
        """Start the browser engine selected by the browser group of the configuration.

        Args:
            playwright: the started Playwright session of the worker thread.

        Returns:
            The connected or launched browser process — the group ``speed``
            maps to the native ``slow_mo``, fixed at process start and never
            a code wait; a set ``endpoint`` connects instead of launching,
            with ``headless`` ignored; ``chrome``/``msedge`` launch through
            the chromium engine with the matching channel.

        Raises:
            Error: a connect failure — re-raised wrapped with the endpoint,
                chained to the original.
        """
        group = self._config.browser
        name = group.name
        # the pace setting maps linearly to the native slow_mo: 100 -> 0 ms, 0 -> 3000 ms
        slow_mo = int((100 - group.speed) * 30)

        engines: dict[str, object] = {
            "chromium": playwright.chromium,
            "firefox": playwright.firefox,
            "webkit": playwright.webkit,
        }

        if group.endpoint:
            endpoint = group.endpoint
            engine = playwright.chromium if name in ("chrome", "msedge") else engines[name]
            try:
                return cast(Browser, engine.connect(endpoint, slow_mo=slow_mo))
            except Error as failure:
                raise Error(f"cannot connect to the browser endpoint {endpoint}: {failure}") from failure

        channel: str | None
        if name in ("chrome", "msedge"):
            engine = playwright.chromium
            channel = name
        else:
            engine = engines[name]
            channel = None

        launch_kwargs: dict[str, object] = {"headless": group.headless, "slow_mo": slow_mo}
        if channel:
            launch_kwargs["channel"] = channel
        if group.screen == "fullscreen" and name in ("chromium", "chrome", "msedge") and not group.headless:
            # a window exists only on a local headed launch — start it maximized
            launch_kwargs["args"] = ["--start-maximized"]
        return cast(Browser, engine.launch(**launch_kwargs))
