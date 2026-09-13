# Architecture Plan — standard-playwright-step-api

## Topic

**standard-playwright-step-api** — Open the standard Playwright sync API to generated step code: the worker-thread execution boundary, the facade demotion, the cheat-sheet carrier, the author escape hatch, the surface removal.

Plan path: `.goga/history/2026/add-expect-count/arch.md` (source task: `task.md`; ADR: `adr.md`, accepted 2026-09-13).

Design decisions locked through the brainstorm gates:

- q1=A — `LocatorFacade`, `DialogFacade`, `FrameFacade` are deleted from the driver contract.
- q2=A — step execution is a contract member of the demoted `PageFacade` (`run`); `run_step_code(code, PageFacade)` keeps its signature; the polling cell is untouched.
- q7=A — the dialog router is the resolver of last resort: an in-step capture wins, every dialog resolves exactly once.
- q9=B — the cheat-sheet lives in `.goga/usages/prompts/cheatsheet.md` and rides every generation request through the renamed `cheat_sheet` slot (block order: CHEAT SHEET, USER INSTRUCTIONS, CODE, ERROR, RECOMMENDATION, USER GUIDANCE, HISTORY).
- q12 — the demoted `PageFacade` stays as the internal runtime handle; the author escape hatch is `PrettyPlay.run_on_page(action)` executing the author callable wholly inside the worker thread with the genuine sync `Page` (no proxy, no getattr passthrough).

## Implementation Order

1. **Project usages** (no cell dependencies; referenced by the manifests below): `prompts/cheatsheet.md` (create), `prompts/generation.md` (rewrite), `cooks/playwright.md` (update).
2. **`prettyplay/driver`** (modified) — depends only on `prettyplay/config`; the worker boundary (`PageFacade.run`) and the internal handle must exist before engine/steering/root reference them.
3. **`prettyplay/llm`** (modified) — depends on `prettyplay/config`, `prettyplay/failures`; the `cheat_sheet` slot must exist before engine and steering pass it.
4. **`prettyplay/engine`** (modified) — depends on `prettyplay/driver` (`PageFacade`), `prettyplay/engine/polling` (untouched), `prettyplay/llm`, `prettyplay/cache`, `prettyplay/config`, `prettyplay/failures`, `prettyplay/reporting`.
5. **`prettyplay/engine/steering`** (modified) — depends on `prettyplay/engine` (`run_step_code`, `check_step_compliance`), `prettyplay/driver`, `prettyplay/llm`, `prettyplay/cache`, `prettyplay/config`, `prettyplay/failures`, `prettyplay/reporting`.
6. **`prettyplay`** (root, modified) — depends on all of the above; the facade lands last.

`prettyplay/engine/polling`, `prettyplay/config`, `prettyplay/cache`, `prettyplay/failures`, `prettyplay/reporting` are **not modified**.

## Artifacts

Series constraint (one coherent breaking change): the surface constant `PAGE_API_SURFACE` with both frozen copies (engine, steering), the parity/mirror tests and the doc mirror are removed in this same series — no staged deprecation, no leftovers. The step cache is disposable: no compatibility shims, examples regenerate.

---

### Artifact 1 — `.goga/usages/prompts/cheatsheet.md` (CREATE)

```md
# Playwright cheat sheet

The compact standard Playwright sync API reference carried by every step-code generation and regeneration request
of prettyplay — referenced by the engine and steering cells as the `cheat_sheet` practice; rendered by the provider
implementations as the leading CHEAT SHEET block of the user content. Guidance, not an allowlist: everything
standard stays allowed — the error-driven regeneration loop is the second line of defense against hallucinated
calls. Target audience: the generation model — a model that knows Playwright weakly writes a correct step from
this reference alone.

## Locator factories

    page.get_by_role("button", name="Sign in")
    page.get_by_label("Username")
    page.get_by_text("Welcome back")
    page.get_by_placeholder("Search")
    page.get_by_alt_text("Logo")
    page.get_by_title("Close")
    page.get_by_test_id("submit")
    page.locator("css selector | //xpath | [data-qa=row]")

## Narrowing

    locator.first / locator.last / locator.nth(2)
    locator.filter(has_text="Product X")
    locator.and_(other) / locator.or_(other)

## Actions

    .click() / .dblclick() / .click(button="right")
    .fill("text") / .clear() / .press("Enter") / .press("Control+A")
    .check() / .uncheck() / .hover() / .select_option("v")
    .drag_to(target) / .set_input_files("path.png")

## Navigation and waits

    page.goto(url) / page.go_back() / page.go_forward() / page.reload()
    page.wait_for_url("**/dashboard") / page.wait_for_load_state("networkidle")

## Waiting assertions — expect chains

    from playwright.sync_api import expect

    expect(locator).to_be_visible() / to_be_hidden()
    expect(locator).to_be_enabled() / to_be_checked()
    expect(locator).to_have_text("...") / to_contain_text("...")
    expect(locator).to_have_value("v") / to_have_attribute("href", "/docs")
    expect(page).to_have_url("**/dashboard") / to_have_title("Dashboard")

## Count forms — "the page shows a list of X"

    videos = page.get_by_role("listitem")
    expect(videos.first).to_be_visible()
    assert videos.count() > 1

An exact count is the rarer need: `expect(videos).to_have_count(3)`.

## Immediate reads with plain asserts

    assert locator.count() >= 1
    assert "Dashboard" in page.title()

## Dialogs

    with page.expect_event("dialog") as info:
        page.get_by_role("button", name="Delete").click()
    dialog = info.value
    dialog.type / dialog.message / dialog.default_value
    dialog.accept() / dialog.dismiss() / dialog.accept("the answer")

## Popups and new tabs

    with page.expect_popup() as popup_info:
        page.get_by_role("link", name="Open docs").click()
    popup = popup_info.value
    popup.bring_to_front()

## Frames

    frame = page.frame_locator("#checkout")
    frame.get_by_role("button", name="Pay").click()

## Scrolling

    locator.scroll_into_view_if_needed()
    page.mouse.wheel(0, 600)
```

