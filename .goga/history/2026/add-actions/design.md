# Design Document: `add-actions`

Topic: full Playwright sync API parity for the driver facade (`.goga/history/2026/add-actions/`).

The CODEMANIFEST layer already moved (stage apply-architecture): `prettyplay/config`,
`prettyplay/driver`, `prettyplay/engine` contracts carry the parity surface, `DialogFacade`,
`FrameFacade`, `accept_dialogs` and the rewritten `system_prompt` rules. This document designs
the **source-code implementation** — every file, member, algorithm, error path and test — that
brings the Python package to those contracts.

---

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/config/CODEMANIFEST` — `BrowserConfig` gains `accept_dialogs: bool` (param +
  property, neutral default False); env list gains `PRETTYPLAY_BROWSER_ACCEPT_DIALOGS`;
  `load_config` Algorithm step 5 and Requirements name five `PRETTYPLAY_BROWSER_*` variables;
  `Config.browser` param description and footer Description mention the dialog auto-accept switch.
- `prettyplay/driver/CODEMANIFEST` — `Imports` gains `Usages: [configuration]` from
  `prettyplay/config`; global annotations replace the backward-compatibility constraint with the
  parity principle (contour-scoped: locating, interactions, navigation, waits, expectations,
  dialogs, popups and frames; three declared non-mirror families — the scroll extras, the
  method-style expect_* names, and the `expect_dialog` capture constructor over Playwright's
  `expect_event("dialog")`, which the Python client ships under no other name) + the
  excluded-capabilities list (route/evaluate/CDP/clock/HAR/tracing/raw input devices) + the
  every-facade-kind thread-marshaling boundary; `DriverSession.open_context` gains the
  dialog-routing step 4 (context-scoped: `context.on("page", …)` wires one routing handler per
  page of the context — the open_context page and every popup/new tab; wrap becomes step 5);
  `PageFacade`/`LocatorFacade` rebuilt to the mirror
  surface; new `DialogFacade` and `FrameFacade`.
- `prettyplay/engine/CODEMANIFEST` — the inline `system_prompt` usage Rules rewritten: the
  Playwright-mirroring page API, label-or-placeholder locating, `get_by_test_id`/`locator(selector)`
  for nameless elements, dialog capture, popup/new-tab capture, iframe frame locators.

### New Entities

- `DialogFacade(dialog: Dialog)` — `prettyplay/driver/page.py`. The wrapped dialog captured by
  `expect_dialog`; properties `type`/`message`/`default_value`, methods `accept(prompt_text)` /
  `dismiss`.
- `FrameFacade(frame_locator: FrameLocator)` — `prettyplay/driver/page.py`. The frame-scoped
  locator factory: the `get_by_*` family, `locator(selector)`, nested `frame_locator(selector)`.

### Changed Entities

- `BrowserConfig` — new field `accept_dialogs: bool = False` (+ property, docstring).
- `load_config` — env override name, boolean parsing, allowed-text entry for the new field.
- `DriverSession.open_context` — step 4: register the single dialog routing handler on the page
  before any step code runs.
- `PageFacade` — `open` → `goto`; `find_by_role/label/text` → `get_by_role/label/text`;
  `find_by_attribute/css/xpath` removed; new: `go_back`, `go_forward`, `reload`, `wait_for_url`,
  `wait_for_load_state`, `expect_url`, `expect_title`, `get_by_placeholder`, `get_by_alt_text`,
  `get_by_title`, `get_by_test_id`, `locator`, `expect_dialog`, `expect_popup`, `bring_to_front`,
  `frame_locator`, property `pages`. Scroll family and `aria_snapshot`/`screenshot`/`url`/`close`
  unchanged.
- `LocatorFacade` — `click` gains the `button` parameter; new: `dblclick`, `clear`, `press`,
  `check`, `uncheck`, `hover`, `drag_to`, `set_input_files`, `expect_hidden`, `expect_value`,
  `expect_checked`, `expect_count`, `expect_attribute`; `expect_text` semantics stated as
  contains (unchanged implementation).
- `StepGenerator` (engine) — no signature change; the module constants `SYSTEM_PROMPT` and
  `PAGE_API_SURFACE` it feeds to every request change to the new contract texts.

### Deleted Entities

- `PageFacade.open`, `PageFacade.find_by_role`, `PageFacade.find_by_label`,
  `PageFacade.find_by_text`, `PageFacade.find_by_attribute`, `PageFacade.find_by_css`,
  `PageFacade.find_by_xpath` — replaced by the mirror names; the parity principle replaces the
  backward-compatibility constraint. Cached steps calling them fail on `AttributeError` —
  accepted per the task (lazy healing through the existing classify → rot → regenerate loop; no
  migration mechanism).

### Usages and Annotations Changes

- `.goga/usages/cooks/playwright.md` — added sections: interactions (keyboard via element
  `press`, advanced clicks, drag, upload — raw input devices stay outside the facade surface),
  dialogs routing and auto-accept (one routing handler per page of the context; registering any
  listener disables Playwright's implicit auto-dismiss — the handler itself resolves uncaptured
  dialogs; captures claim through `page.expect_event("dialog")` — the client ships no
  `expect_dialog`), popups and new tabs, frames and iframes, the full
  expectation set, waits. Applied by this design to every new facade member.
- `prettyplay/driver/.usages/facade.md` — rewritten to four surface tables (page/dialog/frame/
  element) + parity intro + dialogs/popups/iframes/interactions examples. This file is the
  single source `PAGE_API_SURFACE` mirrors.
- `prettyplay/config/.usages/configuration.md` — `accept_dialogs` in the TOML block, env table,
  layered-merge bullet, new Dialogs section.
- `prettyplay/engine/.usages/generation.md` — "The fixed form" section rewritten to the new
  surface.

## Applied Fixes

### Fixed in the Design Review (2026-09-11)

1. **expect_dialog arming call (Critical)** — playwright 1.62 ships no `Page.expect_dialog()`;
   the capture arms through `page.expect_event("dialog")` (identical `EventContextManager`
   machinery, identical timeout message naming event "dialog"); fakes updated accordingly. The
   facade member keeps the contract name `expect_dialog()`.
2. **Parity principle scoping (driver CODEMANIFEST + facade.md + playwright.md)** — the principle
   is contour-scoped (locating, interactions, navigation, waits, expectations, dialogs, popups,
   frames) with three declared non-mirror families (scroll extras, method-style expect_*,
   `expect_dialog` over `expect_event("dialog")`); raw input devices (keyboard/mouse) joined the
   excluded capabilities; the playwright practice's `page.keyboard` example replaced with element
   press.
3. **accept_dialogs scope (driver CODEMANIFEST + design)** — the routing handler now wires for
   **every page of the context** through the context page event (`context.on("page", …)` before
   `new_page()`), so uncaptured popup dialogs follow the setting; the shared router propagates to
   popup/`pages` facades; new tests (popup routing, popup capture claims through the shared
   router).
4. **playwright.md dialog section** — rewritten to the routing-handler semantics (any listener
   disables implicit auto-dismiss; unconditional handler; capture claims first).
5. **Gate-test contradiction on page.close()** — the facade-practice mirror test skips the
   `page.close()` row (32 listed page rows); the exclusion is pinned by the members-exist test
   alone.
6. **expect_popup timeout test gap** — `test_expect_popup_timeout_names_the_event` added.
7. **_DialogRouter shape pinned** — `handle_for(page)` closure per page; the router lives in
   `driver/page.py` (resolved together with fix 3).
8. **pydantic bool-coercion edge case** — file-layer `"yes"` lax-coerces to True; the actionable
   render fires for uncoercible values (`"maybe"`); env layer stays strict (wording fixed).
9. **Test registry** — the six llm/cache fixture files carrying retired names added with an
   opaque-string sweep instruction.

### Fixed CODEMANIFEST Defects

None. The Phase 3 audit found no DSL defects: `goga lint` reports 8 cells, 0 errors; document
structure, `location` directives (same-level `.py` files), unique member names, `PrettyplayError::`
mutation base, backtick-reference resolvability (including the two plain-text `expect_dialog`
mentions the apply stage de-backticked) and the config → driver → engine dependency direction all
verify. The four consistency dimensions (interface↔type, type↔mutation, interface↔interface,
annotations↔entity) pass — details in the traces below. No CODEMANIFEST edits were needed, so no
user approval round (Phase 3 Step 4) was required.

## Entity Interaction and Data Flow

### Interaction Diagram

```
                         pyproject.toml / env / PrettyConfig overrides
                                        |
                                  load_config (config/loader.py)
                                        |  Config.browser.accept_dialogs
                                        v
  StepExecutor ── page ──> DriverSession (driver/session.py)
                              |  open_context()
                              |    1-3 launch/connect + screen params + new_context    [driver thread]
                              |    4    context.on("page", λ p: p.on("dialog",        ┐
                              |         router.handle_for(p))); new_page() fires it   │
                              |    5    PageFacade(page, context) + worker + router  │
                              v                                                    │
                        PageFacade (driver/page.py)                                 │
                          goto / get_by_* / locator ──────> LocatorFacade            │
                          expect_url / expect_title ─────> expect(Page)              │
                          expect_dialog() ──> _DialogCapture ──> DialogFacade        │
                          expect_popup()  ──> _PopupCapture  ──> PageFacade (popup)  │
                          frame_locator() ──> FrameFacade ─────> LocatorFacade       │
                          pages ───────────> list[PageFacade]                        │
                              |                                                    │
                              | every call marshaled through PlaywrightWorker.run   │
                              +──────────── dialog event fires ─────────────────────┘
                                   router.handle: capture on this page? skip
                                   else accept_dialogs? accept : dismiss

  StepGenerator (engine/generator.py)
     SYSTEM_PROMPT (verbatim from engine CODEMANIFEST `system_prompt`)
     PAGE_API_SURFACE (verbatim mirror of driver `.usages/facade.md`)
     └─> provider.generate_step_code(...) ─> run_step_code(code, page)
