"""Integration test: transport retries stay inside one logical engine attempt.

The cross-cell scenario of the bounded transport backoff — a real
``OpenAIProvider`` inside a real ``StepGenerator`` cycle; only the SDK client
boundary and the sleep/random primitives are faked. The central invariant: the
transport retries of one logical LLM attempt consume no engine budget.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from openai import APIConnectionError
from prettyplay.cache import RunBudgets, StepCache, StepIdentity
from prettyplay.config import Config
from prettyplay.engine import StepGenerator
from prettyplay.engine.polling import SettleWindow
from prettyplay.failures import LLMUnavailableError
from prettyplay.llm import OpenAIProvider
from prettyplay.reporting import StepHooks, StepReporter

WORKING_CODE = "def step(page) -> None:\n    page.goto('https://example.com')\n"


class FakeLocator:
    """Fake locator boundary: click records into the owning page's log."""

    def __init__(self, calls: list[tuple[str, ...]]) -> None:
        self._calls = calls

    def click(self) -> None:
        self._calls.append(("click",))


class FakePage:
    """Fake page facade: run/aria_snapshot/screenshot/url in the hand-built shape.

    The fake doubles as the handle and the raw page it hands out — the run
    primitive executes the action against the fake itself, so the generated
    step code drives the locator-factory surface directly.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    @property
    def url(self) -> str:
        return "https://example.com"

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))

    def get_by_role(self, role: str, name: str) -> FakeLocator:
        self.calls.append(("get_by_role", role, name))
        return FakeLocator(self.calls)

    def run(self, action: Callable[[object], object]) -> object:
        """The run primitive: executes the action against the fake itself, as a hand-built handle does."""
        return action(self)

    def aria_snapshot(self) -> str:
        return "- snapshot"

    def screenshot(self) -> bytes:
        return b"png"


class RecorderHook(StepHooks):
    """Hook boundary recording the generation events of the cycle."""

    def __init__(self) -> None:
        self.generation_started: list[int] = []
        self.cache_saved: list[str] = []

    def on_generation_started(self, step_text: str, attempt: int) -> None:
        self.generation_started.append(attempt)

    def on_cache_saved(self, step_text: str, filename: str) -> None:
        self.cache_saved.append(filename)


class TestTransportRetriesBudgetNeutrality:
    """The engine cycle with the provider's bounded transport retries inside it."""

    def test_engine_budgets_untouched_by_transport_retries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One transient SDK failure recovers inside the single engine attempt.

        Args:
            tmp_path: isolated cache root of the cycle.
            monkeypatch: the sleep and randomness boundaries.
            caplog: the WARNING trace of the retry.
        """
        outcomes: list[object] = [
            APIConnectionError(request=SimpleNamespace()),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=WORKING_CODE))]),
        ]

        def create(**_kwargs: object) -> object:
            outcome = outcomes.pop(0)

            if isinstance(outcome, Exception):
                raise outcome

            return outcome

        sdk_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=mock.MagicMock(side_effect=create)))
        )
        config = Config(cache_root=str(tmp_path), model="gpt-5", llm_request_attempts=2, generation_attempts=1)
        provider = OpenAIProvider(config)
        recorder = RecorderHook()
        reporter = StepReporter(hooks=[recorder])
        cache = StepCache(config, None, reporter)
        budgets = RunBudgets(generation_limit=1, healing_limit=2)
        generator = StepGenerator(config, provider, cache, budgets, reporter)
        identity = StepIdentity(
            cache_key="tests/test_transport.py", step_type="action", normalized_text="open the shop page"
        )
        page = FakePage()
        window = SettleWindow(None, 0.5)  # polling off — one execution per candidate
        sleeps: list[float] = []

        monkeypatch.setattr("time.sleep", sleeps.append)
        monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)
        caplog.set_level(logging.WARNING, logger="prettyplay")

        with mock.patch.object(provider, "_get_client", return_value=sdk_client):
            cached_step = generator.generate(identity, "open the shop page", "action", [], None, page, [], window)

        assert cached_step.code == WORKING_CODE
        assert page.calls == [("goto", "https://example.com")]  # the candidate really executed
        assert sdk_client.chat.completions.create.call_count == 2  # the resend stayed inside the attempt
        assert budgets._generation_used[identity.filename] == 1  # transport retries consumed nothing
        assert budgets.try_generation(identity) is False  # the single logical slot is exhausted

        # the trace: one WARNING, one pause, one engine attempt, one cache write
        assert sleeps == [1.0]
        assert [record.getMessage() for record in caplog.records] == ["llm request retry"]
        assert caplog.records[0].provider == "openai"
        assert caplog.records[0].operation == "generation"
        assert caplog.records[0].attempt == 1
        assert caplog.records[0].category == "connection"
        assert recorder.generation_started == [1]  # no second engine attempt occurred
        assert recorder.cache_saved == [identity.filename]

    @pytest.mark.parametrize("recovers", [True, False], ids=["recovers", "exhausts"])
    def test_compliance_retry_does_not_repeat_candidate_or_cache_without_verdict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovers: bool
    ) -> None:
        """Only the verdict request is resent after the browser action has run."""
        generation = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=WORKING_CODE))])
        verdict = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="[]"))])
        outcomes: list[object] = [
            generation,
            APIConnectionError(request=SimpleNamespace()),
            verdict if recovers else APIConnectionError(request=SimpleNamespace()),
        ]

        def create(**_kwargs: object) -> object:
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        sdk_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=mock.MagicMock(side_effect=create)))
        )
        config = Config(
            cache_root=str(tmp_path),
            model="gpt-5",
            generation_prompt="Only navigate to the requested page.",
            llm_request_attempts=2,
            generation_attempts=1,
        )
        provider = OpenAIProvider(config)
        recorder = RecorderHook()
        reporter = StepReporter(hooks=[recorder])
        cache = StepCache(config, None, reporter)
        budgets = RunBudgets(generation_limit=1, healing_limit=2)
        generator = StepGenerator(config, provider, cache, budgets, reporter)
        identity = StepIdentity(
            cache_key="tests/test_compliance_retry.py", step_type="action", normalized_text="open the shop page"
        )
        page = FakePage()
        window = SettleWindow(None, 0.5)
        sleeps: list[float] = []
        monkeypatch.setattr("time.sleep", sleeps.append)
        monkeypatch.setattr("random.uniform", lambda _a, _b: 0.0)

        with mock.patch.object(provider, "_get_client", return_value=sdk_client):
            if recovers:
                cached_step = generator.generate(identity, "open the shop page", "action", [], None, page, [], window)
                assert cached_step.code == WORKING_CODE
            else:
                with pytest.raises(LLMUnavailableError):
                    generator.generate(identity, "open the shop page", "action", [], None, page, [], window)

        assert sdk_client.chat.completions.create.call_count == 3
        assert page.calls == [("goto", "https://example.com")]
        assert budgets._generation_used[identity.filename] == 1
        assert sleeps == [1.0]
        assert recorder.cache_saved == ([identity.filename] if recovers else [])
        assert (cache.load(identity) is not None) is recovers
