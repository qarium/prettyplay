"""Tests for the StepGenerator of the prettyplay.engine cell."""

import inspect
import logging
import re
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from prettyplay.cache import RunBudgets, StepCache, StepIdentity
from prettyplay.config import Config
from prettyplay.driver import DialogFacade, FrameFacade, LocatorFacade, PageFacade
from prettyplay.engine import StepGenerator
from prettyplay.engine import generator as generator_module  # to verify the CLASSIFICATION_PROMPT move
from prettyplay.engine.generator import PAGE_API_SURFACE, SYSTEM_PROMPT
from prettyplay.engine.polling import SettleWindow
from prettyplay.failures import IncurableStepError, LLMUnavailableError, ProductDefectError
from prettyplay.llm import FailureClassification
from prettyplay.reporting import StepHooks, StepReporter

WORKING_CODE = "def step(page) -> None:\n    page.goto('https://example.com')\n"
BROKEN_CODE = "def step(page) -> None:\n    page.get_by_role('button', name='Войти').click()\n"

#: a candidate whose check fails — the locator expectation raises AssertionError
CHECK_CODE = "def step(page) -> None:\n    page.get_by_text('Welcome back').expect_visible()\n"

#: a candidate whose execution fails with a non-assertion TypeError
TYPING_BROKEN_CODE = "def step(page) -> None:\n    page.get_by_role('button', name='Pay').click()\n"

FACADE_PRACTICE = Path(__file__).resolve().parents[2] / "prettyplay" / "driver" / ".usages" / "facade.md"
GENERATION_PROMPT_PRACTICE = Path(__file__).resolve().parents[2] / ".goga" / "usages" / "prompts" / "generation.md"


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


class StubProvider:
    """Stub LLM provider boundary: scripted answers and verdicts with recorded requests."""

    def __init__(
        self,
        answers: list[str | Exception],
        verdict: FailureClassification | None = None,
        verdicts: list[FailureClassification | Exception | None] | None = None,
    ) -> None:
        self.answers = list(answers)
        self.verdict = verdict
        self.verdicts = list(verdicts) if verdicts is not None else None
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
        recommendation: str | None = None,
        guidance: str | None = None,
        guidance_history: list[str] | None = None,
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
                "recommendation": recommendation,
                "guidance": guidance,
                "guidance_history": guidance_history,
            }
        )
        if not self.answers:
            raise AssertionError("stub provider has no answers left")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):  # a scripted provider failure plays itself
            raise answer
        return answer

    def classify_failure(self, **kwargs: object) -> FailureClassification | None:
        self.classify_failure_calls.append(dict(kwargs))
        outcome = self.verdicts.pop(0) if self.verdicts is not None else self.verdict
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


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


class TypeErrorPage(FakePage):
    """Fake page where every candidate fails with a non-assertion TypeError."""

    def get_by_role(self, role: str, name: str) -> None:
        self.calls.append(("get_by_role", role, name))
        raise TypeError("bad code")


class FlakyPlaywrightPage(FakePage):
    """Fake page whose navigation fails with a pollable Playwright error N times, then works."""

    def __init__(self, failures: int = 2) -> None:
        super().__init__()
        self._remaining = failures

    def goto(self, url: str) -> None:
        if self._remaining > 0:
            self._remaining -= 1
            raise PlaywrightError("Timeout 10000ms exceeded")
        self.calls.append(("goto", url))


