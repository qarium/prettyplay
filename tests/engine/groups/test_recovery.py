"""Tests for the GroupRecovery engine of the prettyplay.engine.groups cell."""

import inspect
import logging
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from prettyplay.cache import CachedStep, RunBudgets, StepCache, StepIdentity
from prettyplay.config import Config
from prettyplay.engine import StepAttempt, StepGenerator
from prettyplay.engine.attempts import OUTCOME_ORIGINAL
from prettyplay.engine.groups import GroupRecovery, GroupStepOutcome
from prettyplay.engine.polling import SettleWindow
from prettyplay.failures import IncurableStepError, LLMUnavailableError, ProductDefectError
from prettyplay.llm import GroupFailureClassification, ScenarioStep
from prettyplay.reporting import StepHooks, StepReporter

GROUP_PROMPT = "accept cookies, fill and submit the order form"
COOKIE = "accept the cookie banner"
FILL = "fill the email field"
SUBMIT = "submit the form"
STATUS = "the status shows order confirmed"

WORKING_CODE = "def step(page) -> None:\n    pass\n"

#: a candidate whose execution always fails — the repeat-failure scenario's row answer
FAILING_CODE = "def step(page) -> None:\n    raise RuntimeError('boom')\n"


class FakePage:
    """Fake page facade boundary: the run primitive, the snapshot and a fixed URL."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    @property
    def url(self) -> str:
        return "https://example.com/checkout"

    def run(self, action: Callable[[object], object]) -> object:
        self.calls.append(("run",))
        return action(self)

    def aria_snapshot(self) -> str:
        return "- snapshot"

    def screenshot(self) -> bytes:
        return b"png"


class RecoveryProvider:
    """Stub provider boundary: scripted diagnosis verdicts and row answers, all calls recorded."""

    def __init__(
        self,
        verdicts: list[GroupFailureClassification | Exception] | None = None,
        answers: list[str] | None = None,
    ) -> None:
        self.verdicts = list(verdicts) if verdicts is not None else []
        self.answers = list(answers) if answers is not None else []
        self.diagnosis_calls: list[dict[str, object]] = []
        self.generate_calls: list[dict[str, object]] = []

    def classify_group_failure(self, **kwargs: object) -> GroupFailureClassification:
        self.diagnosis_calls.append(dict(kwargs))
        verdict = self.verdicts.pop(0)

        if isinstance(verdict, Exception):  # a scripted provider failure plays itself
            raise verdict
        return verdict

    def generate_step_code(self, **kwargs: object) -> str:
        self.generate_calls.append(dict(kwargs))
        if not self.answers:
            raise AssertionError("stub provider has no answers left")

        return self.answers.pop(0)

    def check_instruction_compliance(self, **_kwargs: object) -> list[object]:
        return []


class FakeGenerator:
    """Stub generator boundary: recorded regenerate calls with scripted outcomes."""

    def __init__(self, outcomes: list[CachedStep | Exception] | None = None) -> None:
        self.outcomes = list(outcomes) if outcomes is not None else []
        self.calls: list[dict[str, object]] = []

    def regenerate(self, **kwargs: object) -> CachedStep:
        self.calls.append(dict(kwargs))
        if not self.outcomes:
            raise AssertionError("fake generator has no outcomes left")

        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):  # a scripted regeneration failure plays itself
            raise outcome
        return outcome


class RecorderHook(StepHooks):
    """Hook recording engine events into a shared ``events`` list for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str | int]]] = []

    def on_generation_started(self, step_text: str, attempt: int) -> None:
        self.events.append(("on_generation_started", {"step_text": step_text, "attempt": attempt}))

    def on_healing_started(self, step_text: str, category: str) -> None:
        self.events.append(("on_healing_started", {"step_text": step_text, "category": category}))

    def on_healed(self, step_text: str, explanation: str) -> None:
        self.events.append(("on_healed", {"step_text": step_text, "explanation": explanation}))

    def on_cache_saved(self, step_text: str, filename: str) -> None:
        self.events.append(("on_cache_saved", {"step_text": step_text, "filename": filename}))


