"""Tests for the StepHealer of the prettyplay.engine cell."""

import inspect
from pathlib import Path

import pytest
from prettyplay.cache import CachedStep, RunBudgets, StepCache, StepIdentity
from prettyplay.config import Config
from prettyplay.engine import StepHealer
from prettyplay.engine.generator import CLASSIFICATION_PROMPT
from prettyplay.failures import (
    IncurableStepError,
    LlmUnavailableError,
    PrettyplayError,
    ProductDefectError,
)
from prettyplay.llm import FailureClassification
from prettyplay.reporting import StepHooks, StepReporter

FAILED_CODE = "def step(page) -> None:\n    page.find_by_role('button', name='Войти').click()\n"
HEALED_CODE = "def step(page) -> None:\n    page.find_by_role('button', name='Sign in').click()\n"


class FakePage:
    """Fake page facade boundary: snapshot for the classification request."""

    def aria_snapshot(self) -> str:
        return "- snapshot"

    def screenshot(self) -> bytes:
        return b"png"


class ClassificationProvider:
    """Stub provider boundary returning one scripted verdict with recorded requests."""

    def __init__(self, verdict: FailureClassification) -> None:
        self.verdict = verdict
        self.calls: list[dict[str, object]] = []

    def classify_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        step_text: str,
        code: str,
        error: str,
        snapshot: str,
        screenshot: bytes | None,
    ) -> FailureClassification:
        self.calls.append(
            {
                "prompt": prompt,
                "step_text": step_text,
                "code": code,
                "error": error,
                "snapshot": snapshot,
                "screenshot": screenshot,
            }
        )
        return self.verdict


class UnavailableProvider:
    """Stub provider whose service is down: classification raises LlmUnavailableError."""

    def __init__(self) -> None:
        self.calls = 0

    def classify_failure(self, **_kwargs: object) -> FailureClassification:
        self.calls += 1
        raise LlmUnavailableError("llm unavailable: openai request failed")


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
    """Contract tests: facade import, constructor and method signatures."""

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


class HealerFixture:
    """Healer assembled with stubs and spies, plus the failed step under healing."""

    def __init__(self, provider: object, tmp_path: Path) -> None:
        self.recorder = RecorderHook()
        self.reporter = StepReporter(hooks=[self.recorder])
        self.config = Config(cache_root=str(tmp_path))
        self.cache = SpyCache()
        self.budgets = RunBudgets(3, 2)
        self.failed_step = CachedStep(
            identity=StepIdentity(cache_key="login-flow", step_type="action", normalized_text="нажать войти"),
            code=FAILED_CODE,
            created_at="2026-09-07",
        )
        self.healed_step = CachedStep(
            identity=self.failed_step.identity,
            code=HEALED_CODE,
            created_at="2026-09-08",
        )
        self.generator = SpyGenerator(self.healed_step)
        self.healer = StepHealer(self.config, provider, self.generator, self.cache, self.budgets, self.reporter)


