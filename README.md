# prettyplay

UI tests written as plain sentences. Each step sentence is turned into executable
code once — by an LLM, against the live page — and cached in the repository.
Every later run replays the cached code with no LLM involvement at all.

## Installation

```bash
pip install prettyplay
playwright install            # browser binaries for the driver
```

Requires Python 3.10+.

Full documentation: <https://qarium.github.io/prettyplay/>

A complete pytest project — Allure reporting hooks included — lives in the
`example/` directory of the repository; it additionally requires
`allure-pytest` (`pip install allure-pytest`), which the core package does
not depend on.

## Quick start

```python
from prettyplay import PrettyPlay


def test_login():
    t = PrettyPlay("login-flow")
    t.step("open the login page")
    t.step("enter the login and password")
    t.step("click the Sign in button")
    t.expect("the Welcome message appears")
    t.close()
```

Or with the context manager:

```python
with PrettyPlay("login-flow") as t:
    t.step("open the login page")
```

Each `PrettyPlay` is fully self-contained: it owns its settings, its attempt
budgets and its own browser session. `close()` (or leaving the `with` block)
closes the page and stops the whole browser of that test, and every test
starts with fresh attempt budgets. The old process-wide
`prettyplay.get_runtime()` singleton was removed — build
`prettyplay.PrettyplayRuntime(config)` directly if you composed objects over
it.

The constructor arguments form the cache address: `cache_key` (mandatory) and
`cache_path` (optional subdirectory). Equal keys in the shared root reuse one
cached step across tests; a different language, step type or key is a
different step.

The third argument overrides settings per test — only the fields you pass
count: explicitly set values win over pyproject.toml and the environment,
everything else resolves from the file layer as before. Browser settings form
the nested `BrowserConfig` group; an empty string inside the group means unset,
untouched group defaults never overwrite the file values:

```python
from prettyplay import BrowserConfig, PrettyConfig

t = PrettyPlay("login-flow", config=PrettyConfig(browser=BrowserConfig(name="firefox")))
```

Screenshots belong to the author — nothing is captured automatically. Both
methods need a step to have run (the page opens lazily):

```python
png = t.get_screenshot()                  # full-page PNG bytes
t.save_screenshot("artifacts/home.png")   # write full-page PNG to a file
```

## What happens on a step

- **cache hit** — the cached code runs; no LLM is contacted
- **cache miss** — the step code is generated (a candidate that must actually
  work on the page), then cached; only successes are cached. A candidate
  assertion that legitimately fails stops the retries at once and is
  classified: a real defect fails as `product_defect` instead of burning the
  attempt budget
- **cached failure** — the failure is classified:
  - `rot` (the UI changed) — the step is regenerated and the cache rewritten
  - `product_defect` — the test fails loudly; nothing is regenerated
  - `incurable` — the step fails with an explanation and a recommendation

