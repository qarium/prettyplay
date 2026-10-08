"""The deterministic acceptance gate for returned step results."""

from .render import PreparedStep


def _validate_values(result: dict[object, object]) -> None:
    """Validate every captured value of an accepted result dictionary.

    Args:
        result: The result dictionary whose keys already match the declarations.

    Raises:
        AssertionError: A value is not a string or is blank.
    """
    for name, value in result.items():
        if not isinstance(value, str):
            raise AssertionError(f"the result value of {name!r} must be a string, got {type(value).__name__}")

        if value.strip() == "":
            raise AssertionError(f"the result value of {name!r} is blank")


def validate_step_result(prepared: PreparedStep, result: object) -> dict[str, str]:
    """Deterministically validate the returned result of one step execution.

    Compares the untrusted step function's return against the declaration set of
    the render product: a declaration-free step accepts None, a declaring step
    must return exactly the declared names as non-blank strings. A violation
    raises ``AssertionError`` with the deterministic violation text — the
    failed-check channel of the calling cycle. Never fabricates or repairs.

    Args:
        prepared: The render product of the executed step — the declaration set.
        result: The untrusted step function's return — expected to be the
            dictionary of declared names to observed strings, or None for a
            declaration-free step.

    Returns:
        The validated captures, ready for publication; empty for a
        declaration-free step.

    Raises:
        AssertionError: The result violates the declared contract — a wrong
            type, a missing or unexpected name, or a non-string or blank value.
    """
    if not prepared.declarations:
        if result is None:
            return {}

        raise AssertionError("unexpected result without declarations")

    if result is None:
        names = ", ".join(prepared.declarations)

        raise AssertionError(f"missing result: the step declares {names}")

    if not isinstance(result, dict):
        raise AssertionError(f"result must be a dictionary, got {type(result).__name__}")

    missing = sorted(set(prepared.declarations) - set(result), key=repr)
    unexpected = sorted(set(result) - set(prepared.declarations), key=repr)

    if missing or unexpected:
        problems = []

        if missing:
            problems.append(f"missing {', '.join(repr(name) for name in missing)}")

        if unexpected:
            problems.append(f"unexpected {', '.join(repr(name) for name in unexpected)}")

        raise AssertionError(f"result keys do not match the declared captures: {'; '.join(problems)}")

    _validate_values(result)

    return dict(result)
