"""Tests for the StepGenerator of the prettyplay.engine cell."""

import inspect
import logging
import re
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from prettyplay.cache import RunBudgets, StepCache, StepIdentity
from prettyplay.config import Config
from prettyplay.engine import StepGenerator
from prettyplay.engine import generator as generator_module  # для проверки переноса CLASSIFICATION_PROMPT
from prettyplay.engine.generator import PAGE_API_SURFACE, SYSTEM_PROMPT
from prettyplay.failures import IncurableStepError, LlmUnavailableError, ProductDefectError
from prettyplay.llm import FailureClassification
from prettyplay.reporting import StepHooks, StepReporter

WORKING_CODE = "def step(page) -> None:\n    page.open('https://example.com')\n"
BROKEN_CODE = "def step(page) -> None:\n    page.find_by_role('button', name='Войти').click()\n"

FACADE_PRACTICE = Path("prettyplay") / "driver" / ".usages" / "facade.md"


class FakeLocator:
    """Fake element boundary: expectations fail with the scripted message."""

    def __init__(self, assertion_message: str | None) -> None:
        self._assertion_message = assertion_message

    def expect_visible(self) -> None:
        if self._assertion_message is not None:
            raise AssertionError(self._assertion_message)


class FakePage:
    """Fake page facade boundary: snapshot plus recorded facade calls."""

    def __init__(self, assertion_message: str | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._assertion_message = assertion_message

    def open(self, url: str) -> None:
        self.calls.append(("open", url))

    def find_by_text(self, text: str) -> FakeLocator:
        self.calls.append(("find_by_text", text))
        return FakeLocator(self._assertion_message)

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
    """Stub LLM provider boundary: scripted answers and verdicts with recorded requests."""

    def __init__(self, answers: list[str], verdict: FailureClassification | None = None) -> None:
        self.answers = list(answers)
        self.verdict = verdict
        self.calls: list[dict[str, object]] = []
        self.classify_failure_calls: list[dict[str, object]] = []

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str = "",
        step_text: str = "",
        previous_steps: list[str] | None = None,
        snapshot: str = "",
        screenshot: bytes | None = None,
        page_api: str = "",
        existing_code: str | None = None,
        error: str | None = None,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "user_instructions": user_instructions,
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

    def classify_failure(self, **kwargs: object) -> FailureClassification | None:
        self.classify_failure_calls.append(dict(kwargs))
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


class UnavailableProvider:
    """Stub provider whose service is down: every request raises LlmUnavailableError."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_step_code(self, **_kwargs: object) -> str:
        self.calls += 1
        raise LlmUnavailableError("llm unavailable: openai request failed")

    def classify_failure(self, **_kwargs: object) -> FailureClassification:
        raise LlmUnavailableError("llm unavailable: openai request failed")


class TimeoutPage(FakePage):
    """Fake page where every candidate fails with a non-assertion TimeoutError."""

    def find_by_role(self, role: str, name: str) -> None:
        self.calls.append(("find_by_role", role, name))
        raise TimeoutError("navigation timed out")


class PlaywrightTimeoutPage(FakePage):
    """Fake page where the locator action fails with the real Playwright TimeoutError."""

    def find_by_role(self, role: str, name: str) -> None:
        self.calls.append(("find_by_role", role, name))
        raise PlaywrightTimeoutError("locator.click: Timeout 30000ms exceeded")


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

    def test_system_prompt_constant_renamed(self) -> None:
        assert hasattr(generator_module, "SYSTEM_PROMPT")
        assert not hasattr(generator_module, "GENERATION_PROMPT")  # переименован константой Task 7


class GeneratorFixture:
    """Generator assembled on a tmp cache with recording visibility, for logic tests."""

    def __init__(
        self,
        tmp_path: Path,
        provider: object,
        limits: tuple[int, int] = (3, 2),
    ) -> None:
        self.recorder = RecorderHook()
        self.reporter = StepReporter(hooks=[self.recorder])
        self.config = Config(cache_root=str(tmp_path))
        self.cache = StepCache(self.config, None, self.reporter)
        self.budgets = RunBudgets(*limits)
        self.generator = StepGenerator(self.config, provider, self.cache, self.budgets, self.reporter)


ROT_VERDICT = FailureClassification(
    category="rot",
    explanation="the button was renamed",
    recommendation="refresh the cache",
)


def facade_page_calls(practice: str) -> list[str]:
    """Extract the ordered ``page.*`` call column of the facade practice table."""
    return re.findall(r"^\| (page\.[a-z_]+(?:\([^)]*\))?)", practice, flags=re.MULTILINE)


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
        assert request["prompt"] == SYSTEM_PROMPT
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

    def test_generator_passes_generation_prompt_to_provider(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        recorder = RecorderHook()
        reporter = StepReporter(hooks=[recorder])
        config = Config(cache_root=str(tmp_path), generation_prompt="prefer data-test-id")
        generator = StepGenerator(config, provider, StepCache(config, None, reporter), RunBudgets(3, 2), reporter)
        page = FakePage()

        generator.generate(make_identity(), "click Sign in", [], page)

        captured = provider.calls[0]
        assert captured["user_instructions"] == "prefer data-test-id"
        assert captured["prompt"] == SYSTEM_PROMPT
        assert "page.find_by_attribute(name, value)" in captured["page_api"]

    def test_regenerate_carries_user_instructions_with_code_and_error(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        recorder = RecorderHook()
        reporter = StepReporter(hooks=[recorder])
        config = Config(cache_root=str(tmp_path), generation_prompt="prefer data-test-id")
        generator = StepGenerator(config, provider, StepCache(config, None, reporter), RunBudgets(1, 1), reporter)
        page = FakePage()

        generator.regenerate(
            make_identity(),
            "click Sign in",
            [],
            page,
            existing_code="def step(page) -> None:\n    page.open('https://old')\n",
            error="TimeoutError",
        )

        captured = provider.calls[0]
        # instructions travel with the regeneration-only fields through the one shared call site
        assert captured["user_instructions"] == "prefer data-test-id"
        assert captured["existing_code"] == "def step(page) -> None:\n    page.open('https://old')\n"
        assert captured["error"] == "TimeoutError"
        assert captured["prompt"] == SYSTEM_PROMPT

    def test_empty_generation_prompt_passes_empty_instructions(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage()

        fixture.generator.generate(make_identity(), "click Sign in", [], page)

        # движок передаёт значение безусловно; пустая строка означает «нет блока» в хелпере провайдера
        assert provider.calls[0]["user_instructions"] == ""

    def test_generate_retries_with_existing_code_then_succeeds(self, tmp_path: Path) -> None:
        provider = StubProvider([BROKEN_CODE, WORKING_CODE], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider)
        page = TimeoutPage()

        step = fixture.generator.generate(make_identity(), "нажать Войти", [], page)

        assert step.code == WORKING_CODE
        assert len(provider.calls) == 2
        assert provider.calls[1]["existing_code"] == BROKEN_CODE
        assert "navigation timed out" in provider.calls[1]["error"]
        attempts = [
            payload["attempt"] for event, payload in fixture.recorder.events if event == "on_generation_started"
        ]
        assert attempts == [1, 2]

    def test_generate_budget_exhaustion_raises_incurable(self, tmp_path: Path) -> None:
        provider = StubProvider([BROKEN_CODE, BROKEN_CODE, BROKEN_CODE], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider)
        page = TimeoutPage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "невозможный шаг", [], page)

        assert excinfo.value.reason == "generation attempt budget exhausted; last failure: navigation timed out"
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "rot"  # вердикт последнего кандидата
        assert len(provider.calls) == 3
        assert len(provider.classify_failure_calls) == 1  # одна классификация на исчерпание
        assert not [event for event in fixture.recorder.events if event[0] == "on_cache_saved"]

    def test_generate_pre_exhausted_budget_keeps_plain_reason(self, tmp_path: Path) -> None:
        provider = StubProvider([])
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 1))
        identity = make_identity()
        page = FakePage()

        assert fixture.budgets.try_generation(identity) is True  # тратим единственную попытку напрямую
        assert fixture.budgets.try_generation(identity) is False  # бюджет уже потрачен до вызова

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(identity, "невозможный шаг", [], page)

        assert excinfo.value.reason == "generation attempt budget exhausted"
        assert provider.calls == []  # ни одного запроса к провайдеру

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

    def test_regenerate_budget_exhaustion_names_healing_pool(self, tmp_path: Path) -> None:
        provider = StubProvider([BROKEN_CODE], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider, limits=(3, 1))
        identity = make_identity()
        page = TimeoutPage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.regenerate(
                identity,
                "невозможный шаг",
                [],
                page,
                existing_code=BROKEN_CODE,
                error="assertion failed",  # исходная ошибка кэша — reason должен нести последнюю ошибку кандидата
            )

        assert excinfo.value.reason == "healing attempt budget exhausted; last failure: navigation timed out"
        assert excinfo.value.verdict is None  # вердикт присоединяет healer — без второго LLM-запроса
        assert excinfo.value.recommendation == "reword the step or refresh the cache"  # fallback без вердикта
        assert len(provider.calls) == 1  # healing-бюджет (1) исчерпан после первой попытки
        assert provider.classify_failure_calls == []  # healing-пул не классифицирует исчерпание

    def test_messageless_candidate_failure_is_retried_not_crashed(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE, WORKING_CODE], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage(assertion_message="")  # message-less assert: str(exc) == ''

        first = fixture.generator.generate(make_identity(), "проверить страницу", [], page)

        assert first.code == WORKING_CODE
        assert len(provider.calls) == 1  # даже пустой AssertionError — остановка без повторов
        assert provider.calls[0]["error"] is None

    def test_messageless_candidate_check_keeps_plain_reason(self, tmp_path: Path) -> None:
        provider = StubProvider(
            ["def step(page) -> None:\n    page.find_by_text('Welcome back').expect_visible()\n"],
            verdict=FailureClassification(category="incurable", explanation="e", recommendation="r"),
        )
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 2))
        page = FakePage(assertion_message="")  # message-less assert: str(exc) == ''

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "невозможный шаг", [], page)

        # пустое описание сбоя не оставляет в reason хвоста «; last failure: »
        assert excinfo.value.reason == "candidate check failed: "

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

    def test_generate_failed_check_product_defect_stops_and_carries_verdict(self, tmp_path: Path) -> None:
        provider = StubProvider(
            ["def step(page) -> None:\n    page.find_by_text('Welcome back').expect_visible()\n"],
            verdict=FailureClassification(
                category="product_defect",
                explanation="the banner is missing",
                recommendation="file a bug",
            ),
        )
        fixture = GeneratorFixture(tmp_path, provider)  # RunBudgets(3, 2)
        page = FakePage(assertion_message="banner missing")

        with pytest.raises(ProductDefectError) as excinfo:
            fixture.generator.generate(make_identity(), "see the welcome banner", [], page)

        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "product_defect"
        assert "banner missing" in str(excinfo.value)
        assert len(provider.calls) == 1  # retries stopped at once
        assert len(provider.classify_failure_calls) == 1
        assert provider.classify_failure_calls[0]["error"] == "candidate check failed: banner missing"

    def test_generate_failed_check_non_defect_verdict_raises_incurable(self, tmp_path: Path) -> None:
        provider = StubProvider(
            ["def step(page) -> None:\n    page.find_by_text('Welcome back').expect_visible()\n"],
            verdict=FailureClassification(
                category="incurable",
                explanation="the step is ambiguous",
                recommendation="reword the step",
            ),
        )
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage(assertion_message="banner missing")

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "see the welcome banner", [], page)

        assert excinfo.value.reason.startswith("candidate check failed")
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "incurable"
        assert len(provider.calls) == 1
        assert len(provider.classify_failure_calls) == 1

    def test_generate_exhaustion_classifies_last_candidate(self, tmp_path: Path) -> None:
        provider = StubProvider(
            [BROKEN_CODE],
            verdict=FailureClassification(
                category="incurable",
                explanation="the selector no longer matches",
                recommendation="reword the step",
            ),
        )
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 2))
        page = TimeoutPage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "невозможный шаг", [], page)

        assert excinfo.value.reason.startswith("generation attempt budget exhausted")
        assert "last failure:" in excinfo.value.reason
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "incurable"
        assert provider.classify_failure_calls[0]["error"] == "navigation timed out"

    def test_generate_quiet_verdict_skip_on_unavailable_classification(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = StubProvider(
            ["def step(page) -> None:\n    page.find_by_text('Welcome back').expect_visible()\n"],
            verdict=LlmUnavailableError("openai down"),
        )
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage(assertion_message="banner missing")

        with caplog.at_level(logging.WARNING, logger="prettyplay"), pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "see the welcome banner", [], page)

        assert excinfo.value.verdict is None
        assert excinfo.value.reason.startswith("candidate check failed")
        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert any("verdict skipped" in record.message for record in warnings)

    def test_generate_exhaustion_quiet_verdict_skip_on_unavailable_classification(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Exhaustion classification quiet-skips too: the budget failure is never masked."""
        provider = StubProvider([BROKEN_CODE], verdict=LlmUnavailableError("openai down"))
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 2))
        page = TimeoutPage()

        with caplog.at_level(logging.WARNING, logger="prettyplay"), pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "impossible step", [], page)

        assert excinfo.value.reason.startswith("generation attempt budget exhausted")
        assert "last failure:" in excinfo.value.reason
        assert excinfo.value.verdict is None  # quiet skip — not an infrastructure failure
        assert excinfo.value.recommendation == "reword the step or refresh the cache"  # fallback без вердикта
        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert any("verdict skipped" in record.message for record in warnings)

    def test_generate_playwright_timeout_is_retried_not_a_failed_check(self, tmp_path: Path) -> None:
        """ADR-3 boundary pin: the real Playwright locator timeout is not an AssertionError."""
        assert not issubclass(PlaywrightTimeoutError, AssertionError)  # граница, на которую опирается стоп проверок
        provider = StubProvider([BROKEN_CODE, WORKING_CODE], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider)
        page = PlaywrightTimeoutPage()

        step = fixture.generator.generate(make_identity(), "press the sign in button", [], page)

        assert step.code == WORKING_CODE
        assert len(provider.calls) == 2  # таймаут локатора тратит попытку и уходит в ретрай, не в стоп проверок
        assert provider.calls[1]["existing_code"] == BROKEN_CODE
        assert provider.classify_failure_calls == []

    def test_generate_first_refusal_without_candidate(self, tmp_path: Path) -> None:
        provider = StubProvider([], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 2))
        identity = make_identity()
        page = FakePage()

        assert fixture.budgets.try_generation(identity) is True  # тратим попытку до генерации
        assert fixture.budgets.try_generation(identity) is False

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(identity, "невозможный шаг", [], page)

        assert excinfo.value.reason == "generation attempt budget exhausted"
        assert excinfo.value.verdict is None  # классифицировать нечего
        assert provider.classify_failure_calls == []
        assert provider.calls == []


