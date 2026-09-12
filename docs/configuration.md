# Configuration

PrettyPlay settings. For integrators configuring a test project and CI.

The immutable part of the settings lives in the `[tool.prettyplay]` section of
pyproject.toml. Load it once per test; a test can additionally override
specific values programmatically through `PrettyConfig`.

```toml
[tool.prettyplay]
provider = "openai"              # openai | anthropic
model = "gpt-5"
generation_model = ""            # optional: empty -> model
classification_model = ""        # optional: empty -> model
base_url = ""
cache_root = ""                  # empty -> <repo>/.prettyplay/cache/
generation_prompt = ""           # user instructions for generation; empty -> no instructions block
classification_prompt = ""       # user instructions for classification; empty -> no instructions block
strict = false                   # true -> replay-only mode (no generation, no healing)
generation_attempts = 3
healing_attempts = 2
send_screenshots = false

[tool.prettyplay.browser]
name = "chromium"                # chromium | firefox | webkit | chrome | msedge
screen = ""                      # "" | WxH | fullscreen | Playwright device name
headless = true                  # false -> run with a visible browser window
endpoint = ""                    # ws:// endpoint of a remote browser; empty -> local launch
accept_dialogs = false           # true -> automatically accept dialogs outside step-captured dialogs
```

The browser group settings — engines, screen modes, remote endpoints — are
covered in detail in [Browser setup](guides/browser-setup.md).

## Environment overrides

Every setting has an override for CI — env variable `PRETTYPLAY_<SETTING>` in
upper case; the browser group keeps flat env names:

| Setting | Env override |
|---|---|
| provider | `PRETTYPLAY_PROVIDER` |
| browser.name | `PRETTYPLAY_BROWSER_NAME` |
| browser.screen | `PRETTYPLAY_BROWSER_SCREEN` |
| browser.headless | `PRETTYPLAY_BROWSER_HEADLESS` |
| browser.endpoint | `PRETTYPLAY_BROWSER_ENDPOINT` |
| browser.accept_dialogs | `PRETTYPLAY_BROWSER_ACCEPT_DIALOGS` |
| model | `PRETTYPLAY_MODEL` |
| generation_model | `PRETTYPLAY_GENERATION_MODEL` |
| classification_model | `PRETTYPLAY_CLASSIFICATION_MODEL` |
| base_url | `PRETTYPLAY_BASE_URL` |
| cache_root | `PRETTYPLAY_CACHE_ROOT` |
| generation_attempts | `PRETTYPLAY_GENERATION_ATTEMPTS` |
| healing_attempts | `PRETTYPLAY_HEALING_ATTEMPTS` |
| send_screenshots | `PRETTYPLAY_SEND_SCREENSHOTS` |
| strict | `PRETTYPLAY_STRICT` |
| generation_prompt | `PRETTYPLAY_GENERATION_PROMPT` |
| classification_prompt | `PRETTYPLAY_CLASSIFICATION_PROMPT` |

Env values parse by the field type: booleans accept `true/false/1/0`
case-insensitively, integers parse as decimals, and an unparseable value fails
loudly with a `ConfigurationError` naming the setting, the received value and
the accepted form.

## Old flat keys are gone — hard break

`browser`, `headless` and `browser_endpoint` at the `[tool.prettyplay]` level
no longer exist (pre-1.0 break). A config carrying them fails loudly at load:
the error names each old key and its new home — `browser` →
`[tool.prettyplay.browser] name`, `headless` → `[tool.prettyplay.browser]
headless`, `browser_endpoint` → `[tool.prettyplay.browser] endpoint`. The
removed legacy env name `PRETTYPLAY_BROWSER` fails the same way with a hint to
use `PRETTYPLAY_BROWSER_NAME`. Migrate before upgrading.

## Per-test overrides — layered merge

`PrettyConfig` is the public name of the full settings model. A config passed
to the test object carries only the explicitly set values; everything else
resolves from pyproject+env:

