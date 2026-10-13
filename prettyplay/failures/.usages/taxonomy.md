# Failure taxonomy

Domain: failure kinds of prettyplay. Audience: integrators wiring library failures into runner and CI reporting.

Every step failure is one of four distinct kinds; all derive from `PrettyplayError`, so one except clause catches any
prettyplay failure. A fifth kind — the configuration error — joins the base from the config cell.

| Exception | Meaning | When it happens | Recommended reaction |
|---|---|---|---|
| ProductDefectError | real product regression | an assertion expectation legitimately failed | treat as a bug: file it, fix the product — this failure is the value of the suite |
| IncurableStepError | the step cannot be (re)generated | attempt budget exhausted, step text no longer matches reality, ambiguity, strict mode forbids generation | follow the verdict `recommendation`: reword the step or refresh the cache |
| LLMUnavailableError | LLM infrastructure down | an LLM operation (generation, failure classification, group diagnosis, compliance verdict) exhausted its bounded transport retries, met a permanent provider rejection, or received Retry-After above 10 seconds | restore provider access or keys, or wait the indicated interval before rerunning; cached steps are unaffected |
| ComplianceVerdictError | a provider compliance answer did not parse | raised by the parser/provider, caught by the built-in engine gate | inspect the WARNING: one re-ask is followed by an unchecked pass if still malformed; direct parser/provider callers handle the error |
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

ProductDefectError and IncurableStepError render one structured message — the same text
reaches the exception message, the log record and the `error` field of the `on_step_failed`
hook event:

```text
ProductDefectError: the "Sign in" button stayed invisible after submitting the form
---
step: Check that the "Sign in" button appears
error: Locator expected to be visible
---
received: <actual value — only when the underlying error carries one>
cause: <error cause>
Call log:
  - waiting for locator("button[name='Sign in']")
---
explanation: the page has no element with role button and name "Sign in"
recommendation: check the selector or the button text in the application
```

- The first line carries the class name of the terminal failure and the authored
  reason — the render is self-sufficient in log records and hook payloads where no runner
  prefix exists
- The `step:`/`error:` section carries the step sentence and the decomposed headline of the
  underlying error (its expectation or kind); for failed checks the `error:` text never
  carries an AssertionError prefix; the section is omitted entirely when both are empty
- The details section — `received:`/`cause:`/`Call log:` — appears only when the underlying
  error carries those parts (Playwright expect failures do); otherwise the whole section is
  omitted
- No label padding anywhere — labels render at column zero; multi-line verdict values
  indent by two spaces
- A page snapshot never appears in any terminal error output
- The `category:` line is gone — the category travels in the structured fields of
  `on_step_verdict`, never in the render; IncurableStepError without a verdict keeps the
  fallback `recommendation:` line
- The failed step's code is never included — it lives in the cache and the `code` field of
  IncurableStepError

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

The compliance parser/provider raises `ComplianceVerdictError` when the answer cannot
be parsed into valid findings, including after syntax salvage. The parser remains strict:
invalid shapes, missing fields and unknown priority/dimension labels are never findings.

The built-in engine gate catches this error, re-asks exactly once and, if that verdict is
also malformed, logs a WARNING and permits the successfully executed candidate to pass
unchecked and be cached. `PrettyPlay.step` and `expect` do not propagate this parse error.
A provider outage remains a hard `LLMUnavailableError` with no acceptance or cache write.

Direct parser/provider consumers can catch the error:

```python
from prettyplay.failures import ComplianceVerdictError
from prettyplay.llm import parse_compliance_verdict

try:
    parse_compliance_verdict("not json")
except ComplianceVerdictError:
    ...  # this parser accepted no findings; the caller chooses recovery
```

A repeated malformed verdict points at the verdict model; inspect the WARNING before
trusting the unchecked candidate. Disabling `generation_approve` removes the gate entirely.

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
