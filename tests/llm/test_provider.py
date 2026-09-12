"""Tests for the LLMProvider port and the create_provider factory of the prettyplay.llm cell."""

import inspect
from types import SimpleNamespace
from unittest import mock

import pytest
from prettyplay.config import Config
from prettyplay.llm import AnthropicProvider, LLMProvider, OpenAIProvider, create_provider

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
    "recommendation",
    "guidance",
    "guidance_history",
]
CLASSIFY_FAILURE_PARAMS = [
    "self",
    "prompt",
    "user_instructions",
    "step_text",
    "code",
    "error",
    "snapshot",
    "screenshot",
]


class TestLLMProviderContract:
    """Contract tests: facade import, exact port signatures, base bodies raise."""

    def test_port_importable_from_facade(self) -> None:
        assert isinstance(LLMProvider, type)

    def test_factory_importable_from_facade(self) -> None:
        assert callable(create_provider)

    def test_generate_step_code_signature(self) -> None:
        signature = inspect.signature(LLMProvider.generate_step_code)

        assert list(signature.parameters) == GENERATE_STEP_CODE_PARAMS
        assert signature.return_annotation is str

    def test_classify_failure_signature(self) -> None:
        signature = inspect.signature(LLMProvider.classify_failure)

        assert list(signature.parameters) == CLASSIFY_FAILURE_PARAMS
        assert signature.return_annotation is not inspect.Signature.empty

    def test_classify_failure_signature_carries_user_instructions(self) -> None:
        for owner in (LLMProvider, OpenAIProvider, AnthropicProvider):
            parameters = inspect.signature(owner.classify_failure).parameters
            names = list(parameters)

            assert names[names.index("prompt") + 1] == "user_instructions", owner.__name__
            assert parameters["user_instructions"].annotation is str, owner.__name__

    def test_generate_step_code_signature_carries_the_steering_inputs(self) -> None:
        for owner in (LLMProvider, OpenAIProvider, AnthropicProvider):
            parameters = inspect.signature(owner.generate_step_code).parameters
            names = list(parameters)

            expected_tail = ["recommendation", "guidance", "guidance_history"]
            assert names[names.index("error") + 1 :] == expected_tail, owner.__name__
            assert parameters["recommendation"].annotation == parameters["existing_code"].annotation, owner.__name__
            assert parameters["guidance"].annotation == parameters["existing_code"].annotation, owner.__name__
            assert parameters["guidance_history"].annotation == parameters["previous_steps"].annotation, owner.__name__
            for name in ("recommendation", "guidance", "guidance_history"):
                assert parameters[name].default is inspect.Signature.empty, (owner.__name__, name)

    def test_base_methods_raise_not_implemented(self) -> None:
        port = LLMProvider()

        with pytest.raises(NotImplementedError):
            port.generate_step_code(
                prompt="p",
                user_instructions="",
                step_text="s",
                previous_steps=[],
                snapshot="- snap",
                screenshot=None,
                page_api="page.goto(...)",
                existing_code=None,
                error=None,
                recommendation=None,
                guidance=None,
                guidance_history=[],
            )

        with pytest.raises(NotImplementedError):
            port.classify_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )


class TestSkeletonImplementationsContract:
    """Contract tests: both skeletons subclass the port and store the config."""

    def test_openai_provider_is_an_llm_provider(self) -> None:
        assert issubclass(OpenAIProvider, LLMProvider)

    def test_anthropic_provider_is_an_llm_provider(self) -> None:
        assert issubclass(AnthropicProvider, LLMProvider)

    def test_constructors_take_config_without_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        OpenAIProvider(Config())  # constructs without exceptions
        AnthropicProvider(Config())


class TestCreateProviderLogic:
    """Logic tests: factory selection by config; unknown value fails loudly."""

    def test_create_provider_selects_by_config(self) -> None:
        anthropic = create_provider(Config(provider="anthropic", model="claude-sonnet-4-5"))
        openai = create_provider(Config(provider="openai", model="gpt-5"))

        assert isinstance(anthropic, AnthropicProvider)
        assert isinstance(anthropic, LLMProvider)  # port contract

        assert isinstance(openai, OpenAIProvider)  # symmetric case
        assert isinstance(openai, LLMProvider)

    def test_create_provider_returns_fresh_instance(self) -> None:
        first = create_provider(Config(provider="openai"))
        second = create_provider(Config(provider="openai"))

        assert first is not second

    def test_create_provider_unknown_fails_loudly(self) -> None:
        config = Config.model_construct(provider="groq")  # validation bypassed intentionally:
        # Literal would otherwise reject the value

        with pytest.raises(ValueError, match="unsupported provider") as excinfo:
            create_provider(config)

        assert "openai" in str(excinfo.value)
        assert "anthropic" in str(excinfo.value)


class TestInitialismRenames:
    """Contract tests: the initialism renames are total — no old spellings survive."""

    def test_provider_renames_are_total(self) -> None:
        import prettyplay.failures  # noqa: PLC0415 — cell facade checks
        import prettyplay.llm  # noqa: PLC0415 — cell facade checks

        assert hasattr(prettyplay.failures, "LLMUnavailableError")
        with pytest.raises(AttributeError):
            getattr(prettyplay.failures, "Llm" + "UnavailableError")

        assert hasattr(prettyplay.llm, "LLMProvider")
        assert hasattr(prettyplay.llm, "OpenAIProvider")
        assert hasattr(prettyplay.llm, "create_provider")
        with pytest.raises(AttributeError):
            getattr(prettyplay.llm, "Llm" + "Provider")
        with pytest.raises(AttributeError):
            getattr(prettyplay.llm, "OpenAi" + "Provider")

        provider = create_provider(Config(provider="openai"))
        assert isinstance(provider, prettyplay.llm.OpenAIProvider)
        assert isinstance(provider, prettyplay.llm.LLMProvider)


