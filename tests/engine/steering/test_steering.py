"""Tests for the StepSteering REPL of the prettyplay.engine.steering cell."""

import builtins
import logging
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest
from playwright.sync_api import Error as PlaywrightError
from prettyplay.cache import CachedStep, StepIdentity
from prettyplay.config import Config
from prettyplay.engine.steering.steering import PAGE_API_SURFACE, SYSTEM_PROMPT
from prettyplay.failures import FailureVerdict, IncurableStepError, LLMUnavailableError
from prettyplay.reporting import StepHooks, StepReporter

STEPPING_MODULE = "prettyplay.engine.steering.steering"

GENERATED_CODE = "def step(page) -> None:\n    page.get_by_label('Close').click()\n"
REGENERATED_CODE = "def step(page) -> None:\n    page.get_by_role('button', name='Pay').click()\n"


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


class FakePage:
    """Fake page facade boundary: a snapshot and screenshot bytes."""

    def aria_snapshot(self) -> str:
        return "- heading: Pay\n- button: Pay now"

    def screenshot(self) -> bytes:
        return b"png"


class DeadPage:
    """Fake page facade whose every interaction raises the driver error."""

    def aria_snapshot(self) -> str:
        raise PlaywrightError("Target closed")

    def screenshot(self) -> bytes:
        raise PlaywrightError("Target closed")


class FakeProvider:
    """Fake provider boundary: scripted candidates with recorded requests."""

    def __init__(self, answers: list[str] | None = None, failure: Exception | None = None) -> None:
        self.answers = list(answers or [])
        self.failure = failure
        self.calls: list[dict[str, object]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        previous_steps: list[str],
        snapshot: str,
        screenshot: bytes | None,
        page_api: str,
        existing_code: str | None,
        error: str | None,
        recommendation: str | None,
        guidance: str | None,
        guidance_history: list[str],
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
                "guidance_history": list(guidance_history),
            }
        )
        if self.failure is not None:
            raise self.failure
        return self.answers.pop(0)


