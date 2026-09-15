"""Tests for the StepSteering REPL of the prettyplay.engine.steering cell."""

import builtins
import inspect
import logging
import re
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from playwright.sync_api import Error as PlaywrightError
from prettyplay.cache import CachedStep, StepCache, StepIdentity
from prettyplay.config import Config
from prettyplay.engine import StepAttempt
from prettyplay.engine.attempts import (
    OUTCOME_COMPLIANCE_BLOCKED,
    OUTCOME_EXECUTION_FAILED,
    OUTCOME_FAILED_CHECK,
    OUTCOME_ORIGINAL,
    OUTCOME_REJECTED,
)
from prettyplay.engine.compliance import COMPLIANCE_PROMPT
from prettyplay.engine.generator import CHEAT_SHEET as ENGINE_CHEAT_SHEET
from prettyplay.engine.generator import SYSTEM_PROMPT as ENGINE_SYSTEM_PROMPT
from prettyplay.engine.steering.steering import CHEAT_SHEET, SYSTEM_PROMPT
from prettyplay.engine.text import format_step_error
from prettyplay.failures import ComplianceVerdictError, FailureVerdict, IncurableStepError, LLMUnavailableError
from prettyplay.llm import ComplianceFinding
from prettyplay.reporting import StepHooks, StepReporter

STEPPING_MODULE = "prettyplay.engine.steering.steering"

GENERATION_PROMPT_PRACTICE = Path(__file__).resolve().parents[3] / ".goga" / "usages" / "prompts" / "generation.md"
CHEAT_SHEET_PRACTICE = Path(__file__).resolve().parents[3] / ".goga" / "usages" / "prompts" / "cheatsheet.md"

GENERATED_CODE = "def step(page) -> None:\n    page.get_by_label('Close').click()\n"
REGENERATED_CODE = "def step(page) -> None:\n    page.get_by_role('button', name='Pay').click()\n"

INSTRUCTIONS = "Prefer id attributes"
HIGH_FINDING = ComplianceFinding(
    instruction="Prefer id attributes", priority="high", explanation="locates by text", dimension="instruction"
)
MEDIUM_FINDING = ComplianceFinding(
    instruction="Prefer id attributes", priority="medium", explanation="minor", dimension="instruction"
)

#: The dimension-aware violation text of the high finding — mirrors the steering wording pin.
VIOLATION = "instruction violation: Prefer id attributes — locates by text"

DEFAULT_PAGE_URL = "https://shop.example.com/checkout"


def _steering_screenshots() -> set[Path]:
    """The temporary screenshot PNGs the dialog has written so far."""
    return set(Path(tempfile.gettempdir()).glob("prettyplay-steering-*.png"))


@pytest.fixture(autouse=True)
def _clean_steering_screenshots() -> Iterator[None]:
    """Remove the temporary PNGs a test's dialogs wrote — the suite never leaks them."""
    existing = _steering_screenshots()
    yield
    for path in _steering_screenshots() - existing:
        path.unlink(missing_ok=True)


def _anchored_history() -> list[StepAttempt]:
    """The shared per-step attempt history anchored by record 0 — the original cached code."""
    return [
        StepAttempt(
            code="old",
            error="Timeout 10000ms exceeded",
            outcome=OUTCOME_ORIGINAL,
            url_before="https://shop.example.com/cart",
            url_after="https://shop.example.com/checkout",
        )
    ]


class FakePage:
    """Fake page facade boundary: a URL, a snapshot and screenshot bytes."""

    def __init__(self, url: str = DEFAULT_PAGE_URL) -> None:
        """Keep the URL the banner, the guided requests and the turn brackets read."""
        self.url = url

    def run(self, action: Callable[[object], object]) -> object:
        """Minimal page-handle shim: the run primitive executes the action against the fake itself."""
        return action(self)

    def aria_snapshot(self) -> str:
        return "- heading: Pay\n- button: Pay now"

    def screenshot(self) -> bytes:
        return b"png"


class DeadPage:
    """Fake page facade whose every interaction raises the driver error."""

    @property
    def url(self) -> str:
        raise PlaywrightError("Target closed")

    def aria_snapshot(self) -> str:
        raise PlaywrightError("Target closed")

    def screenshot(self) -> bytes:
        raise PlaywrightError("Target closed")


class TallSnapshotPage:
    """Fake page facade whose accessibility snapshot spans thirty lines."""

    url = DEFAULT_PAGE_URL

    def aria_snapshot(self) -> str:
        return "\n".join(f"- line {index}" for index in range(1, 31))

    def screenshot(self) -> bytes:
        return b"png"


class FakeProvider:
    """Fake provider boundary: scripted candidates with recorded requests."""

    def __init__(
        self,
        answers: list[str] | None = None,
        failure: Exception | None = None,
        compliance_verdicts: list[list[ComplianceFinding] | Exception] | None = None,
    ) -> None:
        self.answers = list(answers or [])
        self.failure = failure
        self.compliance_verdicts = list(compliance_verdicts) if compliance_verdicts is not None else None
        self.calls: list[dict[str, object]] = []
        self.compliance_calls: list[dict[str, object]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        step_type: str,
        previous_steps: list[str],
        snapshot: str,
        page_url: str | None,
        screenshot: bytes | None,
        cheat_sheet: str,
        attempt_history: list[str],
        recommendation: str | None,
        guidance: str | None,
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
                "attempt_history": list(attempt_history),
                "recommendation": recommendation,
                "guidance": guidance,
            }
        )
        if self.failure is not None:
            raise self.failure
        return self.answers.pop(0)

    def check_instruction_compliance(self, **kwargs: object) -> list[ComplianceFinding]:
        self.compliance_calls.append(dict(kwargs))
        outcome = self.compliance_verdicts.pop(0) if self.compliance_verdicts else []
        if isinstance(outcome, BaseException):  # a scripted gate failure plays itself — SIGINT included
            raise outcome
        return outcome


