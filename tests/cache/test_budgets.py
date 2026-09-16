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

    def test_declares_refresh_healing_and_open_group_cycle(self) -> None:
        refresh_parameters = list(inspect.signature(RunBudgets.refresh_healing).parameters.values())[1:]
        cycle_parameters = list(inspect.signature(RunBudgets.open_group_cycle).parameters.values())[1:]

        assert [parameter.name for parameter in refresh_parameters] == ["identity"]
        assert [parameter.name for parameter in cycle_parameters] == ["group_key"]

    def test_open_group_cycle_returns_bool(self) -> None:
        budgets = RunBudgets(generation_limit=1, healing_limit=1)

        assert isinstance(budgets.open_group_cycle("the checkout flow"), bool)

    def test_refresh_healing_returns_none(self) -> None:
        budgets = RunBudgets(generation_limit=1, healing_limit=1)

        assert budgets.refresh_healing(IDENTITY) is None


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
        assert first_test.try_generation(IDENTITY) is False  # exhausted within the first test
        assert second_test.try_generation(IDENTITY) is True  # a fresh budget for the new test

    def test_budgets_shared_between_two_consumers_of_one_registry(self) -> None:
        """The registry of one test is handed to several consumers; spending is shared, not per-consumer."""
        budgets = RunBudgets(generation_limit=1, healing_limit=1)

        class Consumer:
            def __init__(self, registry: RunBudgets) -> None:
                self.registry = registry

            def try_(self, identity: StepIdentity) -> bool:
                return self.registry.try_generation(identity)

        first, second = Consumer(budgets), Consumer(budgets)  # two consumers of one registry

        assert first.try_(IDENTITY) is True
        assert second.try_(IDENTITY) is False  # the attempt was not returned to the second


class TestRunBudgetsRecoveryLogic:
    """Logic tests: pool renewal, the per-group cycle cap and its keying."""

    def test_refresh_healing_renews_an_exhausted_pool(self) -> None:
        budgets = RunBudgets(generation_limit=3, healing_limit=2)

        first_pool = [budgets.try_healing(IDENTITY) for _ in range(3)]
        budgets.refresh_healing(IDENTITY)
        second_pool = [budgets.try_healing(IDENTITY) for _ in range(3)]

        assert first_pool == [True, True, False]  # exhausted within the first cycle
        assert second_pool == [True, True, False]  # the full healing_limit count again

    def test_refresh_healing_leaves_other_steps_untouched(self) -> None:
        budgets = RunBudgets(generation_limit=3, healing_limit=1)

        assert budgets.try_healing(IDENTITY) is True
        assert budgets.try_healing(IDENTITY2) is True
        budgets.refresh_healing(IDENTITY)  # only IDENTITY renews

        assert budgets.try_healing(IDENTITY) is True
        assert budgets.try_healing(IDENTITY2) is False  # its pool stays exhausted

    def test_open_group_cycle_increments_until_cap(self) -> None:
        budgets = RunBudgets(generation_limit=3, healing_limit=2)

        results = [budgets.open_group_cycle("the checkout flow") for _ in range(3)]

        assert results == [True, True, False]  # the (healing_limit+1)-th call refuses

    def test_two_groups_with_the_same_prompt_share_one_cap(self) -> None:
        budgets = RunBudgets(generation_limit=3, healing_limit=1)

        assert budgets.open_group_cycle("the checkout flow") is True
        assert budgets.open_group_cycle("the checkout flow") is False  # the key is the prompt

    def test_distinct_groups_draw_from_distinct_caps(self) -> None:
        budgets = RunBudgets(generation_limit=3, healing_limit=1)

        assert budgets.open_group_cycle("the checkout flow") is True
        assert budgets.open_group_cycle("the login flow") is True  # a separate cap

    def test_same_group_entered_twice_in_one_test_shares_its_cap(self) -> None:
        budgets = RunBudgets(generation_limit=3, healing_limit=2)

        first_entry = [budgets.open_group_cycle("the checkout flow") for _ in range(2)]
        second_entry = [budgets.open_group_cycle("the checkout flow") for _ in range(2)]

        assert first_entry == [True, True]  # both cycles of the first entry
        assert second_entry == [False, False]  # the second entry opens no new cycles

    def test_fresh_registry_starts_all_counters_at_zero(self) -> None:
        """A new test owns a fresh registry: the group cap and the pools reset."""
        first_test = RunBudgets(generation_limit=3, healing_limit=1)
        first_test.open_group_cycle("the checkout flow")
        first_test.try_healing(IDENTITY)

        second_test = RunBudgets(generation_limit=3, healing_limit=1)

        assert second_test.open_group_cycle("the checkout flow") is True  # the cap is fresh
        assert second_test.try_healing(IDENTITY) is True  # the pool is fresh

    def test_recovery_operations_never_consume_ordinary_pools(self) -> None:
        budgets = RunBudgets(generation_limit=1, healing_limit=1)

        budgets.open_group_cycle("the checkout flow")
        budgets.refresh_healing(IDENTITY2)

        assert budgets.try_generation(IDENTITY) is True  # the generation pool intact
        assert budgets.try_healing(IDENTITY) is True  # other steps' healing pools intact
        assert budgets.open_group_cycle("the login flow") is True  # other groups' caps intact
