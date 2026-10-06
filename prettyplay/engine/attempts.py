"""The verbatim attempt record of the engine: one immutable entry of the per-step attempt history."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from ..driver import PageFacade

#: Record 0 of a healing cycle — the anchored cached code and the error of its failed replay.
OUTCOME_ORIGINAL = "original cached code"

#: The candidate executed but its own check — an AssertionError — did not hold.
OUTCOME_FAILED_CHECK = "failed check"

#: The candidate raised a non-assertion exception while executing.
OUTCOME_EXECUTION_FAILED = "execution failed"

#: The candidate executed green but the compliance gate blocked it from the cache.
OUTCOME_COMPLIANCE_BLOCKED = "compliance blocked"

#: The engineer rejected the candidate in the steering dialog; it never executed.
OUTCOME_REJECTED = "rejected by the engineer, not executed"


class StepAttempt(BaseModel):
    """One immutable verbatim record of the per-step attempt history — never rewritten or truncated.

    Attributes:
        code: the complete candidate code of the attempt, verbatim.
        error: the complete failure text — the execution error, the failed
            check text, or the gate violation text; empty on no error.
        outcome: the outcome label of the closed five-label set (the
            ``OUTCOME_*`` constants of this module).
        url_before: the page URL read immediately before the attempt's
            execution.
        url_after: the page URL read immediately after the attempt's
            execution.
    """

    model_config = ConfigDict(kw_only=True, frozen=True)

    code: str = ""
    error: str = ""
    outcome: str = ""
    url_before: str = ""
    url_after: str = ""

    def render(self) -> str:
        """Render the complete verbatim record text.

        Returns:
            The multi-line record text — the pinned four-part format:
            outcome line, URL pair, the ``code:`` part and, when non-empty,
            the ``error:`` part; no collapsing, no truncation.
        """
        record = f"{self.outcome}\nurl: {self.url_before} -> {self.url_after}\ncode:\n{self.code}"
        if self.error:
            if not record.endswith("\n"):
                record += "\n"
            record += f"error:\n{self.error}"
        return record


def _read_url(page: PageFacade) -> str:
    """Read the page URL for an attempt bracket; never kills the attempt.

    Args:
        page: the page facade handle of the current test.

    Returns:
        The current URL of the page, or the empty string when the read
        fails — the attempt itself proceeds normally.
    """
    try:
        return page.url
    except Exception:
        return ""
