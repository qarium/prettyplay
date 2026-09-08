# Writing steps

Domain: authoring UI tests as plain sentences. Audience: engineers writing tests and integrators wiring the library into a test framework.

## A test as a scenario

```python
from prettyplay import PrettyTest


def test_login():
    t = PrettyTest("login-flow")
    t.action("открыть страницу логина")
    t.action("ввести логин и пароль")
    t.action("нажать «Войти»")
    t.assertion("появилась надпись «Добро пожаловать»")
    t.close()
```

Or with the context manager:

```python
with PrettyTest("login-flow") as t:
    t.action("открыть страницу логина")
```

## Step kinds

- action(text) — performs what the sentence says
- assertion(text) — verifies what the sentence says; a legitimately failed expectation fails the test as a product defect

## Addressing

The constructor arguments form the cache address: cache_key (mandatory) and cache_path (optional subdirectory). Equal cache keys in the shared root reuse one cached step across tests; a different language, step type or key is a different step.

## What you see

Step sentences go to the logger prettyplay at info level — the suite output reads as a plain-language scenario. Healing, cache writes and skipped writes are reported loudly through the same logger.

## Limitations

Step sentences land in the repository cache, the logs and the LLM requests: never put secrets or personal data into a step.