class RecorderHook(StepHooks):
    """Hook recording engine events into a shared ``events`` list for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str | int]]] = []

    def on_generation_started(self, step_text: str, attempt: int) -> None:
        self.events.append(("on_generation_started", {"step_text": step_text, "attempt": attempt}))

    def on_cache_saved(self, step_text: str, filename: str) -> None:
        self.events.append(("on_cache_saved", {"step_text": step_text, "filename": filename}))

    def on_healing_started(self, step_text: str, category: str) -> None:
        self.events.append(("on_healing_started", {"step_text": step_text, "category": category}))


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
            "window",
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
            "recommendation",
            "window",
        ]

    def test_generate_and_regenerate_accept_window_through_direct_calls(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE, WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage()

        generated = fixture.generator.generate(make_identity(), "открыть страницу", [], page, fixture.window)
        regenerated = fixture.generator.regenerate(
            make_identity(),
            "click Sign in",
            [],
            page,
            existing_code=BROKEN_CODE,
            error="TimeoutError",
            recommendation="retry with an id locator",
            window=fixture.window,
        )

        assert generated.code == WORKING_CODE
        assert regenerated.code == WORKING_CODE
        assert provider.calls[1]["recommendation"] == "retry with an id locator"

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
        self.window = SettleWindow(None, 0.5)  # polling off — one execution per candidate
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

        step = fixture.generator.generate(identity, "открыть страницу", [], page, fixture.window)

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

        fixture.generator.generate(make_identity(), "открыть страницу", [], page, fixture.window)

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

        generator.generate(make_identity(), "открыть страницу", [], page, SettleWindow(None, 0.5))

        assert provider.calls[0]["screenshot"] == b"png"

    def test_generator_passes_generation_prompt_to_provider(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        recorder = RecorderHook()
        reporter = StepReporter(hooks=[recorder])
        config = Config(cache_root=str(tmp_path), generation_prompt="prefer data-test-id")
        generator = StepGenerator(config, provider, StepCache(config, None, reporter), RunBudgets(3, 2), reporter)
        page = FakePage()

        generator.generate(make_identity(), "click Sign in", [], page, SettleWindow(None, 0.5))

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
            recommendation="retry with an id locator",
            window=SettleWindow(None, 0.5),
        )

        captured = provider.calls[0]
        # instructions travel with the regeneration-only fields through the one shared call site
        assert captured["user_instructions"] == "prefer data-test-id"
        assert captured["existing_code"] == "def step(page) -> None:\n    page.goto('https://old')\n"
        assert captured["error"] == "TimeoutError"
        assert captured["recommendation"] == "retry with an id locator"
        assert captured["prompt"] == SYSTEM_PROMPT

    def test_empty_generation_prompt_passes_empty_instructions(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage()

        fixture.generator.generate(make_identity(), "click Sign in", [], page, fixture.window)

        # the engine passes the value unconditionally; an empty string means "no block" in the provider helper
        assert provider.calls[0]["user_instructions"] == ""

    def test_generate_retries_with_existing_code_then_succeeds(self, tmp_path: Path) -> None:
        provider = StubProvider([BROKEN_CODE, WORKING_CODE], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider)
        page = TimeoutPage()

        step = fixture.generator.generate(make_identity(), "нажать Войти", [], page, fixture.window)

        assert step.code == WORKING_CODE
        assert len(provider.calls) == 2
        assert provider.calls[1]["existing_code"] == BROKEN_CODE
        assert "navigation timed out" in provider.calls[1]["error"]
        attempts = [
            payload["attempt"] for event, payload in fixture.recorder.events if event == "on_generation_started"
        ]
        assert attempts == [1, 2]

    def test_generate_budget_exhaustion_raises_incurable(self, tmp_path: Path) -> None:
        provider = StubProvider([BROKEN_CODE, BROKEN_CODE, BROKEN_CODE, BROKEN_CODE], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider)
        page = TimeoutPage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "невозможный шаг", [], page, fixture.window)

        assert excinfo.value.reason == "generation attempt budget exhausted"  # repeat failure keeps the entry reason
        assert excinfo.value.error == "TimeoutError: navigation timed out"  # the funded candidate, full and typed
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "rot"  # the entry verdict — no reclassification
        assert excinfo.value.code == BROKEN_CODE  # the funded candidate that repeated the failure
        assert len(provider.calls) == 4  # 3 loop attempts + the funded regeneration
        assert len(provider.classify_failure_calls) == 1  # one classification on exhaustion, none after the repeat
        assert not [event for event in fixture.recorder.events if event[0] == "on_cache_saved"]

    def test_generate_pre_exhausted_budget_keeps_plain_reason(self, tmp_path: Path) -> None:
        provider = StubProvider([])
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 1))
        identity = make_identity()
        page = FakePage()

        assert fixture.budgets.try_generation(identity) is True  # spend the only attempt directly
        assert fixture.budgets.try_generation(identity) is False  # the budget is already spent before the call

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(identity, "невозможный шаг", [], page, fixture.window)

        assert excinfo.value.reason == "generation attempt budget exhausted"
        assert excinfo.value.code == ""  # no candidate ever existed
        assert provider.calls == []  # no requests to the provider

    def test_generate_provider_unavailable_propagates_immediately(self, tmp_path: Path) -> None:
        provider = UnavailableProvider()
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 1))
        identity = make_identity()
        page = FakePage()

        with pytest.raises(LLMUnavailableError):
            fixture.generator.generate(identity, "шаг", [], page, fixture.window)

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
            recommendation="retry with an id locator",
            window=fixture.window,
        )

        assert step.code == WORKING_CODE
        assert provider.calls[0]["existing_code"] == "def step(page) -> None:\n    page.goto('https://old')\n"
        assert provider.calls[0]["error"] == "assertion failed"
        assert provider.calls[0]["recommendation"] == "retry with an id locator"
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
                recommendation="retry with an id locator",
                window=fixture.window,
            )

        assert excinfo.value.reason == "healing attempt budget exhausted"
        assert excinfo.value.error == "TimeoutError: navigation timed out"  # the last candidate of the pool
        assert excinfo.value.code == BROKEN_CODE  # the last candidate of the pool
        assert excinfo.value.verdict is None  # the healer attaches the verdict — no second LLM request
        assert excinfo.value.recommendation == "reword the step or refresh the cache"  # fallback without a verdict
        assert len(provider.calls) == 1  # the healing budget (1) is exhausted after the first attempt
        assert provider.classify_failure_calls == []  # the healing pool does not classify exhaustion

    def test_messageless_candidate_failure_is_retried_not_crashed(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE, WORKING_CODE], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage(assertion_message="")  # message-less assert: str(exc) == ''

        first = fixture.generator.generate(make_identity(), "проверить страницу", [], page, fixture.window)

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
            fixture.generator.generate(make_identity(), "невозможный шаг", [], page, fixture.window)

        # an empty failure description leaves the em-dash reason without an error tail
        assert excinfo.value.reason == "candidate check failed — "

    def test_generated_step_is_saved_into_cache(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        identity = make_identity()
        page = FakePage()

        fixture.generator.generate(identity, "открыть страницу", [], page, fixture.window)

        loaded = fixture.cache.load(identity)
        assert loaded is not None
        assert loaded.code.rstrip("\n") == WORKING_CODE.rstrip("\n")  # the serializer appends a trailing \n
        assert loaded.created_at

    def test_created_at_is_today_iso(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage()

        step = fixture.generator.generate(make_identity(), "открыть страницу", [], page, fixture.window)

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
            fixture.generator.generate(make_identity(), "see the welcome banner", [], page, fixture.window)

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
            fixture.generator.generate(make_identity(), "see the welcome banner", [], page, fixture.window)

        assert excinfo.value.reason.startswith("candidate check failed")
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "incurable"
        assert excinfo.value.code == CHECK_CODE  # the generation path carries the failed candidate
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
            fixture.generator.generate(make_identity(), "невозможный шаг", [], page, fixture.window)

        assert excinfo.value.reason.startswith("generation attempt budget exhausted")
        assert excinfo.value.error == "TimeoutError: navigation timed out"
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "incurable"
        assert excinfo.value.code == BROKEN_CODE  # the last candidate
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
            fixture.generator.generate(make_identity(), "see the welcome banner", [], page, fixture.window)

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
            fixture.generator.generate(make_identity(), "impossible step", [], page, fixture.window)

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

        step = fixture.generator.generate(make_identity(), "press the sign in button", [], page, fixture.window)

        assert step.code == WORKING_CODE
        assert len(provider.calls) == 2  # a locator timeout spends an attempt and retries, no check-stop
        assert provider.calls[1]["existing_code"] == BROKEN_CODE
        assert provider.classify_failure_calls == []

    def test_generate_failed_check_rot_grants_one_funded_regeneration(self, tmp_path: Path) -> None:
        provider = StubProvider(
            [CHECK_CODE, WORKING_CODE],
            verdict=FailureClassification(
                category="rot",
                explanation="the button was renamed",
                recommendation="retry with an id locator",
            ),
        )
        fixture = GeneratorFixture(tmp_path, provider)  # RunBudgets(3, 2)
        page = FakePage(assertion_message="button is hidden")

        step = fixture.generator.generate(make_identity(), "click Pay", [], page, fixture.window)

        assert step.code == WORKING_CODE
        assert len(provider.calls) == 2  # the failed candidate + the one funded regeneration
        second = provider.calls[1]
        assert second["recommendation"] == "retry with an id locator"
        assert second["existing_code"] == CHECK_CODE  # the failed candidate
        assert second["error"] == "button is hidden"
        assert second["guidance"] is None  # engine requests never carry steering guidance
        assert second["guidance_history"] == []
        attempts = [event for event in fixture.recorder.events if event[0] == "on_generation_started"]
        assert attempts == [
            ("on_generation_started", {"step_text": "click Pay", "attempt": 1}),
            ("on_generation_started", {"step_text": "click Pay", "attempt": 2}),  # the funded request is an attempt
        ]
        saved = [event for event in fixture.recorder.events if event[0] == "on_cache_saved"]
        assert len(saved) == 1  # only the healed code is stored
        assert not [event for event in fixture.recorder.events if event[0] == "on_healing_started"]

    def test_generate_failed_check_fixable_verdict_grants_one_funded_regeneration(self, tmp_path: Path) -> None:
        """The fixable label rides the same funded regeneration as rot — the code was at fault."""
        provider = StubProvider(
            [CHECK_CODE, WORKING_CODE],
            verdict=FailureClassification(
                category="fixable",
                explanation="the locator is ambiguous — it resolves 61 elements",
                recommendation="use a precise role-and-name locator",
            ),
        )
        fixture = GeneratorFixture(tmp_path, provider)  # RunBudgets(3, 2)
        page = FakePage(assertion_message="button is hidden")

        step = fixture.generator.generate(make_identity(), "click Pay", [], page, fixture.window)

        assert step.code == WORKING_CODE
        assert len(provider.calls) == 2  # the failed candidate + the one funded regeneration
        second = provider.calls[1]
        assert second["recommendation"] == "use a precise role-and-name locator"
        assert second["existing_code"] == CHECK_CODE
        assert second["error"] == "button is hidden"

    def test_exhaustion_rot_verdict_grants_extra_regeneration_and_repeat_failure_is_terminal(
        self, tmp_path: Path
    ) -> None:
        provider = StubProvider(
            [TYPING_BROKEN_CODE, TYPING_BROKEN_CODE],
            verdict=FailureClassification(category="rot", explanation="e", recommendation="retry with an id locator"),
        )
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 2))  # generation budget 1
        page = TypeErrorPage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "click Pay", [], page, fixture.window)

        assert excinfo.value.reason == "generation attempt budget exhausted"  # the exhausted generation pool
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "rot"  # the entry verdict — no reclassification
        assert excinfo.value.code == TYPING_BROKEN_CODE  # the funded candidate that failed again
        assert excinfo.value.error == "TypeError: bad code"
        assert len(provider.calls) == 2  # 1 loop attempt + 1 funded; no third — no reclassification
        assert len(provider.classify_failure_calls) == 1

    def test_exhaustion_fixable_verdict_grants_extra_regeneration_and_repeat_failure_is_terminal(
        self, tmp_path: Path
    ) -> None:
        """The fixable label rides the exhaustion grant too — and the repeat stays terminal."""
        provider = StubProvider(
            [TYPING_BROKEN_CODE, TYPING_BROKEN_CODE],
            verdict=FailureClassification(
                category="fixable",
                explanation="the locator is ambiguous",
                recommendation="use a precise role-and-name locator",
            ),
        )
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 2))  # generation budget 1
        page = TypeErrorPage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "click Pay", [], page, fixture.window)

        assert excinfo.value.reason == "generation attempt budget exhausted"
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "fixable"  # the entry verdict — no reclassification
        assert excinfo.value.code == TYPING_BROKEN_CODE
        assert provider.calls[1]["recommendation"] == "use a precise role-and-name locator"
        assert len(provider.calls) == 2
        assert len(provider.classify_failure_calls) == 1

    def test_generate_failed_check_repeat_final_classification_unavailable_stays_incurable(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unavailable final classification of the repeat leaves a verdict-less terminal failure."""
        provider = StubProvider(
            [CHECK_CODE, CHECK_CODE],
            verdicts=[
                FailureClassification(category="rot", explanation="the button was renamed", recommendation="id"),
                LLMUnavailableError("llm unavailable: openai request failed"),
            ],
        )
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage(assertion_message="button is hidden")

        with caplog.at_level(logging.WARNING, logger="prettyplay"), pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "click Pay", [], page, fixture.window)

        assert excinfo.value.reason == "candidate check failed — button is hidden"
        assert excinfo.value.verdict is None  # the quiet skip — never an infrastructure failure
        assert excinfo.value.code == CHECK_CODE
        assert excinfo.value.error == "button is hidden"
        assert len(provider.calls) == 2  # the failed candidate + the one funded regeneration
        assert len(provider.classify_failure_calls) == 2  # entry + the final one that died quietly
        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert any("verdict skipped" in record.message for record in warnings)

    def test_generate_failed_check_refused_funding_is_terminal(self, tmp_path: Path) -> None:
        provider = StubProvider(
            [CHECK_CODE],
            verdict=FailureClassification(category="rot", explanation="e", recommendation="r"),
        )
        fixture = GeneratorFixture(tmp_path, provider, limits=(3, 0))  # healing pool empty
        page = FakePage(assertion_message="button is hidden")

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "click Pay", [], page, fixture.window)

        assert excinfo.value.reason == "healing attempt budget exhausted"
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "rot"
        assert excinfo.value.code == CHECK_CODE
        assert len(provider.calls) == 1  # no unfunded request
        assert len(provider.classify_failure_calls) == 1

    def test_generate_failed_check_repeat_check_failure_gets_final_classification(self, tmp_path: Path) -> None:
        """A repeat failed check gets the one final classification — the rot verdict stays terminal."""
        provider = StubProvider(
            [CHECK_CODE, CHECK_CODE],
            verdicts=[
                FailureClassification(category="rot", explanation="the button was renamed", recommendation="id"),
                FailureClassification(category="rot", explanation="still renamed", recommendation="reword"),
            ],
        )
        fixture = GeneratorFixture(tmp_path, provider)  # RunBudgets(3, 2)
        page = FakePage(assertion_message="button is hidden")

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "click Pay", [], page, fixture.window)

        assert excinfo.value.reason == "candidate check failed — button is hidden"  # the repeat names the check
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.explanation == "still renamed"  # the final verdict, not the entry one
        assert excinfo.value.code == CHECK_CODE  # the funded candidate that repeated the failure
        assert excinfo.value.error == "button is hidden"
        assert len(provider.calls) == 2  # the failed candidate + the one funded regeneration
        assert len(provider.classify_failure_calls) == 2  # entry + final; no third request after the repeat
        assert not [event for event in fixture.recorder.events if event[0] == "on_cache_saved"]

    def test_generate_failed_check_repeat_product_defect_verdict_raises_product_defect(
        self, tmp_path: Path
    ) -> None:
        """The final classification of a repeat failure may still say product defect — it raises loudly."""
        provider = StubProvider(
            [CHECK_CODE, CHECK_CODE],
            verdicts=[
                FailureClassification(category="rot", explanation="the button was renamed", recommendation="id"),
                FailureClassification(category="product_defect", explanation="gone", recommendation="file a bug"),
            ],
        )
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage(assertion_message="button is hidden")

        with pytest.raises(ProductDefectError) as excinfo:
            fixture.generator.generate(make_identity(), "click Pay", [], page, fixture.window)

        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "product_defect"  # the final verdict decides the kind
        assert excinfo.value.message == "gone"
        assert excinfo.value.error == "button is hidden"
        assert len(provider.calls) == 2
        assert len(provider.classify_failure_calls) == 2

    def test_generate_failed_check_repeat_non_check_failure_names_candidate_failure(
        self, tmp_path: Path
    ) -> None:
        """A non-assertion repeat of a funded regeneration names the candidate, not the check."""
        provider = StubProvider(
            [CHECK_CODE, TYPING_BROKEN_CODE],
            verdicts=[
                FailureClassification(category="rot", explanation="the button was renamed", recommendation="id"),
                FailureClassification(category="rot", explanation="still renamed", recommendation="reword"),
            ],
        )
        fixture = GeneratorFixture(tmp_path, provider)
        # one page serving both: the entry check fails on the locator expectation, the repeat on get_by_role
        page = TypeErrorPage(assertion_message="button is hidden")

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "click Pay", [], page, fixture.window)

        assert excinfo.value.reason == "candidate failed — TypeError: bad code"  # not "candidate check failed"
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.explanation == "still renamed"
        assert excinfo.value.code == TYPING_BROKEN_CODE
        assert excinfo.value.error == "TypeError: bad code"

    def test_generate_failed_check_provider_failure_in_funded_regeneration_propagates(
        self, tmp_path: Path
    ) -> None:
        """A provider failure of the funded regeneration propagates immediately — no retry, no final classification."""
        outage = LLMUnavailableError("llm unavailable: openai request failed")
        provider = StubProvider(
            [CHECK_CODE, outage],
            verdict=FailureClassification(category="rot", explanation="e", recommendation="r"),
        )
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage(assertion_message="button is hidden")

        with pytest.raises(LLMUnavailableError) as excinfo:
            fixture.generator.generate(make_identity(), "click Pay", [], page, fixture.window)

        assert excinfo.value is outage  # the identical object — never swallowed into a terminal kind
        assert len(provider.calls) == 2  # the failed candidate + the funded request that died
        assert len(provider.classify_failure_calls) == 1  # the entry classification only — no final one

    def test_generate_exhaustion_product_defect_verdict_raises_product_defect(self, tmp_path: Path) -> None:
        provider = StubProvider(
            [BROKEN_CODE],
            verdict=FailureClassification(
                category="product_defect", explanation="the banner is gone", recommendation="file a bug"
            ),
        )
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 2))
        page = TimeoutPage()

        with pytest.raises(ProductDefectError) as excinfo:
            fixture.generator.generate(make_identity(), "see the welcome banner", [], page, fixture.window)

        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "product_defect"
        assert excinfo.value.error == "TimeoutError: navigation timed out"
        assert len(provider.calls) == 1
        assert len(provider.classify_failure_calls) == 1

    def test_generate_exhaustion_refused_healing_funding_is_terminal(self, tmp_path: Path) -> None:
        provider = StubProvider(
            [BROKEN_CODE],
            verdict=FailureClassification(category="rot", explanation="e", recommendation="r"),
        )
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 0))  # the healing pool is empty
        page = TimeoutPage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "click Pay", [], page, fixture.window)

        assert excinfo.value.reason == "healing attempt budget exhausted"  # the exhaustion entry, refused funding
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "rot"
        assert excinfo.value.code == BROKEN_CODE
        assert len(provider.calls) == 1  # no unfunded request
        assert len(provider.classify_failure_calls) == 1

    def test_generate_exhaustion_funded_regeneration_saves_the_step(self, tmp_path: Path) -> None:
        provider = StubProvider(
            [BROKEN_CODE, WORKING_CODE],
            verdict=FailureClassification(category="rot", explanation="e", recommendation="use the id"),
        )
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 2))  # generation budget 1, healing 2
        identity = make_identity()
        page = TimeoutPage()

        step = fixture.generator.generate(identity, "click Pay", [], page, fixture.window)

        assert step.code == WORKING_CODE  # the exhausted pool was saved by the funded regeneration
        assert step.identity == identity
        assert len(provider.calls) == 2
        assert provider.calls[1]["recommendation"] == "use the id"
        attempts = [
            payload["attempt"] for event, payload in fixture.recorder.events if event == "on_generation_started"
        ]
        assert attempts == [1, 2]  # the funded request continues the pool-run count
        saved = [event for event in fixture.recorder.events if event[0] == "on_cache_saved"]
        assert len(saved) == 1  # only the healed code of the funded regeneration is stored
        assert saved[0][1]["filename"] == identity.filename

    def test_on_generation_started_fires_once_despite_settle_retries(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 2))
        identity = make_identity()
        page = FlakyPlaywrightPage(failures=2)

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            step = fixture.generator.generate(identity, "open the page", [], page, SettleWindow(10.0, 0))

        assert step.code == WORKING_CODE
        started = [event for event in fixture.recorder.events if event[0] == "on_generation_started"]
        assert started == [("on_generation_started", {"step_text": "open the page", "attempt": 1})]
        retries = [record for record in caplog.records if record.message == "settle_retry"]
        assert len(retries) == 2  # both re-executions happened inside the one attempt
        assert [record.attempt for record in retries] == [1, 2]
        assert fixture.budgets.try_generation(identity) is False  # exactly one generation attempt spent
        assert fixture.budgets.try_healing(identity) is True  # the healing pool untouched

    def test_generate_first_refusal_without_candidate(self, tmp_path: Path) -> None:
        provider = StubProvider([], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 2))
        identity = make_identity()
        page = FakePage()

        assert fixture.budgets.try_generation(identity) is True  # spend an attempt before generation
        assert fixture.budgets.try_generation(identity) is False

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(identity, "невозможный шаг", [], page, fixture.window)

        assert excinfo.value.reason == "generation attempt budget exhausted"
        assert excinfo.value.verdict is None  # nothing to classify
        assert excinfo.value.code == ""  # no candidate ever existed
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
            defect_fixture.generator.generate(
                make_identity(), "see the welcome banner", [], defect_page, defect_fixture.window
            )

        assert defect.value.error == long_message  # full, no prefix, no truncation at 200 chars
        assert len(defect.value.error) > 200

        exhausted_provider = StubProvider(
            [BROKEN_CODE],
            verdict=FailureClassification(category="incurable", explanation="e", recommendation="r"),
        )
        exhausted_fixture = GeneratorFixture(tmp_path, exhausted_provider, limits=(1, 2))
        timeout_page = TimeoutPage()

        with pytest.raises(IncurableStepError) as exhausted:
            exhausted_fixture.generator.generate(
                make_identity(), "невозможный шаг", [], timeout_page, exhausted_fixture.window
            )

        assert exhausted.value.error == "TimeoutError: navigation timed out"  # the last candidate full text
        assert exhausted.value.reason == "generation attempt budget exhausted"  # no colon, no embedded error


