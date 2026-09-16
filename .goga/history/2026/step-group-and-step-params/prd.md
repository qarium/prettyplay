# Scenario Authoring: Pace Control, Step Parameters and Step Groups

Product change for **prettyplay** — a Python library where engineers write UI test
scenarios as plain sentences (`step(...)`, `expect(...)`); the step code is generated
by an LLM, cached per step, and replayed without any LLM involvement.

## Problem

Engineers authoring prettyplay scenarios hit four gaps in the authoring and
self-healing workflow:

1. **No pace control.** The browser runs at full speed; an engineer watching a headed
   run — debugging, demonstrating, pacing the interaction — cannot slow it down. The
   library exposes no pacing setting at all.
2. **No per-step retry bound.** The only absorption of transient step failures is the
   global, time-bounded settle window from the config; an engineer who knows a specific
   step is flaky (spinners, late hydration) cannot give that step a deterministic,
   count-bounded retry budget.
3. **No inter-step pause.** Pages that need settling time after an action (background
   processing, animations, debounced updates) force the engineer to embed waiting
   instructions into the step sentence — polluting the sentence, the cache address and
   the LLM request — or drop to the low-level escape hatch.
4. **Healing cannot reach back.** A multi-step interaction (accept cookies → fill the
   field → submit → check the status) is one logical scenario, but the LLM generating a
   step sees only a flat list of previous sentences with no shared goal, and healing is
   strictly per-step: when the root cause of a failed check lives in an earlier step
   (the fill never landed), regenerating the failed check can never fix the run — the
   test stays red and the engineer debugs and rewrites steps manually.

## Users

**Primary user — the test automation engineer** authoring UI scenarios as plain
sentences. Writes step sentences, runs the suite headed (local debugging,
demonstration) and headless in CI (cached replay); relies on the step cache for cheap
reruns and reads the suite output as a plain-language scenario.

User goals:

- control browser pace when watching a run;
- make an individually flaky step succeed without weakening the global polling
  settings or polluting the step sentence;
- give a page explicit settling time before a step begins;
- express a multi-step interaction as one coherent mini-scenario and have the library
  recover it when the root cause of a failed check lives in an earlier step of the
  interaction.

Expectations: the authoring surface stays plain sentences; cached replays stay
LLM-free and fast (strict replay-only mode included); healing stays bounded (no
infinite loops) and loud when it gives up; new settings follow the established layered
resolution (pyproject → environment → per-test override).

**Secondary actor — the integrator** wiring the library into a test framework or CI.
Owns the `[tool.prettyplay]` config layer; cares about deterministic CI behavior:
bounded budgets, explicit values, no accidental LLM calls on replay. The pace setting
is an ordinary config-layer value (a percentage) settable from file, environment or
per-test override — whatever writes it sees the same setting.

## Goals

1. **Watchable pace.** The engineer can control how fast the browser executes a run —
   from full speed down to a deliberately slow, observable pace — through the standard
   configuration layers, without touching step sentences.
2. **Per-step resilience.** The engineer can give an individual, known-flaky step its
   own deterministic retry budget, independent of the global time-bounded polling
   settings and without polluting the step sentence.
3. **Explicit inter-step settling.** The engineer can declare a pause before a given
   step — or before a whole interaction sequence — so pages that need background time
   settle before the step begins, instead of smuggling waiting instructions into
   step sentences or dropping to the low-level escape hatch.
4. **Self-recovering interaction scenarios.** The engineer can author a multi-step
   interaction as one coherent group with a shared goal; the library generates the
   group's steps as a single iteratively-built scenario, and when a failure's root
   cause lies in an earlier step of the group, it recovers the whole interaction —
   reaching back to the root cause and re-running the affected row — rather than
   leaving a red test for the engineer to debug and rewrite manually.

## User Experience

### Pacing a run (speed)

The engineer sets a pace as a percentage through the standard config layers
(pyproject → environment → per-test override). 100% — the default — is exactly today's
full-speed behavior; lower percentages slow the run down proportionally to a floor
(the slowest supported pace). The rest of the run experience is unchanged. An
out-of-range or malformed value fails at load with the loud actionable configuration
error naming the setting and the allowed range — never a silent ignore.

### Retrying a known-flaky step (tries)

The engineer declares a retry count on a step. The step executes; when it fails with a
transient failure kind (the same kinds polling already absorbs), the library quietly
re-executes it, at most the declared number of executions in total; the first success
makes the step green. Absorbed retries appear only as retry log records — the step
itself stays green, exactly like settle retries today. When all executions fail, the
step goes through the ordinary failure path — classification, healing, verdict
rendering — unchanged.

### Settling before a step (delay)

