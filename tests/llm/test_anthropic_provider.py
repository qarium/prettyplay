"""Tests for the AnthropicProvider implementation of the prettyplay.llm cell."""

import base64
import inspect
from types import SimpleNamespace
from unittest import mock

import pytest
from anthropic import AnthropicError
from prettyplay.config import Config
from prettyplay.failures import LlmUnavailableError, PrettyplayError
from prettyplay.llm import AnthropicProvider, LlmProvider

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

WORKING_CODE = "def step(page) -> None:\n    page.open('https://example.com')\n"
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


class TestAnthropicProviderContract:
    """Contract tests: facade import, port membership, exact signatures, lazy env."""

    def test_importable_from_facade(self) -> None:
        assert isinstance(AnthropicProvider, type)

    def test_is_an_llm_provider(self) -> None:
        assert issubclass(AnthropicProvider, LlmProvider)

    def test_generate_step_code_signature_matches_port(self) -> None:
        signature = inspect.signature(AnthropicProvider.generate_step_code)

        assert list(signature.parameters) == GENERATE_STEP_CODE_PARAMS
        assert signature.return_annotation is str

    def test_classify_failure_signature_matches_port(self) -> None:
        signature = inspect.signature(AnthropicProvider.classify_failure)

        assert list(signature.parameters) == CLASSIFY_FAILURE_PARAMS
        assert signature.return_annotation is not inspect.Signature.empty

    def test_constructor_reads_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        AnthropicProvider(Config())  # конструкция без исключений — клиент ленивый


class TestAnthropicProviderLogic:
    """Logic tests: SDK mapping, lazy key, request shape, classification parsing."""

    def test_anthropic_provider_error_maps_to_llm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client = SimpleNamespace(messages=SimpleNamespace(create=mock.MagicMock(side_effect=AnthropicError("timeout"))))
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LlmUnavailableError) as excinfo,
        ):
            provider.generate_step_code(
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

        assert "anthropic" in str(excinfo.value)
        assert isinstance(excinfo.value, PrettyplayError)

    def test_empty_content_maps_to_llm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client = make_client_returning(SimpleNamespace(content=[]))  # пустой ответ сервиса
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LlmUnavailableError) as excinfo,
        ):
            provider.generate_step_code(
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
                step_text="s",
                previous_steps=[],
                snapshot="- snap",
                screenshot=None,
                page_api="page.open(...)",
                existing_code=None,
                error=None,
            )

        assert code == WORKING_CODE  # не-текстовый первый блок не ломает извлечение

    def test_content_without_any_text_block_maps_to_llm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        tool_block = SimpleNamespace(type="tool_use", id="t", name="n", input={})
        client = make_client_returning(SimpleNamespace(content=[tool_block]))
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LlmUnavailableError) as excinfo,
        ):
            provider.classify_failure(
                prompt="p",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert "empty completion" in str(excinfo.value)

    def test_anthropic_missing_api_key_surfaces_on_first_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        provider = AnthropicProvider(Config())  # не падает — конструктор не читает env

        with pytest.raises(LlmUnavailableError) as excinfo:
            provider.classify_failure(
                prompt="p",
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
            classification = provider.classify_failure(
                prompt="p",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert classification.category == "incurable"
        assert len(requests) == 1  # один запрос на попытку

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
                step_text="открыть страницу",
                previous_steps=["шаг один"],
                snapshot="- snap",
                screenshot=None,
                page_api="page.open(...)",
                existing_code=None,
                error=None,
            )

        assert code == WORKING_CODE
        assert len(requests) == 1
        request = requests[0]
        assert request["model"] == "claude-haiku-4-5"  # effective_generation_model
        assert request["system"] == "system prompt text"  # prompt verbatim
        assert request["max_tokens"] == 1024
        user = request["messages"][0]
        assert user["role"] == "user"
        assert "открыть страницу" in user["content"]
        assert "шаг один" in user["content"]
        assert "page.open(...)" in user["content"]
        assert "CODE" not in user["content"]  # регенерационные поля отсутствуют на первой попытке

    def test_generate_returns_code_extracted_from_markdown_fence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        fenced = f"```python\n{WORKING_CODE}```"
        client = make_client_create(answer=fenced)[0]
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            code = provider.generate_step_code(
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

        assert code == WORKING_CODE  # фенс снят — код фиксированной формы

    def test_generate_regeneration_request_carries_code_and_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer=WORKING_CODE)
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.generate_step_code(
                prompt="p",
                user_instructions="",
                step_text="s",
                previous_steps=[],
                snapshot="- snap",
                screenshot=None,
                page_api="page.open(...)",
                existing_code="def step(page) -> None:\n    pass\n",
                error="AssertionError: boom",
            )

        user = requests[0]["messages"][0]["content"]
        assert "def step(page) -> None:" in user
        assert "AssertionError: boom" in user

    def test_classification_unknown_category_defaults_to_incurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, _requests = make_client_create(answer="mystery | why | do something")
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            classification = provider.classify_failure(
                prompt="p",
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
            classification = provider.classify_failure(
                prompt="p",
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
                step_text="s",
                previous_steps=[],
                snapshot="- snap",
                screenshot=b"png-bytes",
                page_api="page.open(...)",
                existing_code=None,
                error=None,
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
                step_text="s",
                previous_steps=[],
                snapshot="- snap",
                screenshot=None,
                page_api="page.open(...)",
                existing_code=None,
                error=None,
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
                step_text="s",
                previous_steps=[],
                snapshot="- snap",
                screenshot=None,
                page_api="page.open(...)",
                existing_code=None,
                error=None,
            )

        assert sdk.call_args.kwargs["api_key"] == "test"
        assert sdk.call_args.kwargs["base_url"] is None

    def test_classification_parses_verdict_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        client, requests = make_client_create(answer="rot | кнопка переименована | проверить шаг")
        provider = AnthropicProvider(Config(model="claude-sonnet-4-5", classification_model="claude-haiku-4-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            classification = provider.classify_failure(
                prompt="p",
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
            provider.classify_failure(
                prompt="p",
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
            pytest.raises(LlmUnavailableError) as excinfo,
        ):
            provider.classify_failure(
                prompt="p",
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
                step_text="s",
                previous_steps=[],
                snapshot="- snap",
                screenshot=None,
                page_api="page.open(...)",
                existing_code=None,
                error=None,
            )

        user = requests[0]["messages"][0]["content"]
        # parity: the same block at the same relative position as the openai implementation
        assert f"USER INSTRUCTIONS:\n{USER_INSTRUCTIONS}" in user
        assert user.index("PAGE API:") < user.index("USER INSTRUCTIONS:")
