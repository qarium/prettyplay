"""Tests for the AnthropicProvider implementation of the prettyplay.llm cell."""

import base64
import inspect
import logging
from types import SimpleNamespace
from unittest import mock

import pytest
from anthropic import AnthropicError, APIConnectionError, AuthenticationError
from prettyplay.config import Config
from prettyplay.failures import ComplianceVerdictError, LLMUnavailableError, PrettyplayError
from prettyplay.llm import (
    AnthropicProvider,
    LLMProvider,
    ScenarioStep,
    anthropic_provider,
    classify_anthropic_failure,
)
from prettyplay.llm._request import build_compliance_fields

GENERATE_STEP_CODE_PARAMS = [
    "self",
    "prompt",
    "user_instructions",
    "instruction",
    "step_type",
    "previous_steps",
    "group_prompt",
    "inputs",
    "declarations",
    "snapshot",
    "page_url",
    "screenshot",
    "cheat_sheet",
    "attempt_history",
    "recommendation",
    "guidance",
]
CLASSIFY_STEP_FAILURE_PARAMS = [
    "self",
    "prompt",
    "user_instructions",
    "step_text",
    "code",
    "error",
    "snapshot",
    "screenshot",
]
CLASSIFY_GROUP_FAILURE_PARAMS = [
    "self",
    "prompt",
    "user_instructions",
    "group_prompt",
    "group_steps",
    "previous_steps",
    "step_text",
    "attempt_history",
    "snapshot",
    "screenshot",
]
CHECK_INSTRUCTION_COMPLIANCE_PARAMS = [
    "self",
    "prompt",
    "user_instructions",
    "instruction",
    "step_type",
    "inputs",
    "declarations",
    "code",
    "attempt_history",
]

WORKING_CODE = "def step(page) -> None:\n    page.goto('https://example.com')\n"
USER_INSTRUCTIONS = "prefer data-test-id"


def make_client_create(answer: str = WORKING_CODE) -> tuple[object, list[dict]]:
    """Build a fake SDK client whose messages.create returns the answer.

    Returns:
        The fake client and the list the request payloads get appended to.
    """
    requests: list[dict] = []
    response = SimpleNamespace(content=[text_block(answer)])
    create = mock.MagicMock(return_value=response, side_effect=lambda **kwargs: requests.append(kwargs) or response)
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return client, requests


def make_client_returning(response: object) -> object:
    """Build a fake SDK client whose messages.create returns the raw response."""
    create = mock.MagicMock(return_value=response)
    return SimpleNamespace(messages=SimpleNamespace(create=create))


def text_block(answer: str) -> SimpleNamespace:
    """Build a fake anthropic text content block carrying the answer."""
    return SimpleNamespace(type="text", text=answer)


def make_status_error(error_class: type[Exception], status: int, headers: dict | None = None) -> Exception:
    """Build an SDK status error over a faked response for the transport wiring tests."""
    response = SimpleNamespace(status_code=status, headers=headers or {}, request=SimpleNamespace())

    return error_class("boom", response=response, body=None)


class TestAnthropicProviderContract:
    """Contract tests: facade import, port membership, exact signatures, lazy env."""

    def test_importable_from_facade(self) -> None:
        assert isinstance(AnthropicProvider, type)

    def test_is_an_llm_provider(self) -> None:
        assert issubclass(AnthropicProvider, LLMProvider)

    def test_generate_step_code_signature_matches_port(self) -> None:
        signature = inspect.signature(AnthropicProvider.generate_step_code)

        assert list(signature.parameters) == GENERATE_STEP_CODE_PARAMS
        assert signature.return_annotation is str

    def test_classify_step_failure_signature_matches_port(self) -> None:
        signature = inspect.signature(AnthropicProvider.classify_step_failure)

        assert list(signature.parameters) == CLASSIFY_STEP_FAILURE_PARAMS
        assert signature.return_annotation is not inspect.Signature.empty

    def test_classify_group_failure_signature_matches_port(self) -> None:
        signature = inspect.signature(AnthropicProvider.classify_group_failure)

        assert list(signature.parameters) == CLASSIFY_GROUP_FAILURE_PARAMS
        assert signature.return_annotation is not inspect.Signature.empty

    def test_the_old_classify_failure_name_is_gone(self) -> None:
        with pytest.raises(AttributeError):
            getattr(AnthropicProvider, "classify_" + "failure")  # the dead name, assembled — no literal

    def test_check_instruction_compliance_signature_matches_port(self) -> None:
        signature = inspect.signature(AnthropicProvider.check_instruction_compliance)

        assert list(signature.parameters) == CHECK_INSTRUCTION_COMPLIANCE_PARAMS
        assert signature.return_annotation is not inspect.Signature.empty

    def test_constructor_reads_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        AnthropicProvider(Config())  # constructs without exceptions — the client is lazy


