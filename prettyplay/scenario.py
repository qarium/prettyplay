"""The integrator-facing object: one PrettyTest per test owns the addressing and the page."""

from __future__ import annotations

import types
from pathlib import Path
from types import TracebackType

from .cache import StepCache
from .config import PrettyConfig, load_config
from .driver import PageFacade
from .engine import StepGenerator, StepHealer
from .executor import StepExecutor
from .failures.errors import PrettyplayError
from .reporting import StepHooks, StepReporter
from .runtime import PrettyplayRuntime


def _raise_folded(error: PrettyplayError) -> types.NoReturn:
    """Re-raise a library failure with its traceback folded to this boundary.

    The head link of the caught traceback is the facade method's own frame;
    the folded traceback keeps exactly that link, so the internal library
    frames (engine, healing, provider) never appear in what the runner shows.
    The same exception object is re-raised — never a copy — keeping identity
    for hook consumers and ``except`` clauses, and adding no context nesting.
    The chained exceptions (``__context__``/``__cause__``) keep their identity
    and messages — the original step failure stays visible for debugging —
    but their tracebacks are folded away too: a runner that renders the chain
    shows no internal frames either.

    Args:
        error: the library failure leaving ``action``/``assertion``.

    Raises:
        Always: the given error with the folded traceback attached.
    """
    tb = error.__traceback__
    _fold_chain_tracebacks(error)

    folded = types.TracebackType(
        tb_next=None,
        tb_frame=tb.tb_frame,
        tb_lasti=tb.tb_lasti,
        tb_lineno=tb.tb_lineno,
    )

    raise error.with_traceback(folded)


def _fold_chain_tracebacks(error: BaseException) -> None:
    """Drop the tracebacks of the chained exceptions, keeping the chains themselves.

    Args:
        error: the exception whose ``__context__``/``__cause__`` chains are folded.
    """
    pending = [error]
    seen: set[int] = set()

    while pending:
        current = pending.pop()

        if id(current) in seen:
            continue

        seen.add(id(current))

        for link in (current.__context__, current.__cause__):
            if link is not None:
                link.__traceback__ = None
                pending.append(link)


class PrettyTest:
    """The main object of the integrator: one instance per UI test.

    The test writes its scenario in plain sentences — :meth:`action` and
    :meth:`assertion` — and this object does the rest: addressing of the
    cached steps by the context key, the isolated page of the test, and the
    full step cycle delegated to the executor (in strict replay-only mode:
    cached code only, classification at most). Construction is cheap: the
    page opens lazily on the first step and no LLM credential is needed —
    the runtime provider handed to the executor is a lightweight object,
    its SDK client stays lazy until the first request.
    Every test composes its own runtime here — no process-wide state, no
    state leaks between tests; two tests in one process hold two runtimes,
    two attempt registries and two browser sessions.

    Attributes:
        _runtime: the composition root owned by this one test.
        _reporter: the visibility point of this test.
        _cache: the step cache of this test.
        _generator: the generation engine of this test.
        _healer: the healing engine of this test.
        _executor: the owner of the step cycle of this test.
        _page: the isolated page of this test; ``None`` until the first step.
    """

    def __init__(self, cache_key: str, cache_path: str | None = None, config: PrettyConfig | None = None) -> None:
        """Compose the per-test objects over the runtime this test owns.

        Args:
            cache_key: the context key of the test; the addressing part of
                every cached step of this scenario.
            cache_path: the optional subdirectory inside the cache; part of
                the address, so steps of different subdirectories never
                collide.
            config: the programmatic settings layer; explicitly set values
                win over the pyproject+env file layer, unset and empty
                fields resolve from it. ``None`` resolves everything from
                the file layer, as before.
        """
        effective = load_config(None, config)
        self._runtime = PrettyplayRuntime(effective)
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
            config=self._runtime.config,
            provider=self._runtime.provider,  # cheap object construction; the SDK client stays lazy
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

        A library failure leaving this method carries its traceback folded to
        this boundary: the runner sees the test frame and the boundary frame
        with the rendered message, never the internal engine frames.

        Args:
            text: the sentence of the action as written by the engineer.

        Raises:
            ProductDefectError: the step expectation is genuinely broken in the product.
            IncurableStepError: the step never generated successfully, or the verdict
                says regeneration cannot help.
            LLMUnavailableError: the provider service failed; no retry.
        """
        try:
            self._executor.execute(text, "action", self._ensure_page())
        except PrettyplayError as error:
            _raise_folded(error)

    def assertion(self, text: str) -> None:
        """Execute one assertion step sentence through the step cycle.

        A library failure leaving this method carries its traceback folded to
        this boundary, exactly as :meth:`action` does.

        Args:
            text: the sentence of the assertion as written by the engineer.

        Raises:
            ProductDefectError: the step expectation is genuinely broken in the product.
            IncurableStepError: the step never generated successfully, or the verdict
                says regeneration cannot help.
            LLMUnavailableError: the provider service failed; no retry.
        """
        try:
            self._executor.execute(text, "assertion", self._ensure_page())
        except PrettyplayError as error:
            _raise_folded(error)

    def get_screenshot(self) -> bytes:
        """Return a full-page PNG screenshot of the current test page.

        The decision to take a screenshot belongs to the author: nothing is
        captured automatically on step failures.

        Returns:
            The PNG image bytes of the page.

        Raises:
            PrettyplayError: no test page exists yet — run a step first.
        """
        if self._page is None:
            raise PrettyplayError("no test page yet: run a step first — the page opens lazily on the first step")

        return self._page.screenshot()

    def save_screenshot(self, filepath: str) -> None:
        """Save a full-page PNG screenshot of the current test page to a file.

        Parent directories are not created: nothing is created silently —
        a missing directory is a loud failure.

        Args:
            filepath: the destination path of the PNG file.

        Raises:
            PrettyplayError: no test page exists yet, or the file cannot be
                written; the original ``OSError`` is chained.
        """
        if self._page is None:
            raise PrettyplayError("no test page yet: run a step first — the page opens lazily on the first step")

        image = self._page.screenshot()

        try:
            Path(filepath).write_bytes(image)
        except OSError as error:
            raise PrettyplayError(f"cannot write the screenshot to {filepath}: {error}") from error

    def add_hooks(self, hooks: StepHooks) -> None:
        """Register integrator hooks for the events of this test.

        Args:
            hooks: the hooks object; register before the first step to see
                every event of the scenario.
        """
        self._reporter.hooks.append(hooks)

    def close(self) -> None:
        """Close the page and the whole runtime of this test.

        The isolated page context closes first, then the runtime stops
        unconditionally — a failing page close (e.g. after a browser crash)
        never keeps the browser of the test alive; its error still propagates.
        The browser of this test does not outlive the test.

        Idempotent and safe before the first step: nothing was opened —
        nothing is closed beyond the no-op runtime close. The page reference
        drops before its close runs, so even a failing page close never
        repeats on a retried ``close``.
        """
        page = self._page
        self._page = None

        try:
            if page is not None:
                page.close()
        finally:
            self._runtime.close()

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
        """Leave the scenario block: close the test and never suppress.

        Args:
            exc_type: the type of the block exception, if any.
            exc_value: the block exception, if any.
            traceback: the traceback of the block exception, if any.

        Returns:
            Nothing — a falsy return keeps the exception propagating.
        """
        self.close()
