# Step healing

Domain: healing a failed cached step. Audience: library internals and engineers reasoning about healed runs.

## Heal

```python
healed = healer.heal(
    step=failed_step,
    error="element not found: button «Sign in»",
    step_text="click the «Sign in» button",
    step_type="action",
    previous_steps=[ScenarioStep(sentence="open the login page", group_prompt="")],
    page=page,
    attempt_history=history,
    window=window,
)
```

The executor seeds record 0 of `attempt_history` before the delegation — the original cached code, the full replay
error and the URL pair of the replay — so regeneration never loses the original: the history carries every record,
the anchored cached code first. The raw `step_text` and the step type ride every classification and regeneration
request — the casefolded normalization is an addressing key only.

The classification verdict decides the path — the uniform decision table:

| Category | Path |
|---|---|
| rot, fixable | regenerate from the current page within the healing budget (default 2), the request carrying the classification recommendation as a RECOMMENDATION block and the grown attempt history; execute under the settle window, save back to the cache on success, report loudly |
| product_defect | raise ProductDefectError carrying the verdict — explanation and recommendation reach the exception message and the log, all three fields reach the on_step_verdict hook (the category never renders) |
| incurable | raise IncurableStepError carrying the verdict; the reason names the incurability cause |

## Rules

- A healed candidate passes the two-dimension compliance gate before the write-back: a high
  finding of either dimension fails the healing attempt — the record lands in the history
  with the violation text in its error field; medium and low findings pass with a WARNING;
  a malformed verdict or provider unavailability is a hard failure — nothing is cached
  unchecked
- Anti-masking: healing never turns a product defect into a green test
- The healed code replaces the cached code only after a successful execution
- Generation and healing attempts live in one per-test registry — owned by the runtime of the test — with separate per-step limits (default 3 and 2)
- Inside the regeneration loop no per-attempt classification happens (rejected: LLM cost): a failed attempt of any kind — a failed check included — appends its record and retries with the fresh error, the fresh snapshot and the grown history while budget remains; the entry classification guards the anti-masking
- A regeneration budget exhaustion raises IncurableStepError carrying the verdict of the original classification — no extra LLM request
- The scenario context is typed (the raw sentence + permanent group membership); group steps never reach the healer — their failures route to the group recovery
- Provider unavailability during the classification raises LLMUnavailableError — an explicit infrastructure failure
- Healing never runs in strict mode: a failed cached step is at most classified, never regenerated
- Interactive steering attempts are separate from healing: they consume no budgets, join the same per-step history and report their own healings

## Verdicts

Every terminal failure carries its verdict in full and the full underlying error in the error field: the exception
message is the structured render — the first line carries the class name of the terminal failure and the authored
reason, then the `---` separated step/error section, the conditional received/cause/Call log details section and the
unpadded verdict block; the same text reaches on_step_verdict (structured fields) and the log record. IncurableStepError
also carries the failed step code in the code field — a programmatic field, never rendered.
