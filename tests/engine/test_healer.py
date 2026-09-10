"""Tests for the StepHealer of the prettyplay.engine cell."""

import inspect
from pathlib import Path

import pytest
from prettyplay.cache import CachedStep, RunBudgets, StepCache, StepIdentity
from prettyplay.config import Config
from prettyplay.engine import StepGenerator, StepHealer
from prettyplay.engine.classification import CLASSIFICATION_PROMPT
from prettyplay.failures import (
    FailureVerdict,
    IncurableStepError,
    LLMUnavailableError,
    PrettyplayError,
    ProductDefectError,
)
from prettyplay.llm import FailureClassification
from prettyplay.reporting import StepHooks, StepReporter

FAILED_CODE = "def step(page) -> None:\n    page.find_by_role('button', name='Sign in').click()\n"
HEALED_CODE = "def step(page) -> None:\n    page.find_by_text('Sign in').click()\n"
TIMEOUT_CODE = "def step(page) -> None:\n    page.find_by_role('button', name='Submit').click()\n"
CHECK_CODE = "def step(page) -> None:\n    page.find_by_text('Welcome back').expect_visible()\n"


class FakePage:
    """Fake page facade boundary: snapshot for the classification request."""

    def aria_snapshot(self) -> str:
        return "- snapshot"

    def screenshot(self) -> bytes:
        return b"png"


class TimeoutPage(FakePage):
    """Fake page where every regenerated candidate fails with a TimeoutError."""

    def find_by_role(self, role: str, name: str) -> None:
        raise TimeoutError("waiting for the element timed out")


class FailingLocator:
    """Fake element boundary: the expectation fails with the scripted message."""

    def expect_visible(self) -> None:
        raise AssertionError("banner missing")


class CheckFailingPage(FakePage):
    """Fake page where the candidate check fails with an AssertionError."""

    def find_by_text(self, text: str) -> FailingLocator:
        return FailingLocator()


