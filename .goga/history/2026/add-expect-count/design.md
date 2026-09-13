# Design Document: `standard-playwright-step-api`

Open the standard Playwright sync API to generated step code: the worker-thread execution boundary, the facade demotion, the cheat-sheet carrier, the author escape hatch, the surface removal.

Source plan: `.goga/history/2026/add-expect-count/arch.md` (contracts already materialized by the apply stage — working tree, `goga lint` 10 cells 0 errors). Task: `task.md`; ADR: `adr.md` (accepted 2026-09-13). Language: Python (`goga config language` = python).

This document specifies **what to implement and how** — every changed file, algorithm, and test. The implementation order and code belong to the build stage.

---

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/driver/CODEMANIFEST`: full-replacement state. `PageFacade` demoted from the full-parity mirror to the internal runtime plumbing handle — the `url`/`pages` properties and every mirror method are deleted; four members remain: `run`, `aria_snapshot`, `screenshot`, `close`. `LocatorFacade`, `DialogFacade`, `FrameFacade` type declarations deleted. `DriverSession.open_context` step 4 rewritten to the resolver-of-last-resort dialog semantics (deferred resolution at the run-unit boundary). `is_pollable_failure` step 1 wording updated (a failed check — expect chain or plain assert alike). Global annotations rewritten from the parity principle to the standard-API contour.
- `prettyplay/llm/CODEMANIFEST`: `LLMProvider.generate_step_code` parameter `page_api: str` renamed to `cheat_sheet: str` (position unchanged — after `screenshot`, before `existing_code`); block order of a generation request fixed to CHEAT SHEET, user instructions, CODE, ERROR, RECOMMENDATION, USER GUIDANCE, HISTORY; both provider Algorithm step 1 texts updated; global annotations gain the cheat-sheet parity paragraph; footer Description updated.
- `prettyplay/engine/CODEMANIFEST`: the `facade` usage import from the driver removed (`Types: [PageFacade]` stays); `Usages` gains `cheat_sheet: .goga/usages/prompts/cheatsheet.md`; `StepGenerator.generate` steps 2–3 and the first Requirement now carry the cheat-sheet; `run_step_code` rewritten — compile and resolve on the calling thread, the whole step call inside the driver worker thread through the run primitive of `page`; footer Description updated.
- `prettyplay/engine/steering/CODEMANIFEST`: the `facade` usage import removed; `Usages` gains `cheat_sheet`; annotations swapped `facade` → `cheat_sheet`; `StepSteering.steer` steps 4–5 updated (cheat-sheet request; worker-thread execution); footer Description updated.
- `prettyplay/CODEMANIFEST` (root): global annotations gain the author-escape-hatch paragraph; `PrettyPlay` gains the method `run_on_page(action: Callable[[Page], T]) -> result: T` (placed between `expect` and `get_screenshot`); `StepExecutor` type annotation gains the settle/run_step_code encapsulation sentence; `PrettyplayRuntime.open_page` annotation re-worded to the page handle; footer Description updated.

### New Entities

- `PageFacade.run(action: Callable[[Page], T]) -> result: T` — `prettyplay/driver/page.py`. The worker-boundary crossing primitive: executes the callable wholly inside the driver worker thread with the genuine sync `Page`, then runs the deferred dialog-resolution pass.
- `PrettyPlay.run_on_page(action: Callable[[Page], T]) -> result: T` — `prettyplay/scenario.py`. The author escape hatch: delegates to the run primitive of the opened test page.
- `CHEAT_SHEET` module constant — `prettyplay/engine/generator.py` and (cell-owned copy) `prettyplay/engine/steering/steering.py`. Frozen mirrors of `.goga/usages/prompts/cheatsheet.md`.

### Changed Entities

- `PageFacade` — demoted to the internal runtime plumbing handle (annotations, member set, constraints: no member proxies).
- `_DialogRouter` (internal, `prettyplay/driver/page.py`) — from immediate resolution inside the event handler to record-only handler + deferred `resolve_pending()` at the run-unit boundary with the already-handled guard.
- `DriverSession.open_context` — dialog wiring step reworded to the resolver of last resort; behavior change is the deferral.
- `run_step_code(code, page)` — same signature; execution now crosses the worker boundary through `page.run`; compile/resolve stay on the calling thread.
- `StepGenerator._request` / `StepSteering._guided_request` — pass `cheat_sheet=CHEAT_SHEET` instead of `page_api=PAGE_API_SURFACE`.
- `SYSTEM_PROMPT` (engine and steering copies) — rewritten to the new generation practice.
- `LLMProvider.generate_step_code` + `OpenAIProvider.generate_step_code` + `AnthropicProvider.generate_step_code` + `_request.build_fields_text` — parameter rename and the `CHEAT SHEET:` section header.
- `prettyplay.driver.__init__` exports — shrink to `DriverSession`, `PageFacade`, `is_pollable_failure`.
- `is_pollable_failure` — docstring wording only; behavior identical (plain `AssertionError` was already pollable).

### Deleted Entities

- `LocatorFacade`, `DialogFacade`, `FrameFacade` — the managed element/dialog/frame surfaces die with the mirror (ADR q1=A).
- `PageFacade.url`, `PageFacade.pages` — plumbing never exposes page enumeration.
- `_DialogCapture`, `_PopupCapture`, `PageFacade.__getattr__` shell guard, `_SCROLL_INTO_VIEW_JS`, every mirror/scroll/expect method of `PageFacade` — capture shells and facade extras leave with the surface.
- `PAGE_API_SURFACE` (engine constant and steering copy) — replaced by the cheat-sheet mirrors.
- `prettyplay/driver/.usages/facade.md` — already deleted by the apply stage.
- Parity/mirror tests pinning the surface (see Test Stack Trace).

### Usages and Annotations Changes

- `.goga/usages/prompts/cheatsheet.md` — created (apply stage); the compact standard-API reference.
- `.goga/usages/prompts/generation.md` — rewritten (standard-API rules, import rule, safety core, stateful exclusions).
- `.goga/usages/cooks/playwright.md` — updated (the standard-API contour section, stock dialog means, popups/frames wording, rules footer).
- Cell `.usages/` files — all already materialized: `prettyplay/driver/.usages/plumbing.md` (new), `error_kinds.md` (failed-expectation row), `prettyplay/llm/.usages/providers.md` (cheat-sheet parity), `prettyplay/engine/.usages/generation.md` (execution boundary + fixed form + cheat-sheet bullet), `prettyplay/engine/steering/.usages/steering.md` (banner sample), `prettyplay/.usages/steps.md` (author page access), `prettyplay/.usages/lifecycle.md` (escape-hatch paragraph).

## Applied Fixes

### Fixed CODEMANIFEST Defects

None found by the design stage. Phase 3 validation found zero contract defects: `goga lint` reports 10 cells / 0 errors; reference closure holds for every connected practice of the five changed manifests; the four consistency dimensions pass (interface↔type, type↔mutation, interface↔interface, annotations↔entity — details in the Code Stack Trace checkpoints). The gap analysis found only implementation lag — the exact build-stage work items specified below. No CODEMANIFEST edits were made by the design stage.

**Design review (2026-09-13) — one contract edit applied**: `prettyplay/config/CODEMANIFEST` annotations of `accept_dialogs` (constructor parameter line and the property annotation) still described the setting through the deleted `expect_dialog` capture — reworded to "no in-step stock dialog capture claims" / "outside in-step stock captures", matching the driver manifest language. Behavior unchanged; `goga lint` re-run clean (10 cells / 0 errors). The matching implementation-level artifacts (`prettyplay/config/models.py` docstring, `prettyplay/config/.usages/configuration.md` lines 169/171, `.goga/usages/cooks/playwright.md` line 157) are recorded above as build-series work items.

---

## Entity Interaction and Data Flow

### Interaction Diagram

```
        calling thread (pytest / IPython / the runner)          driver worker thread (PlaywrightWorker._pump)
