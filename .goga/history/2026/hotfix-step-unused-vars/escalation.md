# Breaking Change Escalation Report

## Change

The generation system gains a cleanliness requirement end to end: the generation prompt teaches «every name the code binds, the code uses», the compliance gate names dead weight (bindings assigned and never read) as a high adequacy finding, the manifest fixed-form annotation and the user docs state the clause, prompt-pinning tests cover both texts, and the defective local cache entry is purged to regenerate clean.

## Why it breaks

`check_step_compliance` — same arguments — returns a different verdict for candidates carrying unused bindings: empty findings (pass, cache) today, a high finding (block, retry) after the change. `StepGenerator.generate`/`regenerate` and `StepSteering.steer` consequently take the existing compliance-blocked path for dirty candidates instead of caching them; budget exhaustion after repeated violations raises `IncurableStepError`. This is precisely the defect report turned into enforced behavior: dead code must not reach the cache.

## What does NOT break

No public signature, return type, default, file path, output format, error contract or manifest algorithm step changes. Well-formed clean code behaves byte-identically. Cached replays never pass the gate — existing caches keep replaying untouched. The full test suite passes without modification on the current tree; new tests only pin added prompt text.

## The decision the owner must make

- **High (blocking) — the plan's design.** Dead code never caches. Cost: a dirty candidate consumes its generation attempt and retries within existing budgets; a model that repeatedly hedges can exhaust the budget and fail the step loudly with the finding named — loud failure instead of silent dirt, the same trade the owner approved for context-reading code in `hotfix-step-context`.
- **Medium (warn-only).** Not breaking: dirty candidates still cache, the WARNING log names the findings. The reported defect stays reachable — the owner's symptom file would regenerate with the same dead weight.

## Recommendation

High (blocking). A warn-only gate cannot fix the reported defect; the blocking design uses exclusively existing mechanisms (high-finding path, attempt budgets, history-carried violations) and preserves every well-formed path.

## Status

Pipeline STOPPED at the compatibility guard per the project rule «Breaking-Change Authorization Gate». Proceeding requires explicit owner approval of the blocking design (or an explicit instruction to switch to warn-only).
