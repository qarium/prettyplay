# Actionable failure verdicts: fixable category, settle polling, interactive steering

## Current State

prettyplay's failure taxonomy (`prettyplay/failures`) has three categories — `rot`,
`product_defect`, `incurable`. The classifier (`prettyplay/llm`) produces a category plus
`explanation`/`recommendation`, but there is no slot for "the step code is at fault, the
intent is satisfiable, regeneration can help": a Playwright locator-ambiguity failure
(strict-mode violation: the locator resolved 61 elements) is forced into
`IncurableStepError` — the classifier understands the cause and states the fix, yet nothing
acts on it.

The engine (`prettyplay/engine`) regenerates on `rot`, but:

- the classification `recommendation` never enters regeneration requests — regeneration
  starts from the raw error, not from the diagnosis;
- generation-budget exhaustion is terminal, whatever the verdict said;
- a failed check (`AssertionError`: the check executed and did not hold) stops the
  **generation loop** absolutely — a candidate check is classified and raised terminal
  without any regeneration, whatever the verdict said; a drifted selector makes a
  candidate check unhealable (a failed cached check on the healing path is already
  classified and healable via a `rot` verdict today);
- there is no polling: a transient page-state race (previous action done, state transition
  in flight, next step fails on the stale state) goes straight to classification — either
  misread as structural `rot` (regeneration against a stale snapshot produces dead code)
  or producing the absurd verdict "fixable" over a raised failure.

There is no interactive steering: when the agent loop is terminally stuck, the engineer
cannot talk to the LLM and push it through. The settings (`prettyplay/config`, facade
`PrettyConfig`) have no `polling_timeout` / `polling_delay` / `interactive` keys.

Source ADR: `.goga/history/2026/better-healt/adr.md` (status: accepted).

## Description

Make every classification verdict actionable, absorb transient page-state races with an
honest settle window, and give the engineer an opt-in interactive escape hatch when the
loop is terminally stuck. Four coupled decisions:

1. **Fourth classification category `fixable`** — "the step code is at fault (ambiguous or
   wrong locator/strategy), the intent is satisfiable, regeneration for the same intent can
   help". `rot` keeps its pure meaning ("the UI changed"). The label set becomes `rot`,
   `product_defect`, `fixable`, `incurable` (pre-1.0 breaking change for category-label
   consumers — accepted).

2. **Uniform decision table on every path** (generation loop, healing, budget exhaustion,
   failed check) — the category decides, the path only delivers:

   | Verdict | Action |
   |---|---|
   | `product_defect` | `ProductDefectError` — loud, never healed (anti-masking stands) |
   | `rot`, `fixable` | regeneration carrying the recommendation |
   | `incurable` | terminal `IncurableStepError` with the verdict |

3. **Verdicts become action**:
   - the classification `recommendation` explicitly enters every regeneration request it
     preceded (as a block after CODE/ERROR) — regeneration starts from the diagnosis;
   - generation-budget exhaustion with a `rot`/`fixable` verdict grants **exactly one**
     extra recommendation-carrying regeneration, paid from the step's healing budget; no
     reclassification after it; a repeat failure is terminal;
   - a failed check **is** healed through the classifier (the selector may have drifted):
     one regeneration; if the regenerated check fails again, one final classification
     decides **only the terminal kind** (`product_defect` → `ProductDefectError`, anything
     else → `IncurableStepError`); no further regeneration. The rule bounds the
     **generation-loop candidate check**; the healing path of a failed cached check keeps
     its budget-driven regeneration loop. The failed-check regeneration is paid from the
     step's **healing budget** — uniform with the budget-exhaustion rule.

