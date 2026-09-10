"""Tests for the StepExecutor of the prettyplay root cell."""

import inspect
import logging
from pathlib import Path

import pytest
from prettyplay import StepExecutor
from prettyplay.cache import CachedStep, RunBudgets, StepCache, StepIdentity, normalize_step_text
from prettyplay.config import Config
from prettyplay.failures import FailureVerdict, IncurableStepError, LLMUnavailableError, ProductDefectError
from prettyplay.llm import FailureClassification, LLMProvider
from prettyplay.reporting import StepHooks, StepReporter

CACHED_CODE = "def step(page) -> None:\n    page.open('https://example.com')\n"
BROKEN_CODE = "def step(page) -> None:\n    page.find_by_role('button', name='Войти').click()\n"


class FakePage:
    """Fake page facade boundary: recorded calls, scriptable lookup failure, snapshot."""

    def __init__(self, lookup_error: Exception | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._lookup_error = lookup_error if lookup_error is not None else AssertionError("element not found")

    def open(self, url: str) -> None:
        self.calls.append(("open", url))

    def find_by_role(self, role: str, name: str) -> object:
        self.calls.append(("find_by_role", role, name))
        raise self._lookup_error

    def aria_snapshot(self) -> str:
        return "- button 'Войти'"


class RecordingGenerator:
    """Stub generation engine: records generate requests, returns a canned step."""

    def __init__(self, step: CachedStep | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.step = step

    def generate(
        self,
        identity: StepIdentity,
        step_text: str,
        previous_steps: list[str],
        page: FakePage,
    ) -> CachedStep | None:
        self.calls.append(
            {
                "identity": identity,
                "step_text": step_text,
                "previous_steps": list(previous_steps),  # snapshot: the live list grows after the call
                "page": page,
            }
        )
        return self.step


class RaisingGenerator:
    """Stub generation engine whose generate raises the scripted failure."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def generate(
        self,
        identity: StepIdentity,
        step_text: str,
        previous_steps: list[str],
        page: FakePage,
    ) -> CachedStep:
        self.calls += 1
        raise self.error


class RecordingHealer:
    """Stub healing engine: records heal requests, returns a canned healed step."""

    def __init__(self, step: CachedStep | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.step = step

    def heal(self, step: CachedStep, error: str, previous_steps: list[str], page: FakePage) -> CachedStep | None:
        self.calls.append(
            {
                "step": step,
                "error": error,
                "previous_steps": list(previous_steps),  # snapshot: the live list grows after the call
                "page": page,
            }
        )
        return self.step


class RaisingHealer:
    """Stub healing engine whose heal raises the scripted failure."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def heal(self, step: CachedStep, error: str, previous_steps: list[str], page: FakePage) -> CachedStep:
        self.calls += 1
        raise self.error


class ScriptedProvider(LLMProvider):
    """Stub LLM boundary: a scripted classification verdict, recorded requests, no generation."""

    def __init__(self, verdict: FailureClassification | None = None) -> None:
        self.verdict = verdict
        self.generation_calls = 0
        self.classification_calls = 0

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str = "",
        user_instructions: str = "",
        step_text: str = "",
        previous_steps: list[str] | None = None,
        snapshot: str = "",
        screenshot: bytes | None = None,
        page_api: str = "",
        existing_code: str | None = None,
        error: str | None = None,
    ) -> str:
        self.generation_calls += 1
        raise AssertionError("provider must not generate: strict mode replays cached code only")

    def classify_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str = "",
        user_instructions: str = "",
        step_text: str = "",
        code: str = "",
        error: str = "",
        snapshot: str = "",
        screenshot: bytes | None = None,
    ) -> FailureClassification:
        self.classification_calls += 1
        return self.verdict


class UnavailableProvider(LLMProvider):
    """Stub LLM boundary failing every classification as an infrastructure outage."""

    def __init__(self) -> None:
        self.generation_calls = 0

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str = "",
        user_instructions: str = "",
        step_text: str = "",
        previous_steps: list[str] | None = None,
        snapshot: str = "",
        screenshot: bytes | None = None,
        page_api: str = "",
        existing_code: str | None = None,
        error: str | None = None,
    ) -> str:
        self.generation_calls += 1
        raise AssertionError("provider must not generate: strict mode replays cached code only")

    def classify_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str = "",
        user_instructions: str = "",
        step_text: str = "",
        code: str = "",
        error: str = "",
        snapshot: str = "",
        screenshot: bytes | None = None,
    ) -> FailureClassification:
        raise LLMUnavailableError("llm unavailable: openai request failed")