The engineer declares a pause in seconds on a step; the step starts, the library
waits the declared seconds quietly, then the step's code runs. The pause is quiet —
it shows up as elapsed time, not as output noise. Assertion steps accept it too. A
negative or malformed value is a loud actionable error.

### Authoring an interaction group

The engineer writes a multi-step interaction as one block: a group entered with a
group prompt, containing step and assertion sentences. The test source reads as a
scenario inside the scenario; step sentences keep appearing in the ordinary run output.

### First generation of a group

Steps generate sequentially as today — but every generation request inside the group
is framed by the group's shared goal: the LLM sees the group prompt and the group's
own earlier steps as one iteratively-expanding scenario, on top of the full test
scenario context — nothing existing is removed. Each step still lands in the cache as
an ordinary step.

### Replaying a group

A group whose steps are cached replays exactly like ordinary steps — no LLM
involvement, full pace, strict replay-only mode included. Group membership never
triggers regeneration on replay.

### Group recovery (the core experience)

When a step inside a group fails in a way that would otherwise be classified and
healed — a failed check during first generation or a failed cached replay — the
library skips the isolated per-step treatment and diagnoses with the whole interaction
in view: the group prompt, every step's outcome and transition, the current page
state. The diagnosis determines the earliest step of the group the failure actually
stems from; a root named outside the group ends the run in the honest terminal
failure whose verdict names that step — recovery never leaves the group's steps.
Otherwise, from that step, the affected row is regenerated sequentially and
re-executed immediately on the current page; the group then continues normally. The
engineer sees
loud reporting of the whole recovery: what failed, the diagnosis, which steps were
re-planned — the same loud-report style as healing today. When the diagnosis names a
product defect, or the recovery budget is exhausted, the test fails loudly with the
existing verdict rendering; recovery never masks a defect and never loops forever.

### Conditional pace/pause of a group

If feasible, a group declared with its own pace slows the pauses between its steps,
and a group pause waits before the group's first step begins — the same observable
behavior as the step-level features, applied at group scale.

## Requirements

### R1 — Pace setting

- **R1.1** A pace setting expressed as a percentage, living in the browser settings
  group of the project configuration and participating in the layered resolution
  (pyproject → environment → per-test override) like every other setting, with an
  environment override following the established naming pattern.
- **R1.2** Valid values: a number 0–100 inclusive; default 100 — full speed,
  identical to today's behavior.
- **R1.3** The pace maps to the pause inserted between the browser's actions: 100 →
  no pause, each point below 100 adds pause linearly, 0 → the maximum pause of
  3000 ms (the mapping `int((100 − speed) × 30)`).
- **R1.4** Applies in every launch mode — local headed, local headless, remote
  connect.
- **R1.5** An out-of-range or malformed value fails at configuration load with the
  loud actionable error naming the setting, the received value and the allowed range —
  never a silent ignore.

### R2 — Per-step retry count

- **R2.1** Steps and assertions accept an optional retry count — a positive integer,
  the total number of executions of one piece of the step's code within its
  re-execution loop (the first execution included; 1 — no re-execution); the cached
  code and every generated candidate each get their own full count.
- **R2.2** Absent — the step is governed by the global polling settings as today.
- **R2.3** Declared — the count bound replaces the time bound for that step's
  re-execution loop; the same transient-failure filter as polling applies, and the
  configured pause between re-executions still applies.
- **R2.4** Uniform for every execution of the step's code in the cycle — cached
  replay and generated candidates alike.
- **R2.5** The first successful execution makes the step green; absorbed
  re-executions surface only as retry log records, uniform with settle retries today.
- **R2.6** Exhausted — the step enters the ordinary failure path (classification,
  healing, verdicts) unchanged.
- **R2.7** Invalid values (zero, negative, non-integer) — loud actionable error at
  the step call.

### R3 — Per-step start pause

- **R3.1** Steps and assertions accept an optional pause in seconds — a non-negative
  number, fractional allowed.
- **R3.2** The pause precedes the step's own execution: the step's started event
  fires, the product waits the declared seconds, then the step's code runs — uniform
  for the first step of a test, every following step and every re-execution of a step
  inside a recovery row; a step never reached after a terminal failure never pauses.
- **R3.3** The pause is quiet — observable as elapsed time, not output noise.
- **R3.4** Zero allowed (explicit no-pause); negative or malformed — loud actionable
  error at the step call.

### R4 — Groups: authoring and generation

- **R4.1** The test object provides a group block entered with a group prompt and
  closed on exit; inside, steps and assertions use the same authoring surface as
  ordinary steps, retry count and start pause included.