### Artifact 2 — `.goga/usages/prompts/generation.md` (REWRITE)

```md
# Generation system prompt

The system prompt of every step-code generation and regeneration request of prettyplay — referenced by the engine
and steering cells as the `system_prompt` practice. Content is the single source; both referencing cells render it
verbatim as the system message.

---

You generate executable Python code for one step of a web UI test.

Input you receive:
- STEP: the step sentence in a natural language
- PREVIOUS STEPS: the sentences of the previous steps of the test, in order
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- SCREENSHOT: an image of the page, when attached
- CHEAT SHEET: a compact reference of useful Playwright sync API idioms — guidance, not an allowlist; everything standard stays allowed
- USER INSTRUCTIONS: the project's binding code style guidance, when configured
- CODE: the existing step code that failed (regeneration requests only)
- ERROR: the failure description of the existing code (regeneration requests only)
- RECOMMENDATION: the diagnosis of the classification that preceded this regeneration, when present
- USER GUIDANCE: the engineer guidance message of the interactive steering, when present
- HISTORY: the accumulated steering turns, when present

Output exactly one Python code block with one function of the fixed form:

def step(page) -> None:
    ...

Rules:
- The function receives exactly one argument: the page — the genuine Playwright sync Page; the whole step runs inside the driver worker thread
- Import only from playwright.sync_api — no other imports, no other libraries
- Work through the standard Playwright sync API: locator factories, actions, waits, expect chains, plain asserts on immediate reads — everything standard is allowed; the CHEAT SHEET is guidance, never a boundary
- Assertions: for an assertion sentence end with a check — a waiting expect(...) chain for dynamic content, or an immediate read with a plain Python assert (assert locator.count() > 1)
- No fixed delays, no sleeps, no wait_for_timeout — locators and expect chains auto-wait
- The runtime owns the page lifecycle: never call page.close() or context.close()
- No stateful actions that outlive the step on the page shared by the whole test: page.route, page.clock, add_init_script, tracing, HAR, CDP — excluded from generated code; a cached step would poison every later step far from the cause
- Dialogs: capture with the stock means — with page.expect_event("dialog") as info: — perform the triggering action inside the block, read info.value.type, info.value.message, info.value.default_value, then info.value.accept() or info.value.dismiss()
- Popups and new tabs: capture with with page.expect_popup() as popup_info: — trigger the opening action inside the block, work through popup_info.value; page.bring_to_front() raises a page above the others
- Content inside an iframe goes through page.frame_locator(selector) — locate elements within the returned scope; nested frames chain
- Scrolling: locator.scroll_into_view_if_needed() and page.mouse.wheel(dx, dy) are the standard means
- RECOMMENDATION and USER GUIDANCE carry the diagnosis and the engineer's intent — follow them when they conflict with your first instinct
- USER INSTRUCTIONS are binding for everything below the safety core of these Rules: follow them when configured; silently ignoring an instruction is a violation
- The safety core of these Rules always outranks the instructions: the fixed function form, the import rule, the lifecycle rule, the stateful-action exclusions, no fixed delays. An instruction conflicting with a Rule or demanding a stateful action is unfollowable: never implement it silently — raise in the step code with the message "instruction conflicts with rule Y" naming the conflict, so the failure surfaces loudly
- Prefer-type instructions are conditional by their own wording: follow them when the page offers the option — best-effort with a graceful fallback is compliance
- The step must complete exactly what STEP says — nothing more, nothing less
- Output only the code block, no explanations
```

### Artifact 3 — `.goga/usages/cooks/playwright.md` (UPDATE)

Diff (everything not listed stays as in the current document):

- ADD the leading section right after the intro paragraph (before "Lifecycle"):
  - Title: `## Generated step code — the standard API contour`
  - Content: the whole step executes inside the driver worker thread as one unit; the step function receives the genuine sync `Page` — never a wrapper; imports restricted to `from playwright.sync_api import ...` (a prompt rule, no hard gate); safety core — the fixed form `def step(page) -> None:`, no fixed delays or sleeps, no `page.close()`/`context.close()` (the runtime owns the page lifecycle); stateful actions excluded from generated code (`page.route`, `page.clock`, `add_init_script`, tracing, HAR, CDP) — the author performs them explicitly through the escape hatch; waiting `expect(...)` chains advised for dynamic content, immediate reads with plain Python asserts allowed (`assert locator.count() > 1`); scrolling and dialogs through stock means; everything standard stays allowed — the cheat-sheet carried by every request is guidance, not an allowlist; the error-driven regeneration loop is the second line of defense.