4. **Honest settle polling for transient failures**:
   - `polling_timeout` is the **total settle horizon of a step execution**, measured from
     the **first execution** of the step code (cached code or candidate) — the facade's
     internal waits count inside the window; the window gates repetitions, never kills a
     running attempt;
   - a failure of a **pollable** kind with time remaining → re-execute the same code after
     `polling_delay`, until success or window end; success → the failure was transient,
     the step continues, attempts visible in the log; no LLM budget consumed;
   - window expired (or exhausted by the first execution) → straight to classification and
     the uniform decision table;
   - **pollable kinds** come from a fixed built-in map of driver error kinds (no LLM in the
     decision): not found / not visible / not enabled, timeouts, navigation in flight /
     execution context destroyed, detached/stale element, a failed check (`AssertionError`).
     **Not pollable**: locator ambiguity (the elements are there — waiting will not
     collapse them to one; straight to classification → `fixable` → regeneration) and
     Python-level errors of the step code;
   - polling runs before any costly move — before classification, before the next LLM
     attempt, before the final classification after a verdict-driven regeneration —
     **including replay-strict** (re-executing cached code is execution, not generation);
   - settings: `polling_timeout` (default `None` — polling is opt-in and disabled until a
     positive value is set; `0` is an explicit disable, equivalent to `None`) and
     `polling_delay` (default 0.5 s), in pyproject + env + per-test override, uniform with
     the other settings.

5. **Interactive steering mode**:
   - enablement: the `interactive` setting in `[tool.prettyplay]` (default off) +
     `PRETTYPLAY_INTERACTIVE` env + per-test override via `PrettyConfig` — explicit opt-in,
     an accidentally enabled REPL must not hang CI;
   - trigger: the moment an engine is about to raise `IncurableStepError`, on any incurable
     path; **never** on `product_defect` (a dialog must never repaint a red test green);
     **never** in replay-strict; no interactivity when the LLM is unavailable;
   - dialog: a multi-turn terminal REPL showing the step, code, error, verdict
     (explanation + recommendation), a snapshot fragment, a screenshot path; local commands
     without LLM (full snapshot, screenshot, error, code); each engineer message is
     guidance — a regeneration request carrying a USER GUIDANCE block plus the conversation
     history; the result executes against the live page; success → the step is healed;
     quit / EOF / SIGINT → the original terminal failure is raised; nothing hangs;
   - an interactively healed step is written back to the cache only after a successful
     execution; the guidance is one-shot (logged, not persisted); interactive attempts
     consume no generation/healing budgets;
   - polling never applies inside the REPL: the settle window does not re-arm for
     interactive attempts — the window ended before the REPL opened; a failed interactive
     execution returns to the guidance prompt immediately, no re-execution loop.

## Target API examples

Settings — pyproject, env, per-test override (declarative target surface):

```toml
# pyproject.toml
[tool.prettyplay]
polling_timeout = 6.0   # None (default) — polling off; 0 — explicit disable
polling_delay = 0.5
interactive = false
```

```bash
PRETTYPLAY_POLLING_TIMEOUT=6.0
PRETTYPLAY_POLLING_DELAY=0.5
PRETTYPLAY_INTERACTIVE=1
```

```python
from prettyplay import PrettyConfig, PrettyPlay

test = PrettyPlay(
    cache_key="checkout",
    config=PrettyConfig(polling_timeout=8.0, interactive=True),
)
```

Interactive REPL session (target UX, declarative):

```text
── step "click Checkout" — about to raise IncurableStepError ──────────
intent:   click the checkout button
code:     page.get_by_text("Checkout").click()
error:    TimeoutError: Timeout 10000ms exceeded ... element is not visible
verdict:  fixable — the button is behind the "Terms" modal;
          recommendation: dismiss the modal first, then click.

commands: snapshot | screenshot | error | code | quit
guidance> the modal has id=terms — close it via
          page.get_by_label("Close").click() first
⟳ regenerating with USER GUIDANCE … executing against the live page …
✓ step green — healed step written to the cache
```

## Scope

**In scope:**
- the `fixable` category across the taxonomy, the classification contract and prompts, and
  the verdict/error render paths;
- the uniform decision table on all four paths (generation loop, healing, budget
  exhaustion, failed check);
- recommendation-carrying regeneration requests; the single healing-budget-funded
  regeneration on generation-budget exhaustion; failed-check healing with the final
  terminal-kind classification;
- the settle-polling loop with the fixed pollable-error-kind map against the driver error
  surface, window measured from the first execution, applied before every costly move,
  including replay-strict;
- the `polling_timeout` / `polling_delay` / `interactive` settings: pyproject schema,
  validation, env overrides, per-test merging reaching inside nested groups;
