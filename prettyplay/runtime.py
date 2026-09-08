"""Run-scoped composition root of the library: everything shared by the tests of the run.

One :class:`PrettyplayRuntime` per process composes the objects no single test
owns: validated settings, the per-run attempt registry, the browser driver and
the LLM provider. Nothing here is per-test state. The driver and the provider
construct lazily — building the runtime (and any test object on top of it)
never requires LLM credentials and never launches a browser.
"""

from __future__ import annotations

from .cache import RunBudgets
from .config import Config, load_config
from .driver import DriverSession, PageFacade
from .llm import LlmProvider, create_provider

_runtime: PrettyplayRuntime | None = None


def get_runtime() -> PrettyplayRuntime:
    """Return the process-wide runtime, constructing it on the first call.

    The runtime is a process singleton: every subsequent call is cheap and
    returns the same object.

    Returns:
        The single runtime of the process.
    """
    global _runtime  # noqa: PLW0603 — the process singleton is a module global by contract
    if _runtime is None:
        _runtime = PrettyplayRuntime(load_config(None))
    return _runtime


class PrettyplayRuntime:
    """The composition root: run-scoped objects composed once per process.

    The config and the attempt registry build eagerly — both are cheap and
    credential-free. The browser driver and the LLM provider construct lazily
    on first access; the provider client itself stays unconstructed until the
    first request, so no LLM key is needed to build the runtime.

    Attributes:
        _config: validated project settings of the run.
        _budgets: the per-run attempt registry shared by every test.
        _driver: the browser driver of the run; ``None`` until first access.
        _provider: the LLM provider of the run; ``None`` until first access.
    """

    def __init__(self, config: Config) -> None:
        """Compose the eager run-scoped objects from the config.

        Args:
            config: validated project settings of the run.
        """
        self._config = config
        self._budgets = RunBudgets(config.generation_attempts, config.healing_attempts)
        self._driver: DriverSession | None = None
        self._provider: LlmProvider | None = None

    @property
    def config(self) -> Config:
        """The validated settings of the run."""
        return self._config

    @property
    def budgets(self) -> RunBudgets:
        """The per-run attempt registry shared by every test of the process."""
        return self._budgets

    @property
    def driver(self) -> DriverSession:
        """The browser driver of the run, constructed lazily exactly once."""
        if self._driver is None:
            self._driver = DriverSession(self._config)
        return self._driver

    @property
    def provider(self) -> LlmProvider:
        """The LLM provider of the run, constructed lazily exactly once."""
        if self._provider is None:
            self._provider = create_provider(self._config)
        return self._provider

    def open_page(self) -> PageFacade:
        """Open a fresh isolated page of the run driver.

        Returns:
            The facade of the new page of a fresh isolated context.
        """
        return self.driver.open_context()

    def close(self) -> None:
        """Stop the browser driver of the run; safe when nothing was started.

        Idempotent: a call before any driver access and repeated calls are
        no-ops. The runtime itself stays usable after the call.
        """
        if self._driver is not None:
            self._driver.close()