class TestAnthropicProviderLogic:
    """Logic tests: SDK mapping, lazy key, request shape, classification parsing."""

    def test_anthropic_provider_error_maps_to_llm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client = SimpleNamespace(messages=SimpleNamespace(create=mock.MagicMock(side_effect=AnthropicError("timeout"))))
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
        ):
            provider.generate_step_code(
                prompt="p",
                user_instructions="",
                instruction="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                inputs={},
                declarations=[],
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        assert "anthropic" in str(excinfo.value)
        assert isinstance(excinfo.value, PrettyplayError)

    def test_empty_content_maps_to_llm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client = make_client_returning(SimpleNamespace(content=[]))  # empty service response
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
        ):
            provider.generate_step_code(
                prompt="p",
                user_instructions="",
                instruction="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                inputs={},
                declarations=[],
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        assert "empty completion" in str(excinfo.value)
        assert isinstance(excinfo.value, PrettyplayError)

    def test_non_text_blocks_are_skipped_until_the_text_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        tool_block = SimpleNamespace(type="tool_use", id="t", name="n", input={})
        client = make_client_returning(SimpleNamespace(content=[tool_block, text_block(WORKING_CODE)]))
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            code = provider.generate_step_code(
                prompt="p",
                user_instructions="",
                instruction="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                inputs={},
                declarations=[],
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        assert code == WORKING_CODE  # a non-text first block does not break extraction

    def test_content_without_any_text_block_maps_to_llm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        tool_block = SimpleNamespace(type="tool_use", id="t", name="n", input={})
        client = make_client_returning(SimpleNamespace(content=[tool_block]))
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
        ):
            provider.classify_step_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert "empty completion" in str(excinfo.value)

    def test_anthropic_missing_api_key_surfaces_on_first_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        provider = AnthropicProvider(Config())  # does not fail — the constructor reads no env

        with pytest.raises(LLMUnavailableError) as excinfo:
            provider.classify_step_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert "ANTHROPIC_API_KEY" in str(excinfo.value)

    def test_classification_unparsable_defaults_to_incurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer="sorry cannot answer")
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            classification = provider.classify_step_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert classification.category == "incurable"
        assert len(requests) == 1  # one request per attempt

    def test_generate_returns_code_with_prompt_verbatim_and_effective_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer=WORKING_CODE)
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5", generation_model="claude-haiku-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            code = provider.generate_step_code(
                prompt="system prompt text",
                user_instructions="",
                instruction="открыть страницу",
                step_type="action",
                previous_steps=[ScenarioStep(sentence="шаг один", instruction="шаг один")],
                group_prompt=None,
                inputs={},
                declarations=[],
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        assert code == WORKING_CODE
        assert len(requests) == 1
        request = requests[0]
        assert request["model"] == "claude-haiku-4-5"  # effective_generation_model
        assert request["system"] == "system prompt text"  # prompt verbatim
        assert request["max_tokens"] == 4096
        user = request["messages"][0]
        assert user["role"] == "user"
        assert "открыть страницу" in user["content"]
        assert "шаг один" in user["content"]
        assert "expect(locator).to_be_visible()" in user["content"]
        assert "CODE" not in user["content"]  # no regeneration fields on the first attempt
        assert "PAGE URL" not in user["content"]  # no URL line when page_url is None

    def test_generate_request_carries_the_page_url_line_after_the_snapshot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer=WORKING_CODE)
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.generate_step_code(
                prompt="p",
                user_instructions="",
                instruction="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                inputs={},
                declarations=[],
                snapshot="- snap",
                page_url="https://shop.example.com/cart",
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        user = requests[0]["messages"][0]["content"]
        assert "PAGE URL: https://shop.example.com/cart" in user
        assert user.index("PAGE SNAPSHOT:\n- snap") < user.index("PAGE URL: https://shop.example.com/cart")
        assert user.index("PAGE URL: https://shop.example.com/cart") < user.index("CHEAT SHEET:")

    def test_generate_returns_code_extracted_from_markdown_fence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        fenced = f"```python\n{WORKING_CODE}```"
        client = make_client_create(answer=fenced)[0]
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            code = provider.generate_step_code(
                prompt="p",
                user_instructions="",
                instruction="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                inputs={},
                declarations=[],
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        assert code == WORKING_CODE  # fence stripped — fixed-form code

    def test_generate_regeneration_request_carries_the_attempt_history_records(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer=WORKING_CODE)
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))
        records = [
            "original cached code\nurl: https://a.example -> https://a.example\n"
            "code:\ndef step(page) -> None:\n    pass\nerror:\nAssertionError: boom",
            "execution failed\nurl: https://a.example -> https://b.example\n"
            "code:\ndef step(page) -> None:\n    pass\nerror:\nRuntimeError: crash",
        ]

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.generate_step_code(
                prompt="p",
                user_instructions="",
                instruction="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                inputs={},
                declarations=[],
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=records,
                recommendation="use role locators",
                guidance=None,
            )

        user = requests[0]["messages"][0]["content"]
        # parity: every record verbatim in the HISTORY block, exactly as in the openai implementation
        assert f"HISTORY:\n{records[0]}\n{records[1]}" in user
        assert "AssertionError: boom" in user
        assert user.index("HISTORY:") < user.index("RECOMMENDATION:\nuse role locators")

    def test_classification_unknown_category_defaults_to_incurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, _requests = make_client_create(answer="mystery | why | do something")
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            classification = provider.classify_step_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert classification.category == "incurable"

    def test_classification_empty_answer_defaults_to_incurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, _requests = make_client_create(answer="   ")
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            classification = provider.classify_step_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert classification.category == "incurable"

    def test_generate_with_screenshot_attaches_image_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer=WORKING_CODE)
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.generate_step_code(
                prompt="p",
                user_instructions="",
                instruction="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                inputs={},
                declarations=[],
                snapshot="- snap",
                page_url=None,
                screenshot=b"png-bytes",
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        user_content = requests[0]["messages"][0]["content"]
        assert isinstance(user_content, list)
        assert user_content[0]["type"] == "text"
        image_block = user_content[1]
        assert image_block["type"] == "image"
        assert image_block["source"]["type"] == "base64"
        assert image_block["source"]["media_type"] == "image/png"
        assert image_block["source"]["data"] == base64.b64encode(b"png-bytes").decode("ascii")

    def test_client_constructed_with_base_url_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5", base_url="https://proxy.internal/v1"))
        client, _requests = make_client_create()

        with mock.patch("prettyplay.llm.anthropic_provider.Anthropic", return_value=client) as sdk:
            provider.generate_step_code(
                prompt="p",
                user_instructions="",
                instruction="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                inputs={},
                declarations=[],
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        sdk.assert_called_once()
        assert sdk.call_args.kwargs["api_key"] == "test"
        assert sdk.call_args.kwargs["base_url"] == "https://proxy.internal/v1"

    def test_client_not_constructed_without_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))
        client, _requests = make_client_create()

        with mock.patch("prettyplay.llm.anthropic_provider.Anthropic", return_value=client) as sdk:
            provider.generate_step_code(
                prompt="p",
                user_instructions="",
                instruction="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                inputs={},
                declarations=[],
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        assert sdk.call_args.kwargs["api_key"] == "test"
        assert sdk.call_args.kwargs["base_url"] is None

    def test_classification_parses_verdict_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer="rot | кнопка переименована | проверить шаг")
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5", classification_model="claude-haiku-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            classification = provider.classify_step_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert classification.category == "rot"
        assert classification.explanation == "кнопка переименована"
        assert classification.recommendation == "проверить шаг"
        assert requests[0]["model"] == "claude-haiku-4-5"  # effective_classification_model

    def test_classification_with_screenshot_uses_anthropic_image_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer="rot | e | r")
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.classify_step_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=b"png-bytes",
            )

        user_content = requests[0]["messages"][0]["content"]
        assert user_content[1]["type"] == "image"
        assert user_content[1]["source"]["media_type"] == "image/png"

    def test_sdk_error_in_classify_maps_to_llm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client = SimpleNamespace(messages=SimpleNamespace(create=mock.MagicMock(side_effect=AnthropicError("boom"))))
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
        ):
            provider.classify_step_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert "anthropic" in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, AnthropicError)

    def test_anthropic_user_instructions_parity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer=WORKING_CODE)
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.generate_step_code(
                prompt="SYS",
                user_instructions=USER_INSTRUCTIONS,
                instruction="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                inputs={},
                declarations=[],
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        user = requests[0]["messages"][0]["content"]
        # parity: the same block at the same relative position as the openai implementation
        assert f"USER INSTRUCTIONS:\n{USER_INSTRUCTIONS}" in user
        assert user.index("CHEAT SHEET:") < user.index("USER INSTRUCTIONS:")

    def test_classification_carries_the_instructions_block_last(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer="rot | e | r")
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5", classification_prompt=USER_INSTRUCTIONS))

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.classify_step_failure(
                prompt="p",
                user_instructions=USER_INSTRUCTIONS,
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        user = requests[0]["messages"][0]["content"]
        # parity: the same block appended last, exactly as in the openai implementation
        assert user.endswith(f"USER INSTRUCTIONS:\n{USER_INSTRUCTIONS}")
        assert user.index("PAGE SNAPSHOT:") < user.index("USER INSTRUCTIONS:")

    def test_classification_without_instructions_matches_the_old_form(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer="rot | e | r")
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.classify_step_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert "USER INSTRUCTIONS" not in requests[0]["messages"][0]["content"]

    def test_anthropic_check_instruction_compliance_parity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        verdict = (
            '[{"instruction": "Prefer id attributes", "priority": "high", "explanation": "locates by text",'
            ' "dimension": "instruction"}]'
        )
        client, requests = make_client_create(answer=verdict)
        provider = AnthropicProvider(
            Config(model="claude-sonnet-4-5", generation_model="claude-haiku-4-5", classification_model="claude-x")
        )
        record = (
            "original cached code\nurl: https://a.example -> https://a.example\n"
            f"code:\n{WORKING_CODE}error:\nAssertionError: boom"
        )

        with mock.patch.object(provider, "_get_client", return_value=client):
            findings = provider.check_instruction_compliance(
                prompt="gate prompt",
                user_instructions="Prefer id attributes",
                instruction="нажать Войти",
                step_type="action",
                inputs={},
                declarations=[],
                code=WORKING_CODE,
                attempt_history=[record],
            )

        assert len(requests) == 1  # exactly one verdict request
        request = requests[0]
        assert request["model"] == "claude-x"  # effective classification model — never the generation model
        assert request["system"] == "gate prompt"
        assert request["max_tokens"] == 4096  # the SDK-forced cap rides the verdict request too
        user = request["messages"][0]
        assert user["role"] == "user"
        # parity: the shared builder — the user content equals the openai implementation's
        assert user["content"] == build_compliance_fields(
            "Prefer id attributes", "нажать Войти", "action", {}, [], [record], WORKING_CODE
        )

        assert len(findings) == 1
        assert findings[0].instruction == "Prefer id attributes"
        assert findings[0].priority == "high"
        assert findings[0].explanation == "locates by text"
        assert findings[0].dimension == "instruction"

    def test_anthropic_compliance_sdk_error_maps_to_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client = SimpleNamespace(messages=SimpleNamespace(create=mock.MagicMock(side_effect=AnthropicError("boom"))))
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
        ):
            provider.check_instruction_compliance(
                prompt="p",
                user_instructions="Prefer id attributes",
                instruction="s",
                step_type="action",
                inputs={},
                declarations=[],
                code="c",
                attempt_history=[],
            )

        assert str(excinfo.value) == "llm unavailable: anthropic request failed permanently: invalid_request"
        assert not isinstance(excinfo.value, ComplianceVerdictError)  # the SDK error is never a verdict failure
        assert isinstance(excinfo.value.__cause__, AnthropicError)


DIAGNOSIS_ANSWER = (
    '{"category": "recoverable", "root_cause": "the fill step used a stale locator", '
    '"earliest_step": "fill the email field", "recommendation": "regenerate the row from the fill step"}'
)
GROUP_STEPS = [
    "accept the cookie banner\noutcome: passed\nurl: https://a.example -> https://a.example",
    "the status shows order confirmed\noutcome: failed\nurl: https://a.example -> https://b.example",
]


class TestAnthropicGroupDiagnosis:
    """Logic tests: the group diagnosis operation of the anthropic implementation."""

    def test_anthropic_classify_group_failure_request_and_parse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer=DIAGNOSIS_ANSWER)
        provider = AnthropicProvider(
            Config(model="claude-sonnet-4-5", generation_model="claude-haiku-4-5", classification_model="claude-x")
        )
        record = (
            "original cached code\nurl: https://a.example -> https://a.example\n"
            f"code:\n{WORKING_CODE}error:\nAssertionError: boom"
        )

        with mock.patch.object(provider, "_get_client", return_value=client):
            verdict = provider.classify_group_failure(
                prompt="diagnosis prompt",
                user_instructions="be terse",
                group_prompt="the checkout flow",
                group_steps=GROUP_STEPS,
                previous_steps=[
                    ScenarioStep(sentence="open the shop", instruction="open the shop"),
                    ScenarioStep(sentence="fill {{ field }}", instruction="fill the field", group_prompt="the flow"),
                ],
                step_text="the status shows order confirmed",
                attempt_history=[record],
                snapshot="- snap",
                screenshot=None,
            )

        assert len(requests) == 1  # one request per diagnosis
        request = requests[0]
        assert request["model"] == "claude-x"  # effective classification model — never the generation model
        assert request["system"] == "diagnosis prompt"  # prompt verbatim
        assert request["max_tokens"] == 4096  # the SDK-forced cap rides the diagnosis request too
        user = request["messages"][0]
        assert user["role"] == "user"
        assert (
            user["content"].index("GROUP PROMPT:\nthe checkout flow")
            < user["content"].index("PREVIOUS STEPS:\n- open the shop\n- fill the field [group step — the flow]")
            < user["content"].index("GROUP STEPS:\n")
            < user["content"].index("STEP:\nthe status shows order confirmed")
            < user["content"].index(f"HISTORY:\n{record}")
            < user["content"].index("PAGE SNAPSHOT:\n- snap")
            < user["content"].index("USER INSTRUCTIONS:\nbe terse")
        )  # parity: the fixed diagnosis order, previous steps before group steps, instructions last
        assert "fill {{ field }}" not in user["content"]  # the raw template sentence never reaches the request
        assert GROUP_STEPS[0] in user["content"]  # every trace record verbatim

        assert verdict.category == "recoverable"
        assert verdict.root_cause == "the fill step used a stale locator"
        assert verdict.earliest_step == "fill the email field"
        assert verdict.recommendation == "regenerate the row from the fill step"
        assert verdict.degraded is False

    def test_anthropic_garbage_diagnosis_answer_degrades_inside_the_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer="the app is broken")
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            verdict = provider.classify_group_failure(  # never raises across the port
                prompt="p",
                user_instructions="",
                group_prompt="the checkout flow",
                group_steps=GROUP_STEPS,
                previous_steps=[],
                step_text="the status shows order confirmed",
                attempt_history=[],
                snapshot="- snap",
                screenshot=None,
            )

        assert verdict.category == "incurable"
        assert verdict.degraded is True
        assert verdict.root_cause == "the app is broken"  # the raw answer rides the degraded verdict
        assert len(requests) == 1  # the degradation adds no retry

    def test_anthropic_diagnosis_sdk_error_maps_to_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client = SimpleNamespace(messages=SimpleNamespace(create=mock.MagicMock(side_effect=AnthropicError("boom"))))
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
        ):
            provider.classify_group_failure(
                prompt="p",
                user_instructions="",
                group_prompt="the checkout flow",
                group_steps=GROUP_STEPS,
                previous_steps=[],
                step_text="the status shows order confirmed",
                attempt_history=[],
                snapshot="- snap",
                screenshot=None,
            )

        assert str(excinfo.value) == "llm unavailable: anthropic request failed permanently: invalid_request"
        assert isinstance(excinfo.value.__cause__, AnthropicError)

    def test_anthropic_diagnosis_with_screenshot_uses_anthropic_image_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer=DIAGNOSIS_ANSWER)
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.classify_group_failure(
                prompt="p",
                user_instructions="",
                group_prompt="the checkout flow",
                group_steps=GROUP_STEPS,
                previous_steps=[],
                step_text="the status shows order confirmed",
                attempt_history=[],
                snapshot="- snap",
                screenshot=b"png-bytes",
            )

        user_content = requests[0]["messages"][0]["content"]
        assert isinstance(user_content, list)
        assert user_content[0]["type"] == "text"
        image_block = user_content[1]
        assert image_block["type"] == "image"  # parity: the diagnosis attaches the same image shape
        assert image_block["source"]["media_type"] == "image/png"
        assert image_block["source"]["data"] == base64.b64encode(b"png-bytes").decode("ascii")


