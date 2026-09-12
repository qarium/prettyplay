# Plan: `add-actions`

## Purpose

Bring the Python package to the moved contracts: full Playwright sync API parity for the driver
facade, the dialog routing/auto-accept setting, and the rewritten generation-request surface.

After implementation the package provides:

- `BrowserConfig.accept_dialogs` (neutral default `False`) with the
  `PRETTYPLAY_BROWSER_ACCEPT_DIALOGS` env override riding every existing config layer.
- A rebuilt `PageFacade` (mirror names: `goto`, `get_by_*`, `locator`; navigation, waits,
  expectations, `pages`, `bring_to_front`, `frame_locator`, `expect_dialog`, `expect_popup`),
  an extended `LocatorFacade` (advanced interactions + the full method-style expectation set),
  and the new `DialogFacade` / `FrameFacade` — all exported from `prettyplay.driver`.
- `DriverSession.open_context` wiring one `_DialogRouter` over the context page event, so every
  page of the context routes uncaptured dialogs by the setting.
- `SYSTEM_PROMPT` / `PAGE_API_SURFACE` constants mirroring the engine contract and the driver
  `facade` practice verbatim.
- Retired members (`open`, `find_by_*`) deleted with no aliases; docs pages updated to the new
  surface.

The most important gaps between contract and code: every entity above is absent or renamed in the
implementation; the CODEMANIFEST layer is already final (apply stage) and is **read-only**.
Implementation strategy: config → driver → engine, strict TDD per task, fakes over real browsers.

## Context

### Contract Surface

**Cell: `prettyplay/config`** (manifest `prettyplay/config/CODEMANIFEST`)

**Entity: `BrowserConfig`**
- Type: class (Entity)
- Declared `location`: `models.py`
- Facade obligation: importable from `prettyplay.config`
- Properties: `name -> str`, `screen -> str`, `headless -> bool`, `endpoint -> str`,
  `accept_dialogs -> bool` (new — whether dialogs outside a captured expect_dialog block are
  accepted automatically; `False` keeps the dismiss default)
- Semantic requirements: kw_only construction; every field has an empty or neutral default;
  `accept_dialogs` is a plain bool, no validator (unlike `name`/`endpoint`/`screen`);
  pydantic `extra="forbid"` unaffected
- Imported dependencies: none (uses `PrettyplayError` via loader)
- Annotation context: global annotations → pydantic v2 kw_only models with empty defaults; the
  browser group fields carry no `browser_` prefix

**Entity: `ConfigurationError`** (mutation `PrettyplayError::ConfigurationError(message: str)`)
- Type: class (Entity, mutation of `PrettyplayError` from `prettyplay/failures`)
- Declared `location`: `loader.py`
- Facade obligation: importable from `prettyplay.config`
- Unchanged by this plan — the new env parse failure reuses the existing raise path

**Entity: `load_config`**
- Type: function (Routine)
- Declared `location`: `loader.py`
- Facade obligation: importable from `prettyplay.config`
- Signature: `load_config(pyproject_path: str | None, overrides: Config | None) -> config: Config`
- Semantic requirements (delta): env list gains `PRETTYPLAY_BROWSER_ACCEPT_DIALOGS`;
  `browser.accept_dialogs` parses as boolean (true/false/1/0 case-insensitive); unparseable →
  `ConfigurationError` naming setting, received value, accepted form — never a silent ignore;
  `_ALLOWED_TEXT["browser.accept_dialogs"] = "a boolean"` renders the file-layer mismatch;
  explicit programmatic `False` participates in the group merge (bool is not str)
- Annotation context: Algorithm step 5 names the five `PRETTYPLAY_BROWSER_*` variables

**Cell: `prettyplay/driver`** (manifest `prettyplay/driver/CODEMANIFEST`)

**Entity: `DriverSession`**
- Type: class (Entity)
- Declared `location`: `session.py`
- Facade obligation: importable from `prettyplay.driver`
- Methods: `open_context() -> page: PageFacade` (changed — gains dialog-routing step 4),
  `close()` (unchanged)
- Semantic requirements for `open_context` (contract Algorithm, 5 steps): 1–3 unchanged lazy
  launch/connect + screen params inside the marshaled driver-thread call; **4 (new)** — register
  the single dialog routing handler for every page of the context before any step code runs, the
  open_context page included, through the context page event (`context.on("page", …)` registered
  before `context.new_page()`, so every new page registers exactly once, never twice); an active
  `expect_dialog` capture claims the dialog on its own page; otherwise accept when
  `accept_dialogs` is true, else an explicit dismiss restoring the Playwright dismiss default;
  **5** — wrap into `PageFacade` bound to the driver thread and return it
- Constraints: `PageFacade`, `LocatorFacade`, `DialogFacade`, `FrameFacade` stay untouched by the
  screen modes — changes live in context creation and dialog wiring only; facades never read
  config
- Imported dependencies: `Config` (Types) from `prettyplay/config`; practice `configuration`
  (Usages) from `prettyplay/config`

**Entity: `PageFacade`**
- Type: class (Entity)
- Declared `location`: `page.py`
- Facade obligation: importable from `prettyplay.driver`
- Properties: `url -> str`, `pages -> list[PageFacade]` (new — the open pages of this page's
  context, each a full `PageFacade`, popups and new tabs included)
- Methods (full mirror surface):
  - `goto(url: str)` — navigate and wait for the load state
  - `go_back()`, `go_forward()`, `reload()` — history navigation + reload, each waits for load
  - `wait_for_url(url: str)` — wait until the URL matches the glob pattern `url`
  - `wait_for_load_state(state: str)` — load | domcontentloaded | networkidle
  - `expect_url(url: str)` — assert URL matches the glob pattern — auto-waiting
  - `expect_title(title: str)` — assert the title **contains** `title` — auto-waiting
  - `get_by_role(role: str, name: str) -> element: LocatorFacade` — aria role + accessible name;
    empty `name` — match by role alone
  - `get_by_label(label: str)`, `get_by_text(text: str)`, `get_by_placeholder(placeholder: str)`,
    `get_by_alt_text(alt: str)`, `get_by_title(title: str)`, `get_by_test_id(test_id: str)` —
    each `-> element: LocatorFacade`
  - `locator(selector: str) -> element: LocatorFacade` — any selector: CSS, XPath (incl. the
    `xpath=` form), attribute selectors — verbatim pass-through
  - `expect_dialog() -> dialog: DialogFacade` — context-manager capture; the capture claims the
    dialog (the step controls accept/dismiss); no dialog fired → loud actionable timeout naming
    the awaited event
  - `expect_popup() -> popup: PageFacade` — context-manager capture of the opened page; no popup
    fired → loud actionable timeout naming the awaited event
  - `bring_to_front()` — raise this page above the others — the mirror switching primitive
  - `frame_locator(selector: str) -> frame: FrameFacade` — the locating scope of the iframe
  - `aria_snapshot() -> snapshot: str`, `screenshot() -> image: bytes` — kept
  - `scroll_to_element(element)`, `scroll_down(pixels)`, `scroll_up(pixels)`,
    `scroll_to_bottom()`, `scroll_to_top()`, `scroll_into_view(element, container)`,
    `scroll_container_down(container, pixels)`, `scroll_container_up(container, pixels)` — kept
  - `close()` — kept
- Deleted members: `open`, `find_by_role`, `find_by_label`, `find_by_text`, `find_by_attribute`,
  `find_by_css`, `find_by_xpath` — deleted outright, no deprecation aliases
- Requirements: every Playwright call runs in the driver thread of the owning session; the
  context-manager constructs resolve at block exit; a popup page is a full `PageFacade` bound to
  the same driver thread as its opener; locating methods never sleep
- Constraints: no method exposes raw Playwright objects — pages, dialogs and frame scopes
  included; the excluded capabilities (route/evaluate/CDP/clock/HAR/tracing/raw input devices)
  are absent

**Entity: `LocatorFacade`**
- Type: class (Entity)
- Declared `location`: `page.py`
- Facade obligation: importable from `prettyplay.driver`
- Methods (full set after extension):
  - `click(button: str)` — empty for the left button, `right`, `middle`
  - `dblclick()`, `fill(value)` (kept), `clear()`, `press(key)` (key name or combination, e.g.
    Enter, Control+A), `check()`, `uncheck()`, `hover()`, `select_option(value)` (kept)
  - `drag_to(target: LocatorFacade)` — drag onto the target, auto-waiting both endpoints
  - `set_input_files(path)` — upload one file by filesystem path
  - `expect_visible()` (kept), `expect_hidden()`, `expect_text(text)` (kept — contains,
    whitespace-normalized), `expect_enabled()` (kept), `expect_value(value)` (equals),
    `expect_checked()`, `expect_count(count)`, `expect_attribute(name, value)` (equals)
- Requirements: every action and expectation runs in the inherited driver thread; everything
  auto-waits; failed expectations raise assertion-style errors destined for failure
  classification

**Entity: `DialogFacade`** (new)
- Type: class (Entity)
- Declared `location`: `page.py`
- Facade obligation: importable from `prettyplay.driver`
- Signature: `DialogFacade(dialog: Dialog)`
- Properties: `type -> str` (alert, confirm, prompt or beforeunload), `message -> str`,
  `default_value -> str` (the prompt prefill; empty for the other kinds)
- Methods: `accept(prompt_text: str)` (empty — accept without an answer), `dismiss()`
- Requirements: every call runs in the inherited driver thread; `accept` and `dismiss` resolve
  the dialog exactly once

**Entity: `FrameFacade`** (new)
- Type: class (Entity)
- Declared `location`: `page.py`
- Facade obligation: importable from `prettyplay.driver`
- Signature: `FrameFacade(frame_locator: FrameLocator)`
- Methods: the `get_by_*` family (`get_by_role(role, name)` with the empty-name rule,
  `get_by_label`, `get_by_text`, `get_by_placeholder`, `get_by_alt_text`, `get_by_title`,
  `get_by_test_id`), `locator(selector)`, nested `frame_locator(selector) -> FrameFacade`
- Requirements: every action of a located element runs in the inherited driver thread; nested
  frames chain

**Cell: `prettyplay/engine`** (manifest `prettyplay/engine/CODEMANIFEST`)