- Interactions section, rules: DROP the rule "raw input devices (page.keyboard, page.mouse) are outside the facade surface — keys go through element press"; REPLACE with "raw input devices (`page.keyboard`, `page.mouse`) are standard Playwright — reachable in generated code; element press stays the default guidance". Keep the `press`/`drag_to`/`set_input_files` rules as-is.
- Dialogs section: REPLACE the facade-capture wording with the stock means — the code example becomes `with page.expect_event("dialog") as info: ... ; dialog = info.value; dialog.accept() / dialog.dismiss() / dialog.accept("the answer")`; the routing-handler paragraph is rewritten to the resolver-of-last-resort semantics: the per-page routing handler stays runtime behavior; an in-step stock capture wins — the handler never touches a dialog a capture handled; every unclaimed dialog is resolved exactly once — accept when the setting is on, an explicit dismiss when off; DROP the sentences "An armed event waiter (page.expect_event("dialog")) claims the dialog on its page first; the Python client ships no expect_dialog" and "Scenario-level dialog verification constructs belong to the facade contract design, not to this usage".
- Popups section, rules: DROP the "facade-wrapped pages" phrasing — REPLACE with "the opened page is a genuine Page, usable directly; `bring_to_front()` activates a page; pages of one context share the browser process".
- Frames section: DROP "no raw frame objects cross the facade boundary" from the intro sentence; keep the example and both rules.
- Rules footer: SYNC with the new contour — add "Generated step code uses the genuine sync Page inside the worker thread; the import rule and the stateful exclusions are prompt rules; the runtime owns the page lifecycle"; keep the existing five rules as-is.

### Artifact 4 — `prettyplay/driver/CODEMANIFEST` (MODIFY — full new state)

Diff summary: DELETE the type declarations `LocatorFacade`, `DialogFacade`, `FrameFacade` entirely; DELETE the `properties` block of `PageFacade` (`url`, `pages`); REPLACE the `PageFacade` method set with the four plumbing members (`run`, `aria_snapshot`, `screenshot`, `close`); REWRITE the parity/exclusion global annotations into the standard-API contour; REWRITE the dialog-router wiring as resolver-of-last-resort; UPDATE `is_pollable_failure` step 1 wording; UPDATE the footer Description. Full new state:

