# PrettyPlay

UI tests written as plain sentences. Each step sentence is turned into executable
code once — by an LLM, against the live page — and cached in the repository.
Every later run replays the cached code with no LLM involvement at all.

## Install

```bash
pip install prettyplay
playwright install            # browser binaries for the driver
```

Requires Python 3.10+.

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
closes the page and stops the whole browser of that test.

## What happens on a step

- **cache hit** — the cached code runs; no LLM is contacted
- **cache miss** — the step code is generated (a candidate that must actually
  work on the page), then cached; only successes are cached
- **cached failure** — the failure is classified:
    - `rot` (the UI changed) — the step is regenerated and the cache rewritten
    - `product_defect` — the test fails loudly; nothing is regenerated
    - `incurable` — the step fails with an explanation and a recommendation

**Strict replay-only mode** (`strict = true`) never contacts the LLM for code:
a cache miss fails immediately, a failed cached step is at most classified, and
nothing is regenerated or healed. This is the natural CI posture: generate
locally, run strict in the pipeline — see [Configuration](configuration.md)
and [Step cache](reference/step-cache.md).

## Where to go next

- [Getting started](getting-started.md) — wiring the library into a test framework or CI
- [Writing steps](guides/writing-steps.md) — authoring tests as scenarios
- [Configuration](configuration.md) — pyproject.toml settings, env overrides, the PrettyConfig API
- [Browser setup](guides/browser-setup.md) — engines, screen modes, remote browsers
- [Failure taxonomy](reference/failure-taxonomy.md) — the four failure kinds and the structured message
- [Hooks and logging](reference/hooks.md) — event callbacks for custom reporting
- [Step cache](reference/step-cache.md) — addressing, storage, attempt budgets, CI workflow
- [LLM providers](reference/llm-providers.md) — openai and anthropic parity, model settings
- [Self-healing](reference/self-healing.md) — classification categories and healing paths
- [Driver facade](reference/driver-facade.md) — the page API generated step code uses

!!! warning
    Step sentences land in the repository cache, the logs and the LLM requests:
    never put secrets or personal data into a step.
