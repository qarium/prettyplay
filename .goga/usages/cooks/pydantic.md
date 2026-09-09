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


class PrettyplayConfig(BaseModel):
    model_config = ConfigDict(kw_only=True)

    browser: str = "chromium"           # chromium | firefox | webkit | chrome | msedge
    headless: bool = True               # headless mode (env PRETTYPLAY_BROWSER_HEADLESS)
    model: str = ""
    generation_model: str = ""           # optional override, falls back to model
    classification_model: str = ""       # optional override, falls back to model
    base_url: str = ""
    cache_root: str = ""                 # empty -> <repo root>/.prettyplay/cache/ (ADR-5)
    generation_attempts: int = 3         # ADR-8
    healing_attempts: int = 2            # ADR-8
    send_screenshots: bool = False       # ADR-7
```

Configuration rules:

- Secrets (LLM API keys) are never stored in the config file; the config may reference an environment variable **name** (ADR-13)
- Every setting has an environment override for CI; the browser override is `PRETTYPLAY_BROWSER_NAME` — the legacy `PRETTYPLAY_BROWSER` no longer applies and, when met, is answered with a hint naming the new variable
- Invalid configuration fails loudly with an actionable message (see below)

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
