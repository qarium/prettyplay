"""Normalization of addressing texts for cache identity and addressing."""

import unicodedata


def normalize_step_text(text: str) -> str:
    """Normalize an addressing text for identity and addressing — one verbatim rule for every text.

    Args:
        text: the addressing text of the step — the rendered sentence, or a
            plain sentence, which addresses as itself.

    Returns:
        The normalized addressing text: the input under Unicode NFC
        normalization with leading and trailing whitespace trimmed. Case and
        internal whitespace are significant; template markers in the text are
        plain data.
    """
    return unicodedata.normalize("NFC", text).strip()