```yaml
Imports:
  - Types:
      - Config
    Usages:
      - configuration
    From: prettyplay/config

Usages:
  conventions: .goga/usages/conventions.md
  playwright: .goga/usages/cooks/playwright.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `playwright` for the sync API lifecycle, locators, auto-wait, the accessibility snapshot, browser channels, remote connects, the screen modes, the dialog event model and the error kinds.
  Use `configuration` from Imports for the browser-group settings the session reads, accept_dialogs included.

  The driver is Playwright sync-only: the async API is out of scope.
  The whole Playwright session — start, browser, contexts, pages — lives in one dedicated driver thread owned by the library: the sync API parks its private event loop on its starting thread, so the thread executing the steps never holds a running asyncio loop (interactive hosts such as IPython and Jupyter keep working between steps).
  Driver-thread work is strictly sequential: one unit runs at a time; concurrent driving is out of scope.
  One browser process per test: the session is owned by the test's runtime — no state is shared between tests through the library.
  The start mode branches on the endpoint setting of the browser group of `Config`: empty — local launch with headless and the channel for chrome/msedge; set — connect over the Playwright ws endpoint: headless is ignored, channels do not apply, the name setting selects the engine (see `playwright`).
  The screen setting of the browser group resolves at context creation (see `playwright`): the empty value keeps the Playwright default; WxH and device descriptors apply in every launch mode; fullscreen follows the window on a local headed launch and pins to a fixed 1920x1080 viewport where no window exists. Device names resolve against the devices registry of the running Playwright — the package never hard-codes a device list.
  All waits go through locators and expectations; fixed delays (time.sleep and similar) are forbidden.
  Generated step code runs against the genuine Playwright sync API: the driver manages no page-API surface — the step function receives the genuine sync Page inside the driver worker thread (see `playwright`).
  The page handle of this cell is internal runtime plumbing — snapshot, screenshot, close and the worker-thread run primitive, the only crossing point of the worker boundary; no proxying or delegation of page members exists.
  The dialog routing handler is the resolver of last resort: a dialog handled by an in-step capture is never touched by the router; every unclaimed dialog is resolved exactly once — accept when accept_dialogs of the browser group is true, else an explicit dismiss (see `configuration` from Imports and `playwright`).
  The driver knows its own error surface: the fixed pollable map lives in this cell — the single recognition point deciding which failed step-code exceptions a settle window may absorb (see `playwright`).

---

"DriverSession(config: Config)":
  location: session.py
  annotations: |
    Lifecycle owner of the Playwright sync driver and the browser process of one test.

    `config`: project settings; the browser group carries the engine — the name of the {chromium, firefox, webkit, chrome, msedge} set, chrome and msedge launch the locally installed browser through the channel mechanism — the screen size mode, the headless window visibility of a local launch, the endpoint switching the start to a remote connect and the dialog auto-accept switch (see `playwright` and `configuration` from Imports).

    Requirements:
    - The Playwright session lives in a dedicated driver thread owned by the session: every Playwright-touching operation of this type runs there, and the calling thread never holds a running asyncio loop after any call
  methods:
    "open_context() -> page: PageFacade": |
      Open a fresh isolated context with one page of this test's browser.

      Algorithm:
      1. Start lazily on the first call: constructing the session starts nothing — start the dedicated driver thread, then start Playwright inside it; an empty endpoint — launch the selected engine locally with headless from the browser group and the channel for the chrome/msedge values; a set endpoint — connect over the Playwright ws endpoint of the selected engine: headless is ignored and channels do not apply; a failed launch or connect stops the started driver and closes the thread, so a retry begins from a clean state
      2. Resolve the screen setting of the browser group into the context parameters, by precedence: the literal fullscreen value — a local headed launch (headless false, endpoint empty) opens the context without a fixed viewport, so the viewport follows the window: the chromium-family engines (chromium, chrome, msedge) start the window maximized through the --start-maximized launch argument; firefox and webkit keep their plain launch — the window opens at its default size (see `playwright`); headless or a remote connect — a fixed 1920x1080 viewport, no window exists there; a WxH-shaped value — the viewport dictionary of the parsed width and height, in every launch mode; any other value — a device name: present in the devices registry of the running Playwright — the full descriptor applies to the context (viewport, user_agent, touch, is_mobile, device_scale_factor) in every launch mode; absent — a loud actionable error suggesting close device names from the registry
      3. Create a fresh isolated browser context and its page inside the driver thread with the resolved parameters (see `playwright`)
      4. Register the single dialog routing handler for every page of the context before any step code runs — the open_context page included: the wiring goes through the context page event inside the same driver-thread call (every new page of the context fires it, so each page registers exactly once, never twice). The handler is the resolver of last resort: a dialog handled by an in-step stock capture — page.expect_event("dialog") and friends of the genuine API — is never touched; an unclaimed dialog is resolved exactly once — accept when accept_dialogs of the browser group (see `configuration` from Imports) is true, else an explicit dismiss restoring the Playwright dismiss default (registering a dialog listener disables the implicit auto-dismiss); the resolution is deferred to the end of the run unit of `PageFacade` — the step wins inside the unit, the router resolves the leftovers at the unit boundary, deterministically inside the driver thread
      5. Wrap the page into `PageFacade` — the internal runtime plumbing handle — and return it

      Requirements:
      - Each result is isolated from every other context
      - A channel launch without the installed browser fails loudly with an actionable message naming the missing browser
      - A failed connect fails loudly with an actionable message naming the endpoint
      - WxH and device descriptors apply in every launch mode: local headed, local headless, remote connect
      - fullscreen is not pixel-identical across environments — a headed run follows the actual screen, headless and remote runs are pinned to 1920x1080
      - Every dialog is resolved exactly once across the router and the in-step captures — double-handling never occurs
    "close()": |
      Stop the browser, the Playwright driver and the driver thread; safe to call when nothing was started.

"PageFacade(page: Page, context: BrowserContext)":
  location: page.py
  annotations: |
    The internal runtime plumbing handle of a single test page — not the API of generated step code: the step function receives the genuine sync Page inside the driver worker thread through the run primitive of this handle.
    Wraps one isolated browser context created by `DriverSession`.

    `page`: the wrapped Playwright page object; never exposed to the calling thread.
    `context`: the isolated browser context owning the page; the boundary the close method closes.

    Requirements:
    - Every operation runs in the driver thread of the owning session; the calling thread never adopts the Playwright event loop

    Constraints:
    - No member proxies, delegates or re-exports page capabilities — the handle is plumbing, not a managed surface
  methods:
    "run(action: Callable[[Page], T]) -> result: T": |
      Execute the callable wholly inside the driver worker thread and return its outcome — the only crossing point of the worker boundary.

      `action`: the callable to execute; receives the genuine sync Page of this test.
      `result`: the outcome of `action` as-is.

      Algorithm:
      1. Marshal `action` into the driver worker thread as one unit
      2. Call it with the genuine sync Page
      3. Return the outcome as-is; an exception raised inside `action` propagates to the caller untouched — an AssertionError of a step reaches failure classification unchanged
      4. After `action` completes or raises — the resolver-of-last-resort pass: resolve every dialog of this page left unclaimed by in-step captures — accept when accept_dialogs of the browser group is true, else an explicit dismiss

      Requirements:
      - The calling thread never adopts the Playwright event loop
      - The callable runs sequentially with every other unit of the session
      - A dialog left unclaimed mid-step blocks the page until the unit ends — the deferred resolution closes it at the run boundary; an in-step capture is the remedy when the step must control the dialog

      Constraints:
      - Playwright objects never cross back to the calling thread through `result` — the callable returns plain data
    "aria_snapshot() -> snapshot: str": |
      The structured accessibility-tree representation of the page — the primary machine-readable page state (see `playwright`).
    "screenshot() -> image: bytes": |
      A full-page PNG image of the current state.
    "close()": |
      Close the isolated context of this page; the browser process keeps running.

"is_pollable_failure(exc: Exception) -> pollable: bool":
  location: errors.py
  annotations: |
    The fixed pollable map of the step-code error surface: decide whether a failed step-code
    exception is a transient page state a settle window may absorb — recognition only,
    no LLM, no settings.

    `exc`: the exception raised by the failed step code.
    `pollable`: True — the kind is transient (the settle window may re-execute the same
    code); False — deterministic or unknown (straight to classification).

    Algorithm:
    1. A failed check — an AssertionError that is not the locator-ambiguity violation of
    step 3 — is pollable (see `playwright`): the check executed and did not hold — a failed
    expect(...) chain and a plain Python assert on an immediate read alike; the state may
    catch up
    2. Recognize the driver kinds by the exception type and the message patterns
    (see `playwright`): timeout — Timeout NNNms exceeded; element state — not visible,
    not enabled, outside of the viewport, detached or stale; navigation and context —
    Execution context was destroyed, Target closed, navigation interrupted mid-flight —
    pollable
    3. Locator ambiguity — the strict mode violation, locator resolved to N elements — is
    not pollable: the elements are there; waiting will not collapse them to one
    4. A Python-level error of the step code — syntax, names, types — is not a driver
    error at all: not pollable
    5. An unrecognized kind is not pollable — the conservative default goes to classification

    Requirements:
    - Pure function: no state, no I/O, deterministic on the exception alone
    - The map is fixed in code: never configured, never asked of an LLM

---

Author: Goga
CreatedAt: 10/09/26
Description: |
  The Playwright sync driver of prettyplay: the per-test session with local launches, remote ws connects, the screen modes and the dialog routing — and the internal runtime plumbing handle of the test page (the worker-thread run primitive, the accessibility snapshot, the screenshot, the context close); generated step code runs against the genuine sync Page inside the worker thread.
```

