# Run lifecycle

Domain: how a run is composed — runtime, contexts, hooks, failures. Audience: integrators wiring the library into a runner and CI.

## Composition

One process-wide runtime per run: the configuration, the browser process, the LLM provider and the attempt budgets are created once and shared by every test. Each PrettyTest opens its own isolated browser context and closes it on close(). Tests normally never touch the runtime directly — constructing PrettyTest is enough. When the process exits, the runtime stops the browser and the driver synchronously before returning control to the terminal — scripts never leave browser processes behind.

## Wiring into a framework

The library is framework-agnostic: no plugins, no base classes. Construct the object in your test, call the step methods, let failures propagate — the runner counts them as ordinary test failures. A few lines of glue are enough; the suite runs by the standard runner command.

## Hooks

Implement the StepHooks callback contract and register the implementation with add_hooks before the first step — step, generation, healing, cache and verdict events reach the handler synchronously. on_step_verdict fires after on_step_failed whenever the terminal failure carries an LLM verdict.

## Failures

Four kinds reach the runner:

| Kind | Meaning | Reaction |
|---|---|---|
| ProductDefectError | a real regression — also an AssertionError: runners show a failure, not an error; the traceback is folded to the library boundary | treat as a bug — this failure is the value of the suite |
| IncurableStepError | the step cannot be generated or healed | follow the carried recommendation |
| LlmUnavailableError | the LLM is down | only generation and healing are blocked; cached steps keep running |
| ConfigurationError | the settings are invalid | fix the named setting — the message lists the allowed values |

ProductDefectError and IncurableStepError carry the LLM verdict — category, explanation, recommendation — in the exception message, the on_step_verdict hook event and the log. When the LLM is unavailable the verdict is skipped quietly; the failure itself never waits for it.

## Team workflow

Generate locally where the LLM is reachable, commit the cache directory, run CI fully from the cache with no LLM keys.

## Interactive sessions (IPython, Jupyter)

The Playwright session lives in a background driver thread owned by the library: the thread that executes the steps never holds a running asyncio loop, so interactive hosts that drive their own prompt through asyncio (IPython, Jupyter) keep working after every step — passed or failed.

The browser process stays alive for the whole session once the first step has run. In scripts it stops automatically at process exit via the runtime atexit hook. In an interactive session the process keeps living between cells, so release the browser explicitly when interactive exploration is over:

```python
from prettyplay import get_runtime

get_runtime().close()  # stops the browser and the driver thread
```

Generation of the step cache remains a batch workflow: prefer a plain script or a pytest run over a REPL when generating many steps.
