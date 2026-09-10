"""Tests for the Config model of the prettyplay.config cell."""

import inspect

import prettyplay.config
import pydantic
import pytest
from prettyplay.config import Config


class TestConfigContract:
    """Contract tests: facade, base class, construction shape, property surface."""

    def test_config_is_pydantic_base_model(self) -> None:
        assert issubclass(Config, pydantic.BaseModel)

    def test_config_is_kw_only(self) -> None:
        assert Config.model_config.get("kw_only") is True

    def test_positional_construction_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            Config("openai")  # type: ignore[misc]

    def test_all_fifteen_properties_accessible(self) -> None:
        config = Config()
        expected = [
            "provider",
            "browser",
            "model",
            "generation_model",
            "classification_model",
            "base_url",
            "cache_root",
            "generation_prompt",
            "browser_endpoint",
            "generation_attempts",
            "healing_attempts",
            "send_screenshots",
            "headless",
            "effective_generation_model",
            "effective_classification_model",
        ]
        for name in expected:
            assert hasattr(config, name), f"missing property: {name}"

    def test_signature_declares_thirteen_fields_in_contract_order(self) -> None:
        fields = Config.model_fields
        assert list(fields.keys()) == [
            "provider",
            "browser",
            "model",
            "generation_model",
            "classification_model",
            "base_url",
            "cache_root",
            "generation_prompt",
            "browser_endpoint",
            "generation_attempts",
            "healing_attempts",
            "send_screenshots",
            "headless",
        ]

    def test_new_settings_are_empty_strings_by_default(self) -> None:
        generation_prompt = Config.model_fields["generation_prompt"]
        browser_endpoint = Config.model_fields["browser_endpoint"]

        assert generation_prompt.annotation is str
        assert browser_endpoint.annotation is str
        assert generation_prompt.default == ""
        assert browser_endpoint.default == ""

    def test_pretty_config_is_config_alias_on_facade(self) -> None:
        assert prettyplay.config.PrettyConfig is Config
        assert "PrettyConfig" in prettyplay.config.__all__

    def test_headless_default_and_browser_default(self) -> None:
        config = Config()

        assert config.headless is True
        assert config.browser == "chromium"

    def test_browser_channel_values_type_check(self) -> None:
        for name in ("chromium", "firefox", "webkit", "chrome", "msedge"):
            assert Config(browser=name).browser == name

        assert Config(headless=False).headless is False

    def test_effective_models_are_properties_not_fields(self) -> None:
        assert isinstance(inspect.getattr_static(Config, "effective_generation_model"), property)
        assert isinstance(inspect.getattr_static(Config, "effective_classification_model"), property)


class TestConfigLogic:
    """Logic tests: defaults, effective fallbacks, loud validation."""

    def test_config_defaults_valid(self) -> None:
        config = Config()

        assert config.provider == "openai"
        assert config.browser == "chromium"
        assert config.generation_attempts == 3
        assert config.healing_attempts == 2
        assert config.send_screenshots is False
        assert config.effective_generation_model == config.model == ""

    def test_config_invalid_provider_fails_loudly(self) -> None:
        with pytest.raises(pydantic.ValidationError) as excinfo:
            Config(provider="yandex")

        message = str(excinfo.value)
        assert "provider" in message
        assert "openai" in message
        assert "anthropic" in message

    def test_effective_models_fall_back_to_main_model(self) -> None:
        config = Config(model="gpt-5", generation_model="gpt-5-mini", classification_model="")

        assert config.effective_generation_model == "gpt-5-mini"
        assert config.effective_classification_model == "gpt-5"

    def test_zero_generation_attempts_fails_with_field_name(self) -> None:
        with pytest.raises(pydantic.ValidationError) as excinfo:
            Config(generation_attempts=0)

        assert "generation_attempts" in str(excinfo.value)

    def test_unknown_browser_fails_loudly(self) -> None:
        with pytest.raises(pydantic.ValidationError) as excinfo:
            Config(browser="ie")

        message = str(excinfo.value)
        assert "browser" in message
        assert "chromium" in message

    @pytest.mark.parametrize(
        "endpoint",
        [
            "ws://host:3000/x",
            "wss://grid.example/playwright/chromium",
            "ws://127.0.0.1:9000",
            "WS://host:3000",
        ],
    )
    def test_models_browser_endpoint_accepts_ws_and_wss(self, endpoint: str) -> None:
        assert Config(browser_endpoint=endpoint).browser_endpoint == endpoint

    @pytest.mark.parametrize(
        "endpoint",
        [
            "http://ci-grid:3000",
            "ftp://x",
            "ci-grid:3000",
            "wss://",
        ],
    )
    def test_models_rejects_non_ws_browser_endpoint(self, endpoint: str) -> None:
        with pytest.raises(pydantic.ValidationError) as excinfo:
            Config(browser_endpoint=endpoint)

        locations = [entry["loc"] for entry in excinfo.value.errors()]
        assert ("browser_endpoint",) in locations

    def test_models_empty_browser_endpoint_means_local_launch(self) -> None:
        assert Config().browser_endpoint == ""
        assert Config(browser_endpoint="").browser_endpoint == ""