### Artifact 5 — `prettyplay/driver/.usages/` (cell usage files)

- **DELETE** `prettyplay/driver/.usages/facade.md` — the 65-row surface mirror dies with the surface.
- **CREATE** `prettyplay/driver/.usages/plumbing.md`:

```md
# Driver plumbing — the internal page handle

Domain: the worker-thread boundary and the internal page handle of prettyplay. Audience: implementers of the engine,
steering and root cells — the code that executes step code, collects page state and offers the author escape hatch.
Not an API for generated step code: generated code receives the genuine Playwright sync Page inside the worker thread.

## The worker boundary

The whole Playwright session lives in one dedicated driver thread. The only crossing point is the run primitive of the
page handle: a callable executes wholly inside the worker thread and receives the genuine sync Page there.

    result = page.run(action)  # action(page) runs inside the worker thread

- The calling thread never adopts the Playwright event loop — the IPython/Jupyter guarantee holds
- The result returns as-is; an exception propagates as-is: an AssertionError of a step reaches failure classification
  untouched
- Playwright objects never cross back: the callable returns plain data

## The handle members

| Call | Purpose |
|---|---|
| page.run(action) | execute the callable inside the worker thread with the genuine sync Page |
| page.aria_snapshot() | the accessibility-tree page state — the primary LLM input |
| page.screenshot() | full-page PNG bytes |
| page.close() | close this page's isolated context |

## Step execution through the boundary

Step code of the fixed form `def step(page)` receives the genuine sync Page. Compile and resolve stay on the calling
thread; the whole step call runs inside the worker as one run. Every standard Playwright call — locators, actions,
`expect` chains, plain asserts on immediate reads, `locator.count()` — is the real thing on the real object.

## Dialogs — resolver of last resort

The runtime registers one dialog routing handler per page before any step code runs. A dialog handled by an in-step
stock capture (`with page.expect_event("dialog") as info:` ... `info.value.accept()`) is never touched by the router.
Every unclaimed dialog is resolved exactly once: accept when accept_dialogs is on, an explicit dismiss otherwise.
The step wins, the router is last — deterministic inside the worker thread.

## Rules

- One browser process per test; contexts stay isolated
- Driving is strictly sequential: one run at a time
- No fixed delays anywhere in runtime plumbing — waits live in locators and expectations of step code
```

- **UPDATE** `prettyplay/driver/.usages/error_kinds.md`: in the table, REPLACE the "failed expectation" row message signature with `plain AssertionError from a failed expect(...) chain or a plain Python assert on an immediate read — the check executed and did not hold` (pollable: yes). Everything else in the file stays unchanged.

### Artifact 6 — `prettyplay/llm/CODEMANIFEST` (MODIFY — diff)

- Header: unchanged (Imports, Usages: conventions/openai/anthropic).
- Global Annotations: ADD after the user-instructions parity paragraph:
  `The cheat-sheet input participates in both provider implementations with identical semantics: every generation request renders the CHEAT SHEET block after the scenario inputs and immediately before the USER INSTRUCTIONS block — the compact standard Playwright sync API reference supplied by the calling engine; guidance, not an allowlist; a parity requirement, not a capability difference.`
- `LLMProvider.generate_step_code`:
  - Signature: RENAME the parameter `page_api: str` to `cheat_sheet: str` (position unchanged — stays after `screenshot`, before `existing_code`).
  - Parameter annotation REPLACE: `` `cheat_sheet`: the compact standard Playwright sync API reference supplied by the calling engine — rendered by the provider implementations as the leading CHEAT SHEET block of the user content, identically in both; guidance, not an allowlist — everything standard stays allowed. ``
  - Return annotation REPLACE (last sentence): `` `code`: the generated step code of the fixed form, working through the standard Playwright sync API — imports from playwright.sync_api only; the first markdown-fenced block of the answer is unwrapped — an answer with no closed fence returns verbatim. ``
  - Requirements block REPLACE the block-order line: `The block order of a generation request is fixed: CHEAT SHEET, user instructions, CODE, ERROR, RECOMMENDATION, USER GUIDANCE, HISTORY — a non-empty input renders its named block, identically in both implementations` (was "page API, user instructions, CODE, …").
- `LLMProvider.classify_failure`, `LLMProvider.check_instruction_compliance`, `create_provider`, `FailureClassification`, `ComplianceFinding`, `parse_compliance_verdict`: UNCHANGED.
- `LLMProvider::OpenAIProvider` and `LLMProvider::AnthropicProvider` annotations, Algorithm step 1: REPLACE the phrase `a non-empty user_instructions of a generation request renders as a separate USER INSTRUCTIONS block placed after the page API block` WITH `the CHEAT SHEET block renders after the scenario inputs; a non-empty user_instructions of a generation request renders as a separate USER INSTRUCTIONS block placed immediately after the CHEAT SHEET block`. The compliance-operation paragraphs and all other steps: UNCHANGED.
- Footer Description REPLACE the phrase `with identical user-instructions semantics` WITH `with identical user-instructions and cheat-sheet semantics`.

### Artifact 7 — `prettyplay/llm/.usages/providers.md` (UPDATE — diff)

In the `## Parity` section, ADD after the "Regeneration block parity" paragraph:

```md
Cheat-sheet parity: every generation request renders the CHEAT SHEET block after the scenario inputs and
immediately before the USER INSTRUCTIONS block — the compact standard Playwright sync API reference supplied by
the calling engine; guidance, not an allowlist. Both providers render it identically at the same position.
A parity requirement, not a capability difference.
```

