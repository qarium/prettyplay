"""Per-test composition root of the library: the objects one test owns."""

from __future__ import annotations

import atexit

from .cache import RunBudgets
from .config import Config
from .driver import DriverSession, PageFacade
from .llm import LLMProvider, create_provider


class PrettyplayRuntime:
    """The composition root: the per-test objects one test composes — nothing shared between tests.

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

        Returns:
            The browser driver — a construction after a ``close`` re-arms
            the ``atexit`` hook the close dropped.
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
        """Stop the browser driver of the test; idempotent; drops the ``atexit`` hook."""
        atexit.unregister(self.close)

        if self._driver is not None:
            self._driver.close()
            self._driver = None
