# Full Playwright sync API parity for the driver facade

## Current State

Generated step code works only through the `PageFacade`/`LocatorFacade` surface
(`prettyplay/driver/page.py`), and the exact listing of that surface is sent to the LLM as the
PAGE API (`PAGE_API_SURFACE` in `prettyplay/engine/generator.py`, mirroring
`prettyplay/driver/.usages/facade.md` verbatim). The current surface is narrow: `open`, six
locating methods (`find_by_role`, `find_by_label`, `find_by_text`, `find_by_attribute`,
`find_by_css`, `find_by_xpath`), `aria_snapshot`, `screenshot`, the `url` property, eight scroll
methods and `close` on the page level; `click`, `fill`, `select_option` and three expectations
(`expect_visible`, `expect_text`, `expect_enabled`) on the element level.

The driver CODEMANIFEST carries the standing constraint "the facade surface is a
backward-compatibility contract — extend, never rename or remove". Real scenarios kept failing
because the LLM assumes Playwright's API — the motivating case: generated code called a
non-existent `press` on a located element. Every divergence between the facade and Playwright is
a latent failure. `BrowserConfig` has no dialog setting; dialogs, iframes and popup/tab
switching do not exist on the facade at all.

## Description

Move the facade from the curated surface to **full parity with the Playwright sync API at
page/locator level**: the whole surface mirrors Playwright names 1:1, including renaming
existing methods to their mirror counterparts (`find_by_role` → `get_by_role`, `open` → `goto`).
Backward compatibility is dropped entirely — the parity principle replaces it, and future
Playwright capabilities are expected to land as mirror extensions. The prettyplay-specific
scroll family stays on top of the mirror under its own names. Dialogs, iframes and
popups/tabs with switching enter the contour; automatic dialog acceptance becomes a setting of
the browser group of `BrowserConfig`. The facade remains a thread-marshaling wrapper over the
driver thread: parity means names and capabilities, never exposing raw Playwright objects. The
facade practice, the PAGE API listing that mirrors it exactly, and the generation system prompt
change together in one move.

Intent example — step code against the target surface (intent only; the exact name mapping is
resolved at the design stage):

```python
def step(page) -> None:
    page.goto("https://example.com/login")
    page.get_by_label("Username").fill("user")
    page.get_by_role("button", name="Sign in").click()
    page.get_by_role("textbox", name="Search").press("Enter")
    page.expect_url("**/dashboard")
```

## Scope

**In scope:**
- `prettyplay/driver` — CODEMANIFEST, `page.py`, `session.py`: rename the existing surface to
  its Playwright mirror; add the full mirror set — interaction actions (keyboard including
  `press`, `hover`, checkbox/radio `check`/`uncheck`, `clear`, double and right click, drag&drop,
  file upload), navigation (`goto`, `back`, `forward`, `reload`), the full expectation set
  (value, checked, count, attribute, hidden, url, title — method-style `expect_*` calls on the
  facade; the chained `expect(locator).to_be_*()` model is not adopted), the `wait_for` set,
  dialogs, iframe access, popups/new tabs with switching to the opened window and back; keep the
  scroll family under its own names; retire the backward-compatibility constraint in favor of
  the parity principle
- `prettyplay/config` — the browser group of `BrowserConfig` gains the dialog auto-accept
  setting: field with a neutral default, env override, layered merge, loud validation
- `prettyplay/engine` — `PAGE_API_SURFACE` and the `SYSTEM_PROMPT` rules mirror the new facade
  exactly
- `prettyplay/driver/.usages/facade.md` — rewritten surface table and examples
- MkDocs documentation — `docs/reference/driver-facade.md`, `docs/guides/writing-steps.md` and
  related pages updated to the new surface

**Out of scope:**
- Network interception (`route`/`request`), arbitrary JS (`evaluate`), CDP, clock, HAR, tracing —
  the page-state model that failure classification and healing rely on must stay honest
- Step-cache migration for renamed methods — the cache is deleted manually or healed lazily
  through the existing classify → rot → regenerate loop; no dedicated mechanism
- The async Playwright API
- New LLM provider capabilities

## Acceptance Criteria

- Every facade member name mirrors its Playwright sync API counterpart 1:1 at page/locator
  level, with only the declared non-mirror families excepted: the prettyplay scroll extras
  kept under their own names and the method-style `expect_*` expectation names replacing
  Playwright's chained `to_be_*` model; the old names (`open`, `find_by_*`) no longer exist
