# Usage Reconciliation Report

## Classification

| Usage File | Classification |
|---|---|
| `.goga/usages/prompts/step_generation.md` | DIRECTLY AFFECTED — the generation prompt practice; the economy rule gained the binding-economy clause (updated in implementation) |
| `prettyplay/engine/.usages/generation.md` | DIRECTLY AFFECTED — «The fixed form» section states the generated-code contract; gained the same clause |
| `docs/reference/step-cache.md` | DIRECTLY AFFECTED — user docs state the self-contained contract; gained the clause (updated in implementation) |
| `prettyplay/.usages/steps.md` | INDIRECTLY AFFECTED — the `run_on_page` author callable section mirrors some prompt rules but explicitly states «Prompt rules do not bind the author»; the binding-economy rule is a generation rule and does not reach the author's callable |
| `.goga/usages/prompts/step_cheatsheet.md` | UNAFFECTED — the count-forms idiom is correct as taught |
| `prettyplay/engine/.usages/healing.md` | UNAFFECTED — describes the healing API flow; no code-form contract statement |
| `prettyplay/engine/steering/.usages/steering.md` | UNAFFECTED — describes the dialog flow; the gate reference stays accurate |
| `.goga/usages/conventions.md` | UNAFFECTED — read-only base practice |
| Synced dependency usages (`.goga/usages/cooks/*`) | UNAFFECTED — managed by `goga usages sync`, read-only |

## Updated Usages

| Usage File | Changes Made | Reason |
|---|---|---|
| `.goga/usages/prompts/step_generation.md` | Economy rule extended: «…nothing more, nothing less: every name the code binds, the code uses» | The single source of the generation prompt — the defect carrier |
| `prettyplay/engine/.usages/generation.md` | «The fixed form» section gained «Every name the code binds, the code uses — no dead weight.» | The section states the generated-code contract; the cleanliness dimension is now part of it — kept consistent with the manifest annotation and the docs |
| `docs/reference/step-cache.md` | The self-contained contract sentence gained the every-binding-used clause and «carries no dead weight» | User docs state what the gate now enforces |

## Verified Usages

| Usage File | Verified? | Notes |
|---|---|---|
| `prettyplay/.usages/steps.md` | YES | The author-callable rules unchanged and accurate; the new rule binds only generated code, and the section's «prompt rules do not bind the author» line keeps the boundary explicit |
| `step_cheatsheet.md`, `healing.md`, `steering.md`, `conventions.md` | YES | No statement contradicts the new rule; no example carries dead code |

## Canonical Patterns Status

Preserved. No example, scenario or call pattern changed shape; the three edited texts gained one clause each, consistent in wording with the manifest annotation. `goga lint`: 12 cells, 0 errors; full suite still 1382 passed.

## Consistency Summary

Consistent. The contract statement now appears with the same semantics in four places — the prompt practice (teaching), the manifest fixed-form annotation (specification), the engine usage fixed-form section (consumer documentation) and the user docs — with the gate calibration (enforcement) naming the same finding; mirrors are test-enforced.
