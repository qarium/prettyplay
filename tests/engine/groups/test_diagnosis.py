"""Tests for the single group diagnosis request of the prettyplay.engine.groups cell."""

import inspect
import logging
from pathlib import Path

import pytest
from prettyplay.cache import StepIdentity
from prettyplay.config import Config
from prettyplay.engine import StepAttempt
from prettyplay.engine.groups import GroupStepOutcome, classify_group_failure
from prettyplay.engine.groups.diagnosis import GROUP_DIAGNOSIS_PROMPT
from prettyplay.failures import LLMUnavailableError
from prettyplay.llm import GroupFailureClassification, ScenarioStep

GROUP_DIAGNOSIS_PRACTICE = Path(__file__).resolve().parents[3] / ".goga" / "usages" / "prompts" / "group_diagnosis.md"


class FakePage:
    """Fake page facade boundary: snapshot plus counted screenshot calls."""

    def __init__(self) -> None:
        self.screenshot_calls = 0

    def aria_snapshot(self) -> str:
        return "body: main"

    def screenshot(self) -> bytes:
        self.screenshot_calls += 1
        return b"png"


class DiagnosisProvider:
    """Stub provider boundary returning one scripted verdict with recorded requests."""

    def __init__(self, verdict: GroupFailureClassification) -> None:
        self.verdict = verdict
        self.calls: list[dict[str, object]] = []

    def classify_group_failure(self, **kwargs: object) -> GroupFailureClassification:
        self.calls.append(dict(kwargs))
        return self.verdict


class UnavailableProvider:
    """Stub provider whose service is down: the diagnosis raises LLMUnavailableError once."""

    def __init__(self) -> None:
        self.calls = 0

    def classify_group_failure(self, **_kwargs: object) -> GroupFailureClassification:
        self.calls += 1
        raise LLMUnavailableError("anthropic down")


def _identity(normalized_text: str) -> StepIdentity:
    return StepIdentity(cache_key="tests/test_checkout.py", step_type="action", normalized_text=normalized_text)


def _trace(sentence: str, outcome: str = "passed", instruction: str | None = None) -> GroupStepOutcome:
    return GroupStepOutcome(
        sentence=sentence,
        # a template step records its prepared instruction; a non-template one the sentence itself
        instruction=instruction if instruction is not None else sentence,
        step_type="action",
        outcome=outcome,
        url_before="https://example.com/cart",
        url_after="https://example.com/checkout",
        identity=_identity(sentence),
    )


def _previous(sentence: str, instruction: str, group_prompt: str = "") -> ScenarioStep:
    return ScenarioStep(sentence=sentence, instruction=instruction, group_prompt=group_prompt)


def _scenario() -> list[ScenarioStep]:
    """The prior scenario of the test: one ordinary step, one group step, one template step."""
    return [
        _previous("open the shop", "open the shop"),
        _previous("accept the cookies", "accept the cookies", "accept cookies and submit the order"),
        _previous("read {{ kind }}", "read novel"),
    ]


def _attempt(code: str = "def step(page) -> None:\n    pass\n", error: str = "AssertionError") -> StepAttempt:
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
        "earliest_step": "fill the email field",
        "recommendation": "regenerate the row from the fill step",
    }
    fields.update(overrides)
    return GroupFailureClassification(**fields)  # type: ignore[arg-type]


def _records(caplog: pytest.LogCaptureFixture, event: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.getMessage() == event]


