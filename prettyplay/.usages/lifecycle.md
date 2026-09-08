# Run lifecycle

Domain: how a run is composed — runtime, contexts, hooks, failures. Audience: integrators wiring the library into a runner and CI.

## Composition

One process-wide runtime per run: the configuration, the browser process, the LLM provider and the attempt budgets are created once and shared by every test. Each PrettyTest opens its own isolated browser context and closes it on close(). Tests normally never touch the runtime directly — constructing PrettyTest is enough.

## Wiring into a framework

The library is framework-agnostic: no plugins, no base classes. Construct the object in your test, call the step methods, let failures propagate — the runner counts them as ordinary test failures. A few lines of glue are enough; the suite runs by the standard runner command.

## Hooks

Implement the StepHooks callback contract and register the implementation with add_hooks before the first step — step, generation, healing and cache events reach the handler synchronously.

## Failures

Three kinds reach the runner:

| Kind | Meaning | Reaction |
|---|---|---|
| ProductDefectError | a real regression | treat as a bug — this failure is the value of the suite |
| IncurableStepError | the step cannot be generated or healed | follow the carried recommendation |
| LlmUnavailableError | the LLM is down | only generation and healing are blocked; cached steps keep running |

## Team workflow

Generate locally where the LLM is reachable, commit the cache directory, run CI fully from the cache with no LLM keys.
