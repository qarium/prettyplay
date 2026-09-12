"""Tests for the PrettyPlay scenario object of the prettyplay root cell."""

import contextlib
import inspect
import traceback
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import prettyplay
import pytest
from prettyplay import BrowserConfig, PrettyPlay
from prettyplay.cache import CachedStep, StepCache, StepIdentity, normalize_step_text
from prettyplay.config import Config, PrettyConfig
from prettyplay.failures import FailureVerdict, IncurableStepError, PrettyplayError
from prettyplay.llm import FailureClassification, LLMProvider
from prettyplay.reporting import StepHooks, StepReporter

CACHE_KEY = "k"
STEP_TEXT = "шаг"
CACHED_CODE = "def step(page) -> None:\n    page.goto('https://example.com')\n"


class FakePage:
    """Fake page boundary: records navigation, screenshots and how many times it was closed."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.close_count = 0
        self.screenshot_count = 0

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))

    def close(self) -> None:
        self.close_count += 1

    def screenshot(self) -> bytes:
        self.screenshot_count += 1
        return b"png-bytes"

    @property
    def closed(self) -> bool:
        """Whether the page context was closed at least once."""
        return self.close_count > 0


class RecordingProvider(LLMProvider):
    """Stub LLM boundary recording generation requests; any call fails the acceptance run."""

    def __init__(self) -> None:
        self.generate_calls = 0

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
    ) -> str:
        self.generate_calls += 1
        raise AssertionError("provider must not be called: the cached step runs without a generation request")

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
        raise AssertionError("provider must not be called: the cached step runs without classification")


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


@contextlib.contextmanager
def scenario_on_tmp_cache(tmp_path: Path) -> Iterator[None]:
    """Point the scenario layer at a tmp cache root, bypassing the real pyproject of the repo."""
    with mock.patch("prettyplay.scenario.load_config", return_value=Config(cache_root=str(tmp_path))):
        yield


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


@contextlib.contextmanager
def scenario_with_differing_instructions(
    tmp_path: Path,
    page: FakePage,
    provider: LLMProvider,
) -> Iterator[PrettyPlay]:
    """Build one PrettyPlay whose instructions differ from whatever generated the cached code.

    The effective config carries a tmp cache root and a non-empty
    ``generation_prompt`` passed through the ``config`` parameter; the provider
    factory and the page are patched on the runtime of this one test, per the
    established integration style of the suite.
    """
    config = Config(cache_root=str(tmp_path), generation_prompt="new instructions")
    with (
        mock.patch("prettyplay.scenario.load_config", return_value=config),
        mock.patch("prettyplay.runtime.create_provider", return_value=provider),
    ):
        test = PrettyPlay(CACHE_KEY, config=config)
        with mock.patch.object(test._runtime, "open_page", return_value=page):
            yield test


class TestPrettyPlayContract:
    """Contract tests: facade import, constructor, surface and the context-manager protocol."""

    def test_pretty_play_is_importable_from_facade(self) -> None:
        assert isinstance(PrettyPlay, type)

    def test_facade_reexports_browser_config(self) -> None:
        assert BrowserConfig is prettyplay.config.models.BrowserConfig
        assert "BrowserConfig" in prettyplay.__all__

    def test_facade_reexports_step_hooks(self) -> None:
        assert prettyplay.StepHooks is StepHooks
        assert "StepHooks" in prettyplay.__all__

    def test_constructor_signature_matches_contract(self) -> None:
        parameters = list(inspect.signature(PrettyPlay.__init__).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["cache_key", "cache_path", "hooks", "config"]
        assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD  # cache_key stays positional
        assert parameters[1].default is None
        assert parameters[2].default is None
        assert parameters[2].kind is inspect.Parameter.KEYWORD_ONLY  # hooks — keyword-only
        assert parameters[3].default is None
        assert parameters[3].kind is inspect.Parameter.KEYWORD_ONLY  # config — keyword-only, as before

    def test_surface_matches_contract(self) -> None:
        assert isinstance(PrettyPlay.cache_key, property)

        for name in (
            "step",
            "expect",
            "get_screenshot",
            "save_screenshot",
            "add_hooks",
            "close",
            "__enter__",
            "__exit__",
        ):
            assert callable(getattr(PrettyPlay, name)), name

    def test_step_method_signatures_match_contract(self) -> None:
        assert list(inspect.signature(PrettyPlay.step).parameters) == ["self", "text"]
        assert list(inspect.signature(PrettyPlay.expect).parameters) == ["self", "text"]

    def test_add_hooks_and_close_signatures_match_contract(self) -> None:
        assert list(inspect.signature(PrettyPlay.add_hooks).parameters) == ["self", "hooks"]
        assert list(inspect.signature(PrettyPlay.close).parameters) == ["self"]

    def test_screenshot_method_signatures_match_contract(self) -> None:
        assert list(inspect.signature(PrettyPlay.get_screenshot).parameters) == ["self"]
        assert list(inspect.signature(PrettyPlay.save_screenshot).parameters) == ["self", "filepath"]


class TestPrettyPlayLogic:
    """Logic tests: page lifecycle, laziness, hooks registration and error pass-through."""

    def test_step_and_expect_delegate_step_types(self, tmp_path: Path) -> None:
        seed_cache(tmp_path, step_type="action")
        seed_cache(tmp_path, step_type="assertion")
        page = FakePage()
        hook = RecorderHook()

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)

            with mock.patch.object(test._runtime, "open_page", return_value=page):
                test.add_hooks(hook)
                test.step(STEP_TEXT)
                test.expect(STEP_TEXT)
                test.close()

        assert ("on_step_started", {"step_text": STEP_TEXT, "step_type": "action"}) in hook.events
        assert ("on_step_passed", {"step_text": STEP_TEXT, "step_type": "assertion"}) in hook.events
        assert not [payload for event, payload in hook.events if event == "on_step_failed"]

    def test_constructor_hooks_seed_the_reporter(self, tmp_path: Path) -> None:
        """The keyword-only hooks parameter seeds the reporter — no add_hooks needed."""
        seed_cache(tmp_path)
        page = FakePage()
        hook = RecorderHook()

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY, hooks=[hook])

            with mock.patch.object(test._runtime, "open_page", return_value=page):
                test.step(STEP_TEXT)
                test.close()

        assert ("on_step_started", {"step_text": STEP_TEXT, "step_type": "action"}) in hook.events
        assert ("on_step_passed", {"step_text": STEP_TEXT, "step_type": "action"}) in hook.events

        with scenario_on_tmp_cache(tmp_path):
            silent = PrettyPlay(CACHE_KEY, hooks=None)  # None — an empty hooks list, steps still run

            with mock.patch.object(silent._runtime, "open_page", return_value=page):
                silent.step(STEP_TEXT)
                silent.close()

    def test_scenario_builds_own_runtime_per_test(self, tmp_path: Path) -> None:
        """ADR-1 core acceptance: two tests hold two runtimes with two registries, no singleton."""
        with mock.patch("prettyplay.scenario.load_config", return_value=Config(model="gpt-5")) as load_config_mock:
            t1 = PrettyPlay("k1")
            t2 = PrettyPlay("k2")

            assert t1._runtime is not t2._runtime
            assert t1._runtime.budgets is not t2._runtime.budgets
            assert load_config_mock.call_args_list == [mock.call(None, None), mock.call(None, None)]

    def test_scenario_forwards_config_overrides_through_real_loader(
        self, tmp_path: Path, write_pyproject, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ``config`` parameter reaches the real ``load_config``: explicit values win, the file layer survives."""
        for name in (
            "PRETTYPLAY_MODEL",
            "PRETTYPLAY_BROWSER_NAME",
            "PRETTYPLAY_BROWSER_SCREEN",
            "PRETTYPLAY_BROWSER_HEADLESS",
            "PRETTYPLAY_BROWSER_ENDPOINT",
            "PRETTYPLAY_STRICT",
            "PRETTYPLAY_CLASSIFICATION_PROMPT",
            "PRETTYPLAY_CACHE_ROOT",
            "PRETTYPLAY_GENERATION_PROMPT",
        ):
            monkeypatch.delenv(name, raising=False)

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.prettyplay]\nmodel = "gpt-4o"\ngeneration_prompt = "file instructions"\n'
            '\n[tool.prettyplay.browser]\nname = "firefox"\n',
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)  # load_config(None) walks up from cwd for pyproject.toml

        test = PrettyPlay(CACHE_KEY, config=PrettyConfig(generation_prompt="per-test instructions"))

        effective = test._runtime.config
        assert effective.generation_prompt == "per-test instructions"  # the programmatic layer wins
        assert effective.model == "gpt-4o"  # untouched fields come from the file
        assert effective.browser.name == "firefox"
        assert effective.cache_root == str(tmp_path / ".prettyplay" / "cache")

    def test_default_cache_root_anchors_at_run_cwd_below_pyproject(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Launched from a directory below the pyproject, the cache roots at the run's directory."""
        for name in ("PRETTYPLAY_CACHE_ROOT", "PRETTYPLAY_MODEL"):
            monkeypatch.delenv(name, raising=False)

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.prettyplay]\nmodel = "gpt-4o"\n', encoding="utf-8")
        run_dir = tmp_path / "example"
        run_dir.mkdir()
        monkeypatch.chdir(run_dir)  # the suite runs below the pyproject, as from example/

        test = PrettyPlay(CACHE_KEY)

        assert test._runtime.config.model == "gpt-4o"  # settings still load from the pyproject above
        assert test._runtime.config.cache_root == str(run_dir / ".prettyplay" / "cache")

    def test_pretty_test_wires_config_and_provider_into_executor(self, tmp_path: Path) -> None:
        """The runtime config and the runtime provider reach the executor; no browser launched."""
        config = PrettyConfig(
            cache_root=str(tmp_path),
            strict=True,
            browser=BrowserConfig(screen="fullscreen", headless=False),
        )

        with mock.patch("prettyplay.scenario.load_config", return_value=config):
            test = PrettyPlay(CACHE_KEY)

        executor = test._executor
        assert executor._config is test._runtime.config  # the wired executor reads the runtime settings
        assert executor._config.strict is True
        assert executor._config.browser.screen == "fullscreen"
        assert executor._config.browser.headless is False
        assert executor._provider is test._runtime.provider  # the runtime provider instance, lazily built
        assert test._runtime._driver is None  # construction stays browser-free

    def test_scenario_close_stops_page_and_runtime(self, tmp_path: Path) -> None:
        seed_cache(tmp_path)
        page = FakePage()

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)
            runtime = test._runtime
            driver_mock = mock.Mock(name="driver")
            runtime._driver = driver_mock  # a started driver: the test close must stop it

            with mock.patch.object(runtime, "open_page", return_value=page) as open_page_mock:
                test.step(STEP_TEXT)
                open_page_mock.assert_called_once()

                test.close()
                test.close()  # idempotent: neither the page nor the driver closes twice

        assert page.close_count == 1
        driver_mock.close.assert_called_once()  # plan: «the driver close recorded once»
        assert runtime._driver is None  # stopped session no longer held by the runtime

    def test_scenario_close_stops_runtime_when_page_close_fails(self, tmp_path: Path) -> None:
        """A failing page close (a crashed browser) never keeps the runtime alive."""
        seed_cache(tmp_path)

        class CrashingPage(FakePage):
            def close(self) -> None:
                self.close_count += 1
                raise RuntimeError("page close failed")

        page = CrashingPage()

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)
            runtime = test._runtime
            driver_mock = mock.Mock(name="driver")
            runtime._driver = driver_mock

            with mock.patch.object(runtime, "open_page", return_value=page):
                test.step(STEP_TEXT)

                with pytest.raises(RuntimeError, match="page close failed"):
                    test.close()

                driver_mock.close.assert_called_once()  # runtime stopped even though the page close failed
                test.close()  # failed page close is not retried

        assert page.close_count == 1
        assert test._page is None

    def test_scenario_close_before_first_step_is_safe(self, tmp_path: Path) -> None:
        seed_cache(tmp_path)

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)
            test.close()  # nothing started — close does not raise

            with mock.patch.object(test._runtime, "open_page", return_value=FakePage()) as open_page_mock:
                test.step(STEP_TEXT)  # page still opens lazily after close

                open_page_mock.assert_called_once()

    def test_context_manager_closes_page_and_test(self, tmp_path: Path) -> None:
        seed_cache(tmp_path)
        pages: list[FakePage] = []

        def fresh_page() -> FakePage:
            page = FakePage()
            pages.append(page)
            return page

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)

            with mock.patch.object(test._runtime, "open_page", side_effect=fresh_page):
                with test as running:
                    running.step(STEP_TEXT)

                assert len(pages) == 1
                assert pages[0].closed is True

            with PrettyPlay(CACHE_KEY):
                pass

        assert len(pages) == 1  # page two opens on the first step, not on construction


    def test_construction_is_lazy_and_returns_cache_key(self, tmp_path: Path) -> None:
        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)

            assert test.cache_key == CACHE_KEY
            assert test._page is None  # page opens lazily on the first step
            assert test._runtime._driver is None  # browser not started on construction

        assert isinstance(test._runtime._provider, object)  # provider is cheap: a client without a key

    def test_cache_path_participates_in_addressing(self, tmp_path: Path) -> None:
        seed_cache(tmp_path)
        checkout_code = "def step(page) -> None:\n    page.goto('https://checkout.example.com')\n"
        identity = StepIdentity(cache_key=CACHE_KEY, step_type="action", normalized_text=normalize_step_text(STEP_TEXT))
        StepCache(Config(cache_root=str(tmp_path)), "checkout", StepReporter(hooks=[])).save(
            CachedStep(identity=identity, code=checkout_code, created_at="2026-09-08")
        )
        shared = StepCache(Config(cache_root=str(tmp_path)), None, StepReporter(hooks=[]))
        page = FakePage()

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY, cache_path="checkout")

            with mock.patch.object(test._runtime, "open_page", return_value=page):
                test.step(STEP_TEXT)
                test.close()

            # the same identity triple resolves to different addresses: the subdirectory
            # step runs, and neither store sees the copy of the other
        assert page.calls == [("goto", "https://checkout.example.com")]
        assert shared.load(identity) is not None
        assert test._cache.load(identity).code.rstrip("\n") == checkout_code.rstrip("\n")
        assert shared.load(identity).code != test._cache.load(identity).code

    def test_exit_closes_page_and_never_suppresses(self, tmp_path: Path) -> None:
        seed_cache(tmp_path)
        page = FakePage()

        def failing_scenario() -> None:
            """Open the page through a step, then fail the scenario block."""
            with scenario_on_tmp_cache(tmp_path), PrettyPlay(CACHE_KEY) as test:
                with mock.patch.object(test._runtime, "open_page", return_value=page):
                    test.step(STEP_TEXT)
                raise RuntimeError("scenario failure")

        with pytest.raises(RuntimeError, match="scenario failure"):
            failing_scenario()

        assert page.closed is True

    def test_close_twice_is_noop(self, tmp_path: Path) -> None:
        seed_cache(tmp_path)
        page = FakePage()

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)

            with mock.patch.object(test._runtime, "open_page", return_value=page):
                test.step(STEP_TEXT)
                test.close()
                test.close()

        assert page.close_count == 1

    def test_expect_folds_traceback_to_boundary(self, tmp_path: Path) -> None:
        page = FakePage()
        error = IncurableStepError("s", "r", "", FailureVerdict("incurable", "e", "rec"))

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

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)

            with mock.patch.object(test._runtime, "open_page", return_value=page):
                test._executor = FailingExecutor()  # step-loop stub

                with pytest.raises(IncurableStepError) as excinfo:
                    test.expect("s")

        frames = [entry.filename for entry in traceback.extract_tb(excinfo.value.__traceback__)]
        assert frames[-1].endswith("scenario.py")  # inner frame — the library boundary
        assert not any(f.endswith(("generator.py", "healer.py", "executor.py")) for f in frames)

    def test_folded_error_keeps_identity_and_context(self, tmp_path: Path) -> None:
        page = FakePage()
        error = IncurableStepError("s", "r", "", FailureVerdict("incurable", "e", "rec"))

        class FailingExecutor:
            """Stub executor raising the scripted terminal error."""

            cache_key = CACHE_KEY

            def execute(self, step_text: str, step_type: str, page_: FakePage) -> None:
                raise error

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)

            with mock.patch.object(test._runtime, "open_page", return_value=page):
                test._executor = FailingExecutor()  # step-loop stub

                with pytest.raises(IncurableStepError) as excinfo:
                    test.step("s")

        assert excinfo.value is error  # same object — never a copy
        assert excinfo.value.__context__ is None  # re-raise does not nest context

    def test_folded_error_folds_chained_tracebacks(self, tmp_path: Path) -> None:
        """The context/cause chains survive for debugging, their internal frames do not."""
        page = FakePage()
        terminal = IncurableStepError("s", "r", "", FailureVerdict("incurable", "e", "rec"))
        original = TimeoutError("waiting for the element timed out")
        inner = IncurableStepError("s", "inner reason", "", FailureVerdict("rot", "e2", "r2"))

        class ChainingExecutor:
            """Stub executor raising the terminal error from an except handler."""

            cache_key = CACHE_KEY

            def execute(self, step_text: str, step_type: str, page_: FakePage) -> None:
                try:
                    raise original
                except TimeoutError:
                    # how the healer raises from the executor's except handler: context + cause
                    raise terminal from inner

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)

            with mock.patch.object(test._runtime, "open_page", return_value=page):
                test._executor = ChainingExecutor()  # step-loop stub

                with pytest.raises(IncurableStepError) as excinfo:
                    test.step("s")

        assert excinfo.value is terminal
        assert excinfo.value.__context__ is original  # chain preserved for debugging
        assert excinfo.value.__cause__ is inner
        assert original.__traceback__ is None  # chained frames collapsed — the runner won't show them
        assert inner.__traceback__ is None

    def test_non_library_exception_passes_through_untouched(self, tmp_path: Path) -> None:
        page = FakePage()

        class FailingExecutor:
            """Stub executor raising a non-library exception."""

            cache_key = CACHE_KEY

            def execute(self, step_text: str, step_type: str, page_: FakePage) -> None:
                raise RuntimeError("hook bug")

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)

            with mock.patch.object(test._runtime, "open_page", return_value=page):
                test._executor = FailingExecutor()  # step-loop stub

                with pytest.raises(RuntimeError) as excinfo:
                    test.step("s")

        frames = [entry.filename for entry in traceback.extract_tb(excinfo.value.__traceback__)]
        assert any(f.endswith("test_scenario.py") for f in frames)  # frames not collapsed
        assert frames[-1].endswith("test_scenario.py")

    def test_get_and_save_screenshot(self, tmp_path: Path) -> None:
        seed_cache(tmp_path)
        page = FakePage()
        (tmp_path / "artifacts").mkdir()

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)

            with mock.patch.object(test._runtime, "open_page", return_value=page):
                test.step(STEP_TEXT)

                assert test.get_screenshot() == b"png-bytes"
                test.save_screenshot(str(tmp_path / "artifacts" / "home.png"))

        assert (tmp_path / "artifacts" / "home.png").read_bytes() == b"png-bytes"

    def test_screenshot_before_first_step_raises_library_failure(self, tmp_path: Path) -> None:
        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)

            with mock.patch.object(test._runtime, "open_page") as open_page_mock:
                with pytest.raises(PrettyplayError) as excinfo:
                    test.get_screenshot()
                assert "run a step first" in str(excinfo.value)

                with pytest.raises(PrettyplayError):
                    test.save_screenshot("x.png")

        open_page_mock.assert_not_called()

    def test_save_screenshot_write_failure_wraps_oserror(self, tmp_path: Path) -> None:
        seed_cache(tmp_path)
        page = FakePage()
        filepath = tmp_path / "missing-dir" / "x.png"

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)

            with mock.patch.object(test._runtime, "open_page", return_value=page):
                test.step(STEP_TEXT)

                with pytest.raises(PrettyplayError) as excinfo:
                    test.save_screenshot(str(filepath))

        assert isinstance(excinfo.value.__cause__, OSError)
        assert str(excinfo.value).startswith("cannot write the screenshot to")
        assert not filepath.exists()  # nothing created silently

    def test_scenario_close_then_screenshot_raises(self, tmp_path: Path) -> None:
        seed_cache(tmp_path)
        page = FakePage()

        with scenario_on_tmp_cache(tmp_path):
            test = PrettyPlay(CACHE_KEY)

            with mock.patch.object(test._runtime, "open_page", return_value=page):
                test.step(STEP_TEXT)
                test.close()

                with pytest.raises(PrettyplayError):
                    test.get_screenshot()


