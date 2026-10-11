# Change Plan

## Task Classification

bugfix — remove the execution-context channel from generated step code: steps become self-contained, using only the values rendered into them (owner-reported defect; see `investigation.md`).

## Affected Cells

| Cell | Files to Modify | What Changes |
|---|---|---|
| prettyplay/engine | `execution.py` | Delete `_step_inputs` ContextVar and `bind_step_inputs`; `run_step_code` builds the step namespace with no context global |
| prettyplay/engine | `generator.py` | SYSTEM_PROMPT rule replaced: self-contained values, no context reads; unwrap the three `bind_step_inputs` sites (generation loop, healing loop, funded regeneration) |
| prettyplay/engine | `compliance.py` | COMPLIANCE_PROMPT rule flipped: embedded literals are correct; context reads cannot execute — high adequacy finding |
| prettyplay/engine | `CODEMANIFEST` | `compliance_prompt` practice rule flipped; global annotation :147 rewritten to the self-containment contract |
| prettyplay/engine/steering | `steering.py` | Frozen SYSTEM_PROMPT copy updated identically; unwrap the guided-execution bind |
| prettyplay | `executor.py` | Drop `bind_step_inputs` import and the replay-path binding |
| practice source | `.goga/usages/prompts/step_generation.md` | The teaching rule replaced with the self-containment rule (single source of SYSTEM_PROMPT) |
| docs | `docs/reference/step-cache.md` | The `step_inputs` paragraph (42-45) rewritten to the self-contained contract |

## Root Cause Analysis

The rendered-sentence addressing change did not migrate the step-code value contract: generation/steering prompts still teach reading the `step_inputs` context global, the compliance gate still enforces context reads for input-influenced steps (blocking the correct literal form), the runtime still binds and exposes the context, and the engine manifest still grants it. Deterministically, steps whose values arrive through call `vars` get context-reading cached code — the owner's symptom.

## Trace Summary

All five execution paths (generation `generator.py:418`, healing `:545`, funded regeneration `:847`, steering `steering.py:323`, replay `executor.py:191`) bind the context around `run_step_code`, whose namespace exposes it (`execution.py:42`). Removing the bind at the source (`execution.py`) plus the five call sites removes the channel from every path at once.

## Change Strategy

1. Rewrite the value rule in `.goga/usages/prompts/step_generation.md` (owner amendment, dialog q2): the prompt is not aware that a context exists — the rule states only that the step is a ready instruction and every value it needs is in the STEP sentence, used in the code exactly as written. No mention of context, globals, `step_inputs` or their absence; no safety-core addition.
2. Apply the identical text to the frozen mirrors: `generator.py` SYSTEM_PROMPT and `steering.py` SYSTEM_PROMPT (test-enforced equality — both change in lockstep).
3. Replace the gate rule in the engine CODEMANIFEST `compliance_prompt` practice and its constant mirror `compliance.py`: the code uses the values of the STEP sentence exactly as the step states them — embedding them in the code is correct, never a finding. No context mention; the term `step_inputs` disappears from every prompt.
4. Rewrite the engine CODEMANIFEST global annotation (:147): the fixed form works through the standard Playwright sync API with its rendered values embedded as literals — self-contained; no runtime context, no globals beyond the page argument and the allowed imports.
5. Delete `_step_inputs`/`bind_step_inputs` from `execution.py`; `run_step_code` namespace becomes `{}`. Unwrap the five bind sites (behavior otherwise unchanged — settle, validation, gate, publication untouched).
6. Rewrite the `step_inputs` paragraph in `docs/reference/step-cache.md` to the self-contained contract.
7. Update the three tests pinning the old behavior; add contract tests for the new one (below).
8. Purge the two local defect entries in `example/.prettyplay/cache/tests/test_youtube/test_youtube_search/` (gitignored artifacts; they regenerate with the fixed prompt).
9. Docs carry no new purge note beyond the existing one: legacy cache entries containing context reads fail loudly on replay and self-heal outside strict mode — the documented purge-after-upgrade procedure applies.

## Specification Impact

- `prettyplay/engine/CODEMANIFEST`: `Usages.compliance_prompt` (rule text), global `Annotations` (fixed-form paragraph). No type signatures, locations or imports change.
- `prettyplay/engine/steering/CODEMANIFEST`: no text change (it references the practice by mirror discipline, verified — no `step_inputs` mentions).
- No other manifest touched.

## Usage Impact

- `.goga/usages/prompts/step_generation.md` — one rule replaced, one safety-core phrase added (the single source; mirrors follow).
- `docs/reference/step-cache.md` — one paragraph rewritten; the section's internal contradiction (values pinned by address vs code tracking live context) is gone.
- Cell usages (`engine/.usages/generation.md`, `healing.md`, `steering/.usages/steering.md`) — verified free of `step_inputs`; snippets already show literal-embedding code; re-verified at the usage-reconciliation step.

## Compatibility Verification

NOT backward compatible. `run_step_code(code, page)` for code reading `step_inputs` works today and raises `NameError` after the change; legacy cache entries with context reads fail replay loudly (healing regenerates them outside strict mode). The manifest guarantee granting the context global (the defect carrier itself) is removed. Per the breaking-change policy the pipeline halts at the compatibility guard; the escalation report is presented to the owner — only the owner can approve proceeding.

## Test Strategy

Modified:
- `tests/engine/test_execution.py` — drop the `bind_step_inputs` import; replace `test_cached_code_reads_fresh_bindings_on_each_execution` with `test_step_code_namespace_exposes_no_context` (code referencing `step_inputs` raises `NameError`; the execution otherwise unaffected).
- `tests/engine/test_generator.py` — the healing-path `valid` candidate stops asserting through `step_inputs` (returns its result directly; the memory-publication assertions unchanged).
- `tests/test_executor.py` — `test_template_cache_replay_uses_current_call_inputs` becomes the self-contained replay: two rendered values → two entries, each replays its own literal-embedding code.

Added:
- Prompt contracts: SYSTEM_PROMPT contains the self-containment rule and no `step_inputs` occurrence (engine); COMPLIANCE_PROMPT states literal embedding is never a finding and contains no `step_inputs` occurrence; steering copy covered by the existing mirror-equality tests plus the same containment assertion.
- The existing mirror-equality tests (`test_groups_integration.py:564`, `test_steering.py:353`) verify the three-way lockstep after the edit.

Unchanged suites must stay green: 1378 cases, `pytest tests/ -x`; `ruff check prettyplay/`; `ruff format --check`; `goga lint`.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Breaking legacy caches that read the context | Certain (intended) | Loud replay failure outside strict mode; strict runs need the documented purge | Owner approval at the compatibility gate; healing self-regenerates defect entries; purge note already in docs |
| Regeneration imitates `step_inputs` from legacy HISTORY records | Low | A wasted attempt, then the rule and the NameError correct it | The rule explicitly names the failure; such attempts fail loudly and are retried within existing budgets |
| One-sided prompt mirror edit | Low | Mirror-equality tests fail | Tests run in the same change; three-way edit is one step of the strategy |
| Wording drift between the three SYSTEM_PROMPT copies | None | — | Copies are byte-identical and test-enforced |
| Floor compatibility (Python 3.10) | None | Removal-only runtime change; no version-sensitive constructs | Suite runs on 3.12; requires-python floor unaffected |
