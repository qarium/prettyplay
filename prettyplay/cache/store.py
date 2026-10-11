"""Repository store of cached steps: deterministic addressing, atomic best-effort writes."""

import ast
import contextlib
import logging
import os
import re
import tempfile
import time
from pathlib import Path

from ..config import Config
from ..reporting import StepReporter
from .models import CachedStep, StepIdentity
from .text import normalize_step_text

logger = logging.getLogger("prettyplay")

#: Header constants of a cache file: metadata first, then the step code.
_HEADER_FIELDS = ("STEP_TEXT", "CACHE_KEY", "STEP_TYPE", "CREATED_AT")

#: Line marking the start of the step code tail; the surrounding newlines keep
#: the match out of the header (repr escapes newlines, so a raw newline inside
#: the header literals is impossible) and out of the loaded code.
_CODE_SENTINEL = "\n# --- step code ---\n"

#: Legacy marker of the step code tail: files written before the sentinel carry
#: the code starting at ``def step(`` (the old prompt forbade top-level imports).
_STEP_MARKER = "\ndef step("

#: Replace attempts and backoff for a busy target (Windows keeps the file open).
_REPLACE_ATTEMPTS = 3
_REPLACE_BACKOFF_SECONDS = 0.1

#: Digest-named step files — the sha256 of an address triple (64 lowercase hex
#: characters) with the ``.py`` extension; only these belong to the sweep.
_STEP_FILE_NAME = re.compile(r"^[0-9a-f]{64}\.py$")


class StepCache:
    """The repository store of cache steps: addressing, atomic writes and the read-only mode.

    Attributes:
        _root: the cache root from the settings (absolute after ``load_config``).
        _subdir: the optional subdirectory; part of the address, so steps of
            different subdirectories never collide.
        _reporter: the visibility point for the cache events.
        _writable: the lazily probed writability flag; ``None`` until first use.
        _touched: the per-test working set — file names of the steps this store
            successfully loaded or saved; memory only, never persisted.
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
        self._touched: set[str] = set()

    @property
    def root(self) -> str:
        """Return the effective cache root."""
        return str(self._root)

    @property
    def writable(self) -> bool:
        """Return whether the cache directory accepts writes.

        Returns:
            Whether writes are accepted — probed lazily once: the target
            directory is created, ``os.access`` checked; any ``OSError``
            counts as read-only.
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

            sentinel = text.find(_CODE_SENTINEL)
            if sentinel != -1:
                code = text[sentinel + len(_CODE_SENTINEL) :]
            else:
                marker = text.find(_STEP_MARKER)  # a file written before the sentinel
                if marker == -1:
                    raise KeyError("def step(")
                code = text[marker + 1 :]

            if fields["CACHE_KEY"] != identity.cache_key or fields["STEP_TYPE"] != identity.step_type:
                return None
            if not isinstance(fields["STEP_TEXT"], str):
                return None
            if normalize_step_text(fields["STEP_TEXT"]) != identity.normalized_text:
                return None

            step = CachedStep(
                identity=identity,
                addressing_text=fields["STEP_TEXT"],
                code=code,
                created_at=fields["CREATED_AT"],
            )
            self._touched.add(identity.filename)

            return step
        except (ValueError, SyntaxError, KeyError, IndexError, OSError):
            return None  # cache corruption never cripples the run

    def save(self, step: CachedStep) -> bool:
        """Store the step atomically, best-effort: no write error ever fails the run.

        Args:
            step: the working step to store.

        Returns:
            Whether the step was stored: ``True`` — the atomic replace
            landed; ``False`` — the write was skipped (a read-only cache or
            a busy target; the ``on_cache_skipped`` event carries the
            reason).
        """
        if not self.writable:
            self._emit_skipped(step, "read-only cache")
            return False

        body = _serialize(step)
        try:
            handle, tmp_name = tempfile.mkstemp(dir=self._target_dir(), prefix=".tmp-", suffix=".py")
        except OSError:
            self._emit_skipped(step, "cache target busy")
            return False

        try:
            with os.fdopen(handle, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(body)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
        except (OSError, ValueError):  # ValueError: unencodable text (e.g. surrogates)
            _remove_quietly(tmp_name)
            self._emit_skipped(step, "cache target busy")
            return False

        for _ in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp_name, self._target_dir() / step.identity.filename)
                break
            except PermissionError:
                time.sleep(_REPLACE_BACKOFF_SECONDS)  # Windows: target busy
            except (OSError, ValueError):  # ValueError: unencodable address (e.g. surrogates)
                _remove_quietly(tmp_name)
                self._emit_skipped(step, "cache target busy")
                return False
        else:
            _remove_quietly(tmp_name)
            self._emit_skipped(step, "cache target busy")
            return False

        self._reporter.emit(
            "on_cache_saved",
            {"step_text": step.identity.normalized_text, "filename": step.identity.filename},
        )
        self._touched.add(step.identity.filename)
        return True

    def sweep_untouched(self, cache_key: str) -> list[str]:
        """Delete the untouched step files of one cache key in this store's scope.

        Args:
            cache_key: the key of the test whose untouched entries are swept.

        Returns:
            The names of the deleted files. Never raises: unreadable metadata,
            foreign cache keys and per-file failures are skipped (the last with
            a WARNING); touched files survive, so a repeated call deletes
            nothing new.
        """
        removed: list[str] = []

        scope = self._target_dir()
        if not scope.is_dir():
            return removed

        try:
            candidates = sorted(entry for entry in scope.iterdir() if _STEP_FILE_NAME.fullmatch(entry.name))
        except OSError:
            logger.warning("cache sweep failed to list the scope", extra={"cache_key": cache_key})
            return removed

        # ``filename`` is a reserved LogRecord attribute — the direct records below use the
        # ``ctx_filename`` key, the established record-attribute pattern of the reporter.
        for candidate in candidates:
            try:
                fields = _parse_header(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError, SyntaxError, KeyError, IndexError):
                logger.warning(
                    "cache sweep skipped a file with unreadable metadata", extra={"ctx_filename": candidate.name}
                )
                continue

            if fields["CACHE_KEY"] != cache_key:
                continue
            if candidate.name in self._touched:
                continue

            try:
                candidate.unlink()
            except OSError:
                logger.warning("cache sweep failed on a file", extra={"ctx_filename": candidate.name})
                continue

            removed.append(candidate.name)
            logger.info("cache file swept", extra={"ctx_filename": candidate.name, "cache_key": cache_key})

        return removed

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
    """Serialize a step into the module text: metadata literals, the sentinel line, the code.

    Args:
        step: the step to serialize.

    Returns:
        The text of a valid Python module carrying the step: the sentinel
        line marks where the code tail starts, so ``load`` restores the code
        verbatim — top-level imports included.
    """
    header = "".join(
        f"{name} = {value!r}\n"
        for name, value in (
            ("STEP_TEXT", step.addressing_text),
            ("CACHE_KEY", step.identity.cache_key),
            ("STEP_TYPE", step.identity.step_type),
            ("CREATED_AT", step.created_at),
        )
    )
    return header + _CODE_SENTINEL + step.code + "\n"


def _remove_quietly(path: str) -> None:
    """Remove a temporary file, ignoring a failure: the write is already skipped."""
    with contextlib.suppress(OSError):
        Path(path).unlink()
