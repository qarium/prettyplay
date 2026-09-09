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

## Quick start

```python
from prettyplay import PrettyTest


def test_login():
    t = PrettyTest("login-flow")
    t.action("открыть страницу логина")
    t.action("ввести логин и пароль")
    t.action("нажать «Войти»")
    t.assertion("появилась надпись «Добро пожаловать»")
    t.close()
```

Or with the context manager:

```python
with PrettyTest("login-flow") as t:
    t.action("открыть страницу логина")
```

The constructor arguments form the cache address: `cache_key` (mandatory) and
`cache_path` (optional subdirectory). Equal keys in the shared root reuse one
cached step across tests; a different language, step type or key is a
different step.

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
browser = "chromium"             # chromium | firefox | webkit | chrome | msedge
model = "gpt-5"
generation_model = ""            # optional: empty -> model
classification_model = ""        # optional: empty -> model
base_url = ""
cache_root = ""                  # empty -> <repo>/.prettyplay/cache/
generation_attempts = 3
healing_attempts = 2
send_screenshots = false
headless = true                  # false -> run with a visible browser window
```

`chrome` and `msedge` launch the locally installed browser through the
chromium engine; the browser must be installed on the machine.

Every setting has a `PRETTYPLAY_<SETTING_UPPER>` environment override for CI,
except the browser (`PRETTYPLAY_BROWSER_NAME`) and headless
(`PRETTYPLAY_BROWSER_HEADLESS`). The removed legacy name `PRETTYPLAY_BROWSER`
fails immediately with a hint to use `PRETTYPLAY_BROWSER_NAME`.

An invalid setting fails loudly with a `ConfigurationError`: one line per
setting — the name, the received value and the allowed values.

LLM API keys are never stored in the config file: they come only from the
environment — `OPENAI_API_KEY` for openai, `ANTHROPIC_API_KEY` for anthropic —
and are read lazily on the first request.

## Failure taxonomy

Every library failure derives from `PrettyplayError`:

| Exception | Meaning | Recommended reaction |
|---|---|---|
| ProductDefectError | real product regression | treat as a bug: this failure is the value of the suite |
| IncurableStepError | the step cannot be (re)generated | follow `recommendation`: reword the step or refresh the cache |
| LlmUnavailableError | LLM infrastructure down | restore provider access; cached steps are unaffected |
| ConfigurationError | invalid `[tool.prettyplay]` settings | fix the named setting — the message lists received and allowed values |

`ProductDefectError` and `IncurableStepError` carry a verdict — `category`,
`explanation`, `recommendation` from the failure classification — appended to
the exception message and delivered through the `on_step_verdict` hook.
`ProductDefectError` also derives from `AssertionError`, so any runner counts
it as a failed test, never an error. Tracebacks of library failures are folded
at the `t.action(...)` / `t.assertion(...)` call site: internal engine frames
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


t = PrettyTest("login-flow")
t.add_hooks(Reporter())
```

A raising hook never fails the run; the failure is logged. `on_step_verdict`
fires after `on_step_failed`, only when the terminal failure carried a verdict.

## Cache and CI workflow

The cache lives under `.prettyplay/cache/` as plain Python files — one per
step, carrying its metadata (step sentence, cache key, step type, creation
date) and the step code.

Generate locally where the LLM is reachable → commit the cache directory →
CI runs the whole suite from the cache with no LLM keys at all.

## Limitations

Step sentences land in the repository cache, the logs and the LLM requests:
never put secrets or personal data into a step.