class SpyCache:
    """Cache spy: records save calls — the write-back happens after a green turn only."""

    def __init__(self, writable: bool = True) -> None:
        self.save_calls: list[CachedStep] = []
        self.writable = writable

    def save(self, step: CachedStep) -> None:
        self.save_calls.append(step)


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
    """Contract tests: facade import, constructor substitution, steer call shape."""

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

    def test_steer_is_callable_with_the_four_contract_parameters(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        fixture = SteeringFixture(FakeProvider(), tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["quit"])

        healed = steering.steer(_failure(), _identity(), ["open the page"], FakePage())

        assert healed is None  # declined — no provider request, nothing raised
        assert fixture.provider.call_count == 0

    def test_facade_exports_step_steering_only(self) -> None:
        import prettyplay.engine.steering  # noqa: PLC0415 — cell facade check

        assert prettyplay.engine.steering.__all__ == ["StepSteering"]


class TestStepSteeringLogic:
    """Logic tests: green and red turns, exit paths, local commands, dead pages."""

    def test_steer_green_turn_writes_back_and_reports_healed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A green guided turn writes the healed step back, reports on_healed and returns the step."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["dismiss the modal first"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            healed = steering.steer(_failure(), _identity(), ["open the page"], FakePage())

        assert healed is not None
        assert healed.code == GENERATED_CODE
        assert len(fixture.cache.save_calls) == 1
        assert fixture.cache.save_calls[0].identity == _identity()
        assert fixture.recorder.events == [
            ("on_healed", {"step_text": "click Pay", "explanation": "healed interactively by engineer guidance"})
        ]

        request = provider.calls[0]
        assert request["guidance"] == "dismiss the modal first"
        assert request["recommendation"] is None  # the live guidance replaces the verdict diagnosis
        assert request["existing_code"] == "old"
        assert request["error"] == "Timeout 10000ms exceeded"
        assert request["prompt"] == SYSTEM_PROMPT  # the frozen mirror of the generation practice
        assert request["page_api"] == PAGE_API_SURFACE  # the frozen mirror of the driver facade practice
        assert request["step_text"] == "click Pay"
        assert request["previous_steps"] == ["open the page"]
        assert request["snapshot"] == "- heading: Pay\n- button: Pay now"
        assert request["screenshot"] is None  # send_screenshots defaults to False

        opened = [record for record in caplog.records if record.getMessage() == "steering_opened"]
        assert [record.step_text for record in opened] == ["click Pay"]
        assert "healed step written to the cache" in capsys.readouterr().out

    def test_steer_red_turn_appends_history_and_next_request_carries_it(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A red turn appends the guidance-and-outcome line; the next request carries it as history."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE, REGENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["try hovering first", "then click"])
        monkeypatch.setattr(
            f"{STEPPING_MODULE}.run_step_code",
            mock.Mock(side_effect=[AssertionError("element detached"), None]),
        )

        healed = steering.steer(_failure(), _identity(), [], FakePage())

        assert healed is not None
        assert healed.code == REGENERATED_CODE
        assert provider.call_count == 2

        first, second = provider.calls
        assert first["guidance_history"] == []  # the first turn carries no history yet
        assert first["guidance"] == "try hovering first"
        assert second["guidance_history"] == ["try hovering first => element detached"]  # the red-turn line
        assert second["guidance"] == "then click"
        assert len(fixture.cache.save_calls) == 1  # only the proven code is written back

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
            healed = steering.steer(_failure(), _identity(), [], FakePage())

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
        _script_input(monkeypatch, ["try clicking the label instead"])

        healed = steering.steer(_failure(), _identity(), [], FakePage())

        assert healed is None
        assert provider.call_count == 1
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

        healed = steering.steer(_failure(), _identity(), [], FakePage())

        assert healed is None
        assert provider.call_count == 0

        out = capsys.readouterr().out
        assert "old" in out  # the code command reprints the failed code
        assert "Timeout 10000ms exceeded" in out  # the error command reprints the error
        assert "- heading: Pay" in out  # the snapshot command prints the live snapshot
        assert "commands: snapshot | screenshot | error | code | quit" in out  # the banner hint

        paths = re.findall(r"\S*prettyplay-steering-\S+\.png", out)
        assert paths  # the banner and the screenshot command each printed a temp PNG path
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
            healed = steering.steer(_failure(), _identity(), [], DeadPage())

        assert healed is None
        out = capsys.readouterr().out
        assert out.count("snapshot unavailable: Target closed") >= 2  # banner fragment + snapshot command
        assert out.count("screenshot unavailable: Target closed") >= 2  # the banner screenshot + the screenshot command
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
            healed = steering.steer(_failure(), _identity(), [], FakePage())

        assert healed is None
        assert provider.call_count == 0
        assert [record for record in caplog.records if record.getMessage() == "steering_guidance"] == []

    def test_steer_no_candidate_failure_empty_code(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A generation-path failure with no candidate carries the empty code — the request and banner render it."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
        fixture = SteeringFixture(provider, tmp_path)
        steering = StepSteering(fixture.config, fixture.provider, fixture.cache, fixture.reporter)
        _script_input(monkeypatch, ["code", "click the close button first"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))
        failure = IncurableStepError("click Pay", "budget exhausted", "Timeout 10000ms exceeded", code="", verdict=None)

        healed = steering.steer(failure, _identity(), [], FakePage())

        assert healed is not None
        assert healed.code == GENERATED_CODE
        assert provider.calls[0]["existing_code"] == ""  # empty code is a value, never None
        assert len(fixture.cache.save_calls) == 1

        out = capsys.readouterr().out
        assert out.count("code:") >= 2  # the banner code block and the code command both render the empty code
        assert fixture.recorder.events == [
            ("on_healed", {"step_text": "click Pay", "explanation": "healed interactively by engineer guidance"})
        ]

    def test_steer_banner_renders_the_verdict_context(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A verdict-bearing failure renders its explanation and recommendation in the banner."""
        from prettyplay.engine.steering import StepSteering  # noqa: PLC0415 — cell facade check

        provider = FakeProvider(answers=[GENERATED_CODE])
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

        steering.steer(failure, _identity(), [], FakePage())

        out = capsys.readouterr().out
        assert "verdict:  fixable — the button is behind the modal" in out
        assert "recommendation: dismiss the modal first" in out

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
        _script_input(monkeypatch, ["dismiss the modal first"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        healed = steering.steer(_failure(), _identity(), [], FakePage())

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
        _script_input(monkeypatch, ["dismiss the modal first"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        healed = steering.steer(_failure(), _identity(), [], DeadPage())

        assert healed is not None
        assert provider.calls[0]["screenshot"] is None  # a failed interaction never kills the request
        assert provider.calls[0]["snapshot"] == ""  # the guarded snapshot degraded to empty likewise
        assert "screenshot unavailable: Target closed" in capsys.readouterr().out

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
        _script_input(monkeypatch, ["dismiss the modal first"])
        monkeypatch.setattr(f"{STEPPING_MODULE}.run_step_code", mock.Mock(return_value=None))

        healed = steering.steer(_failure(), _identity(), [], FakePage())

        assert healed is not None  # the green turn still returns the healed step
        assert len(fixture.cache.save_calls) == 1  # the save was attempted
        assert fixture.recorder.events == [
            ("on_healed", {"step_text": "click Pay", "explanation": "healed interactively by engineer guidance"})
        ]
        out = capsys.readouterr().out
        assert "cache write skipped (read-only cache)" in out
        assert "written to the cache" not in out  # the success line is never printed on a skipped write
