"""Execution of step code under the settle window: the re-execution loop of transient page-state failures."""

import logging
import time
from collections.abc import Callable

from ...driver import PageFacade, is_pollable_failure
from .window import SettleWindow

logger = logging.getLogger("prettyplay")


def settle(
    execute: Callable[[str, PageFacade], dict[str, str] | None],
    code: str,
    page: PageFacade,
    window: SettleWindow,
) -> dict[str, str] | None:
    """Execute step code under the settle window and carry the successful execution's result back.

    Args:
        execute: the step-code execution routine passed by the caller — returns
            the step's result (a dictionary of declared names to observed
            strings, or None for a declaration-free step).
        code: the step code text.
        page: the page facade of the current test.
        window: the settle window of the current step execution — a declared
            ``tries`` count bounds the loop by executions (the counter is
            local to this call), otherwise the time window applies; each
            repetition logs ``settle_retry`` at INFO.

    Returns:
        The result returned by the successful execution — untouched: the loop
        never inspects, validates or alters it; validation belongs to the
        calling cycle.
    """
    window.start()

    if window.count_bounded:
        return _settle_by_count(execute, code, page, window)

    attempt = 0

    while True:
        try:
            return execute(code, page)

        except Exception as failure:
            attempt += 1

            if window.enabled and is_pollable_failure(failure) and window.has_remaining():
                logger.info("settle_retry", extra={"attempt": attempt, "error": str(failure)})
                time.sleep(window.delay)

                continue

            raise


def _settle_by_count(
    execute: Callable[[str, PageFacade], dict[str, str] | None],
    code: str,
    page: PageFacade,
    window: SettleWindow,
) -> dict[str, str] | None:
    """Execute step code up to the window's declared tries count and return the successful execution's result.

    Args:
        execute: the step-code execution routine passed by the caller — returns
            the step's result (a dictionary of declared names to observed
            strings, or None for a declaration-free step).
        code: the step code text.
        page: the page facade of the current test.
        window: the count-bounded settle window — re-execute iff enabled,
            pollable and under the declared count; exhaustion propagates
            the failure as-is.

    Returns:
        The result returned by the successful execution — including the result
        of a successful re-execution; the loop never touches it beyond the
        pass-through.
    """
    executed = 0

    while True:
        try:
            return execute(code, page)

        except Exception as failure:
            executed += 1

            if window.enabled and is_pollable_failure(failure) and executed < window.tries:
                logger.info("settle_retry", extra={"attempt": executed, "error": str(failure)})
                time.sleep(window.delay)

                continue

            raise
