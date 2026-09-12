# Failure taxonomy

Failure kinds of prettyplay. For integrators wiring library failures into
runner and CI reporting.

Every step failure is one of three distinct kinds; all derive from
`PrettyplayError`, so one except clause catches any prettyplay failure. A
fourth kind — the configuration error — joins the base from the config cell.

| Exception | Meaning | When it happens | Recommended reaction |
|---|---|---|---|
| `ProductDefectError` | real product regression | an assertion expectation legitimately failed | treat as a bug: file it, fix the product — this failure is the value of the suite |
| `IncurableStepError` | the step cannot be (re)generated | attempt budget exhausted, step text no longer matches reality, ambiguity, strict mode forbids generation | follow the verdict `recommendation`: reword the step or refresh the cache |
| `LLMUnavailableError` | LLM infrastructure down | generation or healing ran while the provider was unavailable | restore provider access or keys; cached steps are unaffected |
| `ConfigurationError` | settings are invalid | the first library use loaded an invalid `[tool.prettyplay]` section | fix the named setting — the message lists the allowed values |

## The structured failure message

`ProductDefectError` and `IncurableStepError` render one structured message —
the same text reaches the exception message, the log record and the `error`
field of the `on_step_failed` hook event:

```text
ProductDefectError: кнопка «Войти» осталась невидимой после отправки формы
---
step: Проверить появление кнопки «Войти»
error: Locator expected to be visible
---
explanation:    на странице нет элемента с ролью button и именем «Войти»
recommendation: проверить селектор или текст кнопки в приложении
```

- The first line is the primary reason only — no kind label, no colons; the
  exception type prefix (rendered by the runner) supplies the kind
- The `step:`/`error:` block carries the step sentence and the full underlying
  error of the failed step code, locator details included; for failed checks
  the `error:` text never carries an `AssertionError` prefix — the exception
  type already carries the assertion semantics; the block is omitted entirely
  when both are empty
- The verdict block shows column-aligned `explanation:` and `recommendation:`
  values — multi-line continuations indent to the same value column; the
  `category:` line is gone — the category travels in the structured fields of
  `on_step_verdict`, never in the render
- Empty blocks are omitted entirely: no verdict → no verdict block; no
  underlying error → no `error:` line
- The failed step's code is never included — it lives in the cache and the log

## Verdicts on terminal failures

`ProductDefectError` and `IncurableStepError` carry an optional verdict:
category, explanation, recommendation. When the LLM is unavailable the verdict
is skipped quietly (`WARNING` in the log) — the failure itself is never
delayed or distorted.

```python
import pytest

from prettyplay.failures import IncurableStepError


def test_reports_only_library_failures():
    with pytest.raises(IncurableStepError) as info:
        ...
    assert info.value.recommendation
    # info.value.verdict may be None when the LLM was unavailable
    # info.value.error carries the full underlying error text ("" when none)
```

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
