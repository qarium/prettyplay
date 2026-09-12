# Run lifecycle

Domain: how a run is composed — runtimes, contexts, hooks, failures, strict mode, polling, steering. Audience: integrators wiring the library into a runner and CI.

## Composition

One runtime per test: each PrettyPlay builds its own runtime — its own configuration, browser process, LLM provider and attempt budgets. Tests never share browser state or budgets through the library; outcomes do not depend on the execution order. Constructing a test is cheap and requires no LLM credentials: the browser starts lazily on the first step. A config passed to the test overrides only the explicitly set values — everything else resolves from pyproject+env; the override reaches inside the nested browser group. When the process exits, every runtime stops its browser and driver synchronously before returning control to the terminal — scripts never leave browser processes behind.

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

# a local generation session with polling and steering
test = PrettyPlay(
    cache_key="login",
    config=PrettyConfig(polling_timeout=8.0, interactive=True),
)
```

## Wiring into a framework

The library is framework-agnostic: no plugins, no base classes. Construct the object in your test, call the step methods, let failures propagate — the runner counts them as ordinary test failures. A few lines of glue are enough; the suite runs by the standard runner command.

## Strict mode — replay-only CI runs

`strict = true` (env PRETTYPLAY_STRICT, per-test override) turns the run into an honest replay: cached code executes exactly as stored and nothing is ever (re)generated. Settle polling still applies to cached code — re-executing it is execution, not generation.

- A cache miss fails the step as IncurableStepError stating that strict mode forbids generation — an expected CI signal: generating a step is a deliberate non-strict act
- A failed cached step is classified when LLM access is configured: product_defect raises ProductDefectError, rot/fixable/incurable raises IncurableStepError — never regenerated
- Without LLM access the failure raises immediately by step type — an assertion step raises ProductDefectError, an action step raises IncurableStepError — each carrying the full underlying error; a WARNING is logged
- Classifications are the only LLM calls; generation and healing budgets are never consumed

Team workflow: generate locally where the LLM is reachable, commit the cache directory, run CI fully from the cache with no LLM keys — optionally with strict=true for guaranteed replay-only behavior.

## Settle polling

`polling_timeout` (default None — off; 0 — explicit disable) opens one settle window per step execution, measured
from the first execution of the step's code: a transient failure of a pollable kind re-executes the same code after
`polling_delay` (default 0.5 s) until success or window end. Attempts appear as settle_retry log records; no LLM
budget is consumed. Locator ambiguity and Python-level errors of the step code never poll.

## Interactive steering

`interactive = true` (env PRETTYPLAY_INTERACTIVE, per-test override) arms the steering REPL for local generation
sessions: when a step terminally fails with IncurableStepError, a terminal dialog opens — step, failed code, error,
verdict, snapshot fragment, screenshot path — and every engineer message drives one regeneration executed against the
live page. A green turn heals the step and writes it back to the cache; quit/EOF/SIGINT raises the original terminal
failure. The dialog never opens on product_defect, in strict mode, or without LLM access, and consumes no budgets.
Keep it off in CI — an accidentally opened dialog would hang the run.

## Hooks

Implement the StepHooks callback contract and register the implementation — either pass the list to the keyword-only constructor parameter `hooks` (events are captured from the very construction) or call add_hooks before the first step. Step, generation, healing, cache and verdict events reach the handler synchronously. on_step_failed carries the full rendered failure message; on_step_verdict fires after it whenever the terminal failure carries an LLM verdict; on_step_finished closes every step exactly once, passed or failed. In strict mode generation and healing events never fire.

## Failures

Four kinds reach the runner:

| Kind | Meaning | Reaction |
|---|---|---|
| ProductDefectError | a real regression — also an AssertionError: runners show a failure, not an error; the traceback is folded to the library boundary | treat as a bug — this failure is the value of the suite |
| IncurableStepError | the step cannot be generated or healed — in strict mode also: the cache miss | follow the carried recommendation |
| LLMUnavailableError | the LLM is down | only generation and healing are blocked; cached steps keep running |
| ConfigurationError | the settings are invalid | fix the named setting — the message lists the allowed values |

ProductDefectError and IncurableStepError render one structured message — the primary reason line, the `---` separated step/error block with the full underlying error, the column-aligned verdict block — and the same text reaches the exception message, the on_step_failed hook event and the log. When the LLM is unavailable the verdict is skipped quietly; the failure itself never waits for it.

## Interactive sessions (IPython, Jupyter)

The Playwright session lives in a background driver thread owned by the library: the thread that executes the steps never holds a running asyncio loop, so interactive hosts that drive their own prompt through asyncio (IPython, Jupyter) keep working after every step — passed or failed.

Each test owns its browser process: it starts on the first step of the test and stops when the test closes. In scripts every runtime stops automatically at process exit through its atexit hook. In an interactive session the process keeps living between cells, so close the test object explicitly when the interactive exploration is over:

```python
from prettyplay import PrettyPlay

test = PrettyPlay("login-flow")
test.step("open the login page")
test.step("enter the login and password")
test.expect("the «Welcome back» message appears")
test.close()  # stops this test's browser and driver thread
```

Generation of the step cache remains a batch workflow: prefer a plain script or a pytest run over a REPL when generating many steps. The `interactive` setting of the previous section is a different thing entirely: it is the steering dialog of a stuck step, not a host mode.
