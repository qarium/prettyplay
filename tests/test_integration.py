"""Integration tests of the full step cycle through the public ``PrettyTest`` facade."""

import contextlib
import traceback
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import prettyplay.runtime as runtime_module
import pytest
from prettyplay import PrettyplayRuntime, PrettyTest
from prettyplay.cache import CachedStep, StepCache, StepIdentity, normalize_step_text
from prettyplay.config import Config
from prettyplay.failures import IncurableStepError, ProductDefectError
from prettyplay.llm import FailureClassification, LlmProvider
from prettyplay.reporting import StepHooks, StepReporter

OPEN_LOGIN_CODE = "def step(page) -> None:\n    page.open('https://login.example.com')\n"
WORKING_CODE = "def step(page) -> None:\n    page.open('https://app.example.com')\n"


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

    def open(self, url: str) -> None:
        self.calls.append(("open", url))

    def find_by_role(self, role: str, name: str) -> FakeLocator:
        return self._lookup("find_by_role", (role, name))

    def find_by_label(self, label: str) -> FakeLocator:
        return self._lookup("find_by_label", (label,))

    def find_by_text(self, text: str) -> FakeLocator:
        return self._lookup("find_by_text", (text,))

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


class StubProvider(LlmProvider):
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
        step_text: str,
        previous_steps: list[str],
        snapshot: str,
        screenshot: bytes | None,
        page_api: str,
        existing_code: str | None,
        error: str | None,
    ) -> str:
        self.generation_requests.append(
            {
                "prompt": prompt,
                "step_text": step_text,
                "previous_steps": list(previous_steps),  # копия: сценарный контекст живёт дальше
                "snapshot": snapshot,
                "screenshot": screenshot,
                "page_api": page_api,
                "existing_code": existing_code,
                "error": error,
            }
        )
        if not self.answers:
            raise AssertionError("stub provider has no generation answers left")
        return self.answers.pop(0)

    def classify_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        step_text: str,
        code: str,
        error: str,
        snapshot: str,
        screenshot: bytes | None,
    ) -> FailureClassification:
        self.classification_requests.append(
            {
                "prompt": prompt,
                "step_text": step_text,
                "code": code,
                "error": error,
                "snapshot": snapshot,
                "screenshot": screenshot,
            }
        )
        return self.verdict


class ForbiddenProvider(LlmProvider):
    """Stub provider failing the run the moment a cached path touches the LLM boundary."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_step_code(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
        step_text: str,
        previous_steps: list[str],
        snapshot: str,
        screenshot: bytes | None,
        page_api: str,
        existing_code: str | None,
        error: str | None,
    ) -> str:
        self.calls += 1
        raise AssertionError("provider must not be called")

    def classify_failure(  # noqa: PLR0913, PLR0917 — the signature is fixed by the port contract
        self,
        prompt: str,
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
def isolated_runtime_global():
    """Reset the process runtime singleton before and after every test."""
    runtime_module._runtime = None
    yield
    runtime_module._runtime = None


@pytest.fixture(autouse=True)
def no_llm_credentials(monkeypatch):
    """Run without provider keys: the cached path needs none of them."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@contextlib.contextmanager
def installed_runtime(
    cache_root: Path,
    provider: LlmProvider,
    page: FakePage,
) -> Iterator[PrettyplayRuntime]:
    """Install an isolated runtime on a tmp cache with stubbed provider and page boundaries."""
    runtime = PrettyplayRuntime(Config(cache_root=str(cache_root)))
    runtime_module._runtime = runtime
    with (
        mock.patch("prettyplay.runtime.create_provider", return_value=provider),
        mock.patch.object(runtime, "open_page", return_value=page),
    ):
        yield runtime


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