- **R4.2** An empty group prompt — loud actionable error at group entry.
- **R4.3** Group membership changes no step's cache address; cached group steps
  replay as ordinary steps — no LLM calls, strict replay-only included.
- **R4.4** Generation inside a group stays sequential per step (the
  one-function-per-step form and per-step caching preserved); every generation
  request of a group step is framed additively — the group prompt and the group's own
  earlier steps marked as such, on top of the full test scenario context; nothing
  existing is removed.
- **R4.5** The run output keeps showing step sentences in execution order, the
  group's framing visible in the log consistent with existing logging.

### R5 — Groups: diagnosis-driven recovery

- **R5.1** On a non-strict run, a failure of a group step that would enter the
  classification-and-healing path — a failed check of a generation candidate or a
  failed cached replay — triggers **one group-level diagnosis request instead of the
  per-step classification-and-heal delegation**; inside a group there is no isolated
  per-step healing. The request carries the group prompt, the group's step sentences
  with their outcomes and transition states (URL before→after), the current page
  state, and the failed step's attempt history. The diagnosis carries the
  anti-masking categorization (R5.2). The generation loop's candidate retries within
  the generation budget are unchanged; strict mode keeps the classification-only path
  (R5.8).
- **R5.2** The diagnosis names the root cause and the earliest affected step; a
  product-defect diagnosis fails the test loudly through the existing product-defect
  failure — recovery never masks a defect.
- **R5.3** The earliest affected step is sought among the group's own steps —
  recovery never leaves the group. A diagnosis naming a step outside the group as the
  root cause ends in the honest terminal incurable failure whose verdict names that
  step: recovery is out of mandate, no doomed cycles are spent. Otherwise, from the
  earliest affected group step through the failed step, the affected steps regenerate
  sequentially — each its own generation request in the additive group context — and
  re-execute immediately on the current page; a re-planned action step repeats its
  action, never riding leftover state.
- **R5.4** Every successfully re-executed step is written back to the cache per step
  and loudly reported.
- **R5.5** After the recovered row, the group continues normally.
- **R5.6** Recovery regenerations draw on the healing pool of each row step; every
  new recovery cycle grants each row step a fresh healing counter (the full
  healing_attempts pool per cycle), while the number of recovery cycles per group is
  bounded by the healing_attempts value — the loop is never infinite; ordinary
  per-step healing keeps its per-test pool unchanged. Cycle exhaustion ends in the
  terminal incurable failure with its verdict, rendered as today.
- **R5.7** Recovery reporting is loud — what failed, the diagnosis, which steps were
  re-planned — in the existing healing-report style.
- **R5.8** Strict mode never runs group recovery; a terminally failed group step on
  an interactive non-strict run still reaches the steering dialog with the group
  context available.

### R6 — Conditional: group-level pace and pause

Feasibility-dependent, explicitly droppable without failing the change.

- **R6.1** A group declared with its own pace slows the pauses between the group's
  steps.
- **R6.2** A group declared with a pause waits before the group's first step begins —
  the group-scale mirror of the step-level start pause.

Both apply the same validation and quiet behavior as their step-level counterparts.

## Constraints

