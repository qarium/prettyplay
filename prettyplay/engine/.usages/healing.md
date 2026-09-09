# Step healing

Domain: healing a failed cached step. Audience: library internals and engineers reasoning about healed runs.

## Heal

```python
healed = healer.heal(
    step=failed_step, error="element not found: button «Sign in»", previous_steps=["open the login page"], page=page
)
```

The classification verdict decides the path:

| Category | Path |
|---|---|
| rot | regenerate from the current page within the healing budget (default 2), execute, save back to the cache, report loudly |
| product_defect | raise ProductDefectError carrying the verdict — category, explanation and recommendation all reach the exception message, the on_step_verdict hook and the log |
| incurable | raise IncurableStepError carrying the verdict; the reason names the incurability cause |

## Rules

- Anti-masking: healing never turns a product defect into a green test
- The healed code replaces the cached code only after a successful execution
- Generation and healing attempts live in one per-test registry — owned by the runtime of the test — with separate per-step limits (default 3 and 2)
- A regeneration budget exhaustion after rot raises IncurableStepError carrying the verdict of the original rot classification — no extra LLM request
- Provider unavailability during the classification raises LlmUnavailableError — an explicit infrastructure failure

## Verdicts

Every terminal failure carries its verdict in full: the exception message starts with the primary reason and appends the verdict render; the same three fields reach on_step_verdict and the structured log record.
