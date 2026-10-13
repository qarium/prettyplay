# Step healing

Domain: healing a failed cached step. Audience: library internals and engineers reasoning about healed runs.

## Heal

```python
from prettyplay.engine.renderer import render_step
from prettyplay.llm import ScenarioStep

prepared = render_step("click the Sign in button", "action", memory, None)
# failed_step was loaded using the identity derived from this render's addressing_text.

healed = healer.heal(
    step=failed_step,
    error="element not found: button «Sign in»",
    prepared=prepared,  # includes the current render's verbatim addressing_text for write-back
    step_type="action",
    previous_steps=[ScenarioStep(sentence="open the login page", instruction="open the login page", group_prompt="")],
    page=page,
    attempt_history=history,
    window=window,
    memory=memory,
)
```

The executor seeds record 0 of `attempt_history` before the delegation — the original cached code, the full replay
error and the URL pair of the replay — so regeneration never loses the original: the history carries every record,
the anchored cached code first. The prepared instruction and the step type ride every classification and regeneration
request — NFC + trim normalization is an addressing key only.

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
  an unparsable verdict is re-asked once and then degrades to a loud unchecked pass —
  provider unavailability stays the hard failure: nothing is cached on an outage
- Regeneration candidates run under the probe bound too when probe_timeout is set — the same
  short action timeouts as generation candidates, restoring the baseline after every candidate;
  the replayed cached code of later runs keeps the baseline
- Anti-masking: healing never turns a product defect into a green test
- The healed code replaces the cached code only after a successful execution
- The accepted regeneration publishes its validated captures after the gate — nothing publishes on a failed or gate-blocked attempt
- Generation and healing attempts live in one per-test registry — owned by the runtime of the test — with separate per-step limits (default 3 and 2)
- Inside the regeneration loop no per-attempt classification happens (rejected: LLM cost): a failed attempt of any kind — a failed check included — appends its record and retries with the fresh error, the fresh snapshot and the grown history while budget remains; the entry classification guards the anti-masking
- Every regeneration candidate passes the deterministic pre-flight gate (`check_step_code`) before execution: a violation — the code does not compile, no step function, an undefined name — appends its record (never executed, the URL pair equal) and retries while budget remains
- A gate-blocked regeneration retries with the standing high finding riding the RECOMMENDATION block as an imperative prohibition, composed with the entry classification diagnosis — never replacing it; a fresh candidate failure supersedes the finding
- A regeneration budget exhaustion raises IncurableStepError carrying the verdict of the original classification — no extra LLM request
- The scenario context is typed (the raw sentence + the prepared instruction + permanent group membership; requests render the instruction); group steps never reach the healer — their failures route to the group recovery
- Provider unavailability during the classification raises LLMUnavailableError after the provider's bounded transport policy terminates. Transport sends consume no healing budget; the healer adds no retry on this infrastructure failure.
- Healing never runs in strict mode: a failed cached step is at most classified, never regenerated
- Interactive steering attempts are separate from healing: they consume no budgets, join the same per-step history and report their own healings

## Verdicts

Every terminal failure carries its verdict in full and the full underlying error in the error field: the exception
message is the structured render — the first line carries the class name of the terminal failure and the authored
reason, then the `---` separated step/error section, the conditional received/cause/Call log details section and the
unpadded verdict block; the same text reaches on_step_verdict (structured fields) and the log record. IncurableStepError
also carries the failed step code in the code field — a programmatic field, never rendered.
