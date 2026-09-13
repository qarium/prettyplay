# Getting started

How a run is composed — runtimes, contexts, hooks, failures, strict mode.
For integrators wiring the library into a runner and CI.

## Install

```bash
pip install prettyplay
playwright install            # browser binaries for the driver
```

Requires Python 3.10+.

## A first test

```python
from prettyplay import PrettyPlay


def test_login():
    t = PrettyPlay("login-flow")
    t.step("open the login page")
    t.step("enter the login and password")
    t.step("click the «Sign in» button")
    t.expect("the «Welcome back» message appears")
    t.close()
```

Or with the context manager:

```python
with PrettyPlay("login-flow") as t:
    t.step("open the login page")
```

- `step(text)` performs what the sentence says
- `expect(text)` verifies what the sentence says; a legitimately failed
  expectation fails the test as a product defect

The constructor arguments form the cache address: `cache_key` (mandatory) and
`cache_path` (optional subdirectory). Equal keys in the shared root reuse one
cached step across tests; a different language, step type or key is a different
step — see [Step cache](reference/step-cache.md).

## Wiring into a framework

The library is framework-agnostic: no plugins, no base classes, no runner
integration. Construct the object in your test, call the step methods, let
failures propagate — the runner counts them as ordinary test failures. A few
lines of glue are enough; the suite runs by the standard runner command.

`ProductDefectError` also derives from `AssertionError`, so both unittest and
pytest report a failed expectation as a failure, never an error. Tracebacks of
library failures are folded at the `t.step(...)` / `t.expect(...)` call site:
internal engine frames never appear in what the runner shows.

## Seeing the scenario

Step sentences go to the `prettyplay` logger at info level — the suite output
reads as a plain-language scenario. The library configures no handlers — enable
logging to see the scenario in the output:

```python
import logging

logging.basicConfig(level=logging.INFO)          # plain unittest runs
```

```ini
# pytest: --log-cli-level=INFO
```

## Composition

One runtime per test: each `PrettyPlay` builds its own runtime — its own
configuration, browser process, LLM provider and attempt budgets. Tests never
share browser state or budgets through the library; outcomes do not depend on
the execution order. Constructing a test is cheap and requires no LLM
credentials: the browser starts lazily on the first step. A config passed to
the test overrides only the explicitly set values — everything else resolves
from pyproject+env; the override reaches inside the nested browser group:

```python
from prettyplay import BrowserConfig, PrettyConfig, PrettyPlay

# a strict run with a fullscreen browser
test = PrettyPlay(
    cache_key="login",
    config=PrettyConfig(
        strict=True,
        browser=BrowserConfig(screen="fullscreen", headless=False),
    ),
)
```

When the process exits, every runtime stops its browser and driver
synchronously before returning control to the terminal — scripts never leave
browser processes behind.

## Strict mode — replay-only CI runs

`strict = true` (env `PRETTYPLAY_STRICT`, per-test override) turns the run
into an honest replay: cached code executes exactly as stored and nothing is
ever (re)generated.

- A cache miss fails the step as `IncurableStepError` stating that strict mode
  forbids generation — an expected CI signal: generating a step is a
  deliberate non-strict act
- A failed cached step is classified when LLM access is configured:
  `product_defect` raises `ProductDefectError`, `rot`/`fixable`/`incurable`
  raises `IncurableStepError` — never regenerated
- Without LLM access the failure raises immediately by step type — an
  assertion step raises `ProductDefectError`, an action step raises
  `IncurableStepError` — each carrying the full underlying error; a `WARNING`
  is logged
- Classifications are the only LLM calls; generation and healing budgets are
  never consumed
- The settle window still applies to cached code — re-executing it is
  execution, not generation

Team workflow: generate locally where the LLM is reachable, commit the cache
directory, run CI fully from the cache with no LLM keys — optionally with
`strict = true` for guaranteed replay-only behavior.

## Settle polling

