# Error kinds — the pollable map

Domain: which failed step-code exceptions the settle window may absorb. Audience: engineers tuning polling and reasoning about why a failure did or did not retry.

The driver ships a fixed map: `is_pollable_failure(exc)` returns True when the exception kind is transient page state — the settle window may re-execute the same code; False when the failure is deterministic or unknown — it goes straight to classification. Recognition is by exception type and message pattern; no LLM, no settings.

| Kind | Message signature | Pollable |
|---|---|---|
| timeout | `Timeout NNNms exceeded` — locator, action, expectation or navigation wait | yes |
| element state | `element is not visible`, `element is not enabled`, `element is outside of the viewport`, detached/stale element | yes |
| navigation / context | `Execution context was destroyed`, `Target closed`, navigation interrupted mid-flight | yes |
| failed expectation | plain `AssertionError` from an expect_* call — the check executed and did not hold | yes |
| locator ambiguity | `strict mode violation: locator resolved to N elements` | no — the elements are there; waiting will not collapse them to one |
| Python-level error | syntax, name and type errors of the step code itself | no — not a driver error at all |
| unrecognized | anything else | no — conservative default, straight to classification |

## Reading the map

- Pollable kinds typically reflect a page-state race: the previous action finished while a state transition was still in flight; re-executing the same code once the state settles is honest retrying, not masking.
- A failed expectation is pollable because the same code passing later means the state caught up — the check itself stays intact.
- Locator ambiguity is deterministic: the locator itself is at fault, the classification labels it `fixable` and regeneration produces an unambiguous locator.

## Rules

- The map is fixed in code: it never reads settings and never asks an LLM.
- The decision takes only the exception object — pure and deterministic.
