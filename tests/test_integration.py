"""Integration tests of the full step cycle through the public ``PrettyPlay`` facade."""

import asyncio
import builtins
import contextlib
import logging
import os
import tempfile
import traceback
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest import mock

import greenlet
import prettyplay
import pytest
from playwright.sync_api import Locator
from prettyplay import BrowserConfig, PrettyPlay
from prettyplay.cache import CachedStep, StepCache, StepIdentity, normalize_step_text
from prettyplay.config import Config, load_config
from prettyplay.failures import IncurableStepError, ProductDefectError
from prettyplay.llm import ComplianceFinding, FailureClassification, LLMProvider, ScenarioStep
from prettyplay.reporting import StepHooks, StepReporter

OPEN_LOGIN_CODE = "def step(page) -> None:\n    page.goto('https://login.example.com')\n"
WORKING_CODE = "def step(page) -> None:\n    page.goto('https://app.example.com')\n"


class FakeLocator:
    """Fake locator boundary recording element calls into the log of the owning page."""

    def __init__(self, calls: list[tuple[str, ...]]) -> None:
        self._calls = calls

    def click(self) -> None:
        self._calls.append(("click",))

    def fill(self, value: str) -> None:
        self._calls.append(("fill", value))

    def select_option(self, value: str) -> None:
        self._calls.append(("select_option", value))

    def expect_visible(self) -> None:
        self._calls.append(("expect_visible",))

    def expect_text(self, text: str) -> None:
        self._calls.append(("expect_text", text))

    def expect_enabled(self) -> None:
        self._calls.append(("expect_enabled",))


class FakePage:
    """Fake page handle in the hand-built shape: ``run``/``aria_snapshot``/``screenshot``.

    The fake doubles as the handle and the raw page it hands out — the run
    primitive executes the action against the fake itself, so the step code
    drives the locator-factory surface directly. Records calls; broken
    lookups simulate a rotted UI.
    """

    def __init__(self, broken_lookups: frozenset[str] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._broken_lookups = broken_lookups or frozenset()
        self.close_count = 0

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))

    def get_by_role(self, role: str, name: str) -> FakeLocator:
        return self._lookup("get_by_role", (role, name))

    def get_by_label(self, label: str) -> FakeLocator:
        return self._lookup("get_by_label", (label,))

    def get_by_text(self, text: str) -> FakeLocator:
        return self._lookup("get_by_text", (text,))

    def run(self, action: Callable[[object], object]) -> object:
        """The run primitive: executes the action against the fake itself, as a hand-built handle does."""
        return action(self)

    def aria_snapshot(self) -> str:
        return "- button 'Войти'"

    def screenshot(self) -> bytes:
        return b"png"

    @property
    def url(self) -> str:
        return "https://app.example.com"

    @property
    def closed(self) -> bool:
        return self.close_count > 0

    def close(self) -> None:
        self.close_count += 1

    def _lookup(self, method: str, args: tuple[str, ...]) -> FakeLocator:
        """Record the lookup and fail it when the rotted UI no longer has the element."""
        self.calls.append((method, *args))
        if method in self._broken_lookups:
            raise AssertionError("element not found")
        return FakeLocator(self.calls)


