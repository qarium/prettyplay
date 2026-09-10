"""Tests for the LlmProvider port and the create_provider factory of the prettyplay.llm cell."""

import inspect

import pytest
from prettyplay.config import Config
from prettyplay.llm import AnthropicProvider, LlmProvider, OpenAiProvider, create_provider

GENERATE_STEP_CODE_PARAMS = [
    "self",
    "prompt",
    "user_instructions",
    "step_text",
    "previous_steps",
    "snapshot",
    "screenshot",
    "page_api",
    "existing_code",
    "error",
]
CLASSIFY_FAILURE_PARAMS = ["self", "prompt", "step_text", "code", "error", "snapshot", "screenshot"]


class TestLlmProviderContract:
    """Contract tests: facade import, exact port signatures, base bodies raise."""

    def test_port_importable_from_facade(self) -> None:
        assert isinstance(LlmProvider, type)

    def test_factory_importable_from_facade(self) -> None:
        assert callable(create_provider)

    def test_generate_step_code_signature(self) -> None:
        signature = inspect.signature(LlmProvider.generate_step_code)

        assert list(signature.parameters) == GENERATE_STEP_CODE_PARAMS
        assert signature.return_annotation is str

    def test_classify_failure_signature(self) -> None:
        signature = inspect.signature(LlmProvider.classify_failure)

        assert list(signature.parameters) == CLASSIFY_FAILURE_PARAMS
        assert signature.return_annotation is not inspect.Signature.empty

    def test_base_methods_raise_not_implemented(self) -> None:
        port = LlmProvider()

        with pytest.raises(NotImplementedError):
            port.generate_step_code(
                prompt="p",
                user_instructions="",
                step_text="s",
                previous_steps=[],
                snapshot="- snap",
                screenshot=None,
                page_api="page.open(...)",
                existing_code=None,
                error=None,
            )

        with pytest.raises(NotImplementedError):
            port.classify_failure(prompt="p", step_text="s", code="c", error="e", snapshot="- snap", screenshot=None)


class TestSkeletonImplementationsContract:
    """Contract tests: both skeletons subclass the port and store the config."""

    def test_openai_provider_is_an_llm_provider(self) -> None:
        assert issubclass(OpenAiProvider, LlmProvider)

    def test_anthropic_provider_is_an_llm_provider(self) -> None:
        assert issubclass(AnthropicProvider, LlmProvider)

    def test_constructors_take_config_without_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        OpenAiProvider(Config())  # конструкция без исключений
        AnthropicProvider(Config())


class TestCreateProviderLogic:
    """Logic tests: factory selection by config; unknown value fails loudly."""

    def test_create_provider_selects_by_config(self) -> None:
        anthropic = create_provider(Config(provider="anthropic", model="claude-sonnet-4-5"))
        openai = create_provider(Config(provider="openai", model="gpt-5"))

        assert isinstance(anthropic, AnthropicProvider)
        assert isinstance(anthropic, LlmProvider)  # контракт порта

        assert isinstance(openai, OpenAiProvider)  # симметричный случай
        assert isinstance(openai, LlmProvider)

    def test_create_provider_returns_fresh_instance(self) -> None:
        first = create_provider(Config(provider="openai"))
        second = create_provider(Config(provider="openai"))

        assert first is not second

    def test_create_provider_unknown_fails_loudly(self) -> None:
        config = Config.model_construct(provider="groq")  # валидация обойдена намеренно:
        # Literal иначе не пропустит значение

        with pytest.raises(ValueError, match="unsupported provider") as excinfo:
            create_provider(config)

        assert "openai" in str(excinfo.value)
        assert "anthropic" in str(excinfo.value)
