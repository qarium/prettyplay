# Writing steps

Domain: authoring UI tests as plain sentences. Audience: engineers writing tests and integrators wiring the library into a test framework.

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

- step(text) — performs what the sentence says
- expect(text) — verifies what the sentence says; a legitimately failed expectation fails the test as a product defect

## Author page access

The excluded-from-generation stateful actions are performed explicitly by the author — the callable runs wholly
inside the driver worker thread and receives the genuine sync Page:

    with PrettyPlay("videos-flow") as t:
        t.step("open the videos page")
        t.run_on_page(lambda page: page.route("**/api/videos", lambda route: route.fulfill(json={"items": []})))
        t.expect("the page shows a list of videos")

- Requires an opened page: call it after the first step — a loud error otherwise
- The callable returns plain data; Playwright objects (locators, handles, pages) never cross back to the calling thread
- Prompt rules do not bind the author: page.route, page.clock, tracing, HAR, CDP are the author's explicit tools
- The callable runs sequentially with the steps — the shared worker takes one unit at a time

## Screenshots

Two author-facing abilities on the test object:

```python
with PrettyPlay("login-flow") as t:
    t.step("open the login page")
    png = t.get_screenshot()  # full-page PNG bytes of the current state
    t.save_screenshot("artifacts/home.png")  # write full-page PNG to an explicit path
```

- Both require an opened page: call them after the first step of the test
- Nothing is captured automatically on failures — attaching screenshots to reports is the author's decision

## Addressing

The constructor arguments form the cache address: cache_key (mandatory) and cache_path (optional subdirectory). Equal cache keys in the shared root reuse one cached step across tests; a different language, step type or key is a different step. User instructions (generation_prompt, classification_prompt) take no part in the address — a cached step never regenerates because the instructions changed. Replayed cached code is never re-checked against the current instructions: purge the cache manually after changing them.

## What you see

Step sentences go to the logger prettyplay at info level — the suite output reads as a plain-language scenario. A failed step renders one structured message — the primary reason, the step and the full underlying error, the verdict — identical in the runner output, the log and the on_step_failed hook. Every step ends with one closing on_step_finished event (passed or failed). Healing, cache writes and skipped writes are reported loudly through the same logger. Transient failures absorbed by the settle window appear as settle_retry records — the step itself stays green.

## Limitations

Step sentences land in the repository cache, the logs and the LLM requests: never put secrets or personal data into a step.
