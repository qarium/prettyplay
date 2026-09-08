# Step generation

Domain: generating executable code for an unknown step. Audience: library internals and engineers debugging a first run.

## Generate a step

```python
step = generator.generate(
    identity=identity,
    step_text="нажать «Войти»",
    previous_steps=["открыть страницу логина", "ввести логин и пароль"],
    page=page,
)
```

- The loop: request code → execute against the live page → on failure re-request with the fresh error and snapshot
- Attempts are budgeted per step per run (default 3): exhaustion raises IncurableStepError
- A success stores the step in the cache and returns it
- Provider unavailability raises LlmUnavailableError immediately — no retry on it

## The fixed form

Generated code is one function receiving exactly one argument — the page facade — and working only through the facade surface: page.find_by_role(...).click(), element.expect_visible() and alike. No provider constructs, no direct driver imports, no fixed delays.
