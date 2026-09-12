"""Tests for the settings models of the prettyplay.config cell."""

import inspect

import prettyplay.config
import pydantic
import pytest
from prettyplay.config import BrowserConfig, Config


class TestConfigContract:
    """Contract tests: facade, base class, construction shape, property surface."""

    def test_facade_exports_models_loader_and_error(self) -> None:
        for name in ("BrowserConfig", "PrettyConfig", "Config", "ConfigurationError", "load_config"):
            assert hasattr(prettyplay.config, name), f"missing facade export: {name}"
            assert name in prettyplay.config.__all__

    def test_config_is_pydantic_base_model(self) -> None:
        assert issubclass(Config, pydantic.BaseModel)

    def test_config_is_kw_only(self) -> None:
        assert Config.model_config.get("kw_only") is True

    def test_positional_construction_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            Config("openai")  # type: ignore[misc]

    def test_all_eighteen_properties_accessible(self) -> None:
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
            "classification_prompt",
            "strict",
            "polling_timeout",
            "polling_delay",
            "interactive",
            "generation_attempts",
            "healing_attempts",
            "send_screenshots",
            "effective_generation_model",
            "effective_classification_model",
        ]
        for name in expected:
            assert hasattr(config, name), f"missing property: {name}"

    def test_signature_declares_sixteen_fields_in_contract_order(self) -> None:
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
            "classification_prompt",
            "strict",
            "polling_timeout",
            "polling_delay",
            "interactive",
            "generation_attempts",
            "healing_attempts",
            "send_screenshots",
        ]

    def test_config_defaults_polling_and_interactive_settings(self) -> None:
        """The three new settings: polling off, half-second pause, steering off."""
        config = Config()

        assert config.polling_timeout is None
        assert config.polling_delay == 0.5
        assert config.interactive is False

    def test_polling_and_interactive_field_types_match_contract(self) -> None:
        polling_timeout = Config.model_fields["polling_timeout"]
        polling_delay = Config.model_fields["polling_delay"]
        interactive = Config.model_fields["interactive"]

        assert polling_timeout.annotation == float | None
        assert polling_timeout.default is None
        assert polling_delay.annotation is float
        assert polling_delay.default == 0.5
        assert interactive.annotation is bool
        assert interactive.default is False

    def test_config_carries_nested_group_and_new_switches(self) -> None:
        """The browser group is a BrowserConfig; strict/classification_prompt are new scalar fields."""
        browser = Config.model_fields["browser"]
        strict = Config.model_fields["strict"]
        classification_prompt = Config.model_fields["classification_prompt"]

        assert browser.annotation is BrowserConfig or browser.annotation == BrowserConfig
        assert isinstance(Config().browser, BrowserConfig)
        assert strict.annotation is bool
        assert strict.default is False
        assert classification_prompt.annotation is str
        assert classification_prompt.default == ""
        for removed in ("headless", "browser_endpoint"):
            assert removed not in Config.model_fields, f"flat field survived: {removed}"

    def test_pretty_config_is_config_alias_on_facade(self) -> None:
        assert prettyplay.config.PrettyConfig is Config
        assert "PrettyConfig" in prettyplay.config.__all__

    def test_effective_models_are_properties_not_fields(self) -> None:
        assert isinstance(inspect.getattr_static(Config, "effective_generation_model"), property)
        assert isinstance(inspect.getattr_static(Config, "effective_classification_model"), property)


class TestBrowserConfigContract:
    """Contract tests: the nested browser group model."""

    def test_browser_config_is_pydantic_base_model(self) -> None:
        assert issubclass(BrowserConfig, pydantic.BaseModel)

    def test_browser_config_is_kw_only(self) -> None:
        assert BrowserConfig.model_config.get("kw_only") is True

    def test_browser_config_declares_five_fields_in_contract_order(self) -> None:
        assert list(BrowserConfig.model_fields) == ["name", "screen", "headless", "endpoint", "accept_dialogs"]

    def test_browser_config_accept_dialogs_default_and_explicit(self) -> None:
        """The dialog auto-accept switch: neutral default False, explicit True."""
        assert BrowserConfig().accept_dialogs is False
        assert BrowserConfig(accept_dialogs=True).accept_dialogs is True
        assert Config().browser.accept_dialogs is False

    def test_browser_config_default_is_deep_copied_per_instance(self) -> None:
        first = Config()
        second = Config()

        assert first.browser is not second.browser  # pydantic deep-copies model defaults


