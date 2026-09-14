# Driver facade

The browser driver of prettyplay. For engineers reading or hand-writing
step code and integrators reasoning about where step code executes.

Generated step code works through the standard Playwright sync API on the
genuine `Page` — prettyplay ships no page API of its own. What the library
owns is the boundary that code crosses: the whole step executes inside the
driver worker thread as one unit, and the calling thread never touches
Playwright. This page documents the internal page handle, the worker
boundary and the generated-code contour.

## The worker boundary

The whole Playwright session — start, browser, contexts, pages — lives in
one dedicated driver thread owned by the library. The only crossing point
of that boundary is the run primitive of the internal page handle:

```python
result = page.run(action)  # action(page) executes wholly inside the worker
```

- The action receives the genuine sync `Page` and its outcome returns
  as-is; an exception inside the action propagates to the caller untouched
- The calling thread never adopts the Playwright event loop — hand-written
  code stays safe in interactive hosts (IPython, Jupyter)
- The callable runs sequentially with every other unit: one unit at a time
- Playwright objects never cross back through the result — plain data only

## The internal page handle

`PageFacade` (exported from `prettyplay.driver`) is the runtime plumbing
handle of a single test page — not the API of step code. Exactly four
members:

| Call | Purpose |
|---|---|
| `page.run(action)` | execute the callable inside the worker thread; receives the genuine sync `Page` |
| `page.aria_snapshot()` | accessibility-tree page state — the primary LLM input |
| `page.screenshot()` | full-page PNG bytes |
| `page.close()` | close this page's isolated context |

No member proxies, delegates or re-exports of page capabilities exist: the
handle is plumbing, not a managed surface. Everything step code does is a
standard Playwright call on the genuine page inside `run`. Each context
opens with the screen mode configured in the browser group — the handle and
the contour are identical in every mode.

## The generated-code contour

Step code is one function of the fixed form `def step(page) -> None:` —
compiled and resolved on the calling thread, then executed as one worker
unit against the genuine page:

```python
from playwright.sync_api import expect


def step(page):
    page.goto("https://example.com/login")
    page.get_by_label("Username").fill("user")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_text("Welcome back")).to_be_visible()
    assert "dashboard" in page.url
```

The contour:

- Standard Playwright sync API — locator factories (`get_by_role`,
  `get_by_label`, `get_by_text`, `locator`, ...), actions, `expect` chains
  for dynamic content, plain Python asserts on immediate reads
  (`assert videos.count() > 1`)
- Imports from `playwright.sync_api` only — a prompt rule, no hard gate;
  every generation and regeneration request carries the compact cheat sheet
  as guidance, never an allowlist
- Safety core: no `time.sleep`, no fixed delays — waits live in locators
  and expectations; never `page.close()` or `context.close()` — the runtime
  owns the page lifecycle
- Stateful actions stay out of generated code: `page.route`, `page.clock`,
  `add_init_script`, tracing, HAR, CDP are the author's explicit tools (see
  the escape hatch below)
- No provider constructs, no direct driver imports

## Dialogs

Step code captures a dialog through the stock Playwright event form:

```python
with page.expect_event("dialog") as info:
    page.get_by_role("button", name="Delete").click()
dialog = info.value
assert dialog.type == "confirm"
assert dialog.message == "Delete the item?"
dialog.accept()
```

