"""Tests for the OpenAIProvider implementation of the prettyplay.llm cell."""

import inspect
from types import SimpleNamespace
from unittest import mock

import pytest
from openai import OpenAIError
from prettyplay.config import Config
from prettyplay.failures import LLMUnavailableError, PrettyplayError
from prettyplay.llm import LLMProvider, OpenAIProvider

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

WORKING_CODE = "def step(page) -> None:\n    page.open('https://example.com')\n"
USER_INSTRUCTIONS = "prefer data-test-id"


def make_client_create(answer: str = WORKING_CODE) -> tuple[object, list[dict]]:
    """Build a fake SDK client whose chat.completions.create returns the answer.

    Returns:
        The fake client and the list the request payloads get appended to.
    """
    requests: list[dict] = []
    message = SimpleNamespace(content=answer)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    create = mock.MagicMock(return_value=response, side_effect=lambda **kwargs: requests.append(kwargs) or response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, requests


def completion_answer(answer: str) -> object:
    """Build a fake chat completion response carrying the answer text."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])


class TestOpenAIProviderContract:
    """Contract tests: facade import, port membership, exact signatures, lazy env."""

    def test_importable_from_facade(self) -> None:
        assert isinstance(OpenAIProvider, type)

    def test_is_an_llm_provider(self) -> None:
        assert issubclass(OpenAIProvider, LLMProvider)

    def test_generate_step_code_signature_matches_port(self) -> None:
        signature = inspect.signature(OpenAIProvider.generate_step_code)

        assert list(signature.parameters) == GENERATE_STEP_CODE_PARAMS
        assert signature.return_annotation is str

    def test_classify_failure_signature_matches_port(self) -> None:
        signature = inspect.signature(OpenAIProvider.classify_failure)

        assert list(signature.parameters) == CLASSIFY_FAILURE_PARAMS
        assert signature.return_annotation is not inspect.Signature.empty

    def test_constructor_reads_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        OpenAIProvider(Config())  # constructs without exceptions — the client is lazy


class TestOpenAIProviderLogic:
    """Logic tests: SDK mapping, lazy key, classification parsing, request shape."""

    def test_openai_provider_error_maps_to_llm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=mock.MagicMock(side_effect=OpenAIError("timeout"))))
        )
        provider = OpenAIProvider(Config(model="gpt-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
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

        assert "openai" in str(excinfo.value)
        assert isinstance(excinfo.value, PrettyplayError)

    def test_missing_api_key_surfaces_on_first_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        provider = OpenAIProvider(Config())  # does not fail — the constructor reads no env

        with pytest.raises(LLMUnavailableError) as excinfo:
            provider.classify_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert "OPENAI_API_KEY" in str(excinfo.value)

    def test_classification_unparsable_defaults_to_incurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer="sorry cannot answer")
        provider = OpenAIProvider(Config(model="gpt-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            classification = provider.classify_failure(
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
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer=WORKING_CODE)
        provider = OpenAIProvider(Config(model="gpt-5", generation_model="gpt-5-mini"))

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
        assert request["model"] == "gpt-5-mini"  # effective_generation_model
        assert request["messages"][0] == {"role": "system", "content": "system prompt text"}
        user = request["messages"][1]
        assert user["role"] == "user"
        assert "открыть страницу" in user["content"]
        assert "шаг один" in user["content"]
        assert "page.open(...)" in user["content"]
        assert "CODE" not in user["content"]  # no regeneration fields on the first attempt

    def test_generate_returns_code_extracted_from_markdown_fence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        fenced = f"```python\n{WORKING_CODE}```"
        client = make_client_create(answer=fenced)[0]
        provider = OpenAIProvider(Config(model="gpt-5"))

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

        assert code == WORKING_CODE  # fence stripped — provider parity

    def test_generate_regeneration_request_carries_code_and_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer=WORKING_CODE)
        provider = OpenAIProvider(Config(model="gpt-5"))

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

        user = requests[0]["messages"][1]["content"]
        assert "def step(page) -> None:" in user
        assert "AssertionError: boom" in user

    def test_generate_with_screenshot_attaches_image_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer=WORKING_CODE)
        provider = OpenAIProvider(Config(model="gpt-5"))

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

        user_content = requests[0]["messages"][1]["content"]
        assert isinstance(user_content, list)
        assert user_content[0]["type"] == "text"
        image_block = user_content[1]
        assert image_block["type"] == "image_url"
        assert image_block["image_url"]["url"].startswith("data:image/png;base64,")

    def test_classification_with_screenshot_uses_openai_image_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer="rot | почему | что делать")
        provider = OpenAIProvider(Config(model="gpt-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.classify_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=b"png-bytes",
            )

        user_content = requests[0]["messages"][1]["content"]
        assert isinstance(user_content, list)
        assert user_content[0]["type"] == "text"
        image_block = user_content[1]
        assert image_block["type"] == "image_url"  # parity: classification attaches the same image shape
        assert image_block["image_url"]["url"].startswith("data:image/png;base64,")

    def test_client_constructed_with_base_url_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        provider = OpenAIProvider(Config(model="gpt-5", base_url="https://proxy.internal/v1"))
        client, _requests = make_client_create()

        with mock.patch("prettyplay.llm.openai_provider.OpenAI", return_value=client) as sdk:
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

    def test_classification_parses_verdict_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer="rot | кнопка переименована | проверить шаг")
        provider = OpenAIProvider(Config(model="gpt-5", classification_model="gpt-5-mini"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            classification = provider.classify_failure(
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
        assert requests[0]["model"] == "gpt-5-mini"  # effective_classification_model

    def test_classification_unknown_category_defaults_to_incurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, _requests = make_client_create(answer="mystery | why | do something")
        provider = OpenAIProvider(Config(model="gpt-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            classification = provider.classify_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert classification.category == "incurable"

    def test_classification_null_content_maps_to_llm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, _requests = make_client_create(answer=None)  # type: ignore[arg-type]
        provider = OpenAIProvider(Config(model="gpt-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
        ):
            provider.classify_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert "empty completion" in str(excinfo.value)

    def test_classification_empty_answer_defaults_to_incurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, _requests = make_client_create(answer="   ")
        provider = OpenAIProvider(Config(model="gpt-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            classification = provider.classify_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert classification.category == "incurable"

    def test_sdk_error_in_classify_maps_to_llm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=mock.MagicMock(side_effect=OpenAIError("boom"))))
        )
        provider = OpenAIProvider(Config(model="gpt-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
        ):
            provider.classify_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert "openai" in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, OpenAIError)

    def test_null_completion_content_maps_to_llm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, _requests = make_client_create(answer=None)  # type: ignore[arg-type]
        provider = OpenAIProvider(Config(model="gpt-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
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

    def test_empty_choices_maps_to_llm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        response = SimpleNamespace(choices=[])  # service returned no completion body
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=mock.MagicMock(return_value=response)))
        )
        provider = OpenAIProvider(Config(model="gpt-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
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

    def test_openai_generate_step_code_carries_user_instructions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        fenced = f"```python\n{WORKING_CODE}```"
        client, requests = make_client_create(answer=fenced)
        provider = OpenAIProvider(Config(model="gpt-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            code = provider.generate_step_code(
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

        assert code == WORKING_CODE  # fenced block unwrapped
        request = requests[0]
        assert request["messages"][0] == {"role": "system", "content": "SYS"}
        user = request["messages"][1]["content"]
        assert f"USER INSTRUCTIONS:\n{USER_INSTRUCTIONS}" in user
        assert user.index("PAGE API:") < user.index("USER INSTRUCTIONS:")  # after the page API block

    def test_classify_failure_never_carries_generation_instructions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer="rot | e | r")
        provider = OpenAIProvider(Config(model="gpt-5", generation_prompt=USER_INSTRUCTIONS))

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.classify_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        user = requests[0]["messages"][1]["content"]
        assert "USER INSTRUCTIONS" not in user  # the generation_prompt setting never reaches classifications

    def test_classification_carries_the_instructions_block_last(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer="rot | e | r")
        provider = OpenAIProvider(Config(model="gpt-5", classification_prompt=USER_INSTRUCTIONS))

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.classify_failure(
                prompt="p",
                user_instructions=USER_INSTRUCTIONS,
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        user = requests[0]["messages"][1]["content"]
        assert user.endswith(f"USER INSTRUCTIONS:\n{USER_INSTRUCTIONS}")  # the block is appended last
        assert user.index("PAGE SNAPSHOT:") < user.index("USER INSTRUCTIONS:")

    def test_empty_choices_in_classify_maps_to_llm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        response = SimpleNamespace(choices=[])  # service returned no completion body
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=mock.MagicMock(return_value=response)))
        )
        provider = OpenAIProvider(Config(model="gpt-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
        ):
            provider.classify_failure(
                prompt="p",
                user_instructions="",
                step_text="s",
                code="c",
                error="e",
                snapshot="- snap",
                screenshot=None,
            )

        assert "empty completion" in str(excinfo.value)
        assert isinstance(excinfo.value, PrettyplayError)
