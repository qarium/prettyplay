# Test Report

## Changes Requiring Coverage

| Change | Type |
|---|---|
| `run_step_code` namespace exposes no context global | behavior + regression (return/exception/identity paths must hold) |
| SYSTEM_PROMPT ready-instruction rule; no `step_inputs` anywhere in prompts | manifest/contract |
| Three-way prompt mirror lockstep (practice file + engine + steering constants) | manifest (mirror discipline) |
| COMPLIANCE_PROMPT: embedded STEP values correct, never a finding | manifest/contract |
| Compliance constant mirrors the CODEMANIFEST practice | manifest (mirror discipline) |
| Replay executes each rendered entry's self-contained code | behavior |
| Healing accepts a self-contained candidate after an invalid attempt | behavior |

## Tests Added

| Test Name | File | What It Validates |
|---|---|---|
| `test_step_code_namespace_exposes_no_context` | tests/engine/test_execution.py | Code referencing `step_inputs` raises `NameError` — nothing beyond the page argument exists (replaces the removed fresh-bindings test) |
| `test_system_prompt_treats_the_step_as_a_ready_instruction` | tests/engine/test_generator.py | The ready-instruction rule is present; `step_inputs` occurs nowhere in SYSTEM_PROMPT |
| `test_compliance_prompt_treats_embedded_step_values_as_correct` | tests/engine/test_compliance.py | The gate rule states embedded STEP values are correct; `step_inputs` occurs nowhere in COMPLIANCE_PROMPT |

## Tests Modified

| Test Name | File | Change |
|---|---|---|
| `test_template_cache_replays_each_rendered_value_entry` (was `…_uses_current_call_inputs`) | tests/test_executor.py | Two rendered values → two entries, each replaying its own literal-embedding code; memory and scenario assertions unchanged |
| `test_regenerate_invalid_capture_preserves_memory_until_acceptance` | tests/engine/test_generator.py | The corrected candidate is self-contained (`assert page is not None` + declared returns) instead of asserting context reads |

## Test Results

| Test | Status | Details |
|---|---|---|
| Full suite `pytest tests/` | **1380 passed**, 0 failed, 0 errors | includes all mirror-equality tests (`test_groups_integration.py:564`, `test_steering.py:353`, compliance manifest mirror) |
| `ruff check prettyplay/ tests/` | passed | |
| `ruff format --check` | 122 files formatted | |
| `goga lint` | 12 cells, 0 errors | |

## Coverage Gaps

| Changed Behavior | Covered? | Notes |
|---|---|---|
| Runtime context removal | Yes | NameError contract + unchanged execution-path suite |
| Prompt rules | Yes | Text-contract tests + byte-equality mirror tests |
| Replay/healing/steering paths without binding | Yes | Existing suites exercised every path with self-contained stub code and stayed green |
| Real model adherence to the new prompt | Out of automated scope | Provider fakes are the project convention (same posture as the acceptance report); the wired example regenerates under the new prompt on the owner's next run |

## Missing Coverage Analysis

Nothing uncovered among changed behaviors. The only untestable dimension — whether a live generation model now embeds literals — is observable in the regenerated example cache entries after the owner's next run; the prompt-contract and gate-contract tests pin the instructions that drive it.
