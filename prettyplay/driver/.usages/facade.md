# Driver facade

Domain: the browser facade of prettyplay. Audience: consumers of the page API — the step generation engine and engineers reading or hand-writing step code.

The facade wraps the Playwright sync API. Step code receives a `PageFacade` and works only through it and `LocatorFacade` — never through raw Playwright objects. The method set is a backward-compatibility contract: cached step code keeps working across library upgrades. Each context opens with the screen mode configured in the browser group — the facade surface itself is identical in every mode.

## Surface

| Call | Purpose |
|---|---|
| page.open(url) | navigate and wait for load |
| page.find_by_role(role, name) | element by aria role and accessible name |
| page.find_by_label(label) | element by associated label |
| page.find_by_text(text) | element by visible text |
| page.find_by_attribute(name, value) | element by attribute value — data-* attributes |
| page.find_by_css(selector) | element by CSS selector |
| page.find_by_xpath(xpath) | element by XPath expression |
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
| element.click() | click with auto-wait |
| element.fill(value) | set input text |
| element.select_option(value) | choose an option |
| element.expect_visible() | assert visible |
| element.expect_text(text) | assert text |
| element.expect_enabled() | assert enabled |

## Example

```python
page.open("https://example.com/login")
page.find_by_label("Username").fill("user")
page.find_by_label("Password").fill("secret")
page.find_by_role("button", name="Sign in").click()
page.find_by_text("Welcome back").expect_visible()

# locating by data attributes, CSS and XPath
page.find_by_attribute("data-test-id", "submit-button").click()
page.find_by_css("form > button.primary").expect_enabled()
page.find_by_xpath("//button[@type='submit']").expect_visible()

# scroll scenarios
page.scroll_down(600)
page.find_by_text("Footer").expect_visible()

cards = page.find_by_role("list", name="Recommendations")
page.scroll_container_down(cards, 400)
page.find_by_text("Fifth card").expect_visible()

snapshot = page.aria_snapshot()
```

## Rules

- One browser process per test: each test owns its browser through its runtime; contexts stay isolated
- Every call executes in the library's driver thread and returns when done: driving is strictly sequential, and the calling thread never adopts the Playwright event loop — hand-written step code stays safe in interactive hosts (IPython, Jupyter)
- Auto-wait everywhere: no time.sleep, no fixed delays in step code — including around scrolls: the scrolled state is awaited through locators and expectations
- The screen mode of the browser group (empty, WxH, fullscreen, device name) changes only how the context opens — never the facade surface; step code is identical in every mode
- Never put secrets into step actions — step texts and code land in the repository cache
