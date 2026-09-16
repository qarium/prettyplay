# Pace, step parameters and step groups — technical decisions

prettyplay gains config-level pace control, per-step `tries`/`delay` parameters, and
step groups with diagnosis-driven recovery. The product boundaries are fixed by the
PRD; this ADR records the technical decisions of the discovery interview that realize
them on the existing runtime (Playwright sync driver, per-step cache, engine loops,
LLM port) — every branch of the design tree was resolved with the author, nothing is
silently assumed.

## Decisions

### Pace (speed)

- The pace is the native Playwright `slow_mo` parameter, computed as
  `int((100 − speed) × 30)` ms and applied at browser start — local launch and remote
  connect alike, covering every launch mode; it acts on replays and strict runs
  identically. No library-level waiting layer.

### Step parameters

- `tries` is the **total number of executions of one piece of step code within its
  re-execution loop** — the first execution included, so `tries=1` means no
  re-execution. The counter belongs to each code unit: the cached code and every
  generated candidate each get their own full count; the LLM attempt budget is never
  multiplied. The count bound replaces the time bound; the pollable filter and the
  `polling_delay` pause keep applying.
- `delay` is a **pre-step** pause, not a post-step one (an amendment to the PRD
  ordered in the interview): the step's started event fires, the declared seconds
  pass quietly, then the step's code runs — uniform for the first step of a test,
  every following step and every re-execution inside a recovery row. The pause
  belongs to the step, so the PRD's skip rule dissolves: a step never reached after a
  terminal failure never pauses.

### Group authoring and generation

- The group block yields a group object with the ordinary step surface:
  `with t.group("…") as g: g.step(…); g.expect(…)` — no ambient rerouting of the test
  object. An empty group prompt fails loudly at entry; a group with zero steps is a
  quiet no-op.
- Generation framing is additive and **permanent**: a scenario-context entry keeps
  its group membership forever, so later ordinary steps and the group diagnosis see
  the group-marked steps in the full test context.

### Group recovery

- Every classification point of a group step — a failed check of a generation
  candidate, a failed cached replay, and the generation-budget-exhaustion
  classification — routes to **one group-level diagnosis** instead of per-step
  classification-and-heal; strict mode keeps the classification-only path.
- The diagnosis answers with its own closed label set `recoverable | product_defect |
  incurable` plus root cause, earliest affected step and recommendation. An
  unparseable or unrecognized answer degrades conservatively to incurable with the
  raw answer logged — a garbage answer never grants regeneration.
- The earliest affected step is named by a verbatim sentence quote matched against
  the group's steps; an unmatched quote degrades to the failed step itself.
- **Recovery is group-scoped**: the row is built from the group's own steps only,
  from the earliest affected step through the failed step. A diagnosis naming a root
  outside the group ends the run in the honest terminal incurable failure whose
  verdict names that step — no doomed cycles are spent.
- Each row step regenerates as its own per-step unit — its request carries the
  diagnosis recommendation and the group framing — re-executes immediately on the
  current page, and writes back to the cache per step.
- Budgets: row regenerations draw on the healing pool; **every new recovery cycle
  grants each row step a fresh healing counter** (the full `healing_attempts` pool
  per cycle), while the number of recovery cycles per group is capped by the
  `healing_attempts` value. Ordinary per-step healing keeps its per-test pool
  unchanged.
- A repeat failure inside the group re-enters a fresh diagnosis and a new cycle while
  cycles remain; a `product_defect` diagnosis fails loudly; cycle exhaustion ends in
  the terminal incurable failure with its verdict.
- The diagnosis request rides the classification model and the classification
  instructions (`classification_prompt`), attaches a screenshot when
  `send_screenshots` is on, and carries the group prompt, the group's step sentences
  with outcomes and URL transitions, the current page state and the failed step's
  attempt history.
- Reporting reuses the existing healing events (`on_healing_started` / `on_healed`)
  per recovered step plus structured log records for the diagnosis itself and the row
  composition; no new hook events.

### Group pace/pause (R6 — included)

- Group speed uses the same percent→ms formula as **pauses between the group's
  steps** — not `slow_mo`, which cannot change mid-run. A group pause waits **before
  the group's first step**, mirroring the step-level start pause. Both validate and
  behave quietly like their step-level counterparts.

## Isolation constraint

The new mechanisms must not touch the existing step cycle: the existing generation,
classification and compliance prompts stay frozen as they are; group generation
framing and group diagnosis form a **new cycle with their own prompts**. Future
maintenance of the ordinary step mechanisms must not affect groups, and vice versa.
(Explicit user constraint from the final interview round; recorded as C13 in the
PRD.)

## Considered options

- **delay placement** — post-step pause (the PRD's original mechanics) vs pre-step
  pause: chosen pre-step — the scenario reads bottom-up, and a delay declared on a
  step is more intuitive at the step's start; the observable settling-between-steps
  behavior is preserved.
- **recovery reach** — the row may name any earlier step of the test scenario vs
  strictly the group's steps: chosen strictly the group's steps. Crossing the
  boundary would let one diagnosis drag regeneration across the whole test — the
  group loses its meaning as a boundary; an outside root instead produces an honest,
  informative terminal refusal.
- **budget refresh** — per-test pools only (the PRD's original wording) vs fresh
  healing counters per recovery cycle: chosen fresh counters per cycle, bounded by
  the per-group cycle cap of `healing_attempts` — the loop stays finite while a
  second attempt is never starved by the first.
- **diagnosis labels** — reuse `rot | fixable | product_defect | incurable` vs a
  dedicated `recoverable | product_defect | incurable` set: chosen the dedicated set;
  inside a group rot and fixable are indistinguishable in action — the row
  regenerates from the diagnosis either way.
- **pace mechanism** — native Playwright `slow_mo` vs a library waiting layer:
  chosen `slow_mo`; it is exactly the required semantics with zero extra code.

## Consequences

- The PRD is amended accordingly: the start pause (UX, Goal 3, R3, R4.1, C10, SC5,
  scope), the group-scoped row with the honest outside-root refusal (UX, R5.3,
  scope), the per-cycle healing counters with the cycle cap (R5.6, scope), the
  pre-group pause (R6.2, UX, scope) and the isolation constraint (C13).
- Cache addressing stays `(cache_key, step_type, normalized sentence)` everywhere:
  group membership, group prompt, `tries`, `delay` and attempt history never join the
  address; replays stay LLM-free.
- Deliberately left open for the architecture stage (out of this ADR's scope): how
  the new surfaces wire into cells — the placement of the group block and the
  recovery cycle, the provider surface of the diagnosis request, and the shape of the
  new prompt artifacts the isolation constraint calls for.