┌──────────────────────────────────────────────┐      ┌─────────────────────────────────────────────────┐
│ PrettyPlay.step / expect                     │      │                                                 │
│  └─ StepExecutor.execute                     │      │  unit():                          one unit    │
│     ├─ cache hit: settle(run_step_code, …)   │      │   ├─ action(genuine sync Page)     at a time  │
│     │    └─ run_step_code(code, page)        │      │   │    step(page)  — stock Playwright:       │
│     │        compile + exec + resolve  ──────┼─────►│   │    locators, expect(…), plain asserts,   │
│     │        (calling thread, no Playwright) │ run( │   │    expect_event("dialog"), expect_popup  │
│     ├─ miss: StepGenerator.generate ─────────┤ unit)│   └─ finally: _DialogRouter.resolve_pending() │
│     │    └─ _request: cheat_sheet=CHEAT_SHEET│      │        the resolver of last resort:          │
│     │    └─ LLMProvider.generate_step_code   │      │        accept per accept_dialogs, else        │
│     │       (CHEAT SHEET block in request)   │      │        dismiss; "already handled" → skip      │
│ PrettyPlay.run_on_page(action) ──────────────┼─────►│                                                 │
│    (author escape hatch; same primitive)     │      │  page.on("dialog") → router.record(dialog)     │
│                                              │      │  (record only — never resolves mid-unit)       │
└──────────────────────────────────────────────┘      └─────────────────────────────────────────────────┘
```

### Data Flows

- **Step execution (cached or candidate)**: `StepExecutor.execute` → `settle(run_step_code, code, page, window)` → `run_step_code` compiles/execs `code` and resolves `step` on the calling thread → `page.run(step)` marshals one unit → the worker calls `step(genuine Page)` → any exception re-raised on the calling thread → `settle` applies `is_pollable_failure` and re-executes inside the window (each re-execution is its own run unit with its own resolver pass) → the engine classifies terminal failures.
- **Generation request**: `StepGenerator._request` collects `page.aria_snapshot()` (+ `page.screenshot()` when enabled) via the plumbing members → `provider.generate_step_code(prompt=SYSTEM_PROMPT, cheat_sheet=CHEAT_SHEET, …)` → `build_fields_text` renders STEP / PREVIOUS STEPS / PAGE SNAPSHOT / CHEAT SHEET / [USER INSTRUCTIONS] / [CODE] / [ERROR] / [RECOMMENDATION] / [USER GUIDANCE] / [HISTORY] → one SDK request → the first fenced block unwrapped as the candidate code.
- **Guided regeneration (steering)**: `StepSteering.steer` step 4 builds the request with `cheat_sheet=CHEAT_SHEET`; step 5 executes via `run_step_code(code, page)` bare (no settle — the window never re-arms inside the dialog); the run primitive still resolves leftover dialogs at the unit boundary, keeping the live page usable for the next turn.
- **Dialog flow**: `DriverSession.open_context` registers `router.record` on every page of the context through the context `page` event before `new_page()` → a dialog firing mid-unit is recorded (page JS blocks — documented behavior) → the step's stock capture (`page.expect_event("dialog")`) may claim and resolve it inside the unit → at the unit tail `resolve_pending()` resolves each unclaimed dialog exactly once; a dialog the step already resolved raises the driver's "already handled" error and is skipped.
- **Author escape hatch**: `PrettyPlay.run_on_page(action)` → missing page raises `PrettyplayError` → `self._page.run(action)` → the author callable runs wholly inside the worker with the genuine `Page` (`page.route`, tracing, HAR, CDP are the author's explicit tools) → the plain-data outcome returns as-is.

### Entity Dependencies

Unchanged dependency map (verified via `goga schema`): `prettyplay/config`, `prettyplay/failures`, `prettyplay/reporting` → `prettyplay/driver` → `prettyplay/engine/polling` → `prettyplay/llm`, `prettyplay/cache` → `prettyplay/engine` → `prettyplay/engine/steering` → `prettyplay` (root). The polling cell is untouched — `settle(execute: Callable[[str, PageFacade], None], …)` still matches `run_step_code(code: str, page: PageFacade)`. Build order is leaves-first: driver → llm → engine → steering → root → tests/docs/example.

---

## Code Stack Trace

### Trace: `PageFacade.run` (new)

#### Chain
1. **Input**: a caller on the calling thread — `run_step_code` (the resolved `step` callable) or `PrettyPlay.run_on_page` (the author callable); `action: Callable[[Page], T]`.
2. **Step**: `run` builds one unit closure wrapping `action` and the deferred resolver → checkpoint: the resolver is inside the unit, so it always runs on the worker thread (contract: "deterministically inside the driver thread") — passed.
3. **Step**: with a live session the unit is marshaled via `PlaywrightWorker.run` (queue → pump thread → `task.done` wait → result/error re-raised on the caller); with no worker (hand-built handle in tests) the unit executes inline → checkpoint: the worker re-raises the original exception object untouched — an `AssertionError` of a step reaches `is_pollable_failure` with type and message intact — passed.
4. **Step**: inside the unit, `action(self._page)` receives the genuine sync `Page` object held by the handle → checkpoint: no wrapper, no proxy — the object Playwright itself returned — passed.
5. **Step**: `finally: router.resolve_pending()` (when a router is attached) resolves every recorded dialog left unclaimed → checkpoint: the resolver swallows its own failures, so it can never mask or replace the action outcome — passed (design decision D3).
6. **Output**: `action`'s return value as-is (`T`) to the calling thread; plain data only by contract (the constraint is documented, not enforced — prompt-level for step code, doc-level for authors).

#### Checkpoint Summary
- Worker-boundary containment: passed — one `worker.run` call per unit; the calling thread never touches a Playwright object.
- Exception identity: passed — the pump stores `task.error` and re-raises the same object; no wrapping exists on the path.
- Dialog determinism: passed — record-only handler plus unit-tail resolution (trace below).

### Trace: `DriverSession.open_context` (changed step 4)

#### Chain
1. **Input**: `StepExecutor` → `PrettyPlay._ensure_page` → `PrettyplayRuntime.open_page` → `DriverSession.open_context` (first call lazily starts worker + Playwright + browser — unchanged).
2. **Step**: inside one `worker.run(open_isolated)`: screen params resolved, `browser.new_context(**params)`, `_DialogRouter(accept_dialogs)` created → checkpoint: the router reads the setting once at context creation — passed.
3. **Step**: `context.on("page", lambda opened: opened.on("dialog", router.record))` registered **before** `new_page()` — the open_context page and every later popup/tab registers exactly one handler → checkpoint: registration-before-creation ordering preserved from the current implementation — passed.
4. **Step**: `page = context.new_page()`; the handle `PageFacade(page, context)` is bound to the worker and the router and returned → checkpoint: the handle carries `_worker` and `_router` exactly as today — passed.
5. **Behavior change**: the handler no longer resolves a dialog when it fires — it appends to the router's pending list (pure bookkeeping, no Playwright call inside event dispatch). Resolution happens at the next run-unit tail. Registering any `dialog` listener still disables Playwright's implicit auto-dismiss, so the router remains the only resolver of unclaimed dialogs.

#### Checkpoint Summary
- Exactly-once resolution: passed — each dialog is resolved either by the step's capture (inside the unit) or by the resolver pass (at the unit tail); the resolver's accept/dismiss on a step-resolved dialog raises the driver's `Cannot accept dialog which is already handled!` and is skipped (Playwright 1.62.0 verified: no `Dialog.handled` property exists — the error text is the only signal; message `Cannot accept|dismiss dialog which is already handled!` confirmed in the installed driver bundle).
- Sequential driving: passed — handler work is O(1) append; resolution joins the unit queue.

### Trace: `run_step_code` (rewritten)

#### Chain
1. **Input**: `settle(execute=run_step_code, code, page, window)` from the executor and both generator loops; or a bare call from steering.
2. **Step**: `exec(compile(code, "<prettyplay-step>", "exec"), namespace)` on the calling thread → checkpoint: a generated `from playwright.sync_api import expect` header executes at import time — safe, the import parks no loop (`sync_playwright().start()` never runs) — passed.
3. **Step**: `fn = namespace["step"]` — the fixed-form callable → checkpoint: a `SyntaxError`/`KeyError` here propagates on the calling thread before any worker involvement; both are Python-level, non-pollable, and reach classification exactly as today — passed.
4. **Step**: `page.run(fn)` — the whole step-function call is one worker unit with the genuine `Page` → checkpoint: signature match with polling — `Callable[[str, PageFacade], None]` — unchanged — passed.
5. **Output**: `None` on success; any exception propagates as-is (never swallowed, translated, or retried here).

#### Checkpoint Summary
- Settle compatibility: passed — `settle`'s `execute(code, page)` call shape untouched.
- Pollable flow: passed — a failed `expect(...)` chain raises `AssertionError`; a failed `assert videos.count() > 1` raises `AssertionError`; Playwright timeouts raise `Error` with `Timeout NNNms exceeded` — `is_pollable_failure` maps both families exactly as before (its behavior is unchanged; only annotation/docstring wording moves).

### Trace: `LLMProvider.generate_step_code` (renamed slot)

#### Chain
1. **Input**: engine `_request` / steering `_guided_request` call with `cheat_sheet=CHEAT_SHEET` (keyword).
2. **Step**: `build_fields_text(user_instructions, step_text, previous_steps, snapshot, cheat_sheet, …)` renders `f"CHEAT SHEET:\n{cheat_sheet}"` in the fixed section order: STEP, PREVIOUS STEPS, PAGE SNAPSHOT, CHEAT SHEET, [USER INSTRUCTIONS], [CODE], [ERROR], [RECOMMENDATION], [USER GUIDANCE], [HISTORY] → checkpoint: "after the scenario inputs and immediately before the USER INSTRUCTIONS block" — the section occupies the exact position the old PAGE API block held — passed.
3. **Step**: `openai_user_content` / `anthropic _user_content` wrap the same text (image block appended when a screenshot is attached) → checkpoint: parity — both providers call the identical shared builder — passed.
4. **Step**: the answer's first markdown-fenced block is unwrapped by `extract_code_block` → checkpoint: unchanged; the return annotation's "imports from playwright.sync_api only" is a property of the generated code, not of the provider — passed.
5. **Output**: `code: str` of the fixed form.

#### Checkpoint Summary
- Block order contract: passed — a non-empty input renders its named block; the rename is mechanical at this layer.
- Step addressing: passed — `cheat_sheet` takes no part in `StepIdentity` (cache addressing unchanged; instructions/surface drift never invalidates cache entries — moot after the purge anyway).

### Trace: `PrettyPlay.run_on_page` (new)

#### Chain
1. **Input**: the author calls `t.run_on_page(action)` between steps.
2. **Step**: `self._page is None` → raise `PrettyplayError("no test page yet: run a step first — the page opens lazily on the first step")` → checkpoint: message uniform with `get_screenshot`/`save_screenshot` — passed.
3. **Step**: `return self._page.run(action)` → the shared worker takes the author unit sequentially with step units → checkpoint: no fold — `run_on_page` does not go through `_raise_folded` (uniform with the screenshot abilities; the contract says the action's exception propagates as-is, and author `Error`s are not `PrettyplayError`s anyway) — passed.
4. **Output**: the action's outcome as-is; Playwright objects never cross back (documented constraint).

#### Checkpoint Summary
- Boundary reuse: passed — the escape hatch is the run primitive, not a new crossing point; the threading invariant of the ADR holds.

### Trace: `StepGenerator` request inputs (changed steps 2–3)

#### Chain
1. **Input**: `_request(step_text, previous_steps, page, existing_code, error, recommendation)`.
2. **Step**: `snapshot = page.aria_snapshot()`, `screenshot = page.screenshot() if config.send_screenshots else None` → checkpoint: both are plumbing members of the demoted handle — they survive — passed.
3. **Step**: `provider.generate_step_code(prompt=SYSTEM_PROMPT, …, cheat_sheet=CHEAT_SHEET, …)` → checkpoint: the frozen mirror rule (below) — passed.
4. **Output**: candidate code → `settle(run_step_code, code, page, window)` — unchanged loop.

#### Checkpoint Summary
- `regenerate`/healing paths: passed — they share `_request`; no text changes needed beyond the shared call (plan artifact 8).

---

## Algorithm Design

### `PageFacade` (rewritten, `prettyplay/driver/page.py`)

**Responsibility**: the internal runtime plumbing handle of one test page — the worker-boundary crossing point, the page-state readers for the engine, and the context close. Not an API for generated code.

**Algorithm (`run`)**:
```
1. build the unit closure:
   - try: return action(self._page)          # the genuine sync Page, inside the worker
   - finally: _resolve_leftovers()           # deferred dialog pass; never raises
