# Validating step results

Domain: deterministic acceptance of returned step results. Audience: library internals — the executor and the engines validating executions.

## Validate an execution result

```python
from prettyplay.engine.renderer import validate_step_result

captures = validate_step_result(prepared, result)  # result — the step function's return
memory.publish(captures)
```

- Exact declared keys: missing or unexpected names violate; string values only; blank (empty or whitespace-only) values violate
- A declaration-free step accepts None and validates to empty captures — the success-without-result behavior
- A violation raises AssertionError with a deterministic text — it enters the existing failed-check paths: classification and bounded corrective generation where non-strict execution permits, strict failure without generation
- Publish only validated captures — never fabricated or repaired values
