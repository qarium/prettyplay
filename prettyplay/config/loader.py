"""Loading of the ``[tool.prettyplay]`` section of pyproject.toml with layered overrides.

The pyproject.toml path is either given explicitly or auto-searched upward from
the current working directory. Environment overrides win over the file
whenever the variable is set — including when it is set to an empty string:
``PRETTYPLAY_<SETTING_UPPER>`` for every scalar setting (including
``PRETTYPLAY_STRICT`` and ``PRETTYPLAY_CLASSIFICATION_PROMPT``) and the flat
group names ``PRETTYPLAY_BROWSER_{NAME|SCREEN|HEADLESS|ENDPOINT|ACCEPT_DIALOGS}``
for the nested browser group. Scalar env values parse by the field type — booleans
accept true/false/1/0 case-insensitively, integers parse as decimal, floats
(``polling_timeout``/``polling_delay``) as decimal floats — and an
unparseable value fails loudly naming the setting, the received value and the
accepted form. The removed legacy name ``PRETTYPLAY_BROWSER`` and the removed
flat keys ``browser``/``headless``/``browser_endpoint`` of the
``[tool.prettyplay]`` level fail loudly before merging. Explicitly set
programmatic values (``PrettyConfig`` fields passed at construction, not
None, non-empty for strings) win over the pyproject+env layer — the merge
reaches inside the browser group. LLM API keys are never read here: they come
only from the provider clients themselves.
"""

import os
import sys
from pathlib import Path

from pydantic import ValidationError

from ..failures import PrettyplayError
from .models import BrowserConfig, Config

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

#: The removed legacy env name; set — the load fails loudly before merging.
_LEGACY_BROWSER_ENV = "PRETTYPLAY_BROWSER"

#: Env variable name of every overridable setting; dotted names address the
#: browser group, whose flat PRETTYPLAY_BROWSER_* names stay historical.
_ENV_NAMES: dict[str, str] = {
    setting: f"PRETTYPLAY_{setting.upper().replace('.', '_')}"
    for setting in (
        "provider",
        "model",
        "generation_model",
        "classification_model",
        "base_url",
        "cache_root",
        "generation_prompt",
        "classification_prompt",
        "strict",
        "polling_timeout",
        "polling_delay",
        "interactive",
        "generation_attempts",
        "healing_attempts",
        "send_screenshots",
        "browser.name",
        "browser.screen",
        "browser.headless",
        "browser.endpoint",
        "browser.accept_dialogs",
    )
}

#: The settings whose env values parse as booleans.
_BOOL_ENV_SETTINGS = frozenset(
    {"strict", "interactive", "send_screenshots", "browser.headless", "browser.accept_dialogs"}
)

#: The settings whose env values parse as decimal integers.
_INT_ENV_SETTINGS = frozenset({"generation_attempts", "healing_attempts"})

#: The settings whose env values parse as decimal floats.
_FLOAT_ENV_SETTINGS = frozenset({"polling_timeout", "polling_delay"})

#: The removed flat keys of the [tool.prettyplay] level and their new group homes.
_FLAT_KEY_HOMES: dict[str, str] = {
    "browser": "name",
    "headless": "headless",
    "browser_endpoint": "endpoint",
}

#: The allowed-values text of the settings the validation render names.
_ALLOWED_TEXT: dict[str, str] = {
    "provider": "openai, anthropic",
    "browser.name": "chromium, firefox, webkit, chrome, msedge",
    "generation_attempts": "a positive integer",
    "healing_attempts": "a positive integer",
    "browser.headless": "a boolean",
    "browser.accept_dialogs": "a boolean",
    "strict": "a boolean",
    "polling_timeout": "None or a non-negative number (finite)",
    "polling_delay": "a non-negative number",
    "interactive": "a boolean",
    "send_screenshots": "a boolean",
    "model": "a non-empty string",
    "generation_model": "a non-empty string",
    "classification_model": "a non-empty string",
    "base_url": "a non-empty string",
    "cache_root": "a non-empty string",
    "generation_prompt": "a non-empty string",
    "classification_prompt": "a non-empty string",
    "browser.endpoint": "a valid ws/wss URL",
    "browser.screen": "an empty value, WxH (must be positive integers), fullscreen or a Playwright device name",
}


