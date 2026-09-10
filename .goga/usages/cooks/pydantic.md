# Pydantic — Data Models and Project Configuration

Practices for `pydantic` within prettyplay, plus the TOML loading fallback for Python 3.10. Target audience: implementing agents defining data models and the configuration schema.

Project conventions (`.goga/usages/conventions.md`) require pydantic for all data models.

## Models — kw_only construction

Every model uses keyword-only construction:

```python
from pydantic import BaseModel, ConfigDict


class StepResult(BaseModel):
    model_config = ConfigDict(kw_only=True)

    step_text: str = ""
    passed: bool = False
```

Rules: `model_config = ConfigDict(kw_only=True)` on every model; empty defaults for regular fields; `None` only for the explicit absence of a value.

## Configuration schema — [tool.prettyplay]

The immutable part of project settings lives in `pyproject.toml` (ADR-13). A pydantic model validates the section (field names below are illustrative of the ADR-13 setting list, not a final contract):

```python
from pydantic import BaseModel, ConfigDict


class BrowserConfig(BaseModel):
    model_config = ConfigDict(kw_only=True)

    name: str = "chromium"       # chromium | firefox | webkit | chrome | msedge
    screen: str = ""             # "" | WxH | fullscreen | Playwright device name
    headless: bool = True        # env PRETTYPLAY_BROWSER_HEADLESS
    endpoint: str = ""           # remote ws endpoint; empty -> local launch


class PrettyplayConfig(BaseModel):
    model_config = ConfigDict(kw_only=True)

    browser: BrowserConfig = BrowserConfig()   # nested [tool.prettyplay.browser] group
    model: str = ""
    strict: bool = False                        # replay-only mode (env PRETTYPLAY_STRICT)
    classification_prompt: str = ""             # classification user instructions (env PRETTYPLAY_CLASSIFICATION_PROMPT)
    # ... the remaining settings unchanged
```

Configuration rules:

- Nested group: `[tool.prettyplay.browser]` maps onto `BrowserConfig`; fields inside the group carry no `browser_` prefix — the group name already scopes them
- Env overrides stay flat: `PRETTYPLAY_BROWSER_{NAME|SCREEN|HEADLESS|ENDPOINT}`; the other settings keep `PRETTYPLAY_<SETTING_UPPERCASE>`
- Old flat keys (`browser`, `headless`, `browser_endpoint` at the `[tool.prettyplay]` level) are a hard break: a loud `ConfigurationError` points at the new location
- Layered merge extends to the nested model: explicitly set fields of a passed `BrowserConfig` win over the file layer
- Secrets (LLM API keys) are never stored in the config file; the config may reference an environment variable **name** (ADR-13)
- Invalid configuration fails loudly with an actionable message (see below)

## Layered merge — explicit values over pyproject+env

A PrettyConfig passed to the test object is the same full model, not a subset: explicitly set values win, empty/unset fields fall back to the pyproject+env layer:

```python
file_config = load_config()                     # pyproject.toml + env overrides, validated
explicit = user_overrides.model_fields_set      # fields passed at construction
effective = file_config.model_copy(update={
    key: value
    for key, value in user_overrides            # a field participates when passed at
    if key in explicit                          # construction and non-empty for strings:
    and (value or not isinstance(value, str))   # an explicit False/0 overrides too
})
```

Rules:
- One model — one validation: file and programmatic values validate identically
- A new setting becomes available across the whole chain pyproject → env → PrettyConfig automatically

## Validation failures — actionable library error

A raw `pydantic.ValidationError` never reaches the user: the loader catches it and re-raises a loud library error built from the pydantic details — the setting name, the received value and the allowed values. The original error stays chained for debugging:

```python
try:
    config = PrettyplayConfig(**section)
except ValidationError as error:
    raise wrap_validation_error(error) from error
```

Wrapper message rules: one line per invalid setting — the setting name, the received value, the allowed list or range; no pydantic internals in the user-visible text.

## TOML loading — tomllib with tomli fallback

Python 3.11+ ships `tomllib`; Python 3.10 does not. The conditional dependency `tomli>=2.0; python_version < "3.11"` is declared in `pyproject.toml`:

```python
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


with pyproject_path.open("rb") as stream:
    data = tomllib.load(stream)

section = data.get("tool", {}).get("prettyplay", {})
config = PrettyplayConfig(**section)
```