class StubProvider(LLMProvider):
    """Stub LLM boundary: scripted generation answers, verdicts, recorded requests."""

    def __init__(
        self,
        answers: list[str] | None = None,
        verdict: FailureClassification | None = None,
        compliance_verdicts: list[list[ComplianceFinding]] | None = None,
    ) -> None:
        self.answers = list(answers or [])
        self.verdict = verdict
        self.compliance_verdicts = list(compliance_verdicts) if compliance_verdicts is not None else None
        self.generation_requests: list[dict[str, object]] = []
        self.classification_requests: list[dict[str, object]] = []
        self.compliance_requests: list[dict[str, object]] = []

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str = "",
        step_text: str = "",
        step_type: str = "",
        previous_steps: list[str] | None = None,
        group_prompt: str | None = None,
        snapshot: str = "",
        page_url: str | None = None,
        screenshot: bytes | None = None,
        cheat_sheet: str = "",
        attempt_history: list[str] | None = None,
        recommendation: str | None = None,
        guidance: str | None = None,
    ) -> str:
        self.generation_requests.append(
            {
                "prompt": prompt,
                "user_instructions": user_instructions,
                "step_text": step_text,
                "step_type": step_type,
                "previous_steps": list(previous_steps),  # copy: the scenario context lives on
                "snapshot": snapshot,
                "page_url": page_url,
                "screenshot": screenshot,
                "cheat_sheet": cheat_sheet,
                "attempt_history": list(attempt_history or []),  # copy: the history lives on
                "recommendation": recommendation,
                "guidance": guidance,
            }
        )
        if not self.answers:
            raise AssertionError("stub provider has no generation answers left")
        return self.answers.pop(0)

    def classify_step_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        code: str,
        error: str,
        snapshot: str,
        screenshot: bytes | None,
    ) -> FailureClassification:
        self.classification_requests.append(
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
        return self.verdict

    def check_instruction_compliance(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        step_type: str,
        code: str,
        attempt_history: list[str] | None = None,
    ) -> list[ComplianceFinding]:
        self.compliance_requests.append(
            {
                "prompt": prompt,
                "user_instructions": user_instructions,
                "step_text": step_text,
                "step_type": step_type,
                "code": code,
                "attempt_history": list(attempt_history or []),
            }
        )
        if self.compliance_verdicts is not None:
            return self.compliance_verdicts.pop(0)
        return []  # compliant by default — the gate passes, the generation assertions hold


class ForbiddenProvider(LLMProvider):
    """Stub provider failing the run the moment a cached path touches the LLM boundary."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str = "",
        step_text: str = "",
        step_type: str = "",
        previous_steps: list[str] | None = None,
        group_prompt: str | None = None,
        snapshot: str = "",
        page_url: str | None = None,
        screenshot: bytes | None = None,
        cheat_sheet: str = "",
        attempt_history: list[str] | None = None,
        recommendation: str | None = None,
        guidance: str | None = None,
    ) -> str:
        self.calls += 1
        raise AssertionError("provider must not be called")

    def classify_step_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        code: str,
        error: str,
        snapshot: str,
        screenshot: bytes | None,
    ) -> FailureClassification:
        self.calls += 1
        raise AssertionError("provider must not be called")

    def check_instruction_compliance(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str,
        step_text: str,
        step_type: str,
        code: str,
        attempt_history: list[str] | None = None,
    ) -> list[ComplianceFinding]:
        self.calls += 1
        raise AssertionError("provider must not be called")


class RecorderHook(StepHooks):
    """Hook recording every step-cycle event into a shared ``events`` list for assertions."""

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

    def on_step_finished(self, step_text: str, step_type: str, outcome: str) -> None:
        self.events.append(("on_step_finished", {"step_text": step_text, "step_type": step_type, "outcome": outcome}))

    def on_generation_started(self, step_text: str, attempt: int) -> None:
        self.events.append(("on_generation_started", {"step_text": step_text, "attempt": attempt}))

    def on_healing_started(self, step_text: str, category: str) -> None:
        self.events.append(("on_healing_started", {"step_text": step_text, "category": category}))

    def on_healed(self, step_text: str, explanation: str) -> None:
        self.events.append(("on_healed", {"step_text": step_text, "explanation": explanation}))

    def on_cache_saved(self, step_text: str, filename: str) -> None:
        self.events.append(("on_cache_saved", {"step_text": step_text, "filename": filename}))

    def on_cache_skipped(self, step_text: str, reason: str) -> None:
        self.events.append(("on_cache_skipped", {"step_text": step_text, "reason": reason}))


@pytest.fixture(autouse=True)
def no_llm_credentials(monkeypatch):
    """Run without provider keys: the cached path needs none of them."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def clean_prettyplay_env(monkeypatch):
    """Unset every PRETTYPLAY_* variable: the file layer each test loads stays deterministic."""
    for name in list(os.environ):
        if name.startswith("PRETTYPLAY_"):
            monkeypatch.delenv(name, raising=False)


def test_pretty_config_exported_and_get_runtime_removed() -> None:
    """The embedding contract: PrettyConfig, BrowserConfig and StepHooks re-exported, the singleton gone."""
    assert prettyplay.PrettyConfig is Config
    assert prettyplay.BrowserConfig is BrowserConfig
    assert prettyplay.StepHooks is StepHooks
    assert prettyplay.__all__ == [
        "PrettyPlay",
        "StepHooks",
        "PrettyConfig",
        "BrowserConfig",
        "PrettyplayRuntime",
        "StepExecutor",
        "StepGroup",
    ]
    assert not hasattr(prettyplay, "get_runtime")


@contextlib.contextmanager
def installed_test(
    cache_root: Path,
    provider: LLMProvider,
    page: FakePage,
    cache_key: str,
    cache_path: str | None = None,
) -> Iterator[PrettyPlay]:
    """Build one PrettyPlay on a tmp cache with stubbed provider and page boundaries.

    Per-test construction: the test resolves its config from the patched loader
    (never the real repo pyproject), owns its runtime, and both external
    boundaries — the provider factory and the page — are patched on that one
    runtime instance.
    """
    with (
        mock.patch("prettyplay.scenario.load_config", return_value=Config(cache_root=str(cache_root))),
        mock.patch("prettyplay.runtime.create_provider", return_value=provider),
    ):
        test = PrettyPlay(cache_key, cache_path=cache_path)
        with mock.patch.object(test._runtime, "open_page", return_value=page):
            yield test


def seed_step(  # noqa: PLR0913 — the address fields mirror the identity triple plus the store root
    cache_root: Path,
    step_text: str,
    code: str,
    *,
    cache_key: str,
    step_type: str = "action",
    cache_path: str | None = None,
) -> StepIdentity:
    """Pre-write a step file so the scenario runs the cache-hit path without the LLM."""
    identity = StepIdentity(
        cache_key=cache_key,
        step_type=step_type,
        normalized_text=normalize_step_text(step_text),
    )
    StepCache(Config(cache_root=str(cache_root)), cache_path, StepReporter(hooks=[])).save(
        CachedStep(identity=identity, code=code, created_at="2026-09-08")
    )
    return identity


@contextlib.contextmanager
def configured_test(config: Config, provider: LLMProvider, page: FakePage) -> Iterator[PrettyPlay]:
    """Build one PrettyPlay through the real layered loader carrying the given config.

    Unlike :func:`installed_test` the settings resolve through the real
    ``load_config`` merge — the programmatic layer wins over the file layer,
    exactly as an integrator's ``PrettyPlay(..., config=PrettyConfig(...))``
    does; the provider factory and the page stay stubbed boundaries.
    """
    with mock.patch("prettyplay.runtime.create_provider", return_value=provider):
        test = PrettyPlay("login-flow", config=config)
        with mock.patch.object(test._runtime, "open_page", return_value=page):
            yield test


def test_cached_step_runs_without_llm(tmp_path: Path) -> None:
    """Flow B: a cached step executes through the whole cycle with no LLM involvement."""
    provider = ForbiddenProvider()
    page = FakePage()
    hook = RecorderHook()
    seed_step(tmp_path, "открыть страницу логина", OPEN_LOGIN_CODE, cache_key="login-flow")

    with installed_test(tmp_path, provider, page, "login-flow") as test:
        test.add_hooks(hook)
        test.step("открыть страницу логина")
        test.close()

    assert page.calls == [("goto", "https://login.example.com")]
    assert hook.events == [
        ("on_step_started", {"step_text": "открыть страницу логина", "step_type": "action"}),
        ("on_step_passed", {"step_text": "открыть страницу логина", "step_type": "action"}),
        ("on_step_finished", {"step_text": "открыть страницу логина", "step_type": "action", "outcome": "passed"}),
    ]
    assert provider.calls == 0


def test_scenario_context_feeds_next_generation(tmp_path: Path) -> None:
    """Flow A: the sentences of the earlier steps feed the generation request of the next one."""
    provider = StubProvider(answers=[WORKING_CODE, WORKING_CODE])
    page = FakePage()
    hook = RecorderHook()

    with installed_test(tmp_path, provider, page, "k") as test:
        test.add_hooks(hook)
        test.step("шаг один")
        test.step("шаг два")
        test.close()

    assert [request["previous_steps"] for request in provider.generation_requests] == [
        [],
        [ScenarioStep(sentence="шаг один")],  # typed records — the sentence plus its empty group membership
    ]
    assert [event for event, _payload in hook.events if event == "on_step_passed"] == [
        "on_step_passed",
        "on_step_passed",
    ]
    assert len([event for event, _payload in hook.events if event == "on_cache_saved"]) == 2


def test_per_test_generation_prompt_reaches_the_provider_request(tmp_path: Path, monkeypatch) -> None:
    """ADR-3 end to end: the per-test config layer carries the instructions into every generation request."""
    monkeypatch.delenv("PRETTYPLAY_GENERATION_PROMPT", raising=False)
    provider = StubProvider(answers=[WORKING_CODE])
    page = FakePage()

    with mock.patch("prettyplay.runtime.create_provider", return_value=provider):
        # real load_config: the programmatic layer goes through the real merge, not a stub
        test = PrettyPlay(
            "login-flow",
            config=Config(cache_root=str(tmp_path), generation_prompt="prefer data-test-id"),
        )
        with mock.patch.object(test._runtime, "open_page", return_value=page):
            test.step("open the app page")
            test.close()

    assert provider.generation_requests[0]["user_instructions"] == "prefer data-test-id"
    assert provider.generation_requests[0]["step_type"] == "action"  # the honest inputs reach the request
    assert provider.generation_requests[0]["attempt_history"] == []  # first attempt — no records yet
    # the gate-on generation made exactly one verdict request carrying the instructions and the executed code
    assert len(provider.compliance_requests) == 1
    assert provider.compliance_requests[0]["user_instructions"] == "prefer data-test-id"
    assert provider.compliance_requests[0]["step_type"] == "action"  # the step type reaches the verdict request
    assert provider.compliance_requests[0]["code"] == WORKING_CODE
    assert provider.compliance_requests[0]["attempt_history"] == []  # green first attempt — no ATTEMPT HISTORY block
    assert page.calls == [("goto", "https://app.example.com")]  # generated code executed


def test_replayed_cached_step_never_runs_the_gate(tmp_path: Path) -> None:
    """The gate never runs on replayed cached code — even with the compliance gate switched on."""
    provider = ForbiddenProvider()  # any gate call would fail the run the moment it happens
    page = FakePage()
    seed_step(tmp_path, "открыть страницу логина", OPEN_LOGIN_CODE, cache_key="login-flow")

    with configured_test(
        Config(cache_root=str(tmp_path), generation_prompt="prefer data-test-id"), provider, page
    ) as test:
        test.step("открыть страницу логина")
        test.close()

    assert page.calls == [("goto", "https://login.example.com")]  # the cached code replayed
    assert provider.calls == 0  # replay never touches the LLM boundary — the compliance gate included


def test_rot_healing_regenerates_rewrites_cache_and_passes(tmp_path: Path) -> None:
    """Flow C: a rotted cached step is classified, regenerated, re-cached and passes."""
    step_text = "нажать Войти"
    broken_code = "def step(page) -> None:\n    page.get_by_role('button', name='Войти').click()\n"
    healed_code = "def step(page) -> None:\n    page.get_by_text('Войти').click()\n"
    identity = seed_step(tmp_path, step_text, broken_code, cache_key="login-flow")
    provider = StubProvider(
        answers=[healed_code],
        verdict=FailureClassification(
            category="rot", explanation="кнопка переименована", recommendation="проверить шаг"
        ),
    )
    page = FakePage(broken_lookups=frozenset({"get_by_role"}))
    hook = RecorderHook()

    with installed_test(tmp_path, provider, page, "login-flow") as test:
        test.add_hooks(hook)
        test.step(step_text)
        test.close()

    assert page.calls == [("get_by_role", "button", "Войти"), ("get_by_text", "Войти"), ("click",)]
    # a cache file carries the code with a trailing newline — compare without the tail
    assert provider.classification_requests[0]["code"].rstrip("\n") == broken_code.rstrip("\n")
    assert provider.classification_requests[0]["error"] == "element not found"
    # record 0 anchors the regeneration request: the original cached code with its replay error
    record0 = provider.generation_requests[0]["attempt_history"][0]
    assert record0.startswith("original cached code\n")
    assert broken_code.rstrip("\n") in record0
    assert "error:\nelement not found" in record0
    assert hook.events == [
        ("on_step_started", {"step_text": "нажать Войти", "step_type": "action"}),
        # the engine events carry the raw sentence — the normalization is an addressing key only
        ("on_healing_started", {"step_text": "нажать Войти", "category": "rot"}),
        ("on_generation_started", {"step_text": "нажать Войти", "attempt": 1}),
        # the cache event carries the identity text — the cache cell addresses by the normalized form
        ("on_cache_saved", {"step_text": "нажать войти", "filename": identity.filename}),
        ("on_healed", {"step_text": "нажать Войти", "explanation": "кнопка переименована"}),
        ("on_step_passed", {"step_text": "нажать Войти", "step_type": "action"}),
        ("on_step_finished", {"step_text": "нажать Войти", "step_type": "action", "outcome": "passed"}),
    ]
    rewritten = (tmp_path / identity.filename).read_text(encoding="utf-8")
    assert "get_by_text" in rewritten
    assert "get_by_role" not in rewritten


def test_retired_members_fail_loudly_on_cached_steps(tmp_path: Path) -> None:
    """The accepted break: a cached step calling a retired member fails loudly and heals to the mirror surface."""
    step_text = "нажать Войти"
    retired_code = "def step(page) -> None:\n    page.find_by_role('button', name='Войти').click()\n"
    regenerated_code = "def step(page) -> None:\n    page.get_by_role('button', name='Войти').click()\n"
    identity = seed_step(tmp_path, step_text, retired_code, cache_key="login-flow")
    provider = StubProvider(
        answers=[regenerated_code],
        verdict=FailureClassification(
            category="rot", explanation="вызов устарел после смены поверхности", recommendation="обновить шаг"
        ),
    )
    page = FakePage()  # the mirror surface only: find_by_role no longer exists on it
    hook = RecorderHook()

    with installed_test(tmp_path, provider, page, "login-flow") as test:
        test.add_hooks(hook)
        test.step(step_text)  # non-strict: the classify → rot → regenerate loop heals lazily
        test.close()

    # the replay failed loudly on the retired member and the failure traveled to the classification
    assert provider.classification_requests[0]["error"] == (
        "AttributeError: 'FakePage' object has no attribute 'find_by_role'"
    )
    # record 0 anchors the regeneration request: the retired code with its replay error
    record0 = provider.generation_requests[0]["attempt_history"][0]
    assert record0.startswith("original cached code\n")
    assert retired_code.rstrip("\n") in record0
    assert "error:\nAttributeError: 'FakePage' object has no attribute 'find_by_role'" in record0
    assert page.calls == [("get_by_role", "button", "Войти"), ("click",)]  # the regenerated candidate ran
    assert [event for event, _payload in hook.events] == [
        "on_step_started",
        "on_healing_started",
        "on_generation_started",
        "on_cache_saved",
        "on_healed",
        "on_step_passed",
        "on_step_finished",
    ]
    rewritten = (tmp_path / identity.filename).read_text(encoding="utf-8")
    assert "get_by_role" in rewritten
    assert "find_by" not in rewritten  # the regenerated code contains no retired name


def test_cache_path_subdirectories_do_not_collide(tmp_path: Path) -> None:
    """The cache subdirectory is part of the address: same triple, different steps."""
    checkout_code = "def step(page) -> None:\n    page.goto('https://checkout.example.com')\n"
    marketing_code = "def step(page) -> None:\n    page.goto('https://marketing.example.com')\n"
    provider = ForbiddenProvider()
    checkout_page = FakePage()
    marketing_page = FakePage()
    identity = seed_step(tmp_path, "открыть страницу", checkout_code, cache_key="k", cache_path="checkout")
    seed_step(tmp_path, "открыть страницу", marketing_code, cache_key="k", cache_path="marketing")

    with installed_test(tmp_path, provider, checkout_page, "k", cache_path="checkout") as test:
        test.step("открыть страницу")
        test.close()

    with installed_test(tmp_path, provider, marketing_page, "k", cache_path="marketing") as test:
        test.step("открыть страницу")
        test.close()

    assert checkout_page.calls == [("goto", "https://checkout.example.com")]
    assert marketing_page.calls == [("goto", "https://marketing.example.com")]
    assert provider.calls == 0
    assert (tmp_path / "checkout" / identity.filename).exists()
    assert (tmp_path / "marketing" / identity.filename).exists()


def test_generated_failed_check_verdict_fails_the_test_loudly(tmp_path: Path) -> None:
    """Flow A failure: a first-run candidate check fails, stops the retries and carries the verdict."""
    step_text = "see the welcome banner"
    check_code = "def step(page) -> None:\n    page.get_by_text('Welcome back').expect_visible()\n"
    provider = StubProvider(
        answers=[check_code],
        verdict=FailureClassification(
            category="product_defect", explanation="the banner is genuinely missing", recommendation="file a bug"
        ),
    )
    page = FakePage(broken_lookups=frozenset({"get_by_text"}))  # lookup fails: the check did not hold
    hook = RecorderHook()

    with installed_test(tmp_path, provider, page, "login-flow") as test:
        test.add_hooks(hook)
        with pytest.raises(ProductDefectError) as excinfo:
            test.expect(step_text)
        test.close()

    assert excinfo.value.verdict is not None
    assert excinfo.value.verdict.category == "product_defect"
    assert len(provider.generation_requests) == 1  # retries stopped: budget not spent on a failed check
    assert len(provider.classification_requests) == 1
    assert provider.classification_requests[0]["error"] == "element not found"
    identity = StepIdentity(
        cache_key="login-flow", step_type="assertion", normalized_text=normalize_step_text(step_text)
    )
    assert not (tmp_path / identity.filename).exists()  # failed candidate not cached
    assert [event for event, _payload in hook.events] == [
        "on_step_started",
        "on_generation_started",
        "on_step_failed",
        "on_step_verdict",
        "on_step_finished",
    ]
    frames = [entry.filename for entry in traceback.extract_tb(excinfo.value.__traceback__)]
    assert frames[-1].endswith("scenario.py")  # traceback folded to the facade boundary
    assert not any(entry.endswith(("generator.py", "executor.py", "classification.py")) for entry in frames)


def test_product_defect_verdict_fails_the_test_loudly(tmp_path: Path) -> None:
    """A classified product defect surfaces through PrettyPlay.step with an intact cache."""
    step_text = "нажать Войти"
    broken_code = "def step(page) -> None:\n    page.get_by_role('button', name='Войти').click()\n"
    identity = seed_step(tmp_path, step_text, broken_code, cache_key="login-flow")
    provider = StubProvider(
        verdict=FailureClassification(
            category="product_defect", explanation="ожидание не оправдалось", recommendation="чинить продукт"
        ),
    )
    page = FakePage(broken_lookups=frozenset({"get_by_role"}))
    hook = RecorderHook()

    with installed_test(tmp_path, provider, page, "login-flow") as test:
        test.add_hooks(hook)
        with pytest.raises(ProductDefectError) as excinfo:
            test.step(step_text)
        test.close()

    assert excinfo.value.step_text == step_text  # the raw sentence — never the casefolded form
    assert excinfo.value.message == "ожидание не оправдалось"
    assert provider.generation_requests == []  # product defect is not regenerated
    rewritten = (tmp_path / identity.filename).read_text(encoding="utf-8")
    assert "get_by_role" in rewritten  # cache untouched
    assert hook.events == [
        ("on_step_started", {"step_text": "нажать Войти", "step_type": "action"}),
        ("on_healing_started", {"step_text": "нажать Войти", "category": "product_defect"}),
        (
            "on_step_failed",
            # the full structured render — str(exc), never re-composed
            {"step_text": "нажать Войти", "step_type": "action", "error": str(excinfo.value)},
        ),
        (
            "on_step_verdict",
            {
                "step_text": "нажать Войти",
                "category": "product_defect",
                "explanation": "ожидание не оправдалось",
                "recommendation": "чинить продукт",
            },
        ),
        ("on_step_finished", {"step_text": "нажать Войти", "step_type": "action", "outcome": "failed"}),
    ]
    # full failure cycle: traceback folded to the facade boundary, message ends with the verdict render
    frames = [entry.filename for entry in traceback.extract_tb(excinfo.value.__traceback__)]
    assert frames[-1].endswith("scenario.py")
    assert not any(entry.endswith(("healer.py", "executor.py", "classification.py")) for entry in frames)
    rendered = str(excinfo.value)
    assert rendered.index("ожидание не оправдалось") < rendered.index("explanation:")
    assert "category:" not in rendered  # the category travels in structured fields, never in the render
    assert rendered.endswith("recommendation: чинить продукт")


def test_incurable_verdict_fails_with_verdict_fields(tmp_path: Path) -> None:
    """An incurable classification surfaces with the verdict explanation and recommendation."""
    step_text = "нажать Войти"
    broken_code = "def step(page) -> None:\n    page.get_by_role('button', name='Войти').click()\n"
    identity = seed_step(tmp_path, step_text, broken_code, cache_key="login-flow")
    provider = StubProvider(
        verdict=FailureClassification(
            category="incurable",
            explanation="текст шага не соответствует реальности",
            recommendation="переформулируйте шаг",
        ),
    )
    page = FakePage(broken_lookups=frozenset({"get_by_role"}))
    hook = RecorderHook()

    with installed_test(tmp_path, provider, page, "login-flow") as test:
        test.add_hooks(hook)
        with pytest.raises(IncurableStepError) as excinfo:
            test.step(step_text)
        test.close()

    assert excinfo.value.reason == "текст шага не соответствует реальности"
    # healer's verdict, not fallback
    assert excinfo.value.recommendation == "переформулируйте шаг"
    assert provider.generation_requests == []  # healing requests no regeneration
    rewritten = (tmp_path / identity.filename).read_text(encoding="utf-8")
    assert "get_by_role" in rewritten  # cache untouched
    assert hook.events == [
        ("on_step_started", {"step_text": "нажать Войти", "step_type": "action"}),
        ("on_healing_started", {"step_text": "нажать Войти", "category": "incurable"}),
        (
            "on_step_failed",
            # the full structured render — str(exc), never re-composed
            {"step_text": "нажать Войти", "step_type": "action", "error": str(excinfo.value)},
        ),
        (
            "on_step_verdict",
            {
                "step_text": "нажать Войти",
                "category": "incurable",
                "explanation": "текст шага не соответствует реальности",
                "recommendation": "переформулируйте шаг",
            },
        ),
        ("on_step_finished", {"step_text": "нажать Войти", "step_type": "action", "outcome": "failed"}),
    ]
    # full failure cycle: traceback folded to the facade boundary, message ends with the verdict render
    frames = [entry.filename for entry in traceback.extract_tb(excinfo.value.__traceback__)]
    assert frames[-1].endswith("scenario.py")
    assert not any(entry.endswith(("healer.py", "executor.py", "classification.py")) for entry in frames)
    rendered = str(excinfo.value)
    assert rendered.index("текст шага не соответствует реальности") < rendered.index("explanation:")
    assert "category:" not in rendered  # the category travels in structured fields, never in the render
    assert rendered.endswith("recommendation: переформулируйте шаг")


def test_strict_cache_miss_raises_incurable_without_generation(tmp_path: Path) -> None:
    """Strict + cache miss: generation is forbidden; the render carries the step and the fallback guidance."""
    provider = ForbiddenProvider()
    page = FakePage()
    hook = RecorderHook()

    with configured_test(Config(strict=True, cache_root=str(tmp_path)), provider, page) as test:
        test.add_hooks(hook)
        with pytest.raises(IncurableStepError) as excinfo:
            test.step("Нажать «Войти»")
        test.close()

    assert excinfo.value.reason == "strict mode forbids generation — the step is missing from the cache"
    assert excinfo.value.error == ""
    assert excinfo.value.verdict is None
    rendered = str(excinfo.value)
    assert "step: Нажать «Войти»" in rendered
    assert "recommendation: reword the step or refresh the cache" in rendered  # render-only fallback verdict
    assert provider.calls == 0  # no LLM boundary touched at all
    assert [event for event, _payload in hook.events] == [
        "on_step_started",
        "on_step_failed",
        "on_step_finished",
    ]
    assert hook.events[1][1]["error"] == str(excinfo.value)  # one render — never re-composed


def test_strict_failed_cached_step_classifies_without_healing(tmp_path: Path, caplog) -> None:
    """Strict + failed cached step: classification is the only LLM call; the log record carries the render."""
    step_text = "виден баннер «С возвращением»"
    broken_code = "def step(page) -> None:\n    page.get_by_text('Welcome back').expect_visible()\n"
    seed_step(tmp_path, step_text, broken_code, cache_key="login-flow", step_type="assertion")
    provider = StubProvider(
        verdict=FailureClassification(
            category="product_defect", explanation="баннера нет в продукте", recommendation="завести дефект"
        ),
    )
    page = FakePage(broken_lookups=frozenset({"get_by_text"}))
    hook = RecorderHook()
    caplog.set_level(logging.INFO, logger="prettyplay")

    with configured_test(Config(strict=True, cache_root=str(tmp_path)), provider, page) as test:
        test.add_hooks(hook)
        with pytest.raises(ProductDefectError) as excinfo:
            test.expect(step_text)
        test.close()

    assert excinfo.value.verdict is not None
    assert excinfo.value.verdict.category == "product_defect"
    assert excinfo.value.error == "element not found"  # assertion failure — no type prefix
    assert provider.generation_requests == []  # classification is the only LLM call of the strict path
    assert len(provider.classification_requests) == 1
    assert [event for event, _payload in hook.events] == [
        "on_step_started",
        "on_step_failed",
        "on_step_verdict",
        "on_step_finished",
    ]  # no on_healing_started / on_generation_started: the engines never run
    assert hook.events[1][1]["error"] == str(excinfo.value)
    assert hook.events[2][1] == {
        "step_text": step_text,
        "category": "product_defect",
        "explanation": "баннера нет в продукте",
        "recommendation": "завести дефект",
    }
    records = [record for record in caplog.records if record.getMessage() == "on_step_failed"]
    assert len(records) == 1
    assert records[0].error == str(excinfo.value)  # the same multi-line render, never re-composed
    assert "\n" in records[0].error
    assert not hasattr(records[0], "ctx_error")  # "error" is not a reserved log-record key — no prefixing


def test_nonstrict_unhealable_failure_carries_full_error_text(tmp_path: Path) -> None:
    """Non-strict unhealable flow: on_step_failed carries the full error line — no 200-char truncation."""
    long_error = "locator.click: Timeout 30000ms exceeded; waiting for " + "x" * 220
    failing_code = f"def step(page) -> None:\n    raise RuntimeError({long_error!r})\n"
    seed_step(tmp_path, "нажать Войти", failing_code, cache_key="login-flow")
    provider = StubProvider(
        verdict=FailureClassification(
            category="incurable", explanation="шаг не соответствует реальности", recommendation="переформулируйте шаг"
        ),
    )
    page = FakePage()
    hook = RecorderHook()

    with configured_test(Config(cache_root=str(tmp_path)), provider, page) as test:
        test.add_hooks(hook)
        with pytest.raises(IncurableStepError) as excinfo:
            test.step("нажать Войти")
        test.close()

    assert excinfo.value.error == f"RuntimeError: {long_error}"  # full typed text, well past the old 200-char cut
    failed = hook.events[[event for event, _payload in hook.events].index("on_step_failed")][1]
    assert failed["error"] == str(excinfo.value)  # the render — never re-composed
    assert f"error: RuntimeError: {long_error}" in failed["error"]  # the full error line of the template


def test_interactive_steering_heals_a_stuck_step_end_to_end(tmp_path: Path, monkeypatch, capsys) -> None:
    """The interactive loop through the public facade: dialog, strict approval gate, heal, write-back, pass."""
    failing_code = "def step(page) -> None:\n    raise RuntimeError('element not found')\n"
    seed_step(tmp_path, "нажать Войти", failing_code, cache_key="login-flow")
    provider = StubProvider(
        answers=[WORKING_CODE],
        verdict=FailureClassification(
            category="incurable", explanation="шаг не соответствует реальности", recommendation="переформулируйте шаг"
        ),
    )
    page = FakePage()
    hook = RecorderHook()
    answers = iter(["кнопка переехала в модалку", "y"])

    def scripted_input(prompt: str = "") -> str:
        print(prompt, end="")  # the real input echoes its prompt — captured stdout keeps the dialog shape
        return next(answers)

    monkeypatch.setattr(builtins, "input", scripted_input)
    existing_pngs = set(Path(tempfile.gettempdir()).glob("prettyplay-steering-*.png"))

    with configured_test(Config(cache_root=str(tmp_path), interactive=True), provider, page) as test:
        test.add_hooks(hook)
        test.step("нажать Войти")  # the incurable verdict opens the dialog instead of failing the step
        test.close()

    for png in set(Path(tempfile.gettempdir()).glob("prettyplay-steering-*.png")) - existing_pngs:
        png.unlink(missing_ok=True)  # the dialog's one temporary screenshot never outlives the test

    assert ("goto", "https://app.example.com") in page.calls  # the approved turn executed against the page
    events = [event for event, _payload in hook.events]
    assert "on_step_failed" not in events  # the heal never let the terminal failure surface
    assert "on_healed" in events
    assert "on_cache_saved" in events
    assert events[-1] == "on_step_finished"
    assert hook.events[-1][1]["outcome"] == "passed"

    request = provider.generation_requests[0]  # the one guided regeneration request of the dialog
    assert request["guidance"] == "кнопка переехала в модалку"
    assert request["step_type"] == "action"  # the honest inputs reach the guided request
    assert request["page_url"] == "https://app.example.com"  # the fresh URL rode the guided request
    # record 0 anchors the shared history the dialog joined — the original failure the guidance refers to
    record0 = request["attempt_history"][0]
    assert record0.startswith("original cached code\n")
    assert failing_code.rstrip("\n") in record0
    assert "RuntimeError: element not found" in record0
    assert provider.compliance_requests == []  # the gate is off without configured instructions

    out = capsys.readouterr().out
    assert "run? [y/N]" in out  # the approval gate asked before anything executed
    assert "IncurableStepError" in out  # the banner showed the terminal render
    assert "https://app.example.com" in out  # and the page URL
    assert "healed step written to the cache" in out


@contextlib.contextmanager
def cleaned_dialog_screenshots() -> Iterator[None]:
    """Delete the temporary screenshot files a steering dialog created inside the block."""
    existing = set(Path(tempfile.gettempdir()).glob("prettyplay-steering-*.png"))
    try:
        yield
    finally:
        for png in set(Path(tempfile.gettempdir()).glob("prettyplay-steering-*.png")) - existing:
            png.unlink(missing_ok=True)  # a dialog's temporary screenshots never outlive the test


def test_scenario_a_generation_retry_carries_grown_history_and_caches_only_the_green_candidate(
    tmp_path: Path,
) -> None:
    """Scenario A end to end: the failed candidate records, the retry carries the grown history, only green persists."""
    failing_code = "def step(page) -> None:\n    raise RuntimeError('boom')\n"
    provider = StubProvider(answers=[failing_code, WORKING_CODE])
    page = FakePage()
    identity = StepIdentity(
        cache_key="login-flow", step_type="action", normalized_text=normalize_step_text("open the app page")
    )

    with configured_test(Config(cache_root=str(tmp_path)), provider, page) as test:
        test.step("open the app page")
        test.close()

    # attempt 1 carried the empty history; the retry carried the grown rendered history
    assert provider.generation_requests[0]["step_type"] == "action"
    assert provider.generation_requests[0]["attempt_history"] == []
    retry_history = provider.generation_requests[1]["attempt_history"]
    assert len(retry_history) == 1
    assert retry_history[0].startswith("execution failed\n")
    assert "url: https://app.example.com -> https://app.example.com" in retry_history[0]
    assert failing_code.rstrip("\n") in retry_history[0]
    assert "error:\nRuntimeError: boom" in retry_history[0]

    # the green candidate is the only thing persisted — the history dies with the step
    cached = (tmp_path / identity.filename).read_text(encoding="utf-8")
    assert WORKING_CODE.rstrip("\n") in cached
    assert "execution failed" not in cached
    assert "RuntimeError: boom" not in cached
    assert "url: " not in cached


def test_scenario_b_failed_cached_hit_seeds_record_zero_and_heals_with_the_raw_sentence(
    tmp_path: Path,
) -> None:
    """Scenario B end to end: record 0 anchors the healing and the raw sentence reaches the classification."""
    step_text = "Press the «Sign in» button"  # raw casing — never the casefolded addressing form
    broken_code = "def step(page) -> None:\n    page.get_by_role('button', name='Sign in').click()\n"
    healed_code = "def step(page) -> None:\n    page.get_by_text('Sign in').click()\n"
    identity = seed_step(tmp_path, step_text, broken_code, cache_key="login-flow")
    provider = StubProvider(
        answers=[healed_code],
        verdict=FailureClassification(
            category="rot", explanation="the selector rotted", recommendation="use text locators"
        ),
    )
    page = FakePage(broken_lookups=frozenset({"get_by_role"}))

    with installed_test(tmp_path, provider, page, "login-flow") as test:
        test.step(step_text)
        test.close()

    # the raw sentence reached the classification request verbatim — the normalization stays addressing-only
    assert provider.classification_requests[0]["step_text"] == "Press the «Sign in» button"
    # record 0 anchors the regeneration request: the original cached code with its replay error and URL pair
    record0 = provider.generation_requests[0]["attempt_history"][0]
    assert record0.startswith("original cached code\n")
    assert "url: https://app.example.com -> https://app.example.com" in record0
    assert broken_code.rstrip("\n") in record0
    assert "error:\nelement not found" in record0
    assert provider.generation_requests[0]["recommendation"] == "use text locators"
    assert provider.generation_requests[0]["step_type"] == "action"

    # the healed write-back persists only the healed code — record 0 never reaches the file
    rewritten = (tmp_path / identity.filename).read_text(encoding="utf-8")
    assert "get_by_text" in rewritten
    assert "get_by_role" not in rewritten
    assert "original cached code" not in rewritten


def test_scenario_c_steering_write_back_threads_shared_history_and_passes_the_gate(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Scenario C end to end: the dialog joins the engine-grown history; the write-back passes the gate."""
    failing_code = "def step(page) -> None:\n    raise RuntimeError('still broken')\n"
    rejected_code = "def step(page) -> None:\n    page.goto('https://rejected.example.com')\n"
    provider = StubProvider(
        answers=[failing_code, failing_code, failing_code, rejected_code, WORKING_CODE],
        verdict=FailureClassification(
            category="incurable", explanation="the budget ran out", recommendation="reword the step"
        ),
        compliance_verdicts=[[]],
    )
    page = FakePage()
    hook = RecorderHook()
    answers = iter(["the button moved into the modal", "n", "click it now", "y"])

    def scripted_input(prompt: str = "") -> str:
        print(prompt, end="")  # the real input echoes its prompt — captured stdout keeps the dialog shape
        return next(answers)

    monkeypatch.setattr(builtins, "input", scripted_input)
    identity = StepIdentity(
        cache_key="login-flow", step_type="action", normalized_text=normalize_step_text("open the app page")
    )

    with (
        cleaned_dialog_screenshots(),
        configured_test(
            Config(cache_root=str(tmp_path), interactive=True, generation_prompt="prefer data-test-id"),
            provider,
            page,
        ) as test,
    ):
        test.add_hooks(hook)
        test.step("open the app page")  # three failures exhaust the generation budget into the dialog
        test.close()

    # the dialog joined the engine-grown history: the first guided request carries the three engine records
    assert len(provider.generation_requests[3]["attempt_history"]) == 3
    assert provider.generation_requests[3]["guidance"] == "the button moved into the modal"
    assert provider.generation_requests[3]["step_text"] == "open the app page"
    assert provider.generation_requests[3]["step_type"] == "action"

    # the rejected turn appended its record — the same URL on both sides — and the next request carries it grown
    turn_two_history = provider.generation_requests[4]["attempt_history"]
    assert len(turn_two_history) == 4
    assert turn_two_history[3].startswith("rejected by the engineer, not executed\n")
    assert "url: https://app.example.com -> https://app.example.com" in turn_two_history[3]
    assert provider.generation_requests[4]["guidance"] == "click it now"

    # the write-back passed the two-dimension gate judging from the step type and the shared history
    assert len(provider.compliance_requests) == 1
    assert provider.compliance_requests[0]["code"] == WORKING_CODE
    assert provider.compliance_requests[0]["step_type"] == "action"
    assert provider.compliance_requests[0]["attempt_history"] == turn_two_history  # the candidate rides the CODE block

    events = [event for event, _payload in hook.events]
    assert "on_step_failed" not in events  # the heal never let the terminal failure surface
    assert events.count("on_cache_saved") == 1  # exactly one write-back
    assert "on_healed" in events
    assert events[-1] == "on_step_finished"
    assert hook.events[-1][1]["outcome"] == "passed"
    cached = (tmp_path / identity.filename).read_text(encoding="utf-8")
    assert WORKING_CODE.rstrip("\n") in cached
    assert "rejected.example.com" not in cached  # the rejected candidate never executed, never persisted

    out = capsys.readouterr().out
    assert "healed step written to the cache" in out


def test_scenario_c_declined_dialog_propagates_the_original_failure(tmp_path: Path, monkeypatch) -> None:
    """Scenario C declined path: quitting the dialog propagates the original terminal failure unchanged."""
    step_text = "нажать Войти"
    failing_code = "def step(page) -> None:\n    raise RuntimeError('element not found')\n"
    identity = seed_step(tmp_path, step_text, failing_code, cache_key="login-flow")
    provider = StubProvider(
        verdict=FailureClassification(
            category="incurable", explanation="шаг не соответствует реальности", recommendation="переформулируйте шаг"
        ),
    )
    page = FakePage()
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "quit")

    with (
        cleaned_dialog_screenshots(),
        configured_test(Config(cache_root=str(tmp_path), interactive=True), provider, page) as test,
    ):
        with pytest.raises(IncurableStepError) as excinfo:
            test.step(step_text)
        test.close()

    assert excinfo.value.reason == "шаг не соответствует реальности"  # the original failure, unchanged
    assert excinfo.value.recommendation == "переформулируйте шаг"
    rewritten = (tmp_path / identity.filename).read_text(encoding="utf-8")
    assert failing_code.rstrip("\n") in rewritten  # a declined dialog writes nothing back


def test_high_adequacy_finding_blocks_the_write_back_end_to_end(tmp_path: Path, monkeypatch, capsys) -> None:
    """A high adequacy finding never reaches the cache through the dialog — the facade-level gate guarantee."""
    failing_code = "def step(page) -> None:\n    raise RuntimeError('still broken')\n"
    blocked_code = "def step(page) -> None:\n    page.goto('https://one.example.com')\n"
    passing_code = "def step(page) -> None:\n    page.goto('https://two.example.com')\n"
    finding = ComplianceFinding(
        instruction="open the app page",
        priority="high",
        explanation="code only checks an already-achieved state",
        dimension="adequacy",
    )
    provider = StubProvider(
        answers=[failing_code, failing_code, failing_code, blocked_code, passing_code],
        verdict=FailureClassification(
            category="incurable", explanation="the budget ran out", recommendation="reword the step"
        ),
        compliance_verdicts=[[finding], []],
    )
    page = FakePage()
    hook = RecorderHook()
    answers = iter(["look again", "y", "make it act", "y"])

    def scripted_input(prompt: str = "") -> str:
        print(prompt, end="")
        return next(answers)

    monkeypatch.setattr(builtins, "input", scripted_input)
    identity = StepIdentity(
        cache_key="login-flow", step_type="action", normalized_text=normalize_step_text("open the app page")
    )

    with (
        cleaned_dialog_screenshots(),
        configured_test(
            Config(cache_root=str(tmp_path), interactive=True, generation_prompt="prefer data-test-id"),
            provider,
            page,
        ) as test,
    ):
        test.add_hooks(hook)
        test.step("open the app page")  # the blocked turn is steered, the acting turn is written back
        test.close()

    # turn 1 ran green but the gate blocked it — no write-back; the violation text rode the shared history
    assert len(provider.compliance_requests) == 2
    assert provider.compliance_requests[0]["step_type"] == "action"
    assert len(provider.compliance_requests[0]["attempt_history"]) == 3  # the engine records only
    blocked_record = provider.generation_requests[4]["attempt_history"][3]
    assert blocked_record.startswith("compliance blocked\n")
    assert "adequacy violation: open the app page — code only checks an already-achieved state" in blocked_record

    # exactly one write-back — the passing candidate; the blocked one never touched the cache
    events = [event for event, _payload in hook.events]
    assert events.count("on_cache_saved") == 1
    cached = (tmp_path / identity.filename).read_text(encoding="utf-8")
    assert "two.example.com" in cached
    assert "one.example.com" not in cached
    assert events[-1] == "on_step_finished"
    assert hook.events[-1][1]["outcome"] == "passed"

    out = capsys.readouterr().out
    assert "compliance violation — not written back: adequacy violation: open the app page" in out


def test_classification_instructions_reach_only_classification_requests(tmp_path: Path) -> None:
    """The configured prompts reach their own request kinds only — generation and classification stay separate."""
    provider = StubProvider(
        answers=[WORKING_CODE],
        verdict=FailureClassification(category="rot", explanation="селектор сгнил", recommendation="обновить шаг"),
    )
    broken_code = "def step(page) -> None:\n    page.get_by_role('button', name='Войти').click()\n"

    # non-strict pass: one generation request — the generation instructions ride along
    with configured_test(
        Config(
            cache_root=str(tmp_path / "generated"),
            generation_prompt="prefer data-test-id",
            classification_prompt="answer in Russian",
        ),
        provider,
        FakePage(),
    ) as test:
        test.step("open the app page")
        test.close()

    # strict pass: one classification request of a failed cached step — the classification instructions ride along
    seed_step(tmp_path / "classified", "нажать Войти", broken_code, cache_key="login-flow")
    with configured_test(
        Config(
            strict=True,
            cache_root=str(tmp_path / "classified"),
            generation_prompt="prefer data-test-id",
            classification_prompt="answer in Russian",
        ),
        provider,
        FakePage(broken_lookups=frozenset({"get_by_role"})),
    ) as test:
        with pytest.raises(IncurableStepError):  # strict: rot is still incurable — the healer never runs
            test.step("нажать Войти")
        test.close()

    assert [request["user_instructions"] for request in provider.generation_requests] == ["prefer data-test-id"]
    assert [request["user_instructions"] for request in provider.classification_requests] == ["answer in Russian"]
    assert (
        "- USER INSTRUCTIONS: the project's binding classification guidance, when configured — follow it; "
        "it never overrides the fixed answer format above" in provider.classification_requests[0]["prompt"]
    )
    # no cross-contamination between the two configured texts and the request kinds
    assert "answer in Russian" not in provider.generation_requests[0]["prompt"]
    assert "prefer data-test-id" not in provider.classification_requests[0]["prompt"]


def test_pyproject_settings_reach_the_executor_config(tmp_path: Path) -> None:
    """The file layer flows into the wired executor config — without launching a browser."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[tool.prettyplay]\n"
        "strict = true\n"
        "\n"
        "[tool.prettyplay.browser]\n"
        'name = "firefox"\n'
        'screen = "fullscreen"\n'
        "headless = false\n",
        encoding="utf-8",
    )

    with (
        mock.patch(
            "prettyplay.scenario.load_config",
            side_effect=lambda _path, overrides: load_config(str(pyproject), overrides),
        ),
        mock.patch("prettyplay.runtime.create_provider", return_value=ForbiddenProvider()),
    ):
        test = PrettyPlay("login-flow")

    wired = test._executor._config
    assert wired.strict is True
    assert wired.browser.name == "firefox"
    assert wired.browser.screen == "fullscreen"
    assert wired.browser.headless is False
    assert test._runtime._driver is None  # the driver constructs lazily — construction launched nothing
    test.close()


def test_strict_failure_never_writes_the_cache(tmp_path: Path) -> None:
    """Strict mode never writes the cache: the generation path — the only writer — never runs."""
    miss_root = tmp_path / "miss"
    failed_root = tmp_path / "failed"
    miss_root.mkdir()
    failed_root.mkdir()

    # cache miss: generation is forbidden — the empty cache stays empty
    with configured_test(Config(strict=True, cache_root=str(miss_root)), ForbiddenProvider(), FakePage()) as test:
        with pytest.raises(IncurableStepError):
            test.step("шаг, которого нет в кэше")
        test.close()

    assert [path for path in miss_root.rglob("*") if path.is_file()] == []

    # failed cached step: classification only — the seeded file survives untouched
    step_text = "нажать Войти"
    broken_code = "def step(page) -> None:\n    page.get_by_role('button', name='Войти').click()\n"
    identity = seed_step(failed_root, step_text, broken_code, cache_key="login-flow")
    provider = StubProvider(
        verdict=FailureClassification(category="rot", explanation="селектор сгнил", recommendation="обновить шаг")
    )
    page = FakePage(broken_lookups=frozenset({"get_by_role"}))

    with configured_test(Config(strict=True, cache_root=str(failed_root)), provider, page) as test:
        with pytest.raises(IncurableStepError):
            test.step(step_text)
        test.close()

    assert [path.name for path in failed_root.iterdir()] == [identity.filename]
    assert "get_by_role" in (failed_root / identity.filename).read_text(encoding="utf-8")  # bytes unchanged


class SettlingPage(FakePage):
    """Fake page whose first text lookup fails — a transient state only a settle window absorbs."""

    def __init__(self) -> None:
        super().__init__()
        self._text_lookups = 0

    def get_by_text(self, text: str) -> FakeLocator:
        self._text_lookups += 1
        if self._text_lookups == 1:  # the element state settles after the first attempt
            self.calls.append(("get_by_text", text))
            raise AssertionError("element is not visible yet")  # a failed expectation — pollable
        return super().get_by_text(text)


def test_scenario_and_full_integration_green_path_with_window(tmp_path: Path, caplog) -> None:
    """The full green cycle with the settle window: generation, settle, cache write, closing event."""
    action_text = "open the page"
    assertion_text = "the heading is visible"
    heading_code = "def step(page) -> None:\n    page.get_by_text('App title').expect_visible()\n"
    provider = StubProvider(answers=[WORKING_CODE, heading_code])
    page = SettlingPage()
    hook = RecorderHook()
    caplog.set_level(logging.INFO, logger="prettyplay")

    with configured_test(
        Config(cache_root=str(tmp_path), polling_timeout=6.0, polling_delay=0.0), provider, page
    ) as test:
        test.add_hooks(hook)
        test.step(action_text)
        test.expect(assertion_text)
        test.close()

    # the transient lookup failure was absorbed inside the window of the one step execution:
    # one LLM attempt per step (no regeneration for a settle-retried candidate), one retry record
    assert len(provider.generation_requests) == 2
    settle_retries = [record for record in caplog.records if record.getMessage() == "settle_retry"]
    assert len(settle_retries) == 1
    assert settle_retries[0].attempt == 1

    action_identity = StepIdentity(
        cache_key="login-flow", step_type="action", normalized_text=normalize_step_text(action_text)
    )
    assertion_identity = StepIdentity(
        cache_key="login-flow", step_type="assertion", normalized_text=normalize_step_text(assertion_text)
    )
    assert hook.events == [
        ("on_step_started", {"step_text": action_text, "step_type": "action"}),
        ("on_generation_started", {"step_text": action_text, "attempt": 1}),
        ("on_cache_saved", {"step_text": action_text, "filename": action_identity.filename}),
        ("on_step_passed", {"step_text": action_text, "step_type": "action"}),
        ("on_step_finished", {"step_text": action_text, "step_type": "action", "outcome": "passed"}),
        ("on_step_started", {"step_text": assertion_text, "step_type": "assertion"}),
        ("on_generation_started", {"step_text": assertion_text, "attempt": 1}),
        ("on_cache_saved", {"step_text": assertion_text, "filename": assertion_identity.filename}),
        ("on_step_passed", {"step_text": assertion_text, "step_type": "assertion"}),
        ("on_step_finished", {"step_text": assertion_text, "step_type": "assertion", "outcome": "passed"}),
    ]

    # cache writes: both proven candidates are on disk under their addressed filenames
    assert (tmp_path / action_identity.filename).exists()
    assert (tmp_path / assertion_identity.filename).exists()

    # both generated codes actually executed against the page — the second one twice (settle retry)
    assert page.calls == [
        ("goto", "https://app.example.com"),
        ("get_by_text", "App title"),
        ("get_by_text", "App title"),
        ("expect_visible",),
    ]


def test_incurable_failure_shape_end_to_end(tmp_path: Path) -> None:
    """The failure shape end to end: an incurable check reaches the integrator with the candidate code."""
    step_text = "the heading is visible"
    failing_check_code = "def step(page) -> None:\n    page.get_by_text('App title').expect_visible()\n"
    provider = StubProvider(
        answers=[failing_check_code, failing_check_code],  # every candidate fails the check
        verdict=FailureClassification(
            category="incurable", explanation="the heading never exists on the page", recommendation="reword the step"
        ),
    )
    page = FakePage(broken_lookups=frozenset({"get_by_text"}))  # the check can never hold
    hook = RecorderHook()

    with configured_test(Config(cache_root=str(tmp_path)), provider, page) as test:  # interactive off
        test.add_hooks(hook)
        with pytest.raises(IncurableStepError) as excinfo:
            test.expect(step_text)
        test.close()

    # the integrator-facing failure carries the last candidate verbatim and the scripted verdict
    assert excinfo.value.code == failing_check_code
    assert excinfo.value.verdict is not None
    assert excinfo.value.verdict.category == "incurable"
    assert excinfo.value.error == "element not found"
    assert provider.classification_requests[0]["code"] == failing_check_code

    # the failed candidate is never cached
    identity = StepIdentity(
        cache_key="login-flow", step_type="assertion", normalized_text=normalize_step_text(step_text)
    )
    assert not (tmp_path / identity.filename).exists()

    assert [event for event, _payload in hook.events] == [
        "on_step_started",
        "on_generation_started",
        "on_step_failed",
        "on_step_verdict",
        "on_step_finished",  # the closing event last, exactly once, outcome failed
    ]
    assert hook.events[-1][1] == {"step_text": step_text, "step_type": "assertion", "outcome": "failed"}
    assert hook.events[2][1]["error"] == str(excinfo.value)  # the render — never re-composed


COUNT_FORMS_CODE = (
    "from playwright.sync_api import expect\n"
    "\n"
    "\n"
    "def step(page):\n"
    '    videos = page.get_by_role("listitem")\n'
    "    expect(videos.first).to_be_visible()\n"
    "    assert videos.count() > 1\n"
)


class VideosLocatorImpl:
    """Impl-side stand-in of the videos locator: the real expect machinery sees a matched check."""

    def __init__(self, loop: asyncio.AbstractEventLoop, fiber: greenlet.greenlet) -> None:
        self._loop = loop
        self._dispatcher_fiber = fiber

    async def _expect(
        self, expression: str, expect_options: dict[str, object], title: str | None = None
    ) -> dict[str, object]:
        return {"matches": True, "received": {}}


class VideosLocator(Locator):
    """Fake sync locator of the videos list: ``first`` is visible, ``count()`` is the list length."""

    def __init__(self, loop: asyncio.AbstractEventLoop, fiber: greenlet.greenlet, count: int) -> None:
        super().__init__(VideosLocatorImpl(loop, fiber))
        self._count = count

    @property
    def first(self) -> "VideosLocator":
        return VideosLocator(self._loop, self._dispatcher_fiber, self._count)

    def count(self) -> int:
        return self._count


class VideosRawPage:
    """Fake raw sync page: the role lookup of the videos list answers the standard API."""

    def __init__(self, loop: asyncio.AbstractEventLoop, fiber: greenlet.greenlet, video_count: int) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._loop = loop
        self._fiber = fiber
        self._video_count = video_count

    def get_by_role(self, role: str, name: str | None = None) -> VideosLocator:
        self.calls.append(("get_by_role", role))
        return VideosLocator(self._loop, self._fiber, self._video_count)


class RecordingHandle:
    """Fake page handle: the run unit executes the action against the raw page and is counted."""

    def __init__(self, raw: VideosRawPage) -> None:
        self._raw = raw
        self.run_units = 0
        self.close_count = 0

    def run(self, action: Callable[[object], object]) -> object:
        """The run primitive: the action receives the raw page, the outcome returns as-is."""
        self.run_units += 1
        return action(self._raw)

    def aria_snapshot(self) -> str:
        return "- listitem 'first video'"

    def screenshot(self) -> bytes:
        return b"png"

    def close(self) -> None:
        self.close_count += 1


def test_count_forms_step_runs_green_through_the_full_cycle(tmp_path: Path) -> None:
    """The motivating step — count forms through the standard Playwright sync API — runs green end to end.

    The exact step that used to die on the facade as a non-pollable
    ``AttributeError`` (``count`` was no mirror member) passes the whole
    cycle: cache miss → generation carrying the cheat sheet → settle →
    ``run_step_code`` → the handle run unit against the raw page → cache
    write.
    """
    loop = asyncio.new_event_loop()

    def dispatch() -> None:
        while True:  # the parked dispatcher: the loop runs from inside its greenlet, as the driver does
            loop.run_forever()
            asyncio._set_running_loop(None)
            greenlet.getcurrent().parent.switch()

    fiber = greenlet.greenlet(dispatch)
    raw = VideosRawPage(loop, fiber, video_count=3)
    handle = RecordingHandle(raw)
    provider = StubProvider(answers=[COUNT_FORMS_CODE])
    step_text = "the page shows a list of videos"

    try:
        with installed_test(tmp_path, provider, handle, "videos") as test:
            test.expect(step_text)
            test.close()
    finally:
        # orderly teardown: the parked dispatcher stops the loop from inside itself (the sync
        # expect machinery adopted the loop into the thread — dispatch gives the thread back)
        # and parks clean at its loop top, so a later collection of the greenlet never re-enters
        # run_forever; the closed loop disposes with no parked select to block the interpreter
        loop.call_soon(loop.stop)
        fiber.switch()
        loop.close()

    assert raw.calls == [("get_by_role", "listitem")]  # the standard-API role lookup ran on the raw page
    assert handle.run_units == 1  # one run unit: the green candidate executed exactly once
    assert handle.close_count == 1
    assert provider.generation_requests[0]["cheat_sheet"]  # the request carried the cheat-sheet reference
    identity = StepIdentity(cache_key="videos", step_type="assertion", normalized_text=normalize_step_text(step_text))
    cached = (tmp_path / identity.filename).read_text(encoding="utf-8")
    assert "expect(videos.first).to_be_visible()" in cached
    assert "videos.count() > 1" in cached
    # the write loads back verbatim — a replayed run receives the import line too,
    # not a code tail amputated at `def step(`
    loaded = StepCache(Config(cache_root=str(tmp_path)), None, StepReporter(hooks=[])).load(identity)
    assert loaded is not None
    assert loaded.code.startswith("from playwright.sync_api import expect")
