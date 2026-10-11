# Usage Reconciliation Report

## Classification

| Usage File | Classification |
|---|---|
| `.goga/usages/prompts/step_generation.md` | DIRECTLY AFFECTED (updated) |
| `docs/reference/step-cache.md` | DIRECTLY AFFECTED (updated) |
| `prettyplay/engine/.usages/generation.md` | INDIRECTLY AFFECTED (verified) |
| `prettyplay/engine/.usages/healing.md` | INDIRECTLY AFFECTED (verified) |
| `prettyplay/engine/steering/.usages/steering.md` | INDIRECTLY AFFECTED (verified) |
| `prettyplay/.usages/steps.md`, `lifecycle.md` | INDIRECTLY AFFECTED (verified) |
| `docs/guides/writing-steps.md` and remaining docs | INDIRECTLY AFFECTED (verified) |

## Updated Usages

| Usage File | Changes Made | Reason |
|---|---|---|
| `.goga/usages/prompts/step_generation.md` | The context-global teaching rule replaced by the ready-instruction rule (per the owner's amendment: no awareness of any context) | The old rule was the defect carrier; the practice is the single source of SYSTEM_PROMPT |
| `docs/reference/step-cache.md` | The `step_inputs` paragraph rewritten: generated code is self-contained, values embedded as literals | The old paragraph contradicted the addressing contract within the same section |

## Verified Usages

| Usage File | Verified? | Notes |
|---|---|---|
| `engine/.usages/generation.md` | Yes | Describes the fixed form (imports, no stateful actions) and request inputs — no context mention; snippets show self-contained code |
| `engine/.usages/healing.md` | Yes | Render-product addressing and write-back examples unaffected |
| `steering/.usages/steering.md` | Yes | "group context" refers to group framing of requests — unrelated; no runtime-context references |
| `prettyplay/.usages/steps.md` | Yes | "The honest step context" describes LLM request inputs (step type, prepared instruction, attempt history) — accurate as-is |
| `prettyplay/.usages/lifecycle.md` | Yes | No step-code value semantics |
| `docs/guides/writing-steps.md` | Yes | Speaks of rendered values and capture declarations; no context reads |
| Project-wide `step_inputs` occurrence scan | Yes | Zero matches across `prettyplay/`, `tests/`, `docs/`, `.goga/usages/` |

## Canonical Patterns Status

Preserved — the authoring surface (`step()`/`expect()` with optional vars), addressing by the rendered sentence, capture publication, steering and recovery recipes are untouched; only the removed runtime-context pattern (the defect) disappeared from every recipe.

`goga lint` after verification: 12 cells, 0 errors.

## Consistency Summary

CONSISTENT — every practice and user doc states the current behavior; no recipe contradicts the implementation.