Everything else in `providers.md` and the whole of `classification.md`: UNCHANGED.

### Artifact 8 — `prettyplay/engine/CODEMANIFEST` (MODIFY — diff)

- Imports: in the `prettyplay/driver` import block REMOVE the `Usages: [facade]` entry — only `Types: [PageFacade]` remains imported from the driver.
- Usages: ADD `cheat_sheet: .goga/usages/prompts/cheatsheet.md` next to `system_prompt`. `classification_prompt` and `compliance_prompt` inline texts: UNCHANGED.
- Global Annotations:
  - DELETE the lines: `Use `facade` from Imports for the page API the generated code works through.` and `Use `facade` from Imports as the single source of the page API surface for generation requests.` and `The page API surface listing sent to the provider mirrors `facade` from Imports exactly — the listing and the practice change together.`
  - ADD: `Use `cheat_sheet` from Usages as the single source of the standard Playwright API reference for generation requests — the listing and the practice change together; guidance, never an allowlist — everything standard stays allowed.` and `The cheat-sheet sent to the provider mirrors `cheat_sheet` from Usages exactly — the listing and the practice change together.`
  - REPLACE the fixed-form paragraph WITH: `The fixed form of step code: one function receiving exactly one argument — the genuine sync Page of the test; the function body works through the standard Playwright sync API, importing from playwright.sync_api only — a prompt rule carried by `system_prompt`; the whole step executes inside the driver worker thread through the run primitive of `PageFacade` — the calling thread never touches Playwright.`
  - All other global paragraphs (budgets, anti-masking, verdicts, quiet skip, failed-check bound, user-instructions routing, compliance gate, unfollowed instruction, colon-free reasons, decision table, polling, on_generation_started): UNCHANGED.
- `StepGenerator.generate` Algorithm:
  - Step 2 REPLACE WITH: `Collect the request inputs: the page accessibility snapshot, the step sentence, `previous_steps`, and the cheat-sheet from `cheat_sheet`; add the page screenshot when the project settings enable screenshots`
  - Step 3 REPLACE WITH: `Request step code from the provider port generate_step_code passing `system_prompt` as the system prompt, the cheat-sheet taken from `cheat_sheet`, and the user instructions — the effective config generation_prompt — when non-empty`
  - Steps 1, 4–9: UNCHANGED.
  - Requirements REPLACE the first requirement WITH: `Every generation request carries the cheat-sheet taken from `cheat_sheet` from Usages: the model always sees the standard-API reference — guidance, never an allowlist`. Other requirements: UNCHANGED.
- `StepGenerator.regenerate`: UNCHANGED except every provider request implicitly carries the cheat-sheet through the same generate_step_code call (no text change required beyond the shared Algorithm reference).
- `format_step_error`: UNCHANGED.
- `run_step_code` REPLACE the whole type block WITH:

```yaml
"run_step_code(code: str, page: PageFacade)":
  location: execution.py
  annotations: |
    Execute step code of the fixed form: compile and resolve on the calling thread, run the
    whole step inside the driver worker thread against the genuine sync Page.

    `code`: the step code text.
    `page`: the page handle of the current test — the carrier of the worker boundary.

    Algorithm:
    1. Compile and load `code` as a module in an isolated namespace — on the calling thread, Playwright untouched
    2. Resolve the step function of the fixed form — the single callable receiving the page
    3. Execute the whole step-function call inside the driver worker thread as one unit through the run primitive of `page` — the step function receives the genuine sync Page and works through the standard Playwright sync API
    4. An exception raised by the step code propagates to the caller as-is

    Requirements:
    - A failure inside the step code reaches the caller untouched: the engine classifies it, this routine never swallows, translates or retries
    - Executing step code loads no LLM provider and touches no network beyond the page itself
    - The calling thread never touches Playwright: the worker boundary is crossed only by the run primitive

    Constraints:
    - Execute only step code produced by generation or loaded from the cache — never arbitrary file content
```

- `classify_step_failure`: UNCHANGED (snapshot and screenshot collection rides the plumbing members of `PageFacade`).
- `check_step_compliance`, `StepHealer`: UNCHANGED.
- Footer Description REPLACE WITH:
  `The agent engine of prettyplay: step code generation against the standard Playwright API with execution in the loop and failed-check classification, the fixed-form execution routine running the whole step inside the driver worker thread, the instruction compliance gate before caching, the shared classification call carrying the classification user instructions, the error-text policy shared with the executor, and healing with anti-masking and verdicts on terminal failures.`

### Artifact 9 — `prettyplay/engine/.usages/generation.md` (UPDATE — diff)

- In `## Generate a step`, ADD the bullet: `Every generation and regeneration request carries the CHEAT SHEET block right before the USER INSTRUCTIONS block — the compact standard Playwright sync API reference carried by every request; guidance, not an allowlist: everything standard stays allowed, the error-driven regeneration loop is the second line of defense`.
- ADD the section `## The execution boundary` right after `## Generate a step`:

```md
## The execution boundary

The whole step executes inside the driver worker thread as one unit: compile and resolve stay on the calling thread,
the step call itself runs in the worker and receives the genuine sync Page — the calling thread never touches
Playwright, so interactive hosts keep working. An AssertionError of a step — a failed expect chain or a plain assert
on an immediate read — reaches failure classification untouched.
```

- REPLACE the whole `## The fixed form` section WITH:

