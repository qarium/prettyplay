# Pace control, step parameters and step groups

Single formulated task (user decision: no decomposition) implementing the approved
ADR (`.goga/history/2026/step-group-and-step-params/adr.md`) and the actualized PRD
(`.goga/history/2026/step-group-and-step-params/prd.md`) on the existing prettyplay
runtime.

## Current State

Derived from the project schema and the code of the affected cells:

- **Pace.** `DriverSession._launch_engine` (`prettyplay/driver/session.py`) starts the
  browser with `headless`/`channel`/`args` only — Playwright's native `slow_mo` is
  never passed; `BrowserConfig` (`prettyplay/config/models.py`) has no pace field
  (name, screen, headless, endpoint, accept_dialogs only). No pacing setting exists
  anywhere in the product.
- **Step parameters.** `PrettyPlay.step(text)` / `expect(text)`
  (`prettyplay/scenario.py`) accept only the sentence. Transient failures are absorbed
  solely by the global time-bounded settle window: `StepExecutor.execute` builds
  `SettleWindow(polling_timeout, polling_delay)` and `settle()`
  (`prettyplay/engine/polling/settle.py`) re-executes step code while time remains and
  the failure is pollable. There is no count-bounded re-execution mode and no pause
  attached to a step.
- **Groups.** No group machinery exists. The scenario context in
  `StepExecutor._scenario` is a flat `list[str]` of previous step sentences; the
  generator and the healer receive it as `previous_steps`. Healing is strictly
  per-step: `StepHealer.heal` classifies one failed step and, on rot/fixable,
  regenerates that one step — a root cause living in an earlier step can never be
  reached.
- **Reporting.** Ten hook events (`prettyplay/reporting/hooks.py`);
  `on_healing_started`/`on_healed` already exist — the ADR reuses them for group
  recovery and adds no new events.

## Description

Implement four mechanisms in prettyplay, exactly per the ADR decisions:

1. **Pace (speed).** A percentage setting in the `browser` group of the project
   configuration, participating in the layered resolution (pyproject → environment →
   per-test override) with the established env naming pattern. Valid values 0–100
   inclusive, default 100 — full speed, identical to today. The pace maps to
   Playwright's native `slow_mo` computed as `int((100 − speed) × 30)` ms (0 → the
   3000 ms maximum) and is applied at browser start — local launch and remote ws
   connect alike, every launch mode, replays and strict runs identically. An
   out-of-range or malformed value fails at configuration load with the loud
   actionable error naming the setting, the received value and the allowed range.
   No library-level waiting layer.
2. **Step parameters.** `step`/`expect` gain optional keyword parameters:
   - `tries` — a positive integer, the total number of executions of one piece of
     step code within its re-execution loop (the first execution included; 1 — no
     re-execution). The counter belongs to each code unit: the cached code and every
     generated candidate each get their own full count; the LLM attempt budget is
     never multiplied. Declared — the count bound replaces the time bound for that
     step's loop; the pollable filter and the `polling_delay` pause keep applying.
     Absent — the step is governed by the global polling settings as today. The
     first successful execution makes the step green; absorbed re-executions surface
     only as retry log records (uniform with settle retries). Exhausted — the
     ordinary failure path (classification, healing, verdicts) unchanged. Invalid
     values (zero, negative, non-integer) — loud actionable error at the step call.
   - `delay` — a non-negative number of seconds (fractional allowed), a **pre-step**
     pause: the step's started event fires, the declared seconds pass quietly, then
     the step's code runs — uniform for the first step of a test, every following
     step and every re-execution inside a recovery row; a step never reached after a
     terminal failure never pauses. The pause is quiet (elapsed time, no output
     noise). Zero allowed; negative or malformed — loud actionable error at the step
     call. Both step kinds accept both parameters.
3. **Step groups — authoring and generation.** The test object provides a group
   block: `with t.group("…") as g:` yields a group object with the ordinary step
   surface (`g.step(...)`, `g.expect(...)`, `tries`/`delay` included) — no ambient
   rerouting of the test object. An empty group prompt fails loudly at entry; a
   group with zero steps is a quiet no-op. Group membership changes no step's cache
   address; cached group steps replay as ordinary steps — no LLM calls, strict
   replay-only included. Generation inside a group stays sequential per step (the
   one-function-per-step form and per-step caching preserved); every generation
   request of a group step is framed additively — the group prompt and the group's
   own earlier steps marked as such, on top of the full test scenario context;
   nothing existing is removed. Group marking in the scenario context is permanent:
   later ordinary steps and the group diagnosis see the group-marked steps in the
   full test context. The run output keeps showing step sentences in execution order
   with the group framing visible in the log consistent with existing logging.