class TestAnthropicProviderTransportWiring:
    """Contract tests: every SDK call of every operation rides the bounded retry loop."""

    def test_anthropic_all_four_operations_route_the_sdk_call_through_send_with_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        cell: dict[str, str] = {"answer": WORKING_CODE}
        create = mock.MagicMock(side_effect=lambda **_kwargs: SimpleNamespace(content=[text_block(cell["answer"])]))
        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        calls: list[tuple[str, str, int, object]] = []

        def recorder(provider_label: str, operation: str, attempts: int, classify: object, send: object) -> object:
            calls.append((provider_label, operation, attempts, classify))

            return send()

        with (
            mock.patch.object(anthropic_provider, "send_with_retries", recorder),
            mock.patch.object(provider, "_get_client", return_value=client),
        ):
            provider.generate_step_code(
                prompt="p",
                user_instructions="",
                instruction="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                inputs={},
                declarations=[],
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )
            cell["answer"] = "rot | e | r"
            provider.classify_step_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )
            cell["answer"] = DIAGNOSIS_ANSWER
            provider.classify_group_failure(
                prompt="p",
                user_instructions="",
                group_prompt="the checkout flow",
                group_steps=GROUP_STEPS,
                previous_steps=[],
                step_text="the status shows order confirmed",
                attempt_history=[],
                snapshot="- snap",
                screenshot=None,
            )
            cell["answer"] = "[]"
            provider.check_instruction_compliance(
                prompt="p",
                user_instructions="Prefer id attributes",
                instruction="s",
                step_type="action",
                inputs={},
                declarations=[],
                code="c",
                attempt_history=[],
            )

        assert [(label, operation) for label, operation, _attempts, _classify in calls] == [
            ("anthropic", "generation"),
            ("anthropic", "classification"),
            ("anthropic", "group diagnosis"),
            ("anthropic", "compliance verdict"),
        ]  # parity: every operation enters the loop exactly once, under its fixed label
        assert all(attempts == 3 for _label, _operation, attempts, _classify in calls)  # config default budget
        assert all(classify is classify_anthropic_failure for _label, _operation, _attempts, classify in calls)

    def test_anthropic_transient_failure_recovers_inside_one_logical_attempt(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        outcomes: list[object] = [APIConnectionError(request=SimpleNamespace()), WORKING_CODE]
        calls: list[int] = []

        def create(**_kwargs: object) -> object:
            calls.append(1)
            outcome = outcomes.pop(0)

            if isinstance(outcome, Exception):
                raise outcome

            return SimpleNamespace(content=[text_block(outcome)])

        client = SimpleNamespace(messages=SimpleNamespace(create=mock.MagicMock(side_effect=create)))
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5", llm_request_attempts=2))
        sleeps: list[float] = []

        monkeypatch.setattr("time.sleep", sleeps.append)
        monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)
        caplog.set_level(logging.WARNING, logger="prettyplay")

        with mock.patch.object(provider, "_get_client", return_value=client):
            code = provider.generate_step_code(
                prompt="p",
                user_instructions="",
                instruction="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                inputs={},
                declarations=[],
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        assert code == WORKING_CODE
        assert client.messages.create.call_count == 2  # parity: the resend stayed inside one logical attempt
        assert sleeps == [1.0]
        assert len(caplog.records) == 1
        assert caplog.records[0].provider == "anthropic"
        assert caplog.records[0].operation == "generation"

    def test_anthropic_permanent_failure_maps_to_llm_unavailable_immediately(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        error = make_status_error(AuthenticationError, 401)
        create = mock.MagicMock(side_effect=error)
        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))
        sleeps: list[float] = []

        monkeypatch.setattr("time.sleep", sleeps.append)

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
        ):
            provider.classify_step_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert "anthropic" in str(excinfo.value)
        assert "authentication" in str(excinfo.value)
        assert excinfo.value.__cause__ is error
        assert create.call_count == 1  # parity: a permanent rejection never resends
        assert sleeps == []
        assert caplog.records == []

    def test_anthropic_missing_api_key_still_surfaces_before_the_retry_loop(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        provider = AnthropicProvider(Config())
        sleeps: list[float] = []

        monkeypatch.setattr("time.sleep", sleeps.append)

        with pytest.raises(LLMUnavailableError) as excinfo:
            provider.classify_step_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert "ANTHROPIC_API_KEY" in str(excinfo.value)
        assert sleeps == []  # parity: the missing-key error never enters the retry loop
        assert caplog.records == []
