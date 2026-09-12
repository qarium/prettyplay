"""Execution of step code under the settle window: the re-execution loop of transient page-state failures."""

import logging
from collections.abc import Callable

from ...driver import (  # noqa: F401 — the recognition point of the loop; the body follows the contract
    PageFacade,
    is_pollable_failure,
)
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
    raise NotImplementedError
