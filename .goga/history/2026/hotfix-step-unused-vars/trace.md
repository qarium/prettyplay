# Trace Report

## Call Flow

Generation path (where the defective `c8135598….py` was produced, 2026-10-11 18:50):
```
PrettyPlay.step (facade scenario.py)
  → StepExecutor.execute (executor.py)
    → StepCache.load(identity) → miss
    → StepGenerator.generate → _generation_loop
        → provider.generate_step_code(prompt=SYSTEM_PROMPT, …)      ← generator.py:909 — no every-binding-used rule
        → settle(run_step_code, code, page, window)                 ← execution.py:6 — compiles and runs whatever parses
        → validate_step_result(prepared, result)                    ← checks the RESULT contract only
        → check_step_compliance(…, COMPLIANCE_PROMPT, …)            ← compliance.py:116 — adequacy never names dead code
        → StepCache.save(CachedStep(code=code))                     ← dead code persisted
```

Healing path: `StepHealer.heal → StepGenerator.regenerate → _healing_loop` — the same prompt, the same gate (`generator.py:566`), the same store.
Funded regeneration: `_funded_regeneration` — the same prompt and gate (`generator.py:863`).
Steering path: `StepSteering.steer → _guided_request(prompt=SYSTEM_PROMPT local copy, steering.py:553) → run_step_code → check_step_compliance (steering.py, gate call per manifest algorithm step 7) → write-back`.
Group recovery: rows regenerate through the engine loop — the same prompt and gate; no own copies.

## Data Flow

`SYSTEM_PROMPT` flows from `.goga/usages/prompts/step_generation.md` (single source) into two frozen constants — `generator.py:SYSTEM_PROMPT` and `steering/steering.py:SYSTEM_PROMPT` — and from there verbatim into every generation/regeneration/guided request through `provider.generate_step_code(prompt=…)`. `COMPLIANCE_PROMPT` flows from the engine CODEMANIFEST `compliance_prompt` practice into `compliance.py:COMPLIANCE_PROMPT` and verbatim into every verdict request through `provider.check_instruction_compliance(prompt=…)`. Candidate code flows: provider answer → `settle(run_step_code, …)` (execution — dead bindings evaluate, `count()` reads hit the page, nothing fails) → `validate_step_result` (result dictionary only) → gate (findings — dead code invisible today) → `StepCache.save` (persisted as the cached step). The cache replays the identical text later; nothing between request and cache ever judges binding usage.

## Manifest Algorithm Mapping

- engine CODEMANIFEST `StepGenerator.generate` algorithm step 5: "Gate the candidate through `check_step_compliance`… An empty findings list — publish… save it to the cache" — the gate is the acceptance authority; its practice text (`compliance_prompt`) defines what a finding is; dead code is absent from both calibrations. Code matches the manifest — the manifest itself omits the cleanliness requirement.
- engine CODEMANIFEST global annotation (fixed form of step code): "…self-contained code that holds nothing beyond its page argument and its allowed imports" — describes the value channel (previous fix), says nothing about bindings the code never uses.
- engine CODEMANIFEST `system_prompt` practice ↔ `generator.py`/`steering.py` mirrors — equality test-enforced (`tests/test_groups_integration.py:564`, `tests/engine/steering/test_steering.py:348-353`); the practice carries no every-binding-used rule, so neither mirror does.
- steering CODEMANIFEST mirror-discipline annotations: "The system prompt sent to the provider is the frozen local mirror of `system_prompt` — the mirror and the practice change together" — lockstep obligation for any edit.
- `run_step_code` (execution.py): "Execute step code of the fixed form" — by design no structural enforcement (manifest: "a prompt rule carried by `system_prompt`, no runtime enforcement").

## Cross-Cell Traversals

| Source Cell | Target Cell | Type | Path |
|---|---|---|---|
| prettyplay/engine | prettyplay/llm | data | SYSTEM_PROMPT / COMPLIANCE_PROMPT texts → `provider.generate_step_code` / `check_instruction_compliance` |
| prettyplay/engine/steering | prettyplay/engine | call | steering imports `run_step_code`, `check_step_compliance`; local SYSTEM_PROMPT mirrors the engine constant (test-enforced equality) |
| prettyplay/engine/steering | prettyplay/llm | data | local SYSTEM_PROMPT → guided request |
| prettyplay/engine | prettyplay/cache | call | `StepCache.save` persists the gated candidate — the acceptance point dead code passes through |
| prettyplay (facade) | prettyplay/engine | call | executor routes generation/healing/steering; no prompt text of its own |

## Inconsistencies

| Type | Location | Expected | Actual |
|---|---|---|---|
| Prompt rule gap | `.goga/usages/prompts/step_generation.md` Rules (mirrored in `generator.py:31-77`, `steering.py:35-81`) | The prompt states the economy of the step code: every binding serves the step | No rule addresses binding usage — the model may hedge and leave unused names; the regenerated `c8135598` (post-`hotfix-step-context`) proves the current prompt produces them |
| Gate calibration gap | engine CODEMANIFEST `compliance_prompt` + `compliance.py:27-50` (Priority calibration — high; Rules) | Adequacy names the material over-reach shapes a candidate may carry | The calibration enumerates behavioral over-reach (assertion changing state, trailing checks) but never dead weight — unused bindings pass the gate and cache |
| Manifest annotation gap | engine CODEMANIFEST global annotation (fixed form of step code) | The fixed-form contract states the cleanliness dimension of cached code | Annotation covers the value channel only (self-contained literals), silent on dead bindings |
| Local remediation | `example/.prettyplay/cache/.../c8135598….py` | Regenerated clean under a corrected prompt | Carries 4 dead bindings (`dialog`, `if_count`, `accept`, `accept_count`); gitignored local artifact |

## Trace Graph

```
step_generation.md (practice, single source)
   │  (frozen mirror, test-enforced equality)
   ├──► generator.SYSTEM_PROMPT ──► provider.generate_step_code ──► candidate code
   └──► steering.SYSTEM_PROMPT  ──► provider.generate_step_code ──► guided candidate
                                                                          │
                                              run_step_code (executes; dead bindings harmless)
                                                                          │
                                              validate_step_result (result contract only)
                                                                          │
engine CODEMANIFEST compliance_prompt ──► compliance.COMPLIANCE_PROMPT ──► provider verdict
   (adequacy: no dead-code finding)          (mirror)                    │ findings=[] for dead code
                                                                          ▼
                                                              StepCache.save  ← defect lands in the cache
```
