# Step healing

Domain: healing a failed cached step. Audience: library internals and engineers reasoning about healed runs.

## Heal

```python
healed = healer.heal(
    step=failed_step, error="element not found: button «Войти»", previous_steps=["открыть страницу логина"], page=page
)
```

The classification verdict decides the path:

| Category | Path |
|---|---|
| rot | regenerate from the current page within the healing budget (default 2), execute, save back to the cache, report loudly |
| product_defect | raise ProductDefectError — the test fails, nothing is regenerated |
| incurable | raise IncurableStepError with reason and recommendation |

## Rules

- Anti-masking: healing never turns a product defect into a green test
- The healed code replaces the cached code only after a successful execution
- Generation and healing attempts live in one run-scoped registry with separate per-step limits (default 3 and 2)
- Provider unavailability during healing raises LlmUnavailableError — an explicit infrastructure failure
