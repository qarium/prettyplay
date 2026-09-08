# Driver facade

Domain: the browser facade of prettyplay. Audience: consumers of the page API — the step generation engine and engineers reading or hand-writing step code.

The facade wraps the Playwright sync API. Step code receives a `PageFacade` and works only through it and `LocatorFacade` — never through raw Playwright objects. The method set is a backward-compatibility contract: cached step code keeps working across library upgrades.

## Surface

| Call | Purpose |
|---|---|
| page.open(url) | navigate and wait for load |
| page.find_by_role(role, name) | element by aria role and accessible name |
| page.find_by_label(label) | element by associated label |
| page.find_by_text(text) | element by visible text |
| page.aria_snapshot() | accessibility-tree page state |
| page.screenshot() | full-page PNG bytes |
| page.url | current URL |
| element.click() | click with auto-wait |
| element.fill(value) | set input text |
| element.select_option(value) | choose an option |
| element.expect_visible() | assert visible |
| element.expect_text(text) | assert text |
| element.expect_enabled() | assert enabled |

## Example

```python
page.open("https://example.com/login")
page.find_by_label("Логин").fill("user")
page.find_by_label("Пароль").fill("secret")
page.find_by_role("button", name="Войти").click()
page.find_by_text("Добро пожаловать").expect_visible()

snapshot = page.aria_snapshot()
```

## Rules

- Contexts are isolated per test; the browser process is shared per run
- Every call executes in the library's driver thread and returns when done: driving is strictly sequential, and the calling thread never adopts the Playwright event loop — hand-written step code stays safe in interactive hosts (IPython, Jupyter)
- Auto-wait everywhere: no time.sleep, no fixed delays in step code
- Never put secrets into step actions — step texts and code land in the repository cache