**Entity: `StepGenerator`**
- Type: class (Entity)
- Declared `location`: `generator.py`
- Facade obligation: importable from `prettyplay.engine`
- No signature change. The module constants `SYSTEM_PROMPT` and `PAGE_API_SURFACE` it feeds to
  every request change to the new contract texts:
  - `SYSTEM_PROMPT` ← the engine CODEMANIFEST `system_prompt` usage **verbatim** (the
    Playwright-mirroring page API rule, label-or-placeholder locating, the
    `get_by_test_id`/`locator(selector)` rule for nameless elements, dialog capture, popup/new
    tab capture, iframe frame locators)
  - `PAGE_API_SURFACE` ← `prettyplay/driver/.usages/facade.md` verbatim as aligned
    `call — purpose` lines (page 33 rows → 32 listed, `page.close()` excluded with the standing
    comment; dialog 5; frame 3; element 19; the `page.url`/`page.pages` properties included)
- Requirement: every generation request carries the exact page API surface taken from `facade`
  from Imports — the listing and the practice change together

### Re-exports

No `->Name: {}` blocks exist in the three manifests. Facade obligations are language-level
(Python `__all__`):

- `prettyplay/driver/__init__.py` must expose `DialogFacade` and `FrameFacade` through `__all__`
  alongside the existing `DriverSession`, `LocatorFacade`, `PageFacade` — the only
  `__init__.py` change of this plan.
- `prettyplay/config/__init__.py`, `prettyplay/engine/__init__.py` — no changes (no new names).

### Usages Context

- `conventions` (`.goga/usages/conventions.md`): Python rules — 3.10+ compatibility, relative
  intra-package imports, pydantic kw_only models, Google docstrings, logging, test structure
  (`tests/<pkg>/test_<module>.py`, fakes over real browsers), ruff. Relevant to every task.
- `pydantic` (`.goga/usages/cooks/pydantic.md`): model rules for the config cell. Relevant to
  Task 1.
- `playwright` (`.goga/usages/cooks/playwright.md`): the sync API practices — lifecycle,
  engines/channels, screen modes, locators/auto-wait, the new sections: interactions (keyboard
  via element `press` — raw input devices stay outside the facade), dialogs routing and
  auto-accept (one routing handler per page of the context; registering any listener disables
  Playwright's implicit auto-dismiss — the handler itself resolves uncaptured dialogs; captures
  claim through `page.expect_event("dialog")` — the client ships no `expect_dialog`), popups and
  new tabs, frames and iframes, the full expectation set, waits. Relevant to Tasks 3–7.
- `system_prompt` (inline usage in the engine CODEMANIFEST header): the verbatim source text of
  the `SYSTEM_PROMPT` constant. Relevant to Task 8.
- `classification_prompt` (inline usage, engine): unchanged — not touched by this plan.

### Imported Usages

- `configuration` from `prettyplay/config` — path `prettyplay/config/.usages/configuration.md`.
  The browser-group settings the session reads, `accept_dialogs` included; no contractual
  obligation crosses the boundary (the driver only reads the switch). Relevant to Task 7.
- `facade` from `prettyplay/driver` — path `prettyplay/driver/.usages/facade.md`. The single
  source of the page API surface for generation requests; `PAGE_API_SURFACE` mirrors it
  verbatim. Relevant to Task 8 (and as the reference surface for Tasks 3–6).
- `classification` from `prettyplay/llm` — unchanged by this change; still referenced by the
  engine annotations. No task needed.

### Local Usages

None. The design's `.usages/` Update section confirms: `configuration`, `facade`, `generation`
are **current** (apply stage deliverable, complete); `healing` carries no facade member names.
No new `.usages/` files — the changes stay inside the existing functional domains.

### External Dependencies

- `playwright` (sync API): `Page`, `Locator`, `Dialog`, `FrameLocator`, `BrowserContext`,
  `expect`, `Error` — verified against playwright 1.62: `Page.expect_dialog()` does **not**
  exist; the dialog waiter is `page.expect_event("dialog")` (a `Literal["dialog"]` overload of
  the same `EventContextManager`/`EventInfo` machinery; timeout message
  `Timeout …ms exceeded while waiting for event "dialog"`); `Page.expect_popup()` exists and
  arms directly; `FrameLocator` carries the full `get_by_*` family + `locator` +
  `frame_locator` (playwright ≥1.49).
- `pydantic` v2: kw_only models, `extra="forbid"`, lax bool coercion on the file layer
  (bool-like strings such as `"yes"` coerce to `True`); the env layer stays strict.
- Tools: `pytest` (fixtures: `tmp_path`, `monkeypatch`), `unittest.mock.patch`,
  `ruff` (line-length 120, target py310), `goga` CLI (lint).
- No new dependency enters `pyproject.toml`.

### Entity Interaction (verbatim from the design)

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

## Facts

- The CODEMANIFEST layer is final: `goga lint` reports 8 cells, 0 errors; the design review
  found no DSL defects and made no CODEMANIFEST edits — implementation fixes code, never
  contracts.
- The dependency direction is config → driver → engine (driver imports `Config`; engine imports
  `Config`, `PageFacade`, the `facade` practice).
- The driver marshaling pattern is established: `PlaywrightWorker.run` in `driver/session.py`;
  facades call `_call(fn)`; `_worker is None` (hand-built facades) runs inline.
- The facade attachment pattern is established: `facade._worker = worker` after construction in
  `open_context`; `_wrap_locator` inherits the worker into `LocatorFacade`.
- The module-level `expect` is patched in tests as `mock.patch("prettyplay.driver.page.expect", …)`
  — the new expectation members keep using that module-level import.
- Existing test fake inventory: `FakePage`/`FakeLocator`/`FakeContext`/`FakeExpectation`/
  `FakeMouse` in `tests/driver/test_page.py`; `FakePlaywrightFactory`/`FakeEngine`/`FakeBrowser`/
  `FakeContext` in `tests/driver/test_session.py`; tmp-path pyproject fixtures in
  `tests/config`; provider fakes in `tests/engine` and `tests/test_integration.py`.
- Retired names currently appear in: `prettyplay/driver/page.py` (the members themselves),
  `prettyplay/engine/generator.py` (constants), `tests/driver/*`, `tests/engine/*`,
  `tests/test_integration.py`, `tests/test_executor.py`, `tests/test_scenario.py`,
  `tests/test_runtime.py` (verified: carries no retired page-facade names),
  `tests/llm/*` (opaque fixture strings:
  `FENCED_CODE`/`WORKING_CODE`/`STEP_CODE`, `page_api="page.open(...)"`),
  `tests/cache/test_models.py`, `tests/cache/test_store.py`, `docs/reference/driver-facade.md`.
- Docs pages exist at `docs/reference/driver-facade.md`, `docs/guides/writing-steps.md`,
  `docs/configuration.md`, `docs/getting-started.md`, `docs/index.md`; `mkdocs.yml` needs no
  navigation change (existing pages only).
- `expect_title` must build `re.compile(f".*{re.escape(title)}.*", re.DOTALL)` — Playwright's
  `to_have_title(str)` is exact-match; the contract demands contains.
- `get_by_role(role, name="")` must omit the `name` kwarg when empty — `name=""` in Playwright
  matches an empty accessible name (a different query).
- The session reads `accept_dialogs` once into the router at `open_context`; config is
  immutable, so a later change needs a new session (non-issue).
- Cached steps calling retired members fail on `AttributeError` — accepted per the task; the
  existing classify → rot → regenerate loop heals them lazily; no migration mechanism.

## Gap Analysis

- Missing contract entities: `DialogFacade`, `FrameFacade` (not in `prettyplay/driver/page.py`,
  not exported); `_DialogRouter`, `_DialogCapture`, `_PopupCapture` (internal, design-mandated).
- Missing facade exposure: `prettyplay/driver/__init__.py` lacks `DialogFacade`, `FrameFacade`.
- Missing members: everything new listed in Contract Surface — `BrowserConfig.accept_dialogs`,
  the env-override loader entries, `PageFacade` navigation/locating/expectation/capture/pages/
  frame members, `LocatorFacade` interactions and expectations, `open_context` step 4,
  the new `SYSTEM_PROMPT`/`PAGE_API_SURFACE` texts.
- API mismatches (renames): `open` → `goto`; `find_by_role/label/text` → `get_by_role/label/
  text`; `find_by_attribute/css/xpath` removed (collapse into `locator`/`get_by_test_id`);
  `click()` gains the `button` parameter; `LocatorFacade.expect_text` semantics already
  contains (implementation unchanged).
- Behavioral mismatches: no dialog routing exists today (Playwright's implicit auto-dismiss
  stands); `expect_title` does not exist; captures do not exist.
- Existing code that can be reused: `_call` marshaling, `_wrap_locator`, the whole scroll
  family, `aria_snapshot`, `screenshot`, `close`, the worker/session machinery, the loader
  override pipeline (`_ENV_NAMES`/`_BOOL_ENV_SETTINGS`/`_ALLOWED_TEXT`/`_apply_overrides`
  already handle the new field once registered), the test fake corpus.
- Test coverage gaps: every scenario in the design's Test Stack Trace (38 named scenarios);
  existing tests asserting the retired surface (they are updated, not deleted, within their
  tasks).
- Missing visibility in workspace or git: none — all files exist and are tracked; the topic
  directory `.goga/history/2026/add-actions/` carries the design.

---

## Tasks

> **Package ordering rule**: coding tasks for each package are completed before starting the next. Within each coding task, contract tests are written first (TDD workflow).

### Task 1: `BrowserConfig.accept_dialogs` field (TDD coding)

Package `prettyplay/config`, entity `BrowserConfig`, declared `location` `models.py`.

Add the dialog auto-accept switch to the browser settings group: one plain `bool` field with the
neutral default `False`, plus the class-docstring Attributes entry. The field is a plain switch —
`BrowserConfig` never resolves dialogs (routing belongs to the driver). pydantic validates it
with no custom validator (unlike `name`/`endpoint`/`screen`); the neutral default keeps the group
valid before a `[tool.prettyplay.browser]` section exists. Design algorithm, verbatim:

```
1. Add field `accept_dialogs: bool = False` after `endpoint`
   → neutral default keeps pre-section construction valid
2. Extend the class docstring Attributes with the setting
   (auto-accept of dialogs no captured expect_dialog block claims; False = Playwright dismiss default)
```