def test_action_cached_step_runs_without_llm(tmp_path: Path) -> None:
    """Flow B: a cached step executes through the whole cycle with no LLM involvement."""
    provider = ForbiddenProvider()
    page = FakePage()
    hook = RecorderHook()
    seed_step(tmp_path, "открыть страницу логина", OPEN_LOGIN_CODE, cache_key="login-flow")

    with installed_runtime(tmp_path, provider, page):
        test = PrettyTest("login-flow")
        test.add_hooks(hook)
        test.action("открыть страницу логина")
        test.close()

    assert page.calls == [("open", "https://login.example.com")]
    assert hook.events == [
        ("on_step_started", {"step_text": "открыть страницу логина", "step_type": "action"}),
        ("on_step_passed", {"step_text": "открыть страницу логина", "step_type": "action"}),
    ]
    assert provider.calls == 0


def test_scenario_context_feeds_next_generation(tmp_path: Path) -> None:
    """Flow A: the sentences of the earlier steps feed the generation request of the next one."""
    provider = StubProvider(answers=[WORKING_CODE, WORKING_CODE])
    page = FakePage()
    hook = RecorderHook()

    with installed_runtime(tmp_path, provider, page):
        test = PrettyTest("k")
        test.add_hooks(hook)
        test.action("шаг один")
        test.action("шаг два")
        test.close()

    assert [request["previous_steps"] for request in provider.generation_requests] == [[], ["шаг один"]]
    assert [event for event, _payload in hook.events if event == "on_step_passed"] == [
        "on_step_passed",
        "on_step_passed",
    ]
    assert len([event for event, _payload in hook.events if event == "on_cache_saved"]) == 2


def test_rot_healing_regenerates_rewrites_cache_and_passes(tmp_path: Path) -> None:
    """Flow C: a rotted cached step is classified, regenerated, re-cached and passes."""
    step_text = "нажать Войти"
    broken_code = "def step(page) -> None:\n    page.find_by_role('button', name='Войти').click()\n"
    healed_code = "def step(page) -> None:\n    page.find_by_text('Войти').click()\n"
    identity = seed_step(tmp_path, step_text, broken_code, cache_key="login-flow")
    provider = StubProvider(
        answers=[healed_code],
        verdict=FailureClassification(
            category="rot", explanation="кнопка переименована", recommendation="проверить шаг"
        ),
    )
    page = FakePage(broken_lookups=frozenset({"find_by_role"}))
    hook = RecorderHook()

    with installed_runtime(tmp_path, provider, page):
        test = PrettyTest("login-flow")
        test.add_hooks(hook)
        test.action(step_text)
        test.close()

    assert page.calls == [("find_by_role", "button", "Войти"), ("find_by_text", "Войти"), ("click",)]
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
    ]
    rewritten = (tmp_path / identity.filename).read_text(encoding="utf-8")
    assert "find_by_text" in rewritten
    assert "find_by_role" not in rewritten


def test_cache_path_subdirectories_do_not_collide(tmp_path: Path) -> None:
    """The cache subdirectory is part of the address: same triple, different steps."""
    checkout_code = "def step(page) -> None:\n    page.open('https://checkout.example.com')\n"
    marketing_code = "def step(page) -> None:\n    page.open('https://marketing.example.com')\n"
    provider = ForbiddenProvider()
    checkout_page = FakePage()
    marketing_page = FakePage()
    identity = seed_step(tmp_path, "открыть страницу", checkout_code, cache_key="k", cache_path="checkout")
    seed_step(tmp_path, "открыть страницу", marketing_code, cache_key="k", cache_path="marketing")

    with installed_runtime(tmp_path, provider, checkout_page):
        test = PrettyTest("k", cache_path="checkout")
        test.action("открыть страницу")
        test.close()

    with installed_runtime(tmp_path, provider, marketing_page):
        test = PrettyTest("k", cache_path="marketing")
        test.action("открыть страницу")
        test.close()

    assert checkout_page.calls == [("open", "https://checkout.example.com")]
    assert marketing_page.calls == [("open", "https://marketing.example.com")]
    assert provider.calls == 0
    assert (tmp_path / "checkout" / identity.filename).exists()
    assert (tmp_path / "marketing" / identity.filename).exists()


