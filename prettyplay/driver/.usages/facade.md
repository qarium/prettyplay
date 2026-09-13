# Driver facade

Domain: the browser facade of prettyplay. Audience: consumers of the page API — the step generation engine and engineers reading or hand-writing step code.

The facade mirrors the Playwright sync API at page/locator level within the step-driving contour — locating, interactions, navigation, waits, expectations, dialogs, popups and frames. A covered capability carries its Playwright mirror name, with three declared non-mirror families: the prettyplay scroll extras (kept under their own names), the method-style expect_* expectation names (replacing Playwright's chained expect(locator).to_be_*() model) and the expect_dialog capture constructor (implemented over Playwright's expect_event("dialog") — the Python client ships no expect_dialog). Raw input devices (keyboard/mouse) stay outside the surface with the other excluded capabilities. Step code receives a PageFacade and works only through it, LocatorFacade, FrameFacade and DialogFacade — never through raw Playwright objects. Each context opens with the screen mode configured in the browser group — the facade surface itself is identical in every mode.

## Surface — page

| Call | Purpose |
|---|---|
| page.goto(url) | navigate and wait for the load state |
| page.go_back() | browser-history back |
| page.go_forward() | browser-history forward |
| page.reload() | reload and wait for the load state |
| page.wait_for_url(url) | wait until the URL matches a glob pattern |
| page.wait_for_load_state(state) | wait for load, domcontentloaded or networkidle |
| page.expect_url(url) | assert the URL matches a glob pattern |
| page.expect_title(title) | assert the title contains |
| page.get_by_role(role, name) | element by aria role and accessible name |
| page.get_by_label(label) | element by associated label |
| page.get_by_text(text) | element by visible text |
| page.get_by_placeholder(placeholder) | input by placeholder text |
| page.get_by_alt_text(alt) | image by alt text |
| page.get_by_title(title) | element by title attribute |
| page.get_by_test_id(test_id) | element by data-testid |
| page.locator(selector) | element by any selector — CSS, XPath, attribute |
| page.expect_dialog() | context manager — the block performs the triggering action; yields the DialogFacade |
| page.expect_popup() | context manager — the block performs the opening action; yields the popup as a full PageFacade |
| page.bring_to_front() | raise this page above the others — the switching primitive |
| page.pages | the open pages of the context, each a full PageFacade |
| page.frame_locator(selector) | the locating scope of one iframe — yields a FrameFacade |
| page.aria_snapshot() | accessibility-tree page state |
| page.screenshot() | full-page PNG bytes |
| page.url | current URL |
| page.scroll_to_element(element) | bring an element into the viewport (works inside scrollable ancestors) |
| page.scroll_down(pixels) | scroll the page down by an amount |
| page.scroll_up(pixels) | scroll the page up by an amount |
| page.scroll_to_bottom() | scroll to the end of the page |
| page.scroll_to_top() | scroll to the start of the page |
| page.scroll_into_view(element, container) | bring an element into view inside a specific scrollable container |
| page.scroll_container_down(container, pixels) | scroll a scrollable container down by an amount |
| page.scroll_container_up(container, pixels) | scroll a scrollable container up by an amount |
| page.close() | close this page's isolated context |

## Surface — dialog

| Call | Purpose |
|---|---|
| dialog.accept(prompt_text) | accept; prompt_text answers a prompt dialog (empty — no answer) |
| dialog.dismiss() | dismiss |
| dialog.type | alert, confirm, prompt or beforeunload |
| dialog.message | the dialog message |
| dialog.default_value | the prompt prefill of a prompt dialog |

## Surface — frame

| Call | Purpose |
|---|---|
| frame.get_by_role(role, name) — and the whole get_by_* family | locate inside the iframe |
| frame.locator(selector) | any selector inside the iframe |
| frame.frame_locator(selector) | the scope of a nested iframe |

## Surface — element

