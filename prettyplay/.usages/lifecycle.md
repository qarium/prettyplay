# Run lifecycle

Domain: how a run is composed — runtimes, contexts, hooks, failures, strict mode. Audience: integrators wiring the library into a runner and CI.

## Composition

One runtime per test: each PrettyTest builds its own runtime — its own configuration, browser process, LLM provider and attempt budgets. Tests never share browser state or budgets through the library; outcomes do not depend on the execution order. Constructing a test is cheap and requires no LLM credentials: the browser starts lazily on the first step. A config passed to the test overrides only the explicitly set values — everything else resolves from pyproject+env; the override reaches inside the nested browser group. When the process exits, every runtime stops its browser and driver synchronously before returning control to the terminal — scripts never leave browser processes behind.

```python
from prettyplay import BrowserConfig, PrettyConfig, PrettyTest

# a strict run with a fullscreen browser
test = PrettyTest(
    cache_key="login",
    config=PrettyConfig(
        strict=True,
        browser=BrowserConfig(screen="fullscreen", headless=False),
    ),
)
```

## Wiring into a framework

The library is framework-agnostic: no plugins, no base classes. Construct the object in your test, call the step methods, let failures propagate — the runner counts them as ordinary test failures. A few lines of glue are enough; the suite runs by the standard runner command.

## Strict mode — replay-only CI runs

`strict = true` (env PRETTYPLAY_STRICT, per-test override) turns the run into an honest replay: cached code executes exactly as stored and nothing is ever (re)generated.

- A cache miss fails the step as IncurableStepError stating that strict mode forbids generation — an expected CI signal: generating a step is a deliberate non-strict act
- A failed cached step is classified when LLM access is configured: product_defect raises ProductDefectError, rot/incurable raises IncurableStepError — never regenerated
- Without LLM access the failure raises immediately by step type — an assertion step raises ProductDefectError, an action step raises IncurableStepError — each carrying the full underlying error; a WARNING is logged
- Classifications are the only LLM calls; generation and healing budgets are never consumed

Team workflow: generate locally where the LLM is reachable, commit the cache directory, run CI fully from the cache with no LLM keys — optionally with strict=true for guaranteed replay-only behavior.

## Hooks

Implement the StepHooks callback contract and register the implementation with add_hooks before the first step — step, generation, healing, cache and verdict events reach the handler synchronously. on_step_failed carries the full rendered failure message; on_step_verdict fires after it whenever the terminal failure carries an LLM verdict. In strict mode generation and healing events never fire.

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
from prettyplay import PrettyTest

test = PrettyTest("login-flow")
test.action("open the login page")
test.action("enter the login and password")
test.assertion("the «Welcome back» message appears")
test.close()  # stops this test's browser and driver thread
```

Generation of the step cache remains a batch workflow: prefer a plain script or a pytest run over a REPL when generating many steps.
