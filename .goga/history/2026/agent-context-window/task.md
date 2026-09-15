# Honest step context window: attempt history and a two-dimension cache gate

## Current State

The agent loop loses action code during step regeneration: a step like
`find results for "X"` ends up cached as wait/check-only code with no form
fill — in both the generation/healing flow and interactive steering (proven
by the cached duckduckgo artifact whose only trace of the search is asserting
the combobox *already* holds the query). The root cause is context
composition, not context window size:

- Every generation/heal/steer request carries a fresh aria snapshot of the
  live page, and the page keeps the side effects of failed candidates and
  manual intervention. The model sees an already-achieved state, rationally
  omits the action, the candidate runs green on the contaminated page, and
  the cache is overwritten with non-replayable code.
- No attempt history exists: `prettyplay/engine/generator.py` re-binds
  `existing_code` to the last failed candidate, so every request carries
  exactly one code+error pair and the original cached code is lost after the
  first regeneration.
- The step type (`action`/`assertion`) is known to the executor and enters
  `StepIdentity` only — it never reaches any LLM request.
- The heal path sends the casefolded normalization instead of the raw step
  sentence (`prettyplay/engine/healer.py:89`).
- The single cache-write gate (`prettyplay/engine/compliance.py`) checks
  instruction compliance only; its prompt explicitly forbids judging the step
  sentence; it sees no attempt history and no step type.
- The steering dialog owns a turn history (engineer message + code + outcome)
  that dies with the dialog and carries no URL-effect lines; engine requests
  pass `guidance_history=[]` and `page_url=None`.

## Description

Implement the accepted ADR
(`.goga/history/2026/agent-context-window/adr.md`):

1. **One continuous, verbatim per-step attempt history** threaded through
   generation, healing and steering. A record: the full candidate code, the
   full error, the outcome, and a mechanical `URL before -> after` line. The
   original cached code (when it exists) anchors the history as record #0.
   No collapsing, no size limits — the history is bounded by attempt budgets
   only. The engine loops gain what the steering dialog already has; the
   steering history no longer dies with its dialog — one shared per-step
   history.
2. **Honest inputs in every step request**: the step type
   (action/assertion); the raw step sentence everywhere (the heal path sends
   the casefolded normalization today); an explicit replayability
   requirement — the current page state may include effects of prior
   attempts or manual intervention, and the code must produce the step
   outcome itself without relying on the current state.
3. **A two-dimension approve gate**: the single compliance check guarding
   every cache write (generation, healing, steering write-back) is extended
   from instruction-compliance only to instruction-compliance + **step
   adequacy** — "the code accomplishes what STEP says, given the step type
   and the attempt history". The review prompt explicitly instructs the
   reviewer to use the attempt history. A `high` finding blocks the cache
   write and its reason feeds the regeneration ERROR. Breaking change to the
   strict JSON verdict contract.

## Scope

**In scope:**

- `prettyplay/llm` — the port (`generate_step_code`,
  `check_instruction_compliance`), the models (`ComplianceFinding`,
  `parse_compliance_verdict`), and both SDK implementations (openai,
  anthropic) in full parity
- `prettyplay/failures` — conditionally: only if the verdict-contract change
  requires new parse-failure semantics of `ComplianceVerdictError`
  (see Existing Architecture)
- `prettyplay/engine` — the attempt-history concept, the generator loops
  (generation, healing, funded regeneration), the healer (raw step
  sentence), the extended gate
- `prettyplay/engine/steering` — the dialog joins the shared attempt
  history; per-attempt URL lines
- `prettyplay` root — the executor threads `step_type` and the raw step
  sentence into the engine calls
- Prompt mirrors: `.goga/usages/prompts/generation.md` together with the
  frozen `SYSTEM_PROMPT`/`CHEAT_SHEET` constants of the engine and steering
  cells; the compliance gate prompt (the practice of the engine CODEMANIFEST)
- CODEMANIFESTs of all touched cells
- The mandatory CI regression on a fake provider (contaminated-page
  scenario)

**Out of scope (rejected in the ADR):**

- Synchronous replay verification before every cache write
- LLM-authored per-attempt state-effect reports
- A separate adequacy-verdict LLM call
- A structural "action steps must contain mutating calls" predicate
- Token management, truncation, or summarization of the history

## Acceptance Criteria

