"""The integrator-facing object: one PrettyPlay per test owns the addressing and the page."""

from __future__ import annotations

import re
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
from .groups import StepGroup, _validate_delay, _validate_tries, _validate_vars
from .reporting import StepHooks, StepReporter
from .runtime import PrettyplayRuntime

_T = TypeVar("_T")

#: The inclusive pace range, in percent, a group's ``speed`` parameter accepts.
_SPEED_RANGE = range(0, 101)

#: The header of the bulky page-state section Playwright appends to a failed
#: expectation message — column zero; the section runs to the message end.
_ARIA_SNAPSHOT_HEADER = re.compile(r"^Aria snapshot:[ \t]*$", re.MULTILINE)


def _trim_aria_snapshot(error: BaseException) -> None:
    """Trim the bulky aria-snapshot section from a chained exception's message.

    Args:
        error: the chained exception; a single-string message carrying the
            page-state section loses it, every other argument shape stays
            untouched.
    """
    if len(error.args) != 1 or not isinstance(error.args[0], str):
        return

    text = error.args[0]
    header = _ARIA_SNAPSHOT_HEADER.search(text)

    if header is not None:
        error.args = (text[: header.start()].rstrip(),)


def _raise_folded(error: PrettyplayError) -> types.NoReturn:
    """Re-raise a library failure with its traceback folded to this boundary.

    Args:
        error: the library failure leaving ``step``/``expect``.

    Raises:
        Always: the given error with the folded traceback attached — the
        same object, never a copy; only the facade boundary frame stays,
        the chained tracebacks fold away too.
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
        error: the exception whose ``__context__``/``__cause__`` chains are
            folded — every chained single-string message also loses its
            bulky aria-snapshot section, so the page state never floods
            the runner output.
    """
    pending = [error]
    seen: set[int] = set()

    while pending:
        current = pending.pop()

        if id(current) in seen:
            continue

        seen.add(id(current))
        _trim_aria_snapshot(current)

        for link in (current.__context__, current.__cause__):
            if link is not None:
                link.__traceback__ = None
                pending.append(link)


def _validate_group_speed(speed: int | None) -> None:
    """Validate the declared group pace; ``None`` — no between-step pauses.

    Args:
        speed: the group pace — an integer 0-100 inclusive, bools never
            coerced.

    Raises:
        PrettyplayError: the value is a bool, not an integer or outside
            0-100 — the loud failure names the parameter, the received
            value and the allowed form.
    """
    if speed is None:
        return

    if isinstance(speed, bool) or not isinstance(speed, int) or speed not in _SPEED_RANGE:
        raise PrettyplayError(f"invalid speed {speed!r} — an integer 0-100 inclusive, keyword-only")


class PrettyPlay:
    """The main object of the integrator: one instance per UI test.

    Attributes:
        _runtime: the composition root owned by this one test — no
            process-wide state: two tests hold two runtimes, two attempt
            registries and two browser sessions.
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
        """Compose the per-test objects over the runtime this test owns; the page and the SDK client stay lazy.

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

    def step(
        self,
        text: str,
        *,
        tries: int | None = None,
        delay: float | None = None,
        vars: dict[str, str] | None = None,
    ) -> None:
        """Execute one action step sentence through the step cycle.

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
            vars: keyword-only — the call-local string inputs of the step;
                every value must be a string, otherwise the loud actionable
                failure names the parameter, the received value and the
                allowed form. ``None`` — no inputs; a separate namespace
                from memory — ``{{ vars.name }}`` reads these values,
                ``{{ name }}`` reads memory; call inputs never establish
                memory.

        Raises:
            PrettyplayError: ``tries``, ``delay`` or ``vars`` is invalid —
                the loud failure names the parameter, the received value
                and the allowed form; every library failure leaving this
                method carries its traceback folded to this boundary.
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
            _validate_vars(vars)
            self._executor.execute(text, "action", self._ensure_page(), tries=tries, delay=delay, vars=vars)
        except PrettyplayError as error:
            _raise_folded(error)

    def expect(
        self,
        text: str,
        *,
        tries: int | None = None,
        delay: float | None = None,
        vars: dict[str, str] | None = None,
    ) -> None:
        """Execute one assertion step sentence through the step cycle.

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
            vars: keyword-only — the call-local string inputs of the step,
                validated exactly as :meth:`step`; ``None`` — no inputs.

        Raises:
            PrettyplayError: ``tries``, ``delay`` or ``vars`` is invalid;
                the traceback folding is exactly as :meth:`step`.
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
            _validate_vars(vars)
            self._executor.execute(text, "assertion", self._ensure_page(), tries=tries, delay=delay, vars=vars)
        except PrettyplayError as error:
            _raise_folded(error)

    def group(self, prompt: str, *, speed: int | None = None, delay: float | None = None) -> StepGroup:
        """Open the group authoring block — one coherent mini-scenario with a shared goal.

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
            The authoring group object — yield it from a ``with`` block: it
            carries the ordinary step surface and frames the block with the
            group lifecycle events; group membership changes no step's cache
            address.

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

            block = StepGroup(prompt, speed, delay, self._executor, self._reporter)
            block._open_page = self._ensure_page  # the lazy opener of this test; the constructor stays five-parameter

            return block
        except PrettyplayError as error:
            _raise_folded(error)

    def run_on_page(self, action: Callable[[Page], _T]) -> _T:
        """Execute the author action wholly inside the driver worker thread.

        Args:
            action: the callable to execute; receives the genuine sync Page,
                runs sequentially with every step — the stateful actions
                excluded from generated code are the author's explicit tools
                here.

        Returns:
            The outcome of ``action`` as-is — plain data only; Playwright
            objects never cross back to the calling thread.

        Raises:
            PrettyplayError: no test page exists yet — run a step first.
            Exception: whatever ``action`` raises propagates to the caller
                as-is; a call back into the test object from inside the
                action is rejected with a loud error instead of a deadlock.
        """
        if self._page is None:
            raise PrettyplayError("no test page yet: run a step first — the page opens lazily on the first step")

        return self._page.run(action)

    def get_screenshot(self) -> bytes:
        """Return a full-page PNG screenshot of the current test page.

        Returns:
            The PNG image bytes of the page — the decision to capture
            belongs to the author: nothing is captured automatically on
            step failures.

        Raises:
            PrettyplayError: no test page exists yet — run a step first.
        """
        if self._page is None:
            raise PrettyplayError("no test page yet: run a step first — the page opens lazily on the first step")

        return self._page.screenshot()

    def save_screenshot(self, filepath: str) -> None:
        """Save a full-page PNG screenshot of the current test page to a file.

        Args:
            filepath: the destination path of the PNG file.

        Raises:
            PrettyplayError: no test page exists yet, or the file cannot be
                written — parent directories are never created silently, a
                missing directory is a loud failure; the original
                ``OSError`` is chained.
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
        """Close the page, then unconditionally the whole runtime of this test; idempotent."""
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
