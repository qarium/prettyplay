"""Normalization of step sentences for cache identity and addressing."""

import re
import unicodedata

#: Pattern of any whitespace run, collapsed to a single space by :func:`normalize_step_text`.
_WHITESPACE_RUN = re.compile(r"\s+")

#: Jinja template markers — any occurrence switches the sentence to verbatim addressing.
_TEMPLATE_MARKERS = ("{{", "{%", "{#")


def normalize_step_text(text: str) -> str:
    """Normalize a step sentence for identity and addressing — template-aware.

    Args:
        text: the raw step sentence as written by the engineer.

    Returns:
        The normalized sentence. A template sentence (containing ``{{``,
        ``{%`` or ``{#``) keeps its source verbatim except NFC normalization
        and trimming — Jinja names are case-sensitive and whitespace inside
        expressions is significant. An ordinary sentence keeps the
        equivalence pipeline: NFC, trimmed, whitespace runs collapsed,
        casefolded.
    """
    normalized = unicodedata.normalize("NFC", text)

    normalized = normalized.strip()

    if any(marker in normalized for marker in _TEMPLATE_MARKERS):
        return normalized

    normalized = _WHITESPACE_RUN.sub(" ", normalized)

    return normalized.casefold()