class TestClassifyGroupFailureContract:
    """Contract tests: facade import, the fixed parameter list, the frozen mirror."""

    def test_is_importable_from_facade(self) -> None:
        assert callable(classify_group_failure)

    def test_is_listed_in_the_facade_all(self) -> None:
        import prettyplay.engine.groups  # noqa: PLC0415 — cell facade check

        assert "classify_group_failure" in prettyplay.engine.groups.__all__

    def test_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(classify_group_failure).parameters.values())

        assert [parameter.name for parameter in parameters] == [
            "config",
            "provider",
            "group_prompt",
            "traces",
            "previous_steps",
            "step_text",
            "step_type",
            "attempt_history",
            "page",
        ]

    def test_returns_the_provider_verdict(self, tmp_path: Path) -> None:
        verdict = _verdict()

        result = classify_group_failure(
            Config(cache_root=str(tmp_path)),
            DiagnosisProvider(verdict),
            "accept cookies and submit the order",
            [_trace("accept the cookie banner"), _trace("submit the form")],
            _scenario(),
            "submit the form",
            "action",
            [_attempt()],
            FakePage(),
        )

        assert result == verdict

    def test_provider_receives_previous_steps_and_the_prepared_step_text(self, tmp_path: Path) -> None:
        """The wrapper threads the typed records and the prepared instruction — never raw Jinja."""
        provider = DiagnosisProvider(_verdict())
        scenario = _scenario()
        traces = [
            _trace("accept the cookie banner"),
            _trace("read {{ kind }}", instruction="read novel"),
            _trace("read {{ kind }} into {% var name %}", "failed", instruction="read novel into "),
        ]

        classify_group_failure(
            Config(cache_root=str(tmp_path)),
            provider,
            "accept cookies and submit the order",
            traces,
            scenario,
            "read novel into ",  # the failed step's prepared instruction — the rendered text
            "action",
            [_attempt()],
            FakePage(),
        )

        kwargs = provider.calls[0]
        assert kwargs["step_text"] == "read novel into "  # the prepared instruction verbatim
        assert kwargs["previous_steps"] is scenario  # the typed records ride through by identity
        assert "{{" not in kwargs["step_text"]  # never the template
        assert "{%" not in kwargs["step_text"]
        assert all("{{" not in record.instruction and "{%" not in record.instruction for record in scenario)
        # the GROUP STEPS traces render their recorded instructions — the raw sentences stay local
        assert all("{{" not in step and "{%" not in step for step in kwargs["group_steps"])

    def test_group_diagnosis_prompt_mirrors_the_practice(self) -> None:
        practice = GROUP_DIAGNOSIS_PRACTICE.read_text(encoding="utf-8")
        prompt = practice.split("---", 1)[1].strip()  # the section after the separator is the prompt itself

        assert prompt == GROUP_DIAGNOSIS_PROMPT  # the frozen mirror — the constant changes only together with the file
        # spot-asserts of the diagnosis contract — the equality alone would hide a both-sides edit
        assert GROUP_DIAGNOSIS_PROMPT.startswith("You diagnose a failure of one step inside a group")
        assert '"category": "recoverable | product_defect | incurable"' in GROUP_DIAGNOSIS_PROMPT
        assert "- PREVIOUS STEPS: the prepared instructions of the prior scenario" in GROUP_DIAGNOSIS_PROMPT
        assert "- GROUP STEPS: every step of the group in execution order — each with its recorded prepared" in (
            GROUP_DIAGNOSIS_PROMPT
        )
        assert "- STEP: the failed step's prepared instruction" in GROUP_DIAGNOSIS_PROMPT
        assert "- recoverable —" in GROUP_DIAGNOSIS_PROMPT
        assert "- product_defect —" in GROUP_DIAGNOSIS_PROMPT
        assert "- incurable —" in GROUP_DIAGNOSIS_PROMPT
        assert "earliest_step must quote a visible instruction verbatim" in GROUP_DIAGNOSIS_PROMPT
        assert "raw template sentences are not\n  request content" in GROUP_DIAGNOSIS_PROMPT  # the wrapped rule tail
        assert "Output only the JSON object, no other text" in GROUP_DIAGNOSIS_PROMPT


