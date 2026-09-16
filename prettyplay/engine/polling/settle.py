"""Execution of step code under the settle window: the re-execution loop of transient page-state failures."""

import logging
import time
from collections.abc import Callable

from ...driver import PageFacade, is_pollable_failure
from .window import SettleWindow

logger = logging.getLogger("prettyplay")


def settle(
    execute: Callable[[str, PageFacade], None],
    code: str,
    page: PageFacade,
    window: SettleWindow,
) -> None:
    """Execute step code under the settle window.

    Absorb transient page-state failures by re-executing the same code,
    propagate everything else as-is. Each repetition writes a
    ``settle_retry`` record at INFO — the attempt counter and the failure
    text; no hook events, no LLM budget. The window carries one of two
    bound modes: a declared ``tries`` count bounds the loop by executions
    (a counter local to this call — the cached code and every candidate
    each get their own full count); otherwise the time window applies.

    Args:
        execute: the step-code execution routine passed by the caller.
        code: the step code text.
        page: the page facade of the current test.
        window: the settle window of the current step execution.
    """
    window.start()

    if window.count_bounded:
        _settle_by_count(execute, code, page, window)

        return

    attempt = 0

    while True:
        try:
            execute(code, page)

            return

        except Exception as failure:
            attempt += 1

            if window.enabled and is_pollable_failure(failure) and window.has_remaining():
                logger.info("settle_retry", extra={"attempt": attempt, "error": str(failure)})
                time.sleep(window.delay)

                continue

            raise


def _settle_by_count(
    execute: Callable[[str, PageFacade], None],
    code: str,
    page: PageFacade,
    window: SettleWindow,
) -> None:
    """Execute step code up to the window's declared tries count.

    The count bound replaces the time bound for this loop: re-execute iff
    the window is enabled, the failure is pollable and fewer executions
    have run than the window declares; exhaustion propagates the failure
    object as-is. The counter is local to this call and never consults the
    clock. Each repetition writes a ``settle_retry`` record at INFO — the
    attempt counter and the failure text — uniform with the time mode.

    Args:
        execute: the step-code execution routine passed by the caller.
        code: the step code text.
        page: the page facade of the current test.
        window: the count-bounded settle window of this step execution.
    """
    executed = 0

    while True:
        try:
            execute(code, page)

            return

        except Exception as failure:
            executed += 1

            if window.enabled and is_pollable_failure(failure) and executed < window.tries:
                logger.info("settle_retry", extra={"attempt": executed, "error": str(failure)})
                time.sleep(window.delay)

                continue

            raise
