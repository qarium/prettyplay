# Specification Drift Analysis

## Manifest Drift

| Cell | Drift Description | Resolved? |
|---|---|---|
| prettyplay/engine | The manifest granted a runtime context global that the rendered-sentence addressing contract made obsolete (inter-contract contradiction) | Resolved — the grant replaced by the self-containment contract; compliance practice rule replaced; `goga lint` 0 errors |
| prettyplay/engine/steering, prettyplay (facade) | None — no context semantics were described | Resolved (nothing to do; verified) |

## Usage Drift

| Cell | Drift Description | Resolved? |
|---|---|---|
| engine/steering | The `system_prompt` practice taught context reads; its two frozen constants carried the same text | Resolved — practice and both constants changed together; byte-equality tests green |
| docs | `docs/reference/step-cache.md` contradicted itself (values pinned by address vs code tracking live context) | Resolved — paragraph rewritten to the self-contained contract |
| All cell usages | None found — verified no context-reading recipes | Resolved (verified) |

## Behavioral Drift

| Cell | Drift Description | Resolved? |
|---|---|---|
| prettyplay/engine | `run_step_code` executed code with a hidden second value channel (context global) beside the page argument | Resolved — namespace carries nothing; the only intended behavioral change, owner-approved at the compatibility gate |
| prettyplay (facade) | Replay bound the context for cached code | Resolved — replay executes self-contained code; legacy context-reading entries fail loudly and self-heal (documented purge posture) |
| prettyplay/engine/steering | Guided execution bound the context | Resolved — same unwrapping |

## Algorithmic Drift

| Cell | Drift Description | Resolved? |
|---|---|---|
| prettyplay/engine | None — generation/healing loop algorithms unchanged (manifest steps never described the binding); settle/validate/gate/publish order intact | Resolved (verified against manifest algorithm steps) |
| prettyplay/engine/steering | None — guided-turn algorithm unchanged | Resolved (verified) |

## Resolution Status

All drift resolved. Final verification: `pytest tests/` — 1380 passed; `ruff check` clean; `ruff format --check` — 122 files formatted; `goga lint` — 12 cells, 0 errors; project-wide `step_inputs` scan — only intentional negative assertions in three test files.