`polling_timeout` (default `None` — off; `0` — explicit disable; env
`PRETTYPLAY_POLLING_TIMEOUT`, per-test override) opens one settle window per
step execution, measured from the first execution of the step's code: a
transient failure of a pollable kind — timeouts, element-state races,
navigation races, failed expectations — re-executes the same code after
`polling_delay` (default 0.5 s) until success or window end. Attempts appear
as `settle_retry` log records; no LLM budget is consumed, and the window
applies to cached code in strict mode too. Locator ambiguity and Python-level
errors of the step code never poll. Size the window above the longest facade
wait it must absorb — 6.0 covers one exhausted 5 s expectation plus one
re-execution.

```python
from prettyplay import PrettyConfig, PrettyPlay

# a local generation session with a settle window
test = PrettyPlay("login-flow", config=PrettyConfig(polling_timeout=8.0))
```

## Interactive steering

`interactive = true` (default `false`; env `PRETTYPLAY_INTERACTIVE`, per-test
override) arms the steering REPL for local generation sessions: when a step
terminally fails with `IncurableStepError` on a non-strict run, a terminal
dialog opens — step, failed code, error, verdict, snapshot fragment,
screenshot path — and every engineer message drives one regeneration executed
against the live page. Local commands serve the context without an LLM
request: `snapshot` (the full accessibility snapshot), `screenshot` (a full
PNG written to a temporary file, path printed), `error` and `code` (the
stored texts) and `quit`. A green turn heals the step and writes it back to
the cache; a red turn is one bare execution — the settle window never
re-arms inside the dialog — and its outcome joins the history of the next
request; quit, EOF, SIGINT or an unreadable stdin raises the original
terminal failure. The dialog never opens on `product_defect`, in strict
mode, or without LLM access, and consumes no budgets. Keep it off in CI — an
accidentally opened dialog would hang the run.

```python
from prettyplay import PrettyConfig, PrettyPlay

# a local generation session with the steering dialog armed
test = PrettyPlay("login-flow", config=PrettyConfig(interactive=True))
```

## Hooks

Implement the `StepHooks` callback contract and register the implementation —
either pass the list to the keyword-only constructor parameter `hooks` (events
are captured from the very construction) or call `add_hooks` before the first
step. Step, generation, healing, cache and verdict events reach the handler
synchronously. See [Hooks and logging](reference/hooks.md).

## Failures

Four kinds reach the runner — see [Failure taxonomy](reference/failure-taxonomy.md):

| Kind | Meaning | Reaction |
|---|---|---|
| `ProductDefectError` | a real regression — also an `AssertionError` | treat as a bug — this failure is the value of the suite |
| `IncurableStepError` | the step cannot be generated or healed — in strict mode also: the cache miss | follow the carried recommendation |
| `LLMUnavailableError` | the LLM is down | only generation and healing are blocked; cached steps keep running |
| `ConfigurationError` | the settings are invalid | fix the named setting — the message lists the allowed values |

## Interactive sessions (IPython, Jupyter)

The Playwright session lives in a background driver thread owned by the
library: the thread that executes the steps never holds a running asyncio
loop, so interactive hosts that drive their own prompt through asyncio
(IPython, Jupyter) keep working after every step — passed or failed.

Each test owns its browser process: it starts on the first step of the test
and stops when the test closes. In scripts every runtime stops automatically
at process exit through its atexit hook. In an interactive session the process
keeps living between cells, so close the test object explicitly when the
interactive exploration is over:

```python
from prettyplay import PrettyPlay

test = PrettyPlay("login-flow")
test.step("open the login page")
test.step("enter the login and password")
test.expect("the «Welcome back» message appears")
test.close()  # stops this test's browser and driver thread
```

Generation of the step cache remains a batch workflow: prefer a plain script
or a pytest run over a REPL when generating many steps. The `interactive`
setting of the previous section is a different thing entirely: it is the
steering dialog of a stuck step, not a host mode.
