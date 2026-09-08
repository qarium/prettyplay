"""Shared short-failure text of the engine: one truncation policy for reports and requests."""

#: Upper bound of the short failure description carried by reports and healing requests.
SHORT_ERROR_LENGTH = 200


def first_line_short(exc: Exception) -> str:
    """Return the first line of the exception text, cut to 200 characters.

    A message-less exception (a bare ``assert`` in step code) yields an
    empty description instead of crashing the reporting and healing paths.

    Args:
        exc: the exception raised by the failed step or candidate branch.

    Returns:
        The short failure description carried by reports and requests.
    """
    return str(exc).partition("\n")[0][:SHORT_ERROR_LENGTH]
