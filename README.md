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

## What happens on a step

- **cache hit** — the cached code runs; no LLM is contacted
- **cache miss** — the step code is generated (a candidate that must actually
  work on the page), then cached; only successes are cached
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
browser = "chromium"             # chromium | firefox | webkit
model = "gpt-5"
generation_model = ""            # optional: empty -> model
classification_model = ""        # optional: empty -> model
base_url = ""
cache_root = ""                  # empty -> <repo>/.prettyplay/cache/
generation_attempts = 3
healing_attempts = 2
send_screenshots = false
```

Every setting has a `PRETTYPLAY_<SETTING_UPPER>` environment override for CI.

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

A healed run never turns a `ProductDefectError` into a green test.

## Hooks

```python
from prettyplay.reporting import StepHooks


class Reporter(StepHooks):
    def on_step_started(self, step_text: str, step_type: str) -> None: ...
    def on_step_passed(self, step_text: str, step_type: str) -> None: ...
    def on_step_failed(self, step_text: str, step_type: str, error: str) -> None: ...
    def on_generation_started(self, step_text: str, attempt: int) -> None: ...
    def on_healing_started(self, step_text: str, category: str) -> None: ...
    def on_healed(self, step_text: str, explanation: str) -> None: ...
    def on_cache_saved(self, step_text: str, filename: str) -> None: ...
    def on_cache_skipped(self, step_text: str, reason: str) -> None: ...


t = PrettyTest("login-flow")
t.add_hooks(Reporter())
```

A raising hook never fails the run; the failure is logged.

## Cache and CI workflow

The cache lives under `.prettyplay/cache/` as plain Python files — one per
step, carrying its metadata (step sentence, cache key, step type, creation
date) and the step code.

Generate locally where the LLM is reachable → commit the cache directory →
CI runs the whole suite from the cache with no LLM keys at all.

## Limitations

Step sentences land in the repository cache, the logs and the LLM requests:
never put secrets or personal data into a step.