```

### Data Flows

1. **Config load with the dialog setting** — `load_config` reads `[tool.prettyplay.browser]` →
   applies `PRETTYPLAY_BROWSER_ACCEPT_DIALOGS` (boolean parse) → constructs `BrowserConfig` with
   `accept_dialogs` → `_apply_overrides` group merge reaches the field. Flow unchanged apart from
   the one setting; the field rides the existing generic merge.
2. **Context opening with dialog routing** — `DriverSession.open_context` marshals into the
   driver thread: screen params → `new_context` → `_DialogRouter(accept_dialogs)` +
   `context.on("page", λ p: p.on("dialog", router.handle_for(p)))` → `new_page` (fires the event,
   registers its handler) → wrap into `PageFacade`, attach `_worker` and `_router`.
   `accept_dialogs` is read once from `self._config.browser` into the router; every page of the
   context — the open_context page and every later popup/new tab — routes uncaptured dialogs
   through it.
3. **Step code against the facade** — generated `def step(page)` calls the mirror surface; every
   call is `facade._call(fn)` → `PlaywrightWorker.run` (or inline for hand-built facades);
   located elements return `LocatorFacade` with inherited worker; expectations run
   `expect(locator).to_*` inside the driver thread and raise `AssertionError` on failure → the
   engine's failed-check path.
4. **Dialog flow, uncaptured** — action fires a dialog → Playwright dispatches to
   `router.handle` in the driver thread → no active capture on this page → `accept_dialogs`
   true: `dialog.accept()`; false: `dialog.dismiss()`.
5. **Dialog flow, captured** — `with page.expect_dialog() as dialog:` arms Playwright's
   `page.expect_event("dialog")` waiter and marks the router's capture page → action inside the block fires the
   dialog → `router.handle` skips (capture is on this page), Playwright's own waiter resolves →
   block exit waits and produces the raw `Dialog` → the bound `DialogFacade` initializes with it →
   the step reads `type`/`message` and calls `accept`/`dismiss`.
6. **Popup flow** — `with page.expect_popup() as popup:` arms `page.expect_popup()` → action
   opens the page → the context page event has already registered the routing handler on it →
   block exit resolves the raw `Page` → the bound `PageFacade` initializes with
   `(popup, popup.context)` and inherits the opener's worker and the shared context router →
   full surface on the popup, captures and routing included; `bring_to_front` / `pages` switch
   between pages.
7. **Generation request surface** — `StepGenerator._loop` passes `page_api=PAGE_API_SURFACE` and
   `prompt=SYSTEM_PROMPT` to the provider — both constants now mirror the contract texts; the LLM
   sees exactly the calls the facade offers.

### Entity Dependencies

Implementation order (leaf → root): `config/models.py` → `config/loader.py` →
`driver/page.py` (facades; imports nothing from config) → `driver/session.py` (imports `Config`)
→ `driver/__init__.py` exports → `engine/generator.py` constants → tests → docs. No import-graph
change beyond `DialogFacade`/`FrameFacade` exports; no new dependency enters `pyproject.toml`.

## Code Stack Trace

Checkpoint notation: `type` (types match the next step), `logic` (transformation correct),
`api` (usage conforms to the Playwright/pydantic API per usages). All checkpoints passed unless
marked.

### Trace: `BrowserConfig(accept_dialogs=True)` construction

#### Chain
1. **Input**: pydantic kw_only construction — TOML dict `{"accept_dialogs": True}` from the
   browser section, or `BrowserConfig(accept_dialogs=True)` programmatic.
2. **Step**: pydantic validates the field — plain `bool`, no validator needed (unlike `name` /
   `endpoint` / `screen`); default `False` keeps the group valid before the section exists →
   checkpoint `type`: bool field, neutral default per "every field has an empty or neutral
   default" — passed.
3. **Step**: `Config.browser: BrowserConfig = BrowserConfig()` default construction unchanged;
   the group grows one field — checkpoint `logic`: `extra="forbid"` unaffected — passed.
4. **Output**: `Config.browser.accept_dialogs: bool`.

#### Checkpoint Summary
- Interface↔type (`accept_dialogs` in signature, param list and property): passed — all three
  present in the CODEMANIFEST and now in the model.
- Contract boundary (`BrowserConfig` never resolves dialogs — routing belongs to the driver):
  passed — the field is a plain switch.

### Trace: `load_config` env override for `accept_dialogs`

#### Chain
1. **Input**: env `PRETTYPLAY_BROWSER_ACCEPT_DIALOGS=true`.
2. **Step**: `_ENV_NAMES` now maps `"browser.accept_dialogs"` → the variable name; the dotted key
   routes into `group_env` → merged into the `browser` section dict → checkpoint `api`: same
   mechanism as `browser.headless` — passed.
3. **Step**: `_parse_env_scalar` — `"browser.accept_dialogs"` in `_BOOL_ENV_SETTINGS` →
   `true/1/false/0` case-insensitive; unparseable raises `ConfigurationError` naming the setting,
   the received value and the accepted form → checkpoint `logic`: "never a silent ignore" —
   passed.
4. **Step**: `Config(**merged)` → pydantic validates; `_ALLOWED_TEXT["browser.accept_dialogs"] =
   "a boolean"` renders an actionable line on a type mismatch from the file layer (TOML
   `accept_dialogs = "maybe"` → pydantic bool coercion error; bool-like strings such as `"yes"`
   lax-coerce to True on the file layer, as for every other bool field — the env layer rejects
   them) → checkpoint `logic` — passed.
5. **Step**: `_apply_overrides` — `accept_dialogs` explicitly set in a passed `BrowserConfig`
   participates: the group-merge condition `(group_value or not isinstance(group_value, str))`
   includes `False` (bool is not str) → checkpoint `logic`: "an explicit False overrides too",
   identical to `strict` — passed.
6. **Output**: effective `Config` with the layered `accept_dialogs`.

#### Checkpoint Summary
- Requirements bullet "an env override exists for every setting … the five PRETTYPLAY_BROWSER_*
  variables": passed after the loader table grows the entry (test pins completeness).
- Interface↔interface (loader value type → `BrowserConfig` field type): passed.

### Trace: `DriverSession.open_context` (changed)

#### Chain
1. **Input**: first call of a test (lazy start) or a later call (browser already up).
2. **Step** (unchanged): `_launch` starts the worker thread, Playwright, and the engine — local
   launch with `headless`/channel, or ws connect; failure cleans up for a clean retry →
   checkpoint `api` — passed (existing code).
3. **Step** (unchanged): `_screen_context_params` resolves empty/WxH/fullscreen/device inside the
   driver thread → checkpoint `api` — passed.
4. **Step** (mostly unchanged): `new_context(**params)` inside the driver thread; `new_page()`
   moves after the dialog wiring of step 5 so the open_context page receives its handler through
   the context page event → checkpoint `type`: `(Page, BrowserContext)` tuple — passed.
5. **Step** (new, contract step 4): inside the same marshaled `open_isolated` call —
   `router = _DialogRouter(accept_dialogs=self._config.browser.accept_dialogs)`; the wiring goes
   through the context page event: `context.on("page", lambda p: p.on("dialog",
   router.handle_for(p)))` registered **before** `context.new_page()`, so the open_context page
   itself fires the event and registers exactly once; every later popup or new tab of the context
   registers the same way — one dialog handler per page, never two → checkpoint `api`: registering
   a `dialog` listener disables Playwright's implicit auto-dismiss, so the handler itself must
   resolve every uncaptured dialog — accept on the setting, else an explicit dismiss restoring the
   Playwright default — passed.
   → checkpoint `type`: the router is a plain Python object shared with the facade — passed.
6. **Step** (contract step 5): `facade = PageFacade(page, context)`; `facade._worker = worker`;
   `facade._router = router` (same attachment pattern `_worker` already uses) → checkpoint
   `logic`: the facade is handed to generated code only after the handler exists — "before any
   step code runs" — passed.
7. **Output**: `PageFacade` bound to the driver thread and the dialog router.

#### Checkpoint Summary
- Contract step numbering 1-5 matches the CODEMANIFEST Algorithm verbatim — passed.
- Constraints bullet ("facades stay untouched by the screen modes — changes live in context
  creation and dialog wiring only") — passed: facades receive the router; they never read config.

### Trace: dialog event → `router.handle` (new)

#### Chain
1. **Input**: Playwright dispatches `dialog` on a page of the context, inside whatever marshaled
   facade call triggered it (the handler body already runs in the driver thread — no marshaling
   inside).
2. **Step**: `if router.capture_page is self_page: return` — an armed `expect_dialog` on this
   page claims the dialog; Playwright's own waiter delivers it to the capture → checkpoint
   `logic`: per-page comparison, so a capture armed on a *popup* page never suppresses routing of
   a main-page dialog — passed.
3. **Step**: `elif router.accept_dialogs: dialog.accept()` → checkpoint `api` — passed.
4. **Step**: `else: dialog.dismiss()` — with the listener registered, Playwright would otherwise
   leave the dialog unhandled; the explicit dismiss restores the Playwright default observable
   behavior → checkpoint `logic` — passed.
5. **Output**: dialog resolved (or left to the capture); the triggering facade call returns.

#### Checkpoint Summary
- CODEMANIFEST open_context step 4 semantics ("the single dialog routing handler for every page of
  the context … an active expect_dialog capture claims the dialog on its own page … otherwise
  accept when accept_dialogs … is true, else an explicit dismiss restoring the Playwright dismiss
  default") — passed, 1:1.
- Boundary isolation: the router is driver-internal; generated code never sees it — passed.

### Trace: `PageFacade.expect_dialog()` (new)

#### Chain
1. **Input**: generated code `with page.expect_dialog() as dialog:` then the triggering action in
   the block.
2. **Step** (`_DialogCapture.__enter__`, marshaled as one driver-thread call): set
   `router.capture_page = self._page`; `cm = page.expect_event("dialog"); cm.__enter__()` —
   arming the Playwright waiter; return an uninitialized `DialogFacade` shell
   (`DialogFacade.__new__(DialogFacade)`) as the bound variable → checkpoint `api`: the Python
   client ships **no `expect_dialog`** (verified against playwright 1.62) — the dialog waiter is
   `page.expect_event("dialog")` (a `Literal["dialog"]` overload); it returns the same
   `EventContextManager`/`EventInfo` machinery (`__enter__` arms and returns immediately,
   `.value` blocks, `__exit__` waits or cancels on a block exception) and produces the same
   `Timeout …ms exceeded while waiting for event "dialog"` error — passed.
   → checkpoint `logic`: the bound variable is a genuine `DialogFacade` (contract: "the block's
   variable is the `DialogFacade` of the captured dialog"); its state fills at exit — passed.
3. **Step**: block body executes on the calling thread; each facade call inside marshals to the
   driver thread; the dialog event fires during the action; `router.handle` skips
   (capture_page matches); Playwright's waiter resolves → checkpoint `logic` — passed.
4. **Step** (`_DialogCapture.__exit__`, marshaled): `cm.__exit__(*exc_info)` waits for the event:
   - dialog fired → returns; the raw `Dialog` is `cm.value`
   - no dialog and no block error → Playwright raises `Error('Timeout … waiting for event
     "dialog"')` — actionable, names the awaited event, non-`AssertionError` (an action failure
     that regenerates, never a failed check) → checkpoint `api` — passed
   - block raised → Playwright's exit cancels the waiter without a timeout; the block exception
     propagates → passed
   then `finally: router.capture_page = None`; initialize the shell:
   `facade.__init__(dialog)`; `facade._worker = self._worker`; return `False` (never suppress)
   → checkpoint `logic`: "The context-manager constructs resolve at block exit … usable right
   after it" — passed.
