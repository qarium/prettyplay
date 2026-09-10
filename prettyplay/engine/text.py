"""The error-text policy of the engine: full typed failure text for reports and requests."""

def format_step_error(exc: Exception) -> str:
    """Format the full failure text of a step-code exception.

    A failed check — an ``AssertionError`` — yields its message verbatim, with
    no prefix: the exception type already carries the assertion semantics, and
    a message-less check yields an empty text, so the structured render omits
    the error line. Any other failure carries its type name — the action
    failures of step code are timeouts and driver errors whose bare messages
    lose the kind of failure; a message-less error yields the bare type name,
    never a dangling separator.

    Args:
        exc: the exception raised by the failed step or candidate branch.

    Returns:
        The full formatted failure text carried by reports and requests.
    """
    text = str(exc)
    if isinstance(exc, AssertionError):
        return text

    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__
