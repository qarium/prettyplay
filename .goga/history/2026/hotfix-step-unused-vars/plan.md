# Change Plan

## Task Classification

bugfix — the generation system accepts and caches step code carrying unused bindings; both the teaching (generation prompt) and the enforcement (compliance gate) dimensions are unspecified for code cleanliness.

## Affected Cells

| Cell | Files to Modify | What Changes |
|---|---|---|
| prettyplay/engine | `.goga/usages/prompts/step_generation.md` (practice source), `generator.py`, `compliance.py`, `CODEMANIFEST` | Generation prompt gains the every-binding-used rule; compliance prompt names dead weight as a blocking adequacy finding; manifest fixed-form annotation gains the cleanliness clause |
| prettyplay/engine/steering | `steering.py` | Frozen local SYSTEM_PROMPT mirror updated in lockstep (no manifest text change — the mirror-discipline lines already pin it) |
| — (user docs) | `docs/reference/step-cache.md` | The self-contained contract sentence gains the every-binding-used clause |
| — (tests) | `tests/engine/test_generator.py`, `tests/engine/test_compliance.py` | Prompt pins for the two new rules |
| — (local remediation) | `example/.prettyplay/cache/tests/test_youtube/test_youtube_search/c813559884ec855a0686a440135ae8cb3b6a066f7fa24232b796fd3a32200de1.py` | Purged (gitignored artifact) — regenerates under the corrected prompt |

## Root Cause Analysis

No cleanliness requirement exists anywhere in the acceptance path. The `system_prompt` practice (mirrored in `generator.py` and `steering.py`) never states that every binding must serve the step; the `compliance_prompt` practice (mirrored in `compliance.py`) calibrates adequacy over behavioral over-reach only — unused bindings are invisible to the gate. Execution runs dead bindings harmlessly, result validation checks only the returned dictionary, so `StepCache.save` persists the candidate verbatim. Trigger context: the example project's binding instruction «Don't use `if` statement» makes a model facing a conditional obstacle (the consent dialog) abandon its conditional mid-way, leaving the prepared ingredients (`dialog`, `accept`, `if_count`, `accept_count`) as dead weight — and the system had no rule to reject it. Evidence: the file was regenerated under the current prompt at 18:50, after the `hotfix-step-context` fix.

## Trace Summary

Both prompt channels reach every candidate-producing path (generation loop, healing loop, funded regeneration, steering guidance, group recovery rows); all green candidates pass `check_step_compliance` before `StepCache.save`. The two practice texts are the single levers; each exists in synchronized frozen copies (generation prompt ×3, compliance prompt ×2) enforced equal by tests.

## Change Strategy

1. **Generation prompt rule** (`.goga/usages/prompts/step_generation.md` + `generator.py:SYSTEM_PROMPT` + `steering.py:SYSTEM_PROMPT`): extend the step-economy rule — «The step must complete exactly what STEP says — nothing more, nothing less» — with the binding-economy clause: «every name the code binds, the code uses». Positive phrasing per the project rule «Positive-Only Prompt Rules»; no new input, no channel awareness.
2. **Gate calibration** (engine CODEMANIFEST `compliance_prompt` + `compliance.py:COMPLIANCE_PROMPT`): dead weight joins the high adequacy calibration — a binding the code assigns and never reads is material weight the step never asked for, evident from the code alone (confident, hence high; only high blocks); the adequacy rules line names it in the same class as extra actions and extra checks.
3. **Manifest annotation** (engine CODEMANIFEST fixed-form global annotation): the fixed form of step code gains «every binding the code makes, the code uses — no dead weight».
4. **Docs rider** (`docs/reference/step-cache.md`): the self-contained contract sentence gains the same clause, so user docs state what the gate enforces.
5. **Tests**: pin the new prompt rule in both frozen mirrors (equality tests carry the lockstep) and the gate calibration in the constant; keep the existing rule-order asserts green (the edits touch the economy rule and the high-calibration list, no marked order changes).
6. **Purge** the defective local cache entry; it regenerates under the corrected prompt on the owner's next example run.

## Specification Impact

- engine CODEMANIFEST `compliance_prompt` practice: two textual insertions (high calibration + adequacy rules line); the frozen constant mirrors verbatim.
- engine CODEMANIFEST global Annotations (fixed form of step code): one clause appended.
- No signatures, locations, types or algorithms change; the manifest's authority structure (gate = acceptance authority) is untouched — the gate's normative text defines one more finding shape.

## Usage Impact

- `.goga/usages/prompts/step_generation.md`: one rule extended; the header description and everything else unchanged.
- `docs/reference/step-cache.md`: one clause in the self-contained contract sentence.
- `.goga/usages/prompts/step_cheatsheet.md`: unchanged — the count-forms idiom is correct as taught.
- Cell-level `.usages/` of engine and steering: unchanged (they describe API consumption, not prompt content).

## Compatibility Verification

**Not backward compatible in one dimension, by intent**: a candidate carrying unused bindings — cached silently today — becomes a high gate finding: the attempt is blocked, recorded with the violation text, retried with the grown history (the existing compliance-blocked path); budget exhaustion after repeated dead-code candidates raises `IncurableStepError` naming the finding. No public signature, path, format or return-semantics change; well-formed clean code behaves identically; existing caches replay untouched (the gate never runs on replayed code). Per the project rule «Breaking-Change Authorization Gate» the pipeline halts at the compatibility guard and proceeds only on explicit owner approval — the guard presents this dimension with the alternative (medium, warn-only — keeps the defect reachable in the cache) so the owner decides with full information.

## Test Strategy

- `tests/engine/test_generator.py` (TestPromptConstants): new pin — the economy rule carries the every-binding-used clause in `SYSTEM_PROMPT`; position after «The step must complete exactly what STEP says» on the same rule line. The existing mirror-equality asserts (practice == engine constant == steering constant, `tests/test_groups_integration.py:564`, `tests/engine/steering/test_steering.py:353`) carry the lockstep to the other two copies.
- `tests/engine/test_compliance.py`: new pin — the dead-weight clause present in `COMPLIANCE_PROMPT` inside the high calibration (before «only high blocks the candidate») and in the adequacy rules line; the manifest↔constant lockstep stays covered by the existing substring asserts plus `goga lint`.
- Full suite `pytest tests/ -x` and `ruff check prettyplay/ tests/` green; `ruff format --check` clean; `goga lint` clean (Formatting Completion Gate).

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Live model still emits dead code despite the rule | medium | low — the gate blocks it; retries target the finding; budget bounds the loop | The gate rule is the enforcement half; the owner's next example run is the live proof |
| Gate false-positive: flags a binding as unused that the code needs | low | medium — a good candidate blocked, one attempt spent | Calibration wording keeps «confident, material, evident from the code alone»; the LLM sees the complete code |
| Blocked dead-code candidates exhaust the generation budget | low | medium — step raises incurable instead of caching dirty code | The failure is loud and names the finding — the intended repair semantics; history carries the violation for diagnosis |
| One-sided mirror edit (3 prompt copies + 2 gate copies) | low | high — mirror tests fail | Equality tests fail the build on any one-sided edit; edit all copies in one commit |
| Legacy caches carry dead code | certain | none — replays are ungated by design | Out of scope; the purge-after-upgrade note already governs incompatible entries; the local defective entry is purged |
