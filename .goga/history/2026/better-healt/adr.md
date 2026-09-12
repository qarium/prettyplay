# ADR: Fixable classification, honest settle polling, and interactive steering for stuck steps

```md
---
status: accepted
date: 2026-09-12
author: Goga (interviewed via goga-discover)
---
```

## Context and decision

prettyplay's failure taxonomy (rot / product_defect / incurable) had no slot for "the step code is
at fault but the intent is satisfiable" — a Playwright locator-ambiguity error (strict-mode
violation: the locator resolved 61 elements) is neither rot (the UI did not change), nor
product_defect, nor truly incurable (regeneration can help). The classifier understood the cause
and said so in `explanation`/`recommendation`, yet the category forced an `IncurableStepError`:
understanding without action. We decided to make every classification verdict actionable, absorb
transient page-state races with an honest settle window instead of misreading them as structural
rot, and give the engineer an opt-in interactive escape hatch when the agent loop is terminally
stuck.

## Decisions

### 1. Fourth classification category `fixable`

`fixable` joins the taxonomy: the step code is at fault (ambiguous or wrong locator/strategy),
the intent is satisfiable, regeneration for the same intent can help. `rot` keeps its pure
meaning ("the UI changed"). The label set becomes: `rot`, `product_defect`, `fixable`,
`incurable` (pre-1.0 breaking change for category consumers — accepted).

**Uniform decision table** — one table on every path (generation loop, healing, budget
exhaustion, failed check); the category decides, the path only delivers:

| Verdict | Action |
|---|---|
| product_defect | `ProductDefectError` — loud, never healed (anti-masking stands) |
| rot, fixable | regeneration carrying the recommendation |
| incurable | terminal `IncurableStepError` with the verdict |

Boundaries unchanged: replay-strict never regenerates; no LLM — terminal failure as today.

### 2. The classifier's understanding becomes action

- The classification `recommendation` explicitly enters every regeneration request it preceded
  (as a block after CODE/ERROR) — regeneration starts from the diagnosis, not the raw error.
- Generation-budget exhaustion with a rot/fixable verdict grants **exactly one** extra
  recommendation-carrying regeneration, paid from the step's healing budget. No reclassification
  after it; a repeat failure is terminal.
- A failed check (AssertionError: the check executed and did not hold) **is** healed through the
  classifier — the selector may have drifted, regenerating the check code heals it. If the
  regenerated check fails again, **one final classification decides only the terminal kind**
  (product_defect → `ProductDefectError`; anything else → `IncurableStepError`). No further
  regeneration — this is the deliberate bound on the accepted masking window.
- Per-attempt classification inside the generation loop: **rejected** (LLM cost), deferred.

### 3. Honest settle polling for transient failures

A page-state race (previous step's action done, state transition in flight, next step fails on
the stale state) must not be treated as structural rot: regenerating against a stale snapshot
produces dead code, and the terminal classification then sees a settled page and says "fixable"
over a raised failure — an absurd verdict we refuse to produce.

- `polling_timeout` is the **total settle horizon of a step execution**: the window starts with
  the first execution of the step code (cached code or candidate), not at the first failure —
  otherwise the effective timeout would be dishonestly inflated on top of the facade's internal
  waits, which count inside the window.
- A failure of a **pollable** kind with time remaining in the window → re-execute the same code
  after `polling_delay`, until success or window end. Success → the failure was transient; the
  step continues normally, attempts visible in the log. No LLM budget is consumed. No running
  attempt is ever killed mid-flight — the window gates repetitions, not executions.
- Window expired (the first execution consumed it) → straight to classification and the uniform
  decision table.
- **Pollable error kinds** (fixed built-in map of driver error kinds, no LLM in the decision):
  not found / not visible / not enabled, timeouts, navigation in flight / execution context
  destroyed, detached/stale element, a failed check (AssertionError — the state may catch up;
  the same code passing is not masking). **Not pollable**: locator ambiguity (the elements are
  there — 61 of them; waiting will not collapse them to one; goes straight to classification →
  fixable → regeneration with an unambiguous locator) and Python-level errors of the step code.
- Polling runs before any costly move: before classification, before the next LLM attempt in the
  generation loop, before the final classification after a verdict-driven regeneration. Applied
  everywhere **including replay-strict** — it re-executes the same cached code, which is
  execution, not generation.