- The full user-level contour of the ADR boundary is covered: interaction actions including
  `press`, navigation, the full expectation set, the `wait_for` set, dialogs, iframes,
  popups/tabs with switching
- The excluded capabilities are absent from the surface: no route/request interception, no
  `evaluate`, no CDP, no clock, no HAR, no tracing
- The scroll family remains available under its own prettyplay names
- `PAGE_API_SURFACE` mirrors `facade.md` exactly and the `SYSTEM_PROMPT` rules match the new
  surface
- The browser group of `BrowserConfig` carries the dialog auto-accept setting with its env
  override participating in the layered merge
- No raw Playwright object crosses the facade boundary; every call marshals through the driver
  thread; the calling thread never adopts the Playwright event loop
- `facade.md` and the MkDocs pages reflect the new surface without contradictions
- Tests follow `conventions` (pytest, mirror structure); `ruff check` passes
- Cached steps calling renamed methods fail on AttributeError — accepted, no migration built

## Stack

- **Frameworks:** none beyond the existing — pure library change
- **Libraries:** playwright (sync API — existing hard dependency), pydantic v2 (config models),
  pytest + ruff (test and lint, existing)
- **Infrastructure:** none — no new dependency enters `pyproject.toml`

## External Dependencies

| Component | Usage file | Status |
|-----------|------------|--------|
| playwright | `.goga/usages/cooks/playwright.md` | updated — added interactions, dialogs, popups/tabs, frames, the full expectation set, waits |
| pydantic | `.goga/usages/cooks/pydantic.md` | existing — covers the nested browser-group pattern; example field list is declared illustrative |

## Risks and Constraints

- Renamed methods break cached step code — accepted cost per the ADR: manual deletion or lazy
  healing; misclassification noise on AttributeError is accepted
- Open contract questions must be resolved at the design stage before implementation: the exact
  name mapping between the current surface and the mirror, the dialog expectation construct for
  scenarios that must verify a dialog (and the behavior when auto-accept is off), the mechanism
  for tab/popup switching and for iframe access
- One atomic change: the facade, the PAGE API listing, the system prompt, the config setting and
  the docs must move together — a partial landing desynchronizes the listing from the facade
- The full-parity PAGE API listing multiplies the size of every generation and regeneration
  request — the accepted standing cost of the parity decision; the listing stays a single
  verbatim mirror of `facade.md`, never a hand-curated subset
- The thread-marshaling boundary extends to the new object kinds (popup pages, frame-scoped
  locators, dialog handling) — none may leak raw Playwright objects into step code
- Python 3.10+ compatibility; `conventions` rules apply (kw_only models, docstrings, relative
  imports)

## Scope Estimate

Single task, no decomposition — per the ADR ("Delivery: one change covering the whole surface at
once, no phasing"). The affected cells form one coupled work area inside the task: the renames,
the listing and the prompt cannot be delivered separately without breaking the mirror between
the facade and what the LLM sees.

## Existing Architecture

Affected cells:
- `prettyplay/driver` (major) — `PageFacade`, `LocatorFacade`, `DriverSession`: the surface
  rebuild, dialog handler wiring, popup/tab support
- `prettyplay/config` (small) — `BrowserConfig` browser group, `load_config` env override and
  merge paths
- `prettyplay/engine` (medium) — `StepGenerator` request inputs: `PAGE_API_SURFACE`,
  `SYSTEM_PROMPT`
- `prettyplay/driver/.usages/facade.md` — the practice consumed by the engine imports
- MkDocs pages under `docs/` that mirror the facade

Integration requirements: the engine imports the `facade` practice and mirrors it exactly; the
top-level facade (`PrettyPlay`, `StepExecutor`, `PrettyplayRuntime`) consumes `PageFacade` and
`open_page` — the signature of the page facade stays the fixed step-form argument, so the
top-level cell needs no contract change beyond what the new surface implies.

## Notes

- Decision record: `.goga/history/2026/add-actions/adr.md` (status: accepted, 2026-09-11) —
  this task formulates the ADR; in case of conflict the ADR wins
- The backward-compatibility constraint of the driver CODEMANIFEST is retired by this task; the
  parity principle replaces it and applies to future surface changes (no extend-only policy)
- The step-cache fate is an explicit non-decision of the ADR: delete or heal lazily, nothing
  dedicated is built
- `.goga/usages/cooks/playwright.md` was extended during this formulation (2026-09-11) with the
  patterns the implementation will rely on