class SpyCache:
    """Cache spy: records save calls — the write-back happens after a green turn only."""

    def __init__(self, writable: bool = True) -> None:
        self.save_calls: list[CachedStep] = []
        self.writable = writable

    def save(self, step: CachedStep) -> bool:
        self.save_calls.append(step)
        return self.writable


class RecorderHook(StepHooks):
    """Hook recording healing events into a shared ``events`` list for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str]]] = []

    def on_healed(self, step_text: str, explanation: str) -> None:
        self.events.append(("on_healed", {"step_text": step_text, "explanation": explanation}))


def _script_input(monkeypatch: pytest.MonkeyPatch, answers: list[str | BaseException]) -> mock.Mock:
    """Replace ``builtins.input`` with a scripted answer queue; exceptions play their role."""
    queue = list(answers)

    def fake_input(prompt: str = "") -> str:
        answer = queue.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    scripted = mock.Mock(side_effect=fake_input, name="input")
    monkeypatch.setattr(builtins, "input", scripted)
    return scripted


def _failure() -> IncurableStepError:
    """The terminal failure the dialog opens over — an exhaustion with the failed code."""
    return IncurableStepError("click Pay", "budget exhausted", "Timeout 10000ms exceeded", code="old", verdict=None)


def _identity() -> StepIdentity:
    return StepIdentity(cache_key="checkout", step_type="action", normalized_text="click Pay")


class SteeringFixture:
    """Steering assembled with stubs and spies, plus the terminal failure under the dialog."""

    def __init__(self, provider: FakeProvider, tmp_path: Path) -> None:
        self.recorder = RecorderHook()
        self.reporter = StepReporter(hooks=[self.recorder])
        self.config = Config(cache_root=str(tmp_path))
        self.cache = SpyCache()
        self.provider = provider


class TestStepSteeringContract:
    """Contract tests: facade import, constructor substitution, steer call shape, frozen mirrors."""

    def test_step_steering_is_importable_from_facade(self) -> None:
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        assert isinstance(StepSteering, type)

    def test_constructor_accepts_the_four_contract_parameters(self, tmp_path: Path) -> None:
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        fixture = SteeringFixture(FakeProvider(), tmp_path)

        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)

        assert steering._reporter is fixture.reporter

    def test_constructor_substitutes_the_hook_less_reporter_when_omitted(self, tmp_path: Path) -> None:
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        fixture = SteeringFixture(FakeProvider(), tmp_path)

        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, None)

        assert isinstance(steering._reporter, StepReporter)
        assert steering._reporter.hooks == []

    def test_steer_declares_the_seven_contract_parameters_in_order(self) -> None:
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        parameters = list(inspect.signature(StepSteering.steer).parameters)

        assert parameters == [
            "self",
            "failure",
            "identity",
            "step_text",
            "step_type",
            "previous_steps",
            "page",
            "attempt_history",
        ]  # the raw sentence, the step type and the shared history thread through in the contract order

    def test_turn_record_helper_is_gone(self) -> None:
        from prettyplay.engine.steering import steering  # noqa: PLC0415 — cell-local module check

        assert not hasattr(steering, "_turn_record")  # the dialog-local turn-history helper is deleted, not adapted

    def test_steer_is_callable_with_the_seven_contract_parameters(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        fixture = SteeringFixture(FakeProvider(), tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["quit"])

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", ["open the page"], FakePage(), [])

        assert healed is None  # declined — no provider request, nothing raised
        assert fixture.provider.call_count == 0

    def test_facade_exports_step_steering_only(self) -> None:
        import prettyplay.engine.steering  # noqa: PLC0415 — cell facade check

        assert prettyplay.engine.steering.__all__ == ["StepSteering"]

    def test_steering_mirrors_the_practices(self) -> None:
        prompt_practice = GENERATION_PROMPT_PRACTICE.read_text(encoding="utf-8")
        prompt = prompt_practice.split("---", 1)[1].strip()  # the section after the separator is the prompt itself

        assert prompt == SYSTEM_PROMPT  # the frozen mirror of the generation practice

        practice = CHEAT_SHEET_PRACTICE.read_text(encoding="utf-8")
        assert practice == CHEAT_SHEET  # the frozen mirror of the cheat-sheet practice — the whole file, verbatim

        assert SYSTEM_PROMPT == ENGINE_SYSTEM_PROMPT  # the two frozen copies agree — no one-sided edit
        assert CHEAT_SHEET == ENGINE_CHEAT_SHEET  # the guided request and the engine request carry identical payloads

        # the cheat sheet is guidance, never an allowlist — the constant-comment wording carries
        assert "Guidance, not an allowlist" in CHEAT_SHEET

    def test_guided_request_carries_the_cheat_sheet(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The guided request carries the frozen cheat sheet — and the healed write-back lands."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["use count forms", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        request = provider.calls[0]
        assert request["cheat_sheet"] == CHEAT_SHEET  # the frozen mirror of the cheat-sheet practice
        assert ("page" + "_api") not in request  # the dead slot name, assembled — no literal for the sweep
        assert healed is not None  # the green turn healed
        assert [step.code for step in fixture.cache.save_calls] == [GENERATED_CODE]  # the write-back happened

    def test_steer_green_turn_with_default_verdict_heals_with_the_gate_on(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A gate-on config with the default empty verdict heals — one gate request, then the write-back."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])  # the default compliance verdict is [] — compliant
        fixture = SteeringFixture(provider, tmp_path)
        fixture.config = Config(cache_root=str(tmp_path), generation_prompt=INSTRUCTIONS)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["dismiss the modal first", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is not None
        assert healed.code == GENERATED_CODE
        assert len(provider.compliance_calls) == 1  # one gate request per green turn, no more
        call = provider.compliance_calls[0]
        assert call["prompt"] == COMPLIANCE_PROMPT  # the frozen mirror of the compliance practice
        assert call["user_instructions"] == INSTRUCTIONS
        assert call["step_text"] == "click Pay"
        assert call["step_type"] == "action"  # the honest input rides the verdict request
        assert call["attempt_history"] == []  # the first green turn — no records yet
        assert call["code"] == GENERATED_CODE
        assert len(fixture.cache.save_calls) == 1  # the compliant candidate reached the cache

    def test_steer_gate_off_config_makes_zero_compliance_calls(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A gate-off config (no generation instructions) heals with zero compliance calls — the old behavior."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)  # the default config holds no generation instructions
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["dismiss the modal first", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is not None
        assert provider.compliance_calls == []  # the gate never ran — fully the old behavior


class TestStepSteeringLogic:
    """Logic tests: approved and rejected turns, red turns, exit paths, local commands, dead pages."""

    def test_steer_green_turn_writes_back_and_reports_healed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A green approved turn writes the healed step back, reports on_healed and returns the step."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["dismiss the modal first", "y"])
        execute = mock.Mock(return_value=None)
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", execute)
        history: list[StepAttempt] = []

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            healed = steering.steer(
                _failure(), _identity(), "click Pay", "action", ["open the page"], FakePage(), history
            )

        assert healed is not None
        assert healed.code == GENERATED_CODE
        assert execute.call_count == 1  # one execution — the approved turn only
        assert len(fixture.cache.save_calls) == 1
        assert fixture.cache.save_calls[0].identity == _identity()
        assert fixture.recorder.events == [
            ("on_healed", {"step_text": "click Pay", "explanation": "healed interactively by engineer guidance"})
        ]

        request = provider.calls[0]
        assert request["guidance"] == "dismiss the modal first"
        assert request["recommendation"] is None  # the live guidance replaces the verdict diagnosis
        assert request["step_text"] == "click Pay"  # the raw sentence rides the request verbatim
        assert request["step_type"] == "action"
        assert request["attempt_history"] == []  # the first turn carries no records yet
        assert history == []  # a green turn never appends a record
        assert request["prompt"] == SYSTEM_PROMPT  # the frozen mirror of the generation practice
        assert request["cheat_sheet"] == CHEAT_SHEET  # the frozen mirror of the cheat-sheet practice
        assert request["previous_steps"] == ["open the page"]
        assert request["snapshot"] == "- heading: Pay\n- button: Pay now"
        assert request["page_url"] == DEFAULT_PAGE_URL  # the fresh URL rides every guided request
        assert request["screenshot"] is None  # send_screenshots defaults to False

        opened = [record for record in caplog.records if record.getMessage() == "steering_opened"]
        assert [record.step_text for record in opened] == ["click Pay"]
        guidance = [record for record in caplog.records if record.getMessage() == "steering_guidance"]
        assert [record.guidance for record in guidance] == ["dismiss the modal first"]  # the audit trail
        out = capsys.readouterr().out
        assert "generated code:" in out  # the complete code showed at the approval gate
        assert GENERATED_CODE in out
        assert "healed step written to the cache" in out

    def test_steer_green_approved_turn_heals(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An approved green turn heals: the complete code shows at the gate, the candidate executes exactly once."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        scripted = _script_input(monkeypatch, ["I solved the captcha", "y"])
        execute = mock.Mock(return_value=None)
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", execute)

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is not None
        assert healed.code == GENERATED_CODE
        assert healed.identity == _identity()
        assert [step.code for step in fixture.cache.save_calls] == [GENERATED_CODE]  # the cache holds it under identity
        assert fixture.recorder.events == [
            ("on_healed", {"step_text": "click Pay", "explanation": "healed interactively by engineer guidance"})
        ]
        assert execute.call_count == 1  # run_step_code executed exactly once — the approved turn

        out = capsys.readouterr().out
        assert "generated code:" in out
        assert GENERATED_CODE in out  # the complete code printed before the approval prompt
        assert [call.args[0] for call in scripted.call_args_list] == ["guidance> ", "run? [y/N] "]  # the gate asked

    def test_steer_request_carries_the_current_url(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Every guided request carries the fresh page URL; the banner shows it once — never per turn."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        url = "https://www.google.com/sorry?continuation=https://www.google.com/search"
        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["I solved the captcha", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(url=url), [])

        assert healed is not None
        assert provider.calls[0]["page_url"] == url  # the recorded request carries the fresh URL
        out = capsys.readouterr().out
        assert url in out  # the banner shows it on its url: line
        assert out.count("url:") == 1  # the banner only — no per-turn URL print

    def test_steer_rejected_turn_never_executes_and_declines(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A turn answered with anything but y never executes — the dialog declines, nothing is cached."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        scripted = _script_input(monkeypatch, ["try this", "n", "quit"])
        execute = mock.Mock(return_value=None)
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", execute)

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is None
        assert execute.call_count == 0  # nothing ran — the gate held
        assert fixture.cache.save_calls == []
        out = capsys.readouterr().out
        assert "generated code:" in out
        assert GENERATED_CODE in out  # the complete code showed before the approval prompt
        assert [call.args[0] for call in scripted.call_args_list] == [
            "guidance> ",
            "run? [y/N] ",
            "guidance> ",
        ]  # the rejection returned to the guidance prompt

    def test_steer_rejected_turn_records_and_the_next_request_carries_it(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A rejected turn appends its record; the next request carries it and the approved turn heals."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE, REGENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["try this", "n", "try hovering first", "y"])
        execute = mock.Mock(return_value=None)
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", execute)
        history: list[StepAttempt] = []

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), history)

        assert healed is not None
        assert healed.code == REGENERATED_CODE
        assert provider.calls[1]["attempt_history"] == [
            StepAttempt(
                code=GENERATED_CODE,
                error="",
                outcome=OUTCOME_REJECTED,
                url_before=DEFAULT_PAGE_URL,
                url_after=DEFAULT_PAGE_URL,
            ).render()
        ]  # the exact rejected record — same URL both sides, no error — reaches the next request
        assert len(history) == 1  # only the rejected turn recorded; the green turn never does
        assert execute.call_count == 1  # only the approved turn executed
        assert [step.code for step in fixture.cache.save_calls] == [REGENERATED_CODE]  # the healed step is cached

    @pytest.mark.parametrize(
        "answer_at_approval",
        ["", "quit", "Y", "yes"],
        ids=["enter", "quit-at-approval", "uppercase-y", "yes"],
    )
    def test_steer_enter_and_quit_at_approval_abort_the_turn(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        answer_at_approval: str,
    ) -> None:
        """Enter and quit typed at the approval prompt behave as a rejection — record appended, no execution."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE, REGENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["msg", answer_at_approval, "follow-up", "y"])
        execute = mock.Mock(return_value=None)
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", execute)

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is not None  # the follow-up turn heals
        assert provider.calls[1]["attempt_history"] == [
            StepAttempt(
                code=GENERATED_CODE,
                error="",
                outcome=OUTCOME_REJECTED,
                url_before=DEFAULT_PAGE_URL,
                url_after=DEFAULT_PAGE_URL,
            ).render()
        ]
        assert execute.call_count == 1  # the aborted turn never executed

    @pytest.mark.parametrize(
        "ending",
        [
            EOFError(),
            KeyboardInterrupt(),
            OSError("reading from stdin while output is captured"),
        ],
        ids=["eof", "sigint", "unreadable-stdin"],
    )
    def test_steer_approval_eof_or_sigint_declines_the_dialog(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        ending: BaseException,
    ) -> None:
        """EOF, SIGINT or an unreadable stdin at the approval prompt declines the dialog — nothing executes."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["try hovering first", ending])
        execute = mock.Mock(return_value=None)
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", execute)

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is None  # the original failure propagates from the executor
        assert provider.call_count == 1  # the turn generated; the approval ended the dialog
        assert execute.call_count == 0  # nothing ran
        assert fixture.cache.save_calls == []
        declined = [record for record in caplog.records if record.getMessage() == "steering_declined"]
        assert len(declined) == 1

    @pytest.mark.parametrize(
        ("red_outcome", "outcome_label"),
        [
            (AssertionError("element detached"), OUTCOME_FAILED_CHECK),
            (RuntimeError("element detached"), OUTCOME_EXECUTION_FAILED),
        ],
        ids=["failed-check", "execution-failed"],
    )
    def test_steer_red_turn_appends_history_and_next_request_carries_it(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        red_outcome: Exception,
        outcome_label: str,
    ) -> None:
        """A red turn appends its record with the outcome label of its exception kind; the next request carries it."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE, REGENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["try hovering first", "y", "then click", "y"])
        monkeypatch.setattr(
            f"{STEPPING_MODULE}.run_step_code",
            mock.Mock(side_effect=[red_outcome, None]),
        )
        history: list[StepAttempt] = []

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), history)

        assert healed is not None
        assert healed.code == REGENERATED_CODE
        assert provider.call_count == 2

        first, second = provider.calls
        assert first["attempt_history"] == []  # the first turn carries no history yet
        assert first["guidance"] == "try hovering first"
        assert second["attempt_history"] == [
            StepAttempt(
                code=GENERATED_CODE,
                error=format_step_error(red_outcome),  # the shared-history format — the engine loops' own
                outcome=outcome_label,  # a failed check for an AssertionError, execution failed otherwise
                url_before=DEFAULT_PAGE_URL,
                url_after=DEFAULT_PAGE_URL,
            ).render()
        ]
        assert second["guidance"] == "then click"
        assert len(fixture.cache.save_calls) == 1  # only the proven code is written back

    def test_steer_red_turn_records_the_full_outcome(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A red turn records the complete multi-line outcome verbatim — and never re-executes the failed code."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        red_outcome = AssertionError(
            "Locator expected to be visible\n"
            "Actual value: none\n"
            "Call log:\n"
            '  - waiting for get_by_role("button", name="Sign in")'
        )
        provider = FakeProvider(answers=[GENERATED_CODE, REGENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["try hovering first", "y", "then click", "y"])
        execute = mock.Mock(side_effect=[red_outcome, None])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", execute)
        history: list[StepAttempt] = []

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), history)

        assert healed is not None
        out = capsys.readouterr().out
        for line in str(red_outcome).splitlines():
            assert line in out  # the complete multi-line outcome shows — every line
        assert provider.calls[1]["attempt_history"] == [
            StepAttempt(
                code=GENERATED_CODE,
                error=format_step_error(red_outcome),  # a failed check's text is its message verbatim — all four lines
                outcome=OUTCOME_FAILED_CHECK,
                url_before=DEFAULT_PAGE_URL,
                url_after=DEFAULT_PAGE_URL,
            ).render()
        ]
        assert [call.args[0] for call in execute.call_args_list] == [
            GENERATED_CODE,
            REGENERATED_CODE,
        ]  # the failed code ran once, the next code once — no re-execution

    def test_steer_failed_execution_returns_to_the_prompt_without_re_execution(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A failed interactive execution is never re-executed — the settle window does not re-arm in the dialog."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        scripted = _script_input(monkeypatch, ["try hovering first", "y", "quit"])
        execute = mock.Mock(side_effect=[AssertionError("element detached")])

        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", execute)

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is None  # quit after the red turn — the original failure propagates
        assert execute.call_count == 1  # one execution per approved guidance message — no settle re-execution
        assert scripted.call_count == 3  # guidance, approval, guidance — the red turn returned to the prompt
        assert "turn failed: element detached" in capsys.readouterr().out

    def test_steer_sigint_during_guided_execution_escapes_directly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A SIGINT during the guided execution escapes directly — never swallowed into a red turn."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["try hovering first", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(side_effect=KeyboardInterrupt()))

        with pytest.raises(KeyboardInterrupt):
            steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert provider.call_count == 1  # the turn ran; the interrupt escaped its execution
        assert fixture.cache.save_calls == []  # never healed, never written back
        assert fixture.recorder.events == []  # no on_healed

    def test_steer_partial_screenshot_write_is_cleaned_up(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A temp screenshot whose write fails leaves nothing behind — the partial file is unlinked."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        created: list[Path] = []

        class ExplodingTempFile:
            """A temp handle whose write always fails after the file was created."""

            def __init__(self, prefix: str, suffix: str, delete: bool) -> None:
                with tempfile.NamedTemporaryFile(prefix=prefix, suffix=suffix, delete=False) as handle:
                    self.name = handle.name
                    created.append(Path(self.name))

            def __enter__(self) -> "ExplodingTempFile":
                return self

            def __exit__(self, *_args: object) -> bool:
                return False

            def write(self, data: bytes) -> int:
                raise OSError("disk full")

        provider = FakeProvider()
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["quit"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.tempfile", SimpleNamespace(NamedTemporaryFile=ExplodingTempFile))

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is None
        assert created  # the dialog attempted a temp screenshot
        assert not created[0].exists()  # the partial write was unlinked — nothing left to inspect
        assert "screenshot unavailable: disk full" in capsys.readouterr().out

    @pytest.mark.parametrize(
        "answer",
        [
            "quit",
            EOFError(),
            KeyboardInterrupt(),
            OSError("reading from stdin while output is captured"),
        ],
        ids=["quit", "eof", "sigint", "unreadable-stdin"],
    )
    def test_steer_quit_eof_sigint_return_none(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        answer: str | BaseException,
    ) -> None:
        """quit, EOF, SIGINT and an unreadable stdin end the dialog declined — no provider request, no hang."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, [answer])

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is None
        assert provider.call_count == 0
        declined = [record for record in caplog.records if record.getMessage() == "steering_declined"]
        assert len(declined) == 1

    def test_steer_provider_unavailable_ends_dialog(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A provider failure ends the dialog — the outcome prints, the original failure propagates at the caller."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(failure=LLMUnavailableError("llm unavailable: openai"))
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        scripted = _script_input(monkeypatch, ["try clicking the label instead"])

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is None
        assert provider.call_count == 1
        assert scripted.call_count == 1  # no approval prompt — the dialog ended before it
        assert "llm unavailable: openai" in capsys.readouterr().out
        assert fixture.recorder.events == []  # no on_healed — nothing healed

    def test_steer_local_commands_served_without_llm(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The four local commands serve the stored and live context — no provider request."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["code", "error", "snapshot", "screenshot", "quit"])

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is None
        assert provider.call_count == 0

        out = capsys.readouterr().out
        assert "old" in out  # the code command reprints the failed code
        assert "Timeout 10000ms exceeded" in out  # the error command reprints the error
        assert "- heading: Pay" in out  # the snapshot command prints the live snapshot
        assert "commands: snapshot | screenshot | error | code | quit" in out  # the banner hint

        paths = re.findall(r"\S*prettyplay-steering-\S+\.png", out)
        assert paths  # the banner and the screenshot command each printed the temp PNG path
        assert len(paths) == 2  # once by the banner, once by the screenshot command
        assert len(set(paths)) == 1  # one file per dialog — reused, never accumulated
        for printed in paths:
            assert Path(printed).exists()  # the printed paths point at real files

    def test_steer_survives_dead_page_banner_and_commands(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A dead page degrades every guarded interaction — the dialog continues and declines cleanly."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["snapshot", "screenshot", "quit"])

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], DeadPage(), [])

        assert healed is None
        out = capsys.readouterr().out
        assert out.count("url unavailable: Target closed") == 1  # the banner URL read degraded
        assert out.count("snapshot unavailable: Target closed") == 1  # the snapshot command — no banner fragment
        assert out.count("screenshot unavailable: Target closed") == 2  # the banner screenshot + the screenshot command
        assert [record.getMessage() for record in caplog.records if record.getMessage() == "steering_declined"]
        assert fixture.recorder.events == []  # no on_healed — nothing healed

    def test_steer_blank_guidance_line_reprompts_without_llm(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A blank line re-prompts — no log record, no LLM request, no history entry."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["", "   ", "quit"])

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is None
        assert provider.call_count == 0
        assert [record for record in caplog.records if record.getMessage() == "steering_guidance"] == []

    def test_steer_no_candidate_failure_empty_code(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A generation-path failure with no candidate renders its empty code — the banner and the code command."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["code", "click the close button first", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))
        failure = IncurableStepError("click Pay", "budget exhausted", "Timeout 10000ms exceeded", code="", verdict=None)

        healed = steering.steer(failure, _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is not None
        assert healed.code == GENERATED_CODE
        assert len(fixture.cache.save_calls) == 1

        out = capsys.readouterr().out
        assert out.count("code:") >= 2  # the banner code block and the code command both render the empty code
        assert fixture.recorder.events == [
            ("on_healed", {"step_text": "click Pay", "explanation": "healed interactively by engineer guidance"})
        ]

    def test_steer_banner_renders_the_terminal_render_and_url(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A verdict-bearing failure renders through the terminal render — the banner shows it and the URL."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider()
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["quit"])
        failure = IncurableStepError(
            "click Pay",
            "budget exhausted",
            "Timeout 10000ms exceeded",
            code="old",
            verdict=FailureVerdict("fixable", "the button is behind the modal", "dismiss the modal first"),
        )

        steering.steer(failure, _identity(), "click Pay", "action", [], FakePage(), [])

        out = capsys.readouterr().out
        assert "IncurableStepError: budget exhausted" in out  # the error: value opens with the render's first line
        assert "explanation: the button is behind the modal" in out  # the verdict explanation rides the render
        assert "recommendation: dismiss the modal first" in out
        assert DEFAULT_PAGE_URL in out  # the fresh URL rides the banner
        assert "verdict:" not in out  # no separate verdict lines — the render already carries them
        assert "intent:" not in out  # the header names the step — no separate intent line

    def test_steer_banner_renders_the_count_forms_code_sample(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The banner prints the failed code verbatim — the practice's count-forms sample, line by line."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider()
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["quit"])
        sample = (
            'videos = page.get_by_role("listitem")\n'
            "expect(videos.first).to_be_visible()\n"
            "assert videos.count() > 1\n"
        )  # the banner code block of the steering practice
        failure = IncurableStepError(
            "click Pay", "budget exhausted", "Timeout 10000ms exceeded", code=sample, verdict=None
        )

        steering.steer(failure, _identity(), "click Pay", "action", [], FakePage(), [])

        out = capsys.readouterr().out
        for line in sample.splitlines():
            assert line in out  # every count-forms line of the practice sample renders in the banner

    def test_steer_banner_indents_multi_line_values_once_to_the_value_column(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Every continuation line of a multi-line banner value renders exactly once, at the value column."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider()
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["quit"])
        sample = (
            'videos = page.get_by_role("listitem")\nexpect(videos.first).to_be_visible()\nassert videos.count() > 1\n'
        )
        failure = IncurableStepError(
            "click Pay", "budget exhausted", "Timeout 10000ms exceeded", code=sample, verdict=None
        )

        steering.steer(failure, _identity(), "click Pay", "action", [], FakePage(), [])

        out = capsys.readouterr().out
        assert 'code:     videos = page.get_by_role("listitem")' in out  # the label column opens the block
        for line in sample.splitlines()[1:]:
            assert out.count(line) == 1  # every continuation line renders exactly once — never duplicated
            assert f"{' ' * 10}{line}" in out  # and lands indented at the value column
            assert f"\n{line}" not in out  # never unindented at column zero

    def test_steer_banner_shows_render_and_url_without_snapshot_fragment(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The banner carries the terminal render and the URL — never a snapshot fragment; the command prints all."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider()
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)

        _script_input(monkeypatch, ["quit"])
        steering.steer(_failure(), _identity(), "click Pay", "action", [], TallSnapshotPage(), [])
        banner = capsys.readouterr().out
        assert "IncurableStepError: budget exhausted" in banner  # the error: line opens with the render's first line
        assert "url:" in banner  # the fresh URL rides the banner
        assert "commands: snapshot | screenshot | error | code | quit" in banner
        assert "- line 1" not in banner  # no line of the accessibility snapshot leaks into the banner
        assert "- line 30" not in banner

        _script_input(monkeypatch, ["snapshot", "quit"])
        steering.steer(_failure(), _identity(), "click Pay", "action", [], TallSnapshotPage(), [])
        served = capsys.readouterr().out
        assert "- line 1" in served  # the snapshot command prints the full tree, uncut
        assert "- line 30" in served

    def test_steer_guided_request_attaches_screenshot_when_enabled(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A send_screenshots project attaches the page PNG to the guided request."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        fixture.config = Config(cache_root=str(tmp_path), send_screenshots=True)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["dismiss the modal first", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is not None
        assert provider.calls[0]["screenshot"] == b"png"  # the guided request carries the image

    def test_steer_dead_page_screenshot_degrades_to_none_in_guided_request(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A dead page degrades the guided-request screenshot to None — the dialog continues."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        fixture.config = Config(cache_root=str(tmp_path), send_screenshots=True)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["dismiss the modal first", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], DeadPage(), [])

        assert healed is not None
        assert provider.calls[0]["screenshot"] is None  # a failed interaction never kills the request
        assert provider.calls[0]["snapshot"] == ""  # the guarded snapshot degraded to empty likewise
        assert "screenshot unavailable: Target closed" in capsys.readouterr().out

    def test_steer_dead_page_url_degrades(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A dead page URL read degrades: the banner omits the url line, the request carries None."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["dismiss the modal first", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))
        history: list[StepAttempt] = []

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], DeadPage(), history)

        assert healed is not None  # the dialog survived and completed the scripted green turn
        assert provider.calls[0]["page_url"] is None  # the failed read degrades to None in the request
        assert history == []  # the green turn records nothing; the degraded reads never surface as records
        out = capsys.readouterr().out
        assert "url unavailable: Target closed" in out  # the banner and the turn brackets noticed the dead reads
        assert "url:" not in out  # and the banner omits the url line

    def test_steer_read_only_cache_reports_the_skipped_write(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A read-only cache prints the honest skip — never a false written-to-the-cache line."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        fixture.cache.writable = False
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["dismiss the modal first", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is not None  # the green turn still returns the healed step
        assert len(fixture.cache.save_calls) == 1  # the save was attempted
        assert fixture.recorder.events == [
            ("on_healed", {"step_text": "click Pay", "explanation": "healed interactively by engineer guidance"})
        ]
        out = capsys.readouterr().out
        assert "cache write skipped (best-effort cache)" in out
        assert "written to the cache" not in out  # the success line is never printed on a skipped write

    def test_steer_busy_cache_save_reports_the_skipped_write(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A writable cache whose best-effort save skipped never prints the written-to-the-cache line."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)

        class BusyCache(SpyCache):
            """Writable cache spy whose save skips — the best-effort busy-target path."""

            def save(self, step: CachedStep) -> bool:
                super().save(step)
                return False  # writable, yet the atomic write skipped

        fixture.cache = BusyCache()
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["dismiss the modal first", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is not None  # the green turn still returns the healed step
        assert len(fixture.cache.save_calls) == 1  # the save was attempted
        out = capsys.readouterr().out
        assert "cache write skipped (best-effort cache)" in out
        assert "written to the cache" not in out  # the console line never claims the failed write

    def test_steer_high_finding_never_reaches_cache(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A high finding blocks the write-back: the violation shows, joins the history, the next guidance heals."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(  # candidate 1 green but high, candidate 2 green and compliant
            answers=[GENERATED_CODE, REGENERATED_CODE], compliance_verdicts=[[HIGH_FINDING], []]
        )
        fixture = SteeringFixture(provider, tmp_path)
        fixture.config = Config(cache_root=str(tmp_path), generation_prompt=INSTRUCTIONS)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["use the id attribute", "y", "now click the button", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is not None
        assert healed.code == REGENERATED_CODE
        assert [step.code for step in fixture.cache.save_calls] == [REGENERATED_CODE]  # candidate 1 never cached
        assert provider.call_count == 2  # the violation re-prompted — a second guided request ran
        assert provider.calls[1]["attempt_history"] == [
            StepAttempt(
                code=GENERATED_CODE,
                error=VIOLATION,
                outcome=OUTCOME_COMPLIANCE_BLOCKED,
                url_before=DEFAULT_PAGE_URL,
                url_after=DEFAULT_PAGE_URL,
            ).render()
        ]  # the blocked turn's complete record reaches the next request
        assert len(provider.compliance_calls) == 2  # every green candidate is gated
        out = capsys.readouterr().out
        assert "compliance violation — not written back" in out  # the violation line of the dialog
        assert VIOLATION in out
        assert fixture.recorder.events == [
            ("on_healed", {"step_text": "click Pay", "explanation": "healed interactively by engineer guidance"})
        ]  # on_healed fired for the compliant candidate only; no budgets exist here — the dialog consumes none

    def test_steer_high_finding_records_the_complete_violation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A high finding blocks the write-back — the record error carries the complete violation text."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE], compliance_verdicts=[[HIGH_FINDING]])
        fixture = SteeringFixture(provider, tmp_path)
        fixture.config = Config(cache_root=str(tmp_path), generation_prompt=INSTRUCTIONS)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["msg", "y", "quit"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))
        history: list[StepAttempt] = []

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), history)

        assert healed is None  # the dialog ended declined — the original failure propagates
        assert fixture.cache.save_calls == []  # no cache write
        assert history[0].outcome == OUTCOME_COMPLIANCE_BLOCKED  # the blocked turn joined the shared history
        assert history[0].error == VIOLATION  # the complete dimension-aware violation text
        out = capsys.readouterr().out
        assert "compliance violation — not written back" in out
        assert VIOLATION in out  # the complete violation text

    def test_steer_medium_findings_pass_with_warning_and_write_back(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Medium findings pass with a WARNING naming the step — the candidate still heals and writes back."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE], compliance_verdicts=[[MEDIUM_FINDING]])
        fixture = SteeringFixture(provider, tmp_path)
        fixture.config = Config(cache_root=str(tmp_path), generation_prompt=INSTRUCTIONS)
        cache = StepCache(fixture.config)
        steering = StepSteering(fixture.config, fixture.provider, cache, fixture.reporter)
        _script_input(monkeypatch, ["dismiss the modal first", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert healed is not None
        assert healed.code == GENERATED_CODE
        stored = cache.load(_identity())  # the real cache — the file exists after the write-back
        assert stored is not None
        assert stored.code.rstrip("\n") == GENERATED_CODE.rstrip("\n")  # the serializer appends a trailing \n
        assert fixture.recorder.events == [
            ("on_healed", {"step_text": "click Pay", "explanation": "healed interactively by engineer guidance"})
        ]
        passed = [record for record in caplog.records if record.getMessage() == "compliance findings passed"]
        assert len(passed) == 1
        assert passed[0].levelno == logging.WARNING
        assert passed[0].step_text == "click Pay"
        assert passed[0].findings == ["medium instruction: Prefer id attributes — minor"]
        assert "compliance violation" not in capsys.readouterr().out  # the passing path prints no blocking line

    @pytest.mark.parametrize(
        "outage",
        [
            ComplianceVerdictError("compliance verdict unparsable — received fragment: nope"),
            LLMUnavailableError("llm unavailable: openai request failed"),
        ],
        ids=["malformed-verdict", "provider-outage"],
    )
    def test_steer_gate_hard_failure_ends_dialog_returning_none(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
        outage: Exception,
    ) -> None:
        """A gate hard failure ends the dialog declined — the green candidate stays unchecked, nothing cached."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE], compliance_verdicts=[outage])
        fixture = SteeringFixture(provider, tmp_path)
        fixture.config = Config(cache_root=str(tmp_path), generation_prompt=INSTRUCTIONS)
        cache = StepCache(fixture.config)
        steering = StepSteering(fixture.config, fixture.provider, cache, fixture.reporter)
        _script_input(monkeypatch, ["dismiss the modal first", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))
        history = _anchored_history()

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), history)

        assert healed is None  # the dialog ended — the original terminal failure propagates at the caller
        assert cache.load(_identity()) is None  # the cache file is absent
        assert len(history) == 1  # the green candidate never recorded — the gate never finished
        assert fixture.recorder.events == []  # no on_healed
        failed = [record for record in caplog.records if record.getMessage() == "compliance gate failed"]
        assert len(failed) == 1
        assert failed[0].levelno == logging.WARNING
        assert failed[0].step_text == "click Pay"
        assert failed[0].gate_failure == str(outage)
        out = capsys.readouterr().out
        assert "compliance gate failed" in out
        assert str(outage) in out  # the gate failure text shows in the dialog
        assert "compliance violation" not in out  # the dialog ended before any verdict handling

    def test_steer_sigint_at_the_compliance_gate_escapes_directly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A SIGINT raised inside the compliance gate escapes the dialog directly — never a decline, never cached."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE], compliance_verdicts=[KeyboardInterrupt()])
        fixture = SteeringFixture(provider, tmp_path)
        fixture.config = Config(cache_root=str(tmp_path), generation_prompt=INSTRUCTIONS)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["dismiss the modal first", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        with pytest.raises(KeyboardInterrupt):
            steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), [])

        assert fixture.cache.save_calls == []  # nothing cached — the gate never finished
        out = capsys.readouterr().out
        assert "compliance gate failed" not in out  # a SIGINT is never swallowed into a gate-failure decline

    def test_steer_appends_rejected_record_with_same_url_on_both_sides(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A rejected turn appends its record into the shared history — one URL read, the same value both sides."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["fix the button", "n", "quit"])
        page = FakePage(url="https://s.example")
        history = _anchored_history()
        record0 = history[0].render()

        healed = steering.steer(_failure(), _identity(), "click the «Sign in» button", "action", [], page, history)

        assert healed is None  # quit after the rejected turn — the original failure propagates
        assert len(history) == 2  # record 0 intact, the rejected turn appended
        assert history[1].outcome == OUTCOME_REJECTED  # the code never ran
        assert history[1].error == ""
        assert history[1].code == GENERATED_CODE
        assert history[1].url_before == history[1].url_after == "https://s.example"  # one read, both sides
        assert provider.calls[0]["step_type"] == "action"  # the honest inputs ride the request
        assert provider.calls[0]["guidance"] == "fix the button"
        assert provider.calls[0]["attempt_history"] == [record0]  # record 0 anchors the dialog

    def test_steer_gates_with_shared_history_and_blocks_on_high_finding(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The write-back gate judges from the shared history — a high instruction finding blocks, the next heals."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(  # candidate 1 green but blocked, candidate 2 green and compliant
            answers=[GENERATED_CODE, REGENERATED_CODE], compliance_verdicts=[[HIGH_FINDING], []]
        )
        fixture = SteeringFixture(provider, tmp_path)
        fixture.config = Config(cache_root=str(tmp_path), generation_prompt=INSTRUCTIONS)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["try again", "y", "once more", "y"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))
        history = _anchored_history()

        healed = steering.steer(_failure(), _identity(), "click Pay", "action", [], FakePage(), history)

        assert healed is not None
        assert healed.code == REGENERATED_CODE
        assert [step.code for step in fixture.cache.save_calls] == [REGENERATED_CODE]  # after the second pass only
        assert len(provider.compliance_calls) == 2  # every green candidate is gated
        assert provider.calls[1]["attempt_history"] == [history[0].render(), history[1].render()]  # the grown history
        assert history[1].outcome == OUTCOME_COMPLIANCE_BLOCKED  # the blocked turn joined the shared history
        assert history[1].error == VIOLATION  # the dimension-aware violation text rides the record
