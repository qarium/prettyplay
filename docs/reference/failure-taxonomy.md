# Failure taxonomy

Failure kinds of prettyplay. For integrators wiring library failures into
runner and CI reporting.

Every step failure is one of four distinct kinds; all derive from
`PrettyplayError`, so one except clause catches any prettyplay failure. A
fifth kind — the configuration error — joins the base from the config cell.

| Exception | Meaning | When it happens | Recommended reaction |
|---|---|---|---|
| `ProductDefectError` | real product regression | an assertion expectation legitimately failed | treat as a bug: file it, fix the product — this failure is the value of the suite |
| `IncurableStepError` | the step cannot be (re)generated | attempt budget exhausted, step text no longer matches reality, ambiguity, strict mode forbids generation | follow the verdict `recommendation`: reword the step or refresh the cache |
| `LLMUnavailableError` | LLM infrastructure down | generation, failure classification, group diagnosis or compliance met a permanent rejection or exhausted its transport retries | restore provider access or keys; cached steps are unaffected |
| ComplianceVerdictError | a provider compliance answer did not parse | raised by the parser/provider, caught by the built-in engine gate | inspect the WARNING: one re-ask is followed by an unchecked pass if still malformed; direct parser/provider callers handle the error |
| `ConfigurationError` | settings are invalid | the first library use loaded an invalid `[tool.prettyplay]` section | fix the named setting — the message lists the allowed values |

## The structured failure message

`ProductDefectError` and `IncurableStepError` render one structured message —
the same text reaches the exception message, the log record and the `error`
field of the `on_step_failed` hook event:

```text
ProductDefectError: the "Sign in" button stayed invisible after submitting the form
---
step: Check that the "Sign in" button appears
error: Locator expected to be visible
---
received: display:none
Call log:
  - waiting for get_by_role("button", name="Sign in")
---
explanation: the page has no element with role button and name "Sign in"
recommendation: check the selector or the button text in the application
```

- The first line is the terminal class name and the authored reason —
  `ClassName: reason`, no padding
- The `step:`/`error:` block carries the step sentence and the decomposed
  headline of the underlying error (the dotted class prefix of a typed error
  reconstructs its kind, e.g. `error: TimeoutError: Timeout 30000ms
  exceeded`; for failed checks the `error:` text never carries an
  `AssertionError` prefix — the exception type already carries the assertion
  semantics); the block is omitted entirely when both are empty
- The details section appears only when the underlying error carries the
  recognized shapes: `received:` (the `Actual value:` detail, multi-line
  verbatim), `cause:` (the `Caused by:` line) and `Call log:` with its
  verbatim indented lines
- The verdict block shows `explanation:` and `recommendation:` labels at
  column zero — multi-line continuations indent two spaces; the `category:`
  line is gone — the category travels in the structured fields of
  `on_step_verdict`, never in the render
- Empty blocks are omitted entirely: no verdict → no verdict block; no
  underlying error → no `error:` line; no detail parts → no details section
- The failed step's code is never included — it lives in the cache and the log

The recognition behind the details section is exposed as public API:
`decompose_error_text(error)` returns an `ErrorParts` (a pydantic model with
`class_name`, `reason`, `received`, `cause`, `call_log` — all strings, empty
when absent) — the pure, never-raising halves of the render, for integrators
who want the parts instead of parsing the message:

```python
from prettyplay.failures import ErrorParts, decompose_error_text

parts = decompose_error_text(str(failure))  # or any underlying error text
# parts.class_name, parts.reason, parts.received, parts.cause, parts.call_log
```

## Verdicts on terminal failures

`ProductDefectError` and `IncurableStepError` carry an optional verdict:
category, explanation, recommendation. When the LLM is unavailable the verdict
is skipped quietly (`WARNING` in the log) — the failure itself is never
delayed or distorted.

`IncurableStepError` additionally carries a `code` attribute — the step code
that terminally failed: the cached step code on the healing and strict
failure paths, the last candidate code on the generation path, empty when no
candidate ever existed. A field for programmatic consumers only: it is never
rendered into the structured message and never carried by hook or log
payloads.

```python
import pytest

from prettyplay.failures import IncurableStepError


def test_reports_only_library_failures():
    with pytest.raises(IncurableStepError) as info:
        ...
    assert info.value.recommendation
    # info.value.verdict may be None when the LLM was unavailable
    # info.value.error carries the full underlying error text ("" when none)
    # info.value.code carries the failed step code ("" when no candidate existed)
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

`ProductDefectError` is also an `AssertionError`: unittest reports the failed
check as a failure (not an error), pytest shows it as an ordinary assertion
failure, the traceback is folded to the library boundary. Catch it with
`except PrettyplayError` or `except AssertionError` — both work.

## Rules

- Every failure message is actionable: what happened, on which step, what to
  do next
- A healed run never turns a `ProductDefectError` into a green test
- `LLMUnavailableError` never occurs on the cached path — a cached suite runs
  without any LLM
- One render per terminal failure: integrators parsing messages parse the
  structured template above; the category comes from the `on_step_verdict`
  event fields, never from the message
