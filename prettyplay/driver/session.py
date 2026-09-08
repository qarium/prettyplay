"""Lifecycle owner of the Playwright sync driver and the browser process of the run."""

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from ..config import Config
from .page import PageFacade


class DriverSession:
    """Owns the Playwright sync driver and one browser process for the whole run.

    The constructor starts nothing: the driver and the browser launch lazily on
    the first :meth:`open_context` call and then serve every test of the run.
    Every call opens a fresh isolated browser context wrapped into a
    :class:`PageFacade` — no state is shared between tests through the library.

    Attributes:
        _config: project settings; ``browser`` selects the engine of the matrix.
        _playwright: the started Playwright driver; ``None`` until first launch.
        _browser: the launched browser process; ``None`` until first launch.
    """

    def __init__(self, config: Config) -> None:
        """Keep the config; nothing is started yet.

        Args:
            config: project settings; the browser setting selects the engine.
        """
        self._config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def open_context(self) -> PageFacade:
        """Open a fresh isolated context with one page wrapped into the facade.

        The driver and the browser launch lazily on the first call exactly once
        per run; each subsequent call only creates a new isolated context.

        Returns:
            The facade of the new page of a fresh isolated context.
        """
        if self._browser is None:
            self._playwright = sync_playwright().start()

            engines: dict[str, object] = {
                "chromium": self._playwright.chromium,
                "firefox": self._playwright.firefox,
                "webkit": self._playwright.webkit,
            }
            engine = engines[self._config.browser]
            self._browser = engine.launch()

        context: BrowserContext = self._browser.new_context()
        page: Page = context.new_page()

        return PageFacade(page, context)

    def close(self) -> None:
        """Stop the browser and the Playwright driver; safe when nothing was started.

        Idempotent: repeated calls and a call before any launch are no-ops.
        """
        if self._browser is not None:
            self._browser.close()
            self._browser = None

        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