- the interactive terminal REPL with USER GUIDANCE-driven regeneration, local context
  commands, quit/EOF/SIGINT semantics, cache write-back after successful execution;
- the `fixable` label in hook payloads and verdict events (accepted pre-1.0 label break);
- tests for all of the above, per the project conventions.

**Out of scope:**
- per-attempt classification inside the generation loop (rejected: LLM cost; deferred);
- manual code paste by the engineer and hook-based custom UIs — IDE integrations (rejected
  for v1);
- persistence of guidance in the cache file (deferred);
- free-form conversational chat REPL (rejected: every turn must have a measurable
  green/red outcome);
- unbounded regeneration while the classifier says `fixable` (rejected: loop risk);
- changing the strict-mode boundary: replay-strict never generates, no-LLM stays terminal.

## Acceptance Criteria

- A locator-ambiguity failure classified `fixable` triggers a regeneration whose request
  carries the classification `recommendation`, and the healed step can turn green and is
  cached. The same `recommendation` block enters the healing-path `rot` regeneration
  request — every verdict-preceded regeneration request carries it, `rot` and `fixable`
  alike.
- `product_defect` never regenerates on any path and raises `ProductDefectError` — in the
  generation loop, in healing, on budget exhaustion, on a failed check, and in the final
  classification after a failed check regeneration.
- Generation-budget exhaustion with a `rot`/`fixable` verdict grants exactly one extra
  regeneration funded from the healing budget; a repeat failure is terminal without
  reclassification; with any other verdict the exhaustion stays terminal as today.
- A failed **candidate** check (generation loop) gets exactly one regeneration, funded
  from the healing budget; on a second failure the final classification decides only the
  terminal kind (`product_defect` → `ProductDefectError`, else `IncurableStepError`);
  no further regeneration. The healing path of a failed cached check keeps its
  budget-driven regeneration loop.
- With `polling_timeout` set: a pollable-kind failure with time remaining re-executes the
  same code after `polling_delay` until success or window end; success continues the step
  with attempts logged; no LLM budget is consumed; a running attempt is never killed
  mid-flight.
- The polling window starts with the first execution of the step code; the facade's
  internal waits count inside it; the first execution may consume the whole window.
- Locator ambiguity and Python-level errors of the step code are never polled — they go
  straight to classification.
- Polling applies in replay-strict to cached code; replay-strict still never regenerates.
- `polling_timeout = None` (default) and `0` both mean polling disabled; `polling_delay`
  defaults to 0.5 s; all three settings load from pyproject, respond to flat env overrides,
  and merge in explicit per-test overrides, uniform with the existing settings.
- With `interactive` off (default): no REPL ever appears, behavior is unchanged in CI.
- With `interactive` on: the REPL appears exactly at the moment `IncurableStepError` would
  be raised; a guidance turn regenerates with a USER GUIDANCE block plus conversation
  history and executes against the live page; success caches the step; quit/EOF/SIGINT
  raises the original terminal failure; no generation/healing budget is consumed.
- The REPL never triggers on `product_defect`, in replay-strict, or when the LLM is
  unavailable.
- Polling never applies inside the REPL: the settle window does not re-arm for interactive
  attempts; a failed interactive execution returns to the guidance prompt immediately.
- Hook payloads and verdict events carry the `fixable` label; `render_terminal_message`
  renders verdict-driven terminal failures.
- `pytest tests/ -x` passes; `ruff check` is clean.

## Stack

- **Frameworks:** pytest (tests), existing prettyplay package layout — no new frameworks
- **Libraries:** pydantic (settings models, `kw_only=True`), Playwright sync API (driver
  error surface for the pollable map), openai + anthropic SDKs (providers; SDK usage
  patterns unchanged), stdlib `input()`/signal handling for the terminal REPL — no new
  REPL library
- **Infrastructure:** none — no databases, brokers, or services

## External Dependencies

| Component | Usage file | Status |
|-----------|------------|--------|
| playwright | `.goga/usages/cooks/playwright.md` | updated — new "Error kinds — the driver error surface" section |
| pydantic | `.goga/usages/cooks/pydantic.md` | existing — covers the settings patterns |
| openai | `.goga/usages/cooks/openai.md` | existing — SDK patterns unchanged |
| anthropic | `.goga/usages/cooks/anthropic.md` | existing — SDK patterns unchanged |

