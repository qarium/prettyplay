"""Repository store of cached steps: deterministic addressing, atomic best-effort writes."""

import ast
import contextlib
import os
import tempfile
import time
from pathlib import Path

from ..config import Config
from ..reporting import StepReporter
from .models import CachedStep, StepIdentity

#: Header constants of a cache file: metadata first, then the step code.
_HEADER_FIELDS = ("STEP_TEXT", "CACHE_KEY", "STEP_TYPE", "CREATED_AT")

#: Marker of the step code tail; the leading newline stays out of the loaded code.
_STEP_MARKER = "\ndef step("

#: Replace attempts and backoff for a busy target (Windows keeps the file open).
_REPLACE_ATTEMPTS = 3
_REPLACE_BACKOFF_SECONDS = 0.1


class StepCache:
    """The repository store of cache steps: addressing, atomic writes and the read-only mode.

    The cache is always read: any structural error of a cache file is a
    protective miss (``None``), never a failed run — the step is simply
    regenerated. Writes are best-effort: a read-only cache or a busy target
    skips the write loudly through the reporter and the run continues.

    Attributes:
        _root: the cache root from the settings (absolute after ``load_config``).
        _subdir: the optional subdirectory; part of the address, so steps of
            different subdirectories never collide.
        _reporter: the visibility point for the cache events.
        _writable: the lazily probed writability flag; ``None`` until first use.
    """

    def __init__(
        self,
        config: Config,
        path: str | None = None,
        reporter: StepReporter | None = None,
    ) -> None:
        """Keep the settings, the optional subdirectory and the reporter.

        Args:
            config: project settings; the ``cache_root`` setting is the cache root.
            path: the optional subdirectory inside the cache; ``None`` — shared root.
            reporter: the visibility point — cache events go through it; a
                missing reporter falls back to the hook-less default reporter,
                so construction and saves never crash on it.

        Raises:
            ValueError: ``path`` is absolute or escapes the cache root.
        """
        self._root = Path(config.cache_root)
        self._subdir = self._validated_subdir(path)
        self._reporter = reporter if reporter is not None else StepReporter(hooks=[])
        self._writable: bool | None = None

    @property
    def root(self) -> str:
        """Return the effective cache root."""
        return str(self._root)

    @property
    def writable(self) -> bool:
        """Return whether the cache directory accepts writes.

        Probed lazily once: the target directory is created (parents included)
        and checked with ``os.access``; any ``OSError`` counts as read-only.
        """
        if self._writable is None:
            try:
                target_dir = self._target_dir()
                target_dir.mkdir(parents=True, exist_ok=True)
                self._writable = os.access(target_dir, os.W_OK)
            except OSError:
                self._writable = False

        return self._writable

    def load(self, identity: StepIdentity) -> CachedStep | None:
        """Load the cached step by address; any structural damage is a miss, not a failure.

        Args:
            identity: the address of the step.

        Returns:
            The cached step, or ``None`` when the file is missing, damaged, or
            its metadata does not match the address.
        """
        target = self._target_dir() / identity.filename
        if not target.exists():
            return None

        try:
            text = target.read_text(encoding="utf-8")
            fields = _parse_header(text)

            marker = text.find(_STEP_MARKER)
            if marker == -1:
                raise KeyError("def step(")
            code = text[marker + 1 :]

            if fields["CACHE_KEY"] != identity.cache_key or fields["STEP_TYPE"] != identity.step_type:
                return None
            if fields["STEP_TEXT"] != identity.normalized_text:
                return None

            return CachedStep(identity=identity, code=code, created_at=fields["CREATED_AT"])
        except (ValueError, SyntaxError, KeyError, IndexError, OSError):
            return None  # повреждение кэша никогда не калечит прогон

    def save(self, step: CachedStep) -> None:
        """Store the step atomically, best-effort: no write error ever fails the run.

        Args:
            step: the working step to store.
        """
        if not self.writable:
            self._emit_skipped(step, "read-only cache")
            return

        body = _serialize(step)
        try:
            handle, tmp_name = tempfile.mkstemp(dir=self._target_dir(), prefix=".tmp-", suffix=".py")
        except OSError:
            self._emit_skipped(step, "cache target busy")
            return

        try:
            with os.fdopen(handle, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(body)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
        except (OSError, ValueError):  # ValueError: непрокодируемый текст (напр. суррогаты)
            _remove_quietly(tmp_name)
            self._emit_skipped(step, "cache target busy")
            return

        for _ in range(_REPLACE_ATTEMPTS):
            try:
                Path(tmp_name).replace(self._target_dir() / step.identity.filename)
                break
            except PermissionError:
                time.sleep(_REPLACE_BACKOFF_SECONDS)  # Windows: цель занята
            except (OSError, ValueError):  # ValueError: непрокодируемый адрес (напр. суррогаты)
                _remove_quietly(tmp_name)
                self._emit_skipped(step, "cache target busy")
                return
        else:
            _remove_quietly(tmp_name)
            self._emit_skipped(step, "cache target busy")
            return

        self._reporter.emit(
            "on_cache_saved",
            {"step_text": step.identity.normalized_text, "filename": step.identity.filename},
        )

    def _target_dir(self) -> Path:
        """Return the directory holding the steps of this address."""
        return self._root / self._subdir if self._subdir else self._root

    @staticmethod
    def _validated_subdir(path: str | None) -> Path | None:
        """Return the subdirectory path, rejecting addresses outside the cache root.

        Args:
            path: the integrator-supplied subdirectory; ``None`` — shared root.

        Returns:
            The validated relative subdirectory, or ``None`` for the shared root.

        Raises:
            ValueError: the path is absolute or resolves outside the cache root.
        """
        if path is None or path == "":
            return None

        subdir = Path(path)

        if subdir.is_absolute():
            raise ValueError(f"cache path must be a subdirectory, got absolute {path!r}")
        if ".." in subdir.parts:
            raise ValueError(f"cache path must stay inside the cache root, got {path!r}")

        return subdir

    def _emit_skipped(self, step: CachedStep, reason: str) -> None:
        """Report a skipped write through the visibility point."""
        self._reporter.emit(
            "on_cache_skipped",
            {"step_text": step.identity.normalized_text, "reason": reason},
        )


def _parse_header(text: str) -> dict[str, str]:
    """Parse the header constants of a cache file into a field map.

    Args:
        text: the whole cache file text.

    Returns:
        The map of the header constants found in the module.

    Raises:
        SyntaxError: the file is not a parseable Python module.
        ValueError: a header value is not a literal.
        KeyError: any of the header constants is missing.
    """
    module = ast.parse(text)

    fields: dict[str, str] = {}
    for node in module.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue

        target = node.targets[0]

        if isinstance(target, ast.Name) and target.id in _HEADER_FIELDS:
            fields[target.id] = ast.literal_eval(node.value)

    missing = [name for name in _HEADER_FIELDS if name not in fields]

    if missing:
        raise KeyError(", ".join(missing))

    return fields


def _serialize(step: CachedStep) -> str:
    """Serialize a step into the module text: metadata literals first, then the code.

    Args:
        step: the step to serialize.

    Returns:
        The text of a valid Python module carrying the step.
    """
    header = "".join(
        f"{name} = {value!r}\n"
        for name, value in (
            ("STEP_TEXT", step.identity.normalized_text),
            ("CACHE_KEY", step.identity.cache_key),
            ("STEP_TYPE", step.identity.step_type),
            ("CREATED_AT", step.created_at),
        )
    )
    return header + "\n" + step.code + "\n"


def _remove_quietly(path: str) -> None:
    """Remove a temporary file, ignoring a failure: the write is already skipped."""
    with contextlib.suppress(OSError):
        Path(path).unlink()