class TestStepHealerLogic:
    """Logic tests: classification branching, event visibility, error propagation."""

    def test_heal_rot_regenerates_and_reports_healed(self, tmp_path: Path) -> None:
        provider = ClassificationProvider(
            FailureClassification(category="rot", explanation="кнопка переименована", recommendation="проверить шаг")
        )
        fixture = HealerFixture(provider, tmp_path)
        page = FakePage()

        healed = fixture.healer.heal(
            step=fixture.failed_step,
            error="element not found",
            previous_steps=["открыть"],
            page=page,
        )

        assert healed is fixture.healed_step
        assert len(fixture.generator.calls) == 1
        call = fixture.generator.calls[0]
        assert call["existing_code"] == FAILED_CODE
        assert call["previous_steps"] == ["открыть"]
        assert call["identity"] == fixture.failed_step.identity
        assert fixture.recorder.events == [
            ("on_healing_started", {"step_text": "нажать войти", "category": "rot"}),
            ("on_healed", {"step_text": "нажать войти", "explanation": "кнопка переименована"}),
        ]
        assert fixture.cache.save_calls == []  # кэш пишет generator после успешного исполнения

    def test_heal_sends_prompt_and_step_context_to_classification(self, tmp_path: Path) -> None:
        provider = ClassificationProvider(FailureClassification(category="rot", explanation="e", recommendation="r"))
        fixture = HealerFixture(provider, tmp_path)

        fixture.healer.heal(fixture.failed_step, "element not found", ["открыть"], FakePage())

        request = provider.calls[0]
        assert request["prompt"] == CLASSIFICATION_PROMPT
        assert request["step_text"] == "нажать войти"
        assert request["code"] == FAILED_CODE
        assert request["error"] == "element not found"
        assert request["snapshot"] == "- snapshot"
        assert request["screenshot"] is None  # send_screenshots по умолчанию False

    def test_heal_attaches_screenshot_when_enabled(self, tmp_path: Path) -> None:
        provider = ClassificationProvider(FailureClassification(category="rot", explanation="e", recommendation="r"))
        recorder = RecorderHook()
        reporter = StepReporter(hooks=[recorder])
        config = Config(cache_root=str(tmp_path), send_screenshots=True)
        failed_step = CachedStep(
            identity=StepIdentity(cache_key="k", step_type="action", normalized_text="шаг"),
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

        assert provider.calls[0]["screenshot"] == b"png"

    def test_heal_provider_unavailable_propagates(self, tmp_path: Path) -> None:
        provider = UnavailableProvider()
        fixture = HealerFixture(provider, tmp_path)

        with pytest.raises(LlmUnavailableError):
            fixture.healer.heal(fixture.failed_step, "err", [], FakePage())

        assert provider.calls == 1
        assert fixture.generator.calls == []
        assert fixture.cache.save_calls == []

    def test_heal_product_defect_raises_and_keeps_cache(self, tmp_path: Path) -> None:
        provider = ClassificationProvider(
            FailureClassification(
                category="product_defect", explanation="ожидание не оправдалось", recommendation="чинить продукт"
            )
        )
        fixture = HealerFixture(provider, tmp_path)

        with pytest.raises(ProductDefectError) as excinfo:
            fixture.healer.heal(fixture.failed_step, "text mismatch", ["шаг"], FakePage())

        assert isinstance(excinfo.value, PrettyplayError)  # единый except на границе suite
        assert fixture.generator.calls == []
        assert fixture.cache.save_calls == []
        assert fixture.recorder.events == [
            ("on_healing_started", {"step_text": "нажать войти", "category": "product_defect"})
        ]

    def test_heal_incurable_carries_verdict_fields(self, tmp_path: Path) -> None:
        provider = ClassificationProvider(
            FailureClassification(
                category="incurable",
                explanation="текст шага не соответствует реальности",
                recommendation="переформулируйте шаг",
            )
        )
        fixture = HealerFixture(provider, tmp_path)

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.healer.heal(fixture.failed_step, "err", [], FakePage())

        rendered = str(excinfo.value)
        assert excinfo.value.reason == "текст шага не соответствует реальности"
        assert excinfo.value.recommendation == "переформулируйте шаг"
        assert "нажать войти" in rendered
        assert "текст шага не соответствует реальности" in rendered
        assert "переформулируйте шаг" in rendered
        assert fixture.generator.calls == []
        assert fixture.cache.save_calls == []


class TestEngineCellFacade:
    """The engine cell facade is complete after the healer joins it."""

    def test_engine_facade_reexports_all_entities(self) -> None:
        from prettyplay import engine  # noqa: PLC0415 — проверка фасада клетки

        assert sorted(engine.__all__) == ["StepGenerator", "StepHealer", "run_step_code"]


def test_real_cache_spy_not_needed_for_healer(tmp_path: Path) -> None:
    """The healer composes over the real cache cell unchanged: a smoke wiring check."""
    recorder = RecorderHook()
    reporter = StepReporter(hooks=[recorder])
    config = Config(cache_root=str(tmp_path))
    cache = StepCache(config, None, reporter)
    failed_step = CachedStep(
        identity=StepIdentity(cache_key="k", step_type="action", normalized_text="шаг"),
        code=FAILED_CODE,
        created_at="2026-09-07",
    )
    provider = ClassificationProvider(FailureClassification(category="rot", explanation="e", recommendation="r"))
    healer = StepHealer(config, provider, SpyGenerator(failed_step), cache, RunBudgets(3, 2), reporter)

    healed = healer.heal(failed_step, "err", [], FakePage())

    assert healed.code == FAILED_CODE  # заглушка генератора вернула тот же объект
    assert healer._generator.calls[0]["existing_code"] == FAILED_CODE  # regenerate реально запрошен
    assert cache.load(failed_step.identity) is None  # кэш напрямую healer'ом не писался
