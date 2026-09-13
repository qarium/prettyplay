# Step generation

Domain: generating executable code for an unknown step. Audience: library internals and engineers debugging a first run.

## Generate a step

```python
step = generator.generate(
    identity=identity,
    step_text="click the «Sign in» button",
    previous_steps=["open the login page", "enter the login and password"],
    page=page,
    window=window,
)
```

- The loop: request code → execute against the live page → on failure re-request with the fresh error and snapshot
- Every candidate execution runs under the settle window: transient failures re-execute the same code inside the window (settle_retry log records), no LLM budget consumed; deterministic failures go to the next request or classification
- A non-empty generation_prompt setting adds a USER INSTRUCTIONS block to every generation and regeneration request; classification requests never carry it; changing the instructions never invalidates the cache — cached steps run as stored
- A non-empty classification_prompt setting adds a USER INSTRUCTIONS block to classification requests only; generation requests never carry it
- Every generation and regeneration request carries the CHEAT SHEET block right before the USER INSTRUCTIONS block — the compact standard Playwright sync API reference carried by every request; guidance, not an allowlist: everything standard stays allowed, the error-driven regeneration loop is the second line of defense

## The execution boundary

The whole step executes inside the driver worker thread as one unit: compile and resolve stay on the calling thread,
the step call itself runs in the worker and receives the genuine sync Page — the calling thread never touches
Playwright, so interactive hosts keep working. An AssertionError of a step — a failed expect chain or a plain assert
on an immediate read — reaches failure classification untouched.

## The decision table

Every classification verdict drives the same table — the category decides, the path only delivers:

| Verdict | Action |
|---|---|
| product_defect | ProductDefectError carrying the verdict — loud, never healed |
| rot, fixable | regeneration carrying the classification recommendation |
| incurable | IncurableStepError carrying the verdict |

## Failed candidate check (bounded healing)

A failed check — an assertion that executed and did not hold, survived the settle window — is classified, then:

- product_defect → ProductDefectError with the verdict; one failed check is spent, never the whole budget
- rot or fixable → exactly one regeneration funded from the healing budget, the request carrying the recommendation as a RECOMMENDATION block; success stores the healed step; a repeat failure gets one final classification deciding only the terminal kind — product_defect → ProductDefectError, anything else → IncurableStepError; no further regeneration
- incurable → IncurableStepError with the verdict
- LLM unavailable at the classification → the verdict is skipped quietly (WARNING in the log) and IncurableStepError raises without it

## The instruction compliance gate

Every successfully executed candidate is verified against the generation_prompt
instructions before it is cached — the default behavior; switch it off with
generation_approve = false:

- one verdict request per candidate through the provider (the effective generation
  model); zero requests when the switch is off or the instructions are empty
- a high finding fails the attempt: the retry request carries the violation text as its
  ERROR, so the model fixes it targeted; budget exhaustion with a standing high finding
  is the terminal incurable failure naming the violated instruction
- medium and low findings pass with a WARNING naming the instructions
- a malformed verdict (ComplianceVerdictError) and provider unavailability
  (LLMUnavailableError) are hard failures — a candidate is never cached unchecked
- replayed cached code is never re-gated: changing the instructions does not invalidate
  the cache — purge it manually when the instructions change

## Budget exhaustion

Exhaustion of the generation attempts classifies the last candidate: rot or fixable grants exactly one extra
recommendation-carrying regeneration funded from the healing budget — a repeat failure is terminal
IncurableStepError without reclassification; any other verdict is terminal as before. LLM unavailability at this
classification skips the verdict quietly.

## Classification call

Both engines classify through one routine:

```python
from prettyplay.engine import classify_step_failure

classification = classify_step_failure(
    config=config,
    provider=provider,
    step_text="click the «Sign in» button",
    code=step_code,
    error="element not found: button «Sign in»",
    page=page,
)
```

The routine collects the fresh page snapshot (plus the screenshot when enabled) and calls the provider with the engine classification prompt; a non-empty classification_prompt setting of the config reaches the request as a USER INSTRUCTIONS block. The category set is four: rot, product_defect, fixable, incurable. Provider unavailability propagates: the calling path decides whether it is a terminal infrastructure failure or a quiet verdict skip.

## The fixed form

Generated code is one function receiving exactly one argument — the genuine Playwright sync Page — importing only
from playwright.sync_api and working through the standard API: `page.get_by_role("button", name="Sign in").click()`,
`page.locator("form > button.primary")`, `videos = page.get_by_role("listitem")` with
`expect(videos.first).to_be_visible()` and `assert videos.count() > 1`,
`with page.expect_event("dialog") as info: ... info.value.accept()`,
`with page.expect_popup() as popup_info: ... popup_info.value`,
`page.frame_locator("#checkout").get_by_role("button", name="Pay").click()`,
`locator.scroll_into_view_if_needed()`, `page.mouse.wheel(0, 600)`. No provider constructs, no fixed delays, no
page.close()/context.close(), no stateful actions (route, clock, add_init_script, tracing, HAR, CDP) — the prompt
rules; the runtime never enforces them.
