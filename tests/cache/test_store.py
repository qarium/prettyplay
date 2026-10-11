"""Tests for the StepCache repository store of the prettyplay.cache cell."""

import importlib.util
import inspect
import logging
import os
import pathlib
from pathlib import Path
from unittest import mock

import pytest
from prettyplay.cache import CachedStep, StepCache, StepIdentity, normalize_step_text
from prettyplay.config import Config
from prettyplay.reporting import StepHooks, StepReporter


class TestStepCacheContract:
    """Contract tests: facade import, signature shape, properties and methods."""

    def test_step_cache_is_importable_from_facade(self) -> None:
        assert isinstance(StepCache, type)

    def test_signature_is_config_path_reporter(self) -> None:
        parameters = list(inspect.signature(StepCache.__init__).parameters.values())[1:]  # drop self

        assert [parameter.name for parameter in parameters] == ["config", "path", "reporter"]
        assert parameters[1].default is None  # path is optional

    def test_constructs_with_config_path_and_reporter(self) -> None:
        cache = StepCache(Config(cache_root="/tmp/pp-store-contract"), "checkout", StepReporter(hooks=[]))

        assert isinstance(cache, StepCache)

    def test_root_is_str_and_writable_is_bool(self) -> None:
        cache = StepCache(Config(cache_root="/tmp/pp-store-contract"), None, StepReporter(hooks=[]))

        assert isinstance(cache.root, str)
        assert isinstance(cache.writable, bool)

    def test_declares_load_and_save_methods(self) -> None:
        load_parameters = list(inspect.signature(StepCache.load).parameters.values())[1:]
        save_parameters = list(inspect.signature(StepCache.save).parameters.values())[1:]

        assert [parameter.name for parameter in load_parameters] == ["identity"]
        assert [parameter.name for parameter in save_parameters] == ["step"]

    def test_declares_callable_sweep_untouched(self) -> None:
        assert callable(StepCache.sweep_untouched)

    def test_sweep_untouched_signature_is_cache_key(self) -> None:
        parameters = list(inspect.signature(StepCache.sweep_untouched).parameters.values())[1:]

        assert [parameter.name for parameter in parameters] == ["cache_key"]


class EventRecorder(StepHooks):
    """Hook recording cache events into a shared ``calls`` list for assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def on_cache_saved(self, step_text: str, filename: str) -> None:
        self.calls.append(("on_cache_saved", {"step_text": step_text, "filename": filename}))

    def on_cache_skipped(self, step_text: str, reason: str) -> None:
        self.calls.append(("on_cache_skipped", {"step_text": step_text, "reason": reason}))


def make_cache(tmp_path: Path, path: str | None = "checkout") -> tuple[StepCache, EventRecorder]:
    """Build a cache on tmp_path with a recording reporter."""
    recorder = EventRecorder()
    reporter = StepReporter(hooks=[recorder])
    config = Config(cache_root=str(tmp_path))
    return StepCache(config, path, reporter), recorder


def write_step_file(target: Path, step_text: str, cache_key: str) -> None:
    """Hand-write a parseable cache file in the serialized on-disk format."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"STEP_TEXT = {step_text!r}\n"
        f"CACHE_KEY = {cache_key!r}\n"
        "STEP_TYPE = 'action'\n"
        "CREATED_AT = '2026-01-01'\n"
        "\n# --- step code ---\n"
        "def step(page) -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )


STEP_CODE = "def step(page) -> None:\n    page.goto('https://x')\n"

#: The generated shape since the import-policy change: imports live at the top
#: level before ``def step`` — the round-trip must keep them, a replay needs them.
IMPORTING_STEP_CODE = (
    "from playwright.sync_api import expect\n"
    "\n"
    "\n"
    "def step(page) -> None:\n"
    "    expect(page.locator('form')).to_have_count(2)\n"
)


