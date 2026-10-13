# Playwright skill

Battle-tested idioms for step code — a pattern library distilled from live generation runs.
Guidance, not an allowlist: everything standard stays allowed.
Derived in part from the microsoft/playwright agent prompts (Apache-2.0).

## Locators

Build locators from what the PAGE SNAPSHOT shows: it carries roles and accessible names, never
ids or classes — never invent a selector you have not seen. A role + accessible name locator is
the default: semantic, observable and resilient. A test-id, id or class wins when the snapshot
or the step text reveals it. A selector over attributes the snapshot cannot show — href
fragments, class chains — is an invented selector all the same.

```python
page.get_by_role("textbox", name="Search").fill("winter tires")
```

Prefer role + exact accessible name over bare text, and anticipate multiple matches — strict mode
fails any locator that resolves to several elements. Narrow by scoping to a container or by a
more exact `name=`; `.first` and `.nth()` are the last resort — they hide the ambiguity
instead of removing it.

```python
page.locator("#settings").get_by_role("button", name="Save changes").click()
```

An accessible name may be a long aria-label — the snapshot shows it verbatim. Never
shorten it to an invented label: match a stable fragment of the real name with a regex.

```python
page.get_by_role("button", name=re.compile(r"save", re.I)).click()
```

Filter a list-like locator by its text instead of matching the whole page.

```python
page.get_by_role("listitem").filter(has_text="Release notes").click()
```

Rows of a table address positionally; read the cell text with an immediate read.

```python
row = page.locator("#orders tbody tr").nth(2)
assert "gamma" in row.inner_text()
```

A positional item of any list — the third result, the second message — locates by role and
index, never by an attribute substring you cannot see.

```python
item = page.get_by_role("listitem").nth(2)
assert "Change log" in item.inner_text()
```

## Popups and overlays

After a popup, banner or overlay closes, it may still cover the target or steal focus: wait for
it to be hidden, then click the input once before filling — a fill on an unfocused input after
an overlay does not take.

```python
page.locator("#close-modal").click()
expect(page.locator("#modal")).to_be_hidden()
page.locator("#search").click()
page.locator("#search").fill("winter tires")
```

A dialog may trap focus while its script initializes — typing before that lands in the page
behind it. Click the dialog's title or container to pull the focus inside, then click the field
and type.

```python
page.locator("#modal-title").click()
field = page.locator("#modal-field")
field.click()
field.fill("the plan")
```

A consent dialog or banner may never appear at all — cookies already accepted, the locale
skipped it. When the step tolerates absence, click the button named in the PAGE SNAPSHOT — a
long aria-label matches by a stable fragment of its real name, never an invented short label —
with a short-but-fair timeout, and let the miss pass; a genuinely missed dismissal surfaces in
the next step and heals from there.

```python
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

try:
    page.get_by_role("button", name=re.compile(r"accept all", re.I)).first.click(timeout=5000)
except PlaywrightTimeoutError:
    pass
```

A control's label switches with the locale — chain the alternatives of the same control with
`.or_()` and a `.first` click (that is the intended use of `.first`: it picks whichever
alternative matched), and tolerate an already-gone state with count assertions. Never branch
with `if` in step code.

```python
page.get_by_role("button", name="Sign in").or_(page.get_by_role("button", name="Войти")).first.click()
```

```python
assert page.locator("#newsletter-opt-in").count() in (0, 1)
```

## Forms

Fill the field and press Enter — submit buttons often duplicate across the page and a click
lands in a strict-mode violation.

```python
page.locator("#search").fill("winter tires")
page.locator("#search").press("Enter")
expect(page.locator("#result")).to_have_text("submitted: winter tires")
```

Select an option by value or label.

```python
page.locator("#color").select_option("blue")
expect(page.locator("#color-result")).to_have_text("blue")
```

Checkboxes and radios go through check/uncheck, not through click — and the state asserts
explicitly.

```python
page.locator("#check").check()
expect(page.locator("#check")).to_be_checked()
```

```python
page.get_by_label("Large").check()
expect(page.locator("#size-result")).to_have_text("large")
```

Textareas fill like inputs; a label addresses the control it wraps.

```python
page.locator("#notes").fill("the plan")
expect(page.locator("#notes")).to_have_value("the plan")
```

A field may need activation before it accepts input — a click swaps in the real input or
unlocks it (lazy render, focus-trap). Click, wait for the activation — an enabled state, a
class, an attribute — then fill.

