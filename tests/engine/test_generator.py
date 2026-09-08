"""Tests for the StepGenerator of the prettyplay.engine cell."""

import inspect
from datetime import date
from pathlib import Path

import pytest
from prettyplay.cache import RunBudgets, StepCache, StepIdentity
from prettyplay.config import Config
from prettyplay.engine import StepGenerator
from prettyplay.engine.generator import (
    CLASSIFICATION_PROMPT,
    GENERATION_PROMPT,
    PAGE_API_SURFACE,
)
from prettyplay.failures import IncurableStepError, LlmUnavailableError
from prettyplay.reporting import StepHooks, StepReporter

WORKING_CODE = "def step(page) -> None:\n    page.open('https://example.com')\n"
BROKEN_CODE = "def step(page) -> None:\n    page.find_by_role('button', name='Войти').click()\n"


class FakePage:
    """Fake page facade boundary: snapshot plus recorded facade calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def open(self, url: str) -> None:
        self.calls.append(("open", url))

    def aria_snapshot(self) -> str:
        self.calls.append(("aria_snapshot",))
        return "- snapshot"

    def screenshot(self) -> bytes:
        self.calls.append(("screenshot",))
        return b"png"


class FailingPage(FakePage):
    """Fake page where locator-driven step code fails like a broken assertion."""

    def find_by_role(self, role: str, name: str) -> None:
        raise AssertionError("element not found")


class StubProvider:
    """Stub LLM provider boundary: scripted answers with recorded requests."""

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, object]] = []

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        step_text: str,
        previous_steps: list[str],
        snapshot: str,
        screenshot: bytes | None,
        page_api: str,
        existing_code: str | None,
        error: str | None,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "step_text": step_text,
                "previous_steps": previous_steps,
                "snapshot": snapshot,
                "screenshot": screenshot,
                "page_api": page_api,
                "existing_code": existing_code,
                "error": error,
            }
        )
        if not self.answers:
            raise AssertionError("stub provider has no answers left")
        return self.answers.pop(0)


class UnavailableProvider:
    """Stub provider whose service is down: every request raises LlmUnavailableError."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_step_code(self, **_kwargs: object) -> str:
        self.calls += 1
        raise LlmUnavailableError("llm unavailable: openai request failed")