2. IF self._worker is None:                  # hand-built handle (tests): inline execution
   - return unit()
3. ELSE:
   - return self._worker.run(unit)           # one queued unit; outcome/error re-raised as-is
```

**`_resolve_leftovers`**: `if self._router is not None: self._router.resolve_pending()` — a handle without a session has no registered handler, hence nothing pending; a no-op is correct.

**Kept members** (unchanged bodies, still through `_call`): `aria_snapshot()` → `self._page.locator("body").aria_snapshot()`; `screenshot()` → `self._page.screenshot(full_page=True)`; `close()` → `self._context.close()`.

**Errors**:
- `action` exception → propagates untouched (worker re-raises the same object).
- resolver failure → logged, swallowed (below); never masks the action outcome.

**Edge cases**:
- Hand-built handle (no worker) → inline unit; resolver still runs when a router was attached.
- No router attached → resolver is a no-op.
- `run` called concurrently from two threads → serialized by the worker queue; with no worker, the same loose contract as today's `_call` (strictly sequential driving is a documented constraint).

### `_DialogRouter` (rewritten, same module)

**Responsibility**: the resolver of last resort for every dialog of one browser context. Record-only during units; resolve once at each unit tail.

**Algorithm**:
```
__init__(accept_dialogs: bool):
  - self.accept_dialogs = accept_dialogs
  - self._pending: list[Dialog] = []          # context-wide; single worker thread touches it

