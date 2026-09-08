"""Tests for the Config model of the prettyplay.config cell."""

import inspect

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

    def test_all_twelve_properties_accessible(self) -> None:
        config = Config()
        expected = [
            "provider",
            "browser",
            "model",
            "generation_model",
            "classification_model",
            "base_url",
            "cache_root",
            "generation_attempts",
            "healing_attempts",
            "send_screenshots",
            "effective_generation_model",
            "effective_classification_model",
        ]
        for name in expected:
            assert hasattr(config, name), f"missing property: {name}"

    def test_signature_declares_ten_fields(self) -> None:
        fields = Config.model_fields
        expected = {
            "provider",
            "browser",
            "model",
            "generation_model",
            "classification_model",
            "base_url",
            "cache_root",
            "generation_attempts",
            "healing_attempts",
            "send_screenshots",
        }
        assert expected == set(fields.keys())

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