class TestPromptConstants:
    """Constant tests: prompts and the frozen page API surface."""

    def test_generation_prompt_is_frozen_text(self) -> None:
        assert SYSTEM_PROMPT.startswith("You generate executable Python code")
        assert "def step(page) -> None:" in SYSTEM_PROMPT

    def test_generation_prompt_carries_the_scroll_rule(self) -> None:
        assert (
            "- Scroll abilities exist for scenario scrolling: bring an element into view, scroll by an "
            "amount, to the page end or start, inside a scrollable container" in SYSTEM_PROMPT
        )
        # правило скролла стоит сразу после правила поиска элементов
        locating = SYSTEM_PROMPT.index("Locating by role and accessible name")
        scroll = SYSTEM_PROMPT.index("Scroll abilities exist")
        no_delays = SYSTEM_PROMPT.index("No fixed delays")
        assert locating < scroll < no_delays

    def test_system_prompt_documents_user_instructions_input(self) -> None:
        # строка входа USER INSTRUCTIONS стоит сразу после строки входа PAGE API
        page_api_input = SYSTEM_PROMPT.index("- PAGE API: the exact surface listing")
        user_instructions_input = SYSTEM_PROMPT.index("- USER INSTRUCTIONS: the project's code style guidance")
        code_input = SYSTEM_PROMPT.index("- CODE: the existing step code that failed")
        assert page_api_input < user_instructions_input < code_input

    def test_system_prompt_carries_the_universal_locating_priority(self) -> None:
        assert (
            "- Attribute, CSS and XPath locating exist for elements without accessible names — the "
            "accessibility-first priority stands unless USER INSTRUCTIONS say otherwise" in SYSTEM_PROMPT
        )
        # приоритет универсального поиска стоит сразу после строки role/text/label
        locating = SYSTEM_PROMPT.index("Locating by role and accessible name is preferred")
        universal = SYSTEM_PROMPT.index("Attribute, CSS and XPath locating exist")
        scroll = SYSTEM_PROMPT.index("Scroll abilities exist")
        assert locating < universal < scroll

    def test_classification_prompt_moved_out_of_generator(self) -> None:
        assert not hasattr(generator_module, "CLASSIFICATION_PROMPT")  # переехала в classification.py

    def test_page_api_surface_lists_every_facade_call(self) -> None:
        for call in (
            "page.open(url)",
            "page.find_by_role(role, name)",
            "page.find_by_label(label)",
            "page.find_by_text(text)",
            "page.find_by_attribute(name, value)",
            "page.find_by_css(selector)",
            "page.find_by_xpath(xpath)",
            "page.aria_snapshot()",
            "page.screenshot()",
            "page.url",
            "page.scroll_to_element(element)",
            "page.scroll_down(pixels)",
            "page.scroll_up(pixels)",
            "page.scroll_to_bottom()",
            "page.scroll_to_top()",
            "page.scroll_into_view(element, container)",
            "page.scroll_container_down(container, pixels)",
            "page.scroll_container_up(container, pixels)",
            "element.click()",
            "element.fill(value)",
            "element.select_option(value)",
            "element.expect_visible()",
            "element.expect_text(text)",
            "element.expect_enabled()",
        ):
            assert call in PAGE_API_SURFACE
        assert "close" not in PAGE_API_SURFACE

    def test_page_api_surface_mirrors_facade_practice(self) -> None:
        practice = FACADE_PRACTICE.read_text(encoding="utf-8")
        surface_calls = [line.split("—")[0].strip() for line in PAGE_API_SURFACE.splitlines()]

        assert surface_calls == [
            *facade_page_calls(practice),
            "element.click()",
            "element.fill(value)",
            "element.select_option(value)",
            "element.expect_visible()",
            "element.expect_text(text)",
            "element.expect_enabled()",
        ]
        assert facade_page_calls(practice) == [
            "page.open(url)",
            "page.find_by_role(role, name)",
            "page.find_by_label(label)",
            "page.find_by_text(text)",
            "page.find_by_attribute(name, value)",
            "page.find_by_css(selector)",
            "page.find_by_xpath(xpath)",
            "page.aria_snapshot()",
            "page.screenshot()",
            "page.url",
            "page.scroll_to_element(element)",
            "page.scroll_down(pixels)",
            "page.scroll_up(pixels)",
            "page.scroll_to_bottom()",
            "page.scroll_to_top()",
            "page.scroll_into_view(element, container)",
            "page.scroll_container_down(container, pixels)",
            "page.scroll_container_up(container, pixels)",
        ]
