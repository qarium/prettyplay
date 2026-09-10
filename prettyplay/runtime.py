"""Per-test composition root of the library: the objects one test owns.

One :class:`PrettyplayRuntime` serves exactly one test: it composes the
validated settings, the per-test attempt registry, the browser driver and
the LLM provider of that single test. Nothing is shared between tests —
two tests in one process build two runtimes with fresh budgets and
independent browser sessions. The driver and the provider construct
lazily — building the runtime (and any test object on top of it) never
requires LLM credentials and never launches a browser.
"""

from __future__ import annotations

import atexit

from .cache import RunBudgets
from .config import Config
from .driver import DriverSession, PageFacade
from .llm import LLMProvider, create_provider


class PrettyplayRuntime:
    """The composition root: the per-test objects one test composes.

    The config and the attempt registry build eagerly — both are cheap and
    credential-free. The browser driver and the LLM provider construct lazily
    on first access; the provider client itself stays unconstructed until the
    first request, so no LLM key is needed to build the runtime. Every
    instance registers its own close with ``atexit``, so the browser and the
    Playwright driver of the test stop synchronously before the process exits
    even when the test never calls close explicitly. A manual ``close``
    unregisters the hook — a closed runtime never stays pinned for the rest
    of the process — and a driver started after a close re-arms it.

    Attributes:
        _config: validated project settings of the test.
        _budgets: the per-test attempt registry owned by this runtime.
        _driver: the browser driver of the test; ``None`` until first access.
        _provider: the LLM provider of the test; ``None`` until first access.
    """

    def __init__(self, config: Config) -> None:
        """Compose the eager per-test objects from the config.

        Args:
            config: validated project settings of the test.
        """
        self._config = config
        self._budgets = RunBudgets(config.generation_attempts, config.healing_attempts)
        self._driver: DriverSession | None = None
        self._provider: LLMProvider | None = None
        atexit.register(self.close)

    @property
    def config(self) -> Config:
        """The validated settings of the test."""
        return self._config

    @property
    def budgets(self) -> RunBudgets:
        """The per-test attempt registry owned by this one runtime."""
        return self._budgets

    @property
    def driver(self) -> DriverSession:
        """The browser driver of the test, constructed lazily exactly once.

        A construction after a ``close`` re-arms the ``atexit`` hook the
        close dropped: a freshly started browser always has its exit stop.
        """
        if self._driver is None:
            self._driver = DriverSession(self._config)
            atexit.register(self.close)

        return self._driver

    @property
    def provider(self) -> LLMProvider:
        """The LLM provider of the test, constructed lazily exactly once."""
        if self._provider is None:
            self._provider = create_provider(self._config)

        return self._provider

    def open_page(self) -> PageFacade:
        """Open a fresh isolated page of the test driver.

        Returns:
            The facade of the new page of a fresh isolated context.
        """
        return self.driver.open_context()

    def close(self) -> None:
        """Stop the browser driver of the test; safe when nothing was started.

        Idempotent: a call before any driver access and repeated calls are
        no-ops. The call also drops the ``atexit`` hook registered in
        ``__init__`` — a closed runtime and its objects are collectible, not
        pinned until process exit — and a driver started later re-arms the
        hook. The runtime itself stays usable after the call: the next
        driver access constructs a fresh session.
        """
        atexit.unregister(self.close)

        if self._driver is not None:
            self._driver.close()
            self._driver = None
