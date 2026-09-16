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
| `LLMUnavailableError` | LLM infrastructure down | generation or healing ran while the provider was unavailable | restore provider access or keys; cached steps are unaffected |
| `ComplianceVerdictError` | the compliance gate could not obtain a usable verdict | a successfully executed candidate was checked, but the verdict model answer did not parse | rerun the step to retry generation; a repeatedly malformed verdict points at the verdict model — the candidate was never cached |
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

## Compliance verdict failure

`ComplianceVerdictError` is raised when the compliance gate cannot
parse the verdict model's answer into findings: the JSON shape is invalid, a
priority label is outside `high|medium|low`, a `dimension` is missing or
outside `instruction|adequacy` (an answer of the old shape included), or a
finding misses its fields.
The gate is strict by design — a flaky verdict model surfaces loudly instead
of waving candidates through.

Catch it together with every other library failure:

```python
from prettyplay.failures import ComplianceVerdictError, PrettyplayError

try:
    scenario.step("open the dashboard")
except ComplianceVerdictError:
    ...  # the candidate was NOT cached; rerun the step to retry generation
except PrettyplayError:
    ...
```

What it means for the engineer:

- the step candidate executed successfully but was never verified against the
project instructions, so it was not cached
- remediation is on the verdict side, not the page: rerun the test, check the
provider state and the model behind the effective classification model; a
repeatedly malformed verdict points at a model unable to follow the verdict
format
- switching `generation_approve` off removes the gate entirely (the old
behavior) — see [Configuration](../configuration.md#the-compliance-gate)

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
