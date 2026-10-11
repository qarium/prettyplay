# Change Execution Report — step-code-context-reads

## Summary

Owner-reported defect: cached step code read the execution context (`step_inputs["vars"]["url"]` in the generated example cache) instead of using the values rendered into the step. Root-caused to the unmigrated value contract of the addressing change: the generation/steering prompts taught context reads, the compliance gate blocked the correct literal form for steps with inputs, the runtime bound a context global, and the manifest granted it. Removed the context channel end to end — steps are now self-contained instructions. Owner approved the breaking dimension at the compatibility gate (dialog q2) with one amendment: the prompt carries no awareness that a context exists — the step is a ready instruction.

## Root Cause

See `investigation.md` in `.goga/history/2026/hotfix-step-context/`. The rendered-sentence addressing (`fix-step-cache`) pinned values into the cache address but left the old value channel in place: SYSTEM_PROMPT taught reading `step_inputs` "instead of hardcoding", COMPLIANCE_PROMPT demanded context reads ("hardcoded values cannot replay with new inputs" — a premise the addressing change had already removed), `execution.py` bound `{**memory, "vars": inputs}` into every step-code namespace, and the engine manifest granted the global. For every step whose values arrive through call `vars` the system deterministically produced context-reading cached code — the owner's symptom; the gate rejected the correct self-contained form. Confidence: HIGH.

## Modified Cells

| Cell | Files Modified |
|---|---|
| prettyplay/engine | `execution.py`, `generator.py`, `compliance.py`, `CODEMANIFEST` |
| prettyplay/engine/steering | `steering.py` |
| prettyplay | `executor.py` |
| — (practice source) | `.goga/usages/prompts/step_generation.md` |
| — (user docs) | `docs/reference/step-cache.md` |
| — (tests) | `tests/engine/test_execution.py`, `tests/engine/test_generator.py`, `tests/engine/test_compliance.py`, `tests/test_executor.py` |

## Implemented Changes

| Change | File | Description |
|---|---|---|
| Runtime context removed | `prettyplay/engine/execution.py` | `_step_inputs` ContextVar and `bind_step_inputs` deleted; `run_step_code` namespace is empty — code holds nothing beyond its page argument and allowed imports |
| Five bind sites unwrapped | `generator.py` (×3), `steering.py`, `executor.py` | Generation, healing, funded regeneration, guided execution and replay execute `run_step_code` directly |
| Generation prompt rule replaced | `.goga/usages/prompts/step_generation.md`, `generator.py`, `steering.py` | "The step is a ready instruction: every value it needs is in the STEP sentence — use those values in the code exactly as written"; `step_inputs` occurs nowhere in any prompt |
| Gate rule flipped | `engine/CODEMANIFEST`, `compliance.py` | "The code uses the values of the STEP sentence exactly as the step states them — embedding them in the code is correct, never a finding" |
| Manifest contract swapped | `engine/CODEMANIFEST` | The fixed-form annotation grants no context: self-contained code with rendered values as literals |
| Docs aligned | `docs/reference/step-cache.md` | The context-global paragraph replaced by the self-contained contract |
| Example cache remediated | `example/.prettyplay/cache/tests/test_youtube/test_youtube_search/` | The two defect entries (`b6341eae…`, `c8135598…`) purged — they regenerate under the fixed prompt |

## Tests Added

| Test | File | What It Validates |
|---|---|---|
| `test_step_code_namespace_exposes_no_context` | `tests/engine/test_execution.py` | `step_inputs` references raise `NameError` — no context exists |
| `test_system_prompt_treats_the_step_as_a_ready_instruction` | `tests/engine/test_generator.py` | The ready-instruction rule present; `step_inputs` absent from SYSTEM_PROMPT |
| `test_compliance_prompt_treats_embedded_step_values_as_correct` | `tests/engine/test_compliance.py` | Embedded STEP values are never a finding; `step_inputs` absent from the gate prompt |

Tests modified: `test_template_cache_replays_each_rendered_value_entry` (self-contained per-entry replay), `test_regenerate_invalid_capture_preserves_memory_until_acceptance` (self-contained corrected candidate). The existing mirror-equality tests (practice ↔ engine constant ↔ steering constant; compliance constant ↔ manifest practice) verify the lockstep edits.

## Specification Updates

| Cell | CODEMANIFEST Changes | Usage Changes |
|---|---|---|
| prettyplay/engine | `compliance_prompt` practice rule replaced; fixed-form global annotation rewritten to the self-containment contract | `system_prompt` practice rule replaced (single source; both frozen mirrors changed together) |
| prettyplay/engine/steering | none (mirror-discipline lines remain true) | covered by the shared `system_prompt` practice |
| prettyplay | none | none |

## Validation Results

VERIFIED. `pytest tests/` — 1380 passed, 0 failed (Python 3.12.15 and 3.11.2); `ruff check prettyplay/ tests/` clean; `ruff format --check` — 122 files formatted; `goga lint` — 12 cells, 0 errors; facade import verified; project-wide `step_inputs` scan — only intentional negative test assertions. Full pipeline artifacts: `.goga/history/2026/hotfix-step-context/` (scope-resolution, trace, investigation, plan, compatibility, escalation, test-report, manifest-reconciliation, usage-reconciliation, drift-analysis, validation).

## Compatibility Status

BREAKING — approved by the owner (dialog q2, recorded in `compatibility.md`): context-reading step code changes from working to a loud `NameError`; legacy cache entries with such code self-heal through regeneration outside strict mode, strict replays follow the documented purge-after-upgrade. No public signature, path, format or return-semantics change for well-formed code.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Legacy caches with context reads fail on replay | accepted | Owner-approved; healing regenerates them under the fixed prompt; docs keep the purge note |
| Regeneration imitates context reads from legacy HISTORY records | low | Such attempts fail loudly (`NameError`) and retry within the existing budgets; the prompt carries no context pattern to imitate |
| Live-model adherence to the new prompt | observational | Provider fakes are the project convention; the owner's next example run regenerates the purged entries — the new cache files are the live proof |

## Updated Files

- .goga/usages/prompts/step_generation.md
- docs/reference/step-cache.md
- prettyplay/engine/CODEMANIFEST
- prettyplay/engine/compliance.py
- prettyplay/engine/execution.py
- prettyplay/engine/generator.py
- prettyplay/engine/steering/steering.py
- prettyplay/executor.py
- tests/engine/test_compliance.py
- tests/engine/test_execution.py
- tests/engine/test_generator.py
- tests/test_executor.py
- example/.prettyplay/cache/tests/test_youtube/test_youtube_search/b6341eae7b62f64ce2676cb5ddb7eb84f179253bccf12bf2cbf781e4d7047608.py (deleted, gitignored)
- example/.prettyplay/cache/tests/test_youtube/test_youtube_search/c813559884ec855a0686a440135ae8cb3b6a066f7fa24232b796fd3a32200de1.py (deleted, gitignored)