## Risks and Constraints

- **Pre-1.0 label break**: category-label consumers (hooks, verdict events) see the new
  `fixable` label — accepted in the ADR.
- **Anti-masking deliberately weakened on the failed-check path**: a regenerated check may
  pass where the original honestly failed; guarded by `product_defect` classification,
  exactly one verdict-driven regeneration, and the final classification that can still
  surface `ProductDefectError`.
- **Non-idempotent steps may fire twice**: polling and regeneration re-execute the whole
  step function — accepted (regeneration already re-executes; polling is no riskier and
  cheaper).
- **Polling default is off** (`None`): transient races are not absorbed until opted in; a
  recommended positive value is a design-stage concern (the facade's internal waits count
  inside the window).
- **REPL in CI**: mitigated by the explicit opt-in default; `PRETTYPLAY_INTERACTIVE` must
  not leak into CI environments.
- **Naming collision**: the `interactive` setting vs the existing "Interactive sessions
  (IPython, Jupyter)" documentation section — the setting name is pinned by the ADR; the
  design stage should disambiguate in docs/usages.
- Python 3.10+ only; relative intra-package imports; pydantic `kw_only` models with empty
  defaults (`None` only for explicit absence — `polling_timeout = None` is exactly that).

## Scope Estimate

Single task (no decomposition — engineer's decision). Internal logical order for the design
stage: fixable + decision table + verdicts-into-action first; interactive steering after it
(it changes when the incurable-raise moment occurs); settle polling is independent and can
be designed in parallel.

## Existing Architecture

Impacted cells:

- `prettyplay/failures` — the `fixable` category in the taxonomy; verdict-bearing terminal
  failures; the structured render for verdict-driven terminal messages.
- `prettyplay/llm` — `FailureClassification` wiring of `fixable`: the model validation and
  the provider answer parsing accept the fourth label; the protective incurable fallback
  stays for unknown labels.
- `prettyplay/engine` — the uniform decision table on all paths; recommendation block in
  regeneration requests; budget-exhaustion regeneration; failed-check healing; the polling
  loop before every costly move; the interactive REPL and its incurable-raise trigger;
  the classification instruction gains the fourth label — the instruction lives in this
  cell (`classification_prompt`), not in `prettyplay/llm` (open contract point: exact
  prompt wording) (`StepGenerator`, `StepHealer`, `run_step_code`, `classify_step_failure`).
- `prettyplay/config` — `polling_timeout` / `polling_delay` / `interactive` in the validated
  `[tool.prettyplay]` schema; flat env overrides; explicit per-test merging.
- `prettyplay/cache` — `RunBudgets`: the healing-budget-funded regeneration on
  generation-budget exhaustion and on a failed candidate check; write-back of
  interactively healed steps after successful execution.
- `prettyplay/reporting` — `StepHooks` / verdict events carry the `fixable` label (open
  contract point: payload format).
- `prettyplay/driver` — the fixed pollable-error-kind map against the facade error surface
  (source: the new error-kinds section of the playwright cook; open contract point: the
  concrete mechanism).
- facade `prettyplay` — `PrettyConfig` re-exports the new fields; `StepExecutor` paths
  (strict replay, budgets, per-test overrides).

## Notes

- ADR amended during task formulation (2026-09-12): `polling_timeout` default `None`
  (polling opt-in; `0` — explicit disable); `polling_delay` fixed at 0.5 s. The ADR's
  original "default 10 s" was ambiguous and is superseded.
- Open contract points handed to the design stage (recorded in the ADR): classification
  prompt wiring for `fixable`, hook payload formats, error reason texts, the pollable-map
  mechanism, REPL presentation details (snapshot fragment size, screenshot handling),
  guidance history rendering, validation of a recommended `polling_timeout` value.
- `.goga/usages/cooks/playwright.md` gained the "Error kinds — the driver error surface"
  section during this formulation — the pollable map builds on it.
- Terminology pinned (ADR): **replay-strict** = prettyplay's `strict` replay-only mode;
  **locator ambiguity** = the Playwright strict-mode violation of a locator resolving
  multiple elements.
