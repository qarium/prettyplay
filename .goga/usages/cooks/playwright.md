# Playwright (Sync API) — Browser Driver Usage

Practices for the `playwright` library within prettyplay. Target audience: implementing agents working on the browser driver facade and step execution.

prettyplay drives the browser exclusively through Playwright's **sync API** (ADR-1, ADR-2). Playwright is a hard dependency of the package.

## Lifecycle — one isolated context per test

`sync_playwright()` starts the driver. One browser process serves the run; every test gets its own **isolated browser context** (R6: each test runs in its own context, independent of other tests).

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()

    context = browser.new_context()
    page = context.new_page()

    context.close()
    browser.close()
```

## Browser matrix — selection from configuration

MVP supports {Chromium, Firefox, WebKit} (ADR-1). The browser is selected from project configuration (`[tool.prettyplay]`), never hard-coded:

```python
browsers = {"chromium": p.chromium, "firefox": p.firefox, "webkit": p.webkit}
browser = browsers[config.browser].launch()
```

## Locators and auto-wait — never sleep

Playwright locators auto-wait for actionability. Step code expresses waits through locators and expectations only; fixed delays are forbidden:

```python
page.get_by_role("button", name="Войти").click()
page.get_by_label("Логин").fill("user")

from playwright.sync_api import expect

expect(page.get_by_text("Добро пожаловать")).to_be_visible()
```

## Accessibility snapshot — primary LLM input

The a11y snapshot (structured accessibility-tree representation of the page) is the primary LLM context for generation and healing (ADR-7). It is cheap and stable compared to raw HTML:

```python
snapshot = page.locator("body").aria_snapshot()
```

## Optional screenshot

Screenshots are an optional extra LLM input, enabled per project via `send_screenshots` (ADR-7):

```python
png_bytes = page.screenshot()
```

## Rules

- Sync API only; the async API is out of MVP scope (ADR-2)
- One browser context per test; no state shared between tests through the library
- All waits go through locators/expectations; `time.sleep` and fixed delays are forbidden
- `aria_snapshot()` is the default page representation sent to the LLM
- Browser binaries come from `playwright install` on user infrastructure; the package never bundles browsers