A captured dialog is step-controlled. Dialogs no in-step capture claims are
resolved by the resolver of last resort: the driver registers one
record-only routing handler per page of the context before any step code
runs (registering a `dialog` listener disables Playwright's implicit
auto-dismiss), and at the tail of every driver-thread unit — each run
action and each plumbing call of the handle alike — every unclaimed dialog
is resolved exactly once, chained dialogs included: accepted when the
`accept_dialogs` browser setting is on, explicitly dismissed when off. The
drain of one unit is bounded: a page that fires a fresh dialog for every
resolution — an endless `while (true) alert()` loop — leaves the excess
pending for the next unit tail instead of holding the unit forever, so the
failure surfaces through the regular timeouts. The resolver never touches
a dialog an in-step capture handled and never masks the outcome of the
action — see
[Configuration](../configuration.md#dialogs).

## Popups, frames, scrolling — stock means

Popups and new tabs:

```python
with page.expect_popup() as popup_info:
    page.get_by_role("link", name="Open docs").click()
popup = popup_info.value
popup.bring_to_front()
expect(popup.get_by_role("heading", name="Documentation")).to_be_visible()
```

Iframes:

```python
checkout = page.frame_locator("#checkout")
checkout.get_by_role("button", name="Pay").click()

inner = page.frame_locator("#outer").frame_locator("#inner")
expect(inner.get_by_text("Nested")).to_be_visible()
```

Scrolling:

```python
page.get_by_role("button", name="More").scroll_into_view_if_needed()
page.mouse.wheel(0, 600)
```

No fixed delays around scrolls — the scrolled state is awaited through
locators and expectations.

## The author escape hatch — `run_on_page`

```python
title = t.run_on_page(lambda page: page.title())
```

`t.run_on_page(action)` executes the author action wholly inside the driver
worker thread against the genuine page — the same primitive step code
crosses through, sequential with every step. The stateful actions excluded
from generated code (`page.route`, `page.clock`, `add_init_script`,
tracing, HAR, CDP) are the author's explicit tools here; the prompt rules
of generated code do not bind the author.

- Requires an opened page — run a step first: the page opens lazily on the
  first step, and a missing page raises a loud actionable `PrettyplayError`
- The action must use the page API only — calling back into the test
  object (`t.step`, screenshots, a nested `run_on_page`) marshals into the
  same worker thread the action runs on; the worker rejects the re-entrant
  crossing with a loud error instead of a deadlock
- The outcome returns as-is — plain data only; an exception inside the
  action propagates to the caller untouched

## Pollable failure kinds

The driver ships a fixed pollable map, exported as `is_pollable_failure(exc)`
from `prettyplay.driver`: it returns `True` when the exception kind is
transient page state — the settle window may re-execute the same code — and
`False` when the failure is deterministic or unknown, so it goes straight to
classification. Pollable: timeouts (`Timeout NNNms exceeded`), element state
(not visible, not enabled, outside the viewport, detached/stale), navigation
and context races (`Execution context was destroyed`, `Target closed`), and
plain `AssertionError`s of failed checks — a failed `expect(...)` chain or a
plain Python assert on an immediate read alike. Not pollable: locator
ambiguity (`strict mode violation` — deterministic), Python-level errors of
the step code itself, and unrecognized failures. The map is fixed in code: it
never reads settings and never asks an LLM. See
[Settle polling](settle-polling.md).

## Rules

- One browser process per test: each test owns its browser through its
  runtime; contexts stay isolated
- Every run unit executes in the library's driver thread and returns when
  done: driving is strictly sequential, and the calling thread never adopts
  the Playwright event loop
- Auto-wait everywhere: no `time.sleep`, no fixed delays in step code —
  the scrolled and loaded states are awaited through locators and
  expectations
- A locator resolving to several elements fails an action or expectation
  with the strict-mode violation — narrow positionally (`first`, `last`,
  `nth`) to address one match; over an `or_` composition the positional
  narrowing is the canonical guard when both branches may match
- The screen mode of the browser group (empty, WxH, fullscreen, device
  name) changes only how the context opens — never the contour; step code
  is identical in every mode
- Dialogs: an in-step stock capture claims its dialog; dialogs outside a
  capture follow the `accept_dialogs` browser setting
- No `page.route`, no `page.clock`, no `add_init_script`, no CDP, no HAR,
  no tracing in generated code — the author performs them explicitly
  through `run_on_page`
- Never put secrets into step actions — step texts and code land in the
  repository cache

!!! warning
    Never put secrets into step actions — step texts and code land in the
    repository cache.