class TestClassifyGroupFailureLogic:
    """Logic tests: input collection, the port call shape, the log records."""

    def test_collects_inputs_and_calls_the_port_once(self, tmp_path: Path) -> None:
        provider = DiagnosisProvider(_verdict())
        page = FakePage()
        traces = [
            _trace("accept the cookie banner"),
            _trace("fill the email field"),
            _trace("submit the form", "failed"),
        ]
        scenario = _scenario()
        history = [_attempt(), _attempt(code="def step(page) -> None:\n    raise AssertionError\n")]

        verdict = classify_group_failure(
            Config(cache_root=str(tmp_path), send_screenshots=True),
            provider,
            "accept cookies and submit the order",
            traces,
            scenario,
            "submit the form",
            "action",
            history,
            page,
        )

        assert verdict == provider.verdict
        assert len(provider.calls) == 1  # one request per diagnosis
        kwargs = provider.calls[0]
        assert set(kwargs) == {  # the port parameter list, nothing invented
            "prompt",
            "user_instructions",
            "group_prompt",
            "group_steps",
            "previous_steps",
            "step_text",
            "attempt_history",
            "snapshot",
            "screenshot",
        }
        assert kwargs["prompt"] == GROUP_DIAGNOSIS_PROMPT
        assert kwargs["group_prompt"] == "accept cookies and submit the order"
        assert kwargs["group_steps"] == [trace.render() for trace in traces]
        assert kwargs["previous_steps"] is scenario  # the typed records ride through by identity
        assert kwargs["step_text"] == "submit the form"
        assert kwargs["attempt_history"] == [record.render() for record in history]
        assert kwargs["snapshot"] == "body: main"
        assert kwargs["screenshot"] == b"png"
        assert page.screenshot_calls == 1

    def test_screenshot_attached_only_when_enabled(self, tmp_path: Path) -> None:
        provider = DiagnosisProvider(_verdict())
        page = FakePage()

        classify_group_failure(
            Config(cache_root=str(tmp_path), send_screenshots=False),
            provider,
            "g",
            [_trace("s")],
            _scenario(),
            "s",
            "assertion",
            [],
            page,
        )

        kwargs = provider.calls[0]
        assert kwargs["screenshot"] is None
        assert page.screenshot_calls == 0

    def test_classification_instructions_ride_as_user_instructions(self, tmp_path: Path) -> None:
        provider = DiagnosisProvider(_verdict())

        classify_group_failure(
            Config(cache_root=str(tmp_path), classification_prompt="answer in Russian"),
            provider,
            "g",
            [_trace("s")],
            _scenario(),
            "s",
            "action",
            [],
            FakePage(),
        )

        assert provider.calls[0]["user_instructions"] == "answer in Russian"

    def test_empty_instructions_reach_the_port_empty(self, tmp_path: Path) -> None:
        """The empty value rides through — the provider renders no instructions block (provider-side)."""
        provider = DiagnosisProvider(_verdict())

        classify_group_failure(
            Config(cache_root=str(tmp_path)),
            provider,
            "g",
            [_trace("s")],
            _scenario(),
            "s",
            "action",
            [],
            FakePage(),
        )

        assert provider.calls[0]["user_instructions"] == ""

    def test_previous_steps_render_input_rides_as_the_record_fields(self, tmp_path: Path) -> None:
        """The records the provider receives carry the prepared instructions and the group marks.

        The provider renders the PREVIOUS STEPS block from these records — the
        wrapper hands over exactly the typed records: the instruction fields
        (never the raw sentences) plus the group membership of the marking.
        """
        provider = DiagnosisProvider(_verdict())
        scenario = _scenario()

        classify_group_failure(
            Config(cache_root=str(tmp_path)),
            provider,
            "accept cookies and submit the order",
            [_trace("fill the email field")],
            scenario,
            "submit the form",
            "action",
            [_attempt()],
            FakePage(),
        )

        received = provider.calls[0]["previous_steps"]
        assert received == scenario
        assert [(record.instruction, record.group_prompt) for record in received] == [
            ("open the shop", ""),
            ("accept the cookies", "accept cookies and submit the order"),
            ("read novel", ""),
        ]  # the render inputs: prepared instructions plus group marks; sentences stay unrendered

    def test_empty_previous_steps_ride_as_the_empty_list(self, tmp_path: Path) -> None:
        """The empty list rides through — the provider omits the PREVIOUS STEPS block."""
        provider = DiagnosisProvider(_verdict())

        classify_group_failure(
            Config(cache_root=str(tmp_path)),
            provider,
            "g",
            [_trace("s")],
            [],
            "s",
            "action",
            [],
            FakePage(),
        )

        assert provider.calls[0]["previous_steps"] == []

    def test_landed_diagnosis_logs_the_info_record(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="prettyplay"):
            classify_group_failure(
                Config(cache_root=str(tmp_path)),
                DiagnosisProvider(_verdict()),
                "accept cookies and submit the order",
                [_trace("fill the email field")],
                _scenario(),
                "submit the form",
                "action",
                [_attempt()],
                FakePage(),
            )

        records = _records(caplog, "group_diagnosed")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert record.group == "accept cookies and submit the order"
        assert record.category == "recoverable"
        assert record.earliest == "fill the email field"
        assert _records(caplog, "group_diagnosis_degraded") == []

    def test_degraded_verdict_logs_warning_and_still_returns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = DiagnosisProvider(_verdict(category="incurable", root_cause="the app is broken", degraded=True))

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            verdict = classify_group_failure(
                Config(cache_root=str(tmp_path)),
                provider,
                "accept cookies and submit the order",
                [_trace("fill the email field")],
                _scenario(),
                "submit the form",
                "action",
                [_attempt()],
                FakePage(),
            )

        assert verdict is provider.verdict  # the degraded verdict is returned, never swallowed
        assert verdict.degraded is True
        warnings = _records(caplog, "group_diagnosis_degraded")
        assert len(warnings) == 1
        warning = warnings[0]
        assert warning.levelno == logging.WARNING
        assert warning.group == "accept cookies and submit the order"
        assert warning.answer == "the app is broken"  # the raw answer rides root_cause
        # the landed-diagnosis INFO record still logs — always
        infos = _records(caplog, "group_diagnosed")
        assert len(infos) == 1
        assert infos[0].category == "incurable"

    def test_provider_unavailability_propagates_untouched(self, tmp_path: Path) -> None:
        provider = UnavailableProvider()

        with pytest.raises(LLMUnavailableError) as excinfo:
            classify_group_failure(
                Config(cache_root=str(tmp_path)),
                provider,
                "g",
                [_trace("s")],
                _scenario(),
                "s",
                "action",
                [],
                FakePage(),
            )

        assert "anthropic down" in str(excinfo.value)
        assert provider.calls == 1  # no retry, no swallow

    def test_empty_traces_and_history_ride_as_empty_lists(self, tmp_path: Path) -> None:
        provider = DiagnosisProvider(_verdict())

        classify_group_failure(
            Config(cache_root=str(tmp_path)),
            provider,
            "g",
            [],
            _scenario(),
            "s",
            "action",
            [],
            FakePage(),
        )

        kwargs = provider.calls[0]
        assert kwargs["group_steps"] == []
        assert kwargs["attempt_history"] == []
