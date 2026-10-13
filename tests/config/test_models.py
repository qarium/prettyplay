"""Tests for the settings models of the prettyplay.config cell."""

import inspect

import prettyplay.config
import pydantic
import pytest
from prettyplay.config import BrowserConfig, PrettyConfig, models


class TestConfigContract:
    """Contract tests: facade, base class, construction shape, property surface."""

    def test_facade_exports_models_loader_and_error(self) -> None:
        for name in ("BrowserConfig", "PrettyConfig", "ConfigurationError", "load_config"):
            assert hasattr(prettyplay.config, name), f"missing facade export: {name}"
            assert name in prettyplay.config.__all__

    def test_config_is_pydantic_base_model(self) -> None:
        assert issubclass(PrettyConfig, pydantic.BaseModel)

    def test_config_is_kw_only(self) -> None:
        assert PrettyConfig.model_config.get("kw_only") is True

    def test_positional_construction_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            PrettyConfig("openai")  # type: ignore[misc]

    def test_all_twenty_properties_accessible(self) -> None:
        config = PrettyConfig()
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
            "llm_request_attempts",
            "send_screenshots",
            "generation_approve",
            "effective_generation_model",
            "effective_classification_model",
        ]
        for name in expected:
            assert hasattr(config, name), f"missing property: {name}"

    def test_config_llm_request_attempts_field_defaults_and_order(self) -> None:
        """Contract: the transport retry budget defaults to 3 and slots after healing_attempts."""
        assert PrettyConfig().llm_request_attempts == 3

        assert list(PrettyConfig.model_fields)[13:16] == [
            "generation_attempts",
            "healing_attempts",
            "llm_request_attempts",
        ]

    def test_signature_declares_nineteen_fields_in_contract_order(self) -> None:
        fields = PrettyConfig.model_fields
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
            "llm_request_attempts",
            "send_screenshots",
            "generation_approve",
            "probe_timeout",
        ]

    def test_generation_approve_is_a_declared_field(self) -> None:
        """Contract: the compliance gate switch is a model field; the probe bound closes the set."""
        assert "generation_approve" in PrettyConfig.model_fields
        assert list(PrettyConfig.model_fields)[-1] == "probe_timeout"

    def test_probe_timeout_field_type_and_off_default(self) -> None:
        """Contract: the probe bound is a float field of seconds defaulting to off."""
        probe = PrettyConfig.model_fields["probe_timeout"]

        assert probe.annotation is float
        assert probe.default == 0
        assert PrettyConfig().probe_timeout == 0

    def test_probe_timeout_accepts_int_and_float_seconds(self) -> None:
        """Contract: the probe bound accepts int and float seconds alike."""
        assert PrettyConfig(probe_timeout=8).probe_timeout == 8.0
        assert PrettyConfig(probe_timeout=1.5).probe_timeout == 1.5

    @pytest.mark.parametrize("value", [-1, -0.5, float("inf"), float("nan")])
    def test_probe_timeout_rejected_forms_raise_naming_the_value(self, value: object) -> None:
        """Contract: negative and non-finite probe bounds fail loudly, value named."""
        with pytest.raises(pydantic.ValidationError) as excinfo:
            PrettyConfig(probe_timeout=value)

        assert repr(value) in str(excinfo.value)

    def test_config_defaults_polling_and_interactive_settings(self) -> None:
        """The three new settings: polling off, half-second pause, steering off."""
        config = PrettyConfig()

        assert config.polling_timeout is None
        assert config.polling_delay == 0.5
        assert config.interactive is False

    def test_polling_and_interactive_field_types_match_contract(self) -> None:
        polling_timeout = PrettyConfig.model_fields["polling_timeout"]
        polling_delay = PrettyConfig.model_fields["polling_delay"]
        interactive = PrettyConfig.model_fields["interactive"]

        assert polling_timeout.annotation == float | None
        assert polling_timeout.default is None
        assert polling_delay.annotation is float
        assert polling_delay.default == 0.5
        assert interactive.annotation is bool
        assert interactive.default is False

    def test_config_carries_nested_group_and_new_switches(self) -> None:
        """The browser group is a BrowserConfig; strict/classification_prompt are new scalar fields."""
        browser = PrettyConfig.model_fields["browser"]
        strict = PrettyConfig.model_fields["strict"]
        classification_prompt = PrettyConfig.model_fields["classification_prompt"]

        assert browser.annotation is BrowserConfig or browser.annotation == BrowserConfig
        assert isinstance(PrettyConfig().browser, BrowserConfig)
        assert strict.annotation is bool
        assert strict.default is False
        assert classification_prompt.annotation is str
        assert classification_prompt.default == ""
        for removed in ("headless", "browser_endpoint"):
            assert removed not in PrettyConfig.model_fields, f"flat field survived: {removed}"

    def test_pretty_config_is_the_same_model_on_facade(self) -> None:
        assert prettyplay.config.PrettyConfig is PrettyConfig
        assert "PrettyConfig" in prettyplay.config.__all__

    def test_pretty_config_is_the_canonical_model_without_a_legacy_alias(self) -> None:
        """Verify the canonical settings class and the removal of the legacy alias."""
        assert prettyplay.PrettyConfig is prettyplay.config.PrettyConfig
        assert prettyplay.config.PrettyConfig.__name__ == "PrettyConfig"
        assert models.PrettyConfig is prettyplay.config.PrettyConfig
        assert not hasattr(models, "Config")
        assert not hasattr(prettyplay.config, "Config")
        assert len(prettyplay.config.__all__) == len(set(prettyplay.config.__all__))

    def test_effective_models_are_properties_not_fields(self) -> None:
        assert isinstance(inspect.getattr_static(PrettyConfig, "effective_generation_model"), property)
        assert isinstance(inspect.getattr_static(PrettyConfig, "effective_classification_model"), property)