Edge case from the design: TOML `accept_dialogs = "maybe"` → pydantic bool-coercion failure →
`_render_validation` line via `_ALLOWED_TEXT["browser.accept_dialogs"] = "a boolean"` (the
`_ALLOWED_TEXT` entry itself is Task 2). pydantic lax mode still coerces bool-like strings such
as `"yes"`/`"on"` to `True` on the file layer — same as every other bool field of the group;
the env layer is stricter and rejects them.

**Usages relevant to this task:**
- `conventions`: pydantic kw_only models, Google docstrings, relative intra-package imports,
  ruff, tests at `tests/config/test_models.py` with fakes over real browsers.
- `pydantic`: model rules — kw_only group, empty/neutral defaults, `extra="forbid"`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/config/test_models.py` add
  `test_browser_config_accept_dialogs_default_and_explicit` — setup: none (pure model); input:
  `BrowserConfig()` and `BrowserConfig(accept_dialogs=True)`; trace:
  `BrowserConfig()` → pydantic kw_only construction → `accept_dialogs == False`;
  `BrowserConfig(accept_dialogs=True)` → pydantic validates the bool field → `accept_dialogs is
  True`; assertions: `BrowserConfig().accept_dialogs is False`,
  `BrowserConfig(accept_dialogs=True).accept_dialogs is True`,
  `Config().browser.accept_dialogs is False`; plus the existing signature-inspection test of the
  suite grows the field row. Expected to fail at this stage (the field does not exist).
- [x] **Code**: in `prettyplay/config/models.py` add `accept_dialogs: bool = False` to
  `BrowserConfig` after `endpoint` (plain field, no validator — pydantic rejects non-bools with
  the existing render path).
- [x] **Code**: extend the `BrowserConfig` class docstring Attributes with the setting —
  auto-accept of dialogs no captured `expect_dialog` block claims; `False` keeps the Playwright
  dismiss default; default `False` (neutral — the pre-setting behavior).
- [x] **Interface verification**: `pytest tests/config/test_models.py -x` — all pass; the field
  is settable through the kw_only constructor and readable as the property the contract declares.
- [x] **Logic tests**: confirm the existing negative/edge tests of the file still pass and that
  `Config()` default construction carries `browser.accept_dialogs is False` (the group grows one
  field; `extra="forbid"` unaffected).
- [x] **Debugging**: `pytest tests/config/ -x` — fix implementation code until all tests pass
  (do NOT fix test code).
- [x] **Contract re-verification**: facade `prettyplay.config` still exports `BrowserConfig`;
  the declared property `accept_dialogs -> bool` exists; kw_only and neutral default hold.
- [x] **Lint**: `ruff check prettyplay/config/ tests/config/` — fix formatting if necessary.

### Task 2: `load_config` env override for `accept_dialogs` (TDD coding)

Package `prettyplay/config`, entity `load_config`, declared `location` `loader.py`.

The new setting rides every existing loader layer. Design algorithm, verbatim:

```
1. _ENV_NAMES += {"browser.accept_dialogs": "PRETTYPLAY_BROWSER_ACCEPT_DIALOGS"}
   (append "browser.accept_dialogs" to the settings tuple)
2. _BOOL_ENV_SETTINGS += "browser.accept_dialogs"
3. _ALLOWED_TEXT["browser.accept_dialogs"] = "a boolean"
4. Module docstring: extend the flat group env-names mention with ACCEPT_DIALOGS
```

Verified load chain (from the design trace — transfer into implementation): env
`PRETTYPLAY_BROWSER_ACCEPT_DIALOGS=true` → `_ENV_NAMES` maps `"browser.accept_dialogs"` → the
dotted key routes into `group_env` → merged into the `browser` section dict (same mechanism as
`browser.headless`) → `_parse_env_scalar` accepts `true/1/false/0` case-insensitively, an
unparseable value raises `ConfigurationError` naming the setting, the received value and the
accepted form → `Config(**merged)` → pydantic validates → `_apply_overrides` group merge reaches
the field: the condition `(group_value or not isinstance(group_value, str))` includes `False`
(bool is not str), so an explicit programmatic `False` overrides a file `true` — identical to
`strict`.

**Usages relevant to this task:**
- `conventions`: test structure at `tests/config/test_loader.py`, tmp-path pyproject fixtures,
  monkeypatch env, ruff.
- `pydantic`: layered resolution — programmatic wins only when explicitly set; file and env
  values validate identically.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/config/test_loader.py` extend the existing
  `test_every_setting_has_an_env_override` — trace: `_ENV_NAMES` values ⊇
  {PRETTYPLAY_PROVIDER, PRETTYPLAY_MODEL, …, PRETTYPLAY_BROWSER_NAME, PRETTYPLAY_BROWSER_SCREEN,
  PRETTYPLAY_BROWSER_HEADLESS, PRETTYPLAY_BROWSER_ENDPOINT, PRETTYPLAY_BROWSER_ACCEPT_DIALOGS,
  PRETTYPLAY_STRICT, PRETTYPLAY_CLASSIFICATION_PROMPT}; assertions: all five browser variables
  and every scalar setting present; count matches the model fields. Expected to fail (the entry
  is absent).
- [x] **Code**: append `"browser.accept_dialogs"` to the settings tuple of `_ENV_NAMES` in
  `prettyplay/config/loader.py` (the dict comprehension derives
  `PRETTYPLAY_BROWSER_ACCEPT_DIALOGS`).
- [x] **Code**: add `"browser.accept_dialogs"` to `_BOOL_ENV_SETTINGS`.
- [x] **Code**: add `"browser.accept_dialogs": "a boolean"` to `_ALLOWED_TEXT`.
- [x] **Code**: extend the flat group env-names mention
  (`PRETTYPLAY_BROWSER_{NAME|SCREEN|HEADLESS|ENDPOINT}` →
  `PRETTYPLAY_BROWSER_{NAME|SCREEN|HEADLESS|ENDPOINT|ACCEPT_DIALOGS}`) in **both** places
  carrying it — the loader module docstring and the `load_config` docstring.
- [x] **Interface verification**: `pytest tests/config/test_loader.py -x` — the registry test
  passes; the override exists and parses by field type.
