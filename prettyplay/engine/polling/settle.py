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
    text; no hook events, no LLM budget.

    Args:
        execute: the step-code execution routine passed by the caller.
        code: the step code text.
        page: the page facade of the current test.
        window: the settle window of the current step execution.
    """
    window.start()

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