**Strict replay-only mode** (`strict = true`) never contacts the LLM for code:
a cache miss fails immediately as `IncurableStepError` ("strict mode forbids
generation — the step is missing from the cache"), and a failed cached step is
at most classified — the only LLM call strict mode ever makes — then raised by
its category (`product_defect` → `ProductDefectError`, everything else — rot
included — → `IncurableStepError`). Nothing is regenerated or healed, no
attempt budget is consumed and the cache is never written. When the LLM is
unavailable, the verdict is skipped with a `WARNING` and the step type alone
picks the error kind. This is the natural CI posture: generate locally, run
strict in the pipeline.

## Seeing the scenario

Step sentences go to the `prettyplay` logger at info level. The library
configures no handlers — enable logging to see the scenario in the output:

```python
import logging

logging.basicConfig(level=logging.INFO)          # plain unittest runs
```

```ini
# pytest: --log-cli-level=INFO
```

## Configuration

The `[tool.prettyplay]` section of pyproject.toml:

```toml
[tool.prettyplay]
provider = "openai"              # openai | anthropic
model = "gpt-5"
generation_model = ""            # optional: empty -> model
classification_model = ""        # optional: empty -> model
base_url = ""
cache_root = ""                  # empty -> <cwd>/.prettyplay/cache/
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
accept_dialogs = false           # true -> automatically accept dialogs outside step-captured expect_dialog blocks
```

The old flat keys `browser`, `headless` and `browser_endpoint` at the
`[tool.prettyplay]` level are gone — a pre-1.0 hard break: the loader rejects
them with a `ConfigurationError` naming their new home inside
`[tool.prettyplay.browser]`, and the removed legacy env name `PRETTYPLAY_BROWSER`
fails the same way with a hint to use `PRETTYPLAY_BROWSER_NAME`.

`chrome` and `msedge` launch the locally installed browser through the
chromium engine; the browser must be installed on the machine.

### Screen modes

The `screen` setting of the browser group decides the context size:

- `""` — the Playwright default.
- `1280x720` (WxH) — a fixed viewport, in every launch mode.
- `fullscreen` — follows the maximized window on a local headed launch (the
  chromium family launches with `--start-maximized`; firefox/webkit keep their
  plain launch) and pins a fixed 1920x1080 viewport where no window exists —
  headless and remote connects.
- anything else — a Playwright device name (`iPhone 13`, `Pixel 7`, ...):
  the full device descriptor is applied. An unknown name fails loudly with the
  closest registry names suggested.

### Instructions

A non-empty `generation_prompt` is sent verbatim as a `USER INSTRUCTIONS`
block with every generation and regeneration request — it steers the style of
the generated code (e.g. `prefer data-test-id attributes`), never the failure
classification. The instructions are not part of the cache address: changing
them never invalidates cached steps — a cached step runs unchanged.

A non-empty `classification_prompt` works the same way for classification
requests only — it steers the verdict explanations (e.g. `answer in Russian`),
never generation, and never invalidates cached steps either.

### Remote browsers

A non-empty `endpoint` (e.g. `ws://ci-grid:3000/playwright/chromium`) connects
to a remote Playwright Server or browser grid instead of launching locally:
`headless` does not apply to a connect (window visibility belongs to the
endpoint server) and `chrome`/`msedge` map to the chromium engine — channels
are a local-launch concept. A non-empty endpoint must be a valid ws/wss URL
(otherwise `ConfigurationError` names the setting), and a failed connect fails
loudly with the endpoint in the message.

### Environment overrides

Every setting has a `PRETTYPLAY_<SETTING_UPPER>` environment override for CI —
including `PRETTYPLAY_STRICT` and `PRETTYPLAY_CLASSIFICATION_PROMPT` — and the
browser group reads the flat `PRETTYPLAY_BROWSER_NAME`,
`PRETTYPLAY_BROWSER_SCREEN`, `PRETTYPLAY_BROWSER_HEADLESS`,
`PRETTYPLAY_BROWSER_ENDPOINT` and `PRETTYPLAY_BROWSER_ACCEPT_DIALOGS`. Env
values parse by the field type: booleans
accept `true/false/1/0` case-insensitively, integers parse as decimals, and an
unparseable value fails loudly with a `ConfigurationError` naming the setting,
the received value and the accepted form.

An invalid setting fails loudly with a `ConfigurationError`: one line per
setting — the name, the received value and the allowed values.

LLM API keys are never stored in the config file: they come only from the
environment — `OPENAI_API_KEY` for openai, `ANTHROPIC_API_KEY` for anthropic —
and are read lazily on the first request.

### Dialogs

`accept_dialogs` of the browser group controls the automatic dialog handling
of the driver:

- `true` — every dialog that no step-captured `expect_dialog` block claims is
  accepted automatically
- `false` (default) — unclaimed dialogs are dismissed (the Playwright
  default; nothing blocks)
- a dialog captured by a step's `expect_dialog` block is accepted or dismissed
  by the step itself — the setting does not apply to captured dialogs

## Failure taxonomy

Every library failure derives from `PrettyplayError`:

| Exception | Meaning | Recommended reaction |
|---|---|---|
| ProductDefectError | real product regression | treat as a bug: this failure is the value of the suite |
| IncurableStepError | the step cannot be (re)generated — budget exhausted, step text stale, or a strict-mode cache miss | follow `recommendation`: reword the step or refresh the cache |
| LLMUnavailableError | LLM infrastructure down | restore provider access; cached steps are unaffected |
| ConfigurationError | invalid `[tool.prettyplay]` settings | fix the named setting — the message lists received and allowed values |

`ProductDefectError` and `IncurableStepError` render one structured terminal
message — the reason line, a `---` separated `step:`/`error:` block (the
`error:` line carries the full underlying error text), and a `---` separated
verdict block with column-aligned `explanation:` and `recommendation:` lines
(the `category` travels in the structured fields, never in the render). The
same single text feeds the exception message, the log record and the
`on_step_failed` hook payload — consumers never re-compose it. The verdict
fields also arrive through the `on_step_verdict` hook.
`ProductDefectError` also derives from `AssertionError`, so any runner counts
it as a failed test, never an error. Tracebacks of library failures are folded
at the `t.step(...)` / `t.expect(...)` call site: internal engine frames
never appear in what the runner shows.

A healed run never turns a `ProductDefectError` into a green test.

## Hooks

```python
from prettyplay.reporting import StepHooks


class Reporter(StepHooks):
    def on_step_started(self, step_text: str, step_type: str) -> None: ...
    def on_step_passed(self, step_text: str, step_type: str) -> None: ...
    def on_step_failed(self, step_text: str, step_type: str, error: str) -> None: ...
    def on_step_verdict(self, step_text: str, category: str, explanation: str, recommendation: str) -> None: ...
    def on_generation_started(self, step_text: str, attempt: int) -> None: ...
    def on_healing_started(self, step_text: str, category: str) -> None: ...
    def on_healed(self, step_text: str, explanation: str) -> None: ...
    def on_cache_saved(self, step_text: str, filename: str) -> None: ...
    def on_cache_skipped(self, step_text: str, reason: str) -> None: ...


t = PrettyPlay("login-flow")
t.add_hooks(Reporter())
```

Hooks can also be wired at construction — pass the list to the keyword-only
`hooks` parameter (`PrettyPlay("login-flow", hooks=[Reporter()])`) and every
event of every step reaches them. `StepHooks` is re-exported from the package
root, so `from prettyplay import StepHooks` works too.

A raising hook never fails the run; the failure is logged. The `error` payload
of `on_step_failed` is the full structured render of the failure — multi-line,
verbatim. `on_step_verdict` fires after `on_step_failed`, only when the
terminal failure carried a real verdict (never for the render-only fallback
recommendation of a verdict-less `IncurableStepError`).

## Cache and CI workflow

The cache lives under `.prettyplay/cache/` as plain Python files — one per
step, carrying its metadata (step sentence, cache key, step type, creation
date) and the step code.

Generate locally where the LLM is reachable → commit the cache directory →
CI runs the whole suite from the cache with no LLM keys at all — `strict = true`
turns that posture into a guarantee: a cache miss fails the run instead of
silently generating.

## Limitations

Step sentences land in the repository cache, the logs and the LLM requests:
never put secrets or personal data into a step.