class TestPromptConstants:
    """Constant tests: prompts and the frozen page API surface."""

    def test_generation_prompt_is_frozen_text(self) -> None:
        assert SYSTEM_PROMPT.startswith("You generate executable Python code")
        assert "def step(page) -> None:" in SYSTEM_PROMPT

    def test_generation_prompt_rule_order_survives_the_edit(self) -> None:
        # the assertion-mechanics rule sits exactly after the assertion-sentence rule, before the dialogs rule
        assertion = SYSTEM_PROMPT.index("- Assertions happen only through")
        dialogs = SYSTEM_PROMPT.index("- Dialogs: when the step verifies")
        scroll = SYSTEM_PROMPT.index("- Scroll abilities exist")
        no_delays = SYSTEM_PROMPT.index("- No fixed delays")
        assert assertion < dialogs < scroll < no_delays

    def test_system_prompt_documents_user_instructions_input(self) -> None:
        # the USER INSTRUCTIONS input line sits right after the PAGE API input line
        page_api_input = SYSTEM_PROMPT.index("- PAGE API: the exact surface listing")
        user_instructions_input = SYSTEM_PROMPT.index("- USER INSTRUCTIONS: the project's code style guidance")
        code_input = SYSTEM_PROMPT.index("- CODE: the existing step code that failed")
        assert page_api_input < user_instructions_input < code_input

    def test_system_prompt_strategy_rules_are_gone(self) -> None:
        assert (
            "- Assertions happen only through the expectation calls of the facade — never a Python assert on a "
            "locator, never SDK-style state reads" in SYSTEM_PROMPT
        )
        assert "Locating by role and accessible name is preferred" not in SYSTEM_PROMPT
        assert "accessibility-first priority" not in SYSTEM_PROMPT
        # the surviving mechanics rules stay intact through the strategy split
        assert "the Playwright-mirroring page API" in SYSTEM_PROMPT
        assert "- Dialogs: when the step verifies or steers a dialog, capture it" in SYSTEM_PROMPT
        assert "with page.expect_dialog() as dialog:" in SYSTEM_PROMPT
        assert "with page.expect_popup() as popup:" in SYSTEM_PROMPT
        assert "bring_to_front() raises a page above the others" in SYSTEM_PROMPT
        assert "Content inside an iframe goes through page.frame_locator(selector)" in SYSTEM_PROMPT
        assert (
            "- Scroll abilities exist for scenario scrolling: bring an element into view, scroll by an "
            "amount, to the page end or start, inside a scrollable container" in SYSTEM_PROMPT
        )
        assert "- No fixed delays, no sleeps, no explicit waits — the facade waits itself" in SYSTEM_PROMPT
        assert "def step(page) -> None:" in SYSTEM_PROMPT  # the fixed form
        assert "- Output only the code block, no explanations" in SYSTEM_PROMPT
        assert "find_by" not in SYSTEM_PROMPT
        assert "Attribute, CSS and XPath locating" not in SYSTEM_PROMPT

    def test_system_prompt_mirrors_the_generation_practice(self) -> None:
        practice = GENERATION_PROMPT_PRACTICE.read_text(encoding="utf-8")
        prompt = practice.split("---", 1)[1].strip()  # the section after the separator is the prompt itself

        assert prompt == SYSTEM_PROMPT  # the frozen mirror — the constant changes only together with the file

    def test_system_prompt_carries_the_new_input_lines_and_rule(self) -> None:
        error_input = SYSTEM_PROMPT.index("- ERROR: the failure description")
        recommendation_input = SYSTEM_PROMPT.index("- RECOMMENDATION: the diagnosis of the classification")
        guidance_input = SYSTEM_PROMPT.index("- USER GUIDANCE: the engineer guidance message")
        history_input = SYSTEM_PROMPT.index("- HISTORY: the accumulated steering turns")
        assert error_input < recommendation_input < guidance_input < history_input
        assert (
            "RECOMMENDATION and USER GUIDANCE carry the diagnosis and the engineer's intent — "
            "follow them when they conflict with your first instinct" in SYSTEM_PROMPT
        )

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
            "element.first",
            "element.last",
            "element.nth(index)",
            "element.filter(has_text=..., has_not_text=..., has=..., has_not=...)",
            "element.or_(other)",
            "element.and_(other)",
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
        assert len(element_rows) == 25  # 19 + the six narrowing rows at the head

    def test_page_api_surface_covers_the_narrowing_family(self) -> None:
        # the listing is the model's only view of the surface — a missing row reproduces the incident
        for call in (
            "element.first",
            "element.last",
            "element.nth(index)",
            "element.filter(has_text=..., has_not_text=..., has=..., has_not=...)",
            "element.or_(other)",
            "element.and_(other)",
        ):
            assert call in PAGE_API_SURFACE

        element_rows = facade_surface_rows(FACADE_PRACTICE.read_text(encoding="utf-8"), "element")
        assert len(element_rows) == 25  # every narrowing row of the practice is listed
        assert "page.close" not in PAGE_API_SURFACE  # the standing exclusion holds through the edit
