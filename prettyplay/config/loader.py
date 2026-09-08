"""Loading of the ``[tool.prettyplay]`` section of pyproject.toml with env overrides.

The pyproject.toml path is either given explicitly or auto-searched upward from
the current working directory. Environment overrides
(``PRETTYPLAY_<SETTING_UPPER>``) win over the file whenever the variable is set
— including when it is set to an empty string. LLM API keys are never read
here: they come only from the provider clients themselves.
"""

import os
import sys
from pathlib import Path

from .models import Config

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

#: Setting names eligible for ``PRETTYPLAY_<NAME_UPPER>`` environment overrides.
_ENV_OVERRIDABLE_FIELDS = (
    "provider",
    "browser",
    "model",
    "generation_model",
    "classification_model",
    "base_url",
    "cache_root",
    "generation_attempts",
    "healing_attempts",
    "send_screenshots",
)


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
    for field in _ENV_OVERRIDABLE_FIELDS:
        value = os.environ.get(f"PRETTYPLAY_{field.upper()}")
        if value is not None:
            overrides[field] = value
    return overrides


def load_config(pyproject_path: str | None) -> Config:
    """Load validated settings from ``[tool.prettyplay]`` with env overrides.

    The section is optional: a missing ``[tool.prettyplay]`` yields defaults.
    Environment variables ``PRETTYPLAY_<SETTING_UPPER>`` override the file value
    whenever the variable is set, empty string included. An empty ``cache_root``
    resolves to ``<pyproject_dir>/.prettyplay/cache``.

    Args:
        pyproject_path: explicit pyproject.toml path; ``None`` auto-searches
            upward from the current working directory.

    Returns:
        Validated configuration.

    Raises:
        FileNotFoundError: when ``pyproject_path`` is ``None`` and no
            pyproject.toml is found upward from the cwd.
        tomllib.TOMLDecodeError: when the file is not valid TOML.
        pydantic.ValidationError: when merged settings fail validation.
    """
    path = Path(pyproject_path) if pyproject_path is not None else _find_pyproject()

    with path.open("rb") as stream:
        data = tomllib.load(stream)
    section = data.get("tool", {}).get("prettyplay", {})

    merged = {**section, **_collect_env_overrides()}

    if not merged.get("cache_root"):
        merged["cache_root"] = str(path.parent / ".prettyplay" / "cache")

    return Config(**merged)
