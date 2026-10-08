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
    traces=group_traces,  # GroupStepOutcome per group step, execution order
    prepared=PreparedStep(...),  # the render product of the failed step
    step_type="assertion",
    previous_steps=scenario,  # the typed scenario records of the test, execution order
    identity=identity,
    attempt_history=history,
    page=page,
    window=window,
    memory=memory,
)
```

1. One group-level diagnosis request — the classification model and instructions, the group
   prompt, the step traces with outcomes and URL transitions, the current page state, the failed
   step's attempt history. Labels: `recoverable | product_defect | incurable`; a garbage answer
   degrades to incurable with the raw answer logged.
2. `product_defect` fails loudly; `incurable` fails terminally; a root named outside the group
   ends in the honest terminal failure naming that step.
3. `recoverable`: the row runs from the earliest affected group step through the failed step —
   each step is
   re-rendered against the current context (its template sentence, its recorded inputs, the current memory),
   regenerates as its own unit (the diagnosis recommendation + the group framing ride the request), re-executes
   immediately on the current page, validates its returned result, passes the two-dimension compliance gate,
   publishes its captures to the test memory and writes back to the cache per step.
4. A repeat failure re-enters a fresh diagnosis and a new cycle while cycles remain; every new
   cycle grants each row step a fresh full healing counter; the number of cycles per group is
   capped by `healing_attempts` — never infinite.

## Reporting

Diagnosis and regeneration requests use the provider's bounded transport retries. Resending
an identical request consumes no additional group cycle or per-step healing attempt. A final
`LLMUnavailableError` propagates out of recovery; it never opens another recovery cycle.

The block itself reports through the four group lifecycle hook events — `on_group_started`,
then `on_group_passed` (a recovered group reports passed) or `on_group_failed`, closed by
`on_group_finished`. `on_healing_started` / `on_healed` fire per recovered step; the diagnosis
itself and the row composition stay log-only records.

## Memory and re-render

- Row steps re-render through `render_step` — recovery never reuses a stale instruction: the current memory and
  the step's recorded inputs produce the fresh one
- Recovery keeps local copies of previous scenario records and group traces. After each accepted row step, its
  newly prepared instruction replaces that occurrence in the local views used by later row requests and diagnoses;
  the test's stored records and appended traces remain immutable
- A failed row regeneration becomes the active failure for the next diagnosis: STEP and HISTORY describe that row
  step and its latest attempt; a complete row still returns the healed code of the originally failed step
- Every accepted row step publishes its captures immediately; a later failure in the row never rolls back accepted
  values — steps left behind keep their last accepted observations
- Traces carry the instruction (what the model saw and what the row matcher quotes) and the original `vars` of
  each step's call
