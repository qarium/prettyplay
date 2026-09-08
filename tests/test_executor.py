"""Tests for the StepExecutor of the prettyplay root cell."""

import inspect
from pathlib import Path

import pytest
from prettyplay import StepExecutor
from prettyplay.cache import CachedStep, RunBudgets, StepCache, StepIdentity, normalize_step_text
from prettyplay.config import Config
from prettyplay.failures import IncurableStepError
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
                "previous_steps": list(previous_steps),  # снимок: живой список растёт после вызова
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
                "previous_steps": list(previous_steps),  # снимок: живой список растёт после вызова
                "page": page,
            }
        )
        return self.step


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


class TestStepExecutorLogic:
    """Logic tests: hit and miss paths, scenario context, failures, healing delegation."""

    def test_hit_path_runs_cached_code_without_engines(self, tmp_path: Path) -> None:
        generator = RecordingGenerator()
        healer = RecordingHealer()
        fixture = ExecutorFixture(tmp_path, generator, healer)
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="открыть страницу")
        fixture.cache.save(CachedStep(identity=identity, code=CACHED_CODE, created_at="2026-09-07"))
        page = FakePage()

        # шаг с другим регистром и пробелами нормализуется в тот же адрес  # noqa: RUF003 — кириллица намерена
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

    def test_generator_failure_reports_and_propagates_by_kind(self, tmp_path: Path) -> None:
        generator = RaisingGenerator(
            IncurableStepError("шаг", "generation attempt budget exhausted", "reword the step")
        )
        fixture = ExecutorFixture(tmp_path, generator, RecordingHealer())
        page = FakePage()

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.executor.execute("шаг", "action", page)

        assert excinfo.value.reason == "generation attempt budget exhausted"
        assert events_named(fixture.recorder, "on_step_failed") == [
            {
                "step_text": "шаг",
                "step_type": "action",
                "error": str(IncurableStepError("шаг", "generation attempt budget exhausted", "reword the step")),
            }
        ]
        assert not events_named(fixture.recorder, "on_step_passed")
        assert fixture.executor._scenario == []  # сбой не пополняет сценарный контекст

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
        assert healer.calls[0]["step"].code.rstrip("\n") == BROKEN_CODE.rstrip("\n")  # сериализатор добавляет \n
        assert "element not found" in healer.calls[0]["error"]
        assert healer.calls[0]["previous_steps"] == ["шаг один"]
        assert healer.calls[0]["page"] is page
        assert len(generator.calls) == 1  # генерация только для первого шага, лечение — для второго
        assert len(events_named(fixture.recorder, "on_step_passed")) == 2
        assert not events_named(fixture.recorder, "on_step_failed")
        assert fixture.executor._scenario == ["шаг один", "нажать Войти"]