class RecordingBudgets(RunBudgets):
    """Real registry boundary recording the recovery's cycle and refresh calls."""

    def __init__(self, generation_limit: int, healing_limit: int) -> None:
        super().__init__(generation_limit, healing_limit)
        self.cycle_calls: list[str] = []
        self.refresh_calls: list[StepIdentity] = []

    def open_group_cycle(self, group_key: str) -> bool:
        self.cycle_calls.append(group_key)

        return super().open_group_cycle(group_key)

    def refresh_healing(self, identity: StepIdentity) -> None:
        self.refresh_calls.append(identity)
        super().refresh_healing(identity)


class RecoveryFixture:
    """Recovery assembled on a tmp cache with recording budgets, for the logic tests."""

    def __init__(
        self,
        tmp_path: Path,
        provider: object,
        generator: object | None = None,
        limits: tuple[int, int] = (3, 2),
    ) -> None:
        self.recorder = RecorderHook()
        self.reporter = StepReporter(hooks=[self.recorder])
        self.config = Config(cache_root=str(tmp_path), polling_delay=0)
        self.cache = StepCache(self.config, None, self.reporter)
        self.budgets = RecordingBudgets(*limits)
        self.generator = (
            generator
            if generator is not None
            else StepGenerator(self.config, provider, self.cache, self.budgets, self.reporter)
        )
        self.recovery = GroupRecovery(self.config, provider, self.generator, self.cache, self.budgets, self.reporter)


def _identity(sentence: str, step_type: str = "action") -> StepIdentity:
    return StepIdentity(cache_key="tests/test_checkout.py", step_type=step_type, normalized_text=sentence)


def _trace(
    sentence: str,
    outcome: str = "passed",
    step_type: str = "action",
    tries: int | None = None,
    delay: float | None = None,
) -> GroupStepOutcome:
    return GroupStepOutcome(
        sentence=sentence,
        step_type=step_type,
        tries=tries,
        delay=delay,
        outcome=outcome,
        url_before="https://example.com/cart",
        url_after="https://example.com/checkout",
        identity=_identity(sentence, step_type),
    )


def _cached(sentence: str, step_type: str = "action") -> CachedStep:
    return CachedStep(identity=_identity(sentence, step_type), code=WORKING_CODE, created_at="2026-09-16")


def _attempt(code: str = WORKING_CODE, error: str = "the check failure text") -> StepAttempt:
    return StepAttempt(
        code=code,
        error=error,
        outcome="failed check",
        url_before="https://example.com/checkout",
        url_after="https://example.com/checkout",
    )


def _verdict(**overrides: object) -> GroupFailureClassification:
    fields: dict[str, object] = {
        "category": "recoverable",
        "root_cause": "the fill step did not land what its sentence says",
        "earliest_step": FILL,
        "recommendation": "regenerate the row from the fill step",
    }
    fields.update(overrides)
    return GroupFailureClassification(**fields)  # type: ignore[arg-type]


def _records(caplog: pytest.LogCaptureFixture, event: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.getMessage() == event]


def _group_traces(**status_kwargs: object) -> list[GroupStepOutcome]:
    """The reference group: three passed steps and the failed status check, execution order."""
    status: dict[str, object] = {"outcome": "failed", "step_type": "assertion", "tries": 2, "delay": 0.5}
    status.update(status_kwargs)
    return [_trace(COOKIE), _trace(FILL, delay=0.25), _trace(SUBMIT), _trace(STATUS, **status)]  # type: ignore[arg-type]


def _group_scenario() -> list[ScenarioStep]:
    """The typed records of the test before the failed step: one ordinary step, the group's passed steps."""
    return [
        ScenarioStep(sentence="open the shop", group_prompt=""),
        ScenarioStep(sentence=COOKIE, group_prompt=GROUP_PROMPT),
        ScenarioStep(sentence=FILL, group_prompt=GROUP_PROMPT),
        ScenarioStep(sentence=SUBMIT, group_prompt=GROUP_PROMPT),
    ]