class TestStepCacheLogic:
    """Logic tests: roundtrip via the file, protective load, loud skips."""

    def test_save_load_roundtrip_via_file(self, tmp_path: Path, caplog) -> None:
        cache, recorder = make_cache(tmp_path)
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="открыть страницу логина")

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            stored = cache.save(
                CachedStep(
                    identity=identity, addressing_text=identity.normalized_text, code=STEP_CODE, created_at="2026-09-07"
                )
            )
        loaded = cache.load(identity)

        assert stored is True  # the atomic replace landed
        assert loaded is not None
        assert loaded.identity == identity
        assert loaded.code.startswith("def step(")
        assert loaded.created_at == "2026-09-07"

        file_path = tmp_path / "checkout" / identity.filename
        text = file_path.read_text(encoding="utf-8")
        assert text.startswith("STEP_TEXT =")
        assert "def step(" in text

        saved_events = [call for call in recorder.calls if call[0] == "on_cache_saved"]
        assert saved_events == [
            ("on_cache_saved", {"step_text": "открыть страницу логина", "filename": identity.filename})
        ]

        info_records = [
            record for record in caplog.records if record.levelno == logging.INFO and record.name == "prettyplay"
        ]
        assert any(record.msg == "on_cache_saved" for record in info_records)
        saved_record = next(record for record in info_records if record.msg == "on_cache_saved")
        assert saved_record.ctx_filename == identity.filename  # type: ignore[attr-defined]

    def test_roundtrip_keeps_top_level_imports(self, tmp_path: Path) -> None:
        """Regression: the code tail boundary is the sentinel line, not `def step(` —
        top-level imports written before the function survive the round-trip, so a
        replayed cached step does not die on `NameError: name 'expect' is not defined`."""
        cache, _ = make_cache(tmp_path)
        identity = StepIdentity(cache_key="videos", step_type="assertion", normalized_text="видео больше одного")

        cache.save(
            CachedStep(
                identity=identity,
                addressing_text=identity.normalized_text,
                code=IMPORTING_STEP_CODE,
                created_at="2026-09-14",
            )
        )
        loaded = cache.load(identity)

        assert loaded is not None
        assert loaded.code.startswith("from playwright.sync_api import expect")
        assert "def step(page) -> None:" in loaded.code

    def test_legacy_file_without_sentinel_still_loads(self, tmp_path: Path) -> None:
        """Files written before the sentinel carry the code starting at `def step(`
        (the old prompt forbade top-level imports) — they keep loading as before."""
        cache, _ = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="старый файл")
        target_dir = tmp_path / "checkout"
        target_dir.mkdir(parents=True)
        (target_dir / identity.filename).write_text(
            "STEP_TEXT = 'старый файл'\n"
            "CACHE_KEY = 'k'\n"
            "STEP_TYPE = 'action'\n"
            "CREATED_AT = '2026-01-01'\n"
            "\n"
            "def step(page) -> None:\n"
            "    page.goto('https://legacy')\n",
            encoding="utf-8",
        )

        loaded = cache.load(identity)

        assert loaded is not None
        assert loaded.created_at == "2026-01-01"
        assert loaded.code.startswith("def step(")

    @pytest.mark.skipif(os.geteuid() == 0, reason="root игнорирует режимы файлов")
    def test_save_readonly_cache_skips_loudly(self, tmp_path: Path) -> None:
        root = tmp_path / "readonly"
        root.mkdir()
        root.chmod(0o500)

        try:
            recorder = EventRecorder()
            reporter = StepReporter(hooks=[recorder])
            cache = StepCache(Config(cache_root=str(root)), "checkout", reporter)
            identity = StepIdentity(cache_key="k", step_type="action", normalized_text="шаг")

            stored = cache.save(
                CachedStep(
                    identity=identity, addressing_text=identity.normalized_text, code=STEP_CODE, created_at="2026-09-07"
                )
            )

            assert stored is False  # the skipped write reports itself
            assert not (root / "checkout").exists()  # no file created
            skipped_events = [call for call in recorder.calls if call[0] == "on_cache_skipped"]
            assert skipped_events == [("on_cache_skipped", {"step_text": "шаг", "reason": "read-only cache"})]
        finally:
            root.chmod(0o700)  # restore so tmp_path cleanup works

    def test_load_missing_file_returns_none(self, tmp_path: Path) -> None:
        cache, _ = make_cache(tmp_path)

        result = cache.load(StepIdentity(cache_key="k", step_type="action", normalized_text="нет такого шага"))

        assert result is None

    def test_load_non_string_step_text_is_a_cache_miss(self, tmp_path: Path) -> None:
        cache, _ = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="open page")
        target = tmp_path / "checkout" / identity.filename
        target.parent.mkdir(parents=True)
        target.write_text(
            "STEP_TEXT = 42\n"
            "CACHE_KEY = 'k'\n"
            "STEP_TYPE = 'action'\n"
            "CREATED_AT = '2026-01-01'\n"
            "\n# --- step code ---\n"
            "def step(page) -> None:\n    pass\n",
            encoding="utf-8",
        )

        assert cache.load(identity) is None
        assert cache._touched == set()

    def test_load_metadata_mismatch_treated_as_miss(self, tmp_path: Path) -> None:
        cache, _ = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="оригинальный шаг")

        cache.save(
            CachedStep(
                identity=identity, addressing_text=identity.normalized_text, code=STEP_CODE, created_at="2026-09-07"
            )
        )
        file_path = tmp_path / "checkout" / identity.filename
        text = file_path.read_text(encoding="utf-8")
        file_path.write_text(
            text.replace("STEP_TEXT = 'оригинальный шаг'", 'STEP_TEXT = "подменённый шаг"'),
            encoding="utf-8",
        )

        assert cache.load(identity) is None  # the step will be regenerated, the run survives

    def test_load_corrupt_file_treated_as_miss(self, tmp_path: Path) -> None:
        cache, _ = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="сломанный шаг")

        target_dir = tmp_path / "checkout"
        target_dir.mkdir(parents=True)
        (target_dir / identity.filename).write_text("garbage not a module", encoding="utf-8")

        assert cache.load(identity) is None  # no exceptions

    def test_saved_file_is_a_valid_python_module(self, tmp_path: Path) -> None:
        """Additional edge: the artifact committed to the repo imports as a module."""
        cache, _ = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="шаг модуль")

        cache.save(
            CachedStep(
                identity=identity, addressing_text=identity.normalized_text, code=STEP_CODE, created_at="2026-09-07"
            )
        )
        path = tmp_path / "checkout" / identity.filename

        spec = importlib.util.spec_from_file_location("cached_step", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        assert module.STEP_TEXT == "шаг модуль"  # type: ignore[attr-defined]
        assert module.CACHE_KEY == "k"  # type: ignore[attr-defined]
        assert module.STEP_TYPE == "action"  # type: ignore[attr-defined]
        assert module.CREATED_AT == "2026-09-07"  # type: ignore[attr-defined]
        assert callable(module.step)  # type: ignore[attr-defined]

    def test_no_temp_files_left_behind(self, tmp_path: Path) -> None:
        """Additional edge: atomic save leaves only the target file in the directory."""
        cache, _ = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="шаг атомарно")

        cache.save(
            CachedStep(
                identity=identity, addressing_text=identity.normalized_text, code=STEP_CODE, created_at="2026-09-07"
            )
        )
        cache.save(
            CachedStep(
                identity=identity, addressing_text=identity.normalized_text, code=STEP_CODE, created_at="2026-09-08"
            )
        )  # overwrite

        files = sorted(entry.name for entry in (tmp_path / "checkout").iterdir())
        assert files == [identity.filename]  # last writer wins, temp removed

    def test_busy_target_retries_then_skips_loudly(self, tmp_path: Path) -> None:
        """Additional edge: PermissionError on replace → skip with cache target busy, run lives."""
        cache, recorder = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="занятая цель")

        with mock.patch("prettyplay.cache.store.os.replace", side_effect=PermissionError("busy")):
            cache.save(
                CachedStep(
                    identity=identity, addressing_text=identity.normalized_text, code=STEP_CODE, created_at="2026-09-07"
                )
            )

        skipped_events = [call for call in recorder.calls if call[0] == "on_cache_skipped"]
        assert skipped_events == [("on_cache_skipped", {"step_text": "занятая цель", "reason": "cache target busy"})]
        assert cache.load(identity) is None  # the partial file never became visible

    def test_replace_oserror_skips_loudly(self, tmp_path: Path) -> None:
        """Additional edge: any OSError on replace (not only PermissionError) skips, never fails."""
        cache, recorder = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="пропавшая цель")

        with mock.patch("prettyplay.cache.store.os.replace", side_effect=FileNotFoundError("dir gone")):
            cache.save(
                CachedStep(
                    identity=identity, addressing_text=identity.normalized_text, code=STEP_CODE, created_at="2026-09-07"
                )
            )

        skipped_events = [call for call in recorder.calls if call[0] == "on_cache_skipped"]
        assert skipped_events == [("on_cache_skipped", {"step_text": "пропавшая цель", "reason": "cache target busy"})]

    def test_mkstemp_failure_skips_loudly(self, tmp_path: Path) -> None:
        """Additional edge: the temp file cannot be created → skip, the run continues."""
        cache, recorder = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="нет temp")

        with mock.patch("prettyplay.cache.store.tempfile.mkstemp", side_effect=OSError("no space")):
            cache.save(
                CachedStep(
                    identity=identity, addressing_text=identity.normalized_text, code=STEP_CODE, created_at="2026-09-07"
                )
            )

        skipped_events = [call for call in recorder.calls if call[0] == "on_cache_skipped"]
        assert skipped_events == [("on_cache_skipped", {"step_text": "нет temp", "reason": "cache target busy"})]

    def test_write_failure_cleans_temp_and_skips(self, tmp_path: Path) -> None:
        """Additional edge: the temp write fails → temp removed, skip emitted, no partial file."""
        cache, recorder = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="сбой записи")

        with mock.patch("prettyplay.cache.store.os.fsync", side_effect=OSError("io error")):
            cache.save(
                CachedStep(
                    identity=identity, addressing_text=identity.normalized_text, code=STEP_CODE, created_at="2026-09-07"
                )
            )

        files = sorted(entry.name for entry in (tmp_path / "checkout").iterdir())
        assert files == []  # temp file removed, no target
        skipped_events = [call for call in recorder.calls if call[0] == "on_cache_skipped"]
        assert skipped_events == [("on_cache_skipped", {"step_text": "сбой записи", "reason": "cache target busy"})]

    def test_unencodable_text_skips_loudly(self, tmp_path: Path) -> None:
        """Additional edge: a lone surrogate in the step text raises UnicodeEncodeError (a
        ValueError, not an OSError) on write — the skip path must still catch it, remove
        the temp file and keep the run alive."""
        cache, recorder = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="шаг с \udcff суррогатом")

        cache.save(
            CachedStep(
                identity=identity, addressing_text=identity.normalized_text, code=STEP_CODE, created_at="2026-09-07"
            )
        )

        files = sorted(entry.name for entry in (tmp_path / "checkout").iterdir())
        assert files == []  # temp file removed, no target
        skipped_events = [call for call in recorder.calls if call[0] == "on_cache_skipped"]
        assert skipped_events == [
            ("on_cache_skipped", {"step_text": "шаг с \udcff суррогатом", "reason": "cache target busy"})
        ]

    def test_load_header_without_step_marker_is_miss(self, tmp_path: Path) -> None:
        """Additional edge: parseable header but no def step( tail → protective miss."""
        cache, _ = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="шаг без хвоста")
        target_dir = tmp_path / "checkout"
        target_dir.mkdir(parents=True)
        (target_dir / identity.filename).write_text(
            "STEP_TEXT = 'шаг без хвоста'\nCACHE_KEY = 'k'\nSTEP_TYPE = 'action'\nCREATED_AT = '2026-09-07'\n",
            encoding="utf-8",
        )

        assert cache.load(identity) is None

    def test_load_missing_header_field_is_miss(self, tmp_path: Path) -> None:
        """Additional edge: a header without CREATED_AT → protective miss, never a crash."""
        cache, _ = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="шаг без поля")
        target_dir = tmp_path / "checkout"
        target_dir.mkdir(parents=True)
        (target_dir / identity.filename).write_text(
            "STEP_TEXT = 'шаг без поля'\nCACHE_KEY = 'k'\nSTEP_TYPE = 'action'\n\ndef step(page) -> None:\n    pass\n",
            encoding="utf-8",
        )

        assert cache.load(identity) is None

    def test_load_cache_key_mismatch_is_miss(self, tmp_path: Path) -> None:
        """Additional edge: the digest matches one field edit, the other diverges → miss."""
        cache, _ = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="шаг чужого ключа")

        cache.save(
            CachedStep(
                identity=identity, addressing_text=identity.normalized_text, code=STEP_CODE, created_at="2026-09-07"
            )
        )
        file_path = tmp_path / "checkout" / identity.filename
        text = file_path.read_text(encoding="utf-8")
        file_path.write_text(text.replace("CACHE_KEY = 'k'", "CACHE_KEY = 'другой'"), encoding="utf-8")

        assert cache.load(identity) is None

    def test_default_reporter_construction_saves_and_skips_loudly(self, tmp_path: Path) -> None:
        """Additional edge: no reporter passed — construction and save still work (no crash)."""
        cache = StepCache(Config(cache_root=str(tmp_path)), "checkout")
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="шаг без репортёра")

        cache.save(
            CachedStep(
                identity=identity, addressing_text=identity.normalized_text, code=STEP_CODE, created_at="2026-09-07"
            )
        )
        loaded = cache.load(identity)

        assert loaded is not None  # write and read without AttributeError

    @pytest.mark.parametrize("bad_path", ["/etc", "../../outside"])
    def test_path_outside_cache_root_fails_loudly(self, tmp_path: Path, bad_path: str) -> None:
        """Additional edge: absolute or escaping cache paths are rejected at construction."""
        with pytest.raises(ValueError, match="cache path"):
            StepCache(Config(cache_root=str(tmp_path)), bad_path)

    @pytest.mark.parametrize("good_path", ["bin", "lib", "nested/dir", "./relative"])
    def test_relative_paths_are_host_independent(self, tmp_path: Path, good_path: str) -> None:
        """Regression: a relative subdir is accepted regardless of host symlinks (merged-/usr)."""
        cache = StepCache(Config(cache_root=str(tmp_path)), good_path)

        assert cache.root == str(tmp_path)


