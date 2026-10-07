# Change Execution Report — aria-snapshot error output pollution

## Summary
A Playwright assertion failure embedded the full page aria snapshot in the raw exception message; chained under prettyplay's terminal errors it flooded the runner output (~100 KB per failure) and bloated LLM request payloads. The snapshot section is now excluded at the two boundaries that carry failure text: the engine error-text policy and the facade traceback fold. Approved via the hotfix stage dialog (plan approval in autonomous_execution.q2.answer.json).

## Root Cause
Playwright (>=1.49) appends the whole-page accessibility snapshot after a column-zero `Aria snapshot:` header to a failed `expect(...)` message. Two library paths carried it unchecked: `format_step_error` returned the AssertionError message verbatim (records, renders' input, LLM requests), and `_raise_folded` folded chained tracebacks but not chained messages, so the runner printed the snapshot in full through the preserved `__context__` chain. The structured terminal render was already clean — `decompose_error_text` collects only the recognized detail shapes.

## Modified Cells
| Cell | Files Modified |
|---|---|
| prettyplay | scenario.py, CODEMANIFEST, .usages/lifecycle.md |
| prettyplay/engine | text.py, CODEMANIFEST, .usages/generation.md |
| tests (verification) | tests/test_scenario.py, tests/engine/test_text.py |

## Implemented Changes
| Change | File | Description |
|---|---|---|
| Error-text policy exclusion | prettyplay/engine/text.py | `format_step_error` drops everything from the first column-zero `Aria snapshot:` header to the message end (private `_strip_aria_snapshot`); all other text stays verbatim |
| Fold trims chained messages | prettyplay/scenario.py | `_fold_chain_tracebacks` also trims the aria-snapshot section from every chained exception's single-string message (`_trim_aria_snapshot` rewrites `args` only for the single-string shape); chain identity and objects preserved |
| Contract: error-text policy | prettyplay/engine/CODEMANIFEST | `format_step_error` requirement now states the trailing aria-snapshot exclusion |
| Contract: facade fold | prettyplay/CODEMANIFEST | `step`/`expect` annotations extend the fold guarantee with the chained-message trim |
| Usage: attempt records | prettyplay/engine/.usages/generation.md | The "complete error" bullet qualifies the exclusion and points to the separately captured snapshot |
| Usage: failure table | prettyplay/.usages/lifecycle.md | ProductDefectError row states the chained aria-snapshot trim at the boundary |

## Tests Added
| Test | File | What It Validates |
|---|---|---|
| TestAriaSnapshotExclusion (6 cases) | tests/engine/test_text.py | Trailing section dropped with head/Call log kept; no-section passthrough; section-only yields empty check text; typed failures strip too; indented header is not a boundary; trailing spaces after the header still bound the section |
| test_folded_chain_trims_chained_aria_snapshot_messages | tests/test_scenario.py | Context and cause exceptions lose the page-state tail at the facade boundary; chain and object identity preserved |
| test_folded_chain_leaves_non_string_argument_shapes_untouched | tests/test_scenario.py | Two-argument and message-less chained exceptions are never rewritten |

## Specification Updates
| Cell | CODEMANIFEST Changes | Usage Changes |
|---|---|---|
| prettyplay/engine | format_step_error requirement: aria-snapshot exclusion | generation.md: complete-error bullet qualified |
| prettyplay | step/expect fold annotations: chained-message trim | lifecycle.md: ProductDefectError fold row extended |

## Validation Results
Full suite 1190 passed, 0 failed (6.6 s). ruff check and format: clean, 111 files formatted. goga lint: 11 cells, 0 errors. End-to-end repro of the reported failure shape (chained AssertionError + LLMUnavailableError): output reduced from ~100 KB to 804 chars, `Actual value`/`Call log` diagnostics retained, no `Aria snapshot` content.

## Compatibility Status
Compatible. Signatures, return types, defaults, render format, file paths and exception kinds unchanged. One approved behavioral delta: failure texts that contain the aria-snapshot section no longer carry it (the defect fix itself); manifest and usage text updated atomically in the same change. Existing tests pass unmodified.

## Risks
| Risk | Severity | Mitigation |
|---|---|---|
| Section-header knowledge lives in two cells (engine policy, facade fold) | Low | Each cell owns its own boundary policy; both pinned by tests; consolidation possible in a follow-up |
| Playwright could change the section shape | Low | Boundary is the column-zero exact header line; tests pin current and edge shapes |
| Content after the section would be cut | Low | Playwright appends the section last; documented in the contract wording ("trailing") |

## Updated Files
- prettyplay/engine/text.py
- prettyplay/scenario.py
- prettyplay/engine/CODEMANIFEST
- prettyplay/CODEMANIFEST
- prettyplay/engine/.usages/generation.md
- prettyplay/.usages/lifecycle.md
- tests/engine/test_text.py
- tests/test_scenario.py

## Acceptance Follow-up — 2026-10-07

Acceptance of commit 09a9caa found that the formatter fix did not cover the generator's assertion-specific branches: generate, regenerate, and the single funded candidate still used str(check_failure). A runtime reproduction retained the snapshot in attempt history, classification input and the terminal error field even though all 1190 original tests passed.

With explicit user approval (accept-result autonomous_execution.q3.answer.json), all five bypass calls in those three branches now use format_step_error. Three integration regressions verify cleaned history, classification/retry payloads and terminal fields, retained Actual value/Call log diagnostics, and the separately supplied page snapshot. All three failed before the repair and passed afterward.

The facade contract and lifecycle documentation were also clarified with q1 approval: trimming modifies a single string exception argument; other shapes and independent custom rendering are outside this guarantee. Exception identities and chains remain preserved.

Final validation: 1193 tests passed (6.67 s), ruff check passed, 111 files passed format checking, goga lint checked 11 cells with zero errors, and git diff --check passed. Acceptance verdict: ACCEPTED_WITH_NOTES; live external services and other Python versions were not exercised in this stage.