CLASSIFICATION_ANSWER = "rot | explanation | recommendation"
GENERATION_ANSWER = "def step(page) -> None:\n    pass\n"


def _openai_client(answer: str) -> tuple[object, list[dict]]:
    """Build a fake openai SDK client capturing every request payload.

    Returns:
        The fake client and the list the request payloads get appended to.
    """
    requests: list[dict] = []
    message = SimpleNamespace(content=answer)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    create = mock.MagicMock(return_value=response, side_effect=lambda **kwargs: requests.append(kwargs) or response)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), requests


def _anthropic_client(answer: str) -> tuple[object, list[dict]]:
    """Build a fake anthropic SDK client capturing every request payload.

    Returns:
        The fake client and the list the request payloads get appended to.
    """
    requests: list[dict] = []
    response = SimpleNamespace(content=[SimpleNamespace(type="text", text=answer)])
    create = mock.MagicMock(return_value=response, side_effect=lambda **kwargs: requests.append(kwargs) or response)
    return SimpleNamespace(messages=SimpleNamespace(create=create)), requests


class TestClassificationInstructionsPlacement:
    """Logic tests: the USER INSTRUCTIONS block reaches classification requests identically."""

    def test_provider_classification_instructions_placement_parity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

        cases = (
            (OpenAIProvider(Config(model="gpt-5")), _openai_client),
            (AnthropicProvider(Config(model="claude-sonnet-4-5")), _anthropic_client),
        )

        for provider, make_client in cases:
            # classification with instructions: the block is the last section of the user content
            client, requests = make_client(CLASSIFICATION_ANSWER)

            with mock.patch.object(provider, "_get_client", return_value=client):
                classification = provider.classify_failure(
                    prompt="sys",
                    user_instructions="be terse",
                    step_text="s",
                    code="c",
                    error="e",
                    snapshot="snap",
                    screenshot=None,
                )

            assert classification.category == "rot"
            user_content = requests[0]["messages"][-1]["content"]
            assert user_content.endswith("USER INSTRUCTIONS:\nbe terse")
            assert user_content.index("PAGE SNAPSHOT:") < user_content.index("USER INSTRUCTIONS:")

            # classification without instructions: byte-identical to the old request form
            empty_client, empty_requests = make_client(CLASSIFICATION_ANSWER)

            with mock.patch.object(provider, "_get_client", return_value=empty_client):
                provider.classify_failure(
                    prompt="sys",
                    user_instructions="",
                    step_text="s",
                    code="c",
                    error="e",
                    snapshot="snap",
                    screenshot=None,
                )

            assert "USER INSTRUCTIONS" not in empty_requests[0]["messages"][-1]["content"]

            # generation placement is unchanged: after PAGE API, before CODE/ERROR
            gen_client, gen_requests = make_client(GENERATION_ANSWER)

            with mock.patch.object(provider, "_get_client", return_value=gen_client):
                provider.generate_step_code(
                    prompt="sys",
                    user_instructions="be terse",
                    step_text="s",
                    previous_steps=[],
                    snapshot="snap",
                    screenshot=None,
                    page_api="page.goto(...)",
                    existing_code="def step(page) -> None:\n    pass\n",
                    error="err",
                    recommendation=None,
                    guidance=None,
                    guidance_history=[],
                )

            gen_user = gen_requests[0]["messages"][-1]["content"]
            assert gen_user.index("PAGE API:") < gen_user.index("USER INSTRUCTIONS:") < gen_user.index("CODE:")


class TestSteeringInputsParity:
    """Logic tests: both providers forward the three steering inputs to one builder output."""

    def test_providers_render_identical_user_text_from_the_steering_inputs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

        user_texts = []

        for provider, make_client in (
            (OpenAIProvider(Config(model="gpt-5")), _openai_client),
            (AnthropicProvider(Config(model="claude-sonnet-4-5")), _anthropic_client),
        ):
            client, requests = make_client(GENERATION_ANSWER)

            with mock.patch.object(provider, "_get_client", return_value=client):
                provider.generate_step_code(
                    prompt="sys",
                    user_instructions="be terse",
                    step_text="s",
                    previous_steps=["step one"],
                    snapshot="snap",
                    screenshot=None,
                    page_api="page.goto(...)",
                    existing_code="old code",
                    error="err",
                    recommendation="use a role locator",
                    guidance="dismiss the modal first",
                    guidance_history=["hover first => Timeout 10000ms exceeded"],
                )

            user_texts.append(requests[0]["messages"][-1]["content"])

        # parity: one shared builder — identical inputs render identical user text
        assert user_texts[0] == user_texts[1]
        assert "RECOMMENDATION:\nuse a role locator" in user_texts[0]
        assert "USER GUIDANCE:\ndismiss the modal first" in user_texts[0]
        assert "HISTORY:\nhover first => Timeout 10000ms exceeded" in user_texts[0]
