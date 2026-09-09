"""Tests for the RunBudgets attempt registry of the prettyplay.cache cell."""

import inspect

from prettyplay.cache import RunBudgets, StepIdentity
from prettyplay.config import Config

IDENTITY = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="нажать войти")
IDENTITY2 = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="нажать выйти")


class TestRunBudgetsContract:
    """Contract tests: facade import, constructor and method signatures."""

    def test_run_budgets_is_importable_from_facade(self) -> None:
        assert isinstance(RunBudgets, type)

    def test_signature_is_generation_and_healing_limits(self) -> None:
        parameters = list(inspect.signature(RunBudgets.__init__).parameters.values())[1:]  # drop self

        assert [parameter.name for parameter in parameters] == ["generation_limit", "healing_limit"]

    def test_constructs_with_both_limits(self) -> None:
        assert isinstance(RunBudgets(generation_limit=3, healing_limit=2), RunBudgets)

    def test_declares_try_generation_and_try_healing(self) -> None:
        generation_parameters = list(inspect.signature(RunBudgets.try_generation).parameters.values())[1:]
        healing_parameters = list(inspect.signature(RunBudgets.try_healing).parameters.values())[1:]

        assert [parameter.name for parameter in generation_parameters] == ["identity"]
        assert [parameter.name for parameter in healing_parameters] == ["identity"]

    def test_try_methods_return_bool(self) -> None:
        budgets = RunBudgets(generation_limit=1, healing_limit=1)

        assert isinstance(budgets.try_generation(IDENTITY), bool)
        assert isinstance(budgets.try_healing(IDENTITY), bool)


class TestRunBudgetsLogic:
    """Logic tests: separate pools, per-identity accounting, per-test ownership, default limits."""

    def test_budgets_separate_pools_shared_per_identity(self) -> None:
        budgets = RunBudgets(generation_limit=1, healing_limit=1)

        results = [
            budgets.try_generation(IDENTITY),
            budgets.try_generation(IDENTITY),
            budgets.try_healing(IDENTITY),
            budgets.try_generation(IDENTITY2),
        ]

        assert results == [True, False, True, True]

    def test_budgets_default_limits_from_config(self) -> None:
        config = Config()
        budgets = RunBudgets(config.generation_attempts, config.healing_attempts)

        generations = [budgets.try_generation(IDENTITY) for _ in range(4)]
        healings = [budgets.try_healing(IDENTITY) for _ in range(3)]

        assert generations == [True, True, True, False]
        assert healings == [True, True, False]

    def test_budgets_pools_do_not_drain_each_other(self) -> None:
        budgets = RunBudgets(generation_limit=0, healing_limit=1)

        assert budgets.try_generation(IDENTITY) is False
        assert budgets.try_healing(IDENTITY) is True  # healing pool intact

    def test_reused_step_gets_fresh_budget_in_each_test(self) -> None:
        """Each test owns its own registry: a step reused across tests starts with full limits."""
        first_test = RunBudgets(generation_limit=1, healing_limit=1)
        second_test = RunBudgets(generation_limit=1, healing_limit=1)

        assert first_test.try_generation(IDENTITY) is True
        assert first_test.try_generation(IDENTITY) is False  # исчерпан внутри первого теста
        assert second_test.try_generation(IDENTITY) is True  # свежий бюджет нового теста

    def test_budgets_shared_between_two_consumers_of_one_registry(self) -> None:
        """The registry of one test is handed to several consumers; spending is shared, not per-consumer."""
        budgets = RunBudgets(generation_limit=1, healing_limit=1)

        class Consumer:
            def __init__(self, registry: RunBudgets) -> None:
                self.registry = registry

            def try_(self, identity: StepIdentity) -> bool:
                return self.registry.try_generation(identity)

        first, second = Consumer(budgets), Consumer(budgets)  # два потребителя одного реестра

        assert first.try_(IDENTITY) is True
        assert second.try_(IDENTITY) is False  # второму попытка не вернулась
