# Groups

Step groups — an authoring block for a coherent mini-scenario that heals as a
unit. For engineers writing multi-step flows where one failing step may root
in an earlier one.

## The group block

```python
with t.group("accept cookies, fill and submit the order form") as g:
    g.step("accept the cookie banner")
    g.step("fill the email field", delay=0.5)
    g.step("submit the form")
    g.expect("the status shows order confirmed", tries=2)
```

- `t.group(prompt, speed=None, delay=None)` yields the group object; the
  prompt names the shared goal of the block and reaches the generation and
  diagnosis requests verbatim as the framing — an empty prompt fails loudly
  at entry
- `g.step` / `g.expect` — the ordinary authoring surface inside the block,
  the `tries`/`delay` step parameters included
- `g.prompt` — the group prompt verbatim; `g.traces` — one verbatim trace
  record per executed group step (sentence, outcome, URL transition),
  appended by the executor in execution order and never rewritten
- A group with zero steps is a quiet no-op — the entry and exit framing
  records and nothing else
- Group membership changes no step's cache address: cached group steps
  replay as ordinary steps — no LLM calls, strict replay-only included.
  After the block there is no ambient rerouting: the steps that follow are
  ordinary steps again

## Group pace and pauses

```python
with t.group("the checkout flow", speed=30, delay=2) as g:
    ...
```

- `delay` — the entry pause: the declared seconds pass quietly immediately
  before the group's first executed step (lazy — a group that never executes
  a step never pauses)
- `speed` — the between-step pace, 0–100: before every following step the
  block sleeps `int((100 − speed) × 30)` ms — the same percent-to-pause
  mapping as the browser `speed` setting
  (see [Configuration](../configuration.md#pace)), but as a plain
  library-level wait, never `slow_mo`: the browser pace is fixed at browser
  start and cannot change mid-run
- Both optional and combinable; `None` — no pause of that kind. A step's own
  `delay` rides the ordinary step cycle on top

## Group-aware generation

Generation and regeneration requests of a group step carry the group
framing: a `GROUP PROMPT` block, and the scenario context in which group
entries stay marked (`- fill the email field [group step — the order form
group]`). Membership is permanent in the typed scenario records — a later
ordinary step still sees which of its predecessors ran inside which group.

The internal classification points are suppressed for group steps: a failed
check or a generation-budget exhaustion never asks the per-step
classification — the failure travels as an unclassified `IncurableStepError`
and the group diagnosis supplies the verdict. The
[compliance gate](../configuration.md#the-compliance-gate) still guards every
group candidate before the cache write-back — it is a caching path, not a
classification point.

## The diagnosis-driven recovery

On a non-strict run a failing group step — a failed cached replay or a
generation failure — routes to the group recovery instead of the per-step
heal; inside a group there is no isolated per-step healing.

1. One group-level diagnosis request — the classification model and
   instructions, the group prompt, the step traces with outcomes and URL
   transitions, the current page state and the failed step's attempt
   history. Labels: `recoverable`, `product_defect`, `incurable`; a garbage
   answer degrades to `incurable` with the raw answer logged — a retry cycle
   is never granted on garbage
2. `product_defect` fails loudly — never healed green; `incurable` fails
   terminally; a root named outside the group ends in the honest terminal
   failure naming that step
3. `recoverable`: the row runs from the earliest affected group step through
   the failed step — each step regenerates as its own unit (the diagnosis
   recommendation and the group framing ride the request), re-executes
   immediately on the current page, passes the compliance gate and writes
   back to the cache per step
4. A repeat failure re-enters a fresh diagnosis and a new cycle while cycles
   remain — never infinite; see [Budgets](#budgets)

Routing precedence: strict mode wins — the classification-only path, no
recovery, no framing; then the group recovery; an ordinary step keeps the
per-step heal of [Self-healing](self-healing.md). A still-terminal group
failure reaches the steering gate with the group context before propagating —
see [Interactive steering](interactive-steering.md).

## Reporting

The block frames itself with the four lifecycle events — `on_group_started`
on entry, then `on_group_passed` (a recovered group reports passed: the
recovery absorbed the failure, the traces keep the verbatim failed record)
or `on_group_failed` (the block exited through an exception), closed by
`on_group_finished` exactly once; all four carry the group prompt verbatim.
`on_healing_started` / `on_healed` fire per recovered step — the
`on_healing_started` category is `recoverable`, distinguishing a group row
from an ordinary `rot`/`fixable` heal. The diagnosis itself stays log-only:
`group_diagnosed` (INFO) and `group_diagnosis_degraded` (WARNING, the raw
answer), one `group_row_recovered` INFO record per recovered step —
see [Hooks and logging](hooks.md).

## Budgets

- Recovery cycles are capped per group per test by `healing_attempts`: two
  groups with the same prompt share one cap — the key is the prompt
- Every cycle grants each row step a fresh full healing counter, while the
  ordinary per-step pools of non-group steps are never consumed — worst case
  bounded: healing attempts per group step ≤ `healing_attempts ×
  healing_attempts` (cycles × pool)
- Recovery re-executions never rewrite the traces: the diagnosis of every
  cycle sees the honest original outcomes, the fresh failure rides the
  attempt history

## Limitations

!!! warning
    The group prompt and the step sentences land in the LLM requests and the
    logs: never put secrets or personal data into them.
