"""Tests for the StepGenerator of the prettyplay.engine cell."""

import inspect
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from prettyplay.cache import RunBudgets, StepCache, StepIdentity
from prettyplay.config import Config
from prettyplay.engine import StepAttempt, StepGenerator
from prettyplay.engine import generator as generator_module  # to verify the CLASSIFICATION_PROMPT move
from prettyplay.engine.attempts import (
    OUTCOME_COMPLIANCE_BLOCKED,
    OUTCOME_EXECUTION_FAILED,
    OUTCOME_FAILED_CHECK,
    OUTCOME_ORIGINAL,
)
from prettyplay.engine.generator import CHEAT_SHEET, SYSTEM_PROMPT
from prettyplay.engine.polling import SettleWindow
from prettyplay.failures import ComplianceVerdictError, IncurableStepError, LLMUnavailableError, ProductDefectError
from prettyplay.llm import ComplianceFinding, FailureClassification
from prettyplay.reporting import StepHooks, StepReporter

WORKING_CODE = "def step(page) -> None:\n    page.goto('https://example.com')\n"
BROKEN_CODE = "def step(page) -> None:\n    page.get_by_role('button', name='Войти').click()\n"

#: a candidate whose execution fails with a RuntimeError raised by the step itself
BAD_CODE = "def step(page) -> None:\n    raise RuntimeError('boom')\n"

#: a candidate whose check fails — the locator expectation raises AssertionError
CHECK_CODE = "def step(page) -> None:\n    page.get_by_text('Welcome back').expect_visible()\n"

#: the incident idiom — a multi-match locator narrowed positionally, green on a green page
NARROWING_CODE = "def step(page) -> None:\n    page.get_by_text('Welcome back').first.expect_visible()\n"

#: a candidate whose execution fails with a non-assertion TypeError
TYPING_BROKEN_CODE = "def step(page) -> None:\n    page.get_by_role('button', name='Pay').click()\n"

#: a candidate whose execution fails with a NameError inside the step
NAMEERROR_CODE = "def step(page) -> None:\n    missing_symbol()\n"

GENERATION_PROMPT_PRACTICE = Path(__file__).resolve().parents[2] / ".goga" / "usages" / "prompts" / "generation.md"
CHEAT_SHEET_PRACTICE = Path(__file__).resolve().parents[2] / ".goga" / "usages" / "prompts" / "cheatsheet.md"


class FakeLocator:
    """Fake element boundary: narrowing members record, expectations fail with the scripted message."""

    def __init__(self, assertion_message: str | None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self._assertion_message = assertion_message

    @property
    def first(self) -> "FakeLocator":
        self.calls.append(("first",))
        return self

    @property
    def last(self) -> "FakeLocator":
        self.calls.append(("last",))
        return self

    def nth(self, index: int) -> "FakeLocator":
        self.calls.append(("nth", index))
        return self

    def filter(self, **kwargs: Any) -> "FakeLocator":
        self.calls.append(("filter", kwargs))
        return self

    def or_(self, other: "FakeLocator") -> "FakeLocator":
        self.calls.append(("or_", other))
        return self

    def and_(self, other: "FakeLocator") -> "FakeLocator":
        self.calls.append(("and_", other))
        return self

    def expect_visible(self) -> None:
        if self._assertion_message is not None:
            raise AssertionError(self._assertion_message)


class FakePage:
    """Fake page facade boundary: snapshot plus recorded facade calls and a scripted URL."""

    def __init__(
        self,
        assertion_message: str | None = None,
        url: str | Exception | Callable[[], str] = "https://example.com",
    ) -> None:
        """Keep the assertion script and the URL script of the attempt brackets.

        Args:
            assertion_message: the message every locator expectation raises; ``None`` stays green.
            url: the scripted page URL — a fixed value, a zero-arg callable returning
                successive values, or an exception instance raised on every read (a dead page).
        """
        self.calls: list[tuple[str, ...]] = []
        self._assertion_message = assertion_message
        self._url = url

    @property
    def url(self) -> str:
        """The scripted page URL: a value, a callable's answer, or the scripted failure."""
        if isinstance(self._url, Exception):
            raise self._url
        if callable(self._url):
            return self._url()
        return self._url

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))

    def run(self, action: Callable[[object], object]) -> object:
        """Minimal page-handle shim: the run primitive executes the action against the fake itself."""
        return action(self)

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
        compliance_verdicts: list[list[ComplianceFinding] | Exception] | None = None,
    ) -> None:
        self.answers = list(answers)
        self.verdict = verdict
        self.verdicts = list(verdicts) if verdicts is not None else None
        self.compliance_verdicts = list(compliance_verdicts) if compliance_verdicts is not None else None
        self.calls: list[dict[str, object]] = []
        self.classify_failure_calls: list[dict[str, object]] = []
        self.compliance_calls: list[dict[str, object]] = []

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str = "",
        step_text: str = "",
        step_type: str = "",
        previous_steps: list[str] | None = None,
        snapshot: str = "",
        page_url: str | None = None,
        screenshot: bytes | None = None,
        cheat_sheet: str = "",
        attempt_history: list[str] | None = None,
        recommendation: str | None = None,
        guidance: str | None = None,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "user_instructions": user_instructions,
                "step_text": step_text,
                "step_type": step_type,
                "previous_steps": previous_steps,
                "snapshot": snapshot,
                "page_url": page_url,
                "screenshot": screenshot,
                "cheat_sheet": cheat_sheet,
                "attempt_history": attempt_history,
                "recommendation": recommendation,
                "guidance": guidance,
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

    def check_instruction_compliance(self, **kwargs: object) -> list[ComplianceFinding]:
        self.compliance_calls.append(dict(kwargs))
        outcome = self.compliance_verdicts.pop(0) if self.compliance_verdicts else []
        if isinstance(outcome, Exception):  # a scripted gate failure plays itself
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
            "step_type",
            "previous_steps",
            "page",
            "attempt_history",
            "window",
        ]

    def test_regenerate_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(StepGenerator.regenerate).parameters.values())[1:]

        # existing_code and error are gone — the anchored history takes their place
        assert [parameter.name for parameter in parameters] == [
            "identity",
            "step_text",
            "step_type",
            "previous_steps",
            "page",
            "attempt_history",
            "recommendation",
            "window",
        ]

    def test_generate_and_regenerate_accept_the_new_inputs_keyword_callable(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE, WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage()

        generated = fixture.generator.generate(
            identity=make_identity(),
            step_text="открыть страницу",
            step_type="action",
            previous_steps=[],
            page=page,
            attempt_history=[],
            window=fixture.window,
        )
        regenerated = fixture.generator.regenerate(
            identity=make_identity(),
            step_text="click Sign in",
            step_type="action",
            previous_steps=[],
            page=page,
            attempt_history=[],
            recommendation="retry with an id locator",
            window=fixture.window,
        )

        assert generated.code == WORKING_CODE
        assert regenerated.code == WORKING_CODE
        assert provider.calls[0]["step_type"] == "action"
        assert provider.calls[0]["attempt_history"] == []
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
        generation_prompt: str = "",
    ) -> None:
        self.recorder = RecorderHook()
        self.reporter = StepReporter(hooks=[self.recorder])
        # a non-empty generation_prompt switches the instruction compliance gate on
        self.config = Config(cache_root=str(tmp_path), generation_prompt=generation_prompt)
        self.cache = StepCache(self.config, None, self.reporter)
        self.budgets = RunBudgets(*limits)
        self.window = SettleWindow(None, 0.5)  # polling off — one execution per candidate
        self.generator = StepGenerator(self.config, provider, self.cache, self.budgets, self.reporter)


