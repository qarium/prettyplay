"""Per-test attempt registry: how many tries a step still has in this test.

One registry lives for the lifetime of one test, owned by the test's runtime
(see the runtime composition root), so every test starts with full limits —
a step reused across tests gets a fresh budget in each test. Generation and
healing draw from separate pools, and each step is accounted by its
deterministic address.
"""

from .models import StepIdentity


class RunBudgets:
    """The per-test registry of generation and healing attempts per step.

    Both pools are keyed by ``identity.filename`` — the deterministic digest
    of the step triple — so accounting survives without hashing the pydantic
    model. Recovery cycles are keyed by the group prompt instead: the cap
    counts recovery cycles per group per test, never per step. Nothing is
    persisted: the registry is process memory only.

    Attributes:
        _generation_limit: how many generation attempts a step may take per test.
        _healing_limit: how many healing attempts a step may take per test.
        _generation_used: attempts already spent per step in the generation pool.
        _healing_used: attempts already spent per step in the healing pool.
        _group_cycles_used: recovery cycles already opened per group in this test.
    """

    def __init__(self, generation_limit: int, healing_limit: int) -> None:
        """Init the registry with separate generation and healing limits.

        Args:
            generation_limit: the per-step generation attempt limit of the test.
            healing_limit: the per-step healing attempt limit of the test.
        """
        self._generation_limit = generation_limit
        self._healing_limit = healing_limit
        self._generation_used: dict[str, int] = {}
        self._healing_used: dict[str, int] = {}
        self._group_cycles_used: dict[str, int] = {}

    def try_generation(self, identity: StepIdentity) -> bool:
        """Spend one generation attempt of the step or refuse on exhaustion.

        Args:
            identity: the address of the step asking for an attempt.

        Returns:
            True when the attempt is granted and counted, False when the
            per-test generation budget of the step is exhausted.
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
            per-test healing budget of the step is exhausted.
        """
        used = self._healing_used.get(identity.filename, 0)
        if used >= self._healing_limit:
            return False

        self._healing_used[identity.filename] = used + 1

        return True

    def refresh_healing(self, identity: StepIdentity) -> None:
        """Grant the step a fresh full healing counter.

        The recovery engine calls this at every new recovery cycle for every
        row step, so a second attempt is never starved by the first cycle.
        Ordinary per-step pools of other steps are untouched.

        Args:
            identity: the address of the row step.
        """
        self._healing_used[identity.filename] = 0

    def open_group_cycle(self, group_key: str) -> bool:
        """Spend one recovery cycle of the group or refuse on exhaustion.

        The cap counts recovery cycles per group per test, never per step —
        the recovery loop is never infinite.

        Args:
            group_key: the key of the group — its group prompt.

        Returns:
            True when a new cycle is open and counted, False when the
            per-test cycle cap of the group (the healing limit) is
            exhausted.
        """
        used = self._group_cycles_used.get(group_key, 0)
        if used >= self._healing_limit:
            return False

        self._group_cycles_used[group_key] = used + 1

        return True
