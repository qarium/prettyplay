# Settle polling

The re-execution policy of step-code execution. For engineers tuning
`polling_timeout` and reasoning about retry behavior.

One settle window per step execution: the step executor creates it from the
polling settings and threads it into every execution of the step's code —
cached code and generation candidates alike, replay-strict included.

## The window

- The window starts at the first execution of the step code — never at the
  first failure; the facade's internal waits count inside it, and the first
  execution may consume the whole window: no repetitions follow
- The window gates repetitions, never kills a running attempt: the
  remaining-time check happens only before a repeat
- A failure re-executes the same code after `polling_delay` when its kind is
  pollable and time remains — until success or window end; success continues
  the step normally
- Everything else propagates as-is: locator ambiguity, Python-level errors of
  the step code, non-pollable and unknown kinds. On cached code such a failure
  goes straight to classification; on a generation candidate it feeds the next
  regeneration request with the fresh error

| Setting | Default | Env | Meaning |
|---|---|---|---|
| `polling_timeout` | `None` | `PRETTYPLAY_POLLING_TIMEOUT` | settle window seconds per step execution; `None`/`0` — polling off |
| `polling_delay` | `0.5` | `PRETTYPLAY_POLLING_DELAY` | pause between re-executions, seconds |

Size the window above the longest facade wait it must absorb — `6.0` covers
one exhausted 5 s expectation plus one re-execution.

```python
from prettyplay import PrettyConfig, PrettyPlay

# a local generation session with a settle window
test = PrettyPlay("login-flow", config=PrettyConfig(polling_timeout=8.0))
```

Inside the engine contour the policy is a plain function pair:

```python
from prettyplay.engine.polling import SettleWindow, settle

window = SettleWindow(timeout=config.polling_timeout, delay=config.polling_delay)
settle(execute=run_step_code, code=cached_step.code, page=page, window=window)
```

`run_step_code` comes from `prettyplay.engine` — the execution routine the
caller threads in.

## Which failures poll

The driver ships a fixed pollable map, exported as `is_pollable_failure(exc)`
from `prettyplay.driver`: it returns `True` when the exception kind is
transient page state and `False` when the failure is deterministic or unknown
— see [Driver facade](driver-facade.md#pollable-failure-kinds). Pollable:
timeouts, element-state races, navigation and context races, plain
`AssertionError`s of failed expectations. Not pollable: locator ambiguity
(deterministic), Python-level errors of the step code itself, unrecognized
failures. The map is fixed in code: it never reads settings and never asks an
LLM.

## Visibility

Each repetition writes a `settle_retry` record to the logger `prettyplay` at
INFO — the attempt counter and the failure text. Re-executions emit no hook
events: hook events fire per step or per LLM attempt, never per execution
retry.

## Budgets

Re-executions consume no generation or healing budgets and make no LLM
requests — polling is cheaper than one regeneration attempt. The window
applies to cached code in strict mode too: re-executing cached code is
execution, not generation.

## Rules

- `polling_timeout` `None` (default) and `0` keep polling off — the settle
  call degenerates to a single execution
- `polling_delay` `0` re-executes without a pause
- The window never re-arms: one window per step execution, shared by every
  execution inside it — the steering dialog included
- A non-pollable failure is never swallowed, translated or retried — the
  classification path decides it