class ConfigurationError(PrettyplayError):
    """An invalid prettyplay configuration: the loaded settings failed validation.

    Raised by :func:`load_config` with the original pydantic
    ``ValidationError`` chained; catchable with the single library except
    clause. Never carries a verdict — a configuration failure is not a step
    failure.

    Args:
        message: the rendered actionable text — one line per invalid setting
            or per removed old flat key.
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


def _parse_env_scalar(setting: str, raw: str) -> object:
    """Parse one environment override by the field type of the setting.

    Args:
        setting: the dotted setting name the variable overrides.
        raw: the raw environment value.

    Returns:
        The parsed value: a bool, a decimal int, a float or the verbatim string.

    Raises:
        ConfigurationError: when the value does not parse — the message names
            the setting, the received value and the accepted form.
    """
    if setting in _BOOL_ENV_SETTINGS:
        lowered = raw.lower()

        if lowered in ("true", "1"):
            return True
        if lowered in ("false", "0"):
            return False

        raise ConfigurationError(f"{setting}: received {raw!r} — allowed: a boolean (true/false/1/0)")

    if setting in _INT_ENV_SETTINGS:
        try:
            return int(raw)
        except ValueError:
            raise ConfigurationError(f"{setting}: received {raw!r} — allowed: a decimal integer") from None

    if setting in _FLOAT_ENV_SETTINGS:
        try:
            return float(raw)
        except ValueError:
            raise ConfigurationError(f"{setting}: received {raw!r} — allowed: a decimal float") from None

    return raw


def _collect_env_overrides() -> dict[str, object]:
    """Collect and parse the set environment overrides of all supported settings.

    Raises:
        ConfigurationError: when a set variable does not parse by its field type.
    """
    overrides: dict[str, object] = {}

    for setting, env_name in _ENV_NAMES.items():
        raw = os.environ.get(env_name)
        if raw is not None:
            overrides[setting] = _parse_env_scalar(setting, raw)

    return overrides


def _render_validation(error: ValidationError) -> str:
    """Render the pydantic error as actionable per-setting lines.

    Args:
        error: the pydantic validation failure of the merged settings.

    Returns:
        One line per invalid setting — the dotted setting name, the received
        value and the allowed values or range — joined with newlines; no
        pydantic internals in the user-visible text.
    """
    lines: list[str] = []

    for entry in error.errors():
        field = ".".join(str(part) for part in entry["loc"])
        received = entry.get("input")

        if entry.get("type") == "extra_forbidden":
            lines.append(f"{field}: received {received!r} — not a prettyplay setting")
            continue

        allowed = _ALLOWED_TEXT.get(field, entry["msg"])
        lines.append(f"{field}: received {received!r} — allowed: {allowed}")

    return "\n".join(lines)


def _reject_flat_keys(section: dict) -> None:
    """Raise when the section carries removed old flat keys.

    Args:
        section: the raw ``[tool.prettyplay]`` mapping of the file.

    Raises:
        ConfigurationError: one line per present old flat key — the key name
            and its new home inside the ``[tool.prettyplay.browser]`` group.
            A ``browser`` key holding a table is the group itself, not a flat
            key.
    """
    flat_old = [
        key
        for key in _FLAT_KEY_HOMES
        if key in section and not (key == "browser" and isinstance(section[key], dict))
    ]

    if flat_old:
        lines = [
            f"{key}: removed — its new home is [tool.prettyplay.browser] {_FLAT_KEY_HOMES[key]}" for key in flat_old
        ]
        raise ConfigurationError("\n".join(lines))


def _apply_overrides(file_config: Config, overrides: Config) -> Config:
    """Overlay the explicitly set fields of ``overrides`` onto the file layer.

    Args:
        file_config: the validated pyproject+env layer.
        overrides: the programmatic layer; a field participates when it was
            passed at construction, is not None and is non-empty for strings —
            explicitly set values win, untouched model defaults, None and empty
            strings never overwrite the file layer.

    Returns:
        The effective configuration: ``file_config`` with the participating
        overrides applied; the merge reaches inside the browser group —
        explicitly set fields of a passed :class:`BrowserConfig` win over the
        file group, untouched group defaults never overwrite it.
    """
    update: dict[str, object] = {}

    for name, value in overrides:
        if name not in overrides.model_fields_set:
            continue
        if value is None:  # None means unset (e.g. polling_timeout) — indistinguishable from untouched
            continue
        if isinstance(value, str) and not value:
            continue
        if isinstance(value, BrowserConfig):
            group_update = {
                group_name: group_value
                for group_name, group_value in value
                if group_name in value.model_fields_set and (group_value or not isinstance(group_value, str))
            }
            if group_update:
                update["browser"] = file_config.browser.model_copy(update=group_update)
            # no explicitly set group fields — the file group survives untouched
        else:
            update[name] = value

    return file_config.model_copy(update=update)


def load_config(pyproject_path: str | None = None, overrides: Config | None = None) -> Config:
    """Load validated settings layered pyproject → env → explicit programmatic values.

    The section is optional: a missing ``[tool.prettyplay]`` yields defaults.
    Environment variables override the file value whenever they are set, empty
    string included: the browser group reads the flat
    ``PRETTYPLAY_BROWSER_{NAME|SCREEN|HEADLESS|ENDPOINT|ACCEPT_DIALOGS}``
    names, ``strict`` reads ``PRETTYPLAY_STRICT``, ``classification_prompt`` reads
    ``PRETTYPLAY_CLASSIFICATION_PROMPT`` and every other setting reads
    ``PRETTYPLAY_<SETTING_UPPER>``. Scalar env values parse by the field type
    and an unparseable value fails loudly. The removed legacy name
    ``PRETTYPLAY_BROWSER`` and the removed flat keys of the
    ``[tool.prettyplay]`` level fail loudly before merging. An empty
    ``cache_root`` resolves to ``<cwd>/.prettyplay/cache`` — the working
    directory of the run, wherever the pyproject.toml was found.

    The programmatic layer wins last: a field of ``overrides`` participates
    when it was passed at construction (``model_fields_set``), is not None and
    is non-empty for strings — explicitly set values win, untouched model
    defaults, None and empty strings never overwrite the pyproject+env values.
    The merge reaches inside the browser group: explicitly set fields of a
    passed :class:`~prettyplay.config.models.BrowserConfig` win over the file
    group, untouched group defaults never overwrite it.

    Args:
        pyproject_path: explicit pyproject.toml path; ``None`` auto-searches
            upward from the current working directory.
        overrides: the programmatic layer, typically a ``PrettyConfig`` built
            by the integrator; ``None`` (or an instance with no explicitly set
            fields) returns the validated file layer as is.

    Returns:
        Validated configuration.

    Raises:
        FileNotFoundError: when ``pyproject_path`` is ``None`` and no
            pyproject.toml is found upward from the cwd.
        tomllib.TOMLDecodeError: when the file is not valid TOML.
        ConfigurationError: when merged settings fail validation or carry a
            removed legacy name — the original ``ValidationError`` chained as
            the cause when there is one.
    """
    path = Path(pyproject_path) if pyproject_path is not None else _find_pyproject()

    with path.open("rb") as stream:
        data = tomllib.load(stream)
    section = data.get("tool", {}).get("prettyplay", {})

    if _LEGACY_BROWSER_ENV in os.environ:
        raise ConfigurationError(f"{_LEGACY_BROWSER_ENV} is no longer supported: use PRETTYPLAY_BROWSER_NAME")

    _reject_flat_keys(section)

    env = _collect_env_overrides()

    merged = {**section, **{setting: value for setting, value in env.items() if "." not in setting}}
    group_env = {setting.split(".", 1)[1]: value for setting, value in env.items() if "." in setting}

    if group_env:
        merged["browser"] = {**(merged.get("browser") or {}), **group_env}

    browser_section = merged.get("browser")

    if isinstance(browser_section, dict) and browser_section.get("name") == "":
        # empty means unset only in the programmatic overlay; from the file or
        # env layer an empty name is an invalid value, not an omission
        raise ConfigurationError(f"browser.name: received '' — allowed: {_ALLOWED_TEXT['browser.name']}")

    if not merged.get("cache_root"):
        merged["cache_root"] = str(Path.cwd() / ".prettyplay" / "cache")

    try:
        file_config = Config(**merged)
    except ValidationError as error:
        raise ConfigurationError(_render_validation(error)) from error

    if overrides is None:
        return file_config

    return _apply_overrides(file_config, overrides)