class TestBrowserConfigContract:
    """Contract tests: the nested browser group model."""

    def test_browser_config_is_pydantic_base_model(self) -> None:
        assert issubclass(BrowserConfig, pydantic.BaseModel)

    def test_browser_config_is_kw_only(self) -> None:
        assert BrowserConfig.model_config.get("kw_only") is True

    def test_browser_config_declares_seven_fields_in_contract_order(self) -> None:
        assert list(BrowserConfig.model_fields) == [
            "name",
            "screen",
            "headless",
            "endpoint",
            "accept_dialogs",
            "speed",
            "timeout",
        ]

    def test_browser_config_timeout_field_type_and_explicit_default(self) -> None:
        """Contract: the page action timeout is a float field of seconds defaulting to 30."""
        timeout = BrowserConfig.model_fields["timeout"]

        assert timeout.annotation is float
        assert timeout.default == 30
        assert BrowserConfig().timeout == 30
        assert PrettyConfig().browser.timeout == 30

    def test_browser_config_timeout_accepts_int_float_and_the_real_zero(self) -> None:
        """Contract: the baseline accepts int and float seconds; 0 is the legal real zero."""
        assert BrowserConfig(timeout=60).timeout == 60.0
        assert BrowserConfig(timeout=2.5).timeout == 2.5
        assert BrowserConfig(timeout=0).timeout == 0.0

    @pytest.mark.parametrize("value", [-1, -0.5, float("inf"), float("nan")])
    def test_browser_config_timeout_rejected_forms_raise_naming_the_value(self, value: object) -> None:
        """Contract: negative and non-finite baselines fail loudly, value named."""
        with pytest.raises(pydantic.ValidationError) as excinfo:
            BrowserConfig(timeout=value)

        assert repr(value) in str(excinfo.value)

    def test_browser_config_speed_field_type_and_full_speed_default(self) -> None:
        """Contract: the pace setting is an int field defaulting to full speed."""
        speed = BrowserConfig.model_fields["speed"]

        assert speed.annotation is int
        assert speed.default == 100
        assert BrowserConfig().speed == 100
        assert PrettyConfig().browser.speed == 100

    def test_browser_config_speed_bounds_zero_and_hundred_pass(self) -> None:
        """Contract: both ends of the 0-100 range are legal paces."""
        assert BrowserConfig(speed=0).speed == 0
        assert BrowserConfig(speed=100).speed == 100

    @pytest.mark.parametrize("value", [-1, 101, True, "fast", 1.5])
    def test_browser_config_speed_rejected_forms_raise_naming_the_value(self, value: object) -> None:
        """Contract: out-of-range, boolean and non-integer paces fail loudly, value named."""
        with pytest.raises(pydantic.ValidationError) as excinfo:
            BrowserConfig(speed=value)

        assert repr(value) in str(excinfo.value)

    def test_browser_config_accept_dialogs_default_and_explicit(self) -> None:
        """The dialog auto-accept switch: neutral default False, explicit True."""
        assert BrowserConfig().accept_dialogs is False
        assert BrowserConfig(accept_dialogs=True).accept_dialogs is True
        assert PrettyConfig().browser.accept_dialogs is False

    def test_browser_config_default_is_deep_copied_per_instance(self) -> None:
        first = PrettyConfig()
        second = PrettyConfig()

        assert first.browser is not second.browser  # pydantic deep-copies model defaults


