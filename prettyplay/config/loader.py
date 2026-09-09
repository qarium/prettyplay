"""Loading of the ``[tool.prettyplay]`` section of pyproject.toml with env overrides.

The pyproject.toml path is either given explicitly or auto-searched upward from
the current working directory. Environment overrides win over the file
whenever the variable is set — including when it is set to an empty string:
``PRETTYPLAY_<SETTING_UPPER>`` for every setting except the browser
(``PRETTYPLAY_BROWSER_NAME``) and headless (``PRETTYPLAY_BROWSER_HEADLESS``).
The removed legacy name ``PRETTYPLAY_BROWSER`` fails loudly before merging.
LLM API keys are never read here: they come only from the provider clients
themselves.
"""

import os
import sys
from pathlib import Path

from pydantic import ValidationError

from ..failures.errors import PrettyplayError
from .models import Config

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

#: The removed legacy env name; set — the load fails loudly before merging.
_LEGACY_BROWSER_ENV = "PRETTYPLAY_BROWSER"

#: Env variable name of every overridable setting; the two browser entries
#: keep their historical special names.
_ENV_NAMES: dict[str, str] = {
    field: f"PRETTYPLAY_{field.upper()}"
    for field in (
        "provider",
        "model",
        "generation_model",
        "classification_model",
        "base_url",
        "cache_root",
        "generation_attempts",
        "healing_attempts",
        "send_screenshots",
    )
}
_ENV_NAMES["browser"] = "PRETTYPLAY_BROWSER_NAME"
_ENV_NAMES["headless"] = "PRETTYPLAY_BROWSER_HEADLESS"

#: The allowed-values text of the settings the validation render names.
_ALLOWED_TEXT: dict[str, str] = {
    "provider": "openai, anthropic",
    "browser": "chromium, firefox, webkit, chrome, msedge",
    "generation_attempts": "a positive integer",
    "healing_attempts": "a positive integer",
    "headless": "a boolean",
    "send_screenshots": "a boolean",
    "model": "a non-empty string",
    "generation_model": "a non-empty string",
    "classification_model": "a non-empty string",
    "base_url": "a non-empty string",
    "cache_root": "a non-empty string",
}


class ConfigurationError(PrettyplayError):
    """An invalid prettyplay configuration: the loaded settings failed validation.

    Raised by :func:`load_config` with the original pydantic
    ``ValidationError`` chained; catchable with the single library except
    clause. Never carries a verdict — a configuration failure is not a step
    failure.

    Args:
        message: the rendered actionable text — one line per invalid setting.
    """


def _find_pyproject() -> Path:
    """Return the first existing pyproject.toml upward from the cwd.

    Returns:
        Absolute path of the found pyproject.toml.

    Raises:
        FileNotFoundError: when no pyproject.toml exists upward from the cwd.
    """
    for directory in (Path.cwd(), *Path.cwd().parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate

    raise FileNotFoundError("pyproject.toml not found upward from the current directory")


def _collect_env_overrides() -> dict[str, str]:
    """Collect the set environment overrides of all supported settings."""
    overrides: dict[str, str] = {}

    for field, env_name in _ENV_NAMES.items():
        value = os.environ.get(env_name)
        if value is not None:
            overrides[field] = value

    return overrides


def _render_validation(error: ValidationError) -> str:
    """Render the pydantic error as actionable per-setting lines.

    Args:
        error: the pydantic validation failure of the merged settings.

    Returns:
        One line per invalid setting — the setting name, the received value
        and the allowed values or range — joined with newlines; no pydantic
        internals in the user-visible text.
    """
    lines: list[str] = []

    for entry in error.errors():
        field = entry["loc"][0]
        received = entry.get("input")
        allowed = _ALLOWED_TEXT.get(str(field), entry["msg"])
        lines.append(f"{field}: received {received!r} — allowed: {allowed}")

    return "\n".join(lines)


def load_config(pyproject_path: str | None) -> Config:
    """Load validated settings from ``[tool.prettyplay]`` with env overrides.

    The section is optional: a missing ``[tool.prettyplay]`` yields defaults.
    Environment variables override the file value whenever they are set, empty
    string included: ``PRETTYPLAY_BROWSER_NAME`` for the browser,
    ``PRETTYPLAY_BROWSER_HEADLESS`` for headless and
    ``PRETTYPLAY_<SETTING_UPPER>`` for every other setting. An empty
    ``cache_root`` resolves to ``<pyproject_dir>/.prettyplay/cache``.

    Args:
        pyproject_path: explicit pyproject.toml path; ``None`` auto-searches
            upward from the current working directory.

    Returns:
        Validated configuration.

    Raises:
        FileNotFoundError: when ``pyproject_path`` is ``None`` and no
            pyproject.toml is found upward from the cwd.
        tomllib.TOMLDecodeError: when the file is not valid TOML.
        ConfigurationError: when merged settings fail validation — the
            original ``ValidationError`` chained as the cause.
    """
    path = Path(pyproject_path) if pyproject_path is not None else _find_pyproject()

    with path.open("rb") as stream:
        data = tomllib.load(stream)
    section = data.get("tool", {}).get("prettyplay", {})

    if _LEGACY_BROWSER_ENV in os.environ:
        raise ConfigurationError(f"{_LEGACY_BROWSER_ENV} is no longer supported: use PRETTYPLAY_BROWSER_NAME")

    merged = {**section, **_collect_env_overrides()}

    if not merged.get("cache_root"):
        merged["cache_root"] = str(path.parent / ".prettyplay" / "cache")

    try:
        return Config(**merged)
    except ValidationError as error:
        raise ConfigurationError(_render_validation(error)) from error
