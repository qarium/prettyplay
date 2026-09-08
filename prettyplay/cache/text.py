"""Normalization of step sentences for cache identity and addressing.

The same normalized sentence in the same context is one step: normalization
erases incidental differences (unicode composition, surrounding and internal
whitespace runs, letter case) while keeping distinct sentences distinct.
"""

import re
import unicodedata

#: Pattern of any whitespace run, collapsed to a single space by :func:`normalize_step_text`.
_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_step_text(text: str) -> str:
    """Normalize a step sentence for identity and addressing.

    Pipeline: Unicode NFC normalization, trimming of leading and trailing
    whitespace, collapsing of internal whitespace runs to single spaces,
    casefold. «Нажать Войти» and «нажать  войти » normalize to the same
    string; a Russian sentence and its English translation stay different.

    Args:
        text: the raw step sentence as written by the engineer.

    Returns:
        The normalized sentence.
    """
    normalized = unicodedata.normalize("NFC", text)

    normalized = normalized.strip()

    normalized = _WHITESPACE_RUN.sub(" ", normalized)

    return normalized.casefold()