```python
page.get_by_role("button", name="Advanced search").click()
box = page.locator("#lazy-box.is-active")
expect(box).to_be_enabled()
box.fill("winter tires")
```

Type gradually when the page reacts per keystroke.

```python
page.locator("#search").press_sequentially("abc", delay=10)
assert page.locator("#search").input_value() == "abc"
```

Upload through the file input — a name and an in-memory buffer, no real file needed — and
never submit the form before the upload lands: wait for the page's confirmation (a preview
name, a checkmark) or the upload response.

```python
page.locator("#upload").set_input_files({"name": "data.txt", "mimeType": "text/plain", "buffer": b"hello"})
expect(page.locator("#upload-result")).to_have_text("uploaded: data.txt", timeout=10000)
```

## Dynamic content — match with regex

Only for text or URLs that rotate and localize: match a stable fragment case-insensitively with
`re.compile` (`import re` at the top of the code block, only when regex is actually used). For
stable text a plain exact locator is better than a regex. Never use glob URL patterns — `*` does
not cross `/` and query strings break them.

```python
page.get_by_text(re.compile(r"announcements", re.I)).first.click()
```

```python
page.locator("#account-link").click()
expect(page).to_have_url(re.compile(r"account(\.html)?\?id="))
```

A widget that renders after a delay needs a longer expect timeout, not a sleep.

```python
page.locator("#slow-btn").click()
expect(page.locator("#slow-result")).to_have_text("done", timeout=5000)
```

A transparent overlay or a spinner with pointer-events: none swallows clicks without any
error — wait for the loader to leave the DOM before acting. This synchronization sits BEFORE
the action: never append a check that confirms your own click — the next step carries its own
expectation.

```python
expect(page.locator("#spinner")).to_have_count(0)
page.locator("#fetch-btn").click()
```

Server-rendered HTML draws buttons before the JS bundle attaches their handlers — the first
click lands in dead markup. Let the first interaction wait for readiness: an enabled control
or a hydration marker.

```python
button = page.get_by_role("button", name="Checkout")
expect(button).to_be_enabled(timeout=10000)
button.click()
```

After an AJAX refresh (pagination, tab switch) the old DOM lingers briefly — never read the
new state through the stale element. Anchor on the change itself: the first row's text moved,
the page counter changed.

```python
page.get_by_role("button", name="Next page").click()
expect(page.locator("#orders tbody tr").first).not_to_have_text("alpha")
```

An element that disappears on action — wait for the detach, never for a fixed time.

```python
page.locator("#remove-btn").click()
expect(page.locator("#victim")).to_have_count(0)
```

Lists assert through counts.

```python
assert page.locator("#results li").count() >= 3
```

## Frames and shadow DOM

Content inside an iframe goes through `frame_locator` — locate elements within the returned
scope; nested frames chain.

```python
page.frame_locator("#frame").locator("#frame-btn").click()
expect(page.locator("#frame-result")).to_have_text("clicked")
```

CSS pierces open shadow roots — an id inside a custom element addresses directly.

```python
page.locator("#shadow-btn").click()
expect(page.locator("#shadow-result")).to_have_text("shadow done")
```

## Dialogs and new tabs

A JavaScript dialog must be handled before the triggering action completes — register the
handler first, then act; the handler resolves the dialog.

```python
page.once("dialog", lambda dialog: dialog.accept())
page.locator("#alert-btn").click()
```

A link or button opening a new tab captures through `expect_popup`; work on the new page.

```python
with page.expect_popup() as popup_info:
    page.locator("#new-tab").click()
popup = popup_info.value
expect(popup).to_have_title("Profile")
```

## Mouse and hover

Menus that open on hover need the hover first — the revealed item locates normally.

```python
page.locator("#menu").hover()
page.locator("#menu-open").click()
expect(page.locator("#menu-result")).to_have_text("opened")
```

A hover menu dies the moment the cursor moves toward its item. When the control supports it,
click the toggle instead — the open state then survives the movement.

```python
page.locator("#menu").click()
page.locator("#menu-open").click()
expect(page.locator("#menu-result")).to_have_text("opened")
```

Double-click goes through `dblclick`, never through two clicks.

```python
page.locator("#dbl-btn").dblclick()
expect(page.locator("#dbl-result")).to_have_text("double")
```

Drag and drop goes through `drag_to`.

```python
page.locator("#drag-src").drag_to(page.locator("#drop-zone"))
expect(page.locator("#drop-result")).to_have_text("dropped")
```

