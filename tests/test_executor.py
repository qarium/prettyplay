"""Tests for the StepExecutor of the prettyplay root cell."""

import inspect
import logging
from pathlib import Path

import pytest
from prettyplay import StepExecutor
from prettyplay.cache import CachedStep, RunBudgets, StepCache, StepIdentity, normalize_step_text
from prettyplay.config import Config
from prettyplay.engine.text import first_line_short
from prettyplay.failures import FailureVerdict, IncurableStepError, LLMUnavailableError, ProductDefectError
from prettyplay.reporting import StepHooks, StepReporter

CACHED_CODE = "def step(page) -> None:\n    page.open('https://example.com')\n"
BROKEN_CODE = "def step(page) -> None:\n    page.find_by_role('button', name='Войти').click()\n"


class FakePage:
    """Fake page facade boundary: recorded calls, locator lookup failing like rot."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def open(self, url: str) -> None:
        self.calls.append(("open", url))

    def find_by_role(self, role: str, name: str) -> object:
        self.calls.append(("find_by_role", role, name))
        raise AssertionError("element not found")


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

    def __init__(self, tmp_path: Path, generator: object, healer: object, cache_key: str = "login-flow") -> None:
        self.recorder = RecorderHook()
        self.reporter = StepReporter(hooks=[self.recorder])
        self.config = Config(cache_root=str(tmp_path))
        self.cache = StepCache(self.config, None, self.reporter)
        self.budgets = RunBudgets(3, 2)
        self.generator = generator
        self.healer = healer
        self.executor = StepExecutor(cache_key, self.cache, generator, healer, self.budgets, self.reporter)


def events_named(recorder: RecorderHook, name: str) -> list[dict[str, str | int]]:
    """Collect the payloads of the recorded events with the given name."""
    return [payload for event, payload in recorder.events if event == name]


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
                # only the render's first line; the verdict tail stays out of the event
                "error": first_line_short(failure),
            }
        ]
        assert not events_named(fixture.recorder, "on_step_passed")
        assert fixture.executor._scenario == []  # failure does not grow the scenario context

    def test_failed_step_error_is_first_line_cut_to_200(self, tmp_path: Path) -> None:
        generator = RaisingGenerator(ValueError(f"first {'x' * 300}\nsecond line"))
        fixture = ExecutorFixture(tmp_path, generator, RecordingHealer())
        page = FakePage()

        with pytest.raises(ValueError, match="first"):
            fixture.executor.execute("шаг", "action", page)

        failed = events_named(fixture.recorder, "on_step_failed")
        assert len(failed) == 1
        error = failed[0]["error"]
        assert error == f"first {'x' * 300}"[:200]
        assert len(error) == 200
        assert "second line" not in error

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