ROT_VERDICT = FailureClassification(
    category="rot",
    explanation="the button was renamed",
    recommendation="refresh the cache",
)

#: the standing high instruction finding of the gate tests — the violated instruction and its explanation
HIGH_FINDING = ComplianceFinding(
    instruction="Prefer id attributes", priority="high", explanation="locates by text", dimension="instruction"
)

#: the fixed violation wording of HIGH_FINDING — the attempt record's error field
VIOLATION_TEXT = "instruction violation: Prefer id attributes — locates by text"


def make_identity() -> StepIdentity:
    """Build a step identity for the tests."""
    return StepIdentity(cache_key="login-flow", step_type="action", normalized_text="открыть страницу")


def make_anchored_history() -> list[StepAttempt]:
    """Build an anchored healing history — record 0 carrying the original cached code."""
    return [
        StepAttempt(
            code="def step(page) -> None:\n    page.goto('https://old')\n",
            error="TimeoutError",
            outcome=OUTCOME_ORIGINAL,
        )
    ]


def url_cycle(*urls: str) -> Callable[[], str]:
    """Script a FakePage URL returning the given values in order, one per read."""
    values = iter(urls)
    return lambda: next(values)


class TestStepGeneratorLogic:
    """Logic tests: attempt loop, regeneration context, budgets, propagation."""

    def test_generate_success_stores_and_reports_attempt(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        identity = make_identity()
        page = FakePage()

        step = fixture.generator.generate(identity, "открыть страницу", "action", [], page, [], fixture.window)

        assert step.code == WORKING_CODE
        assert step.identity == identity
        assert len(provider.calls) == 1
        assert provider.calls[0]["step_type"] == "action"
        assert provider.calls[0]["attempt_history"] == []  # the first request of a fresh step
        assert fixture.recorder.events[0] == (
            "on_generation_started",
            {"step_text": "открыть страницу", "attempt": 1},
        )
        assert isinstance(fixture.recorder.events[0][1]["attempt"], int)
        saved = [event for event in fixture.recorder.events if event[0] == "on_cache_saved"]
        assert saved == [("on_cache_saved", {"step_text": "открыть страницу", "filename": identity.filename})]

    def test_generate_request_carries_the_cheat_sheet(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage()

        fixture.generator.generate(make_identity(), "open the videos page", "action", [], page, [], fixture.window)

        request = provider.calls[0]
        assert request["prompt"] == SYSTEM_PROMPT
        assert request["cheat_sheet"] == CHEAT_SHEET
        assert ("page" + "_api") not in request  # the dead slot name, assembled — no literal for the sweep
        assert request["snapshot"] == "- snapshot"
        assert request["screenshot"] is None  # send_screenshots defaults to False

    def test_engine_requests_pass_page_url_none(self, tmp_path: Path) -> None:
        """Every engine request carries no URL — the input is steering-only, uniform with guidance."""
        provider = StubProvider([WORKING_CODE, WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage()

        fixture.generator.generate(make_identity(), "open the page", "action", [], page, [], fixture.window)
        fixture.generator.regenerate(
            make_identity(), "click Sign in", "action", [], page, [], "retry with an id locator", fixture.window
        )

        assert provider.calls[0]["page_url"] is None  # the generation request — steering-only input
        assert provider.calls[0]["guidance"] is None
        assert provider.calls[1]["page_url"] is None  # the regeneration request — the same shared _request
        assert provider.calls[1]["guidance"] is None

    def test_generate_attaches_screenshot_when_enabled(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        recorder = RecorderHook()
        reporter = StepReporter(hooks=[recorder])
        config = Config(cache_root=str(tmp_path), send_screenshots=True)
        generator = StepGenerator(config, provider, StepCache(config, None, reporter), RunBudgets(3, 2), reporter)
        page = FakePage()

        generator.generate(make_identity(), "открыть страницу", "action", [], page, [], SettleWindow(None, 0.5))

        assert provider.calls[0]["screenshot"] == b"png"

    def test_generator_passes_generation_prompt_to_provider(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        recorder = RecorderHook()
        reporter = StepReporter(hooks=[recorder])
        config = Config(cache_root=str(tmp_path), generation_prompt="prefer data-test-id")
        generator = StepGenerator(config, provider, StepCache(config, None, reporter), RunBudgets(3, 2), reporter)
        page = FakePage()

        generator.generate(make_identity(), "click Sign in", "action", [], page, [], SettleWindow(None, 0.5))

        captured = provider.calls[0]
        assert captured["user_instructions"] == "prefer data-test-id"
        assert captured["prompt"] == SYSTEM_PROMPT
        assert 'page.get_by_test_id("submit")' in captured["cheat_sheet"]

    def test_regenerate_carries_user_instructions_with_recommendation_and_anchored_history(
        self, tmp_path: Path
    ) -> None:
        provider = StubProvider([WORKING_CODE])
        recorder = RecorderHook()
        reporter = StepReporter(hooks=[recorder])
        config = Config(cache_root=str(tmp_path), generation_prompt="prefer data-test-id")
        generator = StepGenerator(config, provider, StepCache(config, None, reporter), RunBudgets(1, 1), reporter)
        page = FakePage()
        history = make_anchored_history()

        generator.regenerate(
            make_identity(), "click Sign in", "action", [], page, history, "retry with an id locator",
            SettleWindow(None, 0.5),
        )

        captured = provider.calls[0]
        # instructions travel with the regeneration-only fields through the one shared call site
        assert captured["user_instructions"] == "prefer data-test-id"
        assert captured["attempt_history"] == [record.render() for record in history]  # the anchored record rides it
        assert captured["recommendation"] == "retry with an id locator"
        assert captured["prompt"] == SYSTEM_PROMPT

    def test_empty_generation_prompt_passes_empty_instructions(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage()

        fixture.generator.generate(make_identity(), "click Sign in", "action", [], page, [], fixture.window)

        # the engine passes the value unconditionally; an empty string means "no block" in the provider helper
        assert provider.calls[0]["user_instructions"] == ""

    def test_generate_retries_with_grown_history_then_succeeds(self, tmp_path: Path) -> None:
        provider = StubProvider([BROKEN_CODE, WORKING_CODE], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider)
        page = TimeoutPage()
        history: list[StepAttempt] = []

        step = fixture.generator.generate(make_identity(), "нажать Войти", "action", [], page, history, fixture.window)

        assert step.code == WORKING_CODE
        assert len(provider.calls) == 2
        assert provider.calls[1]["attempt_history"] == [history[0].render()]  # the failed attempt rides the retry
        assert history[0].outcome == OUTCOME_EXECUTION_FAILED
        assert history[0].code == BROKEN_CODE
        assert "navigation timed out" in history[0].error
        attempts = [
            payload["attempt"] for event, payload in fixture.recorder.events if event == "on_generation_started"
        ]
        assert attempts == [1, 2]

    def test_step_code_error_fails_the_generation_attempt(self, tmp_path: Path) -> None:
        """A NameError inside the step code fails the attempt and drives the retry's HISTORY record."""
        provider = StubProvider([NAMEERROR_CODE, WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        identity = make_identity()
        page = FakePage()
        history: list[StepAttempt] = []

        step = fixture.generator.generate(identity, "open the page", "action", [], page, history, fixture.window)

        assert step.code == WORKING_CODE
        assert len(provider.calls) == 2  # the failing candidate + the retry it funded
        retry = provider.calls[1]
        assert retry["attempt_history"] == [history[0].render()]
        assert history[0].outcome == OUTCOME_EXECUTION_FAILED
        assert history[0].code == NAMEERROR_CODE
        assert "NameError" in history[0].error
        assert "missing_symbol" in history[0].error
        attempts = [
            payload["attempt"] for event, payload in fixture.recorder.events if event == "on_generation_started"
        ]
        assert attempts == [1, 2]  # the budget accounting unchanged — one attempt per LLM request
        assert fixture.budgets.try_generation(identity) is True  # 3 attempts allowed, 2 spent

    def test_generate_budget_exhaustion_raises_incurable(self, tmp_path: Path) -> None:
        provider = StubProvider([BROKEN_CODE, BROKEN_CODE, BROKEN_CODE, BROKEN_CODE], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider)
        page = TimeoutPage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "невозможный шаг", "action", [], page, [], fixture.window)

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
            fixture.generator.generate(identity, "невозможный шаг", "action", [], page, [], fixture.window)

        assert excinfo.value.reason == "generation attempt budget exhausted"
        assert excinfo.value.code == ""  # no candidate ever existed
        assert provider.calls == []  # no requests to the provider

    def test_generate_provider_unavailable_propagates_immediately(self, tmp_path: Path) -> None:
        provider = UnavailableProvider()
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 1))
        identity = make_identity()
        page = FakePage()

        with pytest.raises(LLMUnavailableError):
            fixture.generator.generate(identity, "шаг", "action", [], page, [], fixture.window)

        assert provider.calls == 1  # no retries on an infrastructure failure
        assert fixture.budgets.try_generation(identity) is False  # exactly 1 attempt spent

    def test_regenerate_spends_healing_budget_not_generation(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 1))
        identity = make_identity()
        page = FakePage()
        history = make_anchored_history()

        step = fixture.generator.regenerate(
            identity, "открыть страницу", "action", [], page, history, "retry with an id locator", fixture.window
        )

        assert step.code == WORKING_CODE
        assert provider.calls[0]["attempt_history"] == [history[0].render()]  # record 0 anchors the request
        assert provider.calls[0]["recommendation"] == "retry with an id locator"
        # the healing budget is spent, the generation budget untouched
        assert fixture.budgets.try_healing(identity) is False
        assert fixture.budgets.try_generation(identity) is True

    def test_regenerate_budget_exhaustion_names_healing_pool(self, tmp_path: Path) -> None:
        provider = StubProvider([BROKEN_CODE], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider, limits=(3, 1))
        identity = make_identity()
        page = TimeoutPage()
        history = make_anchored_history()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.regenerate(
                identity, "невозможный шаг", "action", [], page, history, "retry with an id locator", fixture.window
            )

        assert excinfo.value.reason == "healing attempt budget exhausted"
        assert excinfo.value.error == "TimeoutError: navigation timed out"  # the last record of the history
        assert excinfo.value.code == BROKEN_CODE  # the last record of the history, not the anchored original
        assert excinfo.value.verdict is None  # the healer attaches the verdict — no second LLM request
        assert excinfo.value.recommendation == "reword the step or refresh the cache"  # fallback without a verdict
        assert len(provider.calls) == 1  # the healing budget (1) is exhausted after the first attempt
        assert provider.classify_failure_calls == []  # the healing pool does not classify exhaustion
        assert len(history) == 2  # record 0 + the failed healing attempt

    def test_messageless_candidate_failure_is_retried_not_crashed(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE, WORKING_CODE], verdict=ROT_VERDICT)
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage(assertion_message="")  # message-less assert: str(exc) == ''
        history: list[StepAttempt] = []

        first = fixture.generator.generate(
            make_identity(), "проверить страницу", "action", [], page, history, fixture.window
        )

        assert first.code == WORKING_CODE
        assert len(provider.calls) == 1  # even a message-less AssertionError — stop without retries
        assert provider.calls[0]["attempt_history"] == []
        assert history == []  # the green attempt records nothing

    def test_messageless_candidate_check_keeps_plain_reason(self, tmp_path: Path) -> None:
        provider = StubProvider(
            ["def step(page) -> None:\n    page.get_by_text('Welcome back').expect_visible()\n"],
            verdict=FailureClassification(category="incurable", explanation="e", recommendation="r"),
        )
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 2))
        page = FakePage(assertion_message="")  # message-less assert: str(exc) == ''

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(make_identity(), "невозможный шаг", "action", [], page, [], fixture.window)

        # an empty failure description leaves the em-dash reason without an error tail
        assert excinfo.value.reason == "candidate check failed — "

    def test_generated_step_is_saved_into_cache(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        identity = make_identity()
        page = FakePage()

        fixture.generator.generate(identity, "открыть страницу", "action", [], page, [], fixture.window)

        loaded = fixture.cache.load(identity)
        assert loaded is not None
        assert loaded.code.rstrip("\n") == WORKING_CODE.rstrip("\n")  # the serializer appends a trailing \n
        assert loaded.created_at

    def test_incident_narrowing_candidate_runs_green(self, tmp_path: Path) -> None:
        """AC2: the narrowing idiom as a first candidate runs green — no retries, cached as-is."""
        provider = StubProvider([NARROWING_CODE])
        fixture = GeneratorFixture(tmp_path, provider, limits=(3, 3))
        identity = make_identity()
        page = FakePage()

        step = fixture.generator.generate(
            identity, "the «Welcome back» message appears", "action", [], page, [], fixture.window
        )

        assert step.code == NARROWING_CODE
        assert len(provider.calls) == 1  # the first candidate is green — zero retries
        assert "locator.first" in provider.calls[0]["cheat_sheet"]  # the cheat sheet listed the member
        assert ("get_by_text", "Welcome back") in page.calls  # the narrowing chain executed through the page
        loaded = fixture.cache.load(identity)  # StepCache has no save recording — load back
        assert loaded is not None
        assert loaded.code.rstrip("\n") == NARROWING_CODE.rstrip("\n")  # the serializer appends a trailing \n

    def test_created_at_is_today_iso(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])
        fixture = GeneratorFixture(tmp_path, provider)
        page = FakePage()

        step = fixture.generator.generate(make_identity(), "открыть страницу", "action", [], page, [], fixture.window)

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
            fixture.generator.generate(
                make_identity(), "see the welcome banner", "action", [], page, [], fixture.window
            )

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
            fixture.generator.generate(
                make_identity(), "see the welcome banner", "action", [], page, [], fixture.window
            )

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
            fixture.generator.generate(make_identity(), "невозможный шаг", "action", [], page, [], fixture.window)

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
            fixture.generator.generate(
                make_identity(), "see the welcome banner", "action", [], page, [], fixture.window
            )

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
            fixture.generator.generate(make_identity(), "impossible step", "action", [], page, [], fixture.window)

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
        history: list[StepAttempt] = []

        step = fixture.generator.generate(
            make_identity(), "press the sign in button", "action", [], page, history, fixture.window
        )

        assert step.code == WORKING_CODE
        assert len(provider.calls) == 2  # a locator timeout spends an attempt and retries, no check-stop
        assert provider.calls[1]["attempt_history"] == [history[0].render()]  # the timed-out attempt rides the retry
        assert history[0].outcome == OUTCOME_EXECUTION_FAILED  # a locator timeout is a candidate failure, not a check
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
        history: list[StepAttempt] = []

        step = fixture.generator.generate(make_identity(), "click Pay", "action", [], page, history, fixture.window)

        assert step.code == WORKING_CODE
        assert len(provider.calls) == 2  # the failed candidate + the one funded regeneration
        second = provider.calls[1]
        assert second["recommendation"] == "retry with an id locator"
        assert second["attempt_history"] == [history[0].render()]  # the failed check rides the funded request
        assert history[0].outcome == OUTCOME_FAILED_CHECK  # the failed candidate
        assert history[0].code == CHECK_CODE
        assert history[0].error == "button is hidden"
        assert second["guidance"] is None  # engine requests never carry steering guidance
        assert second["page_url"] is None  # the funded regeneration shares the same _request call shape
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
        history: list[StepAttempt] = []

        step = fixture.generator.generate(make_identity(), "click Pay", "action", [], page, history, fixture.window)

        assert step.code == WORKING_CODE
        assert len(provider.calls) == 2  # the failed candidate + the one funded regeneration
        second = provider.calls[1]
        assert second["recommendation"] == "use a precise role-and-name locator"
        assert second["attempt_history"] == [history[0].render()]  # the failed check rides the funded request
        assert history[0].outcome == OUTCOME_FAILED_CHECK
        assert history[0].code == CHECK_CODE
        assert history[0].error == "button is hidden"

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
            fixture.generator.generate(make_identity(), "click Pay", "action", [], page, [], fixture.window)

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
            fixture.generator.generate(make_identity(), "click Pay", "action", [], page, [], fixture.window)

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
            fixture.generator.generate(make_identity(), "click Pay", "action", [], page, [], fixture.window)

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
            fixture.generator.generate(make_identity(), "click Pay", "action", [], page, [], fixture.window)

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
            fixture.generator.generate(make_identity(), "click Pay", "action", [], page, [], fixture.window)

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
            fixture.generator.generate(make_identity(), "click Pay", "action", [], page, [], fixture.window)

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
            fixture.generator.generate(make_identity(), "click Pay", "action", [], page, [], fixture.window)

        # not "candidate check failed"; the first-line contract strips the colon of the embedded text
        assert excinfo.value.reason == "candidate failed — TypeError  bad code"
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
            fixture.generator.generate(make_identity(), "click Pay", "action", [], page, [], fixture.window)

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
            fixture.generator.generate(
                make_identity(), "see the welcome banner", "action", [], page, [], fixture.window
            )

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
            fixture.generator.generate(make_identity(), "click Pay", "action", [], page, [], fixture.window)

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

        step = fixture.generator.generate(identity, "click Pay", "action", [], page, [], fixture.window)

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
            step = fixture.generator.generate(
                identity, "open the page", "action", [], page, [], SettleWindow(10.0, 0)
            )

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
            fixture.generator.generate(identity, "невозможный шаг", "action", [], page, [], fixture.window)

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
                make_identity(), "see the welcome banner", "action", [], defect_page, [], defect_fixture.window
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
                make_identity(), "невозможный шаг", "action", [], timeout_page, [], exhausted_fixture.window
            )

        assert exhausted.value.error == "TimeoutError: navigation timed out"  # the last candidate full text
        assert exhausted.value.reason == "generation attempt budget exhausted"  # no colon, no embedded error


class TestStepGeneratorAttemptHistory:
    """Logic tests: the per-step attempt history growth, URL brackets and honest inputs."""

    def test_generate_appends_execution_failed_record_and_retries_with_grown_history(self, tmp_path: Path) -> None:
        provider = StubProvider([BAD_CODE, WORKING_CODE], compliance_verdicts=[[]])
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        page = FakePage(
            url=url_cycle("https://a.example", "https://b.example", "https://c.example", "https://d.example")
        )
        history: list[StepAttempt] = []

        step = fixture.generator.generate(
            make_identity(), "open the videos page", "action", [], page, history, fixture.window
        )

        assert step.code == WORKING_CODE
        assert provider.calls[0]["attempt_history"] == []  # the first request of a fresh step
        assert provider.calls[1]["attempt_history"] == [history[0].render()]  # the failed attempt rides the retry
        assert history[0].outcome == OUTCOME_EXECUTION_FAILED
        assert history[0].error == "RuntimeError: boom"
        assert history[0].code == BAD_CODE
        assert history[0].url_before == "https://a.example"  # the URL pair brackets the whole attempt
        assert history[0].url_after == "https://b.example"
        assert len(history) == 1  # the green attempt never records

    def test_generate_appends_compliance_blocked_record_on_high_adequacy_finding(self, tmp_path: Path) -> None:
        adequacy = ComplianceFinding(
            instruction="click the «Sign in» button",
            priority="high",
            explanation="code only checks an already-achieved state",
            dimension="adequacy",
        )
        provider = StubProvider([CHECK_CODE, WORKING_CODE], compliance_verdicts=[[adequacy], []])
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        page = FakePage()
        history: list[StepAttempt] = []

        step = fixture.generator.generate(
            make_identity(), "click the «Sign in» button", "action", [], page, history, fixture.window
        )

        assert step.code == WORKING_CODE
        assert history[0].outcome == OUTCOME_COMPLIANCE_BLOCKED
        assert history[0].error.startswith("adequacy violation: click the «Sign in» button")
        assert provider.calls[1]["attempt_history"] == [history[0].render()]  # the retry sees the blocked attempt

    def test_regenerate_never_loses_record_zero_through_retries(self, tmp_path: Path) -> None:
        provider = StubProvider([BAD_CODE, WORKING_CODE], compliance_verdicts=[[]])
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        page = FakePage()
        cached_code = "def step(page) -> None:\n    page.goto('https://old')\n"
        history = [StepAttempt(code=cached_code, error="old rot", outcome=OUTCOME_ORIGINAL)]

        step = fixture.generator.regenerate(
            make_identity(), "click the «Sign in» button", "action", [], page, history, "use role locators",
            fixture.window,
        )

        assert step.code == WORKING_CODE
        assert history[0].code == cached_code  # record 0 stays untouched at index 0 through every retry
        assert history[0].outcome == OUTCOME_ORIGINAL
        assert provider.calls[0]["attempt_history"] == [history[0].render()]
        assert provider.calls[1]["attempt_history"] == [history[0].render(), history[1].render()]
        assert history[1].outcome == OUTCOME_EXECUTION_FAILED  # the failed regeneration appended after record 0

    def test_url_read_failure_degrades_to_empty_string_and_attempt_proceeds(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE], compliance_verdicts=[[]])
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        page = FakePage(url=RuntimeError("page crashed"))  # a dead page — every URL read fails
        history: list[StepAttempt] = []

        step = fixture.generator.generate(make_identity(), "open the page", "action", [], page, history, fixture.window)

        assert step.code == WORKING_CODE  # the failed reads never kill the attempt
        assert history == []  # the green attempt records nothing; the failed reads never surface

    def test_generation_exhaustion_with_standing_adequacy_finding_names_the_step_fragment(
        self, tmp_path: Path
    ) -> None:
        adequacy = ComplianceFinding(
            instruction="click the «Sign in» button",
            priority="high",
            explanation="code only checks an already-achieved state",
            dimension="adequacy",
        )
        provider = StubProvider([WORKING_CODE], compliance_verdicts=[[adequacy]])
        fixture = GeneratorFixture(tmp_path, provider, limits=(1, 0), generation_prompt="Prefer id attributes")
        page = FakePage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(
                make_identity(), "click the «Sign in» button", "action", [], page, [], fixture.window
            )

        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "incurable"  # built from the finding — no classification call
        assert (
            excinfo.value.verdict.explanation
            == "click the «Sign in» button — code only checks an already-achieved state"
        )
        assert excinfo.value.verdict.recommendation.startswith("satisfy the finding in the step code:")
        assert "generation attempt budget exhausted" in excinfo.value.reason
        assert ":" not in excinfo.value.reason  # the first-line contract holds — the reason names the fragment
        assert excinfo.value.error.startswith("adequacy violation:")  # the violation text rides the error field
        assert provider.classify_failure_calls == []  # zero classifications on the standing branch

    def test_regenerate_exhaustion_derives_terminal_facts_from_last_record(self, tmp_path: Path) -> None:
        provider = StubProvider([BAD_CODE])
        fixture = GeneratorFixture(tmp_path, provider, limits=(3, 1))  # exactly one healing attempt
        page = FakePage()
        cached_code = "def step(page) -> None:\n    page.goto('https://old')\n"
        history = [
            StepAttempt(
                code=cached_code,
                error="old rot",
                outcome=OUTCOME_ORIGINAL,
                url_before="https://a.example",
                url_after="https://b.example",
            )
        ]

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.regenerate(
                make_identity(), "click the «Sign in» button", "action", [], page, history, "use role locators",
                fixture.window,
            )

        assert excinfo.value.reason == "healing attempt budget exhausted"
        assert excinfo.value.code == BAD_CODE  # the last record's code — not the anchored original
        assert excinfo.value.error == "RuntimeError: boom"  # the last record's error
        assert excinfo.value.verdict is None  # the healer attaches the entry verdict — none built inside the loop
        assert len(history) == 2
        assert history[0].code == cached_code  # record 0 stays intact through the failed healing
        assert history[0].outcome == OUTCOME_ORIGINAL
        assert history[1].code == BAD_CODE
        assert history[1].outcome == OUTCOME_EXECUTION_FAILED


