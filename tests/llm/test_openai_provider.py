"""Tests for the OpenAIProvider implementation of the prettyplay.llm cell."""

import inspect
from types import SimpleNamespace
from unittest import mock

import pytest
from openai import OpenAIError
from prettyplay.config import Config
from prettyplay.failures import ComplianceVerdictError, LLMUnavailableError, PrettyplayError
from prettyplay.llm import LLMProvider, OpenAIProvider, ScenarioStep

GENERATE_STEP_CODE_PARAMS = [
    "self",
    "prompt",
    "user_instructions",
    "step_text",
    "step_type",
    "previous_steps",
    "group_prompt",
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
    "step_text",
    "attempt_history",
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

WORKING_CODE = "def step(page) -> None:\n    page.goto('https://example.com')\n"
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

    def test_classify_step_failure_signature_matches_port(self) -> None:
        signature = inspect.signature(OpenAIProvider.classify_step_failure)

        assert list(signature.parameters) == CLASSIFY_STEP_FAILURE_PARAMS
        assert signature.return_annotation is not inspect.Signature.empty

    def test_classify_group_failure_signature_matches_port(self) -> None:
        signature = inspect.signature(OpenAIProvider.classify_group_failure)

        assert list(signature.parameters) == CLASSIFY_GROUP_FAILURE_PARAMS
        assert signature.return_annotation is not inspect.Signature.empty

    def test_the_old_classify_failure_name_is_gone(self) -> None:
        with pytest.raises(AttributeError):
            getattr(OpenAIProvider, "classify_" + "failure")  # the dead name, assembled — no literal

    def test_check_instruction_compliance_signature_matches_port(self) -> None:
        signature = inspect.signature(OpenAIProvider.check_instruction_compliance)

        assert list(signature.parameters) == CHECK_INSTRUCTION_COMPLIANCE_PARAMS
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
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        assert "openai" in str(excinfo.value)
        assert isinstance(excinfo.value, PrettyplayError)

    def test_missing_api_key_surfaces_on_first_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        provider = OpenAIProvider(Config())  # does not fail — the constructor reads no env

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

        assert "OPENAI_API_KEY" in str(excinfo.value)

    def test_classification_unparsable_defaults_to_incurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer="sorry cannot answer")
        provider = OpenAIProvider(Config(model="gpt-5"))

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
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer=WORKING_CODE)
        provider = OpenAIProvider(Config(model="gpt-5", generation_model="gpt-5-mini"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            code = provider.generate_step_code(
                prompt="system prompt text",
                user_instructions="",
                step_text="открыть страницу",
                step_type="action",
                previous_steps=[ScenarioStep(sentence="шаг один")],
                group_prompt=None,
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
        assert request["model"] == "gpt-5-mini"  # effective_generation_model
        assert request["messages"][0] == {"role": "system", "content": "system prompt text"}
        user = request["messages"][1]
        assert user["role"] == "user"
        assert "открыть страницу" in user["content"]
        assert "шаг один" in user["content"]
        assert "expect(locator).to_be_visible()" in user["content"]
        assert "CODE" not in user["content"]  # no regeneration fields on the first attempt
        assert "PAGE URL" not in user["content"]  # no URL line when page_url is None

    def test_generate_request_carries_the_page_url_line_after_the_snapshot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer=WORKING_CODE)
        provider = OpenAIProvider(Config(model="gpt-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.generate_step_code(
                prompt="p",
                user_instructions="",
                step_text="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                snapshot="- snap",
                page_url="https://shop.example.com/cart",
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        user = requests[0]["messages"][1]["content"]
        assert "PAGE URL: https://shop.example.com/cart" in user
        assert user.index("PAGE SNAPSHOT:\n- snap") < user.index("PAGE URL: https://shop.example.com/cart")
        assert user.index("PAGE URL: https://shop.example.com/cart") < user.index("CHEAT SHEET:")

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
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        assert code == WORKING_CODE  # fence stripped — provider parity

    def test_generate_regeneration_request_carries_the_attempt_history_records(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer=WORKING_CODE)
        provider = OpenAIProvider(Config(model="gpt-5"))
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
                step_text="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=records,
                recommendation="use role locators",
                guidance=None,
            )

        user = requests[0]["messages"][1]["content"]
        # every record verbatim in the HISTORY block — the last record is the code being fixed
        assert f"HISTORY:\n{records[0]}\n{records[1]}" in user
        assert "AssertionError: boom" in user
        assert user.index("HISTORY:") < user.index("RECOMMENDATION:\nuse role locators")

    def test_generate_with_screenshot_attaches_image_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer=WORKING_CODE)
        provider = OpenAIProvider(Config(model="gpt-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.generate_step_code(
                prompt="p",
                user_instructions="",
                step_text="s",
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                snapshot="- snap",
                page_url=None,
                screenshot=b"png-bytes",
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
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
            provider.classify_step_failure(
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
                step_type="action",
                previous_steps=[],
                group_prompt=None,
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

    def test_classification_parses_verdict_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer="rot | кнопка переименована | проверить шаг")
        provider = OpenAIProvider(Config(model="gpt-5", classification_model="gpt-5-mini"))

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
        assert requests[0]["model"] == "gpt-5-mini"  # effective_classification_model

    def test_classification_unknown_category_defaults_to_incurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, _requests = make_client_create(answer="mystery | why | do something")
        provider = OpenAIProvider(Config(model="gpt-5"))

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

    def test_classification_null_content_maps_to_llm_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, _requests = make_client_create(answer=None)  # type: ignore[arg-type]
        provider = OpenAIProvider(Config(model="gpt-5"))

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

    def test_classification_empty_answer_defaults_to_incurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, _requests = make_client_create(answer="   ")
        provider = OpenAIProvider(Config(model="gpt-5"))

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
            provider.classify_step_failure(
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
                step_type="action",
                previous_steps=[],
                group_prompt=None,
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
                step_type="action",
                previous_steps=[],
                group_prompt=None,
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
                step_type="action",
                previous_steps=[],
                group_prompt=None,
                snapshot="- snap",
                page_url=None,
                screenshot=None,
                cheat_sheet="expect(locator).to_be_visible()",
                attempt_history=[],
                recommendation=None,
                guidance=None,
            )

        assert code == WORKING_CODE  # fenced block unwrapped
        request = requests[0]
        assert request["messages"][0] == {"role": "system", "content": "SYS"}
        user = request["messages"][1]["content"]
        assert f"USER INSTRUCTIONS:\n{USER_INSTRUCTIONS}" in user
        assert user.index("CHEAT SHEET:") < user.index("USER INSTRUCTIONS:")  # after the cheat-sheet block

    def test_classify_failure_never_carries_generation_instructions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer="rot | e | r")
        provider = OpenAIProvider(Config(model="gpt-5", generation_prompt=USER_INSTRUCTIONS))

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

        user = requests[0]["messages"][1]["content"]
        assert "USER INSTRUCTIONS" not in user  # the generation_prompt setting never reaches classifications

    def test_classification_carries_the_instructions_block_last(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer="rot | e | r")
        provider = OpenAIProvider(Config(model="gpt-5", classification_prompt=USER_INSTRUCTIONS))

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
        assert isinstance(excinfo.value, PrettyplayError)

    def test_openai_check_instruction_compliance_request_and_parse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        verdict = (
            '[{"instruction": "Prefer id attributes", "priority": "high", "explanation": "locates by text",'
            ' "dimension": "instruction"}]'
        )
        client, requests = make_client_create(answer=verdict)
        provider = OpenAIProvider(Config(model="gpt-5", generation_model="gpt-5-mini", classification_model="gpt-x"))
        record = (
            "original cached code\nurl: https://a.example -> https://a.example\n"
            f"code:\n{WORKING_CODE}error:\nAssertionError: boom"
        )

        with mock.patch.object(provider, "_get_client", return_value=client):
            findings = provider.check_instruction_compliance(
                prompt="gate prompt",
                user_instructions="Prefer id attributes",
                step_text="нажать Войти",
                step_type="action",
                code=WORKING_CODE,
                attempt_history=[record],
            )

        assert len(requests) == 1  # exactly one verdict request
        request = requests[0]
        assert request["model"] == "gpt-x"  # effective classification model — never the generation model
        assert request["messages"][0] == {"role": "system", "content": "gate prompt"}
        user = request["messages"][1]
        assert user["role"] == "user"
        assert user["content"] == (
            "INSTRUCTIONS:\nPrefer id attributes\n\n"
            "STEP TYPE: action\nSTEP:\nнажать Войти\n\n"
            f"ATTEMPT HISTORY:\n{record}\n\n"
            f"CODE:\n{WORKING_CODE}"
        )  # the four blocks in the fixed order
        assert set(request) == {"model", "messages"}  # plain string content — no screenshot keys anywhere

        assert len(findings) == 1
        assert findings[0].instruction == "Prefer id attributes"
        assert findings[0].priority == "high"
        assert findings[0].explanation == "locates by text"
        assert findings[0].dimension == "instruction"

    def test_openai_compliance_sdk_error_maps_to_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=mock.MagicMock(side_effect=OpenAIError("boom"))))
        )
        provider = OpenAIProvider(Config(model="gpt-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
        ):
            provider.check_instruction_compliance(
                prompt="p",
                user_instructions="Prefer id attributes",
                step_text="s",
                step_type="action",
                code="c",
                attempt_history=[],
            )

        assert str(excinfo.value) == "llm unavailable: openai request failed"
        assert not isinstance(excinfo.value, ComplianceVerdictError)  # the SDK error is never a verdict failure
        assert isinstance(excinfo.value.__cause__, OpenAIError)


DIAGNOSIS_ANSWER = (
    '{"category": "recoverable", "root_cause": "the fill step used a stale locator", '
    '"earliest_step": "fill the email field", "recommendation": "regenerate the row from the fill step"}'
)
GROUP_STEPS = [
    "accept the cookie banner\noutcome: passed\nurl: https://a.example -> https://a.example",
    "the status shows order confirmed\noutcome: failed\nurl: https://a.example -> https://b.example",
]


class TestOpenAIGroupDiagnosis:
    """Logic tests: the group diagnosis operation of the openai implementation."""

    def test_openai_classify_group_failure_request_and_parse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer=DIAGNOSIS_ANSWER)
        provider = OpenAIProvider(Config(model="gpt-5", generation_model="gpt-5-mini", classification_model="gpt-x"))
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
                step_text="the status shows order confirmed",
                attempt_history=[record],
                snapshot="- snap",
                screenshot=None,
            )

        assert len(requests) == 1  # one request per diagnosis
        request = requests[0]
        assert request["model"] == "gpt-x"  # effective classification model — never the generation model
        assert request["messages"][0] == {"role": "system", "content": "diagnosis prompt"}
        user = request["messages"][1]
        assert user["role"] == "user"
        assert (
            user["content"].index("GROUP PROMPT:\nthe checkout flow")
            < user["content"].index("GROUP STEPS:\n")
            < user["content"].index("STEP:\nthe status shows order confirmed")
            < user["content"].index(f"HISTORY:\n{record}")
            < user["content"].index("PAGE SNAPSHOT:\n- snap")
            < user["content"].index("USER INSTRUCTIONS:\nbe terse")
        )  # the fixed diagnosis order, instructions last
        assert GROUP_STEPS[0] in user["content"]  # every trace record verbatim

        assert verdict.category == "recoverable"
        assert verdict.root_cause == "the fill step used a stale locator"
        assert verdict.earliest_step == "fill the email field"
        assert verdict.recommendation == "regenerate the row from the fill step"
        assert verdict.degraded is False

    def test_openai_garbage_diagnosis_answer_degrades_inside_the_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer="the app is broken")
        provider = OpenAIProvider(Config(model="gpt-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            verdict = provider.classify_group_failure(  # never raises across the port
                prompt="p",
                user_instructions="",
                group_prompt="the checkout flow",
                group_steps=GROUP_STEPS,
                step_text="the status shows order confirmed",
                attempt_history=[],
                snapshot="- snap",
                screenshot=None,
            )

        assert verdict.category == "incurable"
        assert verdict.degraded is True
        assert verdict.root_cause == "the app is broken"  # the raw answer rides the degraded verdict
        assert len(requests) == 1  # the degradation adds no retry

    def test_openai_diagnosis_sdk_error_maps_to_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=mock.MagicMock(side_effect=OpenAIError("boom"))))
        )
        provider = OpenAIProvider(Config(model="gpt-5"))

        with (
            mock.patch.object(provider, "_get_client", return_value=client),
            pytest.raises(LLMUnavailableError) as excinfo,
        ):
            provider.classify_group_failure(
                prompt="p",
                user_instructions="",
                group_prompt="the checkout flow",
                group_steps=GROUP_STEPS,
                step_text="the status shows order confirmed",
                attempt_history=[],
                snapshot="- snap",
                screenshot=None,
            )

        assert str(excinfo.value) == "llm unavailable: openai request failed"
        assert isinstance(excinfo.value.__cause__, OpenAIError)

    def test_openai_diagnosis_with_screenshot_uses_openai_image_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test")
        client, requests = make_client_create(answer=DIAGNOSIS_ANSWER)
        provider = OpenAIProvider(Config(model="gpt-5"))

        with mock.patch.object(provider, "_get_client", return_value=client):
            provider.classify_group_failure(
                prompt="p",
                user_instructions="",
                group_prompt="the checkout flow",
                group_steps=GROUP_STEPS,
                step_text="the status shows order confirmed",
                attempt_history=[],
                snapshot="- snap",
                screenshot=b"png-bytes",
            )

        user_content = requests[0]["messages"][1]["content"]
        assert isinstance(user_content, list)
        assert user_content[0]["type"] == "text"
        image_block = user_content[1]
        assert image_block["type"] == "image_url"  # parity: the diagnosis attaches the same image shape
        assert image_block["image_url"]["url"].startswith("data:image/png;base64,")