class TestConfigLogic:
    """Logic tests: defaults, effective fallbacks, loud validation."""

    def test_config_defaults_valid(self) -> None:
        config = PrettyConfig()

        assert config.provider == "openai"
        assert config.browser.name == "chromium"
        assert config.generation_attempts == 3
        assert config.healing_attempts == 2
        assert config.send_screenshots is False
        assert config.strict is False
        assert config.effective_generation_model == config.model == ""

    def test_generation_approve_defaults_true(self) -> None:
        """The gate switch carries the opt-out default — loud errors unless disabled."""
        assert PrettyConfig().generation_approve is True
        assert PrettyConfig(generation_approve=False).generation_approve is False

    def test_config_invalid_provider_fails_loudly(self) -> None:
        with pytest.raises(pydantic.ValidationError) as excinfo:
            PrettyConfig(provider="yandex")

        message = str(excinfo.value)
        assert "provider" in message
        assert "openai" in message
        assert "anthropic" in message

    def test_effective_models_fall_back_to_main_model(self) -> None:
        config = PrettyConfig(model="gpt-5", generation_model="gpt-5-mini", classification_model="")

        assert config.effective_generation_model == "gpt-5-mini"
        assert config.effective_classification_model == "gpt-5"

    def test_zero_generation_attempts_fails_with_field_name(self) -> None:
        with pytest.raises(pydantic.ValidationError) as excinfo:
            PrettyConfig(generation_attempts=0)

        assert "generation_attempts" in str(excinfo.value)

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(0, id="zero"),
            pytest.param(-1, id="negative"),
        ],
    )
    def test_config_rejects_llm_request_attempts_below_one(self, value: int) -> None:
        """Negative: a sub-one budget fails loudly naming the field and the received value."""
        with pytest.raises(pydantic.ValidationError) as excinfo:
            PrettyConfig(llm_request_attempts=value)

        message = str(excinfo.value)
        assert "llm_request_attempts" in message
        assert repr(value) in message

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("polling_timeout", -1.0),
            ("polling_delay", -0.5),
            ("polling_timeout", float("inf")),
            ("polling_timeout", float("nan")),
            ("polling_delay", float("inf")),
            ("polling_delay", float("nan")),
        ],
    )
    def test_config_rejects_negative_polling_values(self, field: str, value: float) -> None:
        """Negative and non-finite polling values fail loudly naming the field."""
        with pytest.raises(pydantic.ValidationError) as excinfo:
            PrettyConfig(**{field: value})

        assert field in str(excinfo.value)

    def test_config_zero_polling_values_are_valid(self) -> None:
        """Boundary: an explicit disable (timeout 0) and a zero pause stay legal."""
        config = PrettyConfig(polling_timeout=0.0, polling_delay=0)

        assert config.polling_timeout == 0.0
        assert config.polling_delay == 0.0

    def test_unknown_browser_fails_loudly(self) -> None:
        with pytest.raises(pydantic.ValidationError) as excinfo:
            PrettyConfig(browser={"name": "ie"})

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
        config = PrettyConfig(
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

        assert PrettyConfig().strict is False
        assert PrettyConfig().classification_prompt == ""

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

    def test_browser_speed_forty_accepted_and_readable_through_config(self) -> None:
        """Positive: a mid-range pace validates and reads through the nested group."""
        assert BrowserConfig(speed=40).speed == 40

        config = PrettyConfig(browser=BrowserConfig(speed=40))

        assert config.browser.speed == 40
        assert PrettyConfig(browser={"speed": 40}).browser.speed == 40

    def test_browser_speed_bounds_stay_legal_through_the_group(self) -> None:
        """Edge: 0 — the slowest supported pace, 100 — full speed; both construct."""
        assert PrettyConfig(browser={"speed": 0}).browser.speed == 0
        assert PrettyConfig(browser={"speed": 100}).browser.speed == 100

    @pytest.mark.parametrize("value", [-1, 101, True, False, "fast", "40", 1.5, None])
    def test_browser_speed_loud_message_names_every_rejected_form(self, value: object) -> None:
        """Negative: every rejected pace names the received value and the allowed range."""
        with pytest.raises(pydantic.ValidationError) as excinfo:
            BrowserConfig(speed=value)

        message = str(excinfo.value)

        assert repr(value) in message
        assert "0-100" in message