```python
from prettyplay import BrowserConfig, PrettyConfig, PrettyPlay

test = PrettyPlay(
    cache_key="login-flow",
    config=PrettyConfig(
        strict=True,
        browser=BrowserConfig(screen="fullscreen", headless=False),
    ),
)
```

- An explicitly set field wins over pyproject+env; a field left at its default
  falls back to the file layer
- The merge reaches inside the nested group: explicitly set fields of a passed
  `BrowserConfig` win over the file layer; untouched group defaults never
  overwrite file values — set only `screen` and the file's `name`,
  `headless`, `endpoint`, `accept_dialogs` keep working
- `strict` participates when passed explicitly — an explicit `False` overrides
  the file value too
- File values you did not touch survive: `base_url` and `model` set only in
  pyproject.toml keep working when a config is passed
- One model — one place of validation: file and programmatic values validate
  identically

## The PrettyConfig API

`PrettyConfig` is the public name of the validated settings model (`Config`
internally, `prettyplay.config.Config`); re-exported from the package root
together with the nested browser group:

```python
from prettyplay import BrowserConfig, PrettyConfig
```

Both models are pydantic v2 with keyword-only construction; every field
carries an empty or neutral default — an empty string means unset for string
fields, which is what makes the layered merge above possible.

### PrettyConfig

| Field | Type | Default | Meaning |
|---|---|---|---|
| `provider` | str | `"openai"` | LLM provider: `openai` or `anthropic` |
| `browser` | BrowserConfig | neutral group | the nested browser settings group |
| `model` | str | `""` | the main LLM model name |
| `generation_model` | str | `""` | generation-only override; empty → `model` |
| `classification_model` | str | `""` | classification-only override; empty → `model` |
| `base_url` | str | `""` | custom LLM API endpoint |
| `cache_root` | str | `""` | empty → `<repo root>/.prettyplay/cache/` resolved at load |
| `generation_prompt` | str | `""` | user instructions for generation requests; empty → no block |
| `classification_prompt` | str | `""` | user instructions for classification requests; empty → no block |
| `strict` | bool | `False` | replay-only mode: no generation, no healing |
| `generation_attempts` | int | `3` | generation attempt budget per step per test |
| `healing_attempts` | int | `2` | healing attempt budget per step per test |
| `send_screenshots` | bool | `False` | attach screenshots to LLM requests |

Read-only effective-model properties resolve the per-operation fallback:

```python
config.effective_generation_model      # generation_model when non-empty, otherwise model
config.effective_classification_model  # classification_model when non-empty, otherwise model
```

### BrowserConfig

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | str | `"chromium"` | `chromium`, `firefox`, `webkit`, `chrome`, `msedge` |
| `screen` | str | `""` | `""` — Playwright default; WxH — fixed viewport; `fullscreen`; Playwright device name |
| `headless` | bool | `True` | windowless local launch; ignored on a remote connect |
| `endpoint` | str | `""` | ws endpoint of a remote browser; empty — local launch |
| `accept_dialogs` | bool | `False` | automatically accept dialogs no step-captured `expect_dialog` block claims |

Fields inside the group carry no `browser_` prefix — the group name scopes
them; env overrides stay flat (`PRETTYPLAY_BROWSER_NAME`, ...). Validation:
`name` against the five-value set, a non-empty `endpoint` as a ws/wss URL,
positive integers for the attempts, `screen` at format level only (a WxH-shaped
value must carry positive integers; everything else — including `fullscreen`
and device names — passes through unresolved, because the device registry
belongs to the running Playwright).

### load_config

```python
from prettyplay.config import load_config

config = load_config(pyproject_path=None, overrides=None)
```

- `pyproject_path` — optional explicit path to pyproject.toml; `None` — the
  first pyproject.toml found upwards from the current directory
