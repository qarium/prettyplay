"""Tests for the PrettyTest scenario object of the prettyplay root cell."""

import inspect
import traceback
from pathlib import Path
from unittest import mock

import prettyplay.runtime as runtime_module
import pytest
from prettyplay import PrettyplayRuntime, PrettyTest
from prettyplay.cache import CachedStep, StepCache, StepIdentity, normalize_step_text
from prettyplay.config import Config
from prettyplay.failures import FailureVerdict, IncurableStepError, PrettyplayError
from prettyplay.reporting import StepHooks, StepReporter

CACHE_KEY = "k"
STEP_TEXT = "шаг"
CACHED_CODE = "def step(page) -> None:\n    page.open('https://example.com')\n"


class FakePage:
    """Fake page boundary: records navigation, screenshots and how many times it was closed."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.close_count = 0
        self.screenshot_count = 0

    def open(self, url: str) -> None:
        self.calls.append(("open", url))

    def close(self) -> None:
        self.close_count += 1

    def screenshot(self) -> bytes:
        self.screenshot_count += 1
        return b"png-bytes"

    @property
    def closed(self) -> bool:
        """Whether the page context was closed at least once."""
        return self.close_count > 0


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


@pytest.fixture(autouse=True)
def isolated_runtime_global():
    """Reset the process runtime singleton before and after every test."""
    runtime_module._runtime = None
    yield
    runtime_module._runtime = None


def make_runtime(tmp_path: Path) -> PrettyplayRuntime:
    """Build a runtime on a tmp cache root and install it as the process singleton."""
    runtime = PrettyplayRuntime(Config(cache_root=str(tmp_path)))
    runtime_module._runtime = runtime
    return runtime


def seed_cache(
    tmp_path: Path,
    cache_key: str = CACHE_KEY,
    step_text: str = STEP_TEXT,
    step_type: str = "action",
) -> None:
    """Pre-write a working cached step, so tests run the cache-hit path without the LLM."""
    identity = StepIdentity(cache_key=cache_key, step_type=step_type, normalized_text=normalize_step_text(step_text))
    StepCache(Config(cache_root=str(tmp_path)), None, StepReporter(hooks=[])).save(
        CachedStep(identity=identity, code=CACHED_CODE, created_at="2026-09-08")
    )


class TestPrettyTestContract:
    """Contract tests: facade import, constructor, surface and the context-manager protocol."""

    def test_pretty_test_is_importable_from_facade(self) -> None:
        assert isinstance(PrettyTest, type)

    def test_constructor_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(PrettyTest.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["cache_key", "cache_path"]
        assert parameters[1].default is None

    def test_surface_matches_contract(self) -> None:
        assert isinstance(PrettyTest.cache_key, property)

        for name in (
            "action",
            "assertion",
            "get_screenshot",
            "save_screenshot",
            "add_hooks",
            "close",
            "__enter__",
            "__exit__",
        ):
            assert callable(getattr(PrettyTest, name)), name

    def test_step_method_signatures_match_contract(self) -> None:
        assert list(inspect.signature(PrettyTest.action).parameters) == ["self", "text"]
        assert list(inspect.signature(PrettyTest.assertion).parameters) == ["self", "text"]

    def test_add_hooks_and_close_signatures_match_contract(self) -> None:
        assert list(inspect.signature(PrettyTest.add_hooks).parameters) == ["self", "hooks"]
        assert list(inspect.signature(PrettyTest.close).parameters) == ["self"]

    def test_screenshot_method_signatures_match_contract(self) -> None:
        assert list(inspect.signature(PrettyTest.get_screenshot).parameters) == ["self"]
        assert list(inspect.signature(PrettyTest.save_screenshot).parameters) == ["self", "filepath"]


class TestPrettyTestLogic:
    """Logic tests: page lifecycle, laziness, hooks registration and error pass-through."""

    def test_context_manager_closes_page_keeps_runtime_alive(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path)
        seed_cache(tmp_path)
        pages: list[FakePage] = []

        def fresh_page() -> FakePage:
            page = FakePage()
            pages.append(page)
            return page

        with (
            mock.patch.object(runtime, "open_page", side_effect=fresh_page),
            mock.patch.object(runtime, "close"),
        ):
            with PrettyTest(CACHE_KEY) as test:
                test.action(STEP_TEXT)

            assert len(pages) == 1
            assert pages[0].closed is True

            with PrettyTest(CACHE_KEY):
                pass

        assert len(pages) == 1  # page two opens on the first step, not on construction

    def test_action_and_assertion_delegate_step_types(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path)
        seed_cache(tmp_path, step_type="action")
        seed_cache(tmp_path, step_type="assertion")
        page = FakePage()
        hook = RecorderHook()

        with mock.patch.object(runtime, "open_page", return_value=page):
            test = PrettyTest(CACHE_KEY)
            test.add_hooks(hook)
            test.action(STEP_TEXT)
            test.assertion(STEP_TEXT)
            test.close()

        assert ("on_step_started", {"step_text": STEP_TEXT, "step_type": "action"}) in hook.events
        assert ("on_step_passed", {"step_text": STEP_TEXT, "step_type": "assertion"}) in hook.events
        assert not [payload for event, payload in hook.events if event == "on_step_failed"]

    def test_construction_is_lazy_and_returns_cache_key(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path)

        with mock.patch.object(runtime, "open_page") as open_page_mock:
            test = PrettyTest(CACHE_KEY)

            assert test.cache_key == CACHE_KEY
            open_page_mock.assert_not_called()

    def test_cache_path_participates_in_addressing(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path)
        seed_cache(tmp_path)
        checkout_code = "def step(page) -> None:\n    page.open('https://checkout.example.com')\n"
        identity = StepIdentity(cache_key=CACHE_KEY, step_type="action", normalized_text=normalize_step_text(STEP_TEXT))
        StepCache(Config(cache_root=str(tmp_path)), "checkout", StepReporter(hooks=[])).save(
            CachedStep(identity=identity, code=checkout_code, created_at="2026-09-08")
        )
        shared = StepCache(Config(cache_root=str(tmp_path)), None, StepReporter(hooks=[]))
        page = FakePage()

        with mock.patch.object(runtime, "open_page", return_value=page):
            test = PrettyTest(CACHE_KEY, cache_path="checkout")
            test.action(STEP_TEXT)
            test.close()

            # the same identity triple resolves to different addresses: the subdirectory
            # step runs, and neither store sees the copy of the other
        assert page.calls == [("open", "https://checkout.example.com")]
        assert shared.load(identity) is not None
        assert test._cache.load(identity).code.rstrip("\n") == checkout_code.rstrip("\n")
        assert shared.load(identity).code != test._cache.load(identity).code

    def test_exit_closes_page_and_never_suppresses(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path)
        seed_cache(tmp_path)
        page = FakePage()

        def failing_scenario() -> None:
            """Open the page through a step, then fail the scenario block."""
            with PrettyTest(CACHE_KEY) as test:
                test.action(STEP_TEXT)
                raise RuntimeError("scenario failure")

        with (
            mock.patch.object(runtime, "open_page", return_value=page),
            pytest.raises(RuntimeError, match="scenario failure"),
        ):
            failing_scenario()

        assert page.closed is True

    def test_close_twice_is_noop(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path)
        seed_cache(tmp_path)
        page = FakePage()

        with mock.patch.object(runtime, "open_page", return_value=page):
            test = PrettyTest(CACHE_KEY)
            test.action(STEP_TEXT)
            test.close()
            test.close()

        assert page.close_count == 1

    def test_action_folds_traceback_to_boundary(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path)
        page = FakePage()
        error = IncurableStepError("s", "r", FailureVerdict("incurable", "e", "rec"))

        def engine_depth_two() -> None:
            """Innermost library frame: raise through two nested helpers."""

            def engine_depth_one() -> None:
                raise error

            engine_depth_one()

        class FailingExecutor:
            """Stub executor raising through nested frames, simulating engine depth."""

            cache_key = CACHE_KEY

            def execute(self, step_text: str, step_type: str, page_: FakePage) -> None:
                engine_depth_two()

        with mock.patch.object(runtime, "open_page", return_value=page):
            test = PrettyTest(CACHE_KEY)
            test._executor = FailingExecutor()  # заглушка цикла шагов

            with pytest.raises(IncurableStepError) as excinfo:
                test.assertion("s")

        frames = [entry.filename for entry in traceback.extract_tb(excinfo.value.__traceback__)]
        assert frames[-1].endswith("scenario.py")  # внутренний кадр — граница библиотеки
        assert not any(f.endswith(("generator.py", "healer.py", "executor.py")) for f in frames)

    def test_folded_error_keeps_identity_and_context(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path)
        page = FakePage()
        error = IncurableStepError("s", "r", FailureVerdict("incurable", "e", "rec"))

        class FailingExecutor:
            """Stub executor raising the scripted terminal error."""

            cache_key = CACHE_KEY

            def execute(self, step_text: str, step_type: str, page_: FakePage) -> None:
                raise error

        with mock.patch.object(runtime, "open_page", return_value=page):
            test = PrettyTest(CACHE_KEY)
            test._executor = FailingExecutor()  # заглушка цикла шагов

            with pytest.raises(IncurableStepError) as excinfo:
                test.action("s")

        assert excinfo.value is error  # тот же объект — никогда копия
        assert excinfo.value.__context__ is None  # повторный raise не вкладывает контекст

    def test_folded_error_folds_chained_tracebacks(self, tmp_path: Path) -> None:
        """The context/cause chains survive for debugging, their internal frames do not."""
        runtime = make_runtime(tmp_path)
        page = FakePage()
        terminal = IncurableStepError("s", "r", FailureVerdict("incurable", "e", "rec"))
        original = TimeoutError("waiting for the element timed out")
        inner = IncurableStepError("s", "inner reason", FailureVerdict("rot", "e2", "r2"))

        class ChainingExecutor:
            """Stub executor raising the terminal error from an except handler."""

            cache_key = CACHE_KEY

            def execute(self, step_text: str, step_type: str, page_: FakePage) -> None:
                try:
                    raise original
                except TimeoutError:
                    # how the healer raises from the executor's except handler: context + cause
                    raise terminal from inner

        with mock.patch.object(runtime, "open_page", return_value=page):
            test = PrettyTest(CACHE_KEY)
            test._executor = ChainingExecutor()  # заглушка цикла шагов

            with pytest.raises(IncurableStepError) as excinfo:
                test.action("s")

        assert excinfo.value is terminal
        assert excinfo.value.__context__ is original  # цепочка сохранена для отладки
        assert excinfo.value.__cause__ is inner
        assert original.__traceback__ is None  # кадры цепочки свёрнуты — раннер их не покажет
        assert inner.__traceback__ is None

    def test_non_library_exception_passes_through_untouched(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path)
        page = FakePage()

        class FailingExecutor:
            """Stub executor raising a non-library exception."""

            cache_key = CACHE_KEY

            def execute(self, step_text: str, step_type: str, page_: FakePage) -> None:
                raise RuntimeError("hook bug")

        with mock.patch.object(runtime, "open_page", return_value=page):
            test = PrettyTest(CACHE_KEY)
            test._executor = FailingExecutor()  # заглушка цикла шагов

            with pytest.raises(RuntimeError) as excinfo:
                test.action("s")

        frames = [entry.filename for entry in traceback.extract_tb(excinfo.value.__traceback__)]
        assert any(f.endswith("test_scenario.py") for f in frames)  # кадры не свёрнуты
        assert frames[-1].endswith("test_scenario.py")

    def test_get_and_save_screenshot(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path)
        seed_cache(tmp_path)
        page = FakePage()
        (tmp_path / "artifacts").mkdir()

        with mock.patch.object(runtime, "open_page", return_value=page):
            test = PrettyTest(CACHE_KEY)
            test.action(STEP_TEXT)

            assert test.get_screenshot() == b"png-bytes"
            test.save_screenshot(str(tmp_path / "artifacts" / "home.png"))

        assert (tmp_path / "artifacts" / "home.png").read_bytes() == b"png-bytes"

    def test_screenshot_before_first_step_raises_library_failure(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path)

        with mock.patch.object(runtime, "open_page") as open_page_mock:
            test = PrettyTest(CACHE_KEY)

            with pytest.raises(PrettyplayError) as excinfo:
                test.get_screenshot()
            assert "run a step first" in str(excinfo.value)

            with pytest.raises(PrettyplayError):
                test.save_screenshot("x.png")

        open_page_mock.assert_not_called()

    def test_save_screenshot_write_failure_wraps_oserror(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path)
        seed_cache(tmp_path)
        page = FakePage()
        filepath = tmp_path / "missing-dir" / "x.png"

        with mock.patch.object(runtime, "open_page", return_value=page):
            test = PrettyTest(CACHE_KEY)
            test.action(STEP_TEXT)

            with pytest.raises(PrettyplayError) as excinfo:
                test.save_screenshot(str(filepath))

        assert isinstance(excinfo.value.__cause__, OSError)
        assert str(excinfo.value).startswith("cannot write the screenshot to")
        assert not filepath.exists()  # ничего не создаётся молча

    def test_scenario_close_then_screenshot_raises(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path)
        seed_cache(tmp_path)
        page = FakePage()

        with mock.patch.object(runtime, "open_page", return_value=page):
            test = PrettyTest(CACHE_KEY)
            test.action(STEP_TEXT)
            test.close()

            with pytest.raises(PrettyplayError):
                test.get_screenshot()