5. **Output**: after the block, `dialog.type` / `dialog.message` / `dialog.default_value` /
   `dialog.accept(...)` / `dialog.dismiss()` work as full `DialogFacade` members.

#### Checkpoint Summary
- Contract signature `DialogFacade(dialog: Dialog)` is honored as the *only* initialization path
  (it runs at exit); no sentinel/None states — passed.
- Pre-resolution access (reading `dialog.message` inside the block): `DialogFacade.__getattr__`
  raises an actionable `AttributeError` ("resolves at the end of the with-block") — loud, not an
  assertion — passed.

### Trace: `PageFacade.expect_popup()` (new)

#### Chain
1. **Input**: `with page.expect_popup() as popup:` + opening action in the block.
2. **Step** (`__enter__`, marshaled): `cm = page.expect_popup(); cm.__enter__()`; return a
   `PageFacade.__new__(PageFacade)` shell → checkpoint `logic`: same deferred pattern as the
   dialog capture — passed.
3. **Step** (block): the action opens the page; Playwright's popup waiter resolves.
4. **Step** (`__exit__`, marshaled): `cm.__exit__(*exc_info)` — timeout raises Playwright's error
   naming event `"popup"`; then `popup_page = cm.value`; shell `__init__(popup_page,
   popup_page.context)`; `facade._worker = self._worker`; `facade._router = self._router` — the
   popup inherits the **shared context router**: the popup already carries the routing handler
   (the context page event registered it when the page opened), so a capture on the popup must
   mark the shared router for the handler to skip, and an uncaptured dialog on the popup follows
   `accept_dialogs` exactly like the main page; return `False` → checkpoint `logic`: "A
   popup page is a full `PageFacade` bound to the same driver thread as its opener" — passed.
5. **Output**: full page surface on the popup; `popup.bring_to_front()` raises it;
   `page.pages` lists both.

#### Checkpoint Summary
- No raw `Page`/`BrowserContext` crosses the boundary (the context of the popup is the same
  context object the opener facade already wraps) — passed.
- Double-wrap safety: `pages`/`expect_popup` may wrap the same raw page more than once — harmless,
  because the dialog handler belongs to the **page** (registered once through the context page
  event), never to a facade; wrapping never registers anything — passed.

### Trace: `PageFacade.pages` / `bring_to_front` / `frame_locator` (new)

#### Chain
1. **Input**: `page.pages` (property), `page.bring_to_front()`, `page.frame_locator("#checkout")`.
2. **Step**: `pages` — `self._call(lambda: list(self._context.pages))` → wrap each raw page:
   `facade = PageFacade(raw, self._context); facade._worker = self._worker;
   facade._router = self._router` (the shared context router — captures on any listed page mark
   it) → checkpoint `type`: `list[PageFacade]`, property matches `pages -> list[PageFacade]` —
   passed.
3. **Step**: `bring_to_front` — `self._page.bring_to_front()` marshaled → checkpoint `api` —
   passed.
4. **Step**: `frame_locator` — `fl = self._call(lambda: self._page.frame_locator(selector))`;
   `FrameFacade(fl)` + `_worker` attach → checkpoint `type`: `FrameFacade`, no raw
   `FrameLocator` escapes — passed.
5. **Output**: wrapped pages for switching; the frame scope for iframe locating.

#### Checkpoint Summary
- "No method exposes raw Playwright objects — pages, dialogs and frame scopes included" — passed.

### Trace: `PageFacade` navigation and locating members (new/renamed)

#### Chain
1. **Input**: step sentences like "open …", "go back", "wait for the dashboard URL".
2. **Step**: `goto(url)` → `self._page.goto(url)` (default `wait_until="load"` — "wait for the
   load state") → checkpoint `api` — passed.
3. **Step**: `go_back()`/`go_forward()`/`reload()` → the Playwright counterparts; each returns
   after the load state → checkpoint `api` — passed.
4. **Step**: `wait_for_url(url)` → `self._page.wait_for_url(url)` — a plain string is a glob
   pattern in Playwright → checkpoint `api` vs "matches the glob pattern" — passed.
5. **Step**: `wait_for_load_state(state)` → pass-through of `load|domcontentloaded|networkidle`;
   an invalid state is Playwright's own loud error → passed.
6. **Step**: `get_by_role(role, name="")` → omit the `name` kwarg when empty
   (`page.get_by_role(role)` matches by role alone; `name=""` would match an empty accessible
   name instead — a real Playwright semantic difference); non-empty → `get_by_role(role,
   name=name)` → checkpoint `api` vs "empty — match by role alone" — passed.
7. **Step**: `get_by_label/get_by_text/get_by_placeholder/get_by_alt_text/get_by_title/
   get_by_test_id` → direct Playwright counterparts (`get_by_test_id` uses the default
   `data-testid` attribute) → checkpoint `api` — passed.
8. **Step**: `locator(selector)` → **verbatim** pass-through. `//`-prefixed XPath auto-detects;
   the explicit `xpath=` engine prefix works as a selector form; CSS and attribute selectors
   pass unchanged. No facade-side sniffing or rewriting (the old `find_by_xpath` `xpath=`
   wrapping is gone with the method) → checkpoint `api` vs "any selector — CSS, XPath (incl. the
   xpath= form) and attribute selectors" — passed.
9. **Step**: every located raw `Locator` wraps through `_wrap_locator` (worker inheritance) →
   `LocatorFacade` → checkpoint `type` — passed.
10. **Output**: `LocatorFacade` handles / navigation side effects.

#### Checkpoint Summary
- Rename mapping `open→goto`, `find_by_role/label/text→get_by_*` is 1:1 with the mirror principle;
  the deleted `find_by_attribute/css/xpath` collapse into `locator`/`get_by_test_id` — passed.
- System-prompt rule "get_by_test_id and locator(selector) exist for elements without accessible
  names" matches the implementation surface — passed.

### Trace: `PageFacade.expect_url` / `expect_title` (new)

#### Chain
1. **Input**: assertion sentences — "the URL is **/dashboard", "the title contains Dashboard".
2. **Step**: `expect_url(url)` → `self._call(lambda: expect(self._page).to_have_url(url))` — a
   string is glob-matched by Playwright (`**/dashboard` style, per the `playwright` usage) →
   checkpoint `api` — passed.
3. **Step**: `expect_title(title)` — the contract demands **contains** while Playwright's
   `to_have_title(str)` is exact; build an unanchored escaped pattern:
   `re.compile(f".*{re.escape(title)}.*", re.DOTALL)` → `to_have_title(pattern)` — correct under
   both possible Playwright regex semantics (`test` or `search`: the `.*` bookends make an
   anchored test behave as search; `DOTALL` lets titles span lines) → checkpoint `api` +
   checkpoint `logic` vs "contains `title`" — passed.
4. **Step**: both run inside the driver thread; a failed expectation raises `AssertionError` →
   the engine's failed-check path (stops retries, classifies) → checkpoint `logic` — passed.
5. **Output**: assertion result or `AssertionError` for classification.

