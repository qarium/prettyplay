# Group recovery

Domain: the diagnosis-driven recovery of step groups. Audience: library internals and engineers
reasoning about recovered group runs.

## When recovery runs

Every classification point of a group step on a non-strict run routes here instead of the per-step
classification-and-heal: a failed check of a generation candidate, a failed cached replay and the
generation-budget exhaustion. Inside a group there is no isolated per-step healing. Strict mode
never runs recovery — the classification-only path stays.

## The cycle

```python
healed = recovery.recover(
    group_prompt="accept cookies, fill and submit the order form",
    traces=group_traces,          # GroupStepOutcome per group step, execution order
    step_text="the status shows order confirmed",
    step_type="assertion",
    previous_steps=scenario,      # the typed scenario records of the test, execution order
    identity=identity,
    attempt_history=history,
    page=page,
    window=window,
)
```

1. One group-level diagnosis request — the classification model and instructions, the group
   prompt, the step traces with outcomes and URL transitions, the current page state, the failed
   step's attempt history. Labels: `recoverable | product_defect | incurable`; a garbage answer
   degrades to incurable with the raw answer logged.
2. `product_defect` fails loudly; `incurable` fails terminally; a root named outside the group
   ends in the honest terminal failure naming that step.
3. `recoverable`: the row runs from the earliest affected group step through the failed step —
   each step regenerates as its own unit (the diagnosis recommendation + the group framing ride
   the request), re-executes immediately on the current page, passes the two-dimension compliance
   gate and writes back to the cache per step.
4. A repeat failure re-enters a fresh diagnosis and a new cycle while cycles remain; every new
   cycle grants each row step a fresh full healing counter; the number of cycles per group is
   capped by `healing_attempts` — never infinite.

## Reporting

The block itself reports through the four group lifecycle hook events — `on_group_started`,
then `on_group_passed` (a recovered group reports passed) or `on_group_failed`, closed by
`on_group_finished`. `on_healing_started` / `on_healed` fire per recovered step; the diagnosis
itself and the row composition stay log-only records.