- [x] **Logic tests** (all in `tests/config/test_loader.py`, from the design):
  - `test_env_override_parses_accept_dialogs_by_type` — setup: tmp_path pyproject.toml with
    `[tool.prettyplay]` `model = "m"` and a browser group without `accept_dialogs`;
    monkeypatch env; input: parametrized `("true", True)`, `("1", True)`, `("false", False)`,
    `("0", False)`; trace: `load_config(pyproject_path=str(toml))` →
    `_collect_env_overrides()` → `_parse_env_scalar("browser.accept_dialogs", raw)` returns
    True/False → group_env merge → `Config(**merged)`; assertion:
    `config.browser.accept_dialogs is expected` for each row.
  - `test_env_override_rejects_unparseable_accept_dialogs` — setup: as above with
    `PRETTYPLAY_BROWSER_ACCEPT_DIALOGS=yes`; trace: `_parse_env_scalar("browser.accept_dialogs",
    "yes")` raises `ConfigurationError("browser.accept_dialogs: received 'yes' — allowed: a
    boolean (true/false/1/0)")`; assertion: `pytest.raises(ConfigurationError)` — message names
    the setting, `'yes'` and the accepted form. ("never a silent ignore".)
  - `test_programmatic_accept_dialogs_merges_into_group` — setup: pyproject with
    `[tool.prettyplay.browser]` `accept_dialogs = true`; input:
    `load_config(path, overrides=PrettyConfig(browser=BrowserConfig()))` (unset) and
    `overrides=PrettyConfig(browser=BrowserConfig(accept_dialogs=False))` (explicit False);
    trace: `_apply_overrides` group merge — unset → skipped → file `True` survives; explicit
    `False` → bool participates → `False` wins; assertions: unset override →
    `config.browser.accept_dialogs is True`; explicit False → `is False`. ("an explicit False
    overrides too".)
- [x] **Debugging**: `pytest tests/config/ -x` — fix implementation code until all tests pass
  (do NOT fix test code).
- [x] **Contract re-verification**: `load_config` signature unchanged; a raw
  `pydantic.ValidationError` never leaves the loader (the new render line flows through
  `_render_validation` via `_ALLOWED_TEXT`); facade `prettyplay.config` exports unchanged.
- [x] **Lint**: `ruff check prettyplay/config/ tests/config/` — fix formatting if necessary.

### Task 3: `LocatorFacade` mirror extension — interactions and expectations (TDD coding)

Package `prettyplay/driver`, entity `LocatorFacade`, declared `location` `page.py`.

Extend the element facade to the mirror action + expectation set. The class exists with
`_call`, `click`, `fill`, `select_option`, `expect_visible`, `expect_text`, `expect_enabled` —
this task adds the rest. Design member → call table, verbatim:

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

`click`'s empty-string → `"left"` mapping is the only non-verbatim argument transform. The raw
locator of `drag_to`'s target crosses facade-to-facade *inside* the boundary module, never out.
The method-style `expect_*` names replacing the chained `to_be_*` model are the declared
non-mirror family. All calls marshal through the inherited worker; failures of expectations
raise `AssertionError` (classification path), action errors are Playwright errors (retry path).

**Usages relevant to this task:**
- `conventions`: Google docstrings (`Args`/`Raises` as the existing members), ruff, tests in
  `tests/driver/test_page.py` extending the existing `FakeLocator`/`FakeExpectation` recorders;
  `expect` patched as `mock.patch("prettyplay.driver.page.expect", …)`.
- `playwright`: the full expectation set (`to_be_hidden`, `to_have_value`, `to_be_checked`,
  `to_have_count`, `to_have_attribute`); `press` combination syntax (`"Enter"`, `"Control+A"`);
  `set_input_files` path form; `drag_to` semantics; auto-wait actionability everywhere —
  "Locating methods never sleep" holds.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/driver/test_page.py` add a signature/surface check for the
  new members of `LocatorFacade` (`click` now takes `button: str = ""`; `dblclick`, `clear`,
  `press`, `check`, `uncheck`, `hover`, `drag_to`, `set_input_files`, `expect_hidden`,
  `expect_value`, `expect_checked`, `expect_count`, `expect_attribute` exist with the declared
  signatures — `inspect.signature`/`get_type_hints` in the suite's established style). Expected
  to fail at this stage.
- [x] **Code**: extend the fakes first where the tests need them — `FakeLocator.click` records
  `button` kwarg; add `dblclick()`, `clear(v)`, `press(k)`, `check()`, `uncheck()`, `hover()`,
  `drag_to(target)`, `set_input_files(p)` recording methods; `FakeExpectation` grows
  `to_be_hidden`, `to_have_value`, `to_be_checked`, `to_have_count`, `to_have_attribute`.
- [x] **Code**: implement the members in `prettyplay/driver/page.py` exactly per the table
  above, with Google docstrings carrying the contract descriptions (`button`: the mouse button —
  empty for the left button, right for the right button, middle for the middle button; `key`:
  the key name or combination, e.g. Enter or Control+A; `path`: the filesystem path of the file
  to upload; `target`: the located drop target element; equality semantics for `expect_value`/
  `expect_attribute`).
- [x] **Interface verification**: `pytest tests/driver/test_page.py -x -k "element or click or
  drag or expectation"` — the contract tests pass against the implemented signatures.
- [x] **Logic tests** (in `tests/driver/test_page.py`, from the design):
  - `test_element_action_family_delegates` — setup: `FakeLocator` records; parametrized
    member/input table: `dblclick()`, `clear()`, `press("Control+A")`, `check()`, `uncheck()`,
    `hover()`, `select_option("red")`, `set_input_files("avatar.png")`; trace:
    `element.<member>(<args>)` → `fake_locator.<member>(<args>)` recorded verbatim; assertion:
    each mirror call recorded with exact args.
  - `test_click_maps_button_values` — setup: `FakeLocator.click(**kwargs)` records; input:
    `click()`, `click("")`, `click("right")`, `click("middle")`; trace: `element.click()` →
    `fake_locator.click(button="left")`; `element.click("")` → `button="left"`;
    `element.click("right")` → `button="right"`; assertion: recorded kwargs per row.
  - `test_drag_to_receives_the_target_locator` — setup: two fakes, source and target
    `FakeLocator`; input: `source.drag_to(target)`; trace: `source.drag_to(target)` →
    `fake_source.drag_to(target._locator)` recorded; assertion: the raw target locator passed to
    Playwright is exactly the wrapped one.
  - `test_expectation_family_uses_the_full_set` — setup: patched `expect` recorder with
    `to_be_hidden/to_have_value/to_be_checked/to_have_count/to_have_attribute`; input:
    `expect_hidden()`, `expect_value("user")`, `expect_checked()`, `expect_count(3)`,
    `expect_attribute("href", "/docs")` (+ the kept visible/text/enabled); trace:
    `element.expect_value("user")` → `expect(loc).to_have_value("user")` recorded, … each member
    → its `to_*` assertion with exact args; assertion: the assertion list == the expected 8
    entries with args.
- [x] **Debugging**: `pytest tests/driver/test_page.py -x` — fix implementation code until all
  tests pass (do NOT fix test code).
- [x] **Contract re-verification**: `LocatorFacade` importable from `prettyplay.driver`; the
  full method list matches the CODEMANIFEST `LocatorFacade` methods verbatim; no raw Playwright
  object is returned; expectations raise `AssertionError` on failure (the fakes' recorder honors
  the same call shape).
- [x] **Lint**: `ruff check prettyplay/driver/ tests/driver/` — fix formatting, apply
  decomposition if necessary.

### Task 4: `DialogFacade` and `FrameFacade` — new facades + driver exports (TDD coding)

Package `prettyplay/driver`, entities `DialogFacade` (new) and `FrameFacade` (new), declared
`location` `page.py`; plus the package facade obligation (`__init__.py` re-exports).

`DialogFacade(dialog: Dialog)` — the wrapped dialog captured by `expect_dialog`;
step-controlled handling. `FrameFacade(frame_locator: FrameLocator)` — the frame-scoped locator
factory; nested frames chain. Design algorithms, verbatim:

```
DialogFacade:
type           → _call(lambda: self._dialog.type)            (property)
message        → _call(lambda: self._dialog.message)         (property)
default_value  → _call(lambda: self._dialog.default_value)   (property)
accept(t="")   → _call(lambda: self._dialog.accept() if t == "" else self._dialog.accept(prompt_text=t))
dismiss()      → _call(self._dialog.dismiss)
```

```
FrameFacade:
get_by_role(r, name="") → fl.get_by_role(r) | fl.get_by_role(r, name=name)   → LocatorFacade + worker
get_by_label/get_by_text/get_by_placeholder/get_by_alt_text/get_by_title/get_by_test_id
                        → fl.<same name>(arg)                               → LocatorFacade + worker
locator(s)              → fl.locator(s)                                     → LocatorFacade + worker
frame_locator(s)        → FrameFacade(fl.frame_locator(s)) + worker
```

The `accept("")` edge case: accept without an answer (no `prompt_text` kwarg). Double handling
is Playwright's own loud error — "accept and dismiss resolve the dialog exactly once" holds
naturally. A frame selector matching nothing fails at action time (Playwright auto-wait), not at
scope creation. `Dialog.default_value` is `""` for non-prompt kinds. Located raw locators wrap
into `LocatorFacade` with worker inheritance — actions on frame content behave exactly like page
content.

`_worker` attachment follows the established pattern (`__init__` sets `_worker: PlaywrightWorker
| None = None`; the creating facade attaches its own), and both classes get the actionable
`__getattr__` pre-resolution guard in Task 6 (the capture shells) — here the public constructors
are the only initialization path.

**Usages relevant to this task:**
- `conventions`: Google docstrings, PascalCase classes, type hints mandatory, ruff; new fakes
  (`FakeDialog`, `FakeFrameLocator`) follow the existing recording style in
  `tests/driver/test_page.py`.
- `playwright`: `Dialog` members (`type`/`message`/`default_value`/`accept(prompt_text)`/
  `dismiss`); `FrameLocator` carries the full `get_by_*` family + `locator` + `frame_locator`
  (playwright ≥1.49); the same empty-name rule for `get_by_role`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/driver/test_page.py` add surface checks — `DialogFacade` and
  `FrameFacade` are importable from `prettyplay.driver` (facade obligation); the property and
  method sets match the CODEMANIFEST verbatim (dialog: properties `type`/`message`/
  `default_value`, methods `accept(prompt_text: str = "")`/`dismiss()`; frame: the `get_by_*`
  family with `get_by_role(role, name="")`, `locator`, `frame_locator`). Expected to fail at
  this stage (the classes do not exist).
- [x] **Code**: add `FakeDialog` (records `accept` kwargs and `dismiss`; attributes
  `type`/`message`/`default_value`) and `FakeFrameLocator` (records calls; returns
  `FakeLocator`s / a nested `FakeFrameLocator`) to `tests/driver/test_page.py`.
- [x] **Code**: implement `DialogFacade` in `prettyplay/driver/page.py` per its algorithm table
  (properties through `_call`; `accept(prompt_text="")` omits the kwarg when empty; `dismiss`).
- [x] **Code**: implement `FrameFacade` in `prettyplay/driver/page.py` per its algorithm table
  (the `get_by_*` family with the empty-name omission rule for `get_by_role`; located locators
  wrap through the worker-inheriting wrap; `frame_locator` returns a nested `FrameFacade` with
  the worker attached).
- [x] **Code**: export both classes — `prettyplay/driver/__init__.py` imports them from
  `.page` and lists `DialogFacade`, `FrameFacade` in `__all__` (sorted per the existing style).
- [x] **Interface verification**: `pytest tests/driver/test_page.py -x -k "dialog or frame"` and
  `python -c "from prettyplay.driver import DialogFacade, FrameFacade"` — all pass.
- [x] **Logic tests** (in `tests/driver/test_page.py`, from the design):
  - `test_dialog_facade_members` — setup: `DialogFacade(FakeDialog(type="prompt",
    message="Name?", default_value="Ann"))`; input: properties + `accept("Bob")` + `dismiss()`;
    trace: `dialog.type` → `"prompt"`; `dialog.message` → `"Name?"`; `dialog.default_value` →
    `"Ann"`; `dialog.accept("Bob")` → `FakeDialog.accept(prompt_text="Bob")`;
    `dialog.dismiss()` → `FakeDialog.dismiss()`; assertions: values and kwargs as above. (The
    empty-`prompt_text` variant is covered by the capture test in Task 6.)
  - `test_frame_facade_family_and_nesting` — setup: `FakeFrameLocator` records; returns
    `FakeLocator`s / a nested `FakeFrameLocator`; input: `frame.get_by_role("button",
    name="Pay")`, `frame.get_by_test_id("pay")`, `frame.locator("#x")`,
    `frame.frame_locator("#inner")`; empty-name variant; trace: `frame.get_by_role(…)` →
    `fl.get_by_role(…)` → `LocatorFacade` (+worker); `frame.frame_locator("#inner")` →
    `fl.frame_locator("#inner")` → `FrameFacade`; assertions: mirror calls recorded; wrapped
    types correct; no raw object escapes.
- [x] **Debugging**: `pytest tests/driver/test_page.py -x` — fix implementation code until all
  tests pass (do NOT fix test code).
- [x] **Contract re-verification**: both facades importable from `prettyplay.driver` (`__all__`
  now `DriverSession`, `DialogFacade`, `FrameFacade`, `LocatorFacade`, `PageFacade`); no raw
  Playwright object crosses either facade; every call goes through `_call`.
- [x] **Lint**: `ruff check prettyplay/driver/ tests/driver/` — fix formatting, apply
  decomposition if necessary.

### Task 5: `PageFacade` mirror rebuild — navigation, locating, expectations, page switching (TDD coding)

Package `prettyplay/driver`, entity `PageFacade`, declared `location` `page.py`.

Rebuild the page facade to the mirror surface: rename `open` → `goto`, `find_by_role/label/
text` → `get_by_role/label/text`; delete `find_by_attribute/css/xpath` (they collapse into
`locator`/`get_by_test_id`); add the navigation, wait and expectation members, the remaining
`get_by_*` family, `pages`, `bring_to_front`, `frame_locator`. The scroll family,
`aria_snapshot`, `screenshot`, `url`, `close` are kept verbatim. Design member → call table,
verbatim:

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
bring_to_front()           → self._page.bring_to_front()
frame_locator(s)           → FrameFacade(self._page.frame_locator(s)) + worker
aria_snapshot()/screenshot()/scroll_*/close()                   (kept verbatim)
```

Verified logic (transfer from the design traces):
- `goto(url)` uses Playwright's default `wait_until="load"` — "wait for the load state".
- A plain string passed to `wait_for_url`/`to_have_url` is a glob pattern in Playwright — pass
  through unchanged; the facade must not transform the value.
- `expect_title` always builds the unanchored escaped pattern
  `re.compile(f".*{re.escape(title)}.*", re.DOTALL)` — correct under both possible Playwright
  regex semantics; never pass a plain string (Playwright would require an exact match).
- `get_by_role(role, name="")` omits the `name` kwarg when empty — `name=""` would match an
  empty accessible name (a real Playwright semantic difference); non-empty passes the kwarg.
- `locator(selector)` is a verbatim pass-through: `//`-prefixed XPath auto-detects, the explicit
  `xpath=` engine prefix works as a selector form, CSS and attribute selectors pass unchanged —
  no facade-side sniffing or rewriting (the old `find_by_xpath` wrapping is gone with the
  method).
- `pages` wraps each raw page as `PageFacade(raw, self._context)` with `_worker` and `_router`
  attached (the `_router` attribute arrives in Task 6; here attach `_worker` and leave the
  router hookup to Task 6 — or define `_router` as part of this task's `pages` wiring only if
  Task 6 has not landed; the final state after Task 6 attaches both).
- `wait_for_load_state` invalid states are Playwright's own loud errors — no facade-level
  validation.
- Retired members are deleted outright — no deprecation aliases; the parity principle replaces
  backward compatibility. The module docstring's backward-compatibility wording is replaced
  with the parity wording.

**Usages relevant to this task:**
- `conventions`: Google docstrings matching the existing page.py style; ruff; the `FakePage`
  recorder grows the mirror methods.
- `playwright`: navigation semantics (`goto`/`go_back`/`go_forward`/`reload` return after the
  load state); `wait_for_url` glob strings; `wait_for_load_state` states; `to_have_url` glob;
  `get_by_test_id` uses the default `data-testid` attribute; selector engines.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/driver/test_page.py` — `test_retired_surface_is_gone`
  (input: retired names; trace: `hasattr(PageFacade, name)` for `("open", "find_by_role",
  "find_by_label", "find_by_text", "find_by_attribute", "find_by_css", "find_by_xpath")` → all
  `False`; assertion: no retired member exists) and `test_page_surface_matches_the_contract`
  (input: the expected member listing — properties `url`, `pages`; methods `goto`, `go_back`,
  `go_forward`, `reload`, `wait_for_url`, `wait_for_load_state`, `expect_url`, `expect_title`,
  `get_by_role`, `get_by_label`, `get_by_text`, `get_by_placeholder`, `get_by_alt_text`,
  `get_by_title`, `get_by_test_id`, `locator`, `expect_dialog`, `expect_popup`,
  `bring_to_front`, `frame_locator`, `aria_snapshot`, `screenshot`, `scroll_to_element`,
  `scroll_down`, `scroll_up`, `scroll_to_bottom`, `scroll_to_top`, `scroll_into_view`,
  `scroll_container_down`, `scroll_container_up`, `close`; trace: `public = {n for n in
  dir(PageFacade) if not n.startswith("_")}`; assertion: `expected == public` — exact set
  equality, nothing extra, nothing missing). Write the test now with the **full** expected set;
  after this task it still fails on the two capture names (`expect_dialog` and `expect_popup`
  land in Task 6) — Task 6's contract-tests checkbox brings it green; the set-equality gate must
  be green before Task 7 starts.
- [x] **Code**: extend the `FakePage` recorder — rename `goto` recording (exists), add
  `go_back()`, `go_forward()`, `reload()`, `wait_for_url(u)`, `wait_for_load_state(s)`,
  `get_by_placeholder`, `get_by_alt_text`, `get_by_title`, `get_by_test_id`, `bring_to_front()`,
  `frame_locator(selector)` (returns a `FakeFrameLocator`), and make `locator(selector)` record
  and return a fresh `FakeLocator` (keeping the `FakeBodyLocator` aria-snapshot path for
  `locator("body")` if the existing tests rely on it); `FakeContext` grows `pages` and `on`.
- [x] **Code**: implement the members in `prettyplay/driver/page.py` per the table above —
  navigation family, wait family, `expect_url`/`expect_title`, the `get_by_*` family with the
  empty-name rule, `locator`, `pages` property, `bring_to_front`, `frame_locator` (wrapping into
  the Task 4 `FrameFacade` with worker attach).
- [x] **Code**: delete the retired members `open`, `find_by_role`, `find_by_label`,
  `find_by_text`, `find_by_attribute`, `find_by_css`, `find_by_xpath` outright and replace the
  module docstring's backward-compatibility paragraph with the parity wording (mirror of the
  Playwright sync API at page/locator level; declared non-mirror families; excluded
  capabilities).
- [x] **Code**: update the existing tests of `tests/driver/test_page.py` that call the retired
  surface (`open`, `find_by_*`) to the mirror names — the assertion shape stays, only the
  recorded method names change; likewise the three step-code call sites of
  `tests/driver/test_session.py` that drive the real facade
  (`test_playwright_lifecycle_runs_in_dedicated_thread`,
  `test_facade_calls_execute_in_worker_thread`,
  `test_worker_exception_propagates_with_type_and_message`): `page.open` → `page.goto`,
  `find_by_role/label/text` → `get_by_role/label/text` — assertions unchanged.
- [x] **Interface verification**: `pytest tests/driver/test_page.py -x -k "not
  test_page_surface_matches_the_contract"` — the delegation, rename and retirement tests pass;
  the excluded set-equality test stays red on the two capture names until Task 6 (by design).
- [x] **Logic tests** (in `tests/driver/test_page.py`, from the design):
  - `test_navigation_members_delegate_to_playwright` — setup: `FakePage` records;
    `PageFacade(fake_page, fake_context)`; input: `goto("https://example.com")`, `go_back()`,
    `go_forward()`, `reload()`, `wait_for_url("**/dashboard")`,
    `wait_for_load_state("networkidle")`; trace: each member → its mirror call with the verbatim
    argument; assertion: `fake.calls == [("goto", "https://example.com"), ("go_back",),
    ("go_forward",), ("reload",), ("wait_for_url", "**/dashboard"), ("wait_for_load_state",
    "networkidle")]`.
  - `test_get_by_family_delegates_and_wraps` — setup: `FakePage` returns distinct `FakeLocator`s
    per method; input: each locator method with a concrete value (`get_by_role("button",
    name="Sign in")`, `get_by_label("Username")`, `get_by_text("Welcome")`,
    `get_by_placeholder("Search")`, `get_by_alt_text("Logo")`, `get_by_title("Close")`,
    `get_by_test_id("submit")`, `locator("form > button")`); trace: e.g.
    `facade.get_by_role("button", name="Sign in")` → `fake_page.get_by_role("button",
    name="Sign in")` recorded with kwarg → `_wrap_locator` → `LocatorFacade`; assertion: each
    returns a `LocatorFacade` wrapping the fake locator it asked for; `fake.calls` carries the
    exact method + args.
  - `test_get_by_role_empty_name_matches_by_role_alone` — input: `facade.get_by_role("button")`
    / `facade.get_by_role("button", name="")`; trace: → `fake_page.get_by_role("button")` with
    NO `name` kwarg; assertion: the recorded call has no `name` kwarg.
  - `test_locator_passes_selectors_verbatim` — input: `"form > button.primary"`,
    `"//button[@type='submit']"`, `"xpath=*[@id='main']"`, `"[data-qa='row'] > input"`; trace:
    `facade.locator(selector)` → `fake_page.locator(selector)` byte-identical; assertion:
    recorded selector equals the input for every form.
  - `test_expect_title_builds_a_contains_pattern` — setup: patch
    `prettyplay.driver.page.expect` with a recorder; input: `facade.expect_title("Dashboard")`;
    trace: → `expect(fake_page).to_have_title(pattern)` with `pattern.pattern == ".*Dashboard.*"`
    (escaped input) and the `DOTALL` flag set; assertion: the received pattern source and flags;
    the receiver is the wrapped page.
  - `test_expect_url_uses_glob_string` — setup: patched expect recorder; input:
    `facade.expect_url("**/dashboard")`; trace: → `expect(fake_page).to_have_url("**/dashboard")`
    string verbatim — glob; assertion: the string passes through unchanged.
  - `test_pages_property_wraps_context_pages` — setup: `FakeContext.pages = [main, popup]` (two
    `FakePage`s); worker fake records runs; input: `facade.pages`; trace: `facade.pages` →
    `_call` → `list(fake_context.pages)` → `PageFacade(main, ctx)`, `PageFacade(popup, ctx)` with
    worker attached; assertions: `len(result) == 2`; each `isinstance PageFacade`; each
    `._worker is` the session worker.
- [x] **Logic tests (edge)**: `test_expect_title_with_regex_metacharacters` — setup: patched
  expect recorder; input: `facade.expect_title("C++ (2026)")`; trace: pattern source is
  `re.escape` of the input between `.*` bookends; assertion: metacharacters escaped — the title
  is matched literally (contains semantics must not turn into an accidental regex).
- [x] **Debugging**: `pytest tests/driver/test_page.py tests/driver/test_session.py -x -k "not
  test_page_surface_matches_the_contract"` — fix implementation code until all tests pass (do
  NOT fix test code); the session tests keep passing (open_context still returns the facade;
  only wiring changes come in Task 7).
- [x] **Contract re-verification**: `PageFacade` public surface == the CODEMANIFEST member list
  (the Task 6 capture members included by then); `prettyplay.driver` facade exports unchanged
  plus Task 4's additions; no raw Playwright object returned (`pages` returns facades,
  `frame_locator` returns `FrameFacade`, locating returns `LocatorFacade`).
