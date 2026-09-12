# Self-healing

Healing a failed cached step. For engineers reasoning about healed runs.

When a cached step fails, the failure is classified first; the classification
verdict decides the path.

## Classification categories

| Category | Meaning | Consequence |
|---|---|---|
| `rot` | the UI changed: selectors, texts, structure | the step is regenerated from the current page and retried |
| `fixable` | the step code is at fault (an ambiguous or wrong locator or strategy) while the intent stays satisfiable | the step is regenerated for the same intent, the request carrying the classification recommendation |
| `product_defect` | the expectation legitimately failed | the test fails loudly — never healed green |
| `incurable` | regeneration cannot help: budget exhausted, text no longer matches reality, ambiguity | the incurable failure carries step, reason, recommendation |

## Heal

```python
healed = healer.heal(
    step=failed_step,
    error="element not found: button «Sign in»",
    previous_steps=["open the login page"],
    page=page,
    window=window,  # the settle window of the current step execution
)
```

The classification verdict decides the path:

| Category | Path |
|---|---|
| `rot`, `fixable` | regenerate from the current page within the healing budget (default 2), execute, save back to the cache, report loudly |
| `product_defect` | raise `ProductDefectError` carrying the verdict — category, explanation and recommendation all reach the exception message, the `on_step_verdict` hook and the log |
| `incurable` | raise `IncurableStepError` carrying the verdict; the reason names the incurability cause |

## Rules

- Anti-masking: healing never turns a product defect into a green test
- The healed code replaces the cached code only after a successful execution
- Generation and healing attempts live in one per-test registry — owned by the
  runtime of the test — with separate per-step limits (default 3 and 2)
- Every failed attempt inside the regeneration loop retries with the fresh
  error and snapshot — a failed check included — with no per-attempt
  classification: the entry classification already guards the anti-masking
- A regeneration budget exhaustion after `rot` or `fixable` raises
  `IncurableStepError` carrying the verdict of the entry classification — no
  extra LLM request
- Provider unavailability during the classification raises
  `LLMUnavailableError` — an explicit infrastructure failure
- Healing never runs in strict mode: a failed cached step is at most
  classified, never regenerated
- Every candidate execution runs under the settle window of the current step
  execution — see [Settle polling](../getting-started.md#settle-polling)

## Verdicts

Every terminal failure carries its verdict in full and the full underlying
error in the error field: the exception message is the structured render — the
primary reason, the `---` separated step/error block, the column-aligned
verdict block; the same text reaches `on_step_verdict` (structured fields) and
the log record. The render format is specified in
[Failure taxonomy](failure-taxonomy.md).

When the LLM is unavailable the verdict is skipped quietly (`WARNING` in the
log) — the failure itself never waits for it.
