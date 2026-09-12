"""The settle window of one step execution: the re-execution horizon of step code."""


class SettleWindow:
    """The settle horizon of one step execution.

    Decides when re-executing the same step code may still help and how long
    to pause between re-executions. Pure time bookkeeping on the monotonic
    clock — no I/O, no logging; the window gates repetitions, never kills a
    running attempt.

    Attributes:
        timeout: the total window in seconds; ``None`` — polling disabled;
            ``0`` — an explicit disable, equivalent to ``None``; positive —
            the window.
        delay: the pause between re-executions in seconds; ``0`` —
            re-execute without a pause.
    """

    def __init__(self, timeout: float | None, delay: float) -> None:
        """Keep the settle horizon of one step execution.

        Args:
            timeout: the total window in seconds; ``None`` — polling
                disabled; ``0`` — an explicit disable, equivalent to
                ``None``.
            delay: the pause between re-executions in seconds; ``0`` —
                re-execute without a pause.
        """
        self.timeout = timeout
        self.delay = delay

    @property
    def enabled(self) -> bool:
        """Whether polling is active: a positive timeout is set.

        Returns:
            True when the window carries a positive timeout.
        """
        raise NotImplementedError

    def start(self) -> None:
        """Mark the window start at the first execution of the step code.

        Idempotent: only the first call wins — later executions of the same
        step never shift the start.
        """
        raise NotImplementedError

    def has_remaining(self) -> bool:
        """Whether the window still allows a repetition.

        Checked only before a repetition: the window never interrupts a
        running attempt.

        Returns:
            True when time remains and the window is enabled and started;
            False when disabled, not started or expired — the first
            execution may consume the whole window.
        """
        raise NotImplementedError