class FakeProvider:
    """Fake provider boundary: scripted verdicts and candidates with recorded requests."""

    def __init__(
        self,
        classifications: list[FailureClassification | Exception],
        answers: list[str] | None = None,
    ) -> None:
        self.classifications = list(classifications)
        self.answers = list(answers or [])
        self.classify_failure_calls: list[dict[str, object]] = []
        self.generate_step_code_calls: list[dict[str, object]] = []

    @property
    def classify_failure_call_count(self) -> int:
        return len(self.classify_failure_calls)

    @property
    def generate_step_code_call_count(self) -> int:
        return len(self.generate_step_code_calls)

    def classify_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        code: str,
        error: str,
        snapshot: str,
        screenshot: bytes | None,
    ) -> FailureClassification:
        self.classify_failure_calls.append(
            {
                "prompt": prompt,
                "user_instructions": user_instructions,
                "step_text": step_text,
                "code": code,
                "error": error,
                "snapshot": snapshot,
                "screenshot": screenshot,
            }
        )
        verdict = self.classifications.pop(0)
        if isinstance(verdict, Exception):
            raise verdict
        return verdict

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
        self.generate_step_code_calls.append(
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
        return self.answers.pop(0)


class SpyGenerator:
    """Generator spy: records regenerate calls, returns the healed step."""

    def __init__(self, healed: CachedStep) -> None:
        self.healed = healed
        self.calls: list[dict[str, object]] = []

    def regenerate(  # noqa: PLR0913, PLR0917 — the signature is fixed by the engine contract
        self,
        identity: StepIdentity,
        step_text: str,
        previous_steps: list[str],
        page: FakePage,
        existing_code: str,
        error: str,
    ) -> CachedStep:
        self.calls.append(
            {
                "identity": identity,
                "step_text": step_text,
                "previous_steps": previous_steps,
                "page": page,
                "existing_code": existing_code,
                "error": error,
            }
        )
        return self.healed


class SpyCache:
    """Cache spy: records save calls; the healer itself must never write."""

    def __init__(self) -> None:
        self.save_calls: list[CachedStep] = []

    def save(self, step: CachedStep) -> None:
        self.save_calls.append(step)


class RecorderHook(StepHooks):
    """Hook recording healing events into a shared ``events`` list for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str]]] = []

    def on_healing_started(self, step_text: str, category: str) -> None:
        self.events.append(("on_healing_started", {"step_text": step_text, "category": category}))

    def on_healed(self, step_text: str, explanation: str) -> None:
        self.events.append(("on_healed", {"step_text": step_text, "explanation": explanation}))


class TestStepHealerContract:
    """Contract tests: facade import, constructor and method signatures, verdict building."""

    def test_step_healer_is_importable_from_facade(self) -> None:
        assert isinstance(StepHealer, type)

    def test_constructor_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(StepHealer.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == [
            "config",
            "provider",
            "generator",
            "cache",
            "budgets",
            "reporter",
        ]

    def test_heal_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(StepHealer.heal).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == [
            "step",
            "error",
            "previous_steps",
            "page",
        ]

    def test_healer_builds_verdict_value_objects(self, tmp_path: Path) -> None:
        provider = FakeProvider([FailureClassification(category="incurable", explanation="e", recommendation="r")])
        fixture = HealerFixture(provider, tmp_path)

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.healer.heal(fixture.failed_step, "err", [], FakePage())

        verdict = excinfo.value.verdict
        assert isinstance(verdict, FailureVerdict)  # the verdict object, not a string recommendation
        assert (verdict.category, verdict.explanation, verdict.recommendation) == ("incurable", "e", "r")


class HealerFixture:
    """Healer assembled with stubs and spies, plus the failed step under healing."""

    def __init__(
        self,
        provider: object,
        tmp_path: Path,
        real_generator: bool = False,
        limits: tuple[int, int] = (3, 2),
    ) -> None:
        self.recorder = RecorderHook()
        self.reporter = StepReporter(hooks=[self.recorder])
        self.config = Config(cache_root=str(tmp_path))
        self.cache = SpyCache()
        self.budgets = RunBudgets(*limits)
        self.failed_step = CachedStep(
            identity=StepIdentity(
                cache_key="login-flow",
                step_type="action",
                normalized_text="click the sign in button",
            ),
            code=FAILED_CODE,
            created_at="2026-09-07",
        )
        self.healed_step = CachedStep(
            identity=self.failed_step.identity,
            code=HEALED_CODE,
            created_at="2026-09-08",
        )
        if real_generator:
            self.generator = StepGenerator(self.config, provider, self.cache, self.budgets, self.reporter)
        else:
            self.generator = SpyGenerator(self.healed_step)
        self.healer = StepHealer(self.config, provider, self.generator, self.cache, self.budgets, self.reporter)


class TestStepHealerLogic:
    """Logic tests: classification branching, verdict reuse, event visibility, error propagation."""

    def test_heal_rot_regenerates_and_reports_healed(self, tmp_path: Path) -> None:
        provider = FakeProvider(
            [
                FailureClassification(
                    category="rot",
                    explanation="the button was renamed",
                    recommendation="refresh the cache",
                )
            ]
        )
        fixture = HealerFixture(provider, tmp_path)
        page = FakePage()

        healed = fixture.healer.heal(
            step=fixture.failed_step,
            error="element not found",
            previous_steps=["open the page"],
            page=page,
        )

        assert healed is fixture.healed_step
        assert len(fixture.generator.calls) == 1
        call = fixture.generator.calls[0]
        assert call["existing_code"] == FAILED_CODE
        assert call["previous_steps"] == ["open the page"]
        assert call["identity"] == fixture.failed_step.identity
        assert fixture.recorder.events == [
            ("on_healing_started", {"step_text": "click the sign in button", "category": "rot"}),
            ("on_healed", {"step_text": "click the sign in button", "explanation": "the button was renamed"}),
        ]
        assert fixture.cache.save_calls == []  # the cache is written by generator after successful execution

    def test_heal_sends_prompt_and_step_context_to_classification(self, tmp_path: Path) -> None:
        provider = FakeProvider([FailureClassification(category="rot", explanation="e", recommendation="r")])
        fixture = HealerFixture(provider, tmp_path)

        fixture.healer.heal(fixture.failed_step, "element not found", ["open the page"], FakePage())

        request = provider.classify_failure_calls[0]
        assert request["prompt"] == CLASSIFICATION_PROMPT
        assert request["step_text"] == "click the sign in button"
        assert request["code"] == FAILED_CODE
        assert request["error"] == "element not found"
        assert request["snapshot"] == "- snapshot"
        assert request["screenshot"] is None  # send_screenshots defaults to False

    def test_heal_attaches_screenshot_when_enabled(self, tmp_path: Path) -> None:
        provider = FakeProvider([FailureClassification(category="rot", explanation="e", recommendation="r")])
        recorder = RecorderHook()
        reporter = StepReporter(hooks=[recorder])
        config = Config(cache_root=str(tmp_path), send_screenshots=True)
        failed_step = CachedStep(
            identity=StepIdentity(cache_key="k", step_type="action", normalized_text="click submit"),
            code=FAILED_CODE,
            created_at="2026-09-07",
        )
        healer = StepHealer(
            config,
            provider,
            SpyGenerator(failed_step),
            SpyCache(),
            RunBudgets(3, 2),
            reporter,
        )

        healer.heal(failed_step, "err", [], FakePage())

        assert provider.classify_failure_calls[0]["screenshot"] == b"png"

    def test_heal_product_defect_carries_full_verdict(self, tmp_path: Path) -> None:
        provider = FakeProvider(
            [
                FailureClassification(
                    category="product_defect",
                    explanation="expected the total 100, observed 90",
                    recommendation="file a bug",
                )
            ]
        )
        fixture = HealerFixture(provider, tmp_path)

        with pytest.raises(ProductDefectError) as excinfo:
            fixture.healer.heal(fixture.failed_step, "text mismatch", ["open the page"], FakePage())

        rendered = str(excinfo.value)
        assert isinstance(excinfo.value.verdict, FailureVerdict)
        assert excinfo.value.verdict.recommendation == "file a bug"
        assert rendered.startswith("expected the total 100, observed 90")
        assert rendered.count("expected the total 100, observed 90") == 2  # message + verdict-render explanation
        assert "recommendation: file a bug" in rendered
        assert fixture.recorder.events == [
            ("on_healing_started", {"step_text": "click the sign in button", "category": "product_defect"})
        ]
        assert provider.generate_step_code_call_count == 0  # a product defect is not regenerated
        assert fixture.generator.calls == []
        assert fixture.cache.save_calls == []  # cache untouched

    def test_heal_incurable_carries_verdict_and_skips_regeneration(self, tmp_path: Path) -> None:
        provider = FakeProvider(
            [
                FailureClassification(
                    category="incurable",
                    explanation="the step text no longer matches reality",
                    recommendation="reword the step",
                )
            ]
        )
        fixture = HealerFixture(provider, tmp_path)

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.healer.heal(fixture.failed_step, "err", [], FakePage())

        rendered = str(excinfo.value)
        assert isinstance(excinfo.value, PrettyplayError)  # a single except at the suite boundary
        assert excinfo.value.reason == "the step text no longer matches reality"
        assert excinfo.value.verdict.category == "incurable"
        assert excinfo.value.recommendation == "reword the step"  # from the verdict, not the fallback
        assert rendered.endswith("recommendation: reword the step")
        assert provider.generate_step_code_call_count == 0  # healing requests no regeneration
        assert fixture.generator.calls == []
        assert fixture.cache.save_calls == []

    def test_heal_rot_exhaustion_reuses_verdict_without_second_request(self, tmp_path: Path) -> None:
        provider = FakeProvider(
            classifications=[
                FailureClassification(
                    category="rot",
                    explanation="the selector rotted",
                    recommendation="refresh the cache",
                )
            ],
            answers=[TIMEOUT_CODE],
        )
        fixture = HealerFixture(provider, tmp_path, real_generator=True, limits=(1, 1))

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.healer.heal(fixture.failed_step, "element not found", [], TimeoutPage())

        assert excinfo.value.verdict.category == "rot"  # the step 1 verdict, no second LLM request
        assert excinfo.value.reason.startswith("healing attempt budget exhausted")
        assert excinfo.value.error == "TimeoutError: waiting for the element timed out"  # the inner candidate
        assert isinstance(excinfo.value.__cause__, IncurableStepError)  # raise … from incurable
        assert provider.classify_failure_call_count == 1
        assert provider.generate_step_code_call_count == 1
        assert fixture.cache.save_calls == []  # no proven candidate — cache untouched

    def test_healer_and_strict_error_fields_end_to_end(self, tmp_path: Path) -> None:
        provider = FakeProvider(
            classifications=[
                FailureClassification(
                    category="product_defect",
                    explanation="the total is wrong",
                    recommendation="file a bug",
                )
            ]
        )
        fixture = HealerFixture(provider, tmp_path)

        with pytest.raises(ProductDefectError) as excinfo:
            fixture.healer.heal(fixture.failed_step, "TimeoutError: click timeout", [], FakePage())

        assert excinfo.value.error == "TimeoutError: click timeout"  # the full underlying error
        assert "error: TimeoutError: click timeout" in str(excinfo.value)

        rot_provider = FakeProvider(
            classifications=[
                FailureClassification(
                    category="rot",
                    explanation="the selector rotted",
                    recommendation="refresh the cache",
                )
            ],
            answers=[TIMEOUT_CODE],
        )
        rot_fixture = HealerFixture(rot_provider, tmp_path, real_generator=True, limits=(1, 1))

        with pytest.raises(IncurableStepError) as rot:
            rot_fixture.healer.heal(rot_fixture.failed_step, "element not found", [], TimeoutPage())

        assert rot.value.verdict is not None
        assert rot.value.verdict.category == "rot"  # the outer verdict is the rot classification verdict
        assert rot.value.error == "TimeoutError: waiting for the element timed out"  # the inner last candidate

    def test_classification_prompt_documents_user_instructions_input(self) -> None:
        # the USER INSTRUCTIONS input line sits right after the SCREENSHOT input line
        screenshot_input = CLASSIFICATION_PROMPT.index("- SCREENSHOT: an image of the page, when attached")
        user_instructions_input = CLASSIFICATION_PROMPT.index(
            "- USER INSTRUCTIONS: the project's classification guidance, when configured"
        )
        answer_line = CLASSIFICATION_PROMPT.index("Answer with exactly one line")
        assert screenshot_input < user_instructions_input < answer_line

    def test_heal_classification_unavailable_is_infrastructure_failure(self, tmp_path: Path) -> None:
        provider = FakeProvider([LLMUnavailableError("anthropic down")])
        fixture = HealerFixture(provider, tmp_path)

        with pytest.raises(LLMUnavailableError) as excinfo:
            fixture.healer.heal(fixture.failed_step, "err", [], FakePage())

        assert "anthropic" in str(excinfo.value)
        assert provider.classify_failure_call_count == 1
        assert fixture.generator.calls == []
        assert fixture.cache.save_calls == []

    def test_heal_preserves_fresh_verdict_from_regenerate_failed_check(self, tmp_path: Path) -> None:
        provider = FakeProvider(
            classifications=[
                FailureClassification(
                    category="rot",
                    explanation="the selector rotted",
                    recommendation="refresh the cache",
                ),
                FailureClassification(
                    category="product_defect",
                    explanation="the banner is genuinely missing",
                    recommendation="file a bug",
                ),
            ],
            answers=[CHECK_CODE],
        )
        fixture = HealerFixture(provider, tmp_path, real_generator=True)

        with pytest.raises(ProductDefectError) as excinfo:
            fixture.healer.heal(fixture.failed_step, "element not found", [], CheckFailingPage())

        # the fresh failed-check verdict wins; the except branch never rewrites it
        assert excinfo.value.verdict.category == "product_defect"
        assert excinfo.value.message == "the banner is genuinely missing"  # the verdict explanation
        assert excinfo.value.error == "banner missing"  # the full check text, no prefix
        assert provider.classify_failure_call_count == 2  # healer classification + a fresh one in regeneration
        assert fixture.cache.save_calls == []

    def test_heal_preserves_fresh_incurable_verdict_from_regenerate_failed_check(self, tmp_path: Path) -> None:
        """A fresh failed-check IncurableStepError is re-raised untouched (not the rot verdict)."""
        provider = FakeProvider(
            classifications=[
                FailureClassification(
                    category="rot",
                    explanation="the selector rotted",
                    recommendation="refresh the cache",
                ),
                FailureClassification(
                    category="incurable",
                    explanation="the banner step is ambiguous",
                    recommendation="reword the step",
                ),
            ],
            answers=[CHECK_CODE],
        )
        fixture = HealerFixture(provider, tmp_path, real_generator=True)

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.healer.heal(fixture.failed_step, "element not found", [], CheckFailingPage())

        # the fresh regeneration classification verdict — the "raise" branch, not overwritten by the rot verdict
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "incurable"
        assert excinfo.value.verdict.explanation == "the banner step is ambiguous"
        assert excinfo.value.reason.startswith("candidate check failed")
        assert provider.classify_failure_call_count == 2
        assert fixture.cache.save_calls == []


class TestEngineCellFacade:
    """The engine cell facade is complete after the healer joins it."""

    def test_engine_facade_reexports_all_entities(self) -> None:
        from prettyplay import engine  # noqa: PLC0415 — cell facade check

        assert sorted(engine.__all__) == ["StepGenerator", "StepHealer", "classify_step_failure", "run_step_code"]


def test_real_cache_spy_not_needed_for_healer(tmp_path: Path) -> None:
    """The healer composes over the real cache cell unchanged: a smoke wiring check."""
    recorder = RecorderHook()
    reporter = StepReporter(hooks=[recorder])
    config = Config(cache_root=str(tmp_path))
    cache = StepCache(config, None, reporter)
    failed_step = CachedStep(
        identity=StepIdentity(cache_key="k", step_type="action", normalized_text="click submit"),
        code=FAILED_CODE,
        created_at="2026-09-07",
    )
    provider = FakeProvider([FailureClassification(category="rot", explanation="e", recommendation="r")])
    healer = StepHealer(config, provider, SpyGenerator(failed_step), cache, RunBudgets(3, 2), reporter)

    healed = healer.heal(failed_step, "err", [], FakePage())

    assert healed.code == FAILED_CODE  # the generator stub returned the same object
    assert healer._generator.calls[0]["existing_code"] == FAILED_CODE  # regenerate actually requested
    assert cache.load(failed_step.identity) is None  # cache not written directly by the healer