```md
## The fixed form

Generated code is one function receiving exactly one argument — the genuine Playwright sync Page — importing only
from playwright.sync_api and working through the standard API: `page.get_by_role("button", name="Sign in").click()`,
`page.locator("form > button.primary")`, `videos = page.get_by_role("listitem")` with
`expect(videos.first).to_be_visible()` and `assert videos.count() > 1`,
`with page.expect_event("dialog") as info: ... info.value.accept()`,
`with page.expect_popup() as popup_info: ... popup_info.value`,
`page.frame_locator("#checkout").get_by_role("button", name="Pay").click()`,
`locator.scroll_into_view_if_needed()`, `page.mouse.wheel(0, 600)`. No provider constructs, no fixed delays, no
page.close()/context.close(), no stateful actions (route, clock, add_init_script, tracing, HAR, CDP) — the prompt
rules; the runtime never enforces them.
```

- `healing.md`: UNCHANGED.

### Artifact 10 — `prettyplay/engine/steering/CODEMANIFEST` (MODIFY — diff)

- Imports: in the `prettyplay/driver` import block REMOVE the `Usages: [facade]` entry — only `Types: [PageFacade]` remains imported from the driver.
- Usages: ADD `cheat_sheet: .goga/usages/prompts/cheatsheet.md` next to `system_prompt`.
- Global Annotations:
  - DELETE: `Use `facade` from Imports as the single source of the page API surface for regeneration requests.` and `The page API surface listing sent to the provider is the frozen local mirror of `facade` from Imports — the listing and the practice change together.`
  - ADD: `Use `cheat_sheet` from Usages as the single source of the standard Playwright API reference for regeneration requests — the listing and the practice change together; guidance, never an allowlist.` and `The cheat-sheet sent to the provider mirrors `cheat_sheet` from Usages exactly — the listing and the practice change together.`
  - Keep: `The system prompt sent to the provider is the frozen local mirror of `system_prompt` — the mirror and the practice change together.` and all escape-hatch semantics paragraphs UNCHANGED.
- `StepSteering.steer` Algorithm:
  - Step 4 REPLACE WITH: `A guidance message builds one regeneration request via the provider: `system_prompt` as the system prompt, the cheat-sheet from `cheat_sheet`, the step sentence of `failure` and `previous_steps` as the scenario context, the fresh accessibility snapshot plus the screenshot when the project settings enable screenshots, the user instructions — the effective config generation_prompt — when non-empty, existing_code from the failed code of `failure`, error from its underlying error, the message as the guidance and the accumulated turns as the guidance history`
  - Step 5 REPLACE WITH: `Execute the regenerated code via `run_step_code` against `page` — the whole step runs inside the driver worker thread through the run primitive of the page handle`
  - Steps 1–3, 6–8, Requirements, Constraints: UNCHANGED.
- Footer Description REPLACE WITH:
  `The interactive steering of prettyplay: the opt-in terminal REPL taking engineer guidance over a terminally stuck step — guided regeneration against the standard Playwright API, live execution inside the driver worker thread, the compliance-gated healed write-back or honest decline.`

### Artifact 11 — `prettyplay/engine/steering/.usages/steering.md` (UPDATE — diff)

In the `## The dialog` sample banner, REPLACE the `code:` line WITH:

```text
code:     videos = page.get_by_role("listitem")
          expect(videos.first).to_be_visible()
          assert videos.count() > 1
```

Everything else in the file: UNCHANGED.

### Artifact 12 — `prettyplay/CODEMANIFEST` (root) (MODIFY — diff)

- Imports and Usages: UNCHANGED (the root never imported the `facade` practice).
- Global Annotations ADD at the end of the block:
  `The author escape hatch: run_on_page executes an author callable wholly inside the driver worker thread with the genuine sync Page — the stateful actions excluded from generated code (page.route, page.clock, add_init_script, tracing, HAR, CDP) are performed by the author explicitly; Playwright objects never cross back to the calling thread — the callable returns plain data.`
- `PrettyPlay`:
  - ADD the method declaration (between `expect` and `get_screenshot`):

```yaml
    "run_on_page(action: Callable[[Page], T]) -> result: T": |
      Execute the author action wholly inside the driver worker thread against the genuine sync Page of the test — the author escape hatch.

      `action`: the callable to execute; receives the genuine sync Page — the stateful actions excluded from generated code (page.route, page.clock, add_init_script, tracing, HAR, CDP) are the author's explicit tools here.
      `result`: the outcome of `action` as-is — plain data only.

      Algorithm:
      1. Resolve the opened test page of this test — a missing page raises a loud actionable `PrettyplayError` telling to run a step first
      2. Delegate to the run primitive of the page handle: `action` executes wholly inside the driver worker thread, sequentially with every step
      3. Return the outcome as-is; an exception raised inside `action` propagates to the caller as-is

      Requirements:
      - Requires an opened test page: calling before the first step raises the loud actionable error
      - The callable runs sequentially with the steps of the test — the shared worker takes one unit at a time

      Constraints:
      - Playwright objects (locators, handles, pages, contexts) never cross back to the calling thread through `result` — the callable returns plain data
      - The prompt rules of generated code do not bind the author
```

  - `step`, `expect`, `get_screenshot`, `save_screenshot`, `add_hooks`, `close`, the `cache_key` property, the type annotation, the construction Algorithm and Requirements: UNCHANGED.
- `StepExecutor`: in the type annotation ADD one sentence after the first line:
  `Every execution of step code — cached code and candidates alike — goes through settle with run_step_code: the worker-thread boundary is encapsulated inside run_step_code, the executor never sees it.`
  The constructor signature, `execute` Algorithm and Requirements: UNCHANGED.
