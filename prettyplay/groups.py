"""The authoring group block of the facade: one coherent mini-scenario with a shared goal."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from types import TracebackType
from typing import TYPE_CHECKING

from .failures import PrettyplayError

if TYPE_CHECKING:
    from .driver import PageFacade
    from .engine.groups import GroupStepOutcome
    from .executor import StepExecutor
    from .reporting import StepReporter


def _validate_tries(tries: int | None) -> None:
    """Validate the declared retry count of one step; ``None`` — the global polling settings.

    Args:
        tries: the declared total number of executions of the step's code,
            the first execution included.

    Raises:
        PrettyplayError: the value is a bool, not an integer or below one —
            the loud failure names the parameter, the received value and the
            allowed form; a bad value never reaches the executor.
    """
    if tries is None:
        return

    if isinstance(tries, bool) or not isinstance(tries, int) or tries < 1:
        raise PrettyplayError(
            f"invalid tries {tries!r} — a positive integer, keyword-only "
            "(the total number of executions of the step's code, the first execution included)"
        )


def _validate_delay(delay: float | None) -> None:
    """Validate the declared quiet pause of one step or group; ``None`` — no pause.

    Args:
        delay: the declared pause in seconds — non-negative, fractional
            allowed, bools never coerced.

    Raises:
        PrettyplayError: the value is a bool, not a number, not finite or
            negative — the loud failure names the parameter, the received
            value and the allowed form.
    """
    if delay is None:
        return

    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay < 0:
        raise PrettyplayError(f"invalid delay {delay!r} — a non-negative number of seconds, keyword-only")


def _validate_vars(vars: dict[str, str] | None) -> None:
    """Validate the call-local string inputs of one step; ``None`` — no inputs.

    Args:
        vars: the declared input mapping of the step — every value must be
            a string, bools never coerced; the names reach the template's
            ``vars`` namespace at render time.

    Raises:
        PrettyplayError: the value is not a mapping or some value is not a
            string — the loud failure names the parameter, the received
            value and the allowed form.
    """
    if vars is None:
        return

    if not isinstance(vars, dict):
        raise PrettyplayError(f"invalid vars {vars!r} — a mapping of input names to string values, keyword-only")

    for value in vars.values():
        if not isinstance(value, str):  # a bool is never a string — no coercion
            raise PrettyplayError(f"invalid vars value {value!r} — every value must be a string, keyword-only")


class StepGroup:
    """The authoring group object yielded by :meth:`PrettyPlay.group`: one coherent mini-scenario with a shared goal.

    Attributes:
        _speed: the group pace, 0-100; ``None`` — no between-step pauses;
            the pace pause is a plain library wait, never ``slow_mo``.
        _delay: the quiet pause before the group's first step, seconds;
            ``None`` — no entry pause.
        _executor: the step cycle executor of the owning test — every step
            delegates to it with this group as the context.
        _reporter: the visibility point of the owning test — the group
            lifecycle events dispatch through it.
        _traces: the verbatim trace records of the group's steps, appended
            by the executor once per executed group step.
        _delegated: the internal first-step marker — set immediately before
            a step delegates to the executor, never read from the traces: a
            first step that dies without a trace record must not re-arm the
            entry pause for a later step of the same group.
        _open_page: the owning test's lazy page opener, bound by
            :meth:`PrettyPlay.group`; the declared constructor stays
            five-parameter, the group is only ever constructed there.
    """

    def __init__(
        self,
        prompt: str,
        speed: int | None,
        delay: float | None,
        executor: StepExecutor,
        reporter: StepReporter,
    ) -> None:
        """Keep the group framing, the pace settings and the owning executor and reporter.

        Args:
            prompt: the group prompt, verbatim — reaches generation and
                diagnosis requests and the lifecycle events.
            speed: the group pace, 0-100; ``None`` — no between-step pauses.
            delay: the quiet pause before the group's first step, seconds;
                ``None`` — no pause.
            executor: the step cycle executor of the owning test.
            reporter: the visibility point of the owning test — the group
                lifecycle events dispatch through it.
        """
        self._prompt = prompt
        self._speed = speed
        self._delay = delay
        self._executor = executor
        self._reporter = reporter
        self._traces: list[GroupStepOutcome] = []
        self._delegated = False
        self._open_page: Callable[[], PageFacade] | None = None

    @property
    def prompt(self) -> str:
        """The group prompt, verbatim."""
        return self._prompt

    @property
    def traces(self) -> list[GroupStepOutcome]:
        """The verbatim trace records of the group's steps, in execution order — never rewritten."""
        return self._traces

    def __enter__(self) -> StepGroup:
        """Enter the group block: the on_group_started event with the group prompt verbatim.

        Returns:
            This group object. The entry pause is applied lazily immediately
            before the group's first executed step — a zero-step group is a
            quiet no-op: the lifecycle events and nothing else.
        """
        self._reporter.emit("on_group_started", {"group_prompt": self._prompt})

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the group block: the outcome event, then the closing event; never suppresses.

        Args:
            exc_type: the type of the block exception, if any.
            exc_value: the block exception, if any.
            traceback: the traceback of the block exception, if any.

        Returns:
            Nothing — a falsy return keeps the exception propagating.
            ``on_group_failed`` fires when the block exits through an
            exception, ``on_group_passed`` when it completes without one —
            a healed step counts as success; ``on_group_finished`` closes
            exactly once.
        """
        outcome_event = "on_group_failed" if exc_type is not None else "on_group_passed"

        self._reporter.emit(outcome_event, {"group_prompt": self._prompt})
        self._reporter.emit("on_group_finished", {"group_prompt": self._prompt})

    def step(
        self,
        text: str,
        *,
        tries: int | None = None,
        delay: float | None = None,
        vars: dict[str, str] | None = None,
    ) -> None:
        """Execute the action step ``text`` inside the group.

        Args:
            text: the sentence of the action as written by the engineer.
            tries: keyword-only — the total number of executions of the
                step's code, the first execution included; ``None`` — the
                time-bounded settle mode of the polling settings.
            delay: keyword-only — the quiet pre-step pause in seconds;
                ``None`` — no pause.
            vars: keyword-only — the call-local string inputs of the step;
                every value must be a string. ``None`` — no inputs; a
                separate namespace from memory — ``{{ vars.name }}`` reads
                these values at render time.

        Raises:
            PrettyplayError: ``tries``, ``delay`` or ``vars`` is invalid —
                the loud failure names the parameter, the received value
                and the allowed form; the executor is never reached.
        """
        self._delegate(text, "action", tries, delay, vars)

    def expect(
        self,
        text: str,
        *,
        tries: int | None = None,
        delay: float | None = None,
        vars: dict[str, str] | None = None,
    ) -> None:
        """Execute the assertion step ``text`` inside the group — the same delegation, assertion kind.

        Args:
            text: the sentence of the assertion as written by the engineer.
            tries: keyword-only — the total number of executions of the
                step's code, the first execution included; ``None`` — the
                time-bounded settle mode of the polling settings.
            delay: keyword-only — the quiet pre-step pause in seconds;
                ``None`` — no pause.
            vars: keyword-only — the call-local string inputs of the step;
                every value must be a string. ``None`` — no inputs; a
                separate namespace from memory — ``{{ vars.name }}`` reads
                these values at render time.

        Raises:
            PrettyplayError: ``tries``, ``delay`` or ``vars`` is invalid —
                the loud failure names the parameter, the received value
                and the allowed form; the executor is never reached.
        """
        self._delegate(text, "assertion", tries, delay, vars)

    def _delegate(
        self,
        text: str,
        step_type: str,
        tries: int | None,
        delay: float | None,
        vars: dict[str, str] | None,
    ) -> None:
        """Validate, pause and delegate one group step to the executor.

        Args:
            text: the raw sentence of the step, verbatim.
            step_type: action or assertion.
            tries: the declared retry count of this execution; ``None`` —
                the global polling settings govern the step.
            delay: the declared start pause of this execution; ``None`` —
                no pause.
            vars: the validated call-local string inputs of this
                execution; ``None`` — no inputs.

        Raises:
            PrettyplayError: ``tries``, ``delay`` or ``vars`` is invalid.
        """
        _validate_tries(tries)
        _validate_delay(delay)
        _validate_vars(vars)

        if not self._delegated:
            if self._delay is not None:
                time.sleep(self._delay)  # the lazy entry pause — quiet, library-level
        elif self._speed is not None:
            time.sleep(int((100 - self._speed) * 30) / 1000)  # the between-step pace — never slow_mo

        self._delegated = True
        self._executor.execute(text, step_type, self._open_page(), group=self, tries=tries, delay=delay, vars=vars)
