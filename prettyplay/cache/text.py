"""Normalization of step sentences for cache identity and addressing."""

import re
import unicodedata

#: Pattern of any whitespace run, collapsed to a single space by :func:`normalize_step_text`.
_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_step_text(text: str) -> str:
    """Normalize a step sentence for identity and addressing.

    Args:
        text: the raw step sentence as written by the engineer.

    Returns:
        The normalized sentence — NFC, trimmed, whitespace runs collapsed,
        casefolded: incidental differences erase, distinct sentences stay
        distinct.
    """
    normalized = unicodedata.normalize("NFC", text)

    normalized = normalized.strip()

    normalized = _WHITESPACE_RUN.sub(" ", normalized)

    return normalized.casefold()
