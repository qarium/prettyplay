# Investigation Report

## Task Summary

Owner-reported defect (dialog q1): generated step code contains unused variables — evidence `example/.prettyplay/cache/tests/test_youtube/test_youtube_search/c813559884ec855a0686a440135ae8cb3b6a066f7fa24232b796fd3a32200de1.py`, bindings `if_count` and `accept_count` (plus `dialog` and `accept`, never acted on). The step executes green, passes validation and the compliance gate, and is cached with the dead weight. Requested outcome: the generation system stops producing and caching step code with unused bindings; the local entry regenerates clean (project rule «Regenerate Caches, Never Hand-Edit»).

## Candidate Cells

| Cell | Reason | Priority |
|---|---|---|
| prettyplay/engine | Owns both defect carriers: the generation prompt (no every-binding-used rule) and the compliance gate calibration (dead code invisible to adequacy); CODEMANIFEST fixes both texts as practices | 1 |
| prettyplay/engine/steering | Frozen local copy of the generation prompt for guided regeneration — the same gap; mirror discipline pins lockstep | 2 |

## Tracing Summary

See `trace.md`. Both prompt channels (generation request, compliance verdict request) reach every candidate-producing path: generation loop, healing loop, funded regeneration, steering guidance, group recovery rows — all render `SYSTEM_PROMPT`; all green candidates pass `check_step_compliance` with `COMPLIANCE_PROMPT` before `StepCache.save`. Neither text mentions binding usage; `run_step_code` executes dead bindings harmlessly (`count()` reads the page, nothing fails); `validate_step_result` checks only the result dictionary. Dead code therefore has no rejection point anywhere between the LLM answer and the cache file.

## Data Flow Analysis

The prompt texts are the single lever: practice file → frozen constants → provider requests, verbatim. A rule added to the practice lands in every generation request (three synchronized copies: practice + engine constant + steering constant); a finding calibration added to the manifest practice lands in every verdict request (two synchronized copies: manifest practice + constant). Acceptance data flow: candidate code → execution (no structural checks) → result validation (result only) → gate (findings; today none for dead code) → cache (persisted verbatim, replayed verbatim).

## Manifest Algorithm Analysis

The CODEMANIFEST makes the gate the acceptance authority (generate algorithm step 5: empty findings → publish → save) and defines finding semantics exclusively through the `compliance_prompt` practice. The fixed-form annotation governs the value channel ("self-contained code that holds nothing beyond its page argument and its allowed imports") but is silent on binding usage. The implementation matches the manifest in every traced step — the defect is an omission in the specification texts themselves, not code drifting from the manifest.

## Affected Usages

| Usage | Cell | Classification | Reason |
|---|---|---|---|
| `.goga/usages/prompts/step_generation.md` (`system_prompt`) | prettyplay/engine, prettyplay/engine/steering | DIRECTLY AFFECTED | Gains the every-binding-used rule; both frozen mirrors change in the same commit |
| engine CODEMANIFEST `compliance_prompt` practice | prettyplay/engine | DIRECTLY AFFECTED | Adequacy calibration gains the dead-code finding; constant mirrors in lockstep |
| engine CODEMANIFEST fixed-form global annotation | prettyplay/engine | DIRECTLY AFFECTED | Gains the cleanliness clause of the fixed form |
| `docs/reference/step-cache.md` | — (user docs) | INDIRECTLY AFFECTED | The self-contained contract sentence gains the every-binding-used clause — docs state what the system now enforces |
| `.goga/usages/prompts/step_cheatsheet.md` (`cheat_sheet`) | prettyplay/engine, prettyplay/engine/steering | NOT AFFECTED | The count-forms idiom (`assert items.count() > 1`) is correct as taught; clean entries use it properly — not a defect carrier |

## Rejected Hypotheses

- **The cheat sheet's count idiom teaches the pattern** — rejected: the idiom binds a name AND asserts on it; clean entries (`aa5f52c8`: `assert videos.count() > 1`) use it correctly. The defective code dropped the assert; the idiom is not the cause, the missing rule is.
- **A runtime channel remnant (as in `hotfix-step-context`)** — rejected: the dead bindings read nothing external; no channel exists to read; the code is self-contained, merely carrying unused names.
- **The example's own USER INSTRUCTIONS are the defect** — rejected as the carrier, retained as the trigger context: the example forbids `if` statements (`example/conftest.py` GENERATION_INSTRUCTIONS); facing a consent dialog, the model prepared conditional ingredients (locators, counts) and abandoned them when the conditional was unfollowable. The library accepted the hedge — that acceptance is the defect. Project instructions are binding by design and stay.
- **A deterministic (AST/lint) checker is the missing piece** — deferred to planning as a design option, not a root cause: the manifest deliberately keeps form rules prompt-borne ("no runtime enforcement"); the omission is in the prompt and gate texts.

## Confirmed Root Cause

The generation system specifies no cleanliness requirement for step code, end to end: (1) `system_prompt` (`.goga/usages/prompts/step_generation.md`, mirrored in `generator.py:31-77` and `steering.py:35-81`) never states that every binding must serve the step, so a hedging model may leave unused names; (2) the compliance gate practice (`compliance_prompt`, engine CODEMANIFEST, mirrored in `compliance.py:11-75`) calibrates adequacy over behavioral over-reach only — unused bindings are not a finding, so the gate returns an empty findings list; (3) with execution green and the result contract satisfied, `StepCache.save` persists the candidate verbatim. Evidence chain: the defective file was regenerated at 18:50 — after the `hotfix-step-context` fix (commit `4bdd2db`) — under the current prompt, passed the current gate, and was cached. Confidence grounded in the texts themselves: no rule and no finding calibration mentions binding usage anywhere in the acceptance path.

## Confidence Level

HIGH — deterministic causality with a full evidence chain: the acceptance path is fully traced (request → execution → validation → gate → cache), both prompt texts are read in full, the regenerated artifact post-dates the previous fix, and all other example entries are clean (the pattern is reproducible under hedging conditions, not random).

## Breaking Change Assessment

The planned change (prompt rule + gate finding + manifest clause + doc clause + tests + purge of the local entry):

1. Same-arguments different behavior? **YES** — `check_step_compliance` with identical inputs (candidate carrying dead code) returns different findings after the change: a dead-code candidate that passes today is blocked (high) or warned (medium) after it. `generate`/`regenerate`/`steer` with identical inputs may take the blocked-attempt path instead of caching. This is the intended repair, and by the project policy it is a breaking dimension.
2. Existing file paths change? **NO** — no module, practice or doc path moves.
3. Output format change? **NO** — the gate answer format (JSON findings list), the attempt record shape and the cache file format are unchanged; new finding texts ride the existing fields.
4. Return value semantics change? **NO** for signatures and types; the *content* of findings for dead-code candidates changes (covered by Q1).
5. Manifest-defined guarantees altered? **YES** — the `compliance_prompt` practice and the fixed-form annotation change their normative text (the practice texts are the guarantees). Well-formed clean code keeps every guarantee.
6. Existing tests break? **NO** — the full suite (1380 tests) passes on the current tree; the prompt-pinning tests assert substrings and rule order among existing markers, which the edit preserves (new rule sits after the marked rules); new tests pin the added rule.

**BREAKING CHANGE DETECTED** (Q1, Q5) — per the pipeline and the project rule «Breaking-Change Authorization Gate», the pipeline halts at the compatibility guard; only explicit owner approval of the presented plan and escalation report lifts the stop.
