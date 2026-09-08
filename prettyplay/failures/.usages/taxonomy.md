# Failure taxonomy

Domain: failure kinds of prettyplay. Audience: integrators wiring library failures into runner and CI reporting.

Every library failure is one of three distinct kinds; each has its own exception type, and all derive from `PrettyplayError`.

| Exception | Meaning | When it happens | Recommended reaction |
|---|---|---|---|
| ProductDefectError | real product regression | an assertion expectation legitimately failed | treat as a bug: file it, fix the product — this failure is the value of the suite |
| IncurableStepError | the step cannot be (re)generated | attempt budget exhausted, step text no longer matches reality, ambiguity | follow `recommendation`: reword the step or refresh the cache |
| LlmUnavailableError | LLM infrastructure down | generation or healing ran while the provider was unavailable | restore provider access or keys; cached steps are unaffected |

## Example

```python
import pytest

from prettyplay.failures import IncurableStepError, PrettyplayError


def test_reports_only_library_failures():
    with pytest.raises(IncurableStepError) as info:
        ...
    assert info.value.recommendation


# any library failure at the suite boundary:
# except PrettyplayError: ...
```

## Rules

- Every failure message is actionable: what happened, on which step, what to do next
- A healed run never turns a ProductDefectError into a green test
- LlmUnavailableError never occurs on the cached path — a cached suite runs without any LLM
