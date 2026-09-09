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

## Browser matrix — engines and channels

The browser is selected from project configuration (`[tool.prettyplay]`), never hard-coded. The matrix is {chromium, firefox, webkit, chrome, msedge}: the first three are Playwright-bundled engines; chrome and msedge are channels launching the locally installed browser through the chromium engine:

```python
engines = {"chromium": p.chromium, "firefox": p.firefox, "webkit": p.webkit}
name = config.browser
engine = engines["chromium" if name in ("chrome", "msedge") else name]
browser = engine.launch(
    headless=config.headless,
    channel=name if name in ("chrome", "msedge") else None,
)
```

Rules:
- `headless` comes from configuration; the default is `True` — the current behavior
- A channel requires the real browser installed on user infrastructure: a missing browser fails loudly with an actionable message; engine binaries come from `playwright install` on user infrastructure — the package never bundles browsers

## Locators and auto-wait — never sleep

Playwright locators auto-wait for actionability. Step code expresses waits through locators and expectations only; fixed delays are forbidden:

```python
page.get_by_role("button", name="Sign in").click()
page.get_by_label("Login").fill("user")

from playwright.sync_api import expect

expect(page.get_by_text("Welcome back")).to_be_visible()
```

## Accessibility snapshot — primary LLM input

The a11y snapshot (structured accessibility-tree representation of the page) is the primary LLM context for generation and healing (ADR-7). It is cheap and stable compared to raw HTML:

```python
snapshot = page.locator("body").aria_snapshot()
```

## Scrolling — explicit programmatic scroll

Playwright auto-scrolls only as part of actions. Explicit scenario scrolling (scroll to an element, scroll by an amount, to the page end/start, inside a scrollable container) goes through the primitives:

```python
# bring an element into the viewport
locator.scroll_into_view_if_needed()

# scroll the page by an amount (down / up)
page.mouse.wheel(0, 600)
page.mouse.wheel(0, -600)

# scroll to the end / the start of the page
page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
page.evaluate("window.scrollTo(0, 0)")

# scroll inside a scrollable container (carousel)
container.evaluate("el => el.scrollTop += 400")
```

Rules: no fixed delays around scrolls — the scrolled state is awaited through locators and expectations.

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