Scroll a distant element into view before interacting; wheel-scroll for the page itself.

```python
page.locator("#bottom").scroll_into_view_if_needed()
assert page.locator("#bottom").is_visible()
```

In an infinite feed the target is not in the DOM until scrolled into existence — a page-level
scroll misses the container. Wheel inside the feed in bounded steps and let the locator wait
for the row to appear.

```python
feed = page.locator("#feed")
for _ in range(10):
    feed.hover()
    page.mouse.wheel(0, 400)
expect(page.get_by_text("final entry")).to_be_visible(timeout=10000)
```

## Network

Verify the request an action fires — capture it around the action, read the method and payload.

```python
with page.expect_request(re.compile(r"/api/orders")) as request_info:
    page.locator("#order-btn").click()
assert request_info.value.method == "POST"
assert "winter" in request_info.value.post_data
```

Read the answer the page consumed — status and body through the captured response.

```python
with page.expect_response(re.compile(r"/api/quote")) as response_info:
    page.locator("#fetch-btn").click()
assert response_info.value.status == 200
assert response_info.value.json()["price"] > 0
```

Search-as-you-type races its own responses — the stale answer of a short prefix can
overwrite the full query's. Type at a human pace and anchor on the response to the final
query before reading the results.

```python
box = page.get_by_role("textbox", name="Filter")
box.press_sequentially("winter tires", delay=30)
with page.expect_response(re.compile(r"/api/search")) as response_info:
    box.press("Enter")
assert response_info.value.json()["query"] == "winter tires"
expect(page.locator("#live-result")).to_contain_text("winter tires")
```

Mock one request — route it to a fulfilled answer and remove the route before the step ends;
the try/finally guarantees the unroute even when the step fails. A route without its unroute is
forbidden.

```python
page.route(re.compile(r"/api/quote"), lambda route: route.fulfill(json={"price": 1}))
try:
    page.locator("#fetch-btn").click()
    expect(page.locator("#fetch-result")).to_contain_text("1")
finally:
    page.unroute(re.compile(r"/api/quote"))
```

## Assertions

A regex matches more than you planned — on a content page the same fragment hits the main
heading and every related card, and a visibility assertion on a multi-match locator dies in
strict mode. Scope the assertion to a unique anchor — the heading level, a container — or
assert containment on the region instead of visibility of one element.

```python
expect(page.get_by_role("heading", level=1)).to_contain_text(re.compile(r"announcements", re.I))
```

Never assert with the same text that located the element — `get_by_text("Saved").to_have_text("Saved")`
is a tautology that always passes. A text-based locator asserts visibility; a text assertion needs
a non-text anchor: role, label, test-id.

```python
box = page.get_by_role("textbox", name="Search")
box.fill("winter tires")
box.press("Enter")
banner = page.get_by_role("status")
expect(banner).to_contain_text("submitted")
```

Input state asserts through value matchers, not through page text.

```python
box = page.get_by_role("textbox", name="Search")
box.fill("winter tires")
expect(box).to_have_value("winter tires")
box.fill("")
expect(box).to_be_empty()
```

A partial accessibility snapshot — a fragment of the very snapshot the request carries — is the
most robust whole-region assertion; the fragment matches any region, regex entries absorb
unstable values.

```python
expect(page.locator("#results")).to_match_aria_snapshot("""
  - listitem: Release notes 2.4
""")
```

## Waits and assertions

Locators and expect chains auto-wait — no fixed delays, no `wait_for_timeout`, no `networkidle`.
Use expect chains for dynamic content and plain asserts only on immediate reads.

Action steps and assertion steps end differently. An action ends at its action: goto opens,
click clicks, fill fills — a trailing check confirming the action's own completion (the URL
landed after goto, the dialog closed after its close-click) is forbidden; the next step brings
its own expectation. An expect belongs to a step only when the step sentence itself names the
outcome to observe — and it observes the page state, never the action that produced it.

```python
expect(page.locator("#results")).to_contain_text(re.compile(r"release notes", re.I))
```

An attribute read is an immediate read — the idiom for a RESULTS step that must return a value
the page carries on an element.

```python
row = page.locator("#orders tbody tr").nth(0)
order_id = row.get_attribute("data-id")
assert order_id == "a-100"
```

## Imports

Global only, at the top of the code block before `def step`: `playwright.sync_api` and the
Python standard library. Never import inside the function body and never call `__import__`.
Import only what this very step uses — an unused import is dead weight that fails the gate.