4. **Step groups — diagnosis-driven recovery.** On a non-strict run, every
   classification point of a group step — a failed check of a generation candidate,
   a failed cached replay, and the generation-budget-exhaustion classification —
   routes to **one group-level diagnosis request** instead of the per-step
   classification-and-heal delegation; inside a group there is no isolated per-step
   healing. The request rides the classification model and the classification
   instructions (`classification_prompt`), attaches a screenshot when
   `send_screenshots` is on, and carries the group prompt, the group's step sentences
   with their outcomes and URL transitions (before→after), the current page state and
   the failed step's attempt history. The diagnosis answers with its own closed label
   set `recoverable | product_defect | incurable` plus root cause, earliest affected
   step (a verbatim sentence quote matched against the group's steps; an unmatched
   quote degrades to the failed step itself) and recommendation. An unparseable or
   unrecognized answer degrades conservatively to `incurable` with the raw answer
   logged — a garbage answer never grants regeneration. Recovery is **group-scoped**:
   the row is built from the group's own steps only, from the earliest affected step
   through the failed step; a diagnosis naming a root outside the group ends the run
   in the honest terminal incurable failure whose verdict names that step — no doomed
   cycles are spent. Each row step regenerates as its own per-step unit (its request
   carries the diagnosis recommendation and the group framing), re-executes
   immediately on the current page — a re-planned action step repeats its action,
   never riding leftover state — passes the two-dimension compliance gate (C7, the
   same gate as every caching path) and writes back to the cache per step, loudly
   reported. Budgets: row regenerations draw on the healing pool; every new recovery
   cycle grants each row step a fresh healing counter (the full `healing_attempts`
   pool per cycle), while the number of recovery cycles per group is capped by the
   `healing_attempts` value — the loop is never infinite; ordinary per-step healing
   keeps its per-test pool unchanged. A repeat failure inside the group re-enters a
   fresh diagnosis and a new cycle while cycles remain; a `product_defect` diagnosis
   fails loudly through the existing product-defect failure; cycle exhaustion ends in
   the terminal incurable failure with its verdict, rendered as today. Strict mode
   never runs group recovery (classification-only path kept); a terminally failed
   group step on an interactive non-strict run still reaches the steering dialog with
   the group context available. Reporting reuses the existing healing events
   (`on_healing_started`/`on_healed`) per recovered step plus structured log records
   for the diagnosis itself and the row composition — no new hook events.
5. **Group pace and pause (R6 — included).** A group declared with its own pace
   slows the **pauses between the group's steps** by the same percent→ms formula
   (`int((100 − speed) × 30)` — library-level pauses, not `slow_mo`, which cannot
   change mid-run); a group declared with a pause waits **before the group's first
   step** — the group-scale mirror of the step-level start pause. Both validate and
   behave quietly like their step-level counterparts.
6. **Public documentation** of the new settings and authoring behavior (the project's
   MkDocs surface).

### Target API examples

The authoring surface fixed by the ADR/PRD (exact signatures — keyword-only or
positional, field names — belong to the architecture stage):

```python
from prettyplay import PrettyPlay

with PrettyPlay("checkout", config=...) as t:
    # pace — a configuration-layer setting: [tool.prettyplay.browser] speed = 40
    t.step("open the pricing page")

    # step parameters: tries — total executions, delay — pause before the step
    t.expect("the price list shows three plans", tries=3, delay=1.5)

    # a group: one coherent mini-scenario with a shared goal
    with t.group("accept cookies, fill and submit the order form") as g:
        g.step("accept the cookie banner")
        g.step("fill the email field", delay=0.5)
        g.step("submit the form")
        g.expect("the status shows order confirmed", tries=2)

    # group pace/pause: pauses between the group's steps / before its first step
    with t.group("slow demo checkout", speed=30, delay=2) as g:
        ...
```

## Scope

**In scope:**

- The pace setting: percent configuration in the browser settings group, the linear
  percent→pause mapping (max 3000 ms), all config layers (file → environment →
  per-test override), loud validation, all launch modes (local headed, local
  headless, remote connect), replays and strict runs.