- [x] **Lint**: `ruff check prettyplay/driver/ tests/driver/` — fix formatting, apply
  decomposition if necessary.

### Task 6: `_DialogRouter` and the captures — `expect_dialog` / `expect_popup` (TDD coding)

Package `prettyplay/driver`, internal machinery of `PageFacade` (`location` `page.py`). This
task completes the `PageFacade` contract members `expect_dialog()` and `expect_popup()`.

`_DialogRouter` — the single dialog routing state of one browser context. Design algorithm,
verbatim:

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

Edge case: a dialog on page A while a capture is armed on popup page B → A's handler routes
(per-page comparison), B's dialog goes to its own capture. Handler exceptions propagate into the
triggering facade call (loud).

The captures (the shared mechanism) — design pseudocode, verbatim:

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

Verified facts (transfer from the design traces):
- playwright 1.62 ships **no** `Page.expect_dialog()`; the capture arms through
  `page.expect_event("dialog")` (a `Literal["dialog"]` overload; same
  `EventContextManager`/`EventInfo` machinery: `__enter__` arms and returns immediately,
  `.value` blocks, `__exit__` waits or cancels on a block exception) and produces the same
  `Timeout …ms exceeded while waiting for event "dialog"` error. The facade member keeps the
  contract name `expect_dialog()`. `expect_popup()` is a genuine Playwright method and arms
  directly.