class TestConfigLogic:
    """Logic tests: defaults, effective fallbacks, loud validation."""

    def test_config_defaults_valid(self) -> None:
        config = Config()

        assert config.provider == "openai"
        assert config.browser.name == "chromium"
        assert config.generation_attempts == 3
        assert config.healing_attempts == 2
        assert config.send_screenshots is False
        assert config.strict is False
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

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("polling_timeout", -1.0),
            ("polling_delay", -0.5),
            ("polling_timeout", float("inf")),
            ("polling_timeout", float("nan")),
            ("polling_delay", float("inf")),
        ],
    )
    def test_config_rejects_negative_polling_values(self, field: str, value: float) -> None:
        """Negative and non-finite polling values fail loudly naming the field."""
        with pytest.raises(pydantic.ValidationError) as excinfo:
            Config(**{field: value})

        assert field in str(excinfo.value)

    def test_config_zero_polling_values_are_valid(self) -> None:
        """Boundary: an explicit disable (timeout 0) and a zero pause stay legal."""
        config = Config(polling_timeout=0.0, polling_delay=0)

        assert config.polling_timeout == 0.0
        assert config.polling_delay == 0.0

    def test_unknown_browser_fails_loudly(self) -> None:
        with pytest.raises(pydantic.ValidationError) as excinfo:
            Config(browser={"name": "ie"})

        message = str(excinfo.value)
        assert "browser" in message
        assert "chromium" in message

    def test_browser_config_defaults_and_kw_only(self) -> None:
        """Positive: the group defaults and the keyword-only construction."""
        defaults = BrowserConfig()

        assert defaults.name == "chromium"
        assert defaults.screen == ""
        assert defaults.headless is True
        assert defaults.endpoint == ""

        with pytest.raises(TypeError):  # positional rejected — kw_only
            BrowserConfig("chromium")  # type: ignore[misc]

    def test_config_uses_nested_browser_group_and_new_switches(self) -> None:
        """Positive: the dict validates into the group; the new switches ride along."""
        config = Config(
            browser={"name": "firefox", "screen": "1280x720"},
            strict=True,
            classification_prompt="answer in Russian",
        )

        assert config.browser.name == "firefox"
        assert config.browser.screen == "1280x720"
        assert config.browser.headless is True  # untouched group default
        assert config.browser.endpoint == ""
        assert config.strict is True
        assert config.classification_prompt == "answer in Russian"

        assert Config().strict is False
        assert Config().classification_prompt == ""

    def test_browser_channel_values_type_check(self) -> None:
        for name in ("chromium", "firefox", "webkit", "chrome", "msedge"):
            assert BrowserConfig(name=name).name == name

        assert BrowserConfig(headless=False).headless is False

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
        assert BrowserConfig(endpoint=endpoint).endpoint == endpoint

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
            BrowserConfig(endpoint=endpoint)

        locations = [entry["loc"] for entry in excinfo.value.errors()]
        assert ("endpoint",) in locations

    def test_models_empty_browser_endpoint_means_local_launch(self) -> None:
        assert BrowserConfig().endpoint == ""
        assert BrowserConfig(endpoint="").endpoint == ""

    def test_models_screen_passes_non_wxh_values_verbatim(self) -> None:
        """Format-level validation only: fullscreen and device names stay unresolved."""
        assert BrowserConfig(screen="fullscreen").screen == "fullscreen"
        assert BrowserConfig(screen="iPhone 13").screen == "iPhone 13"
        assert BrowserConfig(screen="1280x720").screen == "1280x720"

    def test_models_rejects_non_positive_wxh_screen(self) -> None:
        with pytest.raises(pydantic.ValidationError) as excinfo:
            BrowserConfig(screen="0x720")

        locations = [entry["loc"] for entry in excinfo.value.errors()]
        assert ("screen",) in locations
        assert "must be positive" in str(excinfo.value)
