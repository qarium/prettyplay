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

Generated code is one function receiving exactly one argument — the page facade — and working only through the facade surface: `page.get_by_role(...).click()`, `page.get_by_test_id("submit").click()`, `page.locator("form > button.primary")`, `page.locator("//button[@type='submit']")`, `page.get_by_role("row").first.expect_text("Paid")`, `page.get_by_role("listitem").filter(has_text="Product X").expect_visible()`, `element.expect_visible()`, `element.press("Enter")`, `with page.expect_dialog() as dialog: ...`, `with page.expect_popup() as popup: ...`, `page.frame_locator("#checkout").get_by_role("button", name="Pay").click()`, `page.scroll_down(600)` and alike. No provider constructs, no direct driver imports, no fixed delays.
