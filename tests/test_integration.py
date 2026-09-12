"""Integration tests of the full step cycle through the public ``PrettyPlay`` facade."""

import contextlib
import logging
import os
import traceback
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import prettyplay
import pytest
from prettyplay import BrowserConfig, PrettyPlay
from prettyplay.cache import CachedStep, StepCache, StepIdentity, normalize_step_text
from prettyplay.config import Config, load_config
from prettyplay.failures import IncurableStepError, ProductDefectError
from prettyplay.llm import FailureClassification, LLMProvider
from prettyplay.reporting import StepHooks, StepReporter

OPEN_LOGIN_CODE = "def step(page) -> None:\n    page.goto('https://login.example.com')\n"
WORKING_CODE = "def step(page) -> None:\n    page.goto('https://app.example.com')\n"


class FakeLocator:
    """Fake element boundary recording facade calls into the log of the owning page."""

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
    """Fake page boundary recording facade calls; broken lookups simulate a rotted UI."""

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
    """Stub LLM boundary: scripted generation answers, a fixed verdict, recorded requests."""

    def __init__(
        self,
        answers: list[str] | None = None,
        verdict: FailureClassification | None = None,
    ) -> None:
        self.answers = list(answers or [])
        self.verdict = verdict
        self.generation_requests: list[dict[str, object]] = []
        self.classification_requests: list[dict[str, object]] = []

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str = "",
        step_text: str = "",
        previous_steps: list[str] | None = None,
        snapshot: str = "",
        screenshot: bytes | None = None,
        page_api: str = "",
        existing_code: str | None = None,
        error: str | None = None,
        recommendation: str | None = None,
        guidance: str | None = None,
        guidance_history: list[str] | None = None,
    ) -> str:
        self.generation_requests.append(
            {
                "prompt": prompt,
                "user_instructions": user_instructions,
                "step_text": step_text,
                "previous_steps": list(previous_steps),  # copy: the scenario context lives on
                "snapshot": snapshot,
                "screenshot": screenshot,
                "page_api": page_api,
                "existing_code": existing_code,
                "error": error,
                "recommendation": recommendation,
                "guidance": guidance,
                "guidance_history": list(guidance_history or []),
            }
        )
        if not self.answers:
            raise AssertionError("stub provider has no generation answers left")
        return self.answers.pop(0)

    def classify_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
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


class ForbiddenProvider(LLMProvider):
    """Stub provider failing the run the moment a cached path touches the LLM boundary."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        user_instructions: str = "",
        step_text: str = "",
        previous_steps: list[str] | None = None,
        snapshot: str = "",
        screenshot: bytes | None = None,
        page_api: str = "",
        existing_code: str | None = None,
        error: str | None = None,
        recommendation: str | None = None,
        guidance: str | None = None,
        guidance_history: list[str] | None = None,
    ) -> str:
        self.calls += 1
        raise AssertionError("provider must not be called")

    def classify_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
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

    assert [request["previous_steps"] for request in provider.generation_requests] == [[], ["шаг один"]]
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
    assert page.calls == [("goto", "https://app.example.com")]  # generated code executed


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
    assert provider.generation_requests[0]["existing_code"].rstrip("\n") == broken_code.rstrip("\n")
    assert hook.events == [
        ("on_step_started", {"step_text": "нажать Войти", "step_type": "action"}),
        ("on_healing_started", {"step_text": "нажать войти", "category": "rot"}),
        ("on_generation_started", {"step_text": "нажать войти", "attempt": 1}),
        ("on_cache_saved", {"step_text": "нажать войти", "filename": identity.filename}),
        ("on_healed", {"step_text": "нажать войти", "explanation": "кнопка переименована"}),
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
    assert provider.generation_requests[0]["existing_code"].rstrip("\n") == retired_code.rstrip("\n")
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

    assert excinfo.value.step_text == normalize_step_text(step_text)
    assert excinfo.value.message == "ожидание не оправдалось"
    assert provider.generation_requests == []  # product defect is not regenerated
    rewritten = (tmp_path / identity.filename).read_text(encoding="utf-8")
    assert "get_by_role" in rewritten  # cache untouched
    assert hook.events == [
        ("on_step_started", {"step_text": "нажать Войти", "step_type": "action"}),
        ("on_healing_started", {"step_text": "нажать войти", "category": "product_defect"}),
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
        ("on_healing_started", {"step_text": "нажать войти", "category": "incurable"}),
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
        "- USER INSTRUCTIONS: the project's classification guidance, when configured"
        in provider.classification_requests[0]["prompt"]
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
