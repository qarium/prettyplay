# Change Execution Report — step-code-unused-vars

## Summary

Owner-reported defect (dialog q1): generated step code contains unused variables — `if_count` and `accept_count` in the regenerated example cache entry `c8135598….py`. Root-caused to a missing cleanliness requirement across the whole acceptance path: the generation prompt never teaches that every binding must serve the step, and the compliance gate's adequacy calibration never names dead code as a finding — a hedging candidate (the example's binding «Don't use `if` statement» instruction made the model abandon a conditional mid-way, leaving its ingredients bound and unused) executed green, passed validation and the gate, and was cached. Fixed by teaching the rule in the generation prompt (three synchronized copies), blocking dead weight at the gate as a high adequacy finding (two synchronized copies), stating the clause in the manifest fixed-form annotation, the engine usage and the user docs, pinning both texts with tests, and purging the defective cache entry to regenerate clean. Owner approved the breaking dimension (blocking gate) at the compatibility guard (dialog q2, option A).

## Root Cause

See `investigation.md` in `.goga/history/2026/hotfix-step-unused-vars/`. No cleanliness requirement existed anywhere between the LLM answer and the cache file: `system_prompt` had no binding-economy rule, `compliance_prompt` calibrated adequacy over behavioral over-reach only, `run_step_code` executes dead bindings harmlessly and `validate_step_result` checks only the returned dictionary — so `StepCache.save` persisted dirty candidates verbatim. Evidence: the defective file was regenerated at 18:50 under the current (post-`hotfix-step-context`) prompt. Confidence: HIGH.

## Modified Cells

| Cell | Files Modified |
|---|---|
| prettyplay/engine | `generator.py`, `compliance.py`, `CODEMANIFEST`, `.usages/generation.md` |
| prettyplay/engine/steering | `steering.py` |
| — (practice source) | `.goga/usages/prompts/step_generation.md` |
| — (user docs) | `docs/reference/step-cache.md` |
| — (tests) | `tests/engine/test_generator.py`, `tests/engine/test_compliance.py` |

## Implemented Changes

| Change | File | Description |
|---|---|---|
| Binding-economy rule | `.goga/usages/prompts/step_generation.md`, `generator.py`, `steering.py` | The economy rule extended: «The step must complete exactly what STEP says — nothing more, nothing less: every name the code binds, the code uses» — identical in the practice and both frozen mirrors |
| Dead weight joins the high adequacy calibration | `prettyplay/engine/CODEMANIFEST`, `compliance.py` | «…a check of a fact the step sentence never names, dead weight — a binding the code assigns and never reads serves no part of the step; only high blocks the candidate»; the adequacy rules line names it in the same class — manifest practice and constant byte-equal |
| Fixed-form annotation clause | `prettyplay/engine/CODEMANIFEST` | «…self-contained code that holds nothing beyond its page argument and its allowed imports, every binding used — no dead weight…» |
| Engine usage contract completed | `prettyplay/engine/.usages/generation.md` | «The fixed form» section: «Every name the code binds, the code uses — no dead weight.» |
| Docs aligned | `docs/reference/step-cache.md` | The self-contained contract sentence gains the clause and «carries no dead weight» |
| Example cache remediated | `example/.prettyplay/cache/tests/test_youtube/test_youtube_search/` | The defective entry (`c8135598…`) purged — it regenerates under the corrected prompt |

## Tests Added

| Test | File | What It Validates |
|---|---|---|
| `test_system_prompt_requires_every_binding_used` | `tests/engine/test_generator.py` | The economy rule carries the binding-economy clause, positioned on the rule line; the three-way mirror equality carries the lockstep |
| `test_compliance_prompt_blocks_dead_weight` | `tests/engine/test_compliance.py` | The dead-weight clause sits inside the high calibration (blocking) and in the adequacy rules line; wrap-agnostic assertion; the manifest↔constant mirror test carries the lockstep |

## Specification Updates

| Cell | CODEMANIFEST Changes | Usage Changes |
|---|---|---|
| prettyplay/engine | `compliance_prompt` practice — two insertions; fixed-form global annotation — cleanliness clause | `system_prompt` practice rule extended; `.usages/generation.md` fixed-form section completed |
| prettyplay/engine/steering | none (mirror-discipline lines remain true) | covered by the shared `system_prompt` practice |

## Validation Results

VERIFIED. `pytest tests/` — 1382 passed, 0 failed (Python 3.12.15 and 3.11.2 — the compatibility floor); `ruff check prettyplay/ tests/` clean; `ruff format --check` — 122 files formatted; `goga lint` — 12 cells, 0 errors; facade import verified; all prompt mirrors byte-equal (system ×3, compliance ×2). Full pipeline artifacts: `.goga/history/2026/hotfix-step-unused-vars/` (scope-resolution, trace, investigation, plan, compatibility, escalation, test-report, manifest-reconciliation, usage-reconciliation, drift-analysis, validation).

## Compatibility Status

BREAKING — approved by the owner (dialog q2, recorded in `compatibility.md`): a green candidate carrying unused bindings — cached silently before — becomes a high gate finding: blocked, recorded with the violation text, retried with the grown history; budget exhaustion after repeated violations raises the existing incurable failure naming the finding. No public signature, path, format or return-semantics change; well-formed code and cached replays behave identically.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Live model still emits dead code despite the rule | observational | The gate blocks it; retries target the finding; the owner's next example run regenerates the purged entry — the new cache file is the live proof |
| Gate false-positive flags a needed binding | low | Calibration keeps «confident, material, evident from the code alone»; the verdict sees the complete code |
| Repeated dead-code candidates exhaust the generation budget | low | Loud incurable failure naming the finding — the intended repair semantics; the history carries the violation for diagnosis |
| One-sided mirror edit | low | Mirror-equality tests fail the build on any one-sided edit; all copies changed in one commit |

## Updated Files

- .goga/usages/prompts/step_generation.md
- docs/reference/step-cache.md
- prettyplay/engine/.usages/generation.md
- prettyplay/engine/CODEMANIFEST
- prettyplay/engine/compliance.py
- prettyplay/engine/generator.py
- prettyplay/engine/steering/steering.py
- tests/engine/test_compliance.py
- tests/engine/test_generator.py
- example/.prettyplay/cache/tests/test_youtube/test_youtube_search/c813559884ec855a0686a440135ae8cb3b6a066f7fa24232b796fd3a32200de1.py (deleted, gitignored)
