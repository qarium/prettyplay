# Step generation

Domain: generating executable code for an unknown step. Audience: library internals and engineers debugging a first run.

## Generate a step

```python
step = generator.generate(
    identity=identity,
    step_text="click the «Sign in» button",
    previous_steps=["open the login page", "enter the login and password"],
    page=page,
)
```

- The loop: request code → execute against the live page → on failure re-request with the fresh error and snapshot
- A non-empty generation_prompt setting adds a USER INSTRUCTIONS block to every generation and regeneration request — the project's code style guidance (e.g. prefer data-test-id attributes); classification requests never carry it; changing the instructions never invalidates the cache — cached steps run as stored
- A failed check of a candidate (an assertion that executed and did not hold) stops the retries at once: the failure goes to classification — product_defect raises ProductDefectError with the verdict, anything else raises IncurableStepError with it; when the LLM is unavailable at this classification the verdict is skipped quietly (WARNING in the log) and IncurableStepError raises without it; one failed check is spent, never the whole budget
- Other candidate failures (element not found, timeouts) retry with the fresh error and snapshot
- Attempts are budgeted per step per test (default 3); exhaustion raises IncurableStepError carrying the classification verdict of the last candidate — when the LLM is unavailable the verdict is skipped quietly (WARNING in the log) and the failure raises without it
- A success stores the step in the cache and returns it
- Provider unavailability of a generation request raises LlmUnavailableError immediately — no retry on it

## Classification call

Both engines classify through one routine:

```python
from prettyplay.engine import classify_step_failure

classification = classify_step_failure(
    config=config, provider=provider,
    step_text="click the «Sign in» button", code=step_code,
    error="element not found: button «Sign in»", page=page,
)
```

The routine collects the fresh page snapshot (plus the screenshot when enabled) and calls the provider with the engine classification prompt. Provider unavailability propagates: the calling path decides whether it is a terminal infrastructure failure or a quiet verdict skip.

## The fixed form

Generated code is one function receiving exactly one argument — the page facade — and working only through the facade surface: page.find_by_role(...).click(), page.find_by_attribute("data-test-id", "submit").click(), page.find_by_css("form > button.primary"), page.find_by_xpath("//button[@type='submit']"), element.expect_visible(), page.scroll_down(600) and alike. No provider constructs, no direct driver imports, no fixed delays.
