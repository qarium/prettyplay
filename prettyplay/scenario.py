"""The integrator-facing object: one PrettyTest per test owns the addressing and the page."""

from __future__ import annotations

from types import TracebackType

from .cache import StepCache
from .driver import PageFacade
from .engine import StepGenerator, StepHealer
from .executor import StepExecutor
from .reporting import StepHooks, StepReporter
from .runtime import get_runtime


class PrettyTest:
    """The main object of the integrator: one instance per UI test.

    The test writes its scenario in plain sentences — :meth:`action` and
    :meth:`assertion` — and this object does the rest: addressing of the
    cached steps by the context key, the isolated page of the test, and the
    full step cycle delegated to the executor. Construction is cheap: the
    page opens lazily on the first step and no LLM credential is needed.
    Per-test objects compose here over the process-wide runtime; no state
    leaks between tests.

    Attributes:
        _runtime: the process-wide composition root.
        _reporter: the visibility point of this test.
        _cache: the step cache of this test.
        _generator: the generation engine of this test.
        _healer: the healing engine of this test.
        _executor: the owner of the step cycle of this test.
        _page: the isolated page of this test; ``None`` until the first step.
    """

    def __init__(self, cache_key: str, cache_path: str | None = None) -> None:
        """Compose the per-test objects over the process-wide runtime.

        Args:
            cache_key: the context key of the test; the addressing part of
                every cached step of this scenario.
            cache_path: the optional subdirectory inside the cache; part of
                the address, so steps of different subdirectories never
                collide.
        """
        self._runtime = get_runtime()
        self._reporter = StepReporter(hooks=[])
        self._cache = StepCache(self._runtime.config, cache_path, self._reporter)
        self._generator = StepGenerator(
            self._runtime.config,
            self._runtime.provider,
            self._cache,
            self._runtime.budgets,
            self._reporter,
        )
        self._healer = StepHealer(
            self._runtime.config,
            self._runtime.provider,
            self._generator,
            self._cache,
            self._runtime.budgets,
            self._reporter,
        )
        self._executor = StepExecutor(
            cache_key,
            self._cache,
            self._generator,
            self._healer,
            self._runtime.budgets,
            self._reporter,
        )
        self._page: PageFacade | None = None

    @property
    def cache_key(self) -> str:
        """The context key of this test, for diagnostics."""
        return self._executor.cache_key

    def _ensure_page(self) -> PageFacade:
        """Open the isolated page of this test lazily, exactly once.

        Returns:
            The page facade of this test.
        """
        if self._page is None:
            self._page = self._runtime.open_page()
        return self._page

    def action(self, text: str) -> None:
        """Execute one action step sentence through the step cycle.

        Args:
            text: the sentence of the action as written by the engineer.
        """
        self._executor.execute(text, "action", self._ensure_page())

    def assertion(self, text: str) -> None:
        """Execute one assertion step sentence through the step cycle.

        Args:
            text: the sentence of the assertion as written by the engineer.
        """
        self._executor.execute(text, "assertion", self._ensure_page())

    def add_hooks(self, hooks: StepHooks) -> None:
        """Register integrator hooks for the events of this test.

        Args:
            hooks: the hooks object; register before the first step to see
                every event of the scenario.
        """
        self._reporter.hooks.append(hooks)

    def close(self) -> None:
        """Close the page of this test; the browser of the run stays alive.

        Idempotent and safe before the first step: nothing was opened —
        nothing is closed.
        """
        if self._page:
            self._page.close()
            self._page = None

    def __enter__(self) -> PrettyTest:
        """Enter the scenario block of one test.

        Returns:
            This test object.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the scenario block: close the page and never suppress.

        Args:
            exc_type: the type of the block exception, if any.
            exc_value: the block exception, if any.
            traceback: the traceback of the block exception, if any.

        Returns:
            Nothing — a falsy return keeps the exception propagating.
        """
        self.close()
