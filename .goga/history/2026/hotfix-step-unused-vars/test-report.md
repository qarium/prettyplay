# Test Report

## Changes Requiring Coverage

| Change | Type |
|---|---|
| Generation prompt economy rule gains «every name the code binds, the code uses» | behavior (prompt pin) |
| The rule lands identically in all three synchronized copies (practice file, engine constant, steering constant) | manifest (mirror lockstep) |
| Gate high calibration names dead weight as blocking; adequacy rules line names it in the overreach class | behavior (prompt pin) |
| The gate calibration lands identically in manifest practice and constant | manifest (mirror lockstep) |
| Manifest fixed-form annotation gains «every binding used — no dead weight» | manifest (structural validity via `goga lint`) |
| Docs contract sentence gains the clause | documentation — not test-covered by project convention |
| Dirty candidate flows through the existing high-finding block-and-retry path | regression — existing generic tests cover the mechanism; no runtime code changed |

## Tests Added

| Test Name | File | What It Validates |
|---|---|---|
| `test_system_prompt_requires_every_binding_used` | `tests/engine/test_generator.py` | The economy rule carries the binding-economy clause verbatim, positioned on the economy rule line (after its head) |
| `test_compliance_prompt_blocks_dead_weight` | `tests/engine/test_compliance.py` | The dead-weight clause is present in the high calibration (before «only high blocks the candidate» — blocking) and in the adequacy rules line; wrap-agnostic normalization guards the constant's hard line wrapping |

## Test Results

| Test | Status | Details |
|---|---|---|
| Full suite, Python 3.12.15 | PASSED | 1382 passed (1380 existing + 2 new), 0 failed, 0 modified |
| Full suite, Python 3.11.2 (compatibility floor) | PASSED | 1382 passed |
| Mirror equality — generation (practice ↔ engine ↔ steering) | PASSED | `tests/test_groups_integration.py`, `tests/engine/steering/test_steering.py`, `tests/engine/test_generator.py` — carry the lockstep of the edited rule |
| Mirror equality — compliance (manifest practice ↔ constant) | PASSED | `test_compliance_prompt_mirror_matches_the_code_manifest_practice` — byte-equal after the two-sided edit |
| `ruff check prettyplay/ tests/` | PASSED | clean |
| `ruff format --check` | PASSED | 122 files formatted |
| `goga lint` | PASSED | 12 cells, 0 errors |

## Coverage Gaps

| Changed Behavior | Covered? | Notes |
|---|---|---|
| Prompt rule teaches binding economy | YES | new pin + three-way mirror equality |
| Gate blocks dead weight | YES | new pin (position inside high calibration) + two-way mirror equality |
| Dirty candidate blocked and retried | YES (existing) | the compliance-blocked retry path is covered by existing generator/compliance logic tests; the change adds verdict content, not mechanism — no runtime code changed |
| Manifest annotation clause | YES (structural) | `goga lint` validates the manifest; annotation text is normative spec, not behavior — same convention as the previous fix |

## Missing Coverage Analysis

Nothing material is untested. Live-model adherence to the new rule is observational by the project's convention (provider fakes in tests; the owner's next example run regenerates the purged entry under the corrected prompt — the new cache file is the live proof). Documentation text has no test surface by project convention.