| Call | Purpose |
|---|---|
| element.first | the first match — positional narrowing |
| element.last | the last match — positional narrowing |
| element.nth(index) | the match at a 0-based index; negative counts from the end |
| element.filter(has_text=..., has_not_text=..., has=..., has_not=...) | narrow by content — all predicates optional |
| element.or_(other) | union locator — matches either; when both branches may match, compose positional narrowing (first, last, nth) to satisfy strict mode |
| element.and_(other) | intersection locator — matches both |
| element.click(button) | click; empty button = left, "right" = right button |
| element.dblclick() | double click |
| element.fill(value) | set input text |
| element.clear() | clear the input |
| element.press(key) | press a key or combination, e.g. "Enter", "Control+A" |
| element.check() | check a checkbox or radio |
| element.uncheck() | uncheck |
| element.hover() | hover |
| element.select_option(value) | choose an option |
| element.drag_to(target) | drag onto another element |
| element.set_input_files(path) | upload one file by filesystem path |
| element.expect_visible() | assert visible |
| element.expect_hidden() | assert hidden |
| element.expect_text(text) | assert text contains (substring, whitespace-normalized) |
| element.expect_enabled() | assert enabled |
| element.expect_value(value) | assert the input value |
| element.expect_checked() | assert the checkbox/radio state |
| element.expect_count(count) | assert the matched element count |
| element.expect_attribute(name, value) | assert the attribute value |

## Example

```python
page.goto("https://example.com/login")
page.get_by_label("Username").fill("user")
page.get_by_role("button", name="Sign in").click()
page.get_by_role("textbox", name="Search").press("Enter")
page.expect_url("**/dashboard")
```

Locating without accessible names:

```python
page.get_by_test_id("submit-button").click()
page.locator("form > button.primary").expect_enabled()
page.locator("//button[@type='submit']").expect_visible()
page.locator("[data-qa='row'] > input").fill("text")
```

Narrowing a locator — positional, content, combinators:

```python
page.get_by_role("row").first.expect_text("Paid")
page.get_by_role("listitem").last.expect_visible()
page.get_by_role("row").nth(2).expect_text("Shipped")
page.get_by_role("listitem").filter(has_text="Product X").expect_visible()
page.get_by_role("button").and_(page.get_by_text("Save")).expect_enabled()

# disjunction with the strict-mode guard — both texts may be present
page.get_by_text("one").or_(page.get_by_text("two")).first.expect_visible()
```

Dialogs:

```python
with page.expect_dialog() as dialog:
    page.get_by_role("button", name="Delete").click()
assert dialog.type == "confirm"
assert dialog.message == "Delete the item?"
dialog.accept()
```

A captured dialog is step-controlled — the accept_dialogs setting does not apply to it; dialogs outside a capture follow the setting (accept when on, dismiss when off).

Popups and new tabs:

```python
with page.expect_popup() as docs:
    page.get_by_role("link", name="Open docs").click()
docs.bring_to_front()
docs.get_by_role("heading", name="Documentation").expect_visible()
page.bring_to_front()
```

Iframes:

```python
checkout = page.frame_locator("#checkout")
checkout.get_by_role("button", name="Pay").click()

inner = page.frame_locator("#outer").frame_locator("#inner")
inner.get_by_text("Nested").expect_visible()
```

Interactions:

```python
page.get_by_role("checkbox", name="Subscribe").check()
page.get_by_role("img", name="Product").drag_to(page.get_by_role("list", name="Cart"))
page.get_by_label("Avatar").set_input_files("avatar.png")
page.get_by_role("button", name="Options").click(button="right")
```

Scroll scenarios:

```python
page.scroll_down(600)
page.get_by_text("Footer").expect_visible()

cards = page.get_by_role("list", name="Recommendations")
page.scroll_container_down(cards, 400)
page.get_by_text("Fifth card").expect_visible()

snapshot = page.aria_snapshot()
```

## Rules

- One browser process per test: each test owns its browser through its runtime; contexts stay isolated
- Every call executes in the library's driver thread and returns when done: driving is strictly sequential, and the calling thread never adopts the Playwright event loop — hand-written step code stays safe in interactive hosts (IPython, Jupyter)
- Auto-wait everywhere: no time.sleep, no fixed delays in step code — including around scrolls: the scrolled state is awaited through locators and expectations
- A locator resolving to several elements fails an action or expectation with the strict-mode violation — narrow positionally (first, last, nth) to address one match; over an or_ composition the positional narrowing is the canonical guard when both branches may match
- The screen mode of the browser group (empty, WxH, fullscreen, device name) changes only how the context opens — never the facade surface; step code is identical in every mode
- Parity, not exposure: mirroring Playwright never means exposing raw Playwright objects — every interaction stays a facade call marshaled through the driver thread, popup pages and frame scopes included
- No network interception, no evaluate, no CDP, no clock, no HAR, no tracing — these stay outside the facade
- Dialogs: an expect_dialog capture claims its dialog; dialogs outside a capture follow the accept_dialogs browser setting
- Never put secrets into step actions — step texts and code land in the repository cache
