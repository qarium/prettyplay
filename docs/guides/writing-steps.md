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

## Stateful page actions — the escape hatch

Some actions stay out of generated code because they outlive a step on the
page shared by the whole test: network interception (`page.route`), the
clock (`page.clock`), `add_init_script`, tracing, HAR, CDP. They belong to
the author, executed explicitly through `run_on_page`:

```python
with PrettyPlay("login-flow") as t:
    t.step("open the login page")

    def stub_the_api(page):  # runs inside the driver worker thread, on the genuine page
        page.route("**/api/config", lambda route: route.fulfill(json={"mode": "demo"}))

    t.run_on_page(stub_the_api)
    t.step("the dashboard renders in demo mode")
```

- The action receives the genuine sync `Page` and runs sequentially with
  every step — the same primitive step code crosses through
  (see [Driver facade](../reference/driver-facade.md))
- Requires an opened page: call it after the first step — before that a
  loud `PrettyplayError` raises
- The outcome returns as-is; an exception inside the action propagates
  untouched

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

## What the generated code looks like

The step sentence stays a plain sentence; the generated code is standard
Playwright sync API running on the genuine page — see
[Driver facade](../reference/driver-facade.md):

```python
from playwright.sync_api import expect

# «open the login page and sign in»
page.goto("https://example.com/login")
page.get_by_label("Username").fill("user")
page.get_by_role("button", name="Sign in").click()
expect(page.get_by_text("Welcome back")).to_be_visible()

# «the page shows a list of videos» — count forms
videos = page.get_by_role("listitem")
expect(videos.first).to_be_visible()
assert videos.count() > 1

# «click «Delete» and accept the confirmation dialog»
with page.expect_event("dialog") as info:
    page.get_by_role("button", name="Delete").click()
info.value.accept()

# «click «Open docs» — the documentation opens in a new tab»
with page.expect_popup() as popup_info:
    page.get_by_role("link", name="Open docs").click()
popup = popup_info.value
popup.bring_to_front()

# «click «Pay» inside the embedded checkout frame»
checkout = page.frame_locator("#checkout")
checkout.get_by_role("button", name="Pay").click()

# «scroll down until the footer shows»
page.mouse.wheel(0, 600)
expect(page.get_by_text("Footer")).to_be_visible()
```

Dialogs that no in-step capture claims are resolved by the driver's
resolver of last resort — accepted when the `accept_dialogs` browser
setting is on, explicitly dismissed when off — see
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
- Only a success is stored in the cache — and only after it passes the
  instruction compliance gate (`generation_approve`, default on): a `high`
  finding of the verdict fails the attempt and the retry carries the
  violation, `medium` and `low` findings pass with a `WARNING`, a malformed
  verdict is a loud `ComplianceVerdictError`. See
  [Configuration](../configuration.md#the-instruction-compliance-gate)
- Provider unavailability of a generation request raises
  `LLMUnavailableError` immediately — no retry on it

A non-empty `generation_prompt` setting adds a `USER INSTRUCTIONS` block to
every generation and regeneration request — the project's code style guidance
(e.g. `prefer data-test-id attributes`), binding for the generated code while
the compliance gate is on; classification requests never carry
it. The instructions are not part of the cache address: changing them never
invalidates cached steps — replayed code is never re-gated, so changed
instructions need a manual cache purge to take effect.

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