- `overrides` — programmatically passed values, the same full model; `None` —
  no programmatic layer, the file layer resolves everything
- returns the fully resolved and validated `Config`

Resolution order: TOML file → environment overrides (`PRETTYPLAY_*`) →
explicitly set fields of `overrides` (the merge reaches inside the browser
group — see
[Per-test overrides](#per-test-overrides-layered-merge)).

### Examples

```python
from prettyplay import BrowserConfig, PrettyConfig, PrettyPlay

# no programmatic layer — everything resolves from pyproject+env
t1 = PrettyPlay("smoke")

# per-test: strict replay with a visible fullscreen window
t2 = PrettyPlay(
    "login-flow",
    config=PrettyConfig(
        strict=True,
        browser=BrowserConfig(screen="fullscreen", headless=False),
    ),
)

# override one field of the browser group — file values for the rest keep working
t3 = PrettyPlay("login-flow", config=PrettyConfig(browser=BrowserConfig(name="firefox")))

# dedicated models per operation, one main fallback
cfg = PrettyConfig(
    model="claude-sonnet-4-5",
    generation_model="claude-opus-4-7",               # generation requests only
    classification_model="claude-haiku-4-5-20251001",  # classification requests only
)
```

Inspecting the effective config of a project:

```python
from prettyplay.config import load_config

config = load_config()  # locates pyproject.toml upwards from the current directory
print(config.browser.name, config.browser.screen, config.strict)
print(config.effective_generation_model, config.effective_classification_model)
```

### ConfigurationError

An invalid configuration never surfaces as a raw pydantic error: the loader
wraps it into `ConfigurationError` (`from prettyplay.config import
ConfigurationError` — derives from `PrettyplayError`, so the single library
except clause catches it; a configuration failure is not a step failure and
never carries a verdict). The message is actionable — one line per invalid
setting: the setting name, the received value and the allowed values; the
original pydantic `ValidationError` stays chained for debugging.

## Instructions

A non-empty `generation_prompt` is sent verbatim as a `USER INSTRUCTIONS`
block with every generation and regeneration request — it steers the style of
the generated code, never the failure classification.

A non-empty `classification_prompt` works the same way for classification
requests only — it steers the verdict explanations (e.g. `answer in Russian`),
never generation.

Neither ever invalidates cached steps — a cached step runs unchanged.

## Dialogs

`accept_dialogs` of the browser group controls the automatic dialog handling
of the driver:

- `true` — every dialog that no step-captured `expect_dialog` block claims
  is accepted automatically
- `false` (default) — unclaimed dialogs are dismissed (the Playwright
  default; nothing blocks)
- A dialog captured by a step's `expect_dialog` block is accepted or
  dismissed by the step itself — the setting does not apply to captured
  dialogs

## Strict mode

`strict = true` (env `PRETTYPLAY_STRICT`, per-test override) switches the run
to replay-only: cached code executes honestly and nothing is ever
(re)generated. A cache miss fails as an incurable step; a failed cached step
is at most classified — never regenerated. Classification is the only LLM call
strict mode makes; without LLM access the failure raises immediately by step
type — see [Failure taxonomy](reference/failure-taxonomy.md) and
[Getting started](getting-started.md#strict-mode-replay-only-ci-runs).

## Rules

- LLM API keys are never stored in the config file — secrets come only from
  environment variables: `OPENAI_API_KEY` for openai, `ANTHROPIC_API_KEY` for
  anthropic
- Invalid configuration fails loudly: `ConfigurationError` names the setting,
  the received value and the allowed values; the raw pydantic error stays
  chained for debugging
- The provider set: `openai`, `anthropic`; the browser name set: `chromium`,
  `firefox`, `webkit`, `chrome`, `msedge`
- A non-empty `browser.endpoint` must be a valid ws/wss URL
- The cache root default: `<repo root>/.prettyplay/cache/` — resolved from the
  located pyproject.toml