- **C1 — Cache identity is settled.** A step's address stays `(cache_key, step_type,
  normalized sentence)`. Group membership, group prompt, retry count, pause and
  attempt history never take part in addressing.
- **C2 — Replays stay LLM-free.** A cached step executes with zero LLM calls; strict
  replay-only mode never generates, heals or recovers groups, and never consumes
  attempt budgets.
- **C3 — Step-code form and cache structure are fixed.** One function per step, one
  cache file per step; group generation and recovery produce ordinary per-step units.
- **C4 — Anti-masking.** A classified product defect always fails the test loudly;
  group-level recovery, like per-step healing, may only turn rot/fixable failures
  green.
- **C5 — Bounded autonomy.** Every LLM-driven loop is bounded by the per-test attempt
  budgets; no unbounded retry or recovery loops, in any mode.
- **C6 — Loud actionable errors, one render per failure.** Invalid settings and
  invalid authoring inputs fail loudly naming the setting, the received value and the
  allowed form; every terminal failure renders once, identically across exception,
  log and hooks; failures propagate only through the existing failure taxonomy.
- **C7 — The compliance gate guards every caching path.** Every successfully executed
  candidate — group generation and recovery included — passes the two-dimension gate
  (instruction compliance, step adequacy) before it is cached.
- **C8 — Honest inputs.** Raw sentences reach every request verbatim; the group prompt
  joins requests as scenario framing on top, never replacing existing context.
- **C9 — Data leaves the machine.** Step sentences and group prompts land in the
  repository cache, the logs and LLM requests — the existing "never put secrets into a
  step" rule extends to group prompts.
- **C10 — Pacing and pauses live outside generated code.** Generated step code stays
  free of fixed delays (the existing driver rule); the pace setting and the
  step/group pauses are library-level behavior around steps.
- **C11 — Config uniformity.** Every new setting joins the layered resolution
  (pyproject → environment → per-test override) with loud validation; a raw
  validation error never leaves the loader.
- **C12 — Framework-agnostic authoring surface.** New capabilities live on the
  scenario object's authoring surface; no runner integration, no plugin machinery.
- **C13 — Isolation of the new mechanisms.** The group machinery changes nothing in
  the existing step cycle: the existing generation, classification and compliance
  prompts are not touched; group generation framing and group diagnosis are a new
  cycle with their own prompts. Future maintenance of the ordinary step mechanisms
  does not affect groups, and vice versa.

## Scope

### In Scope

Core (non-negotiable):

- The pace setting: percent configuration in the browser settings group, the linear
  percent→pause mapping (max 3000 ms), all config layers (file → environment →
  per-test override), loud validation, all launch modes.
- The per-step retry count on both step kinds: count-bounded re-execution for
  transient failures, replacing the time window for that step, uniform for cached and
  generated code, quiet retry records, ordinary failure path on exhaustion.
- The per-step start pause on both step kinds: quiet seconds-based pause before a
  step's code runs, loud validation.
- The group authoring block: group prompt entry/exit, ordinary steps inside, additive
  generation context (group prompt + marked group steps on top of the full test
  scenario), unchanged per-step caching and replay.
- Diagnosis-driven group recovery: the group-level diagnosis request
  (replacing the per-step heal delegation for group steps), earliest-affected-step
  determination (group-scoped — a root outside the group fails honestly), sequential
  regeneration and immediate re-execution, per-step cache write-back, fresh healing
  counters per recovery cycle bounded by the per-group cycle cap, anti-masking
  preserved, strict-mode and steering interplay.
- Public documentation of the new settings and authoring behavior.

Conditional (explicitly droppable):

- Group-level pace (pauses between the group's steps) and group-level start pause
  (before the group's first step) — included per the discovery decision; both
  validate and behave quietly like their step-level counterparts.

### Out of Scope

- Per-step pace overrides (config-level pace only).
- Nested groups.
- Any change to cache addressing, cache file structure, or the one-function-per-step
  code form — the group is never generated as one multi-step code unit.
- New failure kinds or changes to the failure taxonomy and error rendering.
- True page-state rollback — recovery always re-executes forward on the current page;
  no navigation-back machinery.
- Mechanical full-group restart on failure — rejected; recovery is diagnosis-driven
  only.
- Changes to the global polling behavior for steps without a declared retry count.
- Any GUI/slider work — the pace value's external source is out of the library's
  scope.
- New steering features beyond the group context reaching the existing dialog.
- Recovery analytics/metrics and LLM-request cost optimization.

## Success Criteria

- **SC1 (pace works).** The same scenario at pace 100 behaves indistinguishably from
  the current product; at lower percentages the run executes observably slower,
  following the linear mapping down to the 3000 ms maximum at 0.
- **SC2 (pace is an ordinary setting).** The pace is settable from the file,
  environment and per-test override layers; an out-of-range value fails at load with
  the loud actionable error naming setting, value and range.
- **SC3 (flaky step goes green).** A step declared with a retry count over a
  transiently failing area turns green within its declared executions while the
  global polling settings remain untouched; absorbed retries appear only as retry log
  records and the step stays green.
- **SC4 (exhaustion is honest).** A step whose declared executions all fail enters
  the ordinary failure path — classification, verdicts, existing failure kinds —
  nothing new.
- **SC5 (pause is measurable and quiet).** A declared pause delays the paused step's
  own start by the declared seconds — its started event fires, then the quiet wait,
  then its code — and produces no output noise; a step never reached after a terminal
  failure never pauses.
- **SC6 (the reference scenario recovers).** A group «accept cookies → fill the field
  → submit → check the status» whose check fails because the fill never landed
  recovers without human intervention: the diagnosis reaches back to the fill step,
  the affected row regenerates and re-executes, the test goes green, the healed steps
  are written back to the cache per step, and the recovery is loudly reported.
- **SC7 (group replay is LLM-free).** A group whose steps are all cached replays with
  zero LLM calls; strict replay-only mode runs a group without any recovery attempt.
- **SC8 (no masking, no loops).** A product-defect diagnosis inside a group fails the
  test loudly; budget exhaustion ends in the terminal incurable failure with its
  verdict — never an infinite recovery loop.
- **SC9 (addressing untouched).** The same sentence inside and outside a group is one
  cached step; group membership rides only generation and diagnosis requests.
