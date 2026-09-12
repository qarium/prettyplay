"""Tests for the shared classify_step_failure routine of the prettyplay.engine cell."""

import inspect
from pathlib import Path

import pytest
from prettyplay.config import Config
from prettyplay.engine import classify_step_failure
from prettyplay.failures import LLMUnavailableError
from prettyplay.llm import FailureClassification

STEP_CODE = "def step(page) -> None:\n    page.get_by_role('button', name='Sign in').click()\n"


class FakePage:
    """Fake page facade boundary: snapshot plus counted screenshot calls."""

    def __init__(self) -> None:
        self.screenshot_calls = 0

    def aria_snapshot(self) -> str:
        return "body: main"

    def screenshot(self) -> bytes:
        self.screenshot_calls += 1
        return b"png"


class ClassificationProvider:
    """Stub provider boundary returning one scripted verdict with recorded requests."""

    def __init__(self, verdict: FailureClassification) -> None:
        self.verdict = verdict
        self.classify_failure_calls: list[dict[str, object]] = []

    def classify_failure(self, **kwargs: object) -> FailureClassification:
        self.classify_failure_calls.append(dict(kwargs))
        return self.verdict


class UnavailableProvider:
    """Stub provider whose service is down: classification raises LLMUnavailableError."""

    def classify_failure(self, **_kwargs: object) -> FailureClassification:
        raise LLMUnavailableError("openai down")


class TestClassifyStepFailureContract:
    """Contract tests: facade import and the fixed parameter list."""

    def test_classify_step_failure_is_importable_from_facade(self) -> None:
        assert callable(classify_step_failure)

    def test_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(classify_step_failure).parameters.values())

        assert [parameter.name for parameter in parameters] == [
            "config",
            "provider",
            "step_text",
            "code",
            "error",
            "page",
        ]

    def test_forwards_classification_prompt_as_user_instructions(self, tmp_path: Path) -> None:
        provider = ClassificationProvider(
            FailureClassification(
                category="rot",
                explanation="the button was renamed",
                recommendation="refresh the cache",
            )
        )
        page = FakePage()

        classify_step_failure(
            Config(cache_root=str(tmp_path), classification_prompt="answer in Russian"),
            provider,
            "step",
            "code",
            "err",
            page,
        )

        assert provider.classify_failure_calls[0]["user_instructions"] == "answer in Russian"


class TestClassifyStepFailureLogic:
    """Logic tests: input collection and the port call shape."""

    def test_classify_step_failure_collects_and_calls_port(self, tmp_path: Path) -> None:
        provider = ClassificationProvider(
            FailureClassification(
                category="rot",
                explanation="the button was renamed",
                recommendation="refresh the cache",
            )
        )
        page = FakePage()

        result = classify_step_failure(
            Config(cache_root=str(tmp_path), send_screenshots=True),
            provider,
            "click Sign in",
            STEP_CODE,
            "TimeoutError",
            page,
        )

        assert result.category == "rot"
        kwargs = provider.classify_failure_calls[0]
        assert kwargs["step_text"] == "click Sign in"
        assert kwargs["code"] == STEP_CODE
        assert kwargs["error"] == "TimeoutError"
        assert kwargs["snapshot"] == "body: main"
        assert kwargs["screenshot"] == b"png"
        assert kwargs["prompt"].startswith("You classify a failure of a web UI test step.")
        assert "cached" not in kwargs["prompt"]

    def test_classify_step_failure_without_screenshots(self, tmp_path: Path) -> None:
        provider = ClassificationProvider(FailureClassification(category="rot", explanation="e", recommendation="r"))
        page = FakePage()

        classify_step_failure(
            Config(cache_root=str(tmp_path), send_screenshots=False),
            provider,
            "click Sign in",
            STEP_CODE,
            "TimeoutError",
            page,
        )

        kwargs = provider.classify_failure_calls[0]
        assert kwargs["screenshot"] is None
        assert page.screenshot_calls == 0

    def test_provider_unavailability_propagates_untouched(self, tmp_path: Path) -> None:
        config = Config(cache_root=str(tmp_path))

        with pytest.raises(LLMUnavailableError) as excinfo:
            classify_step_failure(config, UnavailableProvider(), "s", STEP_CODE, "err", FakePage())

        assert "openai down" in str(excinfo.value)

    def test_classify_step_failure_passes_classification_instructions(self, tmp_path: Path) -> None:
        provider = ClassificationProvider(
            FailureClassification(
                category="rot",
                explanation="the button was renamed",
                recommendation="refresh the cache",
            )
        )
        page = FakePage()

        classify_step_failure(
            Config(cache_root=str(tmp_path), classification_prompt="answer in Russian"),
            provider,
            "step",
            "code",
            "err",
            page,
        )

        recorded = provider.classify_failure_calls[0]
        assert recorded["user_instructions"] == "answer in Russian"
        assert "- USER INSTRUCTIONS: the project's classification guidance, when configured" in recorded["prompt"]

        empty = ClassificationProvider(
            FailureClassification(category="rot", explanation="e", recommendation="r")
        )
        classify_step_failure(Config(cache_root=str(tmp_path)), empty, "step", "code", "err", FakePage())

        assert empty.classify_failure_calls[0]["user_instructions"] == ""
