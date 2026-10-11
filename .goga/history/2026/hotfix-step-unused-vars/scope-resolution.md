# Scope Resolution Report

## Task Summary

Owner-reported defect (dialog q1, this run): generated step code contains unused variables. Concrete evidence: `example/.prettyplay/cache/tests/test_youtube/test_youtube_search/c813559884ec855a0686a440135ae8cb3b6a066f7fa24232b796fd3a32200de1.py` — regenerated 2026-10-11 18:50 under the current (post-`hotfix-step-context`) prompt — binds `dialog`, `if_count`, `accept`, `accept_count` and never uses any of them; the owner names `if_count` and `accept_count`. The step works, but its cached code carries dead weight. The defect lives in the generation system: the generation prompt carries no rule that every binding must serve the step, and the compliance gate's adequacy dimension never names dead code as a finding — so a candidate with unused bindings passes the gate and is cached. Per the project rule «Regenerate Caches, Never Hand-Edit», the fix target is the generation system end to end; the local cache entry is purged to regenerate under the corrected prompt.

## Candidate Cells

| Cell | Reason | Priority |
|---|---|---|
| prettyplay/engine | The defect carriers live here: `SYSTEM_PROMPT` (`generator.py`) teaches no every-binding-used rule; `COMPLIANCE_PROMPT` (`compliance.py`) and its practice in CODEMANIFEST calibrate adequacy without dead code; the CODEMANIFEST fixed-form annotation describes self-containment but not cleanliness | 1 |
| prettyplay/engine/steering | Frozen local copy of `SYSTEM_PROMPT` (`steering.py:35`) — the same missing rule; the mirror-discipline lines pin the lockstep | 2 |

## Included Dependencies

| Cell | Behavioral Relevance |
|---|---|
| prettyplay/llm | The port renders the request texts verbatim; no signature or request-shape change — the fix changes only the prompt text passed in. Participates as the unchanged transport; verified: no dead-code semantics exist there today |

## Excluded Dependencies

| Cell | Exclusion Reason |
|---|---|
| prettyplay/cache | Addressing, storage, budgets are correct; the cache faithfully stores what the generation system accepted. The defect is upstream of the cache |
| prettyplay | Facade: no prompt text, no gate call of its own; executor paths route through the engine |
| prettyplay/engine/renderer | Render product already carries the instruction; nothing in the render contributes to dead code |
| prettyplay/engine/groups | Recovery rows regenerate through the engine loop — the same prompt and gate; no own prompt text (grep-verified) |
| prettyplay/config, prettyplay/driver, prettyplay/failures, prettyplay/reporting, prettyplay/engine/polling | Infrastructural only — no behavioral participation in the defect |

## Usage Relationships

| Usage | Relevance |
|---|---|
| `.goga/usages/prompts/step_generation.md` (`system_prompt` practice of engine and steering) | Single source of the generation prompt; must gain the every-binding-used rule in lockstep with both frozen constants (test-enforced: `tests/test_groups_integration.py:564`, `tests/engine/steering/test_steering.py:353`) |
| engine CODEMANIFEST `compliance_prompt` practice | Single source of the compliance prompt; must name dead code as an adequacy finding in lockstep with the `COMPLIANCE_PROMPT` constant |
| `.goga/usages/prompts/step_cheatsheet.md` (`cheat_sheet` practice) | Teaches the count-forms idiom (`items = …; assert items.count() > 1`) the defective code imitated without the assert — read-only context for the investigation; no change planned |
| `docs/reference/step-cache.md` | States the self-contained contract of cached code (line 42); candidate for a one-line cleanliness alignment — decided at planning |
| `.goga/usages/conventions.md` | Testing conventions for the new/updated tests; no edit |

## Semantic Participation Summary

`prettyplay/engine` owns both defect carriers: the generation prompt (no rule that every binding serves the step) and the compliance gate (adequacy calibration without dead code). `prettyplay/engine/steering` mirrors the generation prompt for guided regeneration. Everything a candidate passes — execution, result validation, gate — accepts dead code today; only the prompt and the gate texts carry the fix. The example cache entry is a gitignored local artifact purged as remediation.

## Final Investigation Scope

- prettyplay/engine (`generator.py`, `compliance.py`, CODEMANIFEST)
- prettyplay/engine/steering (`steering.py`, CODEMANIFEST mirror-discipline lines)
- Practice source: `.goga/usages/prompts/step_generation.md`
- Tests pinning the prompts: `tests/engine/test_generator.py`, `tests/engine/test_compliance.py`, `tests/engine/steering/test_steering.py`, `tests/test_groups_integration.py`
- Local remediation: purge `c8135598….py` from `example/.prettyplay/cache/`

## Scope Risks

- Over-scoping: adding a deterministic AST-based dead-code checker to the engine would be a new runtime mechanism the manifest does not grant — excluded unless the plan explicitly decides otherwise with the owner.
- Under-scoping: fixing only the generation prompt leaves the gate blind — a hedging model still caches dead code; the gate rule is the enforcement half.
- Mirror lockstep: the generation prompt exists in three synchronized copies (practice file + engine constant + steering constant), the compliance prompt in two (manifest practice + constant) — a one-sided edit fails the mirror tests.
- Priority calibration: whether a dead-code finding blocks (high) or warns (medium) decides whether the defect can still reach the cache — a planning decision with compatibility weight (blocked candidates consume generation budget).

## Notes

- The other five example cache entries are clean — every binding is used; only the consent-dialog step carries the pattern, suggesting the model hedged around a conditional popup it could not confirm. The unused `count()` reads also perform real page queries, so the dead code is not free at runtime either.
- The evidence file was regenerated AFTER the `hotfix-step-context` fix (18:50 vs commit 18:43) — the current prompt demonstrably still produces dead code.
