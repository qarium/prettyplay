# Failure taxonomy

Domain: failure kinds of prettyplay. Audience: integrators wiring library failures into runner and CI reporting.

Every step failure is one of four distinct kinds; all derive from `PrettyplayError`, so one except clause catches any
prettyplay failure. A fifth kind — the configuration error — joins the base from the config cell.

| Exception | Meaning | When it happens | Recommended reaction |
|---|---|---|---|
| ProductDefectError | real product regression | an assertion expectation legitimately failed | treat as a bug: file it, fix the product — this failure is the value of the suite |
| IncurableStepError | the step cannot be (re)generated | attempt budget exhausted, step text no longer matches reality, ambiguity, strict mode forbids generation | follow the verdict `recommendation`: reword the step or refresh the cache |
| LLMUnavailableError | LLM infrastructure down | generation or healing ran while the provider was unavailable | restore provider access or keys; cached steps are unaffected |
| ComplianceVerdictError | the compliance gate could not obtain a usable verdict | a successfully executed candidate was checked, but the verdict model answer did not parse | rerun the step to retry generation; a repeatedly malformed verdict points at the verdict model — the candidate was never cached |
| ConfigurationError | settings are invalid | the first library use loaded an invalid [tool.prettyplay] section | fix the named setting — the message lists the allowed values |

## Verdict categories

ProductDefectError and IncurableStepError may carry a verdict with a category — the classification label the LLM
assigned to the failure. The label set is four:

| Category | Meaning | Consequence inside the library |
|---|---|---|
| rot | the UI changed: selectors, texts, structure | the step is regenerated from the current page |
| product_defect | the expectation legitimately failed | the test fails loudly — never healed green |
| fixable | the step code is at fault (ambiguous or wrong locator/strategy); the intent is satisfiable | the step is regenerated for the same intent, the request carrying the classification recommendation |
| incurable | regeneration cannot help: budget exhausted, text no longer matches reality, ambiguity | the incurable failure carries step, reason, recommendation |

The category travels in the structured fields of the `on_step_verdict` hook event — never in the rendered message.

## The structured failure message

ProductDefectError and IncurableStepError render one structured message — the same text reaches the exception message,
the log record and the `error` field of the `on_step_failed` hook event:

```text
ProductDefectError: the "Sign in" button stayed invisible after submitting the form
---
step: Check that the "Sign in" button appears
error: Locator expected to be visible
---
explanation:    the page has no element with role button and name "Sign in"
recommendation: check the selector or the button text in the application
```

- The first line is the primary reason only — no kind label, no colons; the exception type prefix (rendered by the
  runner) supplies the kind
- The `step:`/`error:` block carries the step sentence and the full underlying error of the failed step code, locator
  details included; for failed checks the `error:` text never carries an AssertionError prefix — the exception type
  already carries the assertion semantics; the block is omitted entirely when both are empty
- The verdict block shows column-aligned `explanation:` and `recommendation:` values — multi-line continuations indent
  to the same value column; the `category:` line is gone — the category travels in the structured fields of
  `on_step_verdict`, never in the render
- Empty blocks are omitted entirely: no underlying error → no `error:` line; ProductDefectError without a verdict
  renders no verdict block, while IncurableStepError without a verdict always renders a fallback `recommendation:`
  line with the built-in path guidance — the verdict attribute itself stays None and `on_step_verdict` stays silent
- The failed step's code is never included — it lives in the cache and the `code` field of IncurableStepError

## Verdicts on terminal failures

ProductDefectError and IncurableStepError carry an optional verdict: category, explanation, recommendation. When the
LLM is unavailable the verdict is skipped quietly (WARNING in the log) — the failure itself is never delayed or
distorted.

```python
import pytest

from prettyplay.failures import IncurableStepError


def test_reports_only_library_failures():
    with pytest.raises(IncurableStepError) as info:
        ...
    assert info.value.recommendation
    # info.value.verdict may be None when the LLM was unavailable
    # info.value.error carries the full underlying error text ("" when none)
    # info.value.code carries the failed step code ("" when unknown) — programmatic
    # consumers only: never rendered, never in hook or log payloads
```

## Compliance verdict failure — ComplianceVerdictError

Raised when the instruction compliance gate cannot parse the verdict model's answer into
findings: the JSON shape is invalid, a priority label is outside {high, medium, low}, or a
finding misses its fields. The gate is strict by design — a flaky verdict model surfaces
loudly instead of waving candidates through.

Catch it together with every other library failure:

```python
from prettyplay.failures import ComplianceVerdictError, PrettyplayError

try:
    scenario.step("open the dashboard")
except ComplianceVerdictError as error:
    ...  # the candidate was NOT cached; rerun the step to retry generation
except PrettyplayError:
    ...
```

What it means for the engineer:
- the step candidate executed successfully but was never verified against the project
  instructions, so it was not cached
- remediation is on the verdict side, not the page: rerun the test, check the provider
  state and the model behind the effective generation model; a repeatedly malformed
  verdict points at a model unable to follow the verdict format
- switching `generation_approve` off removes the gate entirely (the old behavior)

## Assertion semantics

ProductDefectError is also an AssertionError: unittest reports the failed check as a failure (not an error), pytest
shows it as an ordinary assertion failure, the traceback is folded to the library boundary. Catch it with
`except PrettyplayError` or `except AssertionError` — both work.

## Rules

- Every failure message is actionable: what happened, on which step, what to do next
- A healed run never turns a ProductDefectError into a green test
- LLMUnavailableError never occurs on the cached path — a cached suite runs without any LLM
- One render per terminal failure: integrators parsing messages parse the structured template above; the category
  comes from the `on_step_verdict` event fields, never from the message