- `__exit__` outcomes: dialog fired → the raw `Dialog` is `cm.value`; no dialog and no block
  error → Playwright raises `Error('Timeout … waiting for event "dialog"')` — actionable, names
  the awaited event, non-`AssertionError` (an action failure that regenerates, never a failed
  check); block raised → Playwright's exit cancels the waiter without a timeout, the block
  exception propagates. Then `finally: router.capture_page = None`; initialize the shell
  (`facade.__init__(dialog)`; `._worker = self._worker`); return `False` (never suppress).
- The bound variable is a genuine `DialogFacade` (contract: "the block's variable is the
  `DialogFacade` of the captured dialog"); its state fills at exit — the captures construct
  facade shells via `__new__` and run the real `__init__` at block exit, so the public
  constructors stay the only initialization path; no sentinel/None states.
- The popup shell `__init__(popup_page, popup_page.context)` inherits the opener's worker and
  the **shared context router**: the popup already carries the routing handler (the context page
  event registered it when the page opened), so a capture on the popup must mark the shared
  router for the handler to skip, and an uncaptured dialog on the popup follows
  `accept_dialogs` exactly like the main page.
- Double-wrap safety: `pages`/`expect_popup` may wrap the same raw page more than once —
  harmless, because the dialog handler belongs to the **page** (registered once through the
  context page event), never to a facade; wrapping never registers anything.
- Hand-built facade (no worker): `_call` runs inline; `_router` lazily defaults to a
  `_DialogRouter(accept_dialogs=False)` so `expect_dialog` still works in tests.
- Concurrency: the routing handler runs inside the driver thread (never marshals); the capture
  enter/exit are each one marshaled call, so the block body's calls interleave correctly between
  them; the calling thread never adopts the Playwright event loop.

**Usages relevant to this task:**
- `conventions`: tests in `tests/driver/test_page.py`; fakes mirror the real arming call —
  `FakePage.expect_event("dialog")` returns a recording context manager; ruff.
- `playwright`: the dialogs section — registering any listener disables Playwright's implicit
  auto-dismiss; unconditional routing handler; captures claim first; `expect_popup` semantics;
  the `EventContextManager` contract.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: the `expect_dialog`/`expect_popup` rows of
  `test_page_surface_matches_the_contract` (Task 5) must now pass; add a signature check — both
  are zero-argument methods returning the capture context manager. Expected to fail before the
  code lands.
- [x] **Code**: add `_DialogRouter` to `prettyplay/driver/page.py` per its algorithm
  (`accept_dialogs` bool, `capture_page: Page | None = None`, `handle_for(page)` returning the
  per-page closure `handler(dialog)` with the claim → accept → dismiss chain).
- [x] **Code**: add `_DialogCapture` and `_PopupCapture` per the pseudocode — `__enter__`/`__exit__`
  each as one `_call`-marshaled unit; `expect_event("dialog")` for the dialog waiter
  (the fake mirrors this arming call); `expect_popup()` direct; `finally` clears
  `router.capture_page`; shell initialization at exit; `return False`.
- [x] **Code**: `PageFacade.expect_dialog()` → `_DialogCapture(self)`; `PageFacade.expect_popup()`
  → `_PopupCapture(self)`; `PageFacade.__init__` gains `_router: _DialogRouter | None = None`
  with the lazy `accept_dialogs=False` default at first capture use for hand-built facades;
  `_wrap_page` helper (or the same inline pattern) attaches `_worker` and `_router` for `pages`
  and popup wrapping.
- [x] **Code**: add the actionable `__getattr__` pre-resolution guard on `PageFacade` and
  `DialogFacade`: raise `AttributeError("… resolves at the end of the with-block — read it
  after the block …")` for unmapped attribute access before initialization (careful: `__getattr__`
  fires only for missing attributes — keep dunder/internal names working).
- [x] **Code**: extend the fakes — `FakePage.expect_event("dialog")` and `FakePage.expect_popup()`
  return recording context managers whose `__exit__` resolves `value` (a `FakeDialog` / a
    `FakePopupPage` with `.context`) or raises the Playwright-style timeout `Error`.
- [x] **Interface verification**: `pytest tests/driver/test_page.py -x -k "dialog or popup or
  marshal or inline"` — all pass.
- [x] **Logic tests** (in `tests/driver/test_page.py`, from the design):
  - `test_expect_dialog_yields_usable_dialog_facade` — setup: `FakePage.expect_event("dialog")`
    returns a recording cm whose `__exit__` resolves `value = FakeDialog(type="confirm",
    message="Delete?", default_value="")`; `FakeDialog` records accept/dismiss kwargs; input:
    `with facade.expect_dialog() as dialog: facade.get_by_role("button", name="Delete").click()`
    then `assert dialog.message == "Delete?"`; `dialog.accept()`; trace: `__enter__` →
    `router.capture_page` set; fake `cm.__enter__()` → `DialogFacade` shell returned; block →
    click recorded; `__exit__` → `cm.__exit__` resolves → `facade.__init__(FakeDialog)` +
    worker; `dialog.message` → `"Delete?"`; `dialog.accept()` → `FakeDialog.accept()` with no
    `prompt_text` kwarg; assertions: message/type/default_value read through the facade; accept
    called without kwargs; the router flag cleared after exit.
  - `test_expect_dialog_timeout_names_the_event` — setup: fake cm `__exit__` raises
    `Error('Timeout 30000ms exceeded while waiting for event "dialog"')`; input:
    `with facade.expect_dialog() as d: pass`; trace: `__exit__` → `cm.__exit__` raises `Error` →
    propagates out of the with-statement; router flag cleared in `finally`; assertions:
    `pytest.raises(Error)` — `'event "dialog"'` in `str(exc)`; not an `AssertionError`.
  - `test_expect_popup_yields_bound_page_facade` — setup: `FakePage.expect_popup()` cm resolves
    `value = FakePopupPage` (with `.context`); worker fake attached to the opener; input:
    `with facade.expect_popup() as popup: facade.get_by_role("link", name="Open docs").click()`
    then `popup.bring_to_front()`; trace: `__enter__` → fake `cm.__enter__()` → `PageFacade`
    shell; `__exit__` → resolves popup → `shell.__init__(popup, popup.context)`; worker
    inherited; `popup.bring_to_front()` → recorded; assertions: popup `isinstance PageFacade`;
    `._worker is opener._worker`; the raw popup page never equals any returned object;
    `bring_to_front` recorded.
  - `test_expect_popup_timeout_names_the_event` — setup: `FakePage.expect_popup()` returns a
    fake cm whose `__exit__` raises `Error('Timeout 30000ms exceeded while waiting for event
    "popup"')`; the opener facade carries the worker fake; input:
    `with facade.expect_popup() as popup: pass` (no opening action); trace: `__enter__`
    [marshaled] → fake cm armed → `PageFacade` shell returned; empty block; `__exit__`
    [marshaled] → `cm.__exit__(None, None, None)` raises `Error` → propagates; the shell stays
    uninitialized (the `__getattr__` guard covers any post-catch access); assertions:
    `pytest.raises(Error)` — `'event "popup"'` in `str(exc)`; not an `AssertionError`.
  - `test_new_members_marshal_to_the_driver_thread` — setup: worker fake records
    `threading.get_ident()` of each run; the test thread id known; input: representative calls —
    `goto`, `expect_url`, `frame_locator`, `pages`, dialog `accept` through a resolved capture;
    trace: each facade call → `worker.run(fn)` → fn executes on the fake worker's recorded
    ident; assertion: every recorded ident is the worker's (≠ the calling thread).
  - `test_hand_built_facade_runs_inline` (extend the existing test) — setup:
    `PageFacade(fake_page, fake_context)` with no worker; input: new members — `goto`,
    `locator`, `frame_locator`, `expect_dialog` capture; trace: `facade._worker is None` →
    `_call` executes inline in the test thread; `expect_dialog` → lazily created default
    `_DialogRouter(accept_dialogs=False)` → capture works; assertions: calls reach the fakes; no
    worker required.
- [x] **Logic tests (edge, popups + shared router)**:
  - `test_popup_capture_and_pages_agree` — setup: context with main + popup (popup opened
    through a resolved capture); input: `facade.pages` after the capture; trace: `pages` wraps
    both raw pages → two distinct facades; the captured popup facade and the listed one wrap the
    same raw page independently; assertions: 2 facades; both carry the worker and the shared
    router.
  - `test_popup_capture_claims_through_the_shared_router` — setup: `FakePage` pair (main +
    popup) sharing one `_DialogRouter(accept_dialogs=True)`; the popup carries a dialog handler
    bound through `handle_for(popup)`; a capture armed on the popup via `popup.expect_dialog()`;
    input: dispatch a `FakeDialog` to the popup's registered handler while the capture is armed;
    trace: `popup.expect_dialog().__enter__` → `router.capture_page = popup`;
    `popup_handler(FakeDialog())` → `capture_page is popup` → return (no accept, no dismiss);
    capture exit → cm resolves → `DialogFacade` initialized → step controls accept/dismiss;
    assertions: neither accept nor dismiss fired from the handler; the facade resolves the
    dialog exactly once; `router.capture_page` cleared after the block.
- [x] **Logic test (negative)**: `test_access_before_block_resolution_raises_actionable` —
  setup: capture cm armed; input: `with facade.expect_dialog() as d: d.message`; trace:
  `d.message` → `DialogFacade.__getattr__` → `AttributeError("… resolves at the end of the
  with-block …")`; assertions: `pytest.raises(AttributeError)` with the actionable text; not
  `AssertionError`.
- [x] **Debugging**: `pytest tests/driver/test_page.py -x` — fix implementation code until all
  tests pass (do NOT fix test code).
- [x] **Contract re-verification**: `expect_dialog()`/`expect_popup()` present on the surface
  (Task 5's set-equality gate now fully green); the contract Requirements hold — the capture
  claims the dialog, timeouts name the awaited event, the popup is a full `PageFacade` bound to
  the opener's driver thread; no raw `Page`/`Dialog`/`BrowserContext` crosses the boundary.
- [x] **Lint**: `ruff check prettyplay/driver/ tests/driver/` — fix formatting, apply
  decomposition if necessary.

### Task 7: `DriverSession.open_context` dialog wiring (TDD coding)

Package `prettyplay/driver`, entity `DriverSession.open_context`, declared `location`
`session.py`.

Add contract step 4: register the single dialog routing handler for every page of the context
before any step code runs. Design algorithm, verbatim:

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

Verified logic (transfer from the design trace): the wiring goes through the context page event
registered **before** `context.new_page()`, so the open_context page itself fires the event and
registers exactly once; every later popup or new tab of the context registers the same way —
one dialog handler per page, never two. Registering a `dialog` listener disables Playwright's
implicit auto-dismiss, so the handler itself must resolve every uncaptured dialog — accept on
the setting, else an explicit dismiss restoring the Playwright default observable behavior. The
router is a plain Python object shared with the facade; the facade is handed to generated code
only after the handler exists ("before any step code runs"). `accept_dialogs` is read once from
`self._config.browser` into the router. Facades never read config.

Dialog event → `router.handle` chain (the behavior the tests pin): Playwright dispatches
`dialog` on a page of the context, inside whatever marshaled facade call triggered it (the
handler body already runs in the driver thread — no marshaling inside) → `if
router.capture_page is self_page: return` (per-page comparison, so a capture armed on a *popup*
page never suppresses routing of a main-page dialog) → `elif router.accept_dialogs:
dialog.accept()` → `else: dialog.dismiss()`.

**Usages relevant to this task:**
- `conventions`: tests in `tests/driver/test_session.py`; `FakePlaywrightFactory` extension —
  `FakeContext` records `on(event, handler)` and fires the registered "page" handlers on
  `new_page()`; `FakePage` records `on(event, handler)`; ruff.
- `playwright`: the dialogs section — one routing handler per page of the context; any listener
  disables implicit auto-dismiss; the handler resolves uncaptured dialogs.
- `configuration` from Imports (`prettyplay/config/.usages/configuration.md`): the browser-group
  settings the session reads, `accept_dialogs` included — the driver only reads the switch; no
  contractual obligation crosses the boundary.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests**: in `tests/driver/test_session.py` add a check that `open_context`
  returns a `PageFacade` carrying `._router` (the shared router attachment — same pattern the
  `_worker` tests already pin). Expected to fail at this stage.
- [ ] **Code**: extend the session-test fakes — `FakeContext.on(event, handler)` records and
  fires registered `"page"` handlers on `new_page()`; `FakePage.on(event, handler)` records; a
  `FakeDialog` records accept/dismiss.
- [ ] **Code**: in `prettyplay/driver/session.py` import `_DialogRouter` from `.page` and
  restructure `open_isolated` per the algorithm — `new_context(**params)` →
  `router = _DialogRouter(self._config.browser.accept_dialogs)` →
  `context.on("page", lambda p: p.on("dialog", router.handle_for(p)))` → `context.new_page()`
  (fires the event) → after the marshaled call, `facade = PageFacade(page, context)`;
  `facade._worker = worker`; `facade._router = router`.
- [ ] **Interface verification**: `pytest tests/driver/test_session.py -x` — the existing
  session tests (launch modes, screen params, threading) stay green; the router test passes.
- [ ] **Logic tests** (in `tests/driver/test_session.py`, from the design):
  - `test_open_context_registers_dialog_routing` — setup: extended `FakePlaywrightFactory`;
    config with `accept_dialogs=False`; input: `session.open_context()`; then call the dialog
    handler registered on the page with a `FakeDialog`; trace: `open_context` → `open_isolated`
    in the driver thread → `fake_context.on("page", wiring)` recorded → `new_page()` fires the
    context "page" event → `fake_page.on("dialog", handler)` recorded → `PageFacade` returned
    with `._router`; `handler(FakeDialog())` → no capture → `accept_dialogs` False →
    `FakeDialog.dismiss()` recorded, accept not called; assertions: exactly one "page" wiring on
    the context; exactly one "dialog" registration per page (the main page included, through
    the event — never a second manual registration); dismiss called; router attached to the
    facade.
  - `test_popup_pages_route_dialogs_through_the_context_wiring` — setup: as above; a second raw
    page created through the fake context (a popup) — the context "page" wiring fires for it
    too; `accept_dialogs=True` and `accept_dialogs=False` variants; input: call the dialog
    handler registered on the popup page with a `FakeDialog`, per variant; trace: popup page
    creation → context "page" event → `popup.on("dialog", router.handle_for(popup))`;
    `handler(FakeDialog())` → no capture on the popup → `accept_dialogs` True → accept; False →
    dismiss; assertions: the popup carries exactly one dialog handler; the setting routes it;
    the main-page handler is a different closure bound to the main page.
  - `test_dialog_router_accepts_when_setting_on` — setup: as above with
    `BrowserConfig(accept_dialogs=True)`; input: `handler(FakeDialog())`; trace: →
    `accept_dialogs` True → `dialog.accept()`; assertions: accept called, dismiss not called.
  - `test_dialog_router_skips_only_for_a_capture_on_the_same_page` — setup: as above; a second
    raw page (popup); set `router.capture_page = popup_page` and `router.capture_page =
    main_page` in turn; input: `handler(FakeDialog())` under both states; trace:
    `capture_page` is popup (≠ handler page) → routed by setting (accept/dismiss);
    `capture_page` is main (== handler page) → neither accept nor dismiss; assertions: first
    case resolves the dialog; second case no calls.
- [ ] **Debugging**: `pytest tests/driver/ -x` — fix implementation code until all tests pass
  (do NOT fix test code).
- [ ] **Contract re-verification**: the CODEMANIFEST `open_context` Algorithm steps 1–5 match
  the implementation order verbatim; the Constraints bullet holds (facades stay untouched by the
  screen modes — they receive the router, they never read config); the existing launch/connect/
  screen behavior is unchanged.
- [ ] **Lint**: `ruff check prettyplay/driver/ tests/driver/` — fix formatting, apply
  decomposition if necessary.

### Task 8: `SYSTEM_PROMPT` and `PAGE_API_SURFACE` — the generation request surface (TDD coding)

Package `prettyplay/engine`, entity `StepGenerator` (constants only), declared `location`
`generator.py`.

No signature or logic change — the module constants change to the new contract texts. Design
algorithm, verbatim:

```
1. SYSTEM_PROMPT ← the engine CODEMANIFEST `system_prompt` text verbatim
2. PAGE_API_SURFACE ← the facade.md four tables verbatim as aligned `call — purpose` lines
   (page 33 rows of facade.md, 32 listed — page.close() excluded with the standing comment;
   dialog 5, frame 3, element 19; page.url/page.pages properties included)
3. Update the PAGE_API_SURFACE comment: parity wording replaces backward compatibility
```

The engine CODEMANIFEST `system_prompt` usage text (source of `SYSTEM_PROMPT`, copy verbatim —
read it from `prettyplay/engine/CODEMANIFEST` at implementation time) now carries: the
"Playwright-mirroring page API" rule, "Locating by role and accessible name is preferred; by
visible text next; by label or placeholder for form fields", "get_by_test_id and
locator(selector) exist for elements without accessible names", the dialog capture rule
(`with page.expect_dialog() as dialog:`), the popup rule (`with page.expect_popup() as
popup:`; `bring_to_front()`), the iframe rule (`page.frame_locator(selector)`). The retired
wording ("Attribute, CSS and XPath locating…") is gone.

`PAGE_API_SURFACE` mirrors `prettyplay/driver/.usages/facade.md` verbatim: the four surface
tables (page/dialog/frame/element) as aligned `call — purpose` lines; `page.close()` stays
excluded (runtime method of PrettyPlay, standing comment preserved, parity wording); the two
properties (`page.url`, `page.pages`) listed. Requirement: every generation request carries the
exact page API surface taken from `facade` — the listing and the practice change together; a
mechanical guard test pins that every listed name resolves on the facade classes and every
facade.md row appears in the listing.

**Usages relevant to this task:**
- `conventions`: tests in `tests/engine/test_generator.py`; ruff.
- `facade` from Imports (`prettyplay/driver/.usages/facade.md`): the single source of the page
  API surface — read the four tables from this file; `PAGE_API_SURFACE` mirrors it verbatim.
- `system_prompt` (inline usage of the engine CODEMANIFEST): the verbatim source text.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests**: in `tests/engine/test_generator.py` add
  `test_page_api_surface_members_exist_on_the_facades` — setup: import `PAGE_API_SURFACE`,
  `PageFacade`, `LocatorFacade`, `DialogFacade`, `FrameFacade`; input: parse each line: prefix
  (`page.`/`element.`/`dialog.`/`frame.`) + member name before `(` or end; trace: for each line,
  `owner = {page: PageFacade, element: LocatorFacade, dialog: DialogFacade, frame:
  FrameFacade}[prefix]`; `hasattr(owner, member)` → True; also `"page.close" not in
  PAGE_API_SURFACE`; `"open("` / `"find_by"` not in it; assertions: every listed member resolves
  on its facade class; retired names absent. Expected to fail at this stage.
- [ ] **Code**: replace `SYSTEM_PROMPT` in `prettyplay/engine/generator.py` with the engine
  CODEMANIFEST `system_prompt` text **verbatim** — copy from the manifest's `Usages` block; no
  paraphrasing.
- [ ] **Code**: replace `PAGE_API_SURFACE` with the facade.md four tables verbatim as aligned
  `call — purpose` lines — 32 page rows (`page.close()` excluded), 5 dialog rows, 3 frame rows,
  19 element rows; keep the standing exclusion comment, reworded to the parity principle.
- [ ] **Code**: update the constant's docstring/comment: parity wording replaces the
  backward-compatibility wording.
- [ ] **Interface verification**: `pytest tests/engine/test_generator.py -x -k "surface or
  prompt"` — the contract test passes; the provider request still receives
  `prompt=SYSTEM_PROMPT` and `page_api=PAGE_API_SURFACE` unchanged in shape.
- [ ] **Logic tests** (in `tests/engine/test_generator.py`, from the design):
  - `test_system_prompt_carries_the_new_rules` — setup: import `SYSTEM_PROMPT`; input: none
    (constant inspection); trace: contains "the Playwright-mirroring page API", the
    label-or-placeholder rule, the get_by_test_id/locator rule, the dialog capture rule, the
    popup rule, the iframe rule; lacks "find_by", "Attribute, CSS and XPath locating";
    assertions: substring checks for each new rule line; absence of the retired wording.
  - `test_page_api_surface_mirrors_the_facade_practice` (update the existing test) — setup:
    read `prettyplay/driver/.usages/facade.md`; input: the four surface tables; trace: for each
    facade.md table row call `owner.member(...)` **except `page.close()`** (the runtime method
    of PrettyPlay — excluded by the standing comment; the mirror test skips the close row — 32
    listed page rows; the exclusion itself is pinned by the members-exist test alone): strip
    args → `f"{prefix}.{member}"` present in `PAGE_API_SURFACE`; assertions: all rows present
    (page 32 listed + close excluded, dialog 5, frame 3 collapsed to its family rows, element
    19).
  - Update the existing `TestPromptConstants` assertions and the fixture strings of the file
    (`WORKING_CODE`/`BROKEN_CODE` and any `page.open`/`find_by_*` literals) to the mirror names
    — payloads only, no behavioral change; the file's fake surfaces rename with them so the
    renamed candidates still execute: `FakePage.open` → `goto`, `FakePage.find_by_text` →
    `get_by_text`, `FailingPage`/`TimeoutPage`/`PlaywrightTimeoutPage` `find_by_role` →
    `get_by_role`, and the recorded call names inside `calls` — behavior identical (failures
    and recorded shapes unchanged).
- [ ] **Debugging**: `pytest tests/engine/ -x` — fix implementation code until all tests pass
  (do NOT fix test code).
- [ ] **Contract re-verification**: the annotation "Use `system_prompt` as the system prompt of
  every code generation request" holds — the constant equals the manifest text verbatim; the
  requirement "Every generation request carries the exact page API surface taken from `facade`
  from Imports" holds; no engine signature changed.
- [ ] **Lint**: `ruff check prettyplay/engine/ tests/engine/` — fix formatting if necessary.

### Task 9: Integration tests — cross-package surface consistency and the retired-name sweep

Cross-package scope: the whole library cycle works against the new surface — the fixed form is
consistent end to end, and no test fixture advertises a retired name.

Files: `tests/test_integration.py`, `tests/test_executor.py`, `tests/test_scenario.py`,
`tests/test_runtime.py` (verified — no retired page-facade names; sweep is a no-op, kept for
cross-package consistency), `tests/llm/test_request.py`,
`tests/llm/test_provider.py`, `tests/llm/test_openai_provider.py`,
`tests/llm/test_anthropic_provider.py`, `tests/cache/test_models.py`,
`tests/cache/test_store.py` (opaque fixture strings carrying retired names — sweep only);
`tests/engine/test_execution.py`, `tests/engine/test_classification.py`,
`tests/engine/test_healer.py` (engine-cell fixtures carrying retired names — sweep only).

Design scenario (verbatim): FakePage surface renamed: `open`→`goto`,
`find_by_role/label/text`→`get_by_*` (+ the `_lookup` recorder keys); cached-code literals
`page.open(...)` → `page.goto(...)`. Plus the opaque-string sweep in the llm/cache tests:
`page.open(…)` → `page.goto(…)` in `FENCED_CODE`/`WORKING_CODE`/`STEP_CODE` fixtures,
`page.find_by_role(role, name)` → `page.get_by_role(role, name)` in page-api fixtures,
`page_api="page.open(...)"` → `"page.goto(...)"` — payloads only, no behavioral change. The
existing scenario corpus (generation success, failed-check classification, healing rot, strict
mode, screenshots) keeps its assertions — recorded calls now under mirror names.

**Usages relevant to this task:**
- `conventions`: integration tests live at the repo test root; fakes over real browsers; ruff.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] Create/extend the integration scenarios in `tests/test_integration.py`:
- [ ] Test cross-entity interaction: `test_retired_members_fail_loudly_on_cached_steps` —
  setup: existing integration harness; cached code `"def step(page) -> None:\n
  page.find_by_role('button', name='Войти').click()\n"`; input: step execution replays the
  cached code; trace: `run_step_code(cached, page)` → `page.find_by_role` → `AttributeError` →
  executor strict/normal path → classification (rot) → regeneration with the new surface;
  assertions: the failure surfaces by kind (`IncurableStepError`/healing path as configured);
  the regenerated code contains no retired name. (The accepted break — cached steps heal lazily
  through the existing loop.)
- [ ] Test cross-entity interaction: rename the FakePage surface and cached-code literals in
  `tests/test_integration.py`, `tests/test_executor.py`, `tests/test_scenario.py`,
  `tests/test_runtime.py` — `open`→`goto`, `find_by_role/label/text`→`get_by_*` (+ the
  `_lookup` recorder keys); existing assertions hold (recorded calls now under mirror names);
  and in `tests/engine/test_execution.py`, `tests/engine/test_classification.py`,
  `tests/engine/test_healer.py` — payload strings (`page.open(…)` → `page.goto(…)`,
  `page.find_by_role/text(…)` → `page.get_by_role/text(…)`) and the fake method surfaces
  (`FakePage.find_by_*` → `get_by_*`, recorder keys) — payloads and fake surface only, no
  behavioral change (the engine fakes are their own boundary; only the advertised names move).
- [ ] Test edge case (opaque-string sweep): `tests/llm/test_request.py`,
  `tests/llm/test_provider.py`, `tests/llm/test_openai_provider.py`,
  `tests/llm/test_anthropic_provider.py`, `tests/cache/test_models.py`,
  `tests/cache/test_store.py` — `page.open(…)` → `page.goto(…)` in
  `FENCED_CODE`/`WORKING_CODE`/`STEP_CODE` fixtures, `page.find_by_role(role, name)` →
  `page.get_by_role(role, name)` in page-api fixtures, `page_api="page.open(...)"` →
  `"page.goto(...)"` — payloads only, no behavioral change.
- [ ] Run validation: `pytest tests/ -x` — the whole suite is green end to end; then
  `grep -rn "find_by\|page\.open(" tests/ prettyplay/` returns no hits outside the
  retired-surface test itself (`test_retired_surface_is_gone`,
  `test_retired_members_fail_loudly_on_cached_steps` and the SYSTEM_PROMPT absence checks, which
  reference the retired names as data).

### Task 10: Documentation ride-along — the public docs to the new surface (infrastructure)

Scope: the five existing docs pages move to the new surface. `mkdocs.yml` needs no navigation
change (existing pages only). Design algorithm, verbatim:

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

This is a documentation-only task: no code, no tests beyond the final gates.

**Usages relevant to this task:**
- `facade` from Imports (`prettyplay/driver/.usages/facade.md`): the single source the reference
  page rebuilds from — four surface tables + examples.
- `configuration` (`prettyplay/config/.usages/configuration.md`): the Dialogs subsection and the
  browser-group/env tables mirror this cell practice.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] Rebuild `docs/reference/driver-facade.md` from `prettyplay/driver/.usages/facade.md`:
  parity intro, the four surface tables (page/dialog/frame/element), the
  dialogs/popups/iframes/interactions/scroll example blocks, the updated Rules section.
