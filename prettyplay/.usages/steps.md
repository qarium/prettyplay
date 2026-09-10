# Writing steps

Domain: authoring UI tests as plain sentences. Audience: engineers writing tests and integrators wiring the library into a test framework.

## A test as a scenario

```python
from prettyplay import PrettyTest


def test_login():
    t = PrettyTest("login-flow")
    t.action("open the login page")
    t.action("enter the login and password")
    t.action("click the «Sign in» button")
    t.assertion("the «Welcome back» message appears")
    t.close()
```

Or with the context manager:

```python
with PrettyTest("login-flow") as t:
    t.action("open the login page")
```

## Step kinds

- action(text) — performs what the sentence says
- assertion(text) — verifies what the sentence says; a legitimately failed expectation fails the test as a product defect

## Screenshots

Two author-facing abilities on the test object:

```python
with PrettyTest("login-flow") as t:
    t.action("open the login page")
    png = t.get_screenshot()  # full-page PNG bytes of the current state
    t.save_screenshot("artifacts/home.png")  # write full-page PNG to an explicit path
```

- Both require an opened page: call them after the first step of the test
- Nothing is captured automatically on failures — attaching screenshots to reports is the author's decision

## Addressing

The constructor arguments form the cache address: cache_key (mandatory) and cache_path (optional subdirectory). Equal cache keys in the shared root reuse one cached step across tests; a different language, step type or key is a different step. User instructions (generation_prompt, classification_prompt) take no part in the address — a cached step never regenerates because the instructions changed.

## What you see

Step sentences go to the logger prettyplay at info level — the suite output reads as a plain-language scenario. A failed step renders one structured message — the primary reason, the step and the full underlying error, the verdict — identical in the runner output, the log and the on_step_failed hook. Healing, cache writes and skipped writes are reported loudly through the same logger.

## Limitations

Step sentences land in the repository cache, the logs and the LLM requests: never put secrets or personal data into a step.
