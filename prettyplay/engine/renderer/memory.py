"""The per-test-execution memory of captured observations."""

from __future__ import annotations


class StepMemory:
    """The names namespace of rendering — captured observations of one test execution.

    Owned by the step executor of one test: rendering reads snapshots, publication
    happens only at acceptance points. Constructs empty, survives navigation and
    never crosses test boundaries.
    """

    def __init__(self) -> None:
        """Construct an empty memory."""
        self._values: dict[str, str] = {}

    def snapshot(self) -> dict[str, str]:
        """Return a stable copy of the current values — the render source.

        Returns:
            The copy of the current values; later publications never mutate a
            taken snapshot.
        """
        return dict(self._values)

    def publish(self, captures: dict[str, str]) -> None:
        """Publish validated captures atomically.

        Replaces the value of every present name — a successful recapture
        replaces the previous value; names absent from ``captures`` keep theirs.

        Args:
            captures: The validated dictionary of one accepted step execution.
        """
        for name, value in captures.items():
            self._values[name] = value
