# Playwright (Sync API) — Browser Driver Usage

Practices for the `playwright` library within prettyplay. Target audience: implementing agents working on the browser driver facade and step execution.

prettyplay drives the browser exclusively through Playwright's **sync API** (ADR-1, ADR-2). Playwright is a hard dependency of the package.

## Lifecycle — one browser process per test

`sync_playwright()` starts the driver. Every test owns its runtime: its own **browser process** and its own **isolated browser context** — no browser state is shared between tests through the library. Browser processes start lazily on the first step; every session registers its close with atexit, so all browsers stop before the process exits.

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

## Screen modes — viewport, fullscreen, device emulation

The `screen` setting of the browser group selects the single size mode; it applies at context creation:

```python
# fixed viewport — screen = "1280x720"
context = browser.new_context(viewport={"width": 1280, "height": 720})

# device emulation — screen = "iPhone 13"
with sync_playwright() as p:
    descriptor = p.devices["iPhone 13"]
context = browser.new_context(**descriptor)
# viewport, user_agent, touch, is_mobile, device_scale_factor — the full descriptor

# fullscreen on a local headed launch — screen = "fullscreen"
browser = engine.launch(headless=False, args=["--start-maximized"])  # chromium family
context = browser.new_context(no_viewport=True)  # the viewport follows the window
```

Rules:
- An empty `screen` keeps the Playwright default — the current behavior
- `WxH` and device descriptors apply in every launch mode: local headed, local headless, remote connect
- `fullscreen`: no window exists in headless mode or on a remote connect — the context is pinned to a fixed 1920×1080 viewport; on a local headed launch the window starts maximized and the viewport follows it (`no_viewport=True`)
- An unknown device name fails loudly with an actionable message suggesting close device names
- Device names resolve against the `devices` registry of the running Playwright — the package never hard-codes a device list

## Remote execution — ws endpoint connect

A set `browser_endpoint` (env `PRETTYPLAY_BROWSER_ENDPOINT`) switches the driver from a local launch to a connect over the Playwright ws endpoint — e.g. a Playwright Server or a hosted browser grid:

```python
engines = {"chromium": p.chromium, "firefox": p.firefox, "webkit": p.webkit}
engine = engines["chromium" if name in ("chrome", "msedge") else name]  # каналы — это chromium
browser = engine.connect(ws_endpoint)
```

Rules:
- An empty endpoint keeps the local launch — the current behavior
- `browser` still selects the engine type to connect to; channels (chrome, msedge) do not apply to a connect
- `headless` is ignored on a connect: window visibility is controlled by the endpoint server
- The endpoint is an address, not a secret: it is valid in the config file; CI rotation goes through the env override

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
- One browser process per test; no state shared between tests through the library
- All waits go through locators/expectations; `time.sleep` and fixed delays are forbidden
- `aria_snapshot()` is the default page representation sent to the LLM
- Browser binaries come from `playwright install` on user infrastructure; the package never bundles browsers