class TestGroupRecoveryContract:
    """Contract tests: facade import, the fixed parameter lists, the healed return."""

    def test_is_importable_from_facade(self) -> None:
        assert isinstance(GroupRecovery, type)

    def test_is_listed_in_the_facade_all(self) -> None:
        import prettyplay.engine.groups  # noqa: PLC0415 — cell facade check

        assert "GroupRecovery" in prettyplay.engine.groups.__all__

    def test_constructor_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(GroupRecovery.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == [
            "config",
            "provider",
            "generator",
            "cache",
            "budgets",
            "reporter",
        ]

    def test_recover_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(GroupRecovery.recover).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == [
            "group_prompt",
            "traces",
            "step_text",
            "step_type",
            "previous_steps",
            "identity",
            "attempt_history",
            "page",
            "window",
        ]

    def test_returns_the_healed_cached_step_of_the_failed_step(self, tmp_path: Path) -> None:
        healed = _cached(STATUS, "assertion")
        provider = RecoveryProvider(verdicts=[_verdict(earliest_step=STATUS)])
        fixture = RecoveryFixture(tmp_path, provider, FakeGenerator([healed]))

        result = fixture.recovery.recover(
            GROUP_PROMPT,
            _group_traces(),
            STATUS,
            "assertion",
            _group_scenario(),
            _identity(STATUS, "assertion"),
            [_attempt()],
            FakePage(),
            SettleWindow(None, 0),
        )

        assert result is healed
        assert result.identity == _identity(STATUS, "assertion")


class TestGroupRecoveryReferenceScenario:
    """Logic tests: the reference scenario — diagnosis, row, write-back, reporting, budgets."""

    def test_recover_reference_scenario_goes_green(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr("prettyplay.engine.groups.recovery.time", SimpleNamespace(sleep=sleeps.append))

        verdict = _verdict(earliest_step=FILL)
        provider = RecoveryProvider(verdicts=[verdict], answers=[WORKING_CODE] * 3)
        fixture = RecoveryFixture(tmp_path, provider)
        # the earlier row steps passed their original execution — their caches exist
        fixture.cache.save(CachedStep(identity=_identity(FILL), code=WORKING_CODE, created_at="2026-09-15"))
        fixture.cache.save(CachedStep(identity=_identity(SUBMIT), code=WORKING_CODE, created_at="2026-09-15"))

        traces = _group_traces()
        history = [
            StepAttempt(
                code=WORKING_CODE,
                error="expected the confirmation status",
                outcome=OUTCOME_ORIGINAL,
                url_before="https://example.com/checkout",
                url_after="https://example.com/checkout",
            )
        ]

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            healed = fixture.recovery.recover(
                GROUP_PROMPT,
                traces,
                STATUS,
                "assertion",
                _group_scenario(),
                _identity(STATUS, "assertion"),
                history,
                FakePage(),
                SettleWindow(None, 0),
            )

        # the healed step of the failed step returns — the group continues normally
        assert healed.identity == _identity(STATUS, "assertion")
        assert healed.code == WORKING_CODE

        # the row: three regenerations in trace order, each with the framing and the recommendation
        assert [call["step_text"] for call in provider.generate_calls] == [FILL, SUBMIT, STATUS]
        for call in provider.generate_calls:
            assert call["group_prompt"] == GROUP_PROMPT
            assert call["recommendation"] == verdict.recommendation
            assert call["previous_steps"] == _group_scenario()

        # every row step's cached code present under the tmp cache root — the write-back is per step
        assert fixture.cache.load(_identity(FILL)) is not None
        assert fixture.cache.load(_identity(SUBMIT)) is not None
        assert fixture.cache.load(_identity(STATUS, "assertion")) is not None

        # the healing events: three starts labelled recoverable, three healed
        starts = [payload for event, payload in fixture.recorder.events if event == "on_healing_started"]
        assert starts == [
            {"step_text": FILL, "category": "recoverable"},
            {"step_text": SUBMIT, "category": "recoverable"},
            {"step_text": STATUS, "category": "recoverable"},
        ]
        assert len([1 for event, _ in fixture.recorder.events if event == "on_healed"]) == 3

        # the log records: one row record per step, one diagnosis record naming the fill step
        row_records = _records(caplog, "group_row_recovered")
        assert [record.step for record in row_records] == [FILL, SUBMIT, STATUS]
        assert all(record.group == GROUP_PROMPT and record.earliest == FILL for record in row_records)
        diagnosis = _records(caplog, "group_diagnosed")
        assert len(diagnosis) == 1
        assert diagnosis[0].category == "recoverable"
        assert diagnosis[0].earliest == FILL

        # exactly one cycle consumed; the row steps' pools refreshed in row order
        assert fixture.budgets.cycle_calls == [GROUP_PROMPT]
        assert fixture.budgets.refresh_calls == [
            _identity(FILL),
            _identity(SUBMIT),
            _identity(STATUS, "assertion"),
        ]

        # the ordinary per-step pool of a non-group step keeps its full count — never consumed
        outsider = _identity("open the shop")
        assert fixture.budgets.try_healing(outsider) is True
        assert fixture.budgets.try_healing(outsider) is True

        # the declared delays of the row steps pass quietly, in row order
        assert sleeps == [0.25, 0.5]


class TestGroupRecoveryTerminalFailures:
    """Logic tests: the refused cycle and the out-of-mandate root end the run honestly."""

    def test_recovery_refused_cycle_and_outside_root_are_terminal(self, tmp_path: Path) -> None:
        # case A — the per-group cycle cap is exhausted before any diagnosis
        provider = RecoveryProvider(verdicts=[_verdict()])
        fixture = RecoveryFixture(tmp_path, provider, FakeGenerator())
        assert fixture.budgets.open_group_cycle(GROUP_PROMPT) is True
        assert fixture.budgets.open_group_cycle(GROUP_PROMPT) is True

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.recovery.recover(
                GROUP_PROMPT,
                _group_traces(),
                STATUS,
                "assertion",
                _group_scenario(),
                _identity(STATUS, "assertion"),
                [_attempt()],
                FakePage(),
                SettleWindow(None, 0),
            )

        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "incurable"
        assert "cycle cap" in excinfo.value.verdict.explanation
        assert provider.diagnosis_calls == []  # no diagnosis request made
        assert fixture.generator.calls == []  # type: ignore[attr-defined] — the fake generator records every call

        # case B — the quoted root lives outside the group: recovery is out of mandate
        outside_provider = RecoveryProvider(
            verdicts=[
                _verdict(category="incurable", root_cause="the shop page is broken", earliest_step="open the shop")
            ]
        )
        outside_fixture = RecoveryFixture(tmp_path, outside_provider, FakeGenerator())

        with pytest.raises(IncurableStepError) as outside_excinfo:
            outside_fixture.recovery.recover(
                GROUP_PROMPT,
                _group_traces(),
                STATUS,
                "assertion",
                _group_scenario(),
                _identity(STATUS, "assertion"),
                [_attempt()],
                FakePage(),
                SettleWindow(None, 0),
            )

        verdict = outside_excinfo.value.verdict
        assert verdict is not None
        assert verdict.category == "incurable"
        assert "the root lives outside the group" in verdict.explanation
        assert "open the shop" in verdict.explanation  # the outside step named verbatim
        assert outside_fixture.generator.calls == []  # type: ignore[attr-defined] — no regeneration happened
        assert len(outside_provider.diagnosis_calls) == 1

    def test_repeat_failure_reenters_new_cycle_until_cap(self, tmp_path: Path) -> None:
        provider = RecoveryProvider(verdicts=[_verdict(earliest_step="")] * 2, answers=[FAILING_CODE] * 4)
        fixture = RecoveryFixture(tmp_path, provider)

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.recovery.recover(
                GROUP_PROMPT,
                _group_traces(),
                STATUS,
                "assertion",
                _group_scenario(),
                _identity(STATUS, "assertion"),
                [],
                FakePage(),
                SettleWindow(None, 0),
            )

        # the terminal error carries the authored cap verdict
        assert excinfo.value.verdict is not None
        assert "cycle cap" in excinfo.value.verdict.explanation

        # two cycles opened and diagnosed, the third refused — the loop is never infinite
        assert len(fixture.budgets.cycle_calls) == 3
        assert len(provider.diagnosis_calls) == 2
        assert len(provider.generate_calls) == 4  # two healing attempts per cycle, a fresh pool per cycle
        assert fixture.budgets.refresh_calls == [_identity(STATUS, "assertion")] * 2

        # no row step was written to the cache
        assert fixture.cache.load(_identity(FILL)) is None
        assert fixture.cache.load(_identity(STATUS, "assertion")) is None

    def test_earliest_step_no_match_degrades_to_failed_step_row(self, tmp_path: Path) -> None:
        healed = _cached(STATUS, "assertion")
        provider = RecoveryProvider(verdicts=[_verdict(earliest_step="a sentence matching nothing verbatim")])
        fixture = RecoveryFixture(tmp_path, provider, FakeGenerator([healed]))

        result = fixture.recovery.recover(
            GROUP_PROMPT,
            _group_traces(),
            STATUS,
            "assertion",
            _group_scenario(),
            _identity(STATUS, "assertion"),
            [_attempt()],
            FakePage(),
            SettleWindow(5.0, 9.0),  # the failed step's window — never reused for the row
        )

        assert result is healed
        assert len(fixture.generator.calls) == 1  # type: ignore[attr-defined] — the row is the failed step alone
        call = fixture.generator.calls[0]  # type: ignore[attr-defined]

        assert call["identity"] == _identity(STATUS, "assertion")
        assert call["step_text"] == STATUS
        assert call["group_prompt"] == GROUP_PROMPT

        # the row window is built from the trace's declared tries and the config polling settings
        row_window = call["window"]
        assert isinstance(row_window, SettleWindow)
        assert row_window.tries == 2
        assert row_window.timeout == fixture.config.polling_timeout
        assert row_window.delay == fixture.config.polling_delay

        assert fixture.budgets.refresh_calls == [_identity(STATUS, "assertion")]


class TestGroupRecoveryEdgePins:
    """Edge pins: single-step rows, anchored histories, verdict mapping, immutability."""

    def test_single_step_row_when_the_quote_names_the_failed_step(self, tmp_path: Path) -> None:
        healed = _cached(STATUS, "assertion")
        provider = RecoveryProvider(verdicts=[_verdict(earliest_step=STATUS)])
        fixture = RecoveryFixture(tmp_path, provider, FakeGenerator([healed]))

        result = fixture.recovery.recover(
            GROUP_PROMPT,
            _group_traces(),
            STATUS,
            "assertion",
            _group_scenario(),
            _identity(STATUS, "assertion"),
            [_attempt()],
            FakePage(),
            SettleWindow(None, 0),
        )

        assert result is healed
        assert len(fixture.generator.calls) == 1  # type: ignore[attr-defined]
        assert fixture.generator.calls[0]["identity"] == _identity(STATUS, "assertion")  # type: ignore[attr-defined]
        assert fixture.budgets.refresh_calls == [_identity(STATUS, "assertion")]

    def test_row_histories_anchor_record_zero_per_step(self, tmp_path: Path) -> None:
        provider = RecoveryProvider(verdicts=[_verdict(earliest_step=FILL)])
        # valid Python — the cache loader parses the whole file as a module before restoring the code
        original_code = "def step(page) -> None:\n    original = True\n"
        fixture = RecoveryFixture(
            tmp_path,
            provider,
            FakeGenerator([_cached(FILL), _cached(SUBMIT), _cached(STATUS, "assertion")]),
        )
        # the submit step's cache exists — record 0 anchors its cached code; the fill step's does not
        fixture.cache.save(CachedStep(identity=_identity(SUBMIT), code=original_code, created_at="2026-09-15"))

        history = [_attempt()]
        fixture.recovery.recover(
            GROUP_PROMPT,
            _group_traces(),
            STATUS,
            "assertion",
            _group_scenario(),
            _identity(STATUS, "assertion"),
            history,
            FakePage(),
            SettleWindow(None, 0),
        )

        fill_call, submit_call, status_call = fixture.generator.calls  # type: ignore[attr-defined]

        # the fill step — no cached code: record 0 anchors an empty code with the trace URL pair
        fill_history = fill_call["attempt_history"]
        assert len(fill_history) == 1
        assert isinstance(fill_history[0], StepAttempt)
        assert fill_history[0].outcome == OUTCOME_ORIGINAL
        assert fill_history[0].code == ""
        assert fill_history[0].error == ""
        assert fill_history[0].url_before == "https://example.com/cart"
        assert fill_history[0].url_after == "https://example.com/checkout"

        # the submit step — cached code present: record 0 anchors it as loaded from the cache
        cached_submit = fixture.cache.load(_identity(SUBMIT))
        assert cached_submit is not None
        submit_history = submit_call["attempt_history"]
        assert submit_history[0].code == cached_submit.code

        # the failed step — its passed-in grown history rides by reference
        assert status_call["attempt_history"] is history

    def test_product_defect_diagnosis_raises_the_loud_mapped_failure(self, tmp_path: Path) -> None:
        verdict = _verdict(
            category="product_defect",
            root_cause="the confirmation never arrives",
            earliest_step=STATUS,
        )
        provider = RecoveryProvider(verdicts=[verdict])
        fixture = RecoveryFixture(tmp_path, provider, FakeGenerator())

        with pytest.raises(ProductDefectError) as excinfo:
            fixture.recovery.recover(
                GROUP_PROMPT,
                _group_traces(),
                STATUS,
                "assertion",
                _group_scenario(),
                _identity(STATUS, "assertion"),
                [_attempt()],
                FakePage(),
                SettleWindow(None, 0),
            )

        # the mapped verdict — the category as is, the explanation with the earliest-step quote
        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "product_defect"
        assert excinfo.value.verdict.explanation == (f"{verdict.root_cause} (earliest affected step: {STATUS})")
        assert excinfo.value.verdict.recommendation == verdict.recommendation
        assert excinfo.value.error == "the check failure text"  # the underlying error of the last record
        assert fixture.generator.calls == []  # type: ignore[attr-defined] — anti-masking, nothing regenerated

    def test_incurable_diagnosis_raises_the_mapped_verdict(self, tmp_path: Path) -> None:
        verdict = _verdict(category="incurable", root_cause="regeneration cannot help", earliest_step="")
        provider = RecoveryProvider(verdicts=[verdict])
        fixture = RecoveryFixture(tmp_path, provider, FakeGenerator())

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.recovery.recover(
                GROUP_PROMPT,
                _group_traces(),
                STATUS,
                "assertion",
                _group_scenario(),
                _identity(STATUS, "assertion"),
                [_attempt(code="the failed code", error="the underlying failure")],
                FakePage(),
                SettleWindow(None, 0),
            )

        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.category == "incurable"
        assert excinfo.value.verdict.explanation == verdict.root_cause  # no quote — none named a group step
        assert excinfo.value.code == "the failed code"  # the code of the last record
        assert excinfo.value.error == "the underlying failure"
        assert fixture.generator.calls == []  # type: ignore[attr-defined]

    def test_degraded_diagnosis_maps_to_the_conservative_incurable(self, tmp_path: Path) -> None:
        verdict = _verdict(category="incurable", root_cause="the raw model answer", earliest_step="", degraded=True)
        provider = RecoveryProvider(verdicts=[verdict])
        fixture = RecoveryFixture(tmp_path, provider, FakeGenerator())

        with pytest.raises(IncurableStepError) as excinfo:
            fixture.recovery.recover(
                GROUP_PROMPT,
                _group_traces(),
                STATUS,
                "assertion",
                _group_scenario(),
                _identity(STATUS, "assertion"),
                [_attempt()],
                FakePage(),
                SettleWindow(None, 0),
            )

        assert excinfo.value.verdict is not None
        assert excinfo.value.verdict.explanation == "the raw model answer"  # the raw answer rides root_cause
        assert fixture.generator.calls == []  # type: ignore[attr-defined] — a garbage answer never grants regeneration

    def test_traces_list_is_never_mutated(self, tmp_path: Path) -> None:
        provider = RecoveryProvider(verdicts=[_verdict(earliest_step=FILL)])
        fixture = RecoveryFixture(
            tmp_path,
            provider,
            FakeGenerator([_cached(FILL), _cached(SUBMIT), _cached(STATUS, "assertion")]),
        )
        traces = _group_traces()
        snapshot = list(traces)

        fixture.recovery.recover(
            GROUP_PROMPT,
            traces,
            STATUS,
            "assertion",
            _group_scenario(),
            _identity(STATUS, "assertion"),
            [_attempt()],
            FakePage(),
            SettleWindow(None, 0),
        )

        assert traces == snapshot  # the honest original outcomes — later diagnoses see them unchanged
        assert len(traces) == 4

    def test_provider_unavailability_propagates(self, tmp_path: Path) -> None:
        provider = RecoveryProvider(verdicts=[LLMUnavailableError("openai request failed")])
        fixture = RecoveryFixture(tmp_path, provider, FakeGenerator())

        with pytest.raises(LLMUnavailableError) as excinfo:
            fixture.recovery.recover(
                GROUP_PROMPT,
                _group_traces(),
                STATUS,
                "assertion",
                _group_scenario(),
                _identity(STATUS, "assertion"),
                [_attempt()],
                FakePage(),
                SettleWindow(None, 0),
            )

        assert "openai request failed" in str(excinfo.value)
        assert fixture.generator.calls == []  # type: ignore[attr-defined]
