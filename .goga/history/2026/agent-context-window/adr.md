# Honest step context window: attempt history and a two-dimension cache gate

## Status

Accepted (2026-09-15) — discovery interview on the `agent-context-window` branch.

## Context and decision

The agent loop lost action code during step regeneration: a step like
`find results for "X"` ended up cached as wait/check-only code with no form
fill — in both the generation/healing flow and interactive steering. The root
cause is not the context window size (the codebase has no token management at
all) but context **composition**: every generation/heal/steer request carries
a fresh aria snapshot of the live page, and that page keeps the side effects
of failed candidates and manual intervention. The model sees an
already-achieved state, rationally omits the action, the candidate runs green
on the contaminated page, and the cache is overwritten with non-replayable
code (proven by the cached duckduckgo artifact whose only trace of the search
is asserting the combobox *already* holds the query). We decided to make the
step's context window honest and to make the cache gate judge adequacy, not
just instruction compliance:

1. **Honest attempt-history context window (core).** Each step carries one
   continuous, verbatim attempt history through generation, healing and
   steering. A record is: the full candidate code, the full error, the
   outcome, and a mechanical `URL before -> after` line. The original cached
   code (when it exists) anchors the history as record #0 — fixing the
   healing-loop drift where the original code was never re-sent after the
   first regeneration (`generator.py` re-binds `existing_code` to the last
   failed candidate). The engine loops gain what the steering dialog already
   has; steering history no longer dies with its dialog.
2. **Honest context inputs in every step request.** The step type
   (action/assertion); the raw step sentence everywhere (the heal path sends
   the casefolded normalization today, `healer.py:89`); and an explicit
   replayability requirement: the current page state may include effects of
   prior attempts or manual intervention — the code must produce the step
   outcome itself and must not rely on the current state.
3. **Two-dimension approve gate.** The single compliance check guarding every
   cache write (generation, healing, steering write-back) is extended from
   instruction-compliance only to instruction-compliance + **step adequacy**:
   "the code accomplishes what STEP says, given the step type and the attempt
   history". The review prompt explicitly instructs the reviewer to use the
   attempt history. A `high` finding blocks the cache write and its reason
   feeds the regeneration ERROR. Today the gate is structurally blind to this
   defect — its prompt forbids judging the step sentence (`compliance.py`:
   "Judge only what the code does against the instructions — not the step
   sentence").

## Considered options

- **Synchronous replay verification before every cache write** (fresh browser
  context, replay previous cached steps, run the candidate) — the only
  deterministic write-time guarantee — **rejected**: it increases
  first-generation time. The existing next-run cache replay plus the healing
  cycle is accepted as the mechanical layer instead: a poisoned entry is
  caught by the next run, and with the honest context the healing converges
  to replayable code.
- **LLM-authored per-attempt state-effect reports** — rejected as unreliable
  self-testimony plus an extra provider call; the mechanical URL
  before/after line is used instead.
- **A separate adequacy-verdict LLM call** — rejected: one extended verdict
  call keeps a single gate point and halves provider calls per cached step.
- **A structural "action steps must contain mutating calls" predicate** —
  rejected as a brittle heuristic (legitimate action steps may be wait-only);
  adequacy stays an LLM judgment fed by honest context.
- **History reset at cycle boundaries (status quo)** — rejected: the honesty
  of the loop depends on one continuous per-step history.

## Consequences

- The product promise ("every later run replays the cached code with no
  LLM") is enforced probabilistically at write time (honest context + gate)
  and deterministically at the next run (replay failure → healing); a bad
  entry may survive until the next run — accepted trade-off.
- The strict JSON verdict semantics evolve: an adequacy finding must be
  expressible with blocking priority — a breaking change to the verdict
  contract, owned by the design stage.
- Prompt mirrors (`.goga/usages/prompts/*`) and the engine / steering / llm
  CODEMANIFESTs change together with this decision.
- No token management, truncation or summarization is introduced; the
  history is bounded by attempt budgets and stays verbatim ("no collapsing,
  no size limits" — the steering philosophy, extended to the engine).

## Acceptance criteria

- **Mandatory CI regression** (fake provider, deterministic, no live site):
  reproduce the contaminated state — candidate #1 mutates the page and fails
  a check; assert that every step request carries the full attempt history
  with URL effects, that the gate blocks action-step code with no action,
  and that the final cached code keeps the action.
- **Live acceptance run**: the duckduckgo example from an empty cache caches
  fill+check code for `find results for ...` in both the plain flow and the
  interactive captcha scenario; the next run is green with no LLM.

## Open questions (design stage)

- The exact JSON shape of an adequacy finding inside the strict compliance
  verdict.
- How the attempt history threads through the engine loops (generation →
  healing → steering) without breaking the provider-port parity.
- Which prompt mirrors and CODEMANIFEST annotations change, and in which
  order.
