"""Tests for the LLMProvider port and the create_provider factory of the prettyplay.llm cell."""

import inspect
from types import SimpleNamespace
from typing import ClassVar
from unittest import mock

import pytest
from prettyplay.config import Config
from prettyplay.llm import AnthropicProvider, LLMProvider, OpenAIProvider, create_provider

GENERATE_STEP_CODE_PARAMS = [
    "self",
    "prompt",
    "user_instructions",
    "step_text",
    "step_type",
    "previous_steps",
    "snapshot",
    "page_url",
    "screenshot",
    "cheat_sheet",
    "attempt_history",
    "recommendation",
    "guidance",
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
CHECK_INSTRUCTION_COMPLIANCE_PARAMS = [
    "self",
    "prompt",
    "user_instructions",
    "step_text",
    "step_type",
    "code",
    "attempt_history",
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

    def test_check_instruction_compliance_signature(self) -> None:
        signature = inspect.signature(LLMProvider.check_instruction_compliance)

        assert list(signature.parameters) == CHECK_INSTRUCTION_COMPLIANCE_PARAMS
        assert signature.return_annotation is not inspect.Signature.empty

    def test_check_instruction_compliance_signature_on_every_implementation(self) -> None:
        for owner in (LLMProvider, OpenAIProvider, AnthropicProvider):
            assert list(inspect.signature(owner.check_instruction_compliance).parameters) == (
                CHECK_INSTRUCTION_COMPLIANCE_PARAMS
            ), owner.__name__

    def test_classify_failure_signature_carries_user_instructions(self) -> None:
        for owner in (LLMProvider, OpenAIProvider, AnthropicProvider):
            parameters = inspect.signature(owner.classify_failure).parameters
            names = list(parameters)

            assert names[names.index("prompt") + 1] == "user_instructions", owner.__name__
            assert parameters["user_instructions"].annotation is str, owner.__name__

    def test_generate_step_code_signature_carries_the_new_inputs(self) -> None:
        for owner in (LLMProvider, OpenAIProvider, AnthropicProvider):
            parameters = inspect.signature(owner.generate_step_code).parameters
            names = list(parameters)

            expected_tail = ["attempt_history", "recommendation", "guidance"]
            assert names[names.index("cheat_sheet") + 1 :] == expected_tail, owner.__name__
            assert parameters["step_type"].annotation is str, owner.__name__
            assert parameters["attempt_history"].annotation == parameters["previous_steps"].annotation, owner.__name__
            assert parameters["recommendation"].annotation == parameters["page_url"].annotation, owner.__name__
            assert parameters["guidance"].annotation == parameters["page_url"].annotation, owner.__name__
            for name in ("step_type", "attempt_history", "recommendation", "guidance"):
                assert parameters[name].default is inspect.Signature.empty, (owner.__name__, name)

    def test_generate_step_code_signature_drops_the_removed_regeneration_inputs(self) -> None:
        for owner in (LLMProvider, OpenAIProvider, AnthropicProvider):
            names = list(inspect.signature(owner.generate_step_code).parameters)

            assert "existing_code" not in names, owner.__name__  # the removed inputs are gone, not optional
            assert "error" not in names, owner.__name__
            assert "guidance_history" not in names, owner.__name__

    def test_check_instruction_compliance_signature_carries_the_new_inputs(self) -> None:
        for owner in (LLMProvider, OpenAIProvider, AnthropicProvider):
            parameters = inspect.signature(owner.check_instruction_compliance).parameters

            assert parameters["step_type"].annotation is str, owner.__name__
            assert parameters["attempt_history"].annotation == list[str], owner.__name__
            for name in ("step_type", "code", "attempt_history"):
                assert parameters[name].default is inspect.Signature.empty, (owner.__name__, name)

    def test_generate_step_code_signature_carries_cheat_sheet_after_screenshot(self) -> None:
        for owner in (LLMProvider, OpenAIProvider, AnthropicProvider):
            parameters = inspect.signature(owner.generate_step_code).parameters
            names = list(parameters)

            assert "cheat_sheet" in names, owner.__name__
            assert ("page" + "_api") not in names, owner.__name__  # the dead slot name, assembled — no literal
            assert names[names.index("screenshot") + 1] == "cheat_sheet", owner.__name__
            assert names[names.index("cheat_sheet") + 1] == "attempt_history", owner.__name__
            assert parameters["cheat_sheet"].annotation is str, owner.__name__

    def test_base_methods_raise_not_implemented(self) -> None:
        port = LLMProvider()

        with pytest.raises(NotImplementedError):
            port.generate_step_code(
                prompt="p",
                user_instructions="",
                step_text="s",
                step_type="action",
                previous_steps=[],
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
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

        with pytest.raises(NotImplementedError):
            port.check_instruction_compliance(
                prompt="p",
                user_instructions="i",
                step_text="s",
                step_type="action",
                code="c",
                attempt_history=[],
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

            # generation placement: after CHEAT SHEET, before the HISTORY block
            gen_client, gen_requests = make_client(GENERATION_ANSWER)

            with mock.patch.object(provider, "_get_client", return_value=gen_client):
                provider.generate_step_code(
                    prompt="sys",
                    user_instructions="be terse",
                    step_text="s",
                    step_type="action",
                    previous_steps=[],
                    snapshot="snap",
                    page_url=None,
                    screenshot=None,
                    cheat_sheet="expect(locator).to_be_visible()",
                    attempt_history=["execution failed\nurl: https://a.example -> https://b.example"],
                    recommendation=None,
                    guidance=None,
                )

            gen_user = gen_requests[0]["messages"][-1]["content"]
            assert gen_user.index("CHEAT SHEET:") < gen_user.index("USER INSTRUCTIONS:") < gen_user.index("HISTORY:")


class TestNewInputsParity:
    """Logic tests: both providers render identical user content for the new inputs."""

    PAGE_URL = "https://www.google.com/sorry?continuation=token"
    ATTEMPT_RECORDS: ClassVar[list[str]] = [
        (
            "original cached code\n"
            "url: https://a.example -> https://a.example\n"
            "code:\ndef step(page) -> None:\n    ...\n"
            "error:\nAssertionError: Locator expected to be visible"
        ),
        (
            "execution failed\n"
            "url: https://a.example -> https://b.example\n"
            "code:\ndef step(page) -> None:\n    ...\n"
            "error:\nRuntimeError: click timed out"
        ),
    ]
    VERDICT_ANSWER = (
        '[{"instruction": "Prefer id attributes", "priority": "high", "explanation": "locates by text",'
        ' "dimension": "instruction"}]'
    )

    def test_providers_render_identical_user_content_for_the_new_inputs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

        generation_texts = []
        compliance_texts = []

        for provider, make_client in (
            (OpenAIProvider(Config(model="gpt-5")), _openai_client),
            (AnthropicProvider(Config(model="claude-sonnet-4-5")), _anthropic_client),
        ):
            gen_client, gen_requests = make_client(GENERATION_ANSWER)

            with mock.patch.object(provider, "_get_client", return_value=gen_client):
                provider.generate_step_code(
                    prompt="sys",
                    user_instructions="be terse",
                    step_text="s",
                    step_type="assertion",
                    previous_steps=["step one"],
                    snapshot="snap",
                    page_url=self.PAGE_URL,
                    screenshot=None,
                    cheat_sheet="expect(locator).to_be_visible()",
                    attempt_history=self.ATTEMPT_RECORDS,
                    recommendation="use a role locator",
                    guidance="dismiss the modal first",
                )

            generation_texts.append(gen_requests[0]["messages"][-1]["content"])

            gate_client, gate_requests = make_client(self.VERDICT_ANSWER)

            with mock.patch.object(provider, "_get_client", return_value=gate_client):
                provider.check_instruction_compliance(
                    prompt="gate",
                    user_instructions="be terse",
                    step_text="s",
                    step_type="assertion",
                    code="def step(page) -> None:\n    ...\n",
                    attempt_history=self.ATTEMPT_RECORDS,
                )

            compliance_texts.append(gate_requests[0]["messages"][-1]["content"])

        # parity: one shared builder — identical inputs render identical user text, field for field
        assert generation_texts[0] == generation_texts[1]
        assert compliance_texts[0] == compliance_texts[1]

        for text in generation_texts:
            assert "STEP TYPE: assertion\nSTEP:\ns" in text
            assert f"HISTORY:\n{self.ATTEMPT_RECORDS[0]}\n{self.ATTEMPT_RECORDS[1]}" in text
            assert text.index("USER INSTRUCTIONS:") < text.index("HISTORY:") < text.index("RECOMMENDATION:")
            assert "RECOMMENDATION:\nuse a role locator" in text
            assert "USER GUIDANCE:\ndismiss the modal first" in text
            assert f"PAGE URL: {self.PAGE_URL}" in text
            assert text.index("PAGE SNAPSHOT:\nsnap") < text.index(f"PAGE URL: {self.PAGE_URL}")
            assert text.index(f"PAGE URL: {self.PAGE_URL}") < text.index("CHEAT SHEET:")

        for text in compliance_texts:
            assert "STEP TYPE: assertion\nSTEP:\ns" in text
            assert f"ATTEMPT HISTORY:\n{self.ATTEMPT_RECORDS[0]}\n{self.ATTEMPT_RECORDS[1]}" in text
            assert (
                text.index("INSTRUCTIONS:")
                < text.index("STEP TYPE:")
                < text.index("ATTEMPT HISTORY:")
                < text.index("CODE:")
            )