def test_product_defect_verdict_fails_the_test_loudly(tmp_path: Path) -> None:
    """A classified product defect surfaces through PrettyTest.action with an intact cache."""
    step_text = "нажать Войти"
    broken_code = "def step(page) -> None:\n    page.find_by_role('button', name='Войти').click()\n"
    identity = seed_step(tmp_path, step_text, broken_code, cache_key="login-flow")
    provider = StubProvider(
        verdict=FailureClassification(
            category="product_defect", explanation="ожидание не оправдалось", recommendation="чинить продукт"
        ),
    )
    page = FakePage(broken_lookups=frozenset({"find_by_role"}))
    hook = RecorderHook()

    with installed_runtime(tmp_path, provider, page):
        test = PrettyTest("login-flow")
        test.add_hooks(hook)
        with pytest.raises(ProductDefectError) as excinfo:
            test.action(step_text)
        test.close()

    assert excinfo.value.step_text == normalize_step_text(step_text)
    assert excinfo.value.message == "ожидание не оправдалось"
    assert provider.generation_requests == []  # дефект продукта не регенерируется
    rewritten = (tmp_path / identity.filename).read_text(encoding="utf-8")
    assert "find_by_role" in rewritten  # кэш не тронут
    assert hook.events == [
        ("on_step_started", {"step_text": "нажать Войти", "step_type": "action"}),
        ("on_healing_started", {"step_text": "нажать войти", "category": "product_defect"}),
        (
            "on_step_failed",
            {"step_text": "нажать Войти", "step_type": "action", "error": "ожидание не оправдалось"},
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
    ]
    # полный цикл срыва: трейсбак сложен до границы фасада, сообщение кончается рендером вердикта
    frames = [entry.filename for entry in traceback.extract_tb(excinfo.value.__traceback__)]
    assert frames[-1].endswith("scenario.py")
    assert not any(entry.endswith(("healer.py", "executor.py", "classification.py")) for entry in frames)
    rendered = str(excinfo.value)
    assert rendered.index("ожидание не оправдалось") < rendered.index("category:")
    assert rendered.endswith("recommendation: чинить продукт")


def test_incurable_verdict_fails_with_verdict_fields(tmp_path: Path) -> None:
    """An incurable classification surfaces with the verdict explanation and recommendation."""
    step_text = "нажать Войти"
    broken_code = "def step(page) -> None:\n    page.find_by_role('button', name='Войти').click()\n"
    identity = seed_step(tmp_path, step_text, broken_code, cache_key="login-flow")
    provider = StubProvider(
        verdict=FailureClassification(
            category="incurable",
            explanation="текст шага не соответствует реальности",
            recommendation="переформулируйте шаг",
        ),
    )
    page = FakePage(broken_lookups=frozenset({"find_by_role"}))
    hook = RecorderHook()

    with installed_runtime(tmp_path, provider, page):
        test = PrettyTest("login-flow")
        test.add_hooks(hook)
        with pytest.raises(IncurableStepError) as excinfo:
            test.action(step_text)
        test.close()

    assert excinfo.value.reason == "текст шага не соответствует реальности"
    # вердикт healer'а, не fallback  # noqa: RUF003 — кириллица намерена
    assert excinfo.value.recommendation == "переформулируйте шаг"
    assert provider.generation_requests == []  # лечение не запрашивает регенерацию
    rewritten = (tmp_path / identity.filename).read_text(encoding="utf-8")
    assert "find_by_role" in rewritten  # кэш не тронут
    assert hook.events == [
        ("on_step_started", {"step_text": "нажать Войти", "step_type": "action"}),
        ("on_healing_started", {"step_text": "нажать войти", "category": "incurable"}),
        (
            "on_step_failed",
            {"step_text": "нажать Войти", "step_type": "action", "error": "текст шага не соответствует реальности"},
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
    ]
    # полный цикл срыва: трейсбак сложен до границы фасада, сообщение кончается рендером вердикта
    frames = [entry.filename for entry in traceback.extract_tb(excinfo.value.__traceback__)]
    assert frames[-1].endswith("scenario.py")
    assert not any(entry.endswith(("healer.py", "executor.py", "classification.py")) for entry in frames)
    rendered = str(excinfo.value)
    assert rendered.index("текст шага не соответствует реальности") < rendered.index("category:")
    assert rendered.endswith("recommendation: переформулируйте шаг")