- **CI regression (fake provider, deterministic, no live site):** reproduce
  the contaminated state — candidate #1 mutates the page and fails a check;
  assert that every step request carries the full attempt history with URL
  effects, the step type and the raw step sentence (including the heal
  path), that the gate blocks action-step code with no action, and that
  the final cached code keeps the action.
- **Live acceptance run:** the duckduckgo example from an empty cache caches
  fill+check code for `find results for ...` in both the plain flow and the
  interactive captcha scenario; the next run is green with no LLM.
- **Provider parity:** both SDK implementations render the new inputs
  identically (the existing parity tests extended to the new request parts).
- **Frozen-mirror discipline:** every prompt mirror file and its frozen code
  constant change together; `goga lint` passes.

## Stack

- **Language:** Python 3.10+ (the mandatory `conventions` practice)
- **Frameworks/Libraries:** pydantic (data models), playwright (browser
  automation), openai SDK + anthropic SDK (the two provider implementations)
- **Testing:** pytest with fake providers (`tests/`); live acceptance on the
  duckduckgo example (`example/tests/test_duckduckgo.py`)
- **Infrastructure:** none — no new components

## External Dependencies

| Component | Usage file | Status |
|-----------|------------|--------|
| pydantic | `.goga/usages/cooks/pydantic.md` | existing |
| playwright | `.goga/usages/cooks/playwright.md` | existing |
| openai SDK | `.goga/usages/cooks/openai.md` | existing |
| anthropic SDK | `.goga/usages/cooks/anthropic.md` | existing |
| generation prompt mirror | `.goga/usages/prompts/generation.md` | updated in place |
| cheat sheet mirror | `.goga/usages/prompts/cheatsheet.md` | existing — touched only if its wording must change |

No new usage files; no new cooks.

## Risks and Constraints

- **Breaking change to the verdict contract:** an adequacy finding must be
  expressible with blocking priority inside the strict compliance verdict;
  the parse path must not silently accept old-shaped verdicts as compliant.
- **Open design questions** (owned by the design stage, not fixed here): the
  exact JSON shape of an adequacy finding, how the attempt history threads
  through the engine loops without breaking provider-port parity, and the
  ordering of prompt-mirror and CODEMANIFEST updates.
- **Probabilistic write-time enforcement:** a poisoned entry may survive
  until the next run catches it via replay failure + healing — the accepted
  trade-off of the ADR.
- **Verbatim history growth** is bounded by attempt budgets only — no
  truncation is allowed (the steering philosophy extended to the engine).
- **Authored-reason contract:** terminal error reasons stay colon-free and
  first-line-safe when adequacy findings feed them.

## Scope Estimate

Single task (confirmed with the user). One cohesive defect fix around the
step cycle: ~9 production modules across the touched cells, up to 2 prompt
mirrors with their frozen constants (the cheat sheet conditional), 4–5
CODEMANIFESTs (failures conditional), unit/integration tests plus the
mandatory fake-provider CI regression. The three ADR decisions are mutually dependent
— the adequacy gate consumes the attempt history, the prompts describe
inputs the port must carry, and provider parity forces both SDKs to move
with the port — so a decomposition would produce parts with no independent
value.

## Existing Architecture

Affected cells (bottom-up):

- `prettyplay/llm` — the port signature, the verdict models, both SDK
  implementations; parity is contractual
- `prettyplay/failures` — the verdict semantics evolve; touched only if the
  parse-failure semantics of `ComplianceVerdictError` must change with the
  verdict contract
- `prettyplay/engine` — the attempt history, the generator loops, the
  healer, the gate
- `prettyplay/engine/steering` — joins the shared history
- `prettyplay` (root) — the executor threading of the step type and the raw
  step sentence

Project practices touched: `.goga/usages/prompts/generation.md` and the
compliance-prompt practice of the engine CODEMANIFEST.

## Notes

- Source ADR: `.goga/history/2026/agent-context-window/adr.md` (accepted
  2026-09-15, discover stage).
- Formulation decisions (file-based dialog, q1–q4): formulation approved as
  proposed; no target-API code examples in the task — exact shapes belong to
  the design stage; no new external dependencies or usage-cook files, the
  prompt mirrors are updated in place as part of the task; single task, no
  decomposition.
- The steering turn history is unified with the engine attempt history: the
  dialog appends to the one per-step history instead of owning a dialog-local
  copy.