- [ ] Update `docs/guides/writing-steps.md`: rename surface examples to `goto`/`get_by_*`; add
  dialog, popup, iframe snippets (mirror the facade.md examples).
- [ ] Update `docs/configuration.md`: the browser-group table and env table gain
  `accept_dialogs`; add the Dialogs subsection (mirrors `prettyplay/config/.usages/
  configuration.md`).
- [ ] Update `docs/getting-started.md` and `docs/index.md`: replace retired names where present.
- [ ] Verify facade accessibility: `python -c "import mkdocs"`-free static check — grep the docs
  for retired names: `grep -rn "find_by\|page\.open(" docs/` returns no hits.
- [ ] Lint: `ruff check prettyplay/ tests/` — still clean (no code changed in this task).

---

## Validation Commands

- `pytest tests/ -x`: Run all tests — the whole suite (config, driver, engine, integration, llm,
  cache, reporting, failures) green end to end.
- `ruff check prettyplay/ tests/`: Lint check — formatting and decomposition across the package
  and the tests.
- `goga lint`: Cells lint — 8 cells, 0 errors (the CODEMANIFEST layer stays untouched).
- `python -c "from prettyplay.driver import DialogFacade, DriverSession, FrameFacade, LocatorFacade, PageFacade; from prettyplay.config import BrowserConfig, load_config"`:
  Facade accessibility — every facade obligation importable.