- The per-step retry count on both step kinds: count-bounded re-execution for
  transient failures, replacing the time window for that step, uniform for cached and
  generated code, quiet retry records, ordinary failure path on exhaustion.
- The per-step start pause on both step kinds: quiet seconds-based pause before a
  step's code runs, loud validation.
- The group authoring block: group prompt entry/exit, ordinary steps inside (retry
  count and start pause included), additive generation context (group prompt + marked
  group steps on top of the full test scenario), unchanged per-step caching and
  replay.
- Diagnosis-driven group recovery: the group-level diagnosis request (replacing the
  per-step heal delegation for group steps), earliest-affected-step determination
  (group-scoped — a root outside the group fails honestly), sequential regeneration
  and immediate re-execution, per-step cache write-back, fresh healing counters per
  recovery cycle bounded by the per-group cycle cap, anti-masking preserved,
  strict-mode and steering interplay.
- Group-level pace (pauses between the group's steps) and group-level start pause
  (before the group's first step) — included per the discovery decision.
- Public documentation of the new settings and authoring behavior.
- Updates of the two project usage files approved in grooming: `playwright.md`
  (a `slow_mo` section) and `json_repair.md` (the group diagnosis answer as a second
  consumer of the salvage pattern).

**Out of scope:**

- Per-step pace overrides (config-level pace only).
- Nested groups.
- Any change to cache addressing, cache file structure, or the one-function-per-step
  code form — the group is never generated as one multi-step code unit.
- New failure kinds or changes to the failure taxonomy and error rendering.
- True page-state rollback — recovery always re-executes forward on the current page;
  no navigation-back machinery.
- Mechanical full-group restart on failure — recovery is diagnosis-driven only.
- Changes to the global polling behavior for steps without a declared retry count.
- Any GUI/slider work — the pace value's external source is out of the library's
  scope.
- New steering features beyond the group context reaching the existing dialog.
- Recovery analytics/metrics and LLM-request cost optimization.

## Acceptance Criteria

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
  verdict — never an infinite recovery loop. A diagnosis naming a root outside the
  group ends in the honest terminal failure whose verdict names that step.
- **SC9 (addressing untouched).** The same sentence inside and outside a group is one
  cached step; group membership rides only generation and diagnosis requests.
- **SC10 (group pace and pause work).** A group declared with its own pace slows
  the pauses between its steps observably by the same linear percent→ms mapping
  (never `slow_mo`); a group declared with a pause waits the declared seconds
  before its first step — its entry framing visible, the wait quiet; both validate
  loudly and behave quietly like their step-level counterparts.
- **C13 holds.** The existing generation, classification and compliance prompts stay
  byte-identical; group generation framing and group diagnosis live in new prompt
  artifacts of their own.
- The full test suite passes (`pytest tests/ -x`), `ruff check` is clean, and the
  public docs render the new settings and the group block.

## Stack

- **Frameworks:** none beyond the existing — Python 3.10+ package with
  `pyproject.toml`; pytest/ruff/pytest-cov for tests (project conventions).
- **Libraries:** Playwright sync API (existing hard dependency — native `slow_mo` at
  `launch()` and `connect()`; library-level `time.sleep` pauses for `delay` and group
  pauses); pydantic (existing — the `speed` field and its range validator, step-call
  validation of `tries`/`delay`); openai / anthropic SDKs (existing — the group
  diagnosis request rides the classification model by the same call patterns);
  json-repair (existing — salvage of a malformed diagnosis answer before the
  conservative `incurable` degradation).
- **Infrastructure:** none — no databases, brokers or CI changes.

## External Dependencies

| Component | Usage file | Status |
|-----------|--------------------------------|---------|
| playwright | `.goga/usages/cooks/playwright.md` | updated — a `slow_mo` section (the mapping, launch and connect alike, distinct from library-level group pauses) |
| json_repair | `.goga/usages/cooks/json_repair.md` | updated (minor) — the group diagnosis answer parse joins the compliance verdict as a consumer of the salvage pattern |
| pydantic | `.goga/usages/cooks/pydantic.md` | existing — covers kw_only models, the config schema and validators |
| openai | `.goga/usages/cooks/openai.md` | existing — SDK call patterns unchanged |
| anthropic | `.goga/usages/cooks/anthropic.md` | existing — SDK call patterns unchanged |

## Risks and Constraints

- **Isolation (C13) is the sharpest constraint.** The existing generation,
  classification and compliance prompts are frozen; group framing and group
  diagnosis must arrive as new prompt artifacts. Regressions here are detected by
  prompt-mirror test pins — they must extend to the new artifacts without touching
  the frozen mirrors.
- **Cache identity is settled (C1).** `(cache_key, step_type, normalized sentence)`
  everywhere; group membership, group prompt, `tries`, `delay` and attempt history
  never join the address; replays stay LLM-free (C2).
- **Bounded autonomy (C5).** Fresh healing counters per recovery cycle are bounded by
  the per-group cycle cap of `healing_attempts`; an unbounded recovery loop is a
  correctness bug, not a tuning issue.
- **Engine-loop surgery.** Routing the three classification points of a group step
  into one diagnosis touches the executor, the generator's budget-exhaustion path and
  the cached-replay failure path — the strict classification-only path and the
  steering gate must survive unchanged for non-group steps.
- **Honest inputs (C8) and data egress (C9).** Raw sentences and the group prompt
  reach requests verbatim; the group prompt joins the repository cache/logs/LLM
  requests, so the "never put secrets into a step" rule extends to it.
- **Anti-masking (C4) and one render per failure (C6)** — the group path must fail
  through the existing taxonomy with the existing structured render, exactly once.
- **slow_mo is per browser process** — it cannot change mid-run; group pace therefore
  uses library-level pauses between steps, never `slow_mo` (R6 mechanics).

## Scope Estimate

A single task — the user's explicit decision in grooming (an offered 5-way
decomposition A–E was declined). Large but cohesive: four weakly coupled mechanisms,
one shared authoring surface, one PRD/ADR contract. Internal ordering for the
implementation plan is still natural — pace → step parameters → group authoring →
group pace/pause → group recovery — but they ship as one change.

## Existing Architecture

Affected cells (per the goga schema) and their integration points:

- `prettyplay/config` — `BrowserConfig` gains the pace field + validator;
  `load_config` layers it (env override naming pattern, loud configuration error).
- `prettyplay/driver` — `DriverSession._launch_engine` passes `slow_mo` on both the
  local launch and the remote connect.
- `prettyplay/engine/polling` — the settle loop gains the count-bounded mode beside
  the time window (`SettleWindow`/`settle`).
- `prettyplay/engine` — group-aware generation framing (new prompt artifacts beside
  the frozen ones), the group diagnosis routine, the recovery cycle with fresh
  healing counters; the generation-budget-exhaustion classification point of a group
  step reroutes.
- `prettyplay/llm` — the provider surface of the diagnosis request (the ADR leaves
  its exact shape to the architecture stage: a new port method vs an engine-side
  composition over the existing classification call).
- `prettyplay/cache` — `RunBudgets` semantics extended with the per-cycle refresh and
  the per-group cycle cap (addressing untouched).
- `prettyplay` (facade) — `PrettyPlay.step`/`expect` signatures, the group block and
  group object, the pre-step pause wiring in `StepExecutor`.
- `prettyplay/engine/steering` — expected untouched: the group context reaches the
  existing dialog through the executor's existing inputs; if the architecture
  changes the scenario-context shape beyond plain sentences, this cell joins the
  affected list — an explicit checkpoint for the next stage.
- `prettyplay/reporting` — no new hook events; healing events reused, structured log
  records added.
- `docs/` (MkDocs) — the public documentation of the new settings and authoring
  behavior.

Open architectural wiring deliberately left to the next stage (recorded in the ADR):
cell placement of the group block and the recovery cycle, the provider surface of the
diagnosis request, and the shape of the new prompt artifacts.

## Notes

- Input artifacts: the ADR (all design-tree branches resolved with the author) and
  the actualized PRD — nothing is silently assumed; where this task and the PRD
  disagree, the ADR's amendments win (the pre-step pause, the group-scoped row, the
  per-cycle healing counters, the pre-group pause, the isolation constraint C13).
- Grooming decisions (this session): formulation and boundaries approved as proposed;
  the target API example block is included; the stack approved with zero new external
  components; two usage-file updates approved (`playwright.md`, `json_repair.md`);
  single task, no decomposition.
- Cache addressing, replays LLM-free, one function per step, the failure taxonomy and
  the layered config resolution are fixed constraints, not suggestions.
