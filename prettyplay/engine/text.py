"""The error-text policy of the engine: full typed failure text for reports and requests."""


def format_step_error(exc: Exception) -> str:
    """Format the full failure text of a step-code exception.

    Args:
        exc: the exception raised by the failed step or candidate branch.

    Returns:
        The full formatted failure text — a failed check yields its message
        verbatim with no prefix; any other failure carries its type name; a
        message-less check yields an empty text, a message-less error the
        bare type name.
    """
    text = str(exc)
    if isinstance(exc, AssertionError):
        return text

    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__
