"""The fixed pollable map of the prettyplay.driver error surface."""

from __future__ import annotations

import re

from playwright.sync_api import Error as PlaywrightError

#: The timeout signature of the installed Playwright driver — "Timeout NNNms
#: exceeded" over locator, action, expectation and navigation waits alike.
_TIMEOUT_PATTERN = re.compile(r"timeout \d+m?s exceeded")

#: Fixed message-pattern set of the pollable driver kinds — element state,
#: detach/stale handles, navigation and context races. Every pattern matches
#: a real message of the installed Playwright driver; the detach family is
#: exactly this set.
_POLLABLE_PATTERNS = (
    "element is not visible",
    "element is not enabled",
    "element is outside of the viewport",
    "element is not attached",
    "frame has been detached",
    "detached from document",
    "execution context was destroyed",
    "target closed",
    "interrupted by another navigation",
    "navigation interrupted the evaluation",
)


def _matches_pollable(text: str) -> bool:
    """Match a Playwright error text against the fixed pollable pattern set.

    Args:
        text: the message text of the exception, any casing.

    Returns:
        True when the lowercased text carries a timeout signature or one of
        the fixed pollable message patterns.
    """
    lower = text.lower()

    if _TIMEOUT_PATTERN.search(lower):
        return True

    return any(pattern in lower for pattern in _POLLABLE_PATTERNS)


def is_pollable_failure(exc: Exception) -> bool:
    """Decide whether a failed step-code exception is transient page state.

    Args:
        exc: the exception raised by the failed step code.

    Returns:
        True when the kind is transient — the settle window may re-execute
        the same code; False — deterministic or unknown, it goes straight
        to classification. True covers a failed check and the
        timeout/element-state/navigation driver families; False covers
        locator ambiguity and Python-level errors.
    """
    text = str(exc)

    # Locator ambiguity first — the elements are there, waiting will not
    # collapse them to one; an ambiguity-styled AssertionError is refused too.
    if "strict mode violation" in text:
        return False

    # A failed expectation: the check executed and did not hold; the state
    # may catch up.
    if isinstance(exc, AssertionError):
        return True

    # Driver kinds by type and message pattern — never pattern alone; anything
    # else — Python-level or unknown — is the conservative default.
    return isinstance(exc, PlaywrightError) and _matches_pollable(text)