class TestStepGeneratorComplianceGate:
    """Logic tests: the two-dimension compliance gate on every caching path of the generator."""

    def test_generate_gates_candidate_and_stores_on_compliant(self, tmp_path: Path) -> None:
        provider = StubProvider([WORKING_CODE])  # the default compliance verdict is [] — compliant
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        identity = make_identity()
        page = FakePage()

        step = fixture.generator.generate(identity, "open the page", "action", [], page, [], fixture.window)

        assert step.code == WORKING_CODE
        assert fixture.cache.load(identity) is not None  # the cache file exists
        assert len(provider.calls) == 1  # one generation call
        assert len(provider.compliance_calls) == 1  # one compliance call
        assert provider.compliance_calls[0]["code"] == WORKING_CODE  # the green candidate is the gated one
        assert provider.compliance_calls[0]["step_type"] == "action"  # the honest gate inputs
        assert provider.compliance_calls[0]["attempt_history"] == []  # a green first attempt records nothing yet

    def test_generate_high_finding_fails_attempt_and_retry_carries_violation(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = StubProvider(
            [CHECK_CODE, WORKING_CODE],  # CHECK_CODE is green on a plain page — it violates the instructions
            compliance_verdicts=[[HIGH_FINDING], []],
        )
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        identity = make_identity()
        page = FakePage()
        history: list[StepAttempt] = []

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            step = fixture.generator.generate(identity, "click Sign in", "action", [], page, history, fixture.window)

        assert step.code == WORKING_CODE
        second = provider.calls[1]
        assert second["attempt_history"] == [history[0].render()]  # the blocked attempt rides the retry
        assert history[0].outcome == OUTCOME_COMPLIANCE_BLOCKED
        assert history[0].error == VIOLATION_TEXT  # the violation text rides the record's error field
        assert len(provider.calls) == 2  # exactly 2 generation calls
        assert len(provider.compliance_calls) == 2  # exactly 2 compliance calls
        loaded = fixture.cache.load(identity)
        assert loaded is not None
        assert loaded.code.rstrip("\n") == WORKING_CODE.rstrip("\n")  # only the compliant code is stored
        # nothing passed with findings — no WARNING on the retry path
        assert not [record for record in caplog.records if "compliance" in record.message]

    def test_generate_medium_low_findings_pass_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        findings = [
            ComplianceFinding(
                instruction="Prefer id attributes", priority="medium", explanation="partial", dimension="instruction"
            ),
            ComplianceFinding(
                instruction="Avoid fixed delays", priority="low", explanation="note", dimension="adequacy"
            ),
        ]
        provider = StubProvider([WORKING_CODE], compliance_verdicts=[findings])
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        identity = make_identity()
        page = FakePage()

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            step = fixture.generator.generate(identity, "click Sign in", "action", [], page, [], fixture.window)

        assert step.code == WORKING_CODE  # non-blocking findings never fail the attempt
        assert fixture.cache.load(identity) is not None  # the step is stored and returned
        passed = [record for record in caplog.records if record.message == "compliance findings passed"]
        assert len(passed) == 1
        assert passed[0].step_text == "click Sign in"  # the structured extra names the step
        assert any(rendered.startswith("medium instruction:") for rendered in passed[0].findings)
        assert any(rendered.startswith("low adequacy:") for rendered in passed[0].findings)

    def test_generate_budget_exhaustion_with_standing_high_names_finding(self, tmp_path: Path) -> None:
        provider = StubProvider(
            [WORKING_CODE, WORKING_CODE],  # every candidate is green — the gate is what fails them
            compliance_verdicts=[[HIGH_FINDING], [HIGH_FINDING]],
        )
        fixture = GeneratorFixture(tmp_path, provider, limits=(2, 2), generation_prompt="Prefer id attributes")
        identity = make_identity()
        page = FakePage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(identity, "click Sign in", "action", [], page, [], fixture.window)

        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "incurable"  # built from the finding — no classification call
        assert excinfo.value.verdict.explanation == "Prefer id attributes — locates by text"
        assert excinfo.value.verdict.recommendation == "satisfy the finding in the step code: Prefer id attributes"
        assert excinfo.value.reason == "generation attempt budget exhausted — Prefer id attributes"
        assert ":" not in excinfo.value.reason.split("\n")[0]  # the first-line contract holds
        assert excinfo.value.error == VIOLATION_TEXT  # the violation text rides the error field
        assert excinfo.value.code == WORKING_CODE
        assert provider.classify_failure_calls == []  # zero classifications on the standing-high branch
        assert fixture.cache.load(identity) is None  # nothing in the cache

    def test_generate_gate_hard_failure_propagates_and_caches_nothing(self, tmp_path: Path) -> None:
        outage = ComplianceVerdictError("compliance verdict unparsable — received fragment: nope")
        provider = StubProvider([WORKING_CODE], compliance_verdicts=[outage])
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        identity = make_identity()
        page = FakePage()

        with pytest.raises(ComplianceVerdictError) as excinfo:
            fixture.generator.generate(identity, "click Sign in", "action", [], page, [], fixture.window)

        assert excinfo.value is outage  # propagates — no retry, no budget table
        assert len(provider.calls) == 1  # exactly one generation call
        assert fixture.cache.load(identity) is None  # the unchecked candidate is never cached

    def test_regenerate_gates_healed_candidate_before_write_back(self, tmp_path: Path) -> None:
        provider = StubProvider(
            [CHECK_CODE, WORKING_CODE],
            compliance_verdicts=[[HIGH_FINDING], []],
        )
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        identity = make_identity()
        page = FakePage()
        history = make_anchored_history()

        step = fixture.generator.regenerate(
            identity, "click Sign in", "action", [], page, history, "retry with an id locator", fixture.window
        )

        assert step.code == WORKING_CODE
        assert history[1].outcome == OUTCOME_COMPLIANCE_BLOCKED  # the blocked heal appended after record 0
        assert history[1].error == VIOLATION_TEXT
        # the healing retry carries the anchored record plus the blocked attempt
        assert provider.calls[1]["attempt_history"] == [history[0].render(), history[1].render()]
        assert len(provider.compliance_calls) == 2  # the healed candidate is gated too
        loaded = fixture.cache.load(identity)
        assert loaded is not None
        assert loaded.code.rstrip("\n") == WORKING_CODE.rstrip("\n")  # only the compliant heal is written back

    def test_regenerate_high_finding_exhaustion_carries_violation_and_entry_verdict(
        self, tmp_path: Path
    ) -> None:
        provider = StubProvider(
            [WORKING_CODE],
            compliance_verdicts=[[HIGH_FINDING]],
        )
        fixture = GeneratorFixture(tmp_path, provider, limits=(3, 1), generation_prompt="Prefer id attributes")
        identity = make_identity()
        page = FakePage()
        history = make_anchored_history()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.regenerate(
                identity, "click Sign in", "action", [], page, history, "retry with an id locator", fixture.window
            )

        assert excinfo.value.error == VIOLATION_TEXT  # the last record's error — the blocked candidate
        assert excinfo.value.reason == "healing attempt budget exhausted"  # the unchanged exhaustion raise
        assert excinfo.value.verdict is None  # the healer reattaches the entry verdict — not built inside the loop
        assert excinfo.value.code == WORKING_CODE  # the last gated candidate
        assert len(provider.calls) == 1  # exactly 1 generation call
        assert len(provider.compliance_calls) == 1
        assert provider.classify_failure_calls == []
        assert fixture.cache.load(identity) is None

    def test_funded_regeneration_gates_before_store(self, tmp_path: Path) -> None:
        """The funded candidate is gated too — a high block is a repeat candidate failure, not a check."""
        provider = StubProvider(
            [CHECK_CODE, WORKING_CODE],  # the entry candidate fails the check; the funded one is green but high
            verdicts=[
                FailureClassification(category="rot", explanation="the button was renamed", recommendation="id"),
                FailureClassification(category="incurable", explanation="e", recommendation="r"),
            ],
            compliance_verdicts=[[HIGH_FINDING]],
        )
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        identity = make_identity()
        page = FakePage(assertion_message="button is hidden")  # the entry candidate's check fails

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(identity, "click Pay", "action", [], page, [], fixture.window)

        assert provider.classify_failure_calls[1]["error"] == VIOLATION_TEXT  # the final classification sees it
        assert len(provider.calls) == 2  # the failed candidate + exactly one funded request
        assert len(provider.compliance_calls) == 1  # the gate ran on the funded green candidate only
        assert fixture.cache.load(identity) is None  # the cache is untouched
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "incurable"
        # the repeat reason embeds the violation text first-line safe — the colon is stripped
        assert (
            excinfo.value.reason == "candidate failed — instruction violation  Prefer id attributes — locates by text"
        )
        assert ":" not in excinfo.value.reason.split("\n")[0]  # the first-line contract holds

    def test_funded_regeneration_compliance_block_quiet_skip_keeps_candidate_failure_reason(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A quiet skip of the final classification never relabels a compliance block as a check."""
        provider = StubProvider(
            [CHECK_CODE, WORKING_CODE],  # the entry candidate fails the check; the funded one is green but high
            verdicts=[
                FailureClassification(category="rot", explanation="the button was renamed", recommendation="id"),
                LLMUnavailableError("llm unavailable: openai request failed"),
            ],
            compliance_verdicts=[[HIGH_FINDING]],
        )
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        identity = make_identity()
        page = FakePage(assertion_message="button is hidden")  # the entry candidate's check fails

        with caplog.at_level(logging.WARNING, logger="prettyplay"), pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(identity, "click Pay", "action", [], page, [], fixture.window)

        assert excinfo.value.verdict is None  # the quiet skip — never an infrastructure failure
        assert excinfo.value.error == VIOLATION_TEXT
        assert len(provider.calls) == 2  # the failed candidate + exactly one funded request
        assert fixture.cache.load(identity) is None  # nothing is cached on the blocked path
        # the label stays "candidate failed" — a compliance block is never a check — and the
        # first-line contract holds even without a final verdict to carry the wording
        assert (
            excinfo.value.reason == "candidate failed — instruction violation  Prefer id attributes — locates by text"
        )
        assert ":" not in excinfo.value.reason.split("\n")[0]
        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert any("verdict skipped" in record.message for record in warnings)

    def test_regenerate_gate_hard_failure_propagates_and_caches_nothing(self, tmp_path: Path) -> None:
        """A malformed verdict of a green healed candidate propagates — never swallowed into a retry."""
        outage = ComplianceVerdictError("compliance verdict unparsable — received fragment: nope")
        provider = StubProvider([WORKING_CODE], compliance_verdicts=[outage])
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        identity = make_identity()
        page = FakePage()
        history = make_anchored_history()

        with pytest.raises(ComplianceVerdictError) as excinfo:
            fixture.generator.regenerate(
                identity, "click Sign in", "action", [], page, history, "retry with an id locator", fixture.window
            )

        assert excinfo.value is outage  # propagates — the loop's except Exception never sees the gate
        assert len(provider.calls) == 1  # exactly one healing request — no retry after the hard failure
        assert len(provider.compliance_calls) == 1
        assert fixture.cache.load(identity) is None  # the unchecked candidate is never cached

    def test_funded_regeneration_gate_hard_failure_propagates_and_caches_nothing(self, tmp_path: Path) -> None:
        """A malformed verdict of the funded candidate propagates — no final classification, nothing cached."""
        outage = ComplianceVerdictError("compliance verdict unparsable — received fragment: nope")
        provider = StubProvider(
            [CHECK_CODE, WORKING_CODE],  # the entry candidate fails the check; the funded one is green
            verdicts=[
                FailureClassification(category="rot", explanation="the button was renamed", recommendation="id"),
            ],
            compliance_verdicts=[outage],
        )
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        identity = make_identity()
        page = FakePage(assertion_message="button is hidden")

        with pytest.raises(ComplianceVerdictError) as excinfo:
            fixture.generator.generate(identity, "click Pay", "action", [], page, [], fixture.window)

        assert excinfo.value is outage  # propagates — the settle try never swallows the gate
        assert len(provider.calls) == 2  # the failed candidate + the one funded request that turned green
        assert len(provider.compliance_calls) == 1
        assert len(provider.classify_failure_calls) == 1  # the entry classification only — no final one
        assert fixture.cache.load(identity) is None

    def test_generate_candidate_failure_replaces_the_standing_violation(self, tmp_path: Path) -> None:
        """A real candidate failure drops the standing high finding — the exhaustion follows the normal table."""
        provider = StubProvider(
            [WORKING_CODE, BROKEN_CODE],  # candidate 1 green but high; candidate 2 dies on the page
            verdict=ROT_VERDICT,
            compliance_verdicts=[[HIGH_FINDING]],  # candidate 2 never reaches the gate
        )
        fixture = GeneratorFixture(tmp_path, provider, limits=(2, 0), generation_prompt="Prefer id attributes")
        identity = make_identity()
        page = FakePage()  # no get_by_role — candidate 2 fails with a non-assertion AttributeError

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(identity, "click Pay", "action", [], page, [], fixture.window)

        assert excinfo.value.reason == "healing attempt budget exhausted"  # the refused funding of the rot verdict
        assert "violation" not in excinfo.value.reason  # the reset standing finding no longer names it
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "rot"  # the classification verdict, never the standing-built one
        assert len(provider.classify_failure_calls) == 1  # the exhaustion classified — the standing branch never does
        assert len(provider.compliance_calls) == 1  # only the first green candidate was gated

    def test_generate_standing_high_instruction_with_colon_and_newline_stays_reason_safe(
        self, tmp_path: Path
    ) -> None:
        """A colon-bearing multi-line instruction stays first-line safe in the authored standing reason."""
        instruction = "Use page.locator: prefer ids\nalways narrow positionally"
        finding = ComplianceFinding(
            instruction=instruction, priority="high", explanation="locates by text", dimension="instruction"
        )
        provider = StubProvider(
            [WORKING_CODE, WORKING_CODE], compliance_verdicts=[[finding], [finding]]
        )
        fixture = GeneratorFixture(tmp_path, provider, limits=(2, 2), generation_prompt="Use page.locator: prefer ids")
        identity = make_identity()
        page = FakePage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.generator.generate(identity, "click Sign in", "action", [], page, [], fixture.window)

        assert (
            excinfo.value.reason
            == "generation attempt budget exhausted — Use page.locator  prefer ids"
        )
        assert ":" not in excinfo.value.reason.split("\n")[0]  # the first-line contract holds through the colon
        assert "\n" not in excinfo.value.reason  # the newline of the instruction is cut at the first line
        # the error keeps it all
        assert excinfo.value.error == f"instruction violation: {instruction} — locates by text"

    def test_regenerate_medium_findings_pass_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-blocking findings of a healed candidate pass with a WARNING — the heal is written back."""
        findings = [
            ComplianceFinding(
                instruction="Prefer id attributes", priority="medium", explanation="partial", dimension="instruction"
            )
        ]
        provider = StubProvider([WORKING_CODE], compliance_verdicts=[findings])
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        identity = make_identity()
        page = FakePage()
        history = make_anchored_history()

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            step = fixture.generator.regenerate(
                identity, "click Sign in", "action", [], page, history, "retry with an id locator", fixture.window
            )

        assert step.code == WORKING_CODE  # non-blocking findings never fail the heal
        assert fixture.cache.load(identity) is not None
        passed = [record for record in caplog.records if record.message == "compliance findings passed"]
        assert len(passed) == 1
        assert passed[0].step_text == "click Sign in"

    def test_funded_regeneration_medium_findings_pass_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-blocking findings of the funded candidate pass with a WARNING — the heal is stored."""
        findings = [
            ComplianceFinding(
                instruction="Prefer id attributes", priority="medium", explanation="partial", dimension="instruction"
            )
        ]
        provider = StubProvider(
            [CHECK_CODE, WORKING_CODE],  # the entry candidate fails the check; the funded one is green
            verdicts=[
                FailureClassification(category="rot", explanation="the button was renamed", recommendation="id"),
            ],
            compliance_verdicts=[findings],
        )
        fixture = GeneratorFixture(tmp_path, provider, generation_prompt="Prefer id attributes")
        identity = make_identity()
        page = FakePage(assertion_message="button is hidden")

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            step = fixture.generator.generate(identity, "click Pay", "action", [], page, [], fixture.window)

        assert step.code == WORKING_CODE  # the funded regeneration healed through the warning
        assert fixture.cache.load(identity) is not None
        passed = [record for record in caplog.records if record.message == "compliance findings passed"]
        assert len(passed) == 1
        assert passed[0].step_text == "click Pay"


class TestPromptConstants:
    """Constant tests: prompts and the frozen cheat sheet."""

    def test_generation_prompt_is_frozen_text(self) -> None:
        assert SYSTEM_PROMPT.startswith("You generate executable Python code")
        assert "def step(page) -> None:" in SYSTEM_PROMPT

    def test_generation_prompt_rule_order_survives_the_edit(self) -> None:
        # the assertion rule sits exactly after the work-through rule, before the no-delays rule
        work_through = SYSTEM_PROMPT.index("- Work through the standard Playwright sync API")
        assertion = SYSTEM_PROMPT.index("- Assertions: for an assertion sentence end with a check")
        no_delays = SYSTEM_PROMPT.index("- No fixed delays, no sleeps, no wait_for_timeout")
        dialogs = SYSTEM_PROMPT.index("- Dialogs: capture with the stock means")
        scrolling = SYSTEM_PROMPT.index("- Scrolling: locator.scroll_into_view_if_needed()")
        assert work_through < assertion < no_delays < dialogs < scrolling

    def test_system_prompt_documents_user_instructions_input(self) -> None:
        # the USER INSTRUCTIONS input line sits right after the CHEAT SHEET input line, before HISTORY
        cheat_sheet_input = SYSTEM_PROMPT.index("- CHEAT SHEET: a compact reference")
        user_instructions_input = SYSTEM_PROMPT.index("- USER INSTRUCTIONS: the project's binding code style guidance")
        history_input = SYSTEM_PROMPT.index("- HISTORY: the verbatim record of every attempt")
        assert cheat_sheet_input < user_instructions_input < history_input

    def test_system_prompt_mirrors_the_generation_practice(self) -> None:
        practice = GENERATION_PROMPT_PRACTICE.read_text(encoding="utf-8")
        prompt = practice.split("---", 1)[1].strip()  # the section after the separator is the prompt itself

        assert prompt == SYSTEM_PROMPT  # the frozen mirror — the constant changes only together with the file
        # spot-asserts of the rewritten rules — the equality alone would hide a both-sides edit
        assert "Import from playwright.sync_api and the Python standard library only" in SYSTEM_PROMPT
        assert "never call page.close() or context.close()" in SYSTEM_PROMPT
        assert 'expect_event("dialog")' in SYSTEM_PROMPT
        assert "assert locator.count() > 1" in SYSTEM_PROMPT
        assert ("page." + "expect" + "_dialog()") not in SYSTEM_PROMPT  # the facade capture idiom is gone
        # the honest inputs — the STEP TYPE line rides immediately before the STEP line
        step_type_input = SYSTEM_PROMPT.index("- STEP TYPE: action or assertion — the kind of the step")
        step_input = SYSTEM_PROMPT.index("- STEP: the step sentence in a natural language")
        assert step_type_input < step_input
        # the history record the practice added — the complete verbatim attempt record
        assert (
            "each record carries the attempt outcome, the URL before -> after line, "
            "the complete candidate code and the complete error" in SYSTEM_PROMPT
        )

    def test_system_prompt_carries_the_new_input_lines_and_rule(self) -> None:
        history_input = SYSTEM_PROMPT.index("- HISTORY: the verbatim record")
        recommendation_input = SYSTEM_PROMPT.index("- RECOMMENDATION: the diagnosis of the classification")
        guidance_input = SYSTEM_PROMPT.index("- USER GUIDANCE: the engineer guidance message")
        assert history_input < recommendation_input < guidance_input
        assert (
            "RECOMMENDATION and USER GUIDANCE carry the diagnosis and the engineer's intent — "
            "follow them when they conflict with your first instinct" in SYSTEM_PROMPT
        )
        # the replayability rule sits between the scrolling rule and the RECOMMENDATION rule
        scrolling_rule = SYSTEM_PROMPT.index("- Scrolling: locator.scroll_into_view_if_needed()")
        replayability_rule = SYSTEM_PROMPT.index("Your code must produce the step outcome itself")
        recommendation_rule = SYSTEM_PROMPT.index("- RECOMMENDATION and USER GUIDANCE carry the diagnosis")
        assert scrolling_rule < replayability_rule < recommendation_rule

    def test_classification_prompt_moved_out_of_generator(self) -> None:
        assert not hasattr(generator_module, "CLASSIFICATION_PROMPT")  # moved to classification.py

    def test_cheat_sheet_mirrors_the_practice(self) -> None:
        practice = CHEAT_SHEET_PRACTICE.read_text(encoding="utf-8")

        assert practice == CHEAT_SHEET  # the whole file, verbatim — no extraction logic to drift
        # the dead constant name is assembled — no literal survives the series-end leftover sweep
        assert not hasattr(generator_module, "PAGE" + "_API" + "_SURFACE")  # the surface listing is gone
