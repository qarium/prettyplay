"""The integrator-facing object: one PrettyPlay per test owns the addressing and the page."""

from __future__ import annotations

import types
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import TypeVar

from playwright.sync_api import Page

from .cache import StepCache
from .config import PrettyConfig, load_config
from .driver import PageFacade
from .engine import StepGenerator, StepHealer
from .engine.groups import GroupRecovery
from .engine.steering import StepSteering
from .executor import StepExecutor
from .failures import PrettyplayError
from .groups import StepGroup, _validate_delay, _validate_tries
from .reporting import StepHooks, StepReporter
from .runtime import PrettyplayRuntime

_T = TypeVar("_T")

#: The inclusive pace range, in percent, a group's ``speed`` parameter accepts.
_SPEED_RANGE = range(0, 101)


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
        error: the library failure leaving ``step``/``expect``.

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


def _validate_group_speed(speed: int | None) -> None:
    """Validate the declared group pace; ``None`` — no between-step pauses.

    The group-level twin of the browser ``speed`` setting: an integer
    0-100 inclusive, bools never coerced. The loud failure names the
    parameter, the received value and the allowed form.

    Args:
        speed: the group pace — an integer 0-100 inclusive.

    Raises:
        PrettyplayError: the value is a bool, not an integer or outside 0-100.
    """
    if speed is None:
        return

    if isinstance(speed, bool) or not isinstance(speed, int) or speed not in _SPEED_RANGE:
        raise PrettyplayError(f"invalid speed {speed!r} — an integer 0-100 inclusive, keyword-only")