class RecorderHook(StepHooks):
    """Hook recording step cycle events into a shared ``events`` list for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str | int]]] = []

    def on_step_started(self, step_text: str, step_type: str) -> None:
        self.events.append(("on_step_started", {"step_text": step_text, "step_type": step_type}))

    def on_step_passed(self, step_text: str, step_type: str) -> None:
        self.events.append(("on_step_passed", {"step_text": step_text, "step_type": step_type}))

    def on_step_failed(self, step_text: str, step_type: str, error: str) -> None:
        self.events.append(("on_step_failed", {"step_text": step_text, "step_type": step_type, "error": error}))

    def on_step_verdict(self, step_text: str, category: str, explanation: str, recommendation: str) -> None:
        self.events.append(
            (
                "on_step_verdict",
                {
                    "step_text": step_text,
                    "category": category,
                    "explanation": explanation,
                    "recommendation": recommendation,
                },
            )
        )


class ExecutorFixture:
    """Executor assembled on a tmp cache with recording visibility, for logic tests."""

    def __init__(  # noqa: PLR0913, PLR0917 — the assembly inputs of the fixture
        self,
        tmp_path: Path,
        generator: object,
        healer: object,
        cache_key: str = "login-flow",
        config: Config | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        self.recorder = RecorderHook()
        self.reporter = StepReporter(hooks=[self.recorder])
        self.config = config if config is not None else Config(cache_root=str(tmp_path))
        self.cache = StepCache(self.config, None, self.reporter)
        self.budgets = RunBudgets(3, 2)
        self.generator = generator
        self.healer = healer
        self.provider = provider if provider is not None else ScriptedProvider()
        self.executor = StepExecutor(
            cache_key,
            self.cache,
            generator,
            healer,
            self.budgets,
            self.reporter,
            self.config,
            self.provider,
        )


def events_named(recorder: RecorderHook, name: str) -> list[dict[str, str | int]]:
    """Collect the payloads of the recorded events with the given name."""
    return [payload for event, payload in recorder.events if event == name]


def seed_cached_step(
    fixture: ExecutorFixture,
    step_text: str,
    code: str = BROKEN_CODE,
    step_type: str = "action",
) -> None:
    """Save a cached step under the fixture cache key, so a run takes the cache-hit path."""
    identity = StepIdentity(
        cache_key="login-flow",
        step_type=step_type,
        normalized_text=normalize_step_text(step_text),
    )
    fixture.cache.save(CachedStep(identity=identity, code=code, created_at="2026-09-08"))


def strict_fixture(
    tmp_path: Path,
    generator: object,
    healer: object,
    provider: LLMProvider,
) -> ExecutorFixture:
    """Assemble an executor in strict replay-only mode over the given LLM boundary."""
    return ExecutorFixture(
        tmp_path,
        generator,
        healer,
        config=Config(cache_root=str(tmp_path), strict=True),
        provider=provider,
    )


class TestStepExecutorContract:
    """Contract tests: facade import, constructor and method signatures."""

    def test_step_executor_is_importable_from_facade(self) -> None:
        assert isinstance(StepExecutor, type)

    def test_constructor_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(StepExecutor.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == [
            "cache_key",
            "cache",
            "generator",
            "healer",
            "budgets",
            "reporter",
            "config",
            "provider",
        ]

    def test_execute_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(StepExecutor.execute).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["step_text", "step_type", "page"]

    @pytest.mark.parametrize(
        "failure",
        [
            ProductDefectError(
                "open the dashboard",
                "expected the total 100, observed 90",
                "",
                FailureVerdict("product_defect", "the banner is gone", "file a bug"),
            ),
            IncurableStepError(
                "open the dashboard",
                "the step text no longer matches reality",
                "",
                FailureVerdict("incurable", "the step is ambiguous", "reword the step"),
            ),
        ],
        ids=["product-defect", "incurable"],
    )
    def test_execute_emits_verdict_event_for_verdict_carrying_errors(self, tmp_path: Path, failure: Exception) -> None:
        healer = RaisingHealer(failure)
        fixture = ExecutorFixture(tmp_path, RecordingGenerator(), healer)
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="open the dashboard")
        fixture.cache.save(CachedStep(identity=identity, code=BROKEN_CODE, created_at="2026-09-08"))

        with pytest.raises(type(failure)):
            fixture.executor.execute("open the dashboard", "action", FakePage())

        verdict_events = events_named(fixture.recorder, "on_step_verdict")
        assert len(verdict_events) == 1
        assert verdict_events[0] == {
            "step_text": "open the dashboard",
            "category": failure.verdict.category,
            "explanation": failure.verdict.explanation,
            "recommendation": failure.verdict.recommendation,
        }

    def test_execute_emits_no_verdict_event_for_llm_unavailable(self, tmp_path: Path) -> None:
        healer = RaisingHealer(LLMUnavailableError("llm unavailable: openai request failed"))
        fixture = ExecutorFixture(tmp_path, RecordingGenerator(), healer)
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="open the dashboard")
        fixture.cache.save(CachedStep(identity=identity, code=BROKEN_CODE, created_at="2026-09-08"))

        with pytest.raises(LLMUnavailableError):
            fixture.executor.execute("open the dashboard", "action", FakePage())

        assert not events_named(fixture.recorder, "on_step_verdict")


class TestStepExecutorLogic:
    """Logic tests: hit and miss paths, scenario context, failures, healing delegation."""

    def test_hit_path_runs_cached_code_without_engines(self, tmp_path: Path) -> None:
        generator = RecordingGenerator()
        healer = RecordingHealer()
        fixture = ExecutorFixture(tmp_path, generator, healer)
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="открыть страницу")
        fixture.cache.save(CachedStep(identity=identity, code=CACHED_CODE, created_at="2026-09-07"))
        page = FakePage()

        # step with different case and spacing normalizes to the same address
        fixture.executor.execute("  Открыть   страницу ", "action", page)

        assert page.calls == [("open", "https://example.com")]
        assert generator.calls == []
        assert healer.calls == []
        assert events_named(fixture.recorder, "on_step_started") == [
            {"step_text": "  Открыть   страницу ", "step_type": "action"}
        ]
        assert events_named(fixture.recorder, "on_step_passed") == [
            {"step_text": "  Открыть   страницу ", "step_type": "action"}
        ]
        assert not events_named(fixture.recorder, "on_step_failed")

    def test_miss_path_generates_with_growing_scenario_context(self, tmp_path: Path) -> None:
        generator = RecordingGenerator()
        fixture = ExecutorFixture(tmp_path, generator, RecordingHealer())
        page = FakePage()

        fixture.executor.execute("шаг один", "action", page)
        fixture.executor.execute("шаг два", "action", page)

        assert len(generator.calls) == 2
        assert generator.calls[0]["previous_steps"] == []
        assert generator.calls[0]["step_text"] == "шаг один"
        assert generator.calls[0]["identity"] == StepIdentity(
            cache_key="login-flow", step_type="action", normalized_text=normalize_step_text("шаг один")
        )
        assert generator.calls[1]["previous_steps"] == ["шаг один"]
        passed = events_named(fixture.recorder, "on_step_passed")
        assert len(passed) == 2
        assert not events_named(fixture.recorder, "on_step_failed")

    def test_executor_reports_verdict_after_failed(self, tmp_path: Path) -> None:
        failure = IncurableStepError("s", "r", "", FailureVerdict("incurable", "e", "rec"))
        healer = RaisingHealer(failure)
        fixture = ExecutorFixture(tmp_path, RecordingGenerator(), healer)
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="s")
        fixture.cache.save(CachedStep(identity=identity, code=BROKEN_CODE, created_at="2026-09-08"))

        with pytest.raises(IncurableStepError):
            fixture.executor.execute("s", "action", FakePage())

        names = [event for event, _payload in fixture.recorder.events]
        assert names.index("on_step_failed") < names.index("on_step_verdict")
        assert events_named(fixture.recorder, "on_step_verdict") == [
            {"step_text": "s", "category": "incurable", "explanation": "e", "recommendation": "rec"}
        ]

    def test_verdict_event_absent_without_verdict(self, tmp_path: Path) -> None:
        healer = RaisingHealer(LLMUnavailableError("down"))
        fixture = ExecutorFixture(tmp_path, RecordingGenerator(), healer)
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="s")
        fixture.cache.save(CachedStep(identity=identity, code=BROKEN_CODE, created_at="2026-09-08"))

        with pytest.raises(LLMUnavailableError):
            fixture.executor.execute("s", "action", FakePage())

        assert "on_step_verdict" not in [event for event, _ in fixture.recorder.events]
        assert "on_step_failed" in [event for event, _ in fixture.recorder.events]

    def test_verdict_event_logged_at_info(self, tmp_path: Path, caplog) -> None:
        failure = IncurableStepError("s", "r", "", FailureVerdict("incurable", "e", "rec"))
        healer = RaisingHealer(failure)
        fixture = ExecutorFixture(tmp_path, RecordingGenerator(), healer)
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="s")
        fixture.cache.save(CachedStep(identity=identity, code=BROKEN_CODE, created_at="2026-09-08"))
        page = FakePage()

        with caplog.at_level(logging.INFO, logger="prettyplay"), pytest.raises(IncurableStepError):
            fixture.executor.execute("s", "action", page)

        verdict_records = [record for record in caplog.records if record.msg == "on_step_verdict"]
        assert len(verdict_records) == 1
        assert verdict_records[0].levelno == logging.INFO

    def test_generator_failure_reports_and_propagates_by_kind(self, tmp_path: Path) -> None:
        failure = IncurableStepError("шаг", "generation attempt budget exhausted")
        generator = RaisingGenerator(failure)
        fixture = ExecutorFixture(tmp_path, generator, RecordingHealer())
        page = FakePage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.executor.execute("шаг", "action", page)

        assert excinfo.value.reason == "generation attempt budget exhausted"
        assert events_named(fixture.recorder, "on_step_failed") == [
            {
                "step_text": "шаг",
                "step_type": "action",
                "error": str(failure),  # the render, verbatim — never re-composed
            }
        ]
        assert not events_named(fixture.recorder, "on_step_passed")
        assert fixture.executor._scenario == []  # failure does not grow the scenario context

    def test_failed_step_error_is_the_full_render_uncut(self, tmp_path: Path) -> None:
        generator = RaisingGenerator(ValueError(f"first {'x' * 300}\nsecond line"))
        fixture = ExecutorFixture(tmp_path, generator, RecordingHealer())
        page = FakePage()

        with pytest.raises(ValueError, match="first"):
            fixture.executor.execute("шаг", "action", page)

        failed = events_named(fixture.recorder, "on_step_failed")
        assert len(failed) == 1
        error = failed[0]["error"]
        assert error == f"first {'x' * 300}\nsecond line"  # str(error): the full text
        assert len(error) > 200  # no truncation at the old 200-char cut
        assert "second line" in error

    def test_messageless_cached_failure_flows_to_healing_without_crash(self, tmp_path: Path) -> None:
        generator = RecordingGenerator()
        healer = RecordingHealer()
        fixture = ExecutorFixture(tmp_path, generator, healer)
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="проверить")
        bare_assert_code = "def step(page) -> None:\n    assert 1 == 2\n"  # assert with no message
        fixture.cache.save(CachedStep(identity=identity, code=bare_assert_code, created_at="2026-09-08"))
        page = FakePage()

        fixture.executor.execute("проверить", "action", page)

        assert len(healer.calls) == 1
        assert healer.calls[0]["error"] == ""  # empty failure description, not an IndexError
        assert not events_named(fixture.recorder, "on_step_failed")  # healed — step passed

    def test_messageless_generator_failure_reports_empty_error(self, tmp_path: Path) -> None:
        generator = RaisingGenerator(AssertionError())  # bare assert: str(exc) == ''
        fixture = ExecutorFixture(tmp_path, generator, RecordingHealer())
        page = FakePage()

        with pytest.raises(AssertionError):
            fixture.executor.execute("шаг", "action", page)

        failed = events_named(fixture.recorder, "on_step_failed")
        assert failed == [{"step_text": "шаг", "step_type": "action", "error": ""}]

    def test_cached_failure_heals_with_scenario_context(self, tmp_path: Path) -> None:
        generator = RecordingGenerator()
        healed_step = CachedStep(
            identity=StepIdentity(cache_key="login-flow", step_type="action", normalized_text="нажать войти"),
            code=CACHED_CODE,
            created_at="2026-09-08",
        )
        healer = RecordingHealer(healed_step)
        fixture = ExecutorFixture(tmp_path, generator, healer)
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="нажать войти")
        fixture.cache.save(CachedStep(identity=identity, code=BROKEN_CODE, created_at="2026-09-07"))
        page = FakePage()

        fixture.executor.execute("шаг один", "action", page)
        fixture.executor.execute("нажать Войти", "action", page)

        assert len(healer.calls) == 1
        assert healer.calls[0]["step"].code.rstrip("\n") == BROKEN_CODE.rstrip("\n")  # serializer appends \n
        assert "element not found" in healer.calls[0]["error"]
        assert healer.calls[0]["previous_steps"] == ["шаг один"]
        assert healer.calls[0]["page"] is page
        assert len(generator.calls) == 1  # generation for the first step only, healing for the second
        assert len(events_named(fixture.recorder, "on_step_passed")) == 2
        assert not events_named(fixture.recorder, "on_step_failed")
        assert fixture.executor._scenario == ["шаг один", "нажать Войти"]

    @pytest.mark.parametrize(
        "failure",
        [
            ProductDefectError("нажать войти", "ожидание не оправдалось"),
            IncurableStepError("нажать войти", "текст шага не соответствует реальности"),
            LLMUnavailableError("llm unavailable: openai request failed"),
        ],
    )
    def test_healer_failure_propagates_by_kind_with_event(self, tmp_path: Path, failure: Exception) -> None:
        # no verdict — only on_step_failed; no verdict event
        healer = RaisingHealer(failure)
        fixture = ExecutorFixture(tmp_path, RecordingGenerator(), healer)
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="нажать войти")
        fixture.cache.save(CachedStep(identity=identity, code=BROKEN_CODE, created_at="2026-09-07"))
        page = FakePage()

        with pytest.raises(type(failure)) as excinfo:
            fixture.executor.execute("нажать Войти", "action", page)

        assert excinfo.value is failure  # re-raised as the same object, unwrapped
        assert [event for event, _payload in fixture.recorder.events] == ["on_step_started", "on_step_failed"]
        assert not events_named(fixture.recorder, "on_step_passed")
        assert fixture.executor._scenario == []  # failure does not grow the scenario context

    def test_executor_events_carry_full_render_and_verdict_fields(self, tmp_path: Path) -> None:
        verdict = FailureVerdict("product_defect", "expl", "rec")
        failure = ProductDefectError("step", "msg", "err-text", verdict)
        healer = RaisingHealer(failure)
        fixture = ExecutorFixture(tmp_path, RecordingGenerator(), healer)
        seed_cached_step(fixture, "step")
        page = FakePage()

        with pytest.raises(ProductDefectError) as excinfo:
            fixture.executor.execute("step", "action", page)

        render = str(excinfo.value)
        assert "---" in render  # the full structured render
        assert "recommendation:" in render
        assert events_named(fixture.recorder, "on_step_failed") == [
            {"step_text": "step", "step_type": "action", "error": render}  # str(exc), never re-composed
        ]
        assert events_named(fixture.recorder, "on_step_verdict") == [
            {"step_text": "step", "category": "product_defect", "explanation": "expl", "recommendation": "rec"}
        ]


class TestStepExecutorStrictMode:
    """Logic tests: the strict replay-only cycle — cached code only, classification at most."""

    def test_executor_strict_cache_miss_raises_without_generation(self, tmp_path: Path) -> None:
        generator = RecordingGenerator()
        healer = RecordingHealer()
        fixture = strict_fixture(tmp_path, generator, healer, ScriptedProvider())
        page = FakePage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.executor.execute("Нажать «Войти»", "action", page)

        exc = excinfo.value
        assert exc.reason == "strict mode forbids generation — the step is missing from the cache"
        assert exc.error == ""
        assert exc.verdict is None
        assert generator.calls == []  # strict never delegates to the engines
        assert healer.calls == []
        assert fixture.budgets._generation_used == {}  # generation budget never consumed
        assert "step: Нажать «Войти»" in str(exc)
        assert "recommendation:" in str(exc)  # the render-only fallback verdict
        assert events_named(fixture.recorder, "on_step_failed") == [
            {"step_text": "Нажать «Войти»", "step_type": "action", "error": str(exc)}  # one render
        ]
        names = [event for event, _payload in fixture.recorder.events]
        assert "on_generation_started" not in names
        assert "on_healing_started" not in names

    @pytest.mark.parametrize(
        ("category", "expected"),
        [
            ("product_defect", ProductDefectError),
            ("rot", IncurableStepError),
            ("incurable", IncurableStepError),
        ],
        ids=["product-defect", "rot", "incurable"],
    )
    def test_executor_strict_failed_cached_step_classifies_only(
        self, tmp_path: Path, category: str, expected: type[Exception]
    ) -> None:
        generator = RecordingGenerator()
        healer = RecordingHealer()
        provider = ScriptedProvider(
            verdict=FailureClassification(category=category, explanation="expl", recommendation="rec")
        )
        fixture = strict_fixture(tmp_path, generator, healer, provider)
        seed_cached_step(fixture, "нажать войти", step_type="assertion")
        page = FakePage()

        with pytest.raises(expected) as excinfo:
            fixture.executor.execute("нажать Войти", "assertion", page)

        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == category
        assert provider.generation_calls == 0  # the classification is the only LLM call
        assert provider.classification_calls == 1
        assert generator.calls == []  # engines never invoked
        assert healer.calls == []
        assert fixture.budgets._healing_used == {}  # healing budget never consumed
        assert [event for event, _payload in fixture.recorder.events] == [
            "on_step_started",
            "on_step_failed",
            "on_step_verdict",
        ]

    def test_executor_strict_error_field_full_text_by_exception_kind(self, tmp_path: Path) -> None:
        """The error field carries the typed prefix for action errors, none for assertion checks."""
        provider = ScriptedProvider(
            verdict=FailureClassification(category="product_defect", explanation="expl", recommendation="rec")
        )
        fixture = strict_fixture(tmp_path, RecordingGenerator(), RecordingHealer(), provider)
        seed_cached_step(fixture, "нажать войти", step_type="assertion")

        timing_out_page = FakePage(TimeoutError("locator.click: Timeout 30000ms exceeded"))
        with pytest.raises(ProductDefectError) as typed:
            fixture.executor.execute("нажать Войти", "assertion", timing_out_page)

        assert typed.value.error == "TimeoutError: locator.click: Timeout 30000ms exceeded"

        with pytest.raises(ProductDefectError) as bare:
            fixture.executor.execute("нажать Войти", "assertion", FakePage())

        assert bare.value.error == "element not found"  # no "AssertionError" prefix
        assert "AssertionError" not in bare.value.error

    @pytest.mark.parametrize(
        ("step_type", "expected", "reason_field"),
        [
            ("assertion", ProductDefectError, "message"),
            ("action", IncurableStepError, "reason"),
        ],
        ids=["assertion", "action"],
    )
    def test_executor_strict_llm_unavailable_skips_verdict_quietly(
        self,
        tmp_path: Path,
        step_type: str,
        expected: type[Exception],
        reason_field: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        provider = UnavailableProvider()
        fixture = strict_fixture(tmp_path, RecordingGenerator(), RecordingHealer(), provider)
        seed_cached_step(fixture, "нажать войти", step_type=step_type)
        page = FakePage()

        with caplog.at_level(logging.WARNING, logger="prettyplay"), pytest.raises(expected) as excinfo:
            fixture.executor.execute("нажать Войти", step_type, page)

        exc = excinfo.value
        assert exc.verdict is None  # the failure never waits for a verdict
        assert getattr(exc, reason_field) == "the step failed in strict mode without an llm verdict"
        assert exc.error == "element not found"  # the full failure text travels on
        assert not events_named(fixture.recorder, "on_step_verdict")
        skipped = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert [record.message for record in skipped] == ["verdict skipped: llm unavailable"]
        assert provider.generation_calls == 0

    def test_incurable_fallback_verdict_never_fires_the_event(self, tmp_path: Path) -> None:
        fixture = strict_fixture(tmp_path, RecordingGenerator(), RecordingHealer(), ScriptedProvider())
        page = FakePage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.executor.execute("шаг", "action", page)  # strict cache miss

        failed = events_named(fixture.recorder, "on_step_failed")
        assert "recommendation: reword the step or refresh the cache" in failed[0]["error"]
        assert not events_named(fixture.recorder, "on_step_verdict")
        assert excinfo.value.verdict is None  # render-only fallback: no verdict event for it
