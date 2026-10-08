# Validating step results

Domain: deterministic acceptance of returned step results. Audience: library internals — the executor and the engines validating executions.

## Validate an execution result

```python
from prettyplay.engine.renderer import PreparedStep, StepMemory, validate_step_result

memory = StepMemory()
prepared = PreparedStep(instruction="Read the item name", declarations=["name"])
result = {"name": "Book"}  # returned by the executed step after reading the page
captures = validate_step_result(prepared, result)
memory.publish(captures)  # accepted cached replay; candidates must pass compliance first
```

- Exact declared keys: missing or unexpected names violate; string values only; blank (empty or whitespace-only) values violate
- A declaration-free step accepts None and validates to empty captures — the success-without-result behavior
- A violation raises AssertionError with a deterministic text — it enters the existing failed-check paths: classification and bounded corrective generation where non-strict execution permits, strict failure without generation
- Publish only validated captures — never fabricated or repaired values
