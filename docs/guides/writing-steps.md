# Writing steps

Authoring UI tests as plain sentences. For engineers writing tests and
integrators wiring the library into a test framework.

## A test as a scenario

```python
from prettyplay import PrettyPlay


def test_login():
    t = PrettyPlay("login-flow")
    t.step("open the login page")
    t.step("enter the login and password")
    t.step("click the «Sign in» button")
    t.expect("the «Welcome back» message appears")
    t.close()
```

Or with the context manager:

```python
with PrettyPlay("login-flow") as t:
    t.step("open the login page")
```

## Step kinds

- `step(text)` — performs what the sentence says
- `expect(text)` — verifies what the sentence says; a legitimately failed
  expectation fails the test as a product defect

## Screenshots

Two author-facing abilities on the test object:

```python
with PrettyPlay("login-flow") as t:
    t.step("open the login page")
    png = t.get_screenshot()  # full-page PNG bytes of the current state
    t.save_screenshot("artifacts/home.png")  # write full-page PNG to an explicit path
```

- Both require an opened page: call them after the first step of the test
- Nothing is captured automatically on failures — attaching screenshots to
  reports is the author's decision

## Dialogs, popups and iframes

The step sentence stays a plain sentence; the generated code uses the
facade's capture constructs for dialogs and popups, and frame locators for
iframes — see [Driver facade](../reference/driver-facade.md):

```python
# «click «Delete» and accept the confirmation dialog»
with page.expect_dialog() as dialog:
    page.get_by_role("button", name="Delete").click()
dialog.accept()

# «click «Open docs» — the documentation opens in a new tab»
with page.expect_popup() as docs:
    page.get_by_role("link", name="Open docs").click()
docs.bring_to_front()
docs.get_by_role("heading", name="Documentation").expect_visible()

# «click «Pay» inside the embedded checkout frame»
checkout = page.frame_locator("#checkout")
checkout.get_by_role("button", name="Pay").click()
```

Dialogs that no `expect_dialog` block claims are handled by the
`accept_dialogs` browser setting — see
[Configuration](../configuration.md#dialogs).

## Addressing

The constructor arguments form the cache address: `cache_key` (mandatory) and
`cache_path` (optional subdirectory). Equal cache keys in the shared root
reuse one cached step across tests; a different language, step type or key is
a different step. User instructions (`generation_prompt`,
`classification_prompt`) take no part in the address — a cached step never
regenerates because the instructions changed. See
[Step cache](../reference/step-cache.md).

## How a step is generated

On a cache miss the generation engine produces a candidate and executes it
against the live page:

- The loop: request code → execute against the live page → on failure
  re-request with the fresh error and snapshot
- Attempts are budgeted per step per test (default 3); exhaustion raises
  `IncurableStepError` carrying the classification verdict of the last
  candidate
- A failed check of a candidate (an assertion that executed and did not hold)
  stops the retries at once: the failure goes through the bounded-healing
  decision table — `product_defect` raises `ProductDefectError` with the
  verdict, `incurable` raises `IncurableStepError` with it, and a `rot` or
  `fixable` verdict grants exactly one healing-funded regeneration carrying
  the classification recommendation; a repeat failure of that regeneration is
  terminal with one final classification deciding the kind; one failed check
  is spent, never the whole budget
- Other candidate failures (element not found, timeouts) retry with the fresh
  error and snapshot
- Only a success is stored in the cache
- Provider unavailability of a generation request raises
  `LLMUnavailableError` immediately — no retry on it

A non-empty `generation_prompt` setting adds a `USER INSTRUCTIONS` block to
every generation and regeneration request — the project's code style guidance
(e.g. `prefer data-test-id attributes`); classification requests never carry
it. The instructions are not part of the cache address: changing them never
invalidates cached steps.

## What you see

Step sentences go to the logger `prettyplay` at info level — the suite output
reads as a plain-language scenario. A failed step renders one structured
message — the primary reason, the step and the full underlying error, the
verdict — identical in the runner output, the log and the `on_step_failed`
hook. Healing, cache writes and skipped writes are reported loudly through the
same logger.

## Limitations

!!! warning
    Step sentences land in the repository cache, the logs and the LLM
    requests: never put secrets or personal data into a step.