class RecorderHook(StepHooks):
    """Hook recording engine events into a shared ``events`` list for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str | int]]] = []

    def on_generation_started(self, step_text: str, attempt: int) -> None:
        self.events.append(("on_generation_started", {"step_text": step_text, "attempt": attempt}))

    def on_cache_saved(self, step_text: str, filename: str) -> None:
        self.events.append(("on_cache_saved", {"step_text": step_text, "filename": filename}))


class TestStepGeneratorContract:
    """Contract tests: facade import, constructor and method signatures."""

    def test_step_generator_is_importable_from_facade(self) -> None:
        assert isinstance(StepGenerator, type)

    def test_constructor_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(StepGenerator.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == [
            "config",
            "provider",
            "cache",
            "budgets",
            "reporter",
        ]

    def test_generate_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(StepGenerator.generate).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == [
            "identity",
            "step_text",
            "previous_steps",
            "page",
        ]

    def test_regenerate_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(StepGenerator.regenerate).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == [
            "identity",
            "step_text",
            "previous_steps",
            "page",
            "existing_code",
            "error",
        ]


class GeneratorFixture:
    """Generator assembled on a tmp cache with recording visibility, for logic tests."""

    def __init__(self, tmp_path: Path, provider: object, limits: tuple[int, int] = (3, 2)) -> None:
        self.recorder = RecorderHook()
        self.reporter = StepReporter(hooks=[self.recorder])
        self.config = Config(cache_root=str(tmp_path))
        self.cache = StepCache(self.config, None, self.reporter)
        self.budgets = RunBudgets(*limits)
        self.generator = StepGenerator(self.config, provider, self.cache, self.budgets, self.reporter)


def make_identity() -> StepIdentity:
    """Build a step identity for the tests."""
    return StepIdentity(cache_key="login-flow", step_type="action", normalized_text="открыть страницу")


class TestStepGeneratorLogic:
    """Logic tests: attempt loop, regeneration context, budgets, propagation."""

    def test_generate_success_stores_and_reports_attempt(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        identity = make_identity()
        page = FakePage()

        step = fixture.generator.generate(identity, "открыть страницу", [], page)

        assert step.code == WORKING_CODE
        assert step.identity == identity
        assert len(provider.calls) == 1
        assert provider.calls[0]["existing_code"] is None
        assert provider.calls[0]["error"] is None
        assert fixture.recorder.events[0] == (
            "on_generation_started",
            {"step_text": "открыть страницу", "attempt": 1},
        )
        assert isinstance(fixture.recorder.events[0][1]["attempt"], int)
        saved = [event for event in fixture.recorder.events if event[0] == "on_cache_saved"]
        assert saved == [("on_cache_saved", {"step_text": "открыть страницу", "filename": identity.filename})]

    def test_generate_sends_prompt_snapshot_and_page_api(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage()

        fixture.generator.generate(make_identity(), "открыть страницу", [], page)

        request = provider.calls[0]
        assert request["prompt"] == GENERATION_PROMPT
        assert request["snapshot"] == "- snapshot"
        assert request["page_api"] == PAGE_API_SURFACE
        assert request["screenshot"] is None  # send_screenshots по умолчанию False

    def test_generate_attaches_screenshot_when_enabled(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        recorder = RecorderHook()
        reporter = StepReporter(hooks=[recorder])
        config = Config(cache_root=str(tmp_path), send_screenshots=True)
        generator = StepGenerator(config, provider, StepCache(config, None, reporter), RunBudgets(3, 2), reporter)
        page = FakePage()

        generator.generate(make_identity(), "открыть страницу", [], page)

        assert provider.calls[0]["screenshot"] == b"png"

    def test_generate_retries_with_existing_code_then_succeeds(self, tmp_path: Path) -> None:
        provider = StubProvider([BROKEN_CODE, WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FailingPage()

        step = fixture.generator.generate(make_identity(), "нажать Войти", [], page)

        assert step.code == WORKING_CODE
        assert len(provider.calls) == 2
        assert provider.calls[1]["existing_code"] == BROKEN_CODE
        assert "element not found" in provider.calls[1]["error"]
        attempts = [
            payload["attempt"] for event, payload in fixture.recorder.events if event == "on_generation_started"
        ]
        assert attempts == [1, 2]

    def test_generate_budget_exhaustion_raises_incurable(self, tmp_path: Path) -> None:
        provider = StubProvider([BROKEN_CODE, BROKEN_CODE, BROKEN_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FailingPage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "невозможный шаг", [], page)

        assert "budget" in excinfo.value.reason
        assert excinfo.value.recommendation
        assert len(provider.calls) == 3
        assert not [event for event in fixture.recorder.events if event[0] == "on_cache_saved"]

    def test_generate_provider_unavailable_propagates_immediately(self, tmp_path: Path) -> None:
        provider = UnavailableProvider()
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 1))
        identity = make_identity()
        page = FakePage()

        with pytest.raises(LlmUnavailableError):
            fixture.generator.generate(identity, "шаг", [], page)

        assert provider.calls == 1  # никаких повторов на инфраструктурный сбой
        assert fixture.budgets.try_generation(identity) is False  # израсходована ровно 1 попытка

    def test_regenerate_spends_healing_budget_not_generation(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 1))
        identity = make_identity()
        page = FakePage()

        step = fixture.generator.regenerate(
            identity,
            "открыть страницу",
            [],
            page,
            existing_code="def step(page) -> None:\n    page.open('https://old')\n",
            error="assertion failed",
        )

        assert step.code == WORKING_CODE
        assert provider.calls[0]["existing_code"] == "def step(page) -> None:\n    page.open('https://old')\n"
        assert provider.calls[0]["error"] == "assertion failed"
        # healing-бюджет израсходован, generation-бюджет не тронут
        assert fixture.budgets.try_healing(identity) is False
        assert fixture.budgets.try_generation(identity) is True

    def test_generated_step_is_saved_into_cache(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        identity = make_identity()
        page = FakePage()

        fixture.generator.generate(identity, "открыть страницу", [], page)

        loaded = fixture.cache.load(identity)
        assert loaded is not None
        assert loaded.code.rstrip("\n") == WORKING_CODE.rstrip("\n")  # сериализатор добавляет хвостовой \n
        assert loaded.created_at

    def test_created_at_is_today_iso(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage()

        step = fixture.generator.generate(make_identity(), "открыть страницу", [], page)

        assert step.created_at == date.today().isoformat()  # noqa: DTZ011 — сверка календарной даты


class TestPromptConstants:
    """Constant tests: prompts and the frozen page API surface."""

    def test_generation_prompt_is_frozen_text(self) -> None:
        assert GENERATION_PROMPT.startswith("You generate executable Python code")
        assert "def step(page) -> None:" in GENERATION_PROMPT

    def test_classification_prompt_is_frozen_text(self) -> None:
        assert CLASSIFICATION_PROMPT.startswith("You classify a failure")
        assert "category | explanation | recommendation" in CLASSIFICATION_PROMPT

    def test_page_api_surface_lists_every_facade_call(self) -> None:
        for call in (
            "page.open(url)",
            "page.find_by_role(role, name)",
            "page.find_by_label(label)",
            "page.find_by_text(text)",
            "page.aria_snapshot()",
            "page.screenshot()",
            "page.url",
            "element.click()",
            "element.fill(value)",
            "element.select_option(value)",
            "element.expect_visible()",
            "element.expect_text(text)",
            "element.expect_enabled()",
        ):
            assert call in PAGE_API_SURFACE
        assert "close" not in PAGE_API_SURFACE