record(dialog):                                # the per-page "dialog" handler
  - self._pending.append(dialog)               # pure bookkeeping — no Playwright call inside event dispatch

resolve_pending():                             # the unit-tail pass, inside the worker
1. swap out the pending list (dialogs, self._pending = self._pending, [])
2. FOR each dialog in dialogs:
   - try: dialog.accept() when accept_dialogs else dialog.dismiss()
   - except Error as failure:
     - "already handled" in str(failure) → skip silently   # the step's capture resolved it
     - otherwise → logger.warning("dialog resolution failed", extra={"error": str(failure)})
```

**Errors**: the guard wraps the whole resolution attempt (the impl layer already swallows target-closed on `dismiss`, but not on `accept` — the guard covers both uniformly).

**Edge cases**:
- Pending dialogs on a *popup* page of the context: the flat context-wide queue drains them at the unit tail of the main page's handle — the only deterministic boundary that exists. The manifest's run step ("every dialog of this page") is satisfied; the stronger open_context requirement ("every dialog is resolved exactly once") is upheld context-wide.
- A dialog recorded after the swap — fired during the pass itself or at the unit tail — stays pending for the next unit tail: the flat queue never re-arms mid-pass. The next run unit (a settle re-execution or the next step) drains it; the page's JS stays blocked until then — the documented contract behavior.
- A dialog left unclaimed mid-step blocks the page's JS until the unit ends — documented contract behavior; the step typically times out (pollable), the resolver closes the dialog at the unit tail, and the settle re-execution starts from a clean page.
- Resolver errors (e.g. target closed) never break the unit and never mask the action exception (they run in `finally` and swallow).

### `DriverSession.open_context` (changed wiring, `prettyplay/driver/session.py`)

**Responsibility**: unchanged lifecycle owner; only the dialog wiring step and docstrings change.

**Algorithm (step 4, the only change)**:
```
inside worker.run(open_isolated):
  - router = _DialogRouter(config.browser.accept_dialogs)
  - context.on("page", lambda opened: opened.on("dialog", router.record))
  - page = context.new_page()
```
`handle_for(page)` (the per-page closure) is deleted — `record` needs no page binding. Everything else in `session.py` (lazy start, screen resolution, launch/connect, close) is byte-identical.

### `run_step_code` (rewritten, `prettyplay/engine/execution.py`)

**Responsibility**: execute fixed-form step code — compile and resolve on the calling thread, run the whole step inside the driver worker thread.

**Algorithm**:
```
1. namespace: dict[str, object] = {}
   exec(compile(code, "<prettyplay-step>", "exec"), namespace)   # calling thread; Playwright untouched
