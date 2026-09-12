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
from prettyplay.driver import DialogFacade, FrameFacade, LocatorFacade, PageFacade
from prettyplay.engine import StepGenerator
from prettyplay.engine import generator as generator_module  # to verify the CLASSIFICATION_PROMPT move
from prettyplay.engine.generator import PAGE_API_SURFACE, SYSTEM_PROMPT
from prettyplay.failures import IncurableStepError, LLMUnavailableError, ProductDefectError
from prettyplay.llm import FailureClassification
from prettyplay.reporting import StepHooks, StepReporter

WORKING_CODE = "def step(page) -> None:\n    page.goto('https://example.com')\n"
BROKEN_CODE = "def step(page) -> None:\n    page.get_by_role('button', name='Войти').click()\n"

FACADE_PRACTICE = Path(__file__).resolve().parents[2] / "prettyplay" / "driver" / ".usages" / "facade.md"


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

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))

    def get_by_text(self, text: str) -> FakeLocator:
        self.calls.append(("get_by_text", text))
        return FakeLocator(self._assertion_message)

    def aria_snapshot(self) -> str:
        self.calls.append(("aria_snapshot",))
        return "- snapshot"

    def screenshot(self) -> bytes:
        self.calls.append(("screenshot",))
        return b"png"


class FailingPage(FakePage):
    """Fake page where locator-driven step code fails like a broken assertion."""

    def get_by_role(self, role: str, name: str) -> None:
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
    """Stub provider whose service is down: every request raises LLMUnavailableError."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_step_code(self, **_kwargs: object) -> str:
        self.calls += 1
        raise LLMUnavailableError("llm unavailable: openai request failed")

    def classify_failure(self, **_kwargs: object) -> FailureClassification:
        raise LLMUnavailableError("llm unavailable: openai request failed")


class TimeoutPage(FakePage):
    """Fake page where every candidate fails with a non-assertion TimeoutError."""

    def get_by_role(self, role: str, name: str) -> None:
        self.calls.append(("get_by_role", role, name))
        raise TimeoutError("navigation timed out")


class PlaywrightTimeoutPage(FakePage):
    """Fake page where the locator action fails with the real Playwright TimeoutError."""

    def get_by_role(self, role: str, name: str) -> None:
        self.calls.append(("get_by_role", role, name))
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
        assert not hasattr(generator_module, "GENERATION_PROMPT")  # renamed by the Task 7 constant


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


def facade_surface_rows(practice: str, prefix: str) -> list[str]:
    """Extract the ordered call column of one facade practice surface table."""
    return re.findall(rf"^\| ({prefix}\.[a-z_]+(?:\([^)]*\))?)", practice, flags=re.MULTILINE)


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
        assert request["screenshot"] is None  # send_screenshots defaults to False

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
        assert "page.get_by_test_id(test_id)" in captured["page_api"]

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
            existing_code="def step(page) -> None:\n    page.goto('https://old')\n",
            error="TimeoutError",
        )

        captured = provider.calls[0]
        # instructions travel with the regeneration-only fields through the one shared call site
        assert captured["user_instructions"] == "prefer data-test-id"
        assert captured["existing_code"] == "def step(page) -> None:\n    page.goto('https://old')\n"
        assert captured["error"] == "TimeoutError"
        assert captured["prompt"] == SYSTEM_PROMPT

    def test_empty_generation_prompt_passes_empty_instructions(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage()

        fixture.generator.generate(make_identity(), "click Sign in", [], page)

        # the engine passes the value unconditionally; an empty string means "no block" in the provider helper
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

        assert excinfo.value.reason == "generation attempt budget exhausted"
        assert excinfo.value.error == "TimeoutError: navigation timed out"  # the last candidate, full and typed
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "rot"  # the verdict of the last candidate
        assert len(provider.calls) == 3
        assert len(provider.classify_failure_calls) == 1  # one classification on exhaustion
        assert not [event for event in fixture.recorder.events if event[0] == "on_cache_saved"]

    def test_generate_pre_exhausted_budget_keeps_plain_reason(self, tmp_path: Path) -> None:
        provider = StubProvider([])
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 1))
        identity = make_identity()
        page = FakePage()

        assert fixture.budgets.try_generation(identity) is True  # spend the only attempt directly
        assert fixture.budgets.try_generation(identity) is False  # the budget is already spent before the call

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(identity, "невозможный шаг", [], page)

        assert excinfo.value.reason == "generation attempt budget exhausted"
        assert provider.calls == []  # no requests to the provider

    def test_generate_provider_unavailable_propagates_immediately(self, tmp_path: Path) -> None:
        provider = UnavailableProvider()
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 1))
        identity = make_identity()
        page = FakePage()

        with pytest.raises(LLMUnavailableError):
            fixture.generator.generate(identity, "шаг", [], page)

        assert provider.calls == 1  # no retries on an infrastructure failure
        assert fixture.budgets.try_generation(identity) is False  # exactly 1 attempt spent

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
            existing_code="def step(page) -> None:\n    page.goto('https://old')\n",
            error="assertion failed",
        )

        assert step.code == WORKING_CODE
        assert provider.calls[0]["existing_code"] == "def step(page) -> None:\n    page.goto('https://old')\n"
        assert provider.calls[0]["error"] == "assertion failed"
        # the healing budget is spent, the generation budget untouched
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
                error="assertion failed",  # the original cache error — reason must carry the candidate's last error
            )

        assert excinfo.value.reason == "healing attempt budget exhausted"
        assert excinfo.value.error == "TimeoutError: navigation timed out"  # the last candidate of the pool
        assert excinfo.value.verdict is None  # the healer attaches the verdict — no second LLM request
        assert excinfo.value.recommendation == "reword the step or refresh the cache"  # fallback without a verdict
        assert len(provider.calls) == 1  # the healing budget (1) is exhausted after the first attempt
        assert provider.classify_failure_calls == []  # the healing pool does not classify exhaustion

    def test_messageless_candidate_failure_is_retried_not_crashed(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE, WORKING_CODE], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage(assertion_message="")  # message-less assert: str(exc) == ''

        first = fixture.generator.generate(make_identity(), "проверить страницу", [], page)

        assert first.code == WORKING_CODE
        assert len(provider.calls) == 1  # even a message-less AssertionError — stop without retries
        assert provider.calls[0]["error"] is None

    def test_messageless_candidate_check_keeps_plain_reason(self, tmp_path: Path) -> None:
        provider = StubProvider(
            ["def step(page) -> None:\n    page.get_by_text('Welcome back').expect_visible()\n"],
            verdict=FailureClassification(category="incurable", explanation="e", recommendation="r"),
        )
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 2))
        page = FakePage(assertion_message="")  # message-less assert: str(exc) == ''

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "невозможный шаг", [], page)

        # an empty failure description leaves the em-dash reason without an error tail
        assert excinfo.value.reason == "candidate check failed — "

    def test_generated_step_is_saved_into_cache(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        identity = make_identity()
        page = FakePage()

        fixture.generator.generate(identity, "открыть страницу", [], page)

        loaded = fixture.cache.load(identity)
        assert loaded is not None
        assert loaded.code.rstrip("\n") == WORKING_CODE.rstrip("\n")  # the serializer appends a trailing \n
        assert loaded.created_at

    def test_created_at_is_today_iso(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage()

        step = fixture.generator.generate(make_identity(), "открыть страницу", [], page)

        assert step.created_at == date.today().isoformat()  # noqa: DTZ011 — calendar date comparison

    def test_generate_failed_check_product_defect_stops_and_carries_verdict(self, tmp_path: Path) -> None:
        provider = StubProvider(
            ["def step(page) -> None:\n    page.get_by_text('Welcome back').expect_visible()\n"],
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
        assert excinfo.value.message == "the banner is missing"  # the verdict explanation is the reason
        assert excinfo.value.error == "banner missing"  # the full check text, no prefix
        assert "banner missing" in str(excinfo.value)
        assert len(provider.calls) == 1  # retries stopped at once
        assert len(provider.classify_failure_calls) == 1
        assert provider.classify_failure_calls[0]["error"] == "banner missing"

    def test_generate_failed_check_non_defect_verdict_raises_incurable(self, tmp_path: Path) -> None:
        provider = StubProvider(
            ["def step(page) -> None:\n    page.get_by_text('Welcome back').expect_visible()\n"],
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
        assert excinfo.value.error == "TimeoutError: navigation timed out"
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "incurable"
        assert provider.classify_failure_calls[0]["error"] == "TimeoutError: navigation timed out"

    def test_generate_quiet_verdict_skip_on_unavailable_classification(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = StubProvider(
            ["def step(page) -> None:\n    page.get_by_text('Welcome back').expect_visible()\n"],
            verdict=LLMUnavailableError("openai down"),
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
        provider = StubProvider([BROKEN_CODE], verdict=LLMUnavailableError("openai down"))
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 2))
        page = TimeoutPage()

        with caplog.at_level(logging.WARNING, logger="prettyplay"), pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "impossible step", [], page)

        assert excinfo.value.reason.startswith("generation attempt budget exhausted")
        assert excinfo.value.error == "TimeoutError: navigation timed out"  # error field even without a verdict
        assert excinfo.value.verdict is None  # quiet skip — not an infrastructure failure
        assert excinfo.value.recommendation == "reword the step or refresh the cache"  # fallback without a verdict
        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert any("verdict skipped" in record.message for record in warnings)

    def test_generate_playwright_timeout_is_retried_not_a_failed_check(self, tmp_path: Path) -> None:
        """ADR-3 boundary pin: the real Playwright locator timeout is not an AssertionError."""
        assert not issubclass(PlaywrightTimeoutError, AssertionError)  # the boundary the check-stop relies on
        provider = StubProvider([BROKEN_CODE, WORKING_CODE], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider)
        page = PlaywrightTimeoutPage()

        step = fixture.generator.generate(make_identity(), "press the sign in button", [], page)

        assert step.code == WORKING_CODE
        assert len(provider.calls) == 2  # a locator timeout spends an attempt and retries, no check-stop
        assert provider.calls[1]["existing_code"] == BROKEN_CODE
        assert provider.classify_failure_calls == []

    def test_generate_first_refusal_without_candidate(self, tmp_path: Path) -> None:
        provider = StubProvider([], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 2))
        identity = make_identity()
        page = FakePage()

        assert fixture.budgets.try_generation(identity) is True  # spend an attempt before generation
        assert fixture.budgets.try_generation(identity) is False

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(identity, "невозможный шаг", [], page)

        assert excinfo.value.reason == "generation attempt budget exhausted"
        assert excinfo.value.verdict is None  # nothing to classify
        assert provider.classify_failure_calls == []
        assert provider.calls == []

    def test_generator_carries_full_error_text_in_terminal_failures(self, tmp_path: Path) -> None:
        long_message = "Locator expected to be visible" + " x" * 120  # well past the old 200-char cut
        defect_provider = StubProvider(
            ["def step(page) -> None:\n    page.get_by_text('Welcome back').expect_visible()\n"],
            verdict=FailureClassification(
                category="product_defect",
                explanation="the banner is gone",
                recommendation="file a bug",
            ),
        )
        defect_fixture = GeneratorFixture(tmp_path, defect_provider)
        defect_page = FakePage(assertion_message=long_message)

        with pytest.raises(ProductDefectError) as defect:
            defect_fixture.generator.generate(make_identity(), "see the welcome banner", [], defect_page)

        assert defect.value.error == long_message  # full, no prefix, no truncation at 200 chars
        assert len(defect.value.error) > 200

        exhausted_provider = StubProvider(
            [BROKEN_CODE],
            verdict=FailureClassification(category="incurable", explanation="e", recommendation="r"),
        )
        exhausted_fixture = GeneratorFixture(tmp_path, exhausted_provider, limits=(1, 2))
        timeout_page = TimeoutPage()

        with pytest.raises(IncurableStepError) as exhausted:
            exhausted_fixture.generator.generate(make_identity(), "невозможный шаг", [], timeout_page)

        assert exhausted.value.error == "TimeoutError: navigation timed out"  # the last candidate full text
        assert exhausted.value.reason == "generation attempt budget exhausted"  # no colon, no embedded error


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
        # the scroll rule sits right after the element-locating rule
        locating = SYSTEM_PROMPT.index("Locating by role and accessible name")
        scroll = SYSTEM_PROMPT.index("Scroll abilities exist")
        no_delays = SYSTEM_PROMPT.index("No fixed delays")
        assert locating < scroll < no_delays

    def test_system_prompt_documents_user_instructions_input(self) -> None:
        # the USER INSTRUCTIONS input line sits right after the PAGE API input line
        page_api_input = SYSTEM_PROMPT.index("- PAGE API: the exact surface listing")
        user_instructions_input = SYSTEM_PROMPT.index("- USER INSTRUCTIONS: the project's code style guidance")
        code_input = SYSTEM_PROMPT.index("- CODE: the existing step code that failed")
        assert page_api_input < user_instructions_input < code_input

    def test_system_prompt_carries_the_new_rules(self) -> None:
        assert "the Playwright-mirroring page API" in SYSTEM_PROMPT
        assert (
            "- Locating by role and accessible name is preferred; by visible text next; "
            "by label or placeholder for form fields" in SYSTEM_PROMPT
        )
        assert (
            "- get_by_test_id and locator(selector) exist for elements without accessible names" in SYSTEM_PROMPT
        )
        assert "- Dialogs: when the step verifies or steers a dialog, capture it" in SYSTEM_PROMPT
        assert "with page.expect_dialog() as dialog:" in SYSTEM_PROMPT
        assert "with page.expect_popup() as popup:" in SYSTEM_PROMPT
        assert "bring_to_front() raises a page above the others" in SYSTEM_PROMPT
        assert "Content inside an iframe goes through page.frame_locator(selector)" in SYSTEM_PROMPT
        assert "find_by" not in SYSTEM_PROMPT
        assert "Attribute, CSS and XPath locating" not in SYSTEM_PROMPT

    def test_classification_prompt_moved_out_of_generator(self) -> None:
        assert not hasattr(generator_module, "CLASSIFICATION_PROMPT")  # moved to classification.py

    def test_page_api_surface_lists_every_facade_call(self) -> None:
        for call in (
            "page.goto(url)",
            "page.go_back()",
            "page.go_forward()",
            "page.reload()",
            "page.wait_for_url(url)",
            "page.wait_for_load_state(state)",
            "page.expect_url(url)",
            "page.expect_title(title)",
            "page.get_by_role(role, name)",
            "page.get_by_label(label)",
            "page.get_by_text(text)",
            "page.get_by_placeholder(placeholder)",
            "page.get_by_alt_text(alt)",
            "page.get_by_title(title)",
            "page.get_by_test_id(test_id)",
            "page.locator(selector)",
            "page.expect_dialog()",
            "page.expect_popup()",
            "page.bring_to_front()",
            "page.pages",
            "page.frame_locator(selector)",
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
            "dialog.accept(prompt_text)",
            "dialog.dismiss()",
            "dialog.type",
            "dialog.message",
            "dialog.default_value",
            "frame.get_by_role(role, name)",
            "frame.locator(selector)",
            "frame.frame_locator(selector)",
            "element.click(button)",
            "element.dblclick()",
            "element.fill(value)",
            "element.clear()",
            "element.press(key)",
            "element.check()",
            "element.uncheck()",
            "element.hover()",
            "element.select_option(value)",
            "element.drag_to(target)",
            "element.set_input_files(path)",
            "element.expect_visible()",
            "element.expect_hidden()",
            "element.expect_text(text)",
            "element.expect_enabled()",
            "element.expect_value(value)",
            "element.expect_checked()",
            "element.expect_count(count)",
            "element.expect_attribute(name, value)",
        ):
            assert call in PAGE_API_SURFACE
        assert "page.close" not in PAGE_API_SURFACE

    def test_page_api_surface_members_exist_on_the_facades(self) -> None:
        owners = {"page": PageFacade, "element": LocatorFacade, "dialog": DialogFacade, "frame": FrameFacade}

        for line in PAGE_API_SURFACE.splitlines():
            match = re.match(r"^(page|element|dialog|frame)\.([a-z_]+)", line)
            assert match is not None  # every line is an owned facade call
            assert hasattr(owners[match.group(1)], match.group(2))

        assert "page.close" not in PAGE_API_SURFACE
        assert "open(" not in PAGE_API_SURFACE
        assert "find_by" not in PAGE_API_SURFACE

    def test_page_api_surface_mirrors_facade_practice(self) -> None:
        practice = FACADE_PRACTICE.read_text(encoding="utf-8")
        page_rows = facade_surface_rows(practice, "page")
        dialog_rows = facade_surface_rows(practice, "dialog")
        frame_rows = facade_surface_rows(practice, "frame")
        element_rows = facade_surface_rows(practice, "element")

        for row in (*page_rows, *dialog_rows, *frame_rows, *element_rows):
            if row.startswith("page.close"):
                continue  # the runtime method of PrettyPlay — the standing exclusion
            assert row.split("(", 1)[0] in PAGE_API_SURFACE

        assert len(page_rows) == 33  # 32 listed + close excluded by the standing comment
        assert len(dialog_rows) == 5
        assert len(frame_rows) == 3  # the get_by_* family collapsed to its family row
        assert len(element_rows) == 19