- `PrettyplayRuntime`: in `open_page` REPLACE the annotation WITH:
  `Open a fresh isolated browser context and return its page handle — the internal runtime plumbing handle of the test page; one per test. The run_on_page escape hatch of the facade delegates to its run primitive.`
  Everything else: UNCHANGED.
- Footer Description REPLACE WITH:
  `The facade of prettyplay: the per-test scenario object with screenshot abilities and the author escape hatch onto the genuine page, the step cycle executor with the strict replay-only path and verdict reporting, the per-test composition root, and the re-exported settings models — PrettyConfig and BrowserConfig.`

### Artifact 13 — `prettyplay/.usages/` (root usage files, UPDATE — diff)

- `steps.md` — ADD the section `## Author page access` after `## Step kinds`:

```md
## Author page access

The excluded-from-generation stateful actions are performed explicitly by the author — the callable runs wholly
inside the driver worker thread and receives the genuine sync Page:

    with PrettyPlay("videos-flow") as t:
        t.step("open the videos page")
        t.run_on_page(lambda page: page.route("**/api/videos", lambda route: route.fulfill(json={"items": []})))
        t.expect("the page shows a list of videos")

- Requires an opened page: call it after the first step — a loud error otherwise
- The callable returns plain data; Playwright objects (locators, handles, pages) never cross back to the calling thread
- Prompt rules do not bind the author: page.route, page.clock, tracing, HAR, CDP are the author's explicit tools
- The callable runs sequentially with the steps — the shared worker takes one unit at a time
```

- `lifecycle.md` — in `## Interactive sessions (IPython, Jupyter)` ADD after the first paragraph:
  `The author escape hatch run_on_page crosses the same worker boundary the same way: the author callable executes wholly inside the worker thread with the genuine Page — the host thread keeps driving its own prompt loop.`
- Everything else in both files: UNCHANGED.

## Dependency Map

```
prettyplay/config ──────(Config)──────────────────► driver, llm, cache, engine, steering, root
prettyplay/failures ────(failure kinds)───────────► llm, engine, steering, root
prettyplay/reporting ───(StepReporter)────────────► cache, engine, steering, root
prettyplay/driver ──────(PageFacade, is_pollable_failure)──► polling
prettyplay/driver ──────(PageFacade)──────────────► engine, steering
prettyplay/driver ──────(PageFacade, DriverSession)► root
prettyplay/engine/polling ──(SettleWindow, settle)► engine, root
prettyplay/llm ─────────(LLMProvider, FailureClassification, ComplianceFinding)──► engine, steering, root
prettyplay/cache ───────(StepCache, StepIdentity, CachedStep, RunBudgets)──► engine, steering, root
prettyplay/engine ──────(run_step_code, check_step_compliance, StepGenerator, StepHealer, …)──► steering, root
prettyplay/engine/steering ──(StepSteering)───────► root
```

Usage-level edges: `configuration` (config → driver); `hooks` (reporting → root); `taxonomy` (failures → root); `classification` (llm → engine); `generation`, `healing` (engine → root). The `facade` practice import from driver existed for engine and steering — **removed by this plan; no cell imports it afterwards**. No cycles; leaves-to-root order: config, failures, reporting → driver → polling → llm, cache → engine → steering → root.

## Verification Checklist

After each artifact lands, and at series end:

1. `goga lint` — zero errors on all changed CODEMANIFESTs (driver, llm, engine, steering, root).
2. `goga schema` — driver lists exactly three types (`DriverSession`, `PageFacade`, `is_pollable_failure`) and two usages (`error_kinds.md`, `plumbing.md`); polling cell unchanged; no cell has a dependency on the driver `facade` usage; engine and steering list `cheat_sheet` in their usages.
3. Reference closure — every practice connected in a header is referenced by at least one annotation: driver (`conventions`, `playwright`, `configuration`), llm (`conventions`, `openai`, `anthropic`), engine (`conventions`, `system_prompt`, `cheat_sheet`, `classification_prompt`, `compliance_prompt`, `classification`), steering (`conventions`, `system_prompt`, `cheat_sheet`), root (`conventions`, `hooks`, `taxonomy`, `generation`, `healing`).
4. Signature alignment — `run_step_code(code: str, page: PageFacade)` matches `settle`'s `Callable[[str, PageFacade], None]` (polling untouched); `generate_step_code` carries `cheat_sheet` with the block order CHEAT SHEET, USER INSTRUCTIONS, CODE, ERROR, RECOMMENDATION, USER GUIDANCE, HISTORY in both provider implementations.
5. Series completeness — `PAGE_API_SURFACE` and both frozen copies gone (engine constant, steering copy), parity/mirror tests gone, `facade.md` gone; no leftovers (grep the repository).
6. Boundary tests — unit tests cover: the step executes wholly inside the worker thread; the step code receives the genuine sync `Page`; the calling thread never touches Playwright; dialog double-handling never occurs (router yields to an in-step capture; unclaimed dialogs resolve exactly once per `accept_dialogs`).
7. Failure flow — `AssertionError` (expect chain or plain assert) and Playwright timeouts flow through `is_pollable_failure` and the settle window unchanged.
8. Docs same-series — the rewritten `generation.md`, the new `cheatsheet.md`, the updated `playwright.md`, `plumbing.md`, `error_kinds.md`, engine `generation.md`, steering `steering.md`, llm `providers.md`, root `steps.md`/`lifecycle.md` all land with the code.
9. Acceptance — `pytest tests/ -x` green, ruff clean; the step cache purged and the youtube example regenerated on the new engine, including the "list of videos" expectation through standard count forms (`expect(videos.first).to_be_visible()`, `assert videos.count() > 1`); if the environment lacks LLM keys or network, the unit level is accepted and the fact is recorded.