2. step_fn = the namespace["step"] callable                       # the fixed form
3. page.run(step_fn)                                              # one worker unit; genuine Page inside
```
(`namespace["step"]` is typed `object`; keep the current looseness or a `cast` to `Callable` — either matches the existing style of this routine.)

**Errors**: everything propagates as-is; no swallowing, translation, or retry. **Constraints**: only code produced by generation or loaded from the cache — never arbitrary file content (unchanged).

### Frozen mirrors (`SYSTEM_PROMPT`, `CHEAT_SHEET` — engine and steering)

**Responsibility**: the exact request payloads, cell-owned, with no runtime read of `.goga/`.

- `SYSTEM_PROMPT`: the section after the `---` separator of `.goga/usages/prompts/generation.md`, verbatim (same extraction rule and comment as today; the content is the rewritten practice).
- `CHEAT_SHEET`: the **whole** `.goga/usages/prompts/cheatsheet.md` verbatim. The practice has no `---` separator, so the whole-file rule is the only mirror rule with no extraction logic to drift; the intro paragraph is written for the generation model as much as for maintainers. Comment documents: "Frozen mirror of `.goga/usages/prompts/cheatsheet.md` — the constant changes only together with the file."
- Steering keeps its own local copies of both constants (the cell-owned frozen-mirror rule — "A local copy of the engine constant, not an import"), with the mirror comment updated.

### `StepGenerator._request` / `StepSteering._guided_request` (mechanical)

`page_api=PAGE_API_SURFACE` → `cheat_sheet=CHEAT_SHEET`. Nothing else changes in either call site.

### `LLMProvider.generate_step_code` + providers + `_request.build_fields_text` (mechanical rename)

- Parameter `page_api: str` → `cheat_sheet: str` at the same position in: `provider.py` (port), `openai_provider.py`, `anthropic_provider.py`, `_request.build_fields_text`.
- Section header `"PAGE API:\n{page_api}"` → `"CHEAT SHEET:\n{cheat_sheet}"`; docstrings updated to the cheat-sheet semantics (guidance, not an allowlist).
- Docstring/annotation text updates: `code` return ("working through the standard Playwright sync API — imports from playwright.sync_api only"), the block-order requirement line, both provider Algorithm step 1 phrases.

### `PrettyPlay.run_on_page` (new, `prettyplay/scenario.py`)

**Algorithm**:
```
1. IF self._page is None: raise PrettyplayError("no test page yet: run a step first — the page opens lazily on the first step")
2. return self._page.run(action)
```
Placed between `expect` and `get_screenshot` (contract order). Imports gain `Callable`, `Page`, `TypeVar`. Full Google-style docstring per conventions (purpose, `action`, `result`, Raises for `PrettyplayError` and the action's own exceptions). No traceback folding (uniform with the screenshot abilities).

### `prettyplay/driver/__init__.py`

Exports shrink to `DriverSession`, `PageFacade`, `is_pollable_failure` (alphabetized `__all__` as today); the import line drops the three deleted facades.

### `prettyplay/driver/errors.py`

Docstring wording only: "the facade error surface" → "the step-code error surface"; "a failed expectation" → "a failed check — a failed expect(...) chain or a plain Python assert on an immediate read". No logic change.

---

## Cross-cutting Concerns

- **Error handling**: unchanged taxonomy and flow. The step's exception object crosses the worker boundary by identity; the engine classifies; the settle window absorbs pollable kinds. New rule: the dialog resolver never masks the action outcome (it runs in `finally` and swallows its own failures with a WARNING). The steering bare-execution asymmetry (no settle inside the dialog) is intentional and preserved.
- **Logging**: one new record — `dialog resolution failed` at WARNING (`logger = logging.getLogger("prettyplay")` in `page.py`), `extra={"error": str(failure)}`. `settle_retry`, gate warnings, steering records unchanged.
- **Validation**: none added. The import rule and the stateful-action exclusions are prompt rules only — no runtime gate (task.md out-of-scope: "Runtime gating of imports/exclusions — prompt rules only"). The error-driven regeneration loop stays the second line of defense.
- **Caching**: the step cache is disposable — `example/.prettyplay/cache/**` is purged in this series; no compatibility shims; every example regenerates on the new engine. `cheat_sheet`/`system_prompt` take no part in step addressing (unchanged rule).
- **Concurrency**: the unit is the serialization grain — action + resolver pass are one `worker.run` call, sequential with every other unit (steps, author escape-hatch calls, plumbing reads). The dialog handler is record-only, so no Playwright call ever happens inside event dispatch. The calling thread never adopts the Playwright event loop (the IPython/Jupyter guarantee).
- **Environment facts (recorded per the acceptance rule)**: this design was produced by static tracing — the repository venv (`.venv`, created on macOS) has broken interpreter symlinks here (`/opt/homebrew/...`), so `pytest`/`ruff` cannot run in this environment. The build stage must recreate the venv (conventions: "Execute all code within a virtualenv — create it if missing") and run the suite there. Playwright is 1.62.0; its Python `Dialog` has no `handled` property, and the driver's double-handling error text is `Cannot accept|dismiss dialog which is already handled!` — the resolver guard matches `"already handled"` in the message.

---

## Usages Analysis

### Project practices of the changed cells

- **`conventions`** (`.goga/usages/conventions.md`) — Python rules: relative intra-package imports, Google-style docstrings everywhere, `logging` (the `prettyplay` logger), pydantic `kw_only` models (none added here), Python 3.10+. Applied by every touched file; the new `page.py`/`run_on_page` docstrings follow the existing full-docstring style.
- **`playwright`** (`.goga/usages/cooks/playwright.md`, updated) — the sync API lifecycle, the standard-API contour for generated code (worker-thread execution, genuine `Page`, import rule, safety core, stateful exclusions, waiting-vs-immediate assertion guidance), the dialog event model (stock captures; the routing handler as runtime behavior), the error kinds. Used by: driver annotations (session/page/errors), the design of `run`/router, `is_pollable_failure` patterns, and the docs rewrite. Build-series rework (review finding): line ~157 of the Dialogs rules still says "the handler itself resolves every uncaptured dialog" — the immediate-resolution phrasing; reword to "the routing handler subsystem resolves every uncaptured dialog at the run-unit tail" (keeps the parenthetical "the same observable default"; paragraph 147 already carries the resolver-of-last-resort semantics).
- **`system_prompt`** (`.goga/usages/prompts/generation.md`, rewritten) — the single source of the generation system prompt; mirrored frozen into engine and steering constants. Used by: `StepGenerator`, `StepSteering`.
- **`cheat_sheet`** (`.goga/usages/prompts/cheatsheet.md`, new) — the compact standard-API reference carried by every generation/regeneration request; mirrored frozen into engine and steering constants. Used by: `StepGenerator._request`, `StepSteering._guided_request`.
- **`classification_prompt` / `compliance_prompt`** (inline, engine) — unchanged.
- **`openai` / `anthropic`** (`.goga/usages/llm/*.md`, llm cell) — unchanged; both providers' request paths verified against them.
- **`configuration`** (imported from `prettyplay/config`) — the browser-group settings the session reads, `accept_dialogs` included; the resolver reads the setting through the context-created router.
- **`classification`** (imported from `prettyplay/llm`) — unchanged healing categories.
- **`hooks` / `taxonomy` / `generation` / `healing`** (root imports) — unchanged.

### Imported Usages

- `configuration` from `prettyplay/config` — path `prettyplay/config/.usages/configuration.md`; drives `accept_dialogs` resolution semantics in the router. Build-series rework (sweep-blocking): lines 169 and 171 still say «step-captured `expect_dialog` block» — reword to «in-step stock dialog capture» (two lines, no semantic change; syncs with the config CODEMANIFEST annotation edit).
- `classification` from `prettyplay/llm` — path `prettyplay/llm/.usages/classification.md`; unchanged healing-decision context for the engine.
- The removed `facade` import from `prettyplay/driver` (engine, steering) — deleted; `goga schema` confirms no cell depends on the driver `facade` usage anymore.

---

## `.usages/` Update

### Cell: `prettyplay/driver`
- **`plumbing.md`** (new, already materialized) — current; matches the CODEMANIFEST member table (`run`, `aria_snapshot`, `screenshot`, `close`) and the resolver-of-last-resort semantics. No additions needed.
- **`error_kinds.md`** (updated) — current; the failed-expectation row now covers plain asserts. No additions needed.
- **`facade.md`** — deleted (verify in the build series: file absent, no references).

### Cell: `prettyplay/llm`
- **`providers.md`** (updated) — current; the cheat-sheet parity paragraph matches the CODEMANIFEST block order. **`classification.md`** — unchanged, still current.

### Cell: `prettyplay/engine`
- **`generation.md`** (updated) — current: the CHEAT SHEET bullet, the execution-boundary section, the rewritten fixed form. **`healing.md`** — unchanged, still current.

### Cell: `prettyplay/engine/steering`
- **`steering.md`** (updated) — current; the banner sample shows the count-forms code. No additions needed.

### Cell: `prettyplay` (root)
- **`steps.md`** (updated) — current; the Author page access section matches `run_on_page`. **`lifecycle.md`** (updated) — current; the escape-hatch paragraph. No additions needed.

No `.usages/` file requires further changes from the build stage — all are consistent with the materialized CODEMANIFESTs (verified file-by-file against the plan artifacts).

### Project documentation (in scope per task.md/ADR: "the driver-facade docs are rewritten in the same series")

Not cell practices — MkDocs/README pages; the build stage rewrites them with the code:

- **`docs/reference/driver-facade.md`** (270 lines, fully stale) — rewritten in place (path kept — no mkdocs nav churn; ADR says rewritten, not renamed). New content: the internal page handle (member table), the worker boundary, the generated-code contour (standard API, import rule, safety core, stateful exclusions), dialogs (stock captures + resolver of last resort + `accept_dialogs`), popups/frames/scrolling through stock means, the author escape hatch `run_on_page`.
- **`docs/guides/writing-steps.md`** — step-code examples rewritten to standard Playwright forms (locator factories, `expect` chains, count forms `assert videos.count() > 1`, `with page.expect_event("dialog") as info:`, `expect_popup`, `frame_locator`, `scroll_into_view_if_needed` / `page.mouse.wheel`); the driver-facade link text retitled; the unclaimed-dialog paragraph re-worded to the resolver semantics.
- **`docs/configuration.md`** — `accept_dialogs` wording: "step-captured `expect_dialog` blocks" → in-step stock captures / resolver of last resort.
- **`docs/reference/interactive-steering.md`** — banner sample synced with the steering practice (the count-forms code lines); surrounding prose checked for facade phrasing.
- **`README.md`** — four spots: the `accept_dialogs` comment (line ~192) and the two dialog bullets (~275, ~279), plus "the longest facade wait" (~123) → "the longest auto-wait".
- **`docs/index.md`** — line ~71, the reference-list description of the driver page: "the page API generated step code uses" is factually wrong after the change → "the internal page handle, the worker boundary and the generated-code contour" (the link target stays `driver-facade.md`).
- **`docs/reference/settle-polling.md`** — the same wait-phrase family the README item fixes: "the facade's internal waits count inside it" (~13) → "the step's internal auto-waits count inside it"; "the longest facade wait it must absorb" (~30) → "the longest auto-wait it must absorb".
- **`docs/guides/browser-setup.md`** — line ~45 "never the facade surface" → "never the page-driving behavior" (screen modes change only how the context opens). The "Driver facade" link texts of `browser-setup.md:47`, `step-cache.md:65` and `llm-providers.md:68` match the kept page title — no change.

---

## Test Stack Trace

### General Setup

Existing conventions keep applying: fakes over real browsers at the unit level (`FakePage`-style raw objects, hand-built `PageFacade` without a worker → inline execution), `FakeProvider` recording `generate_step_code` kwargs, `tmp_path` caches via the `write_pyproject` fixture, the `_no_runtime_atexit` autouse fixture. New shared fixture needs:

- **`FakeRawDialog`** (reusable, `tests/driver/test_page.py` and `tests/engine/test_execution.py`): fields `message`; `state` in `{"open", "accepted", "dismissed"}`; `accept(prompt_text=None)` / `dismiss()` set state or raise `playwright.sync_api.Error("Cannot accept dialog which is already handled!")` when not open (mirrors the real driver).
- **`FakeRawPage`**: an `object()` sentinel is sufficient for identity checks; a `SimpleNamespace` with the members an action touches for richer tests.
- The real `PlaywrightWorker` is Playwright-independent (queue + pump thread) — unit tests may `start()` it without a browser to prove thread identity.

### Source File Registry

`prettyplay/driver/page.py`, `prettyplay/driver/session.py`, `prettyplay/driver/errors.py`, `prettyplay/driver/__init__.py`, `prettyplay/engine/execution.py`, `prettyplay/engine/generator.py`, `prettyplay/engine/steering/steering.py`, `prettyplay/llm/provider.py`, `prettyplay/llm/_request.py`, `prettyplay/llm/openai_provider.py`, `prettyplay/llm/anthropic_provider.py`, `prettyplay/scenario.py`, `prettyplay/config/models.py` (docstring-only rewording: the `accept_dialogs` field docstring still names the deleted `expect_dialog` capture — «no captured ``expect_dialog`` block claims» becomes «no in-step stock dialog capture claims»; behavior identical).

### File-level plan

| Test file | Action |
|---|---|
| `tests/driver/test_page.py` | rewrite: the facade/mirror/locator/dialog-capture suites die; the run/resolver suite below is written; `aria_snapshot`/`screenshot`/`close` delegation tests are kept/adapted |
| `tests/driver/test_session.py` | keep the launch/screen/connect suites; update the dialog-wiring test to record-only semantics |
| `tests/driver/test_errors.py` | keep; add the plain-assert pollable case |
| `tests/engine/test_execution.py` | rewrite around the run primitive; keep/adapt the compile-phase coverage: the signature test, `SyntaxError` propagation, the missing-step `KeyError`, namespace isolation between calls, no `sys.modules` registration |
| `tests/engine/test_generator.py` | keep the loop/decision-table suites (fakes untouched); replace the surface/mirror tests with the cheat-sheet mirrors; update request assertions |
| `tests/engine/steering/test_steering.py` | update mirrors + request assertion + banner sample |
| `tests/engine/test_healer.py` | rename `page_api` → `cheat_sheet` in the `FakeProvider` signature/recording (lines ~137, ~152); the loop/classification suites otherwise untouched |
| `tests/engine/polling/*` | untouched |
| `tests/llm/test_request.py`, `test_provider.py`, `test_openai_provider.py`, `test_anthropic_provider.py` | rename `page_api` → `cheat_sheet`; block-order assertions |
| `tests/test_scenario.py` | handle-shaped `FakePage`; the `run_on_page` suite; `FakeProvider`: `page_api` → `cheat_sheet` |
| `tests/test_executor.py`, `tests/test_integration.py` | handle-shaped fakes; add a count-forms step through the full cycle; every `FakeProvider` carrying `page_api` (executor ~198/236/274, integration ~116/198) renames it → `cheat_sheet` |

---

### Positive Tests

#### `test_run_executes_the_action_wholly_inside_the_worker_thread`

**Setup**: `worker = PlaywrightWorker(); worker.start()`; `page = PageFacade(fake_raw_page, fake_context)`; `page._worker = worker`; no router.

**Input**: `seen = {}`; `def action(p): seen["thread"] = threading.get_ident(); seen["page"] = p; return "done"`; `page.run(action)`.

**Trace**:
```
page.run(action)
  → unit() built (action + no-op resolver)
  → PlaywrightWorker.run(unit)          # queue.put(task); task.done.wait()
    → _pump: task.fn() == unit()
      → action(fake_raw_page)            # INSIDE the pump thread
        side effect: seen["thread"] = pump thread id; seen["page"] = fake_raw_page
    → task.result = None-or-"done"; task.done.set()
  → returns "done"
```

**Assertions**:
```
result == "done"
seen["thread"] != threading.get_ident()          # not the calling thread
seen["thread"] == the pump thread ident (captured via a second page.run(lambda p: threading.get_ident()))
seen["page"] is fake_raw_page                    # the genuine object crossed, no wrapper
worker._thread.is_alive()                        # the boundary survives
```

**Sufficiency**: pins the load-bearing ADR invariant — the whole unit runs on the worker thread; a regression to caller-thread execution (e.g. someone inlining `action(self._page)`) breaks the IPython/Jupyter guarantee silently otherwise.

#### `test_run_passes_the_genuine_page_and_returns_the_outcome_as_is`

**Setup**: hand-built `PageFacade(raw, ctx)` (no worker → inline unit); `raw = object()`.

**Input**: `page.run(lambda p: (p, 42)[1])` plus an identity-capturing action.

**Trace**:
```
page.run(action) → unit() → action(raw)  →  receives the exact raw object; returns 42
```

**Assertions**: `page.run(...) == 42`; the identity captured inside the action `is raw`.

**Sufficiency**: proves the handle passes the genuine object with no wrapper — the core of the facade demotion.

#### `test_run_resolves_unclaimed_dialogs_at_the_unit_boundary__accept`

**Setup**: hand-built handle; `router = _DialogRouter(accept_dialogs=True)`; `page._router = router`; `dialog = FakeRawDialog("delete?")`; `router.record(dialog)` (simulating the event firing during the action).

**Input**: `page.run(lambda p: "ok")`.

**Trace**:
```
unit() → action → "ok" → finally: router.resolve_pending()
  → dialog.accept()  (accept_dialogs True) → dialog.state == "accepted"
→ returns "ok"
```

**Assertions**: result `"ok"`; `dialog.state == "accepted"`; `router._pending == []`.

**Sufficiency**: the resolver-of-last-resort contract with the setting on — prevents regression to immediate in-handler resolution (which double-handles stock captures).

#### `test_run_resolves_unclaimed_dialogs_at_the_unit_boundary__dismiss`

Same as above with `accept_dialogs=False`; assert `dialog.state == "dismissed"`. **Sufficiency**: the explicit-dismiss default (restoring the Playwright default when a listener disabled auto-dismiss).

#### `test_run_never_touches_a_dialog_the_step_captured`

**Setup**: hand-built handle; `router = _DialogRouter(accept_dialogs=True)`; `page._router = router`; `dialog = FakeRawDialog()`.

**Input**: an action that first `router.record(dialog)` then resolves it itself (`dialog.accept()`), returning "green".

**Trace**:
```
unit() → action: record + accept (state "accepted") → finally: resolve_pending()
  → dialog.accept() raises Error("Cannot accept dialog which is already handled!")
  → guard matches "already handled" → skipped silently
→ returns "green"; no exception
```

**Assertions**: result `"green"`; `dialog.state == "accepted"` (unchanged — resolved exactly once); no exception raised.

**Sufficiency**: the exact double-handling hazard the task names ("a stock `page.expect_event("dialog")` in generated code arms nothing the router sees") — this is the test that keeps `accept_dialogs` honest under stock captures.

#### `test_run_resolver_failure_never_masks_the_action_outcome`

**Setup**: hand-built handle + router; a `FakeRawDialog` whose `accept()` raises `Error("Target closed")` (not already-handled); `router.record(dialog)`.

**Input**: an action raising `AssertionError("videos not listed")`, run through `page.run`.

**Trace**:
```
unit() → action raises AssertionError → finally: resolve_pending()
  → dialog.accept() raises Error("Target closed") → WARNING logged, swallowed
→ the AssertionError propagates to the caller
```

**Assertions**: `pytest.raises(AssertionError, match="videos not listed")`; exactly one WARNING record (`dialog resolution failed`) on the `prettyplay` logger via `caplog`.

**Sufficiency**: the step's failure must reach classification unchanged — a resolver crash replacing it would corrupt the failure taxonomy.

#### `test_run_step_code_runs_the_whole_step_through_the_run_primitive`

**Setup**: `RecordingHandle` — a minimal PageFacade stand-in: `run(action)` records `("run", action)` and returns `action(self._raw)` where `self._raw` is a sentinel; no worker.

**Input**: `code = "from playwright.sync_api import expect\n\n\ndef step(page):\n    assert page is not None\n"` (module-level import compiles on the calling thread).

**Trace**:
```
run_step_code(code, handle)
  → exec(compile(code, "<prettyplay-step>", "exec"), namespace)   # calling thread
  → fn = namespace["step"]
  → handle.run(fn)   →  recorded; fn(sentinel_raw) executed → assert passes
```

**Assertions**: `handle.calls == [("run", fn)]` (one run call; the fn identity is `namespace["step"]`); no exception.

**Sufficiency**: pins the new boundary — compile/resolve outside, the whole call inside the run primitive; also proves the generated import header executes without a Playwright session.

#### `test_run_step_code_propagates_step_failures_untouched`

**Setup**: as above.

**Input**: `code = "def step(page):\n    assert page.count() > 1\n"` with an action-independent failing assert (`def step(page): raise AssertionError("boom")` variant also covered).

**Trace**: `exec` → resolve → `handle.run(fn)` → `fn` raises → propagates through `run` as-is.

**Assertions**: `pytest.raises(AssertionError, match="boom")`; the caught exception `is` the object recorded raised inside the action (identity preserved).

**Sufficiency**: the engine's classification depends on exception identity/type flowing through the boundary unchanged.

#### `test_generate_request_carries_the_cheat_sheet` (engine)

**Setup**: the existing `FakeProvider` generator fixtures (tmp_path cache, budgets, reporter) with a fake page handle exposing `aria_snapshot`/`screenshot`.

**Input**: `generator.generate(identity, "open the videos page", [], page, window)` with the provider returning green code (`"def step(page):\n    pass\n"`).

**Trace**:
```
generate → _request → page.aria_snapshot() → provider.generate_step_code(prompt=SYSTEM_PROMPT, cheat_sheet=CHEAT_SHEET, …)
  → FakeProvider records kwargs → settle runs green → compliance gate (off) → cache save
```

**Assertions**: `request["cheat_sheet"] == CHEAT_SHEET`; `request["prompt"] == SYSTEM_PROMPT`; `"cheat_sheet" in request and "page_api" not in request`.

**Sufficiency**: the carrier contract — every generation request rides the cheat-sheet; a dropped kwarg would send the model no reference at all.

#### `test_cheat_sheet_mirrors_the_practice` (engine)

**Setup/Input**: read `.goga/usages/prompts/cheatsheet.md` (path resolved as the existing `GENERATION_PROMPT_PRACTICE` constant does for generation.md).

**Trace**: `practice = CHEAT_SHEET_PRACTICE.read_text(encoding="utf-8")`.

**Assertions**: `CHEAT_SHEET == practice` (whole file, verbatim).

**Sufficiency**: the frozen-mirror rule — the listing and the practice change together; a one-sided edit desynchronizes the two engine copies' payload silently otherwise.

#### `test_system_prompt_mirrors_the_generation_practice` (updated, engine)

**Trace**: `practice.split("---", 1)[1].strip() == SYSTEM_PROMPT`.

**Assertions**: the section after the separator equals the constant; spot-asserts the new rule lines: `"Import only from playwright.sync_api"`, `"never call page.close() or context.close()"`, `"expect_event(\"dialog\")"`, `"assert locator.count() > 1"`.

**Sufficiency**: same mirror rule for the rewritten prompt.

#### `test_steering_mirrors_the_practices` (updated, steering)

**Assertions**: `SYSTEM_PROMPT == ENGINE_SYSTEM_PROMPT`; `CHEAT_SHEET == ENGINE_CHEAT_SHEET`; the steering `CHEAT_SHEET` equals the practice file; `cheat_sheet` guidance phrase present ("guidance, never an allowlist" wording per the constant comments).

**Sufficiency**: the two cells' frozen copies must agree — a one-sided edit sends different payloads to the same model.

#### `test_guided_request_carries_the_cheat_sheet` (steering)

**Setup**: existing steering dialog fixtures (stdin-driven, `FakeProvider`).

**Input**: guidance `"use count forms"`; provider returns green code.

**Trace**: `_guided_request → provider.generate_step_code(…, cheat_sheet=STEERING_CHEAT_SHEET, guidance=…)` → bare `run_step_code` (fake handle) → green → gate off → write-back.

**Assertions**: `request["cheat_sheet"] == CHEAT_SHEET`; `"page_api" not in request`; the healed write-back happened.

**Sufficiency**: steering is the second carrier; a stale copy here diverges regeneration from generation.

#### `test_build_fields_places_cheat_sheet_after_scenario_inputs_before_instructions` (llm)

**Setup**: direct `build_fields_text` call.

**Input**: `user_instructions="prefer role locators"`, `step_text="open the videos page"`, `previous_steps=["open the home page"]`, `snapshot="- tree"`, `cheat_sheet="…reference…"`, `existing_code=None`, ….

**Trace**: sections list built in order → joined with `"\n\n"`.

**Assertions**:
```
text.index("STEP:\n") < text.index("PREVIOUS STEPS:\n") < text.index("PAGE SNAPSHOT:\n")
  < text.index("CHEAT SHEET:\n…reference…") < text.index("USER INSTRUCTIONS:\nprefer role locators")
"text.startswith('STEP:')" is True; "PAGE API" not in text
```

**Sufficiency**: the fixed block order is a parity contract asserted on the shared builder — both providers inherit it.

#### `test_run_on_page_delegates_to_the_run_primitive` (root)

**Setup**: `PrettyPlay` built over fakes per the existing scenario fixtures; a `FakeHandle` whose `run(action)` executes `action(fake_raw_page)` and records; force `t._page = fake_handle` (or drive one real fake step first).

**Input**: `t.run_on_page(lambda page: page.route_marker)` where the fake raw page carries `route_marker = "plain-data"`.

**Trace**: `run_on_page → self._page.run(action) → action(fake_raw_page) → returns "plain-data"`.

**Assertions**: result `== "plain-data"`; the fake handle recorded exactly one run unit; the received object `is` the raw fake page.

**Sufficiency**: the escape hatch crosses the same boundary as steps — the ADR's "must cross the worker thread boundary" acceptance item.

#### `test_count_forms_step_runs_green_through_the_full_cycle` (integration)

**Setup**: the existing integration fake stack (executor + generator with `FakeProvider`, handle-shaped fake page).

**Input**: provider returns the motivating step: `"from playwright.sync_api import expect\n\n\ndef step(page):\n    videos = page.get_by_role(\"listitem\")\n    expect(videos.first).to_be_visible()\n    assert videos.count() > 1\n"`; the fake raw page's `get_by_role` returns a fake locator whose `first` / `count()` satisfy the checks; `t.expect("the page shows a list of videos")`.

**Trace**: cache miss → generation (cheat sheet carried) → settle → `run_step_code` → `handle.run(step)` → green → gate off → cached → `on_step_passed`.

**Assertions**: the step passes; the cached code contains `videos.count() > 1`; the handle saw one run unit per execution.

**Sufficiency**: the motivating case of the whole change — the exact step that used to die as a non-pollable `AttributeError` on the facade.

### Negative Tests

#### `test_run_on_page_requires_an_opened_page`

**Setup**: a fresh `PrettyPlay` (no step run).

**Input**: `t.run_on_page(lambda page: None)`.

**Trace**: `self._page is None` → `PrettyplayError` raised before any run call.

**Assertions**: `pytest.raises(PrettyplayError, match="no test page yet")`; message contains "run a step first".

**Sufficiency**: the loud actionable missing-page contract, uniform with `get_screenshot`.

#### `test_run_on_page_propagates_action_exceptions_as_is`

**Setup**: `PrettyPlay` with `t._page = fake_handle` whose `run` re-raises.

**Input**: an action raising `playwright.sync_api.Error("route failed")`.

**Assertions**: the same exception type and message surface at the call site; no `PrettyplayError` wrapping, no fold.

**Sufficiency**: the author must see the real Playwright failure — translation here would hide the actionable cause.

#### `test_step_code_error_fails_the_generation_attempt` (updated existing)

**Input**: provider returns code raising `NameError` inside the step.

**Trace**: settle → `run_step_code` → `handle.run` re-raises → not pollable → retry branch with the formatted error.

**Assertions**: the next request's `error` block carries the `NameError` text; the budget accounting unchanged.

**Sufficiency**: keeps the error-driven regeneration loop healthy — the second line of defense per the ADR.

### Edge Case Tests

#### `test_plain_assert_is_pollable` (driver errors)

**Input**: `is_pollable_failure(AssertionError("assert 1 > 2"))` and a `strict mode violation` AssertionError.

**Assertions**: plain assert → `True`; strict-mode violation → `False`.

**Sufficiency**: the immediate-read assertion forms now sanctioned by the prompt must settle-window exactly like expect-chain failures (task.md: "AssertionError ... behave identically").

#### `test_open_context_registers_the_recording_handler_per_page` (session)

**Setup**: session-level fake: a `DriverSession` with a monkeypatched launch returning a fake browser/worker capturing the `context.on("page", …)` wiring.

**Input**: `session.open_context()`.

**Trace**: `open_isolated` runs → `context.on("page", …)` registered before `new_page()` → the page event fires for the first page → `opened.on("dialog", router.record)` wired.

**Assertions**: exactly one dialog listener on the first page, wired to `router.record`. The before-`new_page` ordering is proven by this very assertion — had the wiring run after `new_page()`, the first page would carry no dialog listener at all (the context page event already fired).

**Sufficiency**: every page registers exactly once, never twice — the precondition for exactly-once resolution.

#### `test_run_without_a_router_is_a_plain_pass_through`

**Setup**: hand-built handle, `_router = None`.

**Input**: `page.run(lambda p: 7)`.

**Assertions**: returns `7`; no error, no pending state consulted.

**Sufficiency**: hand-built handles (all engine/steering tests) have no session router — the run primitive must not require one.

#### `test_resolver_clears_pending_for_the_next_unit`

**Setup**: router with one pending dialog; two consecutive `page.run` calls.

**Input**: first run resolves the dialog; second run with a freshly recorded dialog.

**Assertions**: after run 1, `_pending == []`; run 2 resolves only its own dialog; dialog 1's `accept_calls == 1` — never double-resolved across units.

**Sufficiency**: the pending list must not leak between units — a stale queue would dismiss a dialog a later step's capture was about to claim.

---

## Additional Instructions for the Implementation Agent

- **Series constraint**: one coherent change — driver → llm → engine → steering → root → tests → docs → cache purge → example. No staged deprecation, no compatibility shims, no leftover mirrors.
- **Leftover sweep at series end** (plan checklist 5): `grep -r "PAGE_API_SURFACE\|page_api\|LocatorFacade\|DialogFacade\|FrameFacade\|expect_dialog\|PAGE API" prettyplay/ tests/ docs/ README.md example/` returns nothing (except historical `.goga/history/` documents, which stay untouched).
- **Frozen-mirror rule**: `SYSTEM_PROMPT` changes only together with `.goga/usages/prompts/generation.md` (section after `---`); `CHEAT_SHEET` only together with `.goga/usages/prompts/cheatsheet.md` (whole file); steering's copies stay byte-identical to the engine's.
- **Do not** add runtime gates for imports or stateful actions (prompt rules only); **do not** touch `prettyplay/engine/polling`, `is_pollable_failure` logic, the failure taxonomy, or the settle semantics.
- **Cache purge**: delete `example/.prettyplay/cache/**`; regenerate `example/tests/test_youtube.py` (already staged as untracked) and the google/yandex examples on the new engine. If the environment lacks LLM keys or network (or a working venv — the case here), record the fact and accept the unit level, per the task acceptance rule.
- **Verification**: `goga lint` (0 errors), `goga schema` (driver: three types, two usages; no `facade` dependency edges), `pytest tests/ -x`, `ruff`. Recreate the venv first if the interpreter symlinks are broken (macOS-created venv on a Linux host).
- **Docs land with the code** (same series): the rewritten `driver-facade.md`, `writing-steps.md`, `configuration.md`, `interactive-steering.md` sample sync, README wording — the acceptance criteria name the driver-facade docs explicitly.
