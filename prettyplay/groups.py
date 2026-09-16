"""The authoring group block of the facade: one coherent mini-scenario with a shared goal."""

from __future__ import annotations

import logging
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

logger = logging.getLogger("prettyplay")


def _validate_tries(tries: int | None) -> None:
    """Validate the declared retry count of one step; ``None`` — the global polling settings.

    The shared validator of the authoring surface: the facade step methods
    and the group step methods validate identically. The loud failure names
    the parameter, the received value and the allowed form — a bad value
    never reaches the executor.

    Args:
        tries: the declared total number of executions of the step's code,
            the first execution included.

    Raises:
        PrettyplayError: the value is a bool, not an integer or below one.
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

    The shared validator of the authoring surface: steps declare their start
    pause in seconds, groups their entry pause — non-negative, fractional
    allowed, bools never coerced. The loud failure names the parameter, the
    received value and the allowed form.

    Args:
        delay: the declared pause in seconds.

    Raises:
        PrettyplayError: the value is a bool, not a number, not finite or negative.
    """
    if delay is None:
        return

    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay < 0:
        raise PrettyplayError(f"invalid delay {delay!r} — a non-negative number of seconds, keyword-only")


class StepGroup:
    """The authoring group object: one coherent mini-scenario with a shared goal.

    Yielded by :meth:`PrettyPlay.group` — never constructed by the integrator.
    Every step delegated inside the block executes with this group as its
    context: the generation requests carry the group prompt as the framing
    input, the internal classification points are suppressed and a failed
    step routes to the group recovery instead of the per-step heal — that
    routing belongs to the executor; this object owns the authoring surface,
    the pauses and the traces. The pauses are plain library-level waits —
    never ``slow_mo``, which is fixed at browser start and cannot change
    mid-run.

    Attributes:
        _speed: the group pace, 0-100; ``None`` — no between-step pauses.
        _delay: the quiet pause before the group's first step, seconds;
            ``None`` — no entry pause.
        _executor: the step cycle executor of the owning test — every step
            delegates to it with this group as the context.
        _traces: the verbatim trace records of the group's steps, appended
            by the executor once per executed group step.
        _delegated: the internal first-step marker — set immediately before
            a step delegates to the executor, never read from the traces: a
            first step that dies without a trace record must not re-arm the
            entry pause for a later step of the same group.
        _open_page: the owning test's lazy page opener, bound by
            :meth:`PrettyPlay.group`; the declared constructor stays
            four-parameter, the group is only ever constructed there.
    """

    def __init__(self, prompt: str, speed: int | None, delay: float | None, executor: StepExecutor) -> None:
        """Keep the group framing, the pace settings and the owning executor.

        Args:
            prompt: the group prompt, verbatim — reaches generation and
                diagnosis requests and the framing log records.
            speed: the group pace, 0-100; ``None`` — no between-step pauses.
            delay: the quiet pause before the group's first step, seconds;
                ``None`` — no pause.
            executor: the step cycle executor of the owning test.
        """
        self._prompt = prompt
        self._speed = speed
        self._delay = delay
        self._executor = executor
        self._traces: list[GroupStepOutcome] = []
        self._delegated = False
        self._open_page: Callable[[], PageFacade] | None = None

    @property
    def prompt(self) -> str:
        """The group prompt, verbatim."""
        return self._prompt

    @property
    def traces(self) -> list[GroupStepOutcome]:
        """The verbatim trace records of the group's steps, in execution order.

        One record per executed group step, appended by the executor — the
        input the executor passes to the group recovery; a record is never
        rewritten afterwards.
        """
        return self._traces

    def __enter__(self) -> StepGroup:
        """Enter the group block: one INFO framing record with the group prompt verbatim.

        The entry pause is not slept here — it is applied lazily immediately
        before the group's first executed step, so a zero-step group is a
        quiet no-op: the framing records and nothing else.

        Returns:
            This group object.
        """
        logger.info("group_started", extra={"group": self._prompt})

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the group block: one INFO framing record; never suppresses.

        The closing record is unconditional once entry logged — it also
        lands on the exception path of the block.

        Args:
            exc_type: the type of the block exception, if any.
            exc_value: the block exception, if any.
            traceback: the traceback of the block exception, if any.

        Returns:
            Nothing — a falsy return keeps the exception propagating.
        """
        logger.info("group_finished", extra={"group": self._prompt})

    def step(self, text: str, *, tries: int | None = None, delay: float | None = None) -> None:
        """Execute the action step ``text`` inside the group.

        Validates like the facade methods — the shared validators — then
        applies the group's pauses and delegates to the executor with this
        group as the context; the trace recording and the failure routing
        belong to the executor.

        Args:
            text: the sentence of the action as written by the engineer.
            tries: keyword-only — the total number of executions of the
                step's code, the first execution included; ``None`` — the
                time-bounded settle mode of the polling settings.
            delay: keyword-only — the quiet pre-step pause in seconds;
                ``None`` — no pause.

        Raises:
            PrettyplayError: ``tries`` or ``delay`` is invalid — the loud
                failure names the parameter, the received value and the
                allowed form; the executor is never reached.
        """
        self._delegate(text, "action", tries, delay)

    def expect(self, text: str, *, tries: int | None = None, delay: float | None = None) -> None:
        """Execute the assertion step ``text`` inside the group — the same delegation, assertion kind.

        Args:
            text: the sentence of the assertion as written by the engineer.
            tries: keyword-only — the total number of executions of the
                step's code, the first execution included; ``None`` — the
                time-bounded settle mode of the polling settings.
            delay: keyword-only — the quiet pre-step pause in seconds;
                ``None`` — no pause.

        Raises:
            PrettyplayError: ``tries`` or ``delay`` is invalid — the loud
                failure names the parameter, the received value and the
                allowed form; the executor is never reached.
        """
        self._delegate(text, "assertion", tries, delay)

    def _delegate(self, text: str, step_type: str, tries: int | None, delay: float | None) -> None:
        """Validate, pause and delegate one group step to the executor.

        The pause of a call: the group entry pause immediately before the
        group's first executed step (lazy — a zero-step group never pauses),
        or the between-step pace pause before every following step when the
        group declares a speed — the same percent-to-ms mapping as the
        browser speed setting, as a plain library wait. The delegation flag
        is set before the executor call, never read from the traces.

        Args:
            text: the raw sentence of the step, verbatim.
            step_type: action or assertion.
            tries: the declared retry count of this execution; ``None`` —
                the global polling settings govern the step.
            delay: the declared start pause of this execution; ``None`` —
                no pause.

        Raises:
            PrettyplayError: ``tries`` or ``delay`` is invalid.
        """
        _validate_tries(tries)
        _validate_delay(delay)

        if not self._delegated:
            if self._delay is not None:
                time.sleep(self._delay)  # the lazy entry pause — quiet, library-level
        elif self._speed is not None:
            time.sleep(int((100 - self._speed) * 30) / 1000)  # the between-step pace — never slow_mo

        self._delegated = True
        self._executor.execute(text, step_type, self._open_page(), group=self, tries=tries, delay=delay)
