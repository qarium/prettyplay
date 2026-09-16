"""The settle window of one step execution: the re-execution horizon of step code."""

import time


class SettleWindow:
    """The settle horizon of one step execution.

    Decides when re-executing the same step code may still help and how long
    to pause between re-executions. Pure bookkeeping — no I/O, no logging;
    the window gates repetitions, never kills a running attempt. Two bound
    modes live side by side: the time window of a positive ``timeout`` and
    the count bound of a declared ``tries``.

    Attributes:
        timeout: the total window in seconds; ``None`` — polling disabled;
            ``0`` — an explicit disable, equivalent to ``None``; positive —
            the window.
        delay: the pause between re-executions in seconds; ``0`` —
            re-execute without a pause.
        tries: the total number of executions of one code unit within its
            re-execution loop, the first execution included (``1`` — no
            re-execution); ``None`` — the time-bounded mode of today.
    """

    def __init__(self, timeout: float | None, delay: float, tries: int | None = None) -> None:
        """Keep the settle horizon of one step execution.

        Args:
            timeout: the total window in seconds; ``None`` — polling
                disabled; ``0`` — an explicit disable, equivalent to
                ``None``.
            delay: the pause between re-executions in seconds; ``0`` —
                re-execute without a pause.
            tries: the declared retry count; ``None`` — the time-bounded
                mode; a positive integer — the count-bounded mode.
        """
        self.timeout = timeout
        self.delay = delay
        self.tries = tries
        self._started_at: float | None = None

    @property
    def count_bounded(self) -> bool:
        """Whether the window bounds this loop by execution count.

        Returns:
            True when a ``tries`` count is declared.
        """
        return self.tries is not None

    @property
    def enabled(self) -> bool:
        """Whether polling is active: a positive timeout is set or the window is count-bounded.

        Returns:
            True when the window carries a positive timeout or a declared
            ``tries`` count — a count-bounded window stays alive even with
            the time window disabled.
        """
        return (self.timeout is not None and self.timeout > 0) or self.count_bounded

    def start(self) -> None:
        """Mark the window start at the first execution of the step code.

        Idempotent: only the first call wins — later executions of the same
        step never shift the start.
        """
        if self._started_at is None:
            self._started_at = time.monotonic()

    def has_remaining(self) -> bool:
        """Whether the window still allows a repetition.

        Time-bounded mode alone: the count-bounded loop checks its own
        execution counter and never calls this — a count-bounded window
        with polling disabled has no time horizon.

        Checked only before a repetition: the window never interrupts a
        running attempt.

        Returns:
            True when time remains and the window is enabled and started;
            False when disabled, not started or expired — the first
            execution may consume the whole window.
        """
        if not self.enabled or self._started_at is None or self.timeout is None:
            return False
        return (time.monotonic() - self._started_at) < self.timeout
