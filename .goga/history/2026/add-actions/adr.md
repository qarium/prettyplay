---
status: accepted
date: 2026-09-11
---

# Full Playwright parity for the generation API surface

Generated step code works only through the `PageFacade`/`LocatorFacade` surface, and the exact
listing of that surface is sent to the LLM as PAGE API. Real scenarios kept failing on missing
actions — the motivating case: generated code called a non-existent `press` on a located element.
The LLM assumes Playwright's API because that is what it knows, so every divergence between the
facade and Playwright is a latent failure. We decided to move the facade from a narrow curated
surface to **full parity with the Playwright sync API at page/locator level**, mirroring Playwright
names 1:1 across the whole surface — including renaming existing methods (`find_by_role` →
`get_by_role`, `open` → `goto`) — because name divergence was the exact source of the motivating
failure. Backward compatibility is dropped entirely: it is not a concern for this break and is not
adopted as a policy going forward.

## Decision points

- **Boundary**: the full user-level contour — all interaction actions (keyboard including `press`,
  hover, checkbox/radio, clear, double/right click, drag&drop, file upload), all navigation
  (`goto`/back/forward/reload), the full expectation and wait set (value, checked, count,
  attribute, hidden, URL, title, wait_for), dialogs, iframes, tabs/popups with switching.
  Deliberately excluded: network interception (route/request), arbitrary JS (`evaluate`), CDP,
  clock, HAR, tracing — the page-state model that failure classification and healing rely on must
  stay honest.
- **Names**: the whole surface mirrors Playwright names 1:1; existing methods are renamed to their
  mirror counterparts. New Playwright capabilities arriving later are expected to land as mirror
  extensions.
- **Extras**: the prettyplay-specific scroll family (`scroll_to_element`, `scroll_down`,
  `scroll_to_bottom`, `scroll_into_view`, `scroll_container_*`) stays on top of the mirror under
  its own names — power Playwright does not offer at this level.
- **Expectation model**: method-style `expect_*` calls on the facade with full coverage; the
  chained `expect(locator).to_be_*()` model of Playwright is not adopted — the fixed step form
  (one page-facade argument, no imports) forbids it.
- **Multi-page**: popups and new tabs are in scope, with switching to the opened window and back.
- **Delivery**: one change covering the whole surface at once, no phasing.
- **Step cache**: explicitly a non-decision — the cache can simply be deleted or healed lazily
  through the existing classify → rot → regenerate loop; no dedicated mechanism is built.
- **Dialogs**: automatic dialog acceptance (the `page.on("dialog", accept)` equivalent) becomes a
  setting of the browser group of `BrowserConfig`.

## Consequences

- The driver's standing constraint "the facade surface is a backward-compatibility contract —
  extend, never rename or remove" is retired; the parity principle replaces it.
- The `facade` practice, the PAGE API listing that mirrors it exactly, and the generation system
  prompt examples change together in one move.
- The facade remains a thread-marshaling wrapper over the driver thread: parity means names and
  capabilities, never exposing raw Playwright objects.
- Renamed methods make cached steps fail; the accepted answer is manual deletion or lazy healing —
  misclassification noise on AttributeError is an accepted cost.

## Unresolved questions (contract phase)

- The exact name mapping between the current surface and the Playwright mirror.
- The dialog expectation construct for scenarios that must verify a dialog, and the behavior when
  the auto-accept setting is off.
- The mechanism for tab/popup switching and for iframe access.