class TestInstructionsIndependentCacheAddress:
    """ADR-3 acceptance: the cache address ignores the instructions setting.

    The instructions never enter ``StepIdentity``, so a cached step executes
    through ``run_step_code`` with zero provider involvement even when
    ``generation_prompt`` differs from whatever generated the cached code —
    the cache is never invalidated by an instructions change.
    """

    def test_cached_step_runs_without_provider_when_instructions_differ(self, tmp_path: Path) -> None:
        seed_cache(tmp_path)
        page = FakePage()
        provider = RecordingProvider()

        with scenario_with_differing_instructions(tmp_path, page, provider) as test:
            test.step(STEP_TEXT)
            test.close()

        assert page.calls == [("goto", "https://example.com")]  # cached code executed as-is
        assert provider.generate_calls == 0  # zero generation requests — cache not regenerated

    def test_shared_root_reuses_cached_step_across_independent_budgets(self, tmp_path: Path) -> None:
        """Two tests with one cache_key share the cached step while their budgets stay per-test."""
        seed_cache(tmp_path)
        first_page = FakePage()
        second_page = FakePage()
        provider = RecordingProvider()

        with scenario_with_differing_instructions(tmp_path, first_page, provider) as first:
            first.step(STEP_TEXT)
            first.close()

        with scenario_with_differing_instructions(tmp_path, second_page, provider) as second:
            second.step(STEP_TEXT)
            second.close()

        # both tests execute the same cached step from the shared root
        assert first_page.calls == [("goto", "https://example.com")]
        assert second_page.calls == [("goto", "https://example.com")]
        assert provider.generate_calls == 0

        # per-test budget registries: one test's attempts never spend the other's budget
        assert first._runtime.budgets is not second._runtime.budgets
        assert first._runtime.budgets._generation_used == {}  # cache hit spends no attempts
        assert second._runtime.budgets._generation_used == {}
        assert (
            first._runtime.budgets.try_generation(
                StepIdentity(cache_key=CACHE_KEY, step_type="action", normalized_text=normalize_step_text(STEP_TEXT))
            )
            is True
        )
