"""Tests for the composition root of the prettyplay root cell."""

import inspect
from unittest import mock

import prettyplay.runtime as runtime_module
import pytest
from prettyplay import PrettyplayRuntime, get_runtime
from prettyplay.cache import RunBudgets, StepIdentity
from prettyplay.config import Config
from prettyplay.driver import DriverSession


@pytest.fixture(autouse=True)
def isolated_runtime_global():
    """Reset the process runtime singleton before and after every test."""
    runtime_module._runtime = None
    yield
    runtime_module._runtime = None


class TestRuntimeContract:
    """Contract tests: facade import, constructor, surface and the singleton entry."""

    def test_runtime_names_importable_from_root_facade(self) -> None:
        assert isinstance(PrettyplayRuntime, type)
        assert callable(get_runtime)

    def test_get_runtime_takes_no_arguments(self) -> None:
        assert list(inspect.signature(get_runtime).parameters) == []

    def test_constructor_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(PrettyplayRuntime.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["config"]

    def test_runtime_surface_matches_contract(self) -> None:
        for name in ("config", "budgets", "driver", "provider"):
            assert isinstance(getattr(PrettyplayRuntime, name), property), name

        for name in ("open_page", "close"):
            assert callable(getattr(PrettyplayRuntime, name)), name


class TestGetRuntime:
    """Logic tests: the process-wide singleton behind get_runtime."""

    def test_get_runtime_is_process_singleton(self) -> None:
        config = Config(model="gpt-5")

        with mock.patch("prettyplay.runtime.load_config", return_value=config) as load_config_mock:
            runtime1 = get_runtime()
            runtime2 = get_runtime()

        assert runtime1 is runtime2
        assert load_config_mock.call_count == 1
        assert runtime1.config is config

    def test_get_runtime_registers_atexit_close(self) -> None:
        config = Config(model="gpt-5")

        with (
            mock.patch("prettyplay.runtime.load_config", return_value=config),
            mock.patch("prettyplay.runtime.atexit.register") as register_mock,
        ):
            runtime = get_runtime()

        register_mock.assert_called_once_with(runtime.close)

    def test_get_runtime_registers_atexit_once(self) -> None:
        config = Config(model="gpt-5")

        with (
            mock.patch("prettyplay.runtime.load_config", return_value=config),
            mock.patch("prettyplay.runtime.atexit.register") as register_mock,
        ):
            get_runtime()
            get_runtime()
            get_runtime()

        register_mock.assert_called_once()


class TestPrettyplayRuntime:
    """Logic tests: eager composition, laziness and the driver lifecycle."""

    def test_runtime_constructs_without_llm_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        with (
            mock.patch("prettyplay.runtime.create_provider") as create_provider_mock,
            mock.patch("prettyplay.runtime.DriverSession") as driver_session_mock,
        ):
            runtime = PrettyplayRuntime(Config(model="gpt-5"))

            config = runtime.config
            budgets = runtime.budgets

        assert config.model == "gpt-5"
        assert isinstance(budgets, RunBudgets)
        create_provider_mock.assert_not_called()
        driver_session_mock.assert_not_called()

    def test_close_before_open_page_is_noop(self) -> None:
        runtime = PrettyplayRuntime(Config())

        runtime.close()

    def test_budgets_carry_config_limits(self) -> None:
        runtime = PrettyplayRuntime(Config())
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="шаг")

        assert isinstance(runtime.budgets, RunBudgets)
        assert [runtime.budgets.try_generation(identity) for _ in range(4)] == [True, True, True, False]
        assert [runtime.budgets.try_healing(identity) for _ in range(3)] == [True, True, False]

    def test_driver_is_lazy_and_memoized(self) -> None:
        runtime = PrettyplayRuntime(Config())

        assert runtime._driver is None

        driver = runtime.driver

        assert isinstance(driver, DriverSession)
        assert runtime.driver is driver

    def test_provider_is_lazy_and_memoized(self) -> None:
        runtime = PrettyplayRuntime(Config(provider="anthropic", model="claude-sonnet-4-5"))

        with mock.patch("prettyplay.runtime.create_provider") as create_provider_mock:
            provider = runtime.provider
            same_provider = runtime.provider

        create_provider_mock.assert_called_once_with(runtime.config)
        assert provider is same_provider
        assert provider is create_provider_mock.return_value

    def test_open_page_delegates_to_driver(self) -> None:
        runtime = PrettyplayRuntime(Config())

        with mock.patch("prettyplay.runtime.DriverSession") as driver_session_mock:
            page = runtime.open_page()

        driver_session_mock.assert_called_once_with(runtime.config)
        driver_session_mock.return_value.open_context.assert_called_once_with()
        assert page is driver_session_mock.return_value.open_context.return_value

    def test_close_stops_started_driver(self) -> None:
        runtime = PrettyplayRuntime(Config())

        with mock.patch("prettyplay.runtime.DriverSession") as driver_session_mock:
            runtime.open_page()
            runtime.close()

        driver_session_mock.return_value.close.assert_called_once()