- `grep -rn "find_by\|page\.open(" prettyplay/ tests/ docs/` (excluding the retired-name test
  bodies and absence assertions): no retired surface remains outside the tests that pin its
  absence.

---

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location`
  (`config/models.py`, `config/loader.py`, `driver/page.py`, `driver/session.py`,
  `engine/generator.py`)
- [ ] Every contract entity is accessible from the facade (`prettyplay.driver` exports
  `DialogFacade` and `FrameFacade`; config/engine facades unchanged)
- [ ] Properties and methods match the declared API (the set-equality surface test gates the
  page level; signature tests gate the rest)
- [ ] Descriptions are reflected in behavior (routing claim/accept/dismiss chain, capture
  resolve-at-exit, contains-semantics `expect_title`, empty-name role matching, verbatim
  selector pass-through, glob URL pass-through)
- [ ] Contract dependencies are met (`Config` reaches the driver; `facade` reaches the engine)
- [ ] Re-exports are accessible from the facade
- [ ] Every coding task followed the TDD workflow (contract tests → code → verification →
  logic tests → debugging → re-verification → lint)
- [ ] Contract tests and logic tests cover facade, API, and behavior within each coding task
- [ ] Integration tests exist where cross-entity scenarios require them (Task 9)
- [ ] No package boundary was expanded (no new cells, no new dependencies, no raw Playwright
  object exposed)
- [ ] `CODEMANIFEST` files were not modified (contract is read-only)
- [ ] All validation commands pass
- [ ] Every Usages entry is mentioned in at least one task (`conventions`, `pydantic`,
  `playwright`, `system_prompt`; imported: `configuration`, `facade`; `classification` noted as
  unchanged — no task required)
