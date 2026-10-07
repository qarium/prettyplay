"""The error-text policy of the engine: full typed failure text for reports and requests."""

import re

#: The header of the bulky page-state section Playwright appends to a failed
#: expectation message — column zero; the section runs to the message end.
_ARIA_SNAPSHOT_HEADER = re.compile(r"^Aria snapshot:[ \t]*$", re.MULTILINE)


def _strip_aria_snapshot(text: str) -> str:
    """Drop the aria-snapshot section Playwright appends to a failed check message.

    Args:
        text: the full message text of the step-code exception.

    Returns:
        The text before the column-zero ``Aria snapshot:`` header, trailing
        whitespace trimmed; text without the header returns unchanged.
    """
    header = _ARIA_SNAPSHOT_HEADER.search(text)

    return text[: header.start()].rstrip() if header is not None else text


def format_step_error(exc: Exception) -> str:
    """Format the full failure text of a step-code exception.

    Args:
        exc: the exception raised by the failed step or candidate branch.

    Returns:
        The full formatted failure text — a failed check yields its message
        with no prefix, the trailing aria-snapshot section excluded; any
        other failure carries its type name; a message-less check yields an
        empty text, a message-less error the bare type name.
    """
    text = _strip_aria_snapshot(str(exc))
    if isinstance(exc, AssertionError):
        return text

    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__