class PrettyPlay:
    """The main object of the integrator: one instance per UI test.

    The test writes its scenario in plain sentences — :meth:`step` and
    :meth:`expect`, framed into coherent mini-scenarios by :meth:`group` —
    and this object does the rest: addressing of the
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
        _steering: the interactive steering of this test; shares the
            provider, the cache and the reporter of the healer — one
            visibility point and one write-back store per test.
        _recovery: the group recovery engine of this test; shares the
            provider, the cache, the budgets and the reporter of the
            generator — the recovery row regenerates through it.
        _executor: the owner of the step cycle of this test.
        _page: the isolated page of this test; ``None`` until the first step.
    """

    def __init__(
        self,
        cache_key: str,
        cache_path: str | None = None,
        *,
        hooks: list[StepHooks] | None = None,
        config: PrettyConfig | None = None,
    ) -> None:
        """Compose the per-test objects over the runtime this test owns.

        Args:
            cache_key: the context key of the test; the addressing part of
                every cached step of this scenario.
            cache_path: the optional subdirectory inside the cache; part of
                the address, so steps of different subdirectories never
                collide.
            hooks: the optional integrator callbacks of this test,
                keyword-only; the reporter is seeded with them at
                construction, so every event of every step reaches them.
                ``None`` — an empty hooks list; :meth:`add_hooks` appends
                later.
            config: the programmatic settings layer; explicitly set values
                win over the pyproject+env file layer, unset and empty
                fields resolve from it. ``None`` resolves everything from
                the file layer, as before.
        """
        effective = load_config(None, config)
        self._runtime = PrettyplayRuntime(effective)
        self._reporter = StepReporter(hooks=hooks or [])
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
        self._steering = StepSteering(
            self._runtime.config,
            self._runtime.provider,
            self._cache,
            self._reporter,
        )
        self._recovery = GroupRecovery(
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
            self._steering,
            self._recovery,
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

    def step(self, text: str, *, tries: int | None = None, delay: float | None = None) -> None:
        """Execute one action step sentence through the step cycle.

        A library failure leaving this method carries its traceback folded to
        this boundary: the runner sees the test frame and the boundary frame
        with the rendered message, never the internal engine frames.

        Args:
            text: the sentence of the action as written by the engineer.
            tries: keyword-only — the total number of executions of the
                step's code, the first execution included; a positive
                integer. ``None`` — the time-bounded settle mode of the
                polling settings. An invalid value raises the loud
                actionable failure at the call, before any page or LLM
                involvement.
            delay: keyword-only — the quiet pre-step pause in seconds,
                non-negative, fractional allowed; ``None`` — no pause.

        Raises:
            PrettyplayError: ``tries`` or ``delay`` is invalid — the loud
                failure names the parameter, the received value and the
                allowed form.
            ProductDefectError: the step expectation is genuinely broken in the product.
            IncurableStepError: the step never generated successfully, or the verdict
                says regeneration cannot help.
            LLMUnavailableError: the provider service failed; no retry.
            ComplianceVerdictError: the compliance gate could not obtain a
                usable verdict; the executed candidate is never cached.
        """
        try:
            _validate_tries(tries)
            _validate_delay(delay)
            self._executor.execute(text, "action", self._ensure_page(), tries=tries, delay=delay)
        except PrettyplayError as error:
            _raise_folded(error)

    def expect(self, text: str, *, tries: int | None = None, delay: float | None = None) -> None:
        """Execute one assertion step sentence through the step cycle.

        A library failure leaving this method carries its traceback folded to
        this boundary, exactly as :meth:`step` does.

        Args:
            text: the sentence of the assertion as written by the engineer.
            tries: keyword-only — the total number of executions of the
                step's code, the first execution included; a positive
                integer. ``None`` — the time-bounded settle mode of the
                polling settings. An invalid value raises the loud
                actionable failure at the call, before any page or LLM
                involvement.
            delay: keyword-only — the quiet pre-step pause in seconds,
                non-negative, fractional allowed; ``None`` — no pause.

        Raises:
            PrettyplayError: ``tries`` or ``delay`` is invalid — the loud
                failure names the parameter, the received value and the
                allowed form.
            ProductDefectError: the step expectation is genuinely broken in the product.
            IncurableStepError: the step never generated successfully, or the verdict
                says regeneration cannot help.
            LLMUnavailableError: the provider service failed; no retry.
            ComplianceVerdictError: the compliance gate could not obtain a
                usable verdict; the executed candidate is never cached.
        """
        try:
            _validate_tries(tries)
            _validate_delay(delay)
            self._executor.execute(text, "assertion", self._ensure_page(), tries=tries, delay=delay)
        except PrettyplayError as error:
            _raise_folded(error)

    def group(self, prompt: str, *, speed: int | None = None, delay: float | None = None) -> StepGroup:
        """Open the group authoring block — one coherent mini-scenario with a shared goal.

        The returned group object carries the ordinary step surface —
        ``step``/``expect`` with the ``tries``/``delay`` parameters — and
        used as a context manager it frames the block with one INFO record
        on entry and one on exit. There is no ambient rerouting of this test
        object: steps outside the block are ordinary steps, and group
        membership changes no step's cache address.

        Args:
            prompt: the group prompt, verbatim — the shared goal of the
                block, reaching the generation and diagnosis requests;
                empty raises the loud actionable failure at entry.
            speed: keyword-only — the group pace, an integer 0-100; the
                pauses between the group's steps follow the same
                percent-to-ms mapping as the browser speed setting.
                ``None`` — no between-step pauses.
            delay: keyword-only — the quiet pause before the group's first
                step, seconds, non-negative; ``None`` — no pause.

        Returns:
            The authoring group object — yield it from a ``with`` block.

        Raises:
            PrettyplayError: ``prompt`` is empty, ``speed`` is malformed or
                outside 0-100, or ``delay`` is negative or malformed.
        """
        try:
            if not prompt:
                raise PrettyplayError(
                    "the group prompt must not be empty — a group block needs its shared goal sentence"
                )

            _validate_group_speed(speed)
            _validate_delay(delay)

            block = StepGroup(prompt, speed, delay, self._executor)
            block._open_page = self._ensure_page  # the lazy opener of this test; the constructor stays four-parameter

            return block
        except PrettyplayError as error:
            _raise_folded(error)

    def run_on_page(self, action: Callable[[Page], _T]) -> _T:
        """Execute the author action wholly inside the driver worker thread.

        The author escape hatch: the action runs against the genuine sync
        ``Page`` of the test, sequentially with every step — the stateful
        actions excluded from generated code (``page.route``, ``page.clock``,
        ``add_init_script``, tracing, HAR, CDP) are the author's explicit
        tools here. The prompt rules of generated code do not bind the author.
        The action must use the page API only: calling back into the test
        object (a step, a screenshot, a nested ``run_on_page``) marshals into
        the same worker thread the action itself runs on and is rejected with
        a loud error instead of a deadlock.

        Args:
            action: the callable to execute; receives the genuine sync Page.

        Returns:
            The outcome of ``action`` as-is — plain data only; Playwright
            objects never cross back to the calling thread.

        Raises:
            PrettyplayError: no test page exists yet — run a step first.
            Exception: whatever ``action`` raises propagates to the caller
                as-is — the same object, no wrapping, no folding.
        """
        if self._page is None:
            raise PrettyplayError("no test page yet: run a step first — the page opens lazily on the first step")

        return self._page.run(action)

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

    def __enter__(self) -> PrettyPlay:
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
