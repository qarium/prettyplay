"""Per-run attempt registry: how many tries a step still has in this process.

One registry lives for the whole run (see the runtime composition root), so
budgets are never reset between tests — a step that burned its attempts in one
test stays exhausted in the next. Generation and healing draw from separate
pools, and each step is accounted by its deterministic address.
"""

from .models import StepIdentity


class RunBudgets:
    """The per-run registry of generation and healing attempts per step.

    Both pools are keyed by ``identity.filename`` — the deterministic digest
    of the step triple — so accounting survives without hashing the pydantic
    model. Nothing is persisted: the registry is process memory only.

    Attributes:
        _generation_limit: how many generation attempts a step may take per run.
        _healing_limit: how many healing attempts a step may take per run.
        _generation_used: attempts already spent per step in the generation pool.
        _healing_used: attempts already spent per step in the healing pool.
    """

    def __init__(self, generation_limit: int, healing_limit: int) -> None:
        """Init the registry with separate generation and healing limits.

        Args:
            generation_limit: the per-step generation attempt limit of the run.
            healing_limit: the per-step healing attempt limit of the run.
        """
        self._generation_limit = generation_limit
        self._healing_limit = healing_limit
        self._generation_used: dict[str, int] = {}
        self._healing_used: dict[str, int] = {}

    def try_generation(self, identity: StepIdentity) -> bool:
        """Spend one generation attempt of the step or refuse on exhaustion.

        Args:
            identity: the address of the step asking for an attempt.

        Returns:
            True when the attempt is granted and counted, False when the
            per-run generation budget of the step is exhausted.
        """
        used = self._generation_used.get(identity.filename, 0)
        if used >= self._generation_limit:
            return False

        self._generation_used[identity.filename] = used + 1

        return True

    def try_healing(self, identity: StepIdentity) -> bool:
        """Spend one healing attempt of the step or refuse on exhaustion.

        Args:
            identity: the address of the step asking for an attempt.

        Returns:
            True when the attempt is granted and counted, False when the
            per-run healing budget of the step is exhausted.
        """
        used = self._healing_used.get(identity.filename, 0)
        if used >= self._healing_limit:
            return False

        self._healing_used[identity.filename] = used + 1

        return True