class TestStepCacheWorkingSet:
    """Logic tests: the STEP_TEXT contract and the per-test working-set sweep."""

    def test_save_serializes_step_text_from_addressing_text(self, tmp_path: Path) -> None:
        """The metadata sentence is the addressing text — verbatim, pre-normalization."""
        cache, _ = make_cache(tmp_path, path=None)
        identity = StepIdentity(
            cache_key="k", step_type="action", normalized_text=normalize_step_text("Open the item named Book")
        )

        stored = cache.save(
            CachedStep(
                identity=identity,
                addressing_text="Open the item named Book",
                code="def step(page):\n    ...",
                created_at="2026-10-11",
            )
        )

        assert stored is True
        text = (tmp_path / identity.filename).read_text(encoding="utf-8")
        assert text.startswith("STEP_TEXT = 'Open the item named Book'")
        round_step = cache.load(identity)

        assert round_step is not None
        assert round_step.addressing_text == "Open the item named Book"

        padded = StepIdentity(cache_key="k", step_type="action", normalized_text="Open the padded page")
        cache.save(
            CachedStep(
                identity=padded, addressing_text="  Open the padded page  ", code=STEP_CODE, created_at="2026-10-11"
            )
        )
        padded_text = (tmp_path / padded.filename).read_text(encoding="utf-8")

        assert padded_text.startswith("STEP_TEXT = '  Open the padded page  '")
        round_padded = cache.load(padded)

        assert round_padded is not None
        assert round_padded.addressing_text == "  Open the padded page  "

    def test_load_rejects_mismatched_step_text(self, tmp_path: Path) -> None:
        """A same-key file whose sentence normalizes elsewhere is a miss — and stays sweepable."""
        cache, _ = make_cache(tmp_path, path=None)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="Open the page")
        write_step_file(tmp_path / identity.filename, "Open  the PAGE", "k")

        assert cache.load(identity) is None  # a different sentence never replays

        removed = cache.sweep_untouched("k")

        assert removed == [identity.filename]  # the miss touched nothing

    def test_touch_marks_only_successful_load_and_save(self, tmp_path: Path) -> None:
        """Misses, sentence mismatches and skipped writes touch nothing; successes do."""
        cache, _ = make_cache(tmp_path, path=None)
        missing = StepIdentity(cache_key="k", step_type="action", normalized_text="missing address")
        mismatched = StepIdentity(cache_key="k", step_type="action", normalized_text="the address I claim")
        loadable = StepIdentity(cache_key="k", step_type="action", normalized_text="a loadable step")
        savable = StepIdentity(cache_key="k", step_type="action", normalized_text="a saved step")

        assert cache.load(missing) is None  # (a) a missing address touches nothing
        write_step_file(tmp_path / mismatched.filename, "an entirely different sentence", "k")
        assert cache.load(mismatched) is None  # (b) parseable and key-matching, sentence mismatch

        step = CachedStep(identity=savable, addressing_text="a saved step", code=STEP_CODE, created_at="2026-10-11")
        cache._writable = False  # (c) the skipped write touches nothing
        assert cache.save(step) is False
        cache._writable = None  # reset the lazily probed flag

        write_step_file(tmp_path / loadable.filename, "a loadable step", "k")
        assert cache.load(loadable) is not None  # (d) a good load touches
        assert cache.save(step) is True  # (e) a good save touches

        removed = cache.sweep_untouched("k")

        assert removed == [mismatched.filename]  # only (b) is gone
        assert (tmp_path / loadable.filename).exists()
        assert (tmp_path / savable.filename).exists()

    def test_strict_replay_self_preserving_committed_cache(self, tmp_path: Path) -> None:
        """A replayed entry is loaded, hence touched — the committed strict run keeps it."""
        cache, _ = make_cache(tmp_path, path=None)
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="open the login page")
        write_step_file(tmp_path / identity.filename, "open the login page", "login-flow")

        loaded = cache.load(identity)

        assert loaded is not None

        removed = cache.sweep_untouched("login-flow")

        assert removed == []
        assert (tmp_path / identity.filename).exists()

    def test_sweep_skips_unreadable_metadata_with_warning(self, tmp_path: Path, caplog) -> None:
        """Ownership of an unparseable file is unprovable — skip loudly, never delete."""
        cache, _ = make_cache(tmp_path, path=None)
        digest_name = StepIdentity(cache_key="k", step_type="action", normalized_text="broken").filename
        target = tmp_path / digest_name
        target.write_text("not python !!!", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            removed = cache.sweep_untouched("k")

        assert target.exists()
        assert removed == []

        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]

        assert len(warnings) == 1
        assert warnings[0].msg == "cache sweep skipped a file with unreadable metadata"
        assert warnings[0].ctx_filename == digest_name  # type: ignore[attr-defined]

    def test_sweep_swallows_per_file_delete_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        """A poisoned file must not fail the closing test — the deletion failure is a WARNING."""

        def raise_os_error(self: Path) -> None:
            raise OSError("locked")

        cache, _ = make_cache(tmp_path, path=None)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="locked file")
        write_step_file(tmp_path / identity.filename, "locked file", "k")

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            monkeypatch.setattr(pathlib.Path, "unlink", raise_os_error)
            removed = cache.sweep_untouched("k")

        assert removed == []
        assert (tmp_path / identity.filename).exists()

        warnings = [
            record
            for record in caplog.records
            if record.levelno == logging.WARNING and record.msg == "cache sweep failed on a file"
        ]

        assert len(warnings) == 1

    def test_sweep_is_idempotent_and_repeat_close_safe(self, tmp_path: Path) -> None:
        """A repeated sweep re-enumerates and deletes nothing new — repeat closes are safe."""
        cache, _ = make_cache(tmp_path, path=None)
        untouched = StepIdentity(cache_key="k", step_type="action", normalized_text="an untouched leftover")
        touched = StepIdentity(cache_key="k", step_type="action", normalized_text="a replayed step")
        write_step_file(tmp_path / untouched.filename, "an untouched leftover", "k")
        write_step_file(tmp_path / touched.filename, "a replayed step", "k")

        assert cache.load(touched) is not None

        removed1 = cache.sweep_untouched("k")
        removed2 = cache.sweep_untouched("k")

        assert removed1 == [untouched.filename]
        assert removed2 == []
        assert (tmp_path / touched.filename).exists()

    def test_sweep_ignores_non_digest_and_foreign_files(self, tmp_path: Path, caplog) -> None:
        """Foreign artifacts and other tests' entries are invisible to the sweep."""
        cache, _ = make_cache(tmp_path, path=None)
        foreign = StepIdentity(cache_key="other", step_type="action", normalized_text="a foreign step")
        write_step_file(tmp_path / "notes.py", "notes", "k")
        (tmp_path / ".tmp-abc.py").write_text("garbage", encoding="utf-8")
        write_step_file(tmp_path / foreign.filename, "a foreign step", "other")

        with caplog.at_level(logging.WARNING, logger="prettyplay"):
            removed = cache.sweep_untouched("k")

        assert removed == []
        assert [record for record in caplog.records if record.levelno == logging.WARNING] == []
        assert (tmp_path / "notes.py").exists()
        assert (tmp_path / ".tmp-abc.py").exists()
        assert (tmp_path / foreign.filename).exists()

    def test_sweep_of_missing_scope_returns_empty(self, tmp_path: Path) -> None:
        """A fresh test that never wrote has no scope directory — the sweep is a no-op."""
        cache = StepCache(Config(cache_root=str(tmp_path / "never-created")), None, StepReporter(hooks=[]))

        assert cache.sweep_untouched("k") == []