- Settings: `polling_timeout` (default `None` — polling is opt-in and disabled until a positive
  value is set; `0` is an explicit disable, equivalent to `None`) and `polling_delay`
  (default 0.5 s) in pyproject + env + per-test override, uniform with the other settings. A
  recommended positive value remains a design-time concern given the facade's internal waits
  count inside the window.

### 4. Interactive steering mode

When the agent loop is terminally stuck, the engineer can talk to the LLM and push it through.

- Enablement: the `interactive` setting in `[tool.prettyplay]` (default off) +
  `PRETTYPLAY_INTERACTIVE` env + per-test override via `PrettyConfig`. Explicit opt-in — an
  accidentally enabled REPL in CI would hang the run.
- Trigger: the moment an engine is about to raise `IncurableStepError`, on any incurable path.
  **Never** on product_defect (a dialog must never repaint a red test green); **never** in
  replay-strict; no interactivity when the LLM is unavailable.
- Dialog: a multi-turn terminal REPL. Shows the step, code, error, verdict
  (explanation + recommendation), a snapshot fragment, a screenshot path; local commands without
  LLM (full snapshot, screenshot, error, code). Each engineer message is guidance: a
  regeneration request carrying a USER GUIDANCE block plus the conversation history; the result
  executes against the live page; success → the step is healed. quit / EOF / SIGINT → the
  original terminal failure is raised; nothing hangs.
- An interactively healed step is written back to the cache only after a successful execution
  (uniform with healing). The guidance is one-shot (logged, not persisted). Interactive attempts
  consume no generation/healing budgets — the human in the loop is the bound.
- v1 surface: the built-in terminal REPL only. Manual code paste by the engineer and a
  hook-based custom UI (IDE integrations) are rejected for v1; persistence of guidance in the
  cache file is deferred.

## Considered options (rejected, worth remembering)

- **Broaden `rot`** to "regeneration is meaningful" instead of a fourth category — rejected: the
  taxonomy is valued for sharpness (category = decision + diagnostics for `on_step_verdict`);
  a fourth world state deserves a fourth label.
- **React to recommendation semantics without a category** — rejected: unactionable, no label
  for hooks and diagnostics.
- **Unbounded regeneration while the classifier says fixable** — rejected: loop risk on budget.
- **No healing for failed checks** (keep the stop absolute) — considered and **overridden by the
  engineer**: a drifted selector makes a check healable by regeneration; the masking risk is
  accepted and guarded (product_defect classification + single regeneration + final
  classification decides the terminal kind).
- **One-shot "try again" before classification** — rejected in favor of the honest polling
  window measured from the first execution (the engineer's correction: a post-failure grace
  period produces a dishonest total timeout).
- **Polling disabled in replay-strict** — considered and **overridden by the engineer**: polling
  applies to cached code in strict mode; it re-executes cached code, it does not generate.
- **Free-form chat REPL where the LLM answers conversationally** — rejected: each turn must have
  a measurable outcome (green/red) under the existing generation contract; page questions are
  answered by local snapshot/screenshot commands.

## Consequences

- Anti-masking is deliberately weakened on the failed-check path (a regenerated check may pass
  where the original honestly failed). Guards: product_defect classification, exactly one
  verdict-driven regeneration, and the final classification that can still surface
  `ProductDefectError` on the second failure.
- Polling and regeneration re-execute the whole step function; non-idempotent actions may fire
  twice. Accepted: regeneration already re-executes the step function, so polling is no riskier
  and cheaper.
- `polling_timeout` bounds the total settle time of a step execution; the facade's internal
  waits are inside it. Polling is opt-in (`None` default); a recommended positive value may be
  proposed at design.
- Category-label consumers (hooks, verdict events) see a new label — pre-1.0 break, accepted.
- Terminology pinned to avoid the "strict" collision: **replay-strict** = prettyplay's `strict`
  replay-only mode; **locator ambiguity** = the Playwright strict-mode violation of a locator
  resolving multiple elements.

## Unresolved (handed to the design stage, out of discover scope)

- Exact wiring of the new category through the classification prompt, hook payloads and error
  reason texts; the rendered-message policy for verdict-driven terminal failures.
- The concrete mechanism of the pollable-error-kind map against the driver error surface.
- REPL presentation details (snapshot fragment size, screenshot handling) and how the
  interactive path renders guidance history into requests.
- Final validation of a recommended `polling_timeout` value (polling is disabled by default)
  against the facade's internal wait behavior; the `polling_delay` default is fixed at 0.5 s.