#### Checkpoint Summary
- Interface↔interface (`expect_title` semantics ↔ engine "assertion sentence ends with an
  expectation call") — passed.

### Trace: `LocatorFacade` new action members

#### Chain
1. **Input**: action sentences — double click, right click, press Enter, check a box, drag, upload.
2. **Step**: `click(button="")` → `self._locator.click(button=button or "left")` — empty maps to
   the left button; `right`/`middle` pass through → checkpoint `api` vs "empty for the left
   button, right for the right button, middle for the middle button" — passed.
3. **Step**: `dblclick/clear/press/check/uncheck/hover` → direct counterparts; `press(key)`
   accepts names and combinations (`"Enter"`, `"Control+A"`) → checkpoint `api` — passed.
4. **Step**: `drag_to(target: LocatorFacade)` → `self._locator.drag_to(target._locator)` — the
   raw locator crosses facade-to-facade *inside* the boundary module, never out → checkpoint
   `type` + `logic` vs "no raw Playwright objects exposed" — passed.
5. **Step**: `set_input_files(path)` → `self._locator.set_input_files(path)` — a filesystem path
   string; Playwright accepts it directly → checkpoint `api` — passed.
6. **Output**: element state changes; all calls marshal through the inherited worker.

#### Checkpoint Summary
- Auto-wait everywhere (Playwright actionability) — "Locating methods never sleep" holds — passed.

### Trace: `LocatorFacade` new expectation members

#### Chain
1. **Input**: assertion sentences — value, checked, count, attribute, hidden.
2. **Step**: `expect_hidden` → `to_be_hidden()`; `expect_value` → `to_have_value(value)`
   (equality); `expect_checked` → `to_be_checked()`; `expect_count(count)` →
   `to_have_count(count)`; `expect_attribute(name, value)` → `to_have_attribute(name, value)`
   (equality) — all through the module-level `expect` inside `_call` → checkpoint `api` vs the
   `playwright` usage "the full expectation set" — passed.
3. **Step**: failures raise `AssertionError` → "assertion-style errors destined for failure
   classification" — passed.
4. **Output**: assertion results.

#### Checkpoint Summary
- The method-style `expect_*` names replacing the chained `to_be_*` model are the declared
  non-mirror family — consistent with the global annotations — passed.

### Trace: `DialogFacade` members

#### Chain
1. **Input**: after a captured block — `dialog.type`, `dialog.message`, `dialog.default_value`,
   `dialog.accept("yes")`, `dialog.dismiss()`.
2. **Step**: properties read `self._dialog.type/message/default_value` through `_call` →
   checkpoint `api`: `Dialog.default_value` is `""` for non-prompt kinds — matches "empty for the
   other kinds" — passed.
3. **Step**: `accept(prompt_text="")` → `dialog.accept()` with no kwarg when empty ("accept
   without an answer"), else `dialog.accept(prompt_text=prompt_text)` → checkpoint `logic` —
   passed.
4. **Step**: `dismiss()` → `dialog.dismiss()`; double handling is Playwright's own loud error —
   "accept and dismiss resolve the dialog exactly once" holds naturally → passed.
5. **Output**: dialog resolved from the step; every call marshaled to the driver thread.

#### Checkpoint Summary
- Requirements of the entity — passed.

### Trace: `FrameFacade` members

#### Chain
1. **Input**: iframe content — `frame.get_by_role("button", name="Pay")`, nested
   `frame.frame_locator("#inner")`.
2. **Step**: locating members map to `FrameLocator.get_by_role/get_by_label/get_by_text/
   get_by_placeholder/get_by_alt_text/get_by_title/get_by_test_id/locator` (all exist on
   FrameLocator in playwright ≥1.49) with the same empty-name rule for `get_by_role` → checkpoint
   `api` — passed.
3. **Step**: located raw locators wrap into `LocatorFacade` with worker inheritance → actions and
   expectations on frame content behave exactly like page content → checkpoint `type` — passed.
4. **Step**: `frame_locator(selector)` → `FrameLocator.frame_locator(selector)` wrapped into a
   nested `FrameFacade` — "nested frames chain" → passed.
5. **Output**: frame-scoped handles.

#### Checkpoint Summary
- "Every action of a located element runs in the driver thread inherited from the page facade
  that created the scope" — passed (worker attach).

### Trace: `StepGenerator` request surface (engine, changed constants)

#### Chain
1. **Input**: `generate`/`regenerate` attempt loop — unchanged code paths.
2. **Step**: `prompt=SYSTEM_PROMPT` — the constant becomes the engine CODEMANIFEST
   `system_prompt` text **verbatim** (the annotation "Use `system_prompt` as the system prompt of
   every code generation request" makes the manifest the source) → checkpoint `logic` — passed.
3. **Step**: `page_api=PAGE_API_SURFACE` — the constant mirrors `prettyplay/driver/.usages/
   facade.md` verbatim: the four surface tables (page/dialog/frame/element) as aligned
   `call — purpose` lines; `page.close()` stays excluded (runtime method of PrettyPlay, standing
   comment); the two properties (`page.url`, `page.pages`) listed → checkpoint `logic` vs "the
   listing and the practice change together" — passed.
4. **Step**: the provider request carries both; generated code can only call the listed surface →
   checkpoint `interface↔interface`: every listed name resolves on the facade classes (pinned by
   a test) — passed.
5. **Output**: candidates in the fixed form.

#### Checkpoint Summary
- The engine CODEMANIFEST rules (dialogs/popups/iframes guidance) and the listing are mutually
  consistent — passed.

## Algorithm Design

### `BrowserConfig` (config/models.py — changed)

**Responsibility**: the nested browser settings group; one new plain bool field.

**Algorithm:**
```
1. Add field `accept_dialogs: bool = False` after `endpoint`
   → neutral default keeps pre-section construction valid
2. Extend the class docstring Attributes with the setting
   (auto-accept of dialogs no captured expect_dialog block claims; False = Playwright dismiss default)
```

**Errors:** none new (plain bool; pydantic rejects non-bools with the existing render path).

**Edge Cases:**
- TOML `accept_dialogs = "maybe"` → pydantic bool-coercion failure → `_render_validation` line via
  `_ALLOWED_TEXT["browser.accept_dialogs"] = "a boolean"`. (pydantic lax mode still coerces
  bool-like strings such as `"yes"`/`"on"` to True on the file layer — same as every other bool
  field of the group; the env layer is stricter and rejects them.)

### `load_config` (config/loader.py — changed)

**Responsibility**: layered load; the new setting rides every existing layer.

**Algorithm:**
```
1. _ENV_NAMES += {"browser.accept_dialogs": "PRETTYPLAY_BROWSER_ACCEPT_DIALOGS"}
   (append "browser.accept_dialogs" to the settings tuple)
2. _BOOL_ENV_SETTINGS += "browser.accept_dialogs"
3. _ALLOWED_TEXT["browser.accept_dialogs"] = "a boolean"
4. Module docstring: extend the flat group env-names mention with ACCEPT_DIALOGS
```

**Errors:** unparseable env value → `ConfigurationError` naming setting/value/accepted form
(existing `_parse_env_scalar` path).

**Edge Cases:**
- Programmatic `BrowserConfig(accept_dialogs=False)` over a file `true` → explicit False wins
  (group-merge condition already includes bools) — pinned by a test.

### `_DialogRouter` (driver/page.py — new internal class)

**Responsibility**: the single dialog routing state of one browser context — every page of the
context routes uncaptured dialogs through it.

**Algorithm:**
```
1. Construct with accept_dialogs: bool read from the browser group
2. capture_page: Page | None = None
3. handle_for(page) -> handler            # the per-page closure registered on("dialog")
4. handler(dialog):                       # runs in the driver thread
   IF router.capture_page is this handler's page:
     return                               # an armed expect_dialog capture claims it
   ELIF accept_dialogs: dialog.accept()
   ELSE: dialog.dismiss()
```

**Errors:** handler exceptions propagate into the triggering facade call (loud).

**Edge Cases:**
- Dialog on page A while a capture is armed on popup page B → A's handler routes (per-page
  comparison), B's dialog goes to its own capture.

### `DriverSession.open_context` (driver/session.py — changed)

**Responsibility**: unchanged + dialog wiring.

**Algorithm:**
```
1-3. unchanged (lazy launch/connect, screen params) — inside the marshaled open_isolated:
   context = browser.new_context(**params)
   router = _DialogRouter(self._config.browser.accept_dialogs)
   context.on("page", lambda p: p.on("dialog", router.handle_for(p)))
   page = context.new_page()          # fires the context page event → registers its handler
4. Every page of the context — the open_context page and every later popup/new tab — now routes
   uncaptured dialogs through the single router (accept on the setting, else explicit dismiss)
5. facade = PageFacade(page, context); facade._worker = worker; facade._router = router
```

**Errors:** unchanged loud launch/connect/device failures.

**Edge Cases:**
- `accept_dialogs` read once per session — a config change after start needs a new session
  (config is immutable; non-issue).

### `PageFacade` (driver/page.py — rebuilt)

**Responsibility**: the full-parity mirror of one page; the only page API of generated code.

**Algorithm (member → Playwright call, all through `_call`):**
```
url          → self._page.url                                  (property, kept)
pages        → [PageFacade(p, self._context) + worker + router for p in self._context.pages]
goto(u)      → self._page.goto(u)
go_back()    → self._page.go_back()
go_forward() → self._page.go_forward()
reload()     → self._page.reload()
wait_for_url(u)            → self._page.wait_for_url(u)        (glob string)
wait_for_load_state(s)     → self._page.wait_for_load_state(s)
expect_url(u)              → expect(self._page).to_have_url(u) (glob string)
expect_title(t)            → expect(self._page).to_have_title(re.compile(f".*{re.escape(t)}.*", re.DOTALL))
get_by_role(r, name="")    → self._page.get_by_role(r) | self._page.get_by_role(r, name=name)
get_by_label(l)            → self._page.get_by_label(l)
get_by_text(t)             → self._page.get_by_text(t)
get_by_placeholder(p)      → self._page.get_by_placeholder(p)
get_by_alt_text(a)         → self._page.get_by_alt_text(a)
get_by_title(t)            → self._page.get_by_title(t)
get_by_test_id(id)         → self._page.get_by_test_id(id)
locator(s)                 → self._page.locator(s)              (verbatim)
expect_dialog()            → _DialogCapture(self)               (below)
expect_popup()             → _PopupCapture(self)                (below)
bring_to_front()           → self._page.bring_to_front()
frame_locator(s)           → FrameFacade(self._page.frame_locator(s)) + worker
aria_snapshot()/screenshot()/scroll_*/close()                   (kept verbatim)
```

**Captures (the shared mechanism):**
```
_DialogCapture.__enter__  [one marshaled call]: router.capture_page = self._page;
                          cm = page.expect_event("dialog"); cm.__enter__();
                          return DialogFacade.__new__(DialogFacade)
_DialogCapture.__exit__   [one marshaled call]: try: cm.__exit__(*exc) → dialog = cm.value
                          finally: router.capture_page = None
                          then facade_shell.__init__(dialog); ._worker = self._worker
                          return False
_PopupCapture             same shape over page.expect_popup();
                          shell.__init__(popup_page, popup_page.context); ._worker inherited;
                          ._router = self._router (the shared context router — the popup already
                          carries the routing handler through the context page event, so captures
                          on it must mark the shared router for the handler to skip)
__getattr__ on both facade classes (pre-resolution guard):
  raise AttributeError("resolves at the end of the with-block — read it after the block")
```

**Errors:** Playwright errors propagate as-is (timeouts name the awaited event); expectations
raise `AssertionError`; nothing is swallowed.

**Edge Cases:**
- Hand-built facade (no worker): `_call` runs inline; `_router` lazily defaults to a
  `_DialogRouter(accept_dialogs=False)` so `expect_dialog` still works in tests.
- Retired members: deleted, not aliased — parity replaces compatibility.

### `LocatorFacade` (driver/page.py — extended)

**Responsibility**: auto-waiting element handle; mirror action + expectation set.

**Algorithm (member → call):**
```
click(button="")  → self._locator.click(button=button or "left")
dblclick()        → self._locator.dblclick()
fill(v)           → self._locator.fill(v)                    (kept)
clear()           → self._locator.clear()
press(k)          → self._locator.press(k)
check()           → self._locator.check()
uncheck()         → self._locator.uncheck()
hover()           → self._locator.hover()
select_option(v)  → self._locator.select_option(v)           (kept)
drag_to(target)   → self._locator.drag_to(target._locator)
set_input_files(p)→ self._locator.set_input_files(p)
expect_visible()  → expect(loc).to_be_visible()              (kept)
expect_hidden()   → expect(loc).to_be_hidden()
expect_text(t)    → expect(loc).to_contain_text(t)           (kept — contains, normalized)
expect_enabled()  → expect(loc).to_be_enabled()              (kept)
expect_value(v)   → expect(loc).to_have_value(v)
expect_checked()  → expect(loc).to_be_checked()
expect_count(n)   → expect(loc).to_have_count(n)
expect_attribute(n, v) → expect(loc).to_have_attribute(n, v)
```

**Errors:** `AssertionError` from expectations (classification path); Playwright action errors
(retry path).

**Edge Cases:** none beyond Playwright's own (double-handling guards live in Playwright).

### `DialogFacade` (driver/page.py — new)

**Responsibility**: step-controlled captured dialog.

**Algorithm:**
```
type           → _call(lambda: self._dialog.type)            (property)
message        → _call(lambda: self._dialog.message)         (property)
default_value  → _call(lambda: self._dialog.default_value)   (property)
accept(t="")   → _call(lambda: self._dialog.accept() if t == "" else self._dialog.accept(prompt_text=t))
dismiss()      → _call(self._dialog.dismiss)
```

**Errors:** Playwright's already-handled error on double resolution.

**Edge Cases:** `accept("")` on a prompt → accept without an answer (no kwarg).

### `FrameFacade` (driver/page.py — new)

**Responsibility**: iframe locating scope; nested chaining.

**Algorithm:**
```
get_by_role(r, name="") → fl.get_by_role(r) | fl.get_by_role(r, name=name)   → LocatorFacade + worker
get_by_label/get_by_text/get_by_placeholder/get_by_alt_text/get_by_title/get_by_test_id
                        → fl.<same name>(arg)                               → LocatorFacade + worker
locator(s)              → fl.locator(s)                                     → LocatorFacade + worker
frame_locator(s)        → FrameFacade(fl.frame_locator(s)) + worker
```

**Errors:** Playwright locator errors as-is.

**Edge Cases:** a frame selector matching nothing fails at action time (Playwright auto-wait),
not at scope creation — mirror behavior.

### `StepGenerator` constants (engine/generator.py — changed)

**Responsibility**: the request texts; no logic change.

**Algorithm:**
```
1. SYSTEM_PROMPT ← the engine CODEMANIFEST `system_prompt` text verbatim
2. PAGE_API_SURFACE ← the facade.md four tables verbatim as aligned `call — purpose` lines
   (page 33 rows of facade.md, 32 listed — page.close() excluded with the standing comment;
   dialog 5, frame 3, element 19; page.url/page.pages properties included)
3. Update the PAGE_API_SURFACE comment: parity wording replaces backward compatibility
```

**Errors:** none.

**Edge Cases:** none — constants.

### Documentation pages (implementation-time ride-along)

**Algorithm:**
```
1. docs/reference/driver-facade.md — rebuild from facade.md: parity intro, four surface tables,
   dialogs/popups/iframes/interactions/scroll examples, updated Rules
2. docs/guides/writing-steps.md — rename surface examples to goto/get_by_*; add dialog, popup,
   iframe snippets
3. docs/configuration.md — browser-group table + env table gain accept_dialogs; add the Dialogs
   subsection (mirrors configuration.md of the cell)
4. docs/getting-started.md, docs/index.md — replace retired names where present
5. mkdocs.yml — no navigation change (existing pages only)
```

## Cross-cutting Concerns

- **Error handling**: unchanged strategy. Expectations raise `AssertionError` (failed-check path:
  stop retries, classify). Action/navigation/capture errors are Playwright errors (retry path).
  The capture timeout errors name the awaited event ("dialog"/"popup") and are not assertions.
  No facade member swallows or retries anything.
- **Logging**: no new logging — the facades stay silent; the engine/logger behavior is untouched.
- **Validation**: config validation unchanged in mechanism (one new bool field + env parse);
  `wait_for_load_state` invalid states are Playwright's loud errors; no facade-level input
  validation beyond Playwright's own.
- **Caching**: no change. Cached steps calling retired members fail on `AttributeError` —
  accepted per the task; the existing classify → rot → regenerate loop heals them lazily.
- **Concurrency**: strictly sequential driver-thread marshaling extends to every new member —
  pages, popups, dialogs, frames. The routing handler runs inside the driver thread (never
  marshals). The capture enter/exit are each one marshaled call, so the block body's calls
  interleave correctly between them. The calling thread never adopts the Playwright event loop.

## Usages Analysis

### `conventions`
- **What it provides**: Python rules — 3.10+ compat, relative intra-package imports, pydantic
  kw_only models, Google docstrings, logging, test structure (`tests/<pkg>/test_<module>.py`,
  fakes over real browsers), ruff.
- **Where used**: every changed file and test.
- **Why chosen**: mandatory project convention.
- **How exactly**: new members follow the existing docstring/`Args`/`Raises` style of page.py;
  tests extend the existing Fake* recorders; ruff gates the change.

### `playwright`
- **What it provides**: the sync API practices — lifecycle, engines/channels, screen modes,
  locators/auto-wait, and the new sections: interactions, dialogs auto-accept, popups/tabs,
  frames, the full expectation set, waits.
- **Where used**: `DriverSession`, `PageFacade`, `LocatorFacade`, `DialogFacade`, `FrameFacade`.
- **Why chosen**: hard dependency; the parity source.
- **How exactly**: every mirror member maps to its documented counterpart (traces above); the
  dialog section's `page.on("dialog", …)` registration is the routing handler; `expect_popup`
  /`frame_locator` compose exactly as documented; `to_have_url` glob, `to_contain_text`
  normalization, `press` combination syntax, `set_input_files` path form.

### `pydantic`
- **What it provides**: model rules for the config cell.
- **Where used**: `BrowserConfig`.
- **Why chosen**: existing config stack.
- **How exactly**: plain bool field on the kw_only group; validation errors render through the
  existing loader path.

### Imported Usages
- `configuration` from `prettyplay/config` — the browser-group settings the session reads,
  `accept_dialogs` included; path `prettyplay/config/.usages/configuration.md`. Traceable link:
  the driver reads the group through `Config` and its practice documents the setting the router
  consumes; no contractual obligation crosses the boundary (the driver only reads the switch).
- `facade` from `prettyplay/driver` — the single source of the page API surface for generation
  requests; path `prettyplay/driver/.usages/facade.md`. `PAGE_API_SURFACE` mirrors it verbatim.
- `classification` from `prettyplay/llm` — unchanged by this change; still referenced by the
  engine annotations.

## `.usages/` Update

### Cell: `prettyplay/config`

#### Existing Files — Consistency
- **`configuration`** → `prettyplay/config/.usages/configuration.md`
  - Status: **current** — `accept_dialogs` present in the TOML block, env table, layered-merge
    bullet, Dialogs section, Loading example (applied by the apply stage).
  - Additions needed: none. Updates needed: none.

### Cell: `prettyplay/driver`

#### Existing Files — Consistency
- **`facade`** → `prettyplay/driver/.usages/facade.md`
  - Status: **current** — rewritten to the four surface tables + examples; verified 1:1 against
    the CODEMANIFEST members (33 page rows, 5 dialog, 19 element, frame family).
  - Additions needed: none. Updates needed: none.

### Cell: `prettyplay/engine`

#### Existing Files — Consistency
- **`generation`** → `prettyplay/engine/.usages/generation.md`
  - Status: **current** — "The fixed form" rewritten to the new surface.
  - Additions needed: none.
- **`healing`** → `prettyplay/engine/.usages/healing.md`
  - Status: **current** — carries no facade member names; unaffected.
  - Additions needed: none. Updates needed: none.

No new `.usages/` files — the changes stay inside the existing functional domains (consumer
documentation moves were the apply stage's deliverable and are complete).

## Test Stack Trace

### General Setup

Existing fake pattern extended: `FakePage`/`FakeLocator`/`FakeContext`/`FakeDialog`/
`FakeFrameLocator` recorders in `tests/driver/test_page.py`; `FakePlaywrightFactory` in
`tests/driver/test_session.py`; tmp-path pyproject fixtures in `tests/config`; provider fakes in
`tests/engine` and `tests/test_integration.py`. New fakes follow the same recording style. The
module-level `expect` is patched with `mock.patch("prettyplay.driver.page.expect", …)` as today.

### Source File Registry

- `prettyplay/config/models.py`, `prettyplay/config/loader.py`
- `prettyplay/driver/page.py`, `prettyplay/driver/session.py`, `prettyplay/driver/__init__.py`
- `prettyplay/engine/generator.py`
- `tests/config/test_models.py`, `tests/config/test_loader.py`
- `tests/driver/test_page.py`, `tests/driver/test_session.py`
- `tests/engine/test_generator.py`
- `tests/test_integration.py`, `tests/test_executor.py`, `tests/test_scenario.py`,
  `tests/test_runtime.py` (FakePage surface + cached-code strings)
- `tests/llm/test_request.py`, `tests/llm/test_provider.py`, `tests/llm/test_openai_provider.py`,
  `tests/llm/test_anthropic_provider.py`, `tests/cache/test_models.py`,
  `tests/cache/test_store.py` (opaque fixture strings carrying retired names — sweep only)

---

### Positive Tests

#### `test_browser_config_accept_dialogs_default_and_explicit` (tests/config/test_models.py)

**Setup**: none (pure model).

**Input**: `BrowserConfig()` and `BrowserConfig(accept_dialogs=True)`.

**Trace**:
```
BrowserConfig()
  → pydantic kw_only construction        # defaults
    returns: accept_dialogs == False
BrowserConfig(accept_dialogs=True)
  → pydantic validates the bool field
    returns: accept_dialogs is True
```

**Assertions**:
```
BrowserConfig().accept_dialogs is False
BrowserConfig(accept_dialogs=True).accept_dialogs is True
Config().browser.accept_dialogs is False
```

**Sufficiency**: pins the neutral default (the pre-setting behavior) required by the contract.

---

#### `test_env_override_parses_accept_dialogs_by_type` (tests/config/test_loader.py)

**Setup**: tmp_path pyproject.toml with `[tool.prettyplay]` `model = "m"` and a browser group
without `accept_dialogs`; monkeypatch env.

**Input**: parametrized `("true", True)`, `("1", True)`, `("false", False)`, `("0", False)` for
`PRETTYPLAY_BROWSER_ACCEPT_DIALOGS`.

**Trace**:
```
load_config(pyproject_path=str(toml))
  → _collect_env_overrides()
    → _parse_env_scalar("browser.accept_dialogs", raw)   # bool setting
      returns: True/False
    → group_env merge into the browser section
  → Config(**merged)
    returns: browser.accept_dialogs == parsed
```

**Assertions**:
```
config.browser.accept_dialogs is expected          # for each parametrize row
```

**Sufficiency**: proves the fifth PRETTYPLAY_BROWSER_* override exists and parses by field type —
the contract requirement "an env override exists for every setting".

---

#### `test_env_override_rejects_unparseable_accept_dialogs` (tests/config/test_loader.py)

**Setup**: as above; `PRETTYPLAY_BROWSER_ACCEPT_DIALOGS=yes`.

**Input**: `load_config(pyproject_path=...)`.

**Trace**:
```
load_config(...)
  → _parse_env_scalar("browser.accept_dialogs", "yes")
    raises: ConfigurationError("browser.accept_dialogs: received 'yes' — allowed: a boolean (true/false/1/0)")
```

**Assertions**:
```
pytest.raises(ConfigurationError) — message names the setting, 'yes' and the accepted form
```

**Sufficiency**: "never a silent ignore" for the new field.

---

#### `test_programmatic_accept_dialogs_merges_into_group` (tests/config/test_loader.py)

**Setup**: pyproject with `[tool.prettyplay.browser]` `accept_dialogs = true`.

**Input**: `load_config(path, overrides=PrettyConfig(browser=BrowserConfig()))` (unset) and
`overrides=PrettyConfig(browser=BrowserConfig(accept_dialogs=False))` (explicit False).

**Trace**:
```
_apply_overrides(file_config, overrides)
  → group merge: accept_dialogs in model_fields_set?
    unset → skipped          → file value True survives
    explicit False → bool participates → False wins
```

**Assertions**:
```
unset override      → config.browser.accept_dialogs is True
explicit False      → config.browser.accept_dialogs is False
```

**Sufficiency**: "an explicit False overrides too" — the layered merge reaches the new field.

---

#### `test_every_setting_has_an_env_override` (tests/config/test_loader.py)

**Setup**: import `_ENV_NAMES`.

**Input**: none (registry inspection).

**Trace**:
```
_ENV_NAMES values ⊇ {PRETTYPLAY_PROVIDER, PRETTYPLAY_MODEL, …,
                     PRETTYPLAY_BROWSER_NAME, PRETTYPLAY_BROWSER_SCREEN,
                     PRETTYPLAY_BROWSER_HEADLESS, PRETTYPLAY_BROWSER_ENDPOINT,
                     PRETTYPLAY_BROWSER_ACCEPT_DIALOGS, PRETTYPLAY_STRICT,
                     PRETTYPLAY_CLASSIFICATION_PROMPT}
```

**Assertions**: all five browser variables and every scalar setting present; count matches the
model fields.

**Sufficiency**: regression gate against dropping an override when fields change.

---

#### `test_retired_surface_is_gone` (tests/driver/test_page.py)

**Setup**: import `PageFacade`.

**Input**: retired names.

**Trace**:
```
hasattr(PageFacade, name) for name in ("open", "find_by_role", "find_by_label",
"find_by_text", "find_by_attribute", "find_by_css", "find_by_xpath")
  → all False
```

**Assertions**: no retired member exists.

**Sufficiency**: the acceptance criterion "the old names no longer exist".

---

#### `test_page_surface_matches_the_contract` (tests/driver/test_page.py)

**Setup**: none.

**Input**: the expected member listing (properties `url`, `pages`; methods: `goto`, `go_back`,
`go_forward`, `reload`, `wait_for_url`, `wait_for_load_state`, `expect_url`, `expect_title`,
`get_by_role`, `get_by_label`, `get_by_text`, `get_by_placeholder`, `get_by_alt_text`,
`get_by_title`, `get_by_test_id`, `locator`, `expect_dialog`, `expect_popup`, `bring_to_front`,
`frame_locator`, `aria_snapshot`, `screenshot`, `scroll_to_element`, `scroll_down`, `scroll_up`,
`scroll_to_bottom`, `scroll_to_top`, `scroll_into_view`, `scroll_container_down`,
`scroll_container_up`, `close`).

**Trace**:
```
public = {n for n in dir(PageFacade) if not n.startswith("_")}
expected == public            # exact set equality
```

**Assertions**: set equality — nothing extra, nothing missing.

**Sufficiency**: the parity gate for the page level; drives the PAGE_API_SURFACE consistency.

---

#### `test_navigation_members_delegate_to_playwright` (tests/driver/test_page.py)

**Setup**: `FakePage` records calls; `PageFacade(fake_page, fake_context)`.

**Input**: `goto("https://example.com")`, `go_back()`, `go_forward()`, `reload()`,
`wait_for_url("**/dashboard")`, `wait_for_load_state("networkidle")`.

**Trace**:
```
facade.goto(url) → _call → fake_page.goto("https://example.com")   recorded
facade.go_back() → fake_page.go_back()                             recorded
… each member → its mirror call with the verbatim argument
```

**Assertions**:
```
fake.calls == [("goto", "https://example.com"), ("go_back",), ("go_forward",),
               ("reload",), ("wait_for_url", "**/dashboard"),
               ("wait_for_load_state", "networkidle")]
```

**Sufficiency**: mirror delegation for the navigation family.

---

#### `test_get_by_family_delegates_and_wraps` (tests/driver/test_page.py)

**Setup**: FakePage returns distinct FakeLocators per method.

**Input**: each locator method with a concrete value (`get_by_role("button", name="Sign in")`,
`get_by_label("Username")`, `get_by_text("Welcome")`, `get_by_placeholder("Search")`,
`get_by_alt_text("Logo")`, `get_by_title("Close")`, `get_by_test_id("submit")`,
`locator("form > button")`).

**Trace**:
```
facade.get_by_role("button", name="Sign in")
  → fake_page.get_by_role("button", name="Sign in")   recorded with kwarg
  → _wrap_locator → LocatorFacade
… same shape for the rest
```

**Assertions**:
```
each returns a LocatorFacade wrapping the fake locator it asked for
fake.calls carries the exact method + args
```

**Sufficiency**: the locating family maps 1:1 and never leaks a raw locator.

---

#### `test_get_by_role_empty_name_matches_by_role_alone` (tests/driver/test_page.py)

**Setup**: as above.

**Input**: `facade.get_by_role("button")` / `facade.get_by_role("button", name="")`.

**Trace**:
```
facade.get_by_role("button", name="")
  → fake_page.get_by_role("button")          # NO name kwarg
```

**Assertions**: the recorded call has no `name` kwarg.

**Sufficiency**: pins "empty — match by role alone" (an empty-string name kwarg would match an
empty accessible name in Playwright — a different query).

---

#### `test_locator_passes_selectors_verbatim` (tests/driver/test_page.py)

**Setup**: as above.

**Input**: `"form > button.primary"`, `"//button[@type='submit']"`, `"xpath=*[@id='main']"`,
`"[data-qa='row'] > input"`.

**Trace**:
```
facade.locator(selector) → fake_page.locator(selector)   # byte-identical
```

**Assertions**: recorded selector equals the input for every form.

**Sufficiency**: no facade-side sniffing/rewriting — CSS, XPath (both spellings) and attribute
selectors stay the caller's choice.

---

#### `test_expect_title_builds_a_contains_pattern` (tests/driver/test_page.py)

**Setup**: patch `prettyplay.driver.page.expect` with a recorder.

**Input**: `facade.expect_title("Dashboard")`.

**Trace**:
```
facade.expect_title("Dashboard")
  → expect(fake_page).to_have_title(pattern)
     pattern.pattern == ".*Dashboard.*"  (escaped input), DOTALL flag set
```

**Assertions**: the received pattern source and flags; the receiver is the wrapped page.

**Sufficiency**: pins the contains semantics against Playwright's exact-match string form.

---

#### `test_expect_url_uses_glob_string` (tests/driver/test_page.py)

**Setup**: patched expect recorder.

**Input**: `facade.expect_url("**/dashboard")`.

**Trace**:
```
facade.expect_url("**/dashboard")
  → expect(fake_page).to_have_url("**/dashboard")   # string verbatim — glob
```

**Assertions**: the string passes through unchanged.

**Sufficiency**: glob semantics come from Playwright; the facade must not transform the value.

---

#### `test_pages_property_wraps_context_pages` (tests/driver/test_page.py)

**Setup**: FakeContext.pages = [main, popup] (two FakePages); worker fake records runs.

**Input**: `facade.pages`.

**Trace**:
```
facade.pages → _call → list(fake_context.pages)
  → PageFacade(main, ctx), PageFacade(popup, ctx) with worker attached
```

**Assertions**:
```
len(result) == 2; each isinstance PageFacade; each ._worker is the session worker
```

**Sufficiency**: "the open pages of the context, each a full PageFacade" and the marshaling
boundary for the property.

---

#### `test_expect_dialog_yields_usable_dialog_facade` (tests/driver/test_page.py)

**Setup**: FakePage.expect_event("dialog") returns a recording context manager whose `__exit__`
resolves `value = FakeDialog(type="confirm", message="Delete?", default_value="")`; FakeDialog
records accept/dismiss kwargs. The fake mirrors the real arming call — playwright 1.62 has no
`expect_dialog`; the waiter is `page.expect_event("dialog")`.

**Input**:
```python
with facade.expect_dialog() as dialog:
    facade.get_by_role("button", name="Delete").click()
assert dialog.message == "Delete?"
dialog.accept()
```

**Trace**:
```
__enter__ → router.capture_page set; fake cm.__enter__() → DialogFacade shell returned
block      → click recorded
__exit__   → cm.__exit__ resolves → facade.__init__(FakeDialog) + worker
dialog.message → FakeDialog.message        ("Delete?")
dialog.accept() → FakeDialog.accept()      # no prompt_text kwarg
```

**Assertions**: message/type/default_value read through the facade; accept called without kwargs;
the router flag cleared after exit.

**Sufficiency**: the whole captured-dialog contract — claim, resolve at exit, step control.

---

#### `test_expect_dialog_timeout_names_the_event` (tests/driver/test_page.py)

**Setup**: fake cm `__exit__` raises `Error('Timeout 30000ms exceeded while waiting for event "dialog"')`.

**Input**: `with facade.expect_dialog() as d: pass`.

**Trace**:
```
__exit__ → cm.__exit__ raises Error
  → propagates out of the with-statement; router flag cleared in finally
```

**Assertions**:
```
pytest.raises(Error) — "event \"dialog\"" in str(exc); not an AssertionError
```

**Sufficiency**: "fails loudly with an actionable timeout error naming the awaited event" and the
failure kind stays a retryable action error, never a failed check.

---

#### `test_expect_popup_yields_bound_page_facade` (tests/driver/test_page.py)

**Setup**: FakePage.expect_popup() cm resolves `value = FakePopupPage` (with `.context`); worker
fake attached to the opener facade.

**Input**:
```python
with facade.expect_popup() as popup:
    facade.get_by_role("link", name="Open docs").click()
popup.bring_to_front()
```

**Trace**:
```
__enter__ → fake cm.__enter__() → PageFacade shell
__exit__  → resolves popup → shell.__init__(popup, popup.context); worker inherited
popup.bring_to_front() → FakePopupPage.bring_to_front recorded
```

**Assertions**: popup isinstance PageFacade; `._worker is opener._worker`; the raw popup page
never equals any returned object; bring_to_front recorded.

**Sufficiency**: "a popup page is a full PageFacade bound to the same driver thread as its
opener".

---

#### `test_element_action_family_delegates` (tests/driver/test_page.py)

**Setup**: FakeLocator records; parametrized member/input table:
`dblclick()`, `clear()`, `press("Control+A")`, `check()`, `uncheck()`, `hover()`,
`select_option("red")`, `set_input_files("avatar.png")`.

**Trace**:
```
element.<member>(<args>) → fake_locator.<member>(<args>)   recorded verbatim
```

**Assertions**: each mirror call recorded with exact args.

**Sufficiency**: the interaction mirror set.

---

#### `test_click_maps_button_values` (tests/driver/test_page.py)

**Setup**: FakeLocator.click(**kwargs) records.

**Input**: `click()`, `click("")`, `click("right")`, `click("middle")`.

**Trace**:
```
element.click()        → fake_locator.click(button="left")
element.click("")      → fake_locator.click(button="left")
element.click("right") → fake_locator.click(button="right")
```

**Assertions**: recorded kwargs per row.

**Sufficiency**: "empty for the left button" mapping — the only non-verbatim argument transform.

---

#### `test_drag_to_receives_the_target_locator` (tests/driver/test_page.py)

**Setup**: two fakes — source and target FakeLocator.

**Input**: `source.drag_to(target)`.

**Trace**:
```
source.drag_to(target) → fake_source.drag_to(target._locator)   recorded
```

**Assertions**: the raw target locator passed to Playwright is exactly the wrapped one.

**Sufficiency**: facade-to-facade composition stays inside the boundary.

---

#### `test_expectation_family_uses_the_full_set` (tests/driver/test_page.py)

**Setup**: patched `expect` recorder with `to_be_hidden/to_have_value/to_be_checked/
to_have_count/to_have_attribute`.

**Input**: `expect_hidden()`, `expect_value("user")`, `expect_checked()`,
`expect_count(3)`, `expect_attribute("href", "/docs")` (+ the kept visible/text/enabled).

**Trace**:
```
element.expect_value("user") → expect(loc).to_have_value("user")   recorded
… each member → its to_* assertion with exact args
```

**Assertions**: assertion list == the expected 8 entries with args.

**Sufficiency**: the method-style expectation family maps to Playwright's full set.

---

#### `test_dialog_facade_members` (tests/driver/test_page.py)

**Setup**: `DialogFacade(FakeDialog(type="prompt", message="Name?", default_value="Ann"))`.

**Input**: properties + `accept("Bob")` + `dismiss()`.

**Trace**:
```
dialog.type → "prompt"; dialog.message → "Name?"; dialog.default_value → "Ann"
dialog.accept("Bob") → FakeDialog.accept(prompt_text="Bob")
dialog.dismiss()     → FakeDialog.dismiss()
```

**Assertions**: values and kwargs as above.

**Sufficiency**: the dialog surface table row by row; the empty-prompt_text variant is covered in
the capture test.

---

#### `test_frame_facade_family_and_nesting` (tests/driver/test_page.py)

**Setup**: FakeFrameLocator records; returns FakeLocators / a nested FakeFrameLocator.

**Input**: `frame.get_by_role("button", name="Pay")`, `frame.get_by_test_id("pay")`,
`frame.locator("#x")`, `frame.frame_locator("#inner")`; empty-name variant.

**Trace**:
```
frame.get_by_role(...) → fl.get_by_role(...) → LocatorFacade (+worker)
frame.frame_locator("#inner") → fl.frame_locator("#inner") → FrameFacade
```

**Assertions**: mirror calls recorded; wrapped types correct; no raw object escapes.

**Sufficiency**: the iframe contour including nested chaining.

---

#### `test_open_context_registers_dialog_routing` (tests/driver/test_session.py)

**Setup**: `FakePlaywrightFactory` extended — FakeContext records `on(event, handler)` and fires
the registered "page" handlers on `new_page()`; FakePage records `on(event, handler)`; config
with `accept_dialogs=False`; `FakeDialog` records accept/dismiss.

**Input**: `session.open_context()`; then call the dialog handler registered on the page with a
FakeDialog.

**Trace**:
```
open_context → open_isolated in driver thread
  → fake_context.on("page", wiring) recorded
  → new_page() fires the context "page" event → fake_page.on("dialog", handler) recorded
  → PageFacade returned with ._router
handler(FakeDialog())
  → no capture → accept_dialogs False → FakeDialog.dismiss() recorded, accept not called
```

**Assertions**: exactly one "page" wiring on the context; exactly one "dialog" registration per
page (the main page included, through the event — never a second manual registration); dismiss
called; router attached to the facade.

**Sufficiency**: contract step 4 — context-scoped registration before any step code, dismiss
default.

---

#### `test_popup_pages_route_dialogs_through_the_context_wiring` (tests/driver/test_session.py)

**Setup**: as above; a second raw page created through the fake context (a popup) — the context
"page" wiring fires for it too; `accept_dialogs=True` and `accept_dialogs=False` variants.

**Input**: call the dialog handler registered on the popup page with a FakeDialog, per variant.

**Trace**:
```
popup page creation → context "page" event → popup.on("dialog", router.handle_for(popup))
handler(FakeDialog())
  → no capture on the popup → accept_dialogs True → accept; False → dismiss
```

**Assertions**: the popup carries exactly one dialog handler; the setting routes it (accept /
dismiss branches); the main-page handler is a different closure bound to the main page.

**Sufficiency**: the accept_dialogs promise holds on every page of the context, not only the
open_context page.

---

#### `test_dialog_router_accepts_when_setting_on` (tests/driver/test_session.py)

**Setup**: as above with `BrowserConfig(accept_dialogs=True)`.

**Input**: handler(FakeDialog()).

**Trace**:
```
handler(dialog) → accept_dialogs True → dialog.accept()
```

**Assertions**: accept called, dismiss not called.

**Sufficiency**: the accept branch of the routing algorithm.

---

#### `test_dialog_router_skips_only_for_a_capture_on_the_same_page` (tests/driver/test_session.py)

**Setup**: as above; a second raw page (popup); set `router.capture_page = popup_page` and
`router.capture_page = main_page` in turn.

**Input**: handler(FakeDialog()) under both states.

**Trace**:
```
capture_page is popup (≠ handler page) → routed by setting (accept/dismiss)
capture_page is main (== handler page) → neither accept nor dismiss
```

**Assertions**: first case resolves the dialog; second case no calls.

**Sufficiency**: the per-page capture claim — a popup capture never suppresses main-page routing.

---

#### `test_new_members_marshal_to_the_driver_thread` (tests/driver/test_page.py)

**Setup**: worker fake records `threading.get_ident()` of each run; the test thread id known.

**Input**: representative calls — `goto`, `expect_url`, `frame_locator`, `pages`,
dialog `accept` through a resolved capture.

**Trace**:
```
each facade call → worker.run(fn) → fn executes on the fake worker's recorded ident
```

**Assertions**: every recorded ident is the worker's (≠ the calling thread).

**Sufficiency**: the marshaling boundary covers the new facade kinds — pages, frames, dialogs.

---

#### `test_system_prompt_carries_the_new_rules` (tests/engine/test_generator.py)

**Setup**: import `SYSTEM_PROMPT`.

**Input**: none (constant inspection).

**Trace**:
```
SYSTEM_PROMPT
  contains: "the Playwright-mirroring page API", the label-or-placeholder rule,
            the get_by_test_id/locator rule, the dialog capture rule,
            the popup rule, the iframe rule
  lacks:    "find_by", "Attribute, CSS and XPath locating"
```

**Assertions**: substring checks for each new rule line; absence of the retired wording.

**Sufficiency**: the manifest rule "Use `system_prompt` as the system prompt of every code
generation request" — the constant must track the contract.

---

#### `test_page_api_surface_members_exist_on_the_facades` (tests/engine/test_generator.py)

**Setup**: import `PAGE_API_SURFACE`, `PageFacade`, `LocatorFacade`, `DialogFacade`,
`FrameFacade`.

**Input**: parse each line: prefix (`page.`/`element.`/`dialog.`/`frame.`) + member name before
`(` or end.

**Trace**:
```
for line in PAGE_API_SURFACE lines:
  owner = {page: PageFacade, element: LocatorFacade, dialog: DialogFacade, frame: FrameFacade}[prefix]
  hasattr(owner, member) → True
also: "page.close" not in PAGE_API_SURFACE; "open(" / "find_by" not in it
```

**Assertions**: every listed member resolves on its facade class; retired names absent.

**Sufficiency**: "the listing and the practice change together" — a mechanical guard that the LLM
never sees a call the facade lacks (or vice versa for retired names).

---

#### `test_page_api_surface_mirrors_the_facade_practice` (tests/engine/test_generator.py)

**Setup**: read `prettyplay/driver/.usages/facade.md`.

**Input**: the four surface tables.

**Trace**:
```
for each facade.md table row call `owner.member(...)` except page.close()
(the runtime method of PrettyPlay — excluded by the standing comment):
  strip args → f"{prefix}.{member}" present in PAGE_API_SURFACE
```

**Assertions**: all rows present (page 32 listed + close excluded, dialog 5, frame 3 collapsed
to its family rows, element 19).

**Sufficiency**: the exact-mirror requirement between the practice and the listing.

---

### Negative Tests

#### `test_retired_members_fail_loudly_on_cached_steps` (tests/test_integration.py)

**Setup**: existing integration harness; cached code
`"def step(page) -> None:\n    page.find_by_role('button', name='Войти').click()\n"`.

**Input**: step execution replays the cached code.

**Trace**:
```
run_step_code(cached, page)
  → page.find_by_role → AttributeError
  → executor strict/normal path → classification (rot) → regeneration with the new surface
```

**Assertions**: the failure surfaces by kind (`IncurableStepError`/healing path as configured);
the regenerated code contains no retired name.

**Sufficiency**: the accepted break — cached steps heal lazily through the existing loop.

---

#### `test_block_without_dialog_times_out` (tests/driver/test_page.py)

Covered by `test_expect_dialog_timeout_names_the_event` (negative form of the capture).

---

#### `test_expect_popup_timeout_names_the_event` (tests/driver/test_page.py)

**Setup**: FakePage.expect_popup() returns a fake cm whose `__exit__` raises
`Error('Timeout 30000ms exceeded while waiting for event "popup"')`; the opener facade carries
the worker fake.

**Input**: `with facade.expect_popup() as popup: pass` (no opening action).

**Trace**:
```
__enter__ [marshaled] → fake cm armed → PageFacade shell returned
(empty block)
__exit__  [marshaled] → cm.__exit__(None, None, None) raises Error
  → propagates out of the with-statement; the shell stays uninitialized
    (the __getattr__ guard covers any post-catch access)
```

**Assertions**:
```
pytest.raises(Error) — 'event "popup"' in str(exc); not an AssertionError
```

**Sufficiency**: pins the expect_popup requirement 1:1 — loud, actionable, names "popup", and
stays a retryable action error (never a failed check), mirroring the dialog-side guarantee.

---

#### `test_access_before_block_resolution_raises_actionable` (tests/driver/test_page.py)

**Setup**: capture cm armed; inside the block read the bound variable.

**Input**: `with facade.expect_dialog() as d: d.message`.

**Trace**:
```
d.message → DialogFacade.__getattr__ → AttributeError("… resolves at the end of the with-block …")
```

**Assertions**: `pytest.raises(AttributeError)` with the actionable text; not AssertionError.

**Sufficiency**: loud early-use failure instead of a confusing missing-attribute error.

---

### Edge Case Tests

#### `test_hand_built_facade_runs_inline` (tests/driver/test_page.py — extend existing)

**Setup**: `PageFacade(fake_page, fake_context)` with no worker (today's pattern).

**Input**: new members — `goto`, `locator`, `frame_locator`, `expect_dialog` capture.

**Trace**:
```
facade._worker is None → _call executes inline in the test thread
expect_dialog → lazily created default _DialogRouter(accept_dialogs=False) → capture works
```

**Assertions**: calls reach the fakes; no worker required.

**Sufficiency**: hand-built facades (tests, embedders) keep the full new surface.

---

#### `test_locator_selector_edge_forms` (tests/driver/test_page.py)

Covered by `test_locator_passes_selectors_verbatim` (the `xpath=` explicit engine form and the
attribute-selector form).

---

#### `test_expect_title_with_regex_metacharacters` (tests/driver/test_page.py)

**Setup**: patched expect recorder.

**Input**: `facade.expect_title("C++ (2026)")`.

**Trace**:
```
pattern source == ".*C\+\+ \(2026\)\.*"-equivalent (re.escape of the input between .* bookends)
```

**Assertions**: metacharacters escaped — the title is matched literally.

**Sufficiency**: contains semantics must not turn into an accidental regex.

---

#### `test_popup_capture_and_pages_agree` (tests/driver/test_page.py)

**Setup**: context with main + popup (popup opened through a resolved capture).

**Input**: `facade.pages` after the capture.

**Trace**:
```
pages → wraps both raw pages → two distinct facades; the captured popup facade and the listed
one wrap the same raw page independently (the dialog handler belongs to the page via the context
event — wrapping twice registers nothing)
```

**Assertions**: 2 facades; both carry the worker and the shared router; the popup's own capture
marks the shared router so its handler skips (see the popup-capture test below).

**Sufficiency**: the switching contour — capture + listing + bring_to_front compose.

---

#### `test_popup_capture_claims_through_the_shared_router` (tests/driver/test_page.py)

**Setup**: FakePage pair (main + popup) sharing one `_DialogRouter(accept_dialogs=True)`; the
popup carries a dialog handler bound through `handle_for(popup)`; a capture armed on the popup
via `popup.expect_dialog()`.

**Input**: dispatch a FakeDialog to the popup's registered handler while the capture is armed.

**Trace**:
```
popup.expect_dialog().__enter__ → router.capture_page = popup
popup_handler(FakeDialog()) → capture_page is popup → return (no accept, no dismiss)
capture exit → cm resolves → DialogFacade initialized → step controls accept/dismiss
```

**Assertions**: neither accept nor dismiss fired from the handler; the facade resolves the
dialog exactly once; `router.capture_page` cleared after the block.

**Sufficiency**: with context-scoped routing, a capture on a popup MUST claim through the shared
router — otherwise the handler would resolve the dialog before the capture reads it (Playwright
double-handling).

**Sufficiency**: the switching contour — capture + listing + bring_to_front compose.

---

#### Integration surfaces (tests/test_integration.py, tests/test_executor.py, tests/test_scenario.py)

**Setup**: FakePage surface renamed: `open`→`goto`, `find_by_role/label/text`→`get_by_*` (+ the
`_lookup` recorder keys); cached-code literals `page.open(...)` → `page.goto(...)`. Plus the
opaque-string sweep in the llm/cache tests: `page.open(…)` → `page.goto(…)` in
`FENCED_CODE`/`WORKING_CODE`/`STEP_CODE` fixtures, `page.find_by_role(role, name)` →
`page.get_by_role(role, name)` in page-api fixtures, `page_api="page.open(...)"` →
`"page.goto(...)"` — payloads only, no behavioral change.

**Input**: the existing scenario corpus (generation success, failed-check classification, healing
rot, strict mode, screenshots).

**Trace**: unchanged flows through the renamed surface.

**Assertions**: existing assertions hold (recorded calls now under mirror names).

**Sufficiency**: the whole library cycle works against the new surface — the fixed form is
consistent end to end, and no test fixture advertises a retired name.

---

## Additional Instructions for the Implementation Agent

- Implement strictly in this order: `config/models.py` → `config/loader.py` → `driver/page.py`
  (facades + captures + router) → `driver/session.py` → `driver/__init__.py` exports
  (`DialogFacade`, `FrameFacade`) → `engine/generator.py` constants → tests → docs pages.
- `SYSTEM_PROMPT` and `PAGE_API_SURFACE` are copied **verbatim** from the engine CODEMANIFEST
  `system_prompt` usage and `prettyplay/driver/.usages/facade.md` respectively — no paraphrasing;
  `page.close()` stays out of the listing (standing comment preserved, parity wording).
- Defaults on the facade: `get_by_role(role, name="")`, `click(button="")`,
  `accept(prompt_text="")` — generated code may call them bare.
- `expect_title` always builds `re.compile(f".*{re.escape(title)}.*", re.DOTALL)` — never pass a
  plain string (Playwright would require an exact match).
- Never register `on("dialog")` outside `DriverSession.open_context` — double registration
  double-handles dialogs. Popups get no routing handler (the contract registers on the
  open_context page only); captures on popups work through Playwright's own context managers.
- The captures construct facade shells via `__new__` and run the real `__init__` at block exit —
  the public constructors stay the only initialization path; add the actionable `__getattr__`
  guards for pre-resolution access.
- The facade member keeps the contract name `expect_dialog()`, implemented over Playwright's
  `page.expect_event("dialog")` — the Python client ships no `expect_dialog` (verified against
  1.62); the waiter semantics and the timeout message naming event "dialog" are identical.
  `expect_popup()` is a genuine Playwright method and arms directly.
- Delete the retired members outright — no deprecation aliases; the parity principle replaces
  backward compatibility.
- No new dependencies; Python 3.10 compatibility (no 3.11+ syntax); relative intra-package
  imports; Google docstrings on every public member; ruff must pass.
- Docs ride-along is in scope of the task: `docs/reference/driver-facade.md`,
  `docs/guides/writing-steps.md`, `docs/configuration.md`, `docs/getting-started.md`,
  `docs/index.md` updated to the new surface; `mkdocs.yml` navigation unchanged.
- Gates before done: `pytest tests/ -x` green, `ruff check prettyplay/ tests/` clean,
  `goga lint` 0 errors (cells already clean), and the two surface-consistency tests
  (`test_page_api_surface_members_exist_on_the_facades`,
  `test_page_api_surface_mirrors_the_facade_practice`) green.
