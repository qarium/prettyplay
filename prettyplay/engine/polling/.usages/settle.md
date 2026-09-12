# Settle window

Domain: how transient page-state failures are absorbed before any costly move. Audience: engineers tuning polling_timeout and reasoning about retry behavior.

## The window

One settle window per step execution: the step executor creates it from the polling settings and threads it into
every execution of the step's code — cached code and generation candidates alike, replay-strict included.

```python
from prettyplay.engine.polling import SettleWindow, settle

window = SettleWindow(timeout=config.polling_timeout, delay=config.polling_delay)
settle(execute=run_step_code, code=cached_step.code, page=page, window=window)
```

`run_step_code` comes from `prettyplay.engine` — the execution routine the caller threads in.

- The window starts at the first execution of the step code — never at the first failure; the facade's internal
  waits count inside it, and the first execution may consume the whole window: no repetitions follow
- The window gates repetitions, never kills a running attempt: the remaining-time check happens only before a repeat
- A failure re-executes the same code after `polling_delay` when its kind is pollable and time remains — until
  success or window end; success continues the step normally
- Everything else propagates as-is: locator ambiguity, Python-level errors, non-pollable and unknown kinds. On
  cached code such a failure goes straight to classification; on a generation candidate it feeds the next
  regeneration request with the fresh error

## Visibility

Each repetition writes a `settle_retry` record to the logger prettyplay at INFO — the attempt counter and the failure
text. Re-executions emit no hook events: hook events fire per step or per LLM attempt, never per execution retry.

## Budgets

Re-executions consume no generation or healing budgets and make no LLM requests — polling is cheaper than one
regeneration attempt.

## Rules

- `polling_timeout` None (default) and 0 keep polling off — the settle call degenerates to a single execution
- `polling_delay` 0 re-executes without a pause
- The settle window never re-arms: one window per step execution, shared by every execution inside it
