"""Tests for the StepCache repository store of the prettyplay.cache cell."""

import importlib.util
import inspect
import logging
import os
from pathlib import Path
from unittest import mock

import pytest
from prettyplay.cache import CachedStep, StepCache, StepIdentity
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


STEP_CODE = "def step(page) -> None:\n    page.open('https://x')\n"


class TestStepCacheLogic:
    """Logic tests: roundtrip via the file, protective load, loud skips."""

    def test_save_load_roundtrip_via_file(self, tmp_path: Path, caplog) -> None:
        cache, recorder = make_cache(tmp_path)
        identity = StepIdentity(cache_key="login-flow", step_type="action", normalized_text="открыть страницу логина")

        with caplog.at_level(logging.INFO, logger="prettyplay"):
            cache.save(CachedStep(identity=identity, code=STEP_CODE, created_at="2026-09-07"))
        loaded = cache.load(identity)

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

            cache.save(CachedStep(identity=identity, code=STEP_CODE, created_at="2026-09-07"))

            assert not (root / "checkout").exists()  # no file created
            skipped_events = [call for call in recorder.calls if call[0] == "on_cache_skipped"]
            assert skipped_events == [("on_cache_skipped", {"step_text": "шаг", "reason": "read-only cache"})]
        finally:
            root.chmod(0o700)  # restore so tmp_path cleanup works

    def test_load_missing_file_returns_none(self, tmp_path: Path) -> None:
        cache, _ = make_cache(tmp_path)

        result = cache.load(StepIdentity(cache_key="k", step_type="action", normalized_text="нет такого шага"))

        assert result is None

    def test_load_metadata_mismatch_treated_as_miss(self, tmp_path: Path) -> None:
        cache, _ = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="оригинальный шаг")

        cache.save(CachedStep(identity=identity, code=STEP_CODE, created_at="2026-09-07"))
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

        cache.save(CachedStep(identity=identity, code=STEP_CODE, created_at="2026-09-07"))
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

        cache.save(CachedStep(identity=identity, code=STEP_CODE, created_at="2026-09-07"))
        cache.save(CachedStep(identity=identity, code=STEP_CODE, created_at="2026-09-08"))  # overwrite

        files = sorted(entry.name for entry in (tmp_path / "checkout").iterdir())
        assert files == [identity.filename]  # last writer wins, temp removed

    def test_busy_target_retries_then_skips_loudly(self, tmp_path: Path) -> None:
        """Additional edge: PermissionError on replace → skip with cache target busy, run lives."""
        cache, recorder = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="занятая цель")

        with mock.patch("prettyplay.cache.store.os.replace", side_effect=PermissionError("busy")):
            cache.save(CachedStep(identity=identity, code=STEP_CODE, created_at="2026-09-07"))

        skipped_events = [call for call in recorder.calls if call[0] == "on_cache_skipped"]
        assert skipped_events == [("on_cache_skipped", {"step_text": "занятая цель", "reason": "cache target busy"})]
        assert cache.load(identity) is None  # the partial file never became visible

    def test_replace_oserror_skips_loudly(self, tmp_path: Path) -> None:
        """Additional edge: any OSError on replace (not only PermissionError) skips, never fails."""
        cache, recorder = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="пропавшая цель")

        with mock.patch("prettyplay.cache.store.os.replace", side_effect=FileNotFoundError("dir gone")):
            cache.save(CachedStep(identity=identity, code=STEP_CODE, created_at="2026-09-07"))

        skipped_events = [call for call in recorder.calls if call[0] == "on_cache_skipped"]
        assert skipped_events == [("on_cache_skipped", {"step_text": "пропавшая цель", "reason": "cache target busy"})]

    def test_mkstemp_failure_skips_loudly(self, tmp_path: Path) -> None:
        """Additional edge: the temp file cannot be created → skip, the run continues."""
        cache, recorder = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="нет temp")

        with mock.patch("prettyplay.cache.store.tempfile.mkstemp", side_effect=OSError("no space")):
            cache.save(CachedStep(identity=identity, code=STEP_CODE, created_at="2026-09-07"))

        skipped_events = [call for call in recorder.calls if call[0] == "on_cache_skipped"]
        assert skipped_events == [("on_cache_skipped", {"step_text": "нет temp", "reason": "cache target busy"})]

    def test_write_failure_cleans_temp_and_skips(self, tmp_path: Path) -> None:
        """Additional edge: the temp write fails → temp removed, skip emitted, no partial file."""
        cache, recorder = make_cache(tmp_path)
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="сбой записи")

        with mock.patch("prettyplay.cache.store.os.fsync", side_effect=OSError("io error")):
            cache.save(CachedStep(identity=identity, code=STEP_CODE, created_at="2026-09-07"))

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

        cache.save(CachedStep(identity=identity, code=STEP_CODE, created_at="2026-09-07"))

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

        cache.save(CachedStep(identity=identity, code=STEP_CODE, created_at="2026-09-07"))
        file_path = tmp_path / "checkout" / identity.filename
        text = file_path.read_text(encoding="utf-8")
        file_path.write_text(text.replace("CACHE_KEY = 'k'", "CACHE_KEY = 'другой'"), encoding="utf-8")

        assert cache.load(identity) is None

    def test_default_reporter_construction_saves_and_skips_loudly(self, tmp_path: Path) -> None:
        """Additional edge: no reporter passed — construction and save still work (no crash)."""
        cache = StepCache(Config(cache_root=str(tmp_path)), "checkout")
        identity = StepIdentity(cache_key="k", step_type="action", normalized_text="шаг без репортёра")

        cache.save(CachedStep(identity=identity, code=STEP_CODE, created_at="2026-09-07"))
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
