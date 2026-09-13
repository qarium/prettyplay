# Plan: `better-healt-2` — Driver locator narrowing & prompt strategy split

## Purpose

Implement the «better-healt-2» change end-to-end: the six Playwright locator-narrowing members (`first`, `last`, `nth`, `filter`, `or_`, `and_`) join `LocatorFacade` in the driver cell as full facade members, and the locating-strategy rules move wholly out of the generation system prompt — both engine cells' frozen constants (`SYSTEM_PROMPT`, `PAGE_API_SURFACE`) are brought back to mirror parity with the already-updated practices.

After implementation:

- Generated and hand-written step code can narrow a multi-match locator positionally (`first`/`last`/`nth`), by content (`filter`), and through combinators (`or_`/`and_`) — every member marshals through the driver thread and returns a full `LocatorFacade`, so chains compose and the boundary stays closed.
- The incident idiom `page.get_by_text("Welcome back").first.expect_visible()` runs green as a first generation candidate (the surface listing carries the member; the facade no longer raises `AttributeError`).
- Locating strategy reaches the model only through the project's `generation_prompt` user instructions; the system prompt carries mechanics only.
- `docs/reference/driver-facade.md` is at parity with the `facade` practice.

The most important gaps between contract and code: the entire narrowing family is missing from `prettyplay/driver/page.py`; both constants in `prettyplay/engine/generator.py` and `prettyplay/engine/steering/steering.py` still carry the two removed strategy lines and 19 element rows (the practices now have 25) — the existing mirror tests are red against the apply-stage-updated practices.

Strategy: TDD per cell, leaf first — driver, then engine (mirrors + the incident integration test), then steering (mirrors + new mirror tests), then the public doc. Contracts and practices are already materialized and **read-only**.

## Context

### Contract Surface

**Entity: `LocatorFacade`** (changed — six new members)
- Type: `class` (Entity)
- Declared `location`: `page.py` (cell `prettyplay/driver`)
- Facade obligation: importable from `prettyplay.driver` (already exported via `__all__` — no facade change)
- Mutations: none
- Added contract Requirement (verbatim): «The narrowing members — first, last, nth, filter, or_ and and_ — run in the driver thread like every facade call and return a full LocatorFacade: chains compose and no raw Playwright object crosses the boundary»
- Properties (new):
  - `first -> LocatorFacade` — «The first match of this locator in document order — the positional narrowing selecting one element among many (see `playwright`).»
  - `last -> LocatorFacade` — «The last match of this locator in document order (see `playwright`).»
- Methods (new, at the head of `methods`):
  - `nth(index: int) -> element: LocatorFacade` — «Select the match at `index` — the positional narrowing. `index`: 0-based position; negative counts from the end (see `playwright`).»
  - `filter(has_text: str, has_not_text: str, has: LocatorFacade | None, has_not: LocatorFacade | None) -> element: LocatorFacade` — «Narrow this locator by element content — the predicates are optional and combine as a logical and (see `playwright`). `has_text`: keep elements whose text contains this string; empty — not applied. `has_not_text`: drop elements whose text contains this string; empty — not applied. `has`: keep elements containing a match of this inner locator; None — not applied. `has_not`: drop elements containing a match of this inner locator; None — not applied. Constraints: The inner locators of `has` and `has_not` are facades — no raw Playwright object crosses the boundary.»
  - `or_(other: LocatorFacade) -> element: LocatorFacade` — «The union locator — matches what this locator or `other` matches (see `playwright`). `other`: the alternative `LocatorFacade`. Requirements: An action or expectation over a composition matching elements of both branches raises the strict-mode violation like any multi-match locator — positional narrowing over the composition is the canonical guard (see `playwright`).»
  - `and_(other: LocatorFacade) -> element: LocatorFacade` — «The intersection locator — matches elements matching both this locator and `other` (see `playwright`). `other`: the intersecting `LocatorFacade`.»
- Semantic requirements from descriptions: parity delegation (pure selector composition), optional-predicate filtering («empty — not applied» / «None — not applied»), logical-and combination, union/intersection composition, strict-mode propagation without facade handling
- Imported dependencies: none new (`configuration` from `prettyplay/config` is untouched — the facade surface is identical in every screen mode)
- Annotation context: cell global annotations (driver-thread marshal, parity principle, excluded capabilities, no raw objects) → entity Requirements/Constraints → per-member descriptions above
- Pinned design decisions: **P1** — `first`/`last` are properties (upstream shape; the incident idiom `…get_by_text(…).first.expect_visible()` stays literal); **P2** — `filter` mirrors string arguments only, no regex, no `visible` predicate; **P3** — `or_` keeps pure upstream union semantics, no facade-side strict-mode handling, no error wrapping — the guard `.or_(…).first` is documentation, not code

**Entity: `StepGenerator`** (unchanged code paths; frozen constants change)
- Type: `class` (Entity)
- Declared `location`: `generator.py` (cell `prettyplay/engine`)
- No method/property changes. Two module constants change content:
  - `SYSTEM_PROMPT` — loses the two locating-strategy rules, gains one assertion-mechanics rule inserted immediately after the assertion-sentence rule.
  - `PAGE_API_SURFACE` — six element rows at the head of the element section.
- Contract context (engine CODEMANIFEST, verbatim): «The page API surface listing sent to the provider mirrors `facade` from Imports exactly — the listing and the practice change together.» / «The system prompt sent to the provider is the frozen local mirror of `system_prompt` — the mirror and the practice change together.»

**Entity: `StepSteering`** (unchanged code paths; frozen constants change)
- Type: `class` (Entity)
- Declared `location`: `steering.py` (cell `prettyplay/engine/steering`)
- No method/property changes. Its own cell-owned local copies of `SYSTEM_PROMPT` and `PAGE_API_SURFACE` receive the identical edits.
- Contract context (steering CODEMANIFEST, verbatim): «The system prompt sent to the provider is the frozen local mirror of `system_prompt` — the mirror and the practice change together.» / «The page API surface listing sent to the provider is the frozen local mirror of `facade` from Imports — the listing and the practice change together.»

### Re-exports

- None added. `prettyplay.driver.__all__` already exports `LocatorFacade`; the engine and steering facades are unchanged. No `->Name: {}` blocks are touched by this change.

### Usages Context

- `conventions` (`.goga/usages/conventions.md`) — Python code-writing rules: relative imports, Google docstrings, blank-line block separation, pytest structure. Applied in every coding task (Tasks 1–4); Task 5 is documentation-only. Tests mirror `tests/<package>/test_<module>.py`.
- `playwright` (`.goga/usages/cooks/playwright.md`) — the parity source of truth. The section «Locator narrowing — positional, content, combinators» (already on disk) defines: `first`/`last` properties, `nth(index)` 0-based with negative-from-the-end, `filter` optional keyword predicates, `or_`/`and_` combinators, strict mode with positional narrowing as the canonical guard.
- `system_prompt` (`.goga/usages/prompts/generation.md`) — the single source of the generation system prompt; the section after `---` is the prompt text. Already updated (strategy rules out, assertion-mechanics rule in). Both cells' constants must equal it.
- `classification_prompt` (inline, engine CODEMANIFEST) — unchanged by this change; classification requests never carry the generation instructions. Explicit non-goal of the engine task.

### Imported Usages

- `facade` from `prettyplay/driver` (imported by engine and steering) — source path `prettyplay/driver/.usages/facade.md`. Already updated by the apply stage: 25 element rows (six narrowing rows at the head), the example block «Narrowing a locator — positional, content, combinators», the strict-mode rule. This file is the parity target of both `PAGE_API_SURFACE` constants and of the public doc.
- `configuration` from `prettyplay/config` (imported by driver; source path `prettyplay/config/.usages/configuration.md`) — screen/browser-group settings. Untouched by narrowing: the facade surface is identical in every mode.

### Local Usages

- None to create or update. The apply stage already materialized every planned practice file:
  - `prettyplay/driver/.usages/facade.md` — current (six rows, example, strict-mode rule); additions needed: none.
  - `prettyplay/engine/.usages/generation.md` — current (the two narrowing idioms sit in the fixed-form list); additions needed: none.
  - `prettyplay/engine/steering/.usages/` — intentionally absent (plan decision: the steering practice documents the REPL surface and lists no step-code idioms); nothing to create.
  - `.goga/usages/cooks/playwright.md` — the «Locator narrowing» section already on disk.

### External Dependencies

- Playwright 1.62.0 (installed) — verified upstream shapes: `first`/`last` are `@property` returning a new `Locator`; `nth(index: int)` returns a `Locator`; `filter(*, has_text, has_not_text, has, has_not, visible)` is keyword-only with `None` defaults (the facade mirrors all parameters except `visible` — decision P2); `or_(locator)`/`and_(locator)` return a `Locator` and raise `Error("Locators must belong to the same frame.")` on a frame mismatch.
- pytest + ruff (project `[test]` extra); `goga` CLI for lint.

### Interaction Diagram and Data Flows (from the design, verbatim)

```
 generated step code (fixed form, one arg: page)
        │
        ▼
  PageFacade.get_by_role("row")          ── driver thread ──► raw Locator
        │ _wrap_locator                                  ◄── LocatorFacade(_worker)
        ▼
  LocatorFacade.first / .last / .nth(i) / .filter(...) / .or_(other) / .and_(other)
        │ self._call(...)  ── driver thread ──► upstream locator.first / .nth(i) / .filter(**applied)
        │                                      / .or_(other._locator) / .and_(other._locator)
        │ _wrap_locator    ◄── raw Locator (chained composition)
        ▼
  LocatorFacade.click / .expect_*        (auto-wait at resolution time — untouched)
        │
        ├── AssertionError (failed expectation / strict mode violation) ──► settle window
        │       └─ "strict mode violation" → is_pollable_failure() = False → classification
        └── PlaywrightError (timeout / element state / frame mismatch) ──► pollable map

  engine:  StepGenerator._request() ── prompt=SYSTEM_PROMPT, page_api=PAGE_API_SURFACE ──► LLMProvider
  steering: StepSteering._guided_request() ── same inputs, its own local copies ──► LLMProvider
  mirrors: .goga/usages/prompts/generation.md ──(SYSTEM_PROMPT)──► generator.py, steering.py
           prettyplay/driver/.usages/facade.md ──(PAGE_API_SURFACE)──► generator.py, steering.py
           prettyplay/driver/.usages/facade.md ──(public mirror)──► docs/reference/driver-facade.md
```

**Data flows**:

1. **Narrowing flow (new)**: step code calls a locating method on `PageFacade`/`FrameFacade` → the raw `Locator` is wrapped into a `LocatorFacade` carrying `_worker` → a narrowing member marshals one callable into the driver thread, where the upstream composition runs (`first`/`last`/`nth`/`filter`/`or_`/`and_` are pure selector compositions — no browser I/O, but the marshal is uniform with every facade call) → the resulting raw `Locator` is wrapped into a fresh `LocatorFacade` with the same `_worker` → chains compose; the eventual action/expectation resolves with Playwright's own auto-wait.
2. **Prompt flow (changed content, unchanged path)**: `SYSTEM_PROMPT`/`PAGE_API_SURFACE` are module constants read at import → every `generate`/`regenerate` request (`StepGenerator._request`) and every guided request (`StepSteering._guided_request`) passes them to `LLMProvider.generate_step_code(prompt=..., page_api=...)` → the provider renders them as the system message and the PAGE API block. No runtime read of `.goga/` ever happens — the constants are frozen local mirrors, changed only together with the practices.
3. **Failure flow (unchanged, narrowing-relevant)**: an action or expectation over a locator resolving to several elements — including an `or_`-composition with both branches present — raises the strict-mode violation; `is_pollable_failure` recognizes `"strict mode violation"` in the text and returns False (deterministic) → the failure goes straight to classification, never to the settle window.

**Entity dependencies**: `prettyplay/driver` ← `prettyplay/config` (untouched). Leaf of the touched cluster; implement first. `prettyplay/engine` ← `prettyplay/driver` (`PageFacade` type + `facade` practice) and the project practice `system_prompt`. `prettyplay/engine/steering` ← `prettyplay/driver`, `prettyplay/engine` (`run_step_code`). Import edges unchanged (schema-verified); no cycles.

## Facts

- The three CODEMANIFESTs already carry the change (apply stage): the driver manifest declares the six members and the narrowing Requirement; engine and steering manifests carry the frozen-mirror annotation lines. `goga lint`: 10 cells, 0 errors. CODEMANIFEST files are read-only for the implementation agent.
- The practice files are already updated on disk (git-modified, uncommitted): `generation.md` (assertion-mechanics rule at line 33, strategy rules absent), `facade.md` (25 element rows), engine `generation.md` (two narrowing idioms), the cook (narrowing section).
- Consequently the suite is **red right now** at the mirror points: `test_system_prompt_mirrors_the_generation_practice` (constant ≠ practice) and `test_page_api_surface_mirrors_facade_practice` (asserts 19 element rows; the practice has 25). The TDD «contract tests fail first» state already exists live for the engine task.
- `LocatorFacade` (`prettyplay/driver/page.py:456`) currently has actions and expectations only — no narrowing members, no `_wrap_locator` of its own. `PageFacade._wrap_locator` (`page.py:412`) is the established wrap pattern (construct facade, inherit `_worker`).
- `LocatorFacade._call` (`page.py:479`) is the uniform marshal: runs the callable inline when `_worker is None` (hand-built test handles), else `self._worker.run(fn)`.
- Both constants still carry the two locating-strategy lines (`generator.py:46-47`, steering equivalents) and 19 element rows — out of sync with the updated practices.
- The engine and steering copies are deliberately independent (cell-owned frozen mirrors); no runtime read of `.goga/` ever happens.
- `is_pollable_failure` (`prettyplay/driver/errors.py`) recognizes `"strict mode violation"` → `False`; the frame-mismatch `Error` text matches no pollable pattern → `False`. `errors.py` needs no change.
- `format_step_error` (`prettyplay/engine/text.py`) renders a non-assertion error as `f"{type(exc).__name__}: {text}"` → the frame-mismatch render is exactly `Error: Locators must belong to the same frame.`
- `tests/driver/test_page.py` already imports `Error` from `playwright.sync_api` (line 12); expectations in driver tests ride the patched `prettyplay.driver.page.expect` (the pattern of `test_failed_expectation_raises_assertion_error`, line 1250).
- `StepCache` exposes no save recording — cache assertions use the load-back idiom (`fixture.cache.load(identity)`).
- The repo `.venv` is a darwin/Python-3.14 build (`pyvenv.cfg` points at `/opt/homebrew`). On any other host it cannot execute — recreate it (`python3 -m venv .venv && .venv/bin/pip install -e ".[test]"`) before running validation commands. `requires-python = ">=3.10"`; ruff `target-version = "py310"`, `line-length = 120`.
- `docs/reference/driver-facade.md` is outdated relative to `facade.md`: no narrowing rows in «Surface — element», no narrowing example, no strict-mode rule, no narrowing idioms in the fixed-form paragraph.
- `LocatorFacade` is already in `prettyplay.driver.__all__`; `__init__.py` exports are untouched.

## Gap Analysis

- Missing contract entities: the entire narrowing family — `LocatorFacade.first`, `.last`, `.nth`, `.filter`, `.or_`, `.and_` (plus the private `_wrap_locator` helper they need).
- Missing facade exposure: none (`LocatorFacade` already exported).
- Incorrect `location` placement: none — everything lands in the declared `page.py` / `generator.py` / `steering.py`.
- API mismatches: `SYSTEM_PROMPT` in both cells (two strategy lines present; assertion-mechanics rule missing) and `PAGE_API_SURFACE` in both cells (19 element rows vs 25 practice rows). These are mirror inequalities, not signature changes.
- Behavioral mismatches: none — no loop, dialog, or classification logic changes; the change is additive at the facade and editorial at the mirrors.
- Existing code that can be reused: `LocatorFacade._call` (uniform marshal), `PageFacade._wrap_locator` pattern, driver-test `FakeLocator`/`RecordingWorker`/patched-`expect` idioms, engine-test `StubProvider`/`GeneratorFixture`/`facade_surface_rows`, steering-test fixtures.
- Test coverage gaps: engine test-local `FakeLocator`/`FakePage` lack narrowing passthroughs (the incident code would `AttributeError`); steering has no mirror-equality tests; no test anywhere covers the frame-mismatch error; two engine tests anchor on lines the edit removes (`test_generation_prompt_carries_the_scroll_rule` anchors on the removed locating line; `test_system_prompt_carries_the_new_rules` asserts the removed lines).
- Missing visibility in workspace or git: the apply-stage practice/contract edits are uncommitted; the docs page lags the practice.

---

## Tasks

> **Package ordering rule**: coding tasks for each package are completed before starting the next. Within each coding task, contract tests are written first (TDD workflow).

### Task 1: `LocatorFacade` narrowing family — six members in `prettyplay/driver/page.py` (TDD coding)

Implement the six locator-narrowing members of `LocatorFacade` (contract entity above, `location: page.py`): properties `first`/`last`, methods `nth`/`filter`/`or_`/`and_`, each one marshaled delegation returning a wrapped full `LocatorFacade`. The Playwright `Locator` narrowing family is pure selector composition (no browser I/O), but the marshal is uniform with every facade call — the added contract Requirement pins it. `PageFacade` and its wrap pattern are untouched; `__init__.py` exports are untouched (no infrastructure work — this task is pure TDD coding inside the existing class).

**Verified upstream shapes** (Playwright 1.62.0, `playwright/_impl/_locator.py`, `playwright/sync_api/_generated.py`): `first`/`last` are `@property` returning `Locator`; `nth(index: int)` returns `Locator`; `filter` is keyword-only `(*, has_text, has_not_text, has, has_not, visible)` with `None` defaults — mirror all but `visible` (P2); `or_(locator)`/`and_(locator)` return `Locator` and raise `Error("Locators must belong to the same frame.")` on a frame mismatch.

**Usages relevant to this task:**
- `playwright`: the cook section «Locator narrowing — positional, content, combinators» is the parity source — `first`/`last` properties, `nth(index)` 0-based with negative from the end, `filter` optional keyword predicates combining as a logical and, `or_`/`and_` combinators, strict mode with positional narrowing as the canonical guard.
- `conventions`: Google docstrings (``Args``/``Returns``), relative imports, the file's established voice; constraint notes in the prose (e.g. the `or_` strict-mode requirement).
- `configuration` from Imports (`prettyplay/config/.usages/configuration.md`): untouched by narrowing — the facade surface is identical in every screen mode; no setting reaches the new members.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

**Algorithm** (per member; `wrap` = build `LocatorFacade(raw)`, inherit `_worker` — the `PageFacade._wrap_locator` pattern, as a private method on `LocatorFacade`):

```
first / last (property):
1. run in the driver thread: access the upstream locator property
   → raw narrowed Locator (pure selector composition: nth=0 / nth=-1)
2. wrap the raw result, inherit the worker
   → LocatorFacade

nth(index):
1. run in the driver thread: call upstream nth(index) — the int passes verbatim
   → raw Locator (nth={index}; negative counts from the end)
2. wrap → LocatorFacade

filter(has_text="", has_not_text="", has=None, has_not=None)  [keyword-only]:
1. build the applied-predicate kwargs inside ONE driver-thread closure:
   - has_text non-empty        → kwargs["has_text"] = has_text
   - has_not_text non-empty    → kwargs["has_not_text"] = has_not_text
   - has is not None          → kwargs["has"] = has._locator      (unwrap at the boundary)
   - has_not is not None      → kwargs["has_not"] = has_not._locator
2. run in the driver thread: call upstream filter(**kwargs)
   → raw Locator (predicates combine as a logical and; empty call — identity)
3. wrap → LocatorFacade

or_(other) / and_(other):
1. run in the driver thread: call upstream or_/and_ with other._locator
   → raw Locator (internal:or= / internal:and= composition)
2. wrap → LocatorFacade
```

**Verified trace — `LocatorFacade.first`** (property; `last` symmetric):
1. **Input**: generated step code evaluates `element.first` on a `LocatorFacade` produced by a locating method.
2. **Step**: the property getter runs `self._call(lambda: self._locator.first)` — the access of the upstream property happens inside the driver-thread callable → checkpoint: marshaling uniform with every facade call (contract Requirement); the upstream getter performs a pure selector composition (`selector >> nth=0`), no browser I/O, so the marshal is safe and side-effect-free. **Passed.**
3. **Step**: the raw `Locator` result passes to `LocatorFacade._wrap_locator` → checkpoint: type flow `Locator` → `LocatorFacade`, `_worker` inherited so the next chain link marshals to the same thread. **Passed.**
4. **Output**: a full `LocatorFacade`; the incident idiom `page.get_by_text("Welcome back").first.expect_visible()` stays literal (decision P1). Auto-wait is preserved by construction — waiting lives in Playwright's locator resolution at action/expectation time, not in composition.

**Verified trace — `LocatorFacade.nth(index)`**:
1. **Input**: `element.nth(2)` (or a negative `element.nth(-1)`).
2. **Step**: `self._call(lambda: self._locator.nth(index))` → checkpoint: `index: int` passes through verbatim; upstream encodes `nth={index}` in the selector, where negative counts from the end — matches the contract annotation. **Passed.**
3. **Step**: wrap the raw result → checkpoint: same as `first`. **Passed.**
4. **Output**: `LocatorFacade` of the positional pick; `nth(0)` ≡ `first`, `nth(-1)` ≡ `last`.

**Verified trace — `LocatorFacade.filter(has_text, has_not_text, has, has_not)`**:
1. **Input**: `element.filter(has_text="Product X")` — keyword call (the practice row and upstream are keyword-shaped).
2. **Step**: the method builds the applied-predicate set inside one marshaled closure: `has_text`/`has_not_text` enter only when non-empty, `has`/`has_not` enter only when not `None`, and the inner facades unwrap to their raw locators (`has._locator`) exactly at the boundary → checkpoint: contract semantics «empty — not applied» / «None — not applied» map to absent upstream kwargs; the Constraint «inner locators are facades — no raw Playwright object crosses the boundary» holds because the unwrap happens inside the driver-thread callable, the same pattern as `drag_to(target)`. **Passed.**
3. **Step**: upstream `filter(**applied)` composes the content predicate into the selector chain; predicates combine as a logical and → checkpoint: upstream semantics match the contract. String arguments only — regex and `visible` stay unmirrored (decision P2; consistent with the facade's string-only `expect_text`). **Passed.**
4. **Step**: wrap the raw result → **Passed.**
5. **Output**: `LocatorFacade` narrowed by content; `filter()` with no applied predicate is an identity narrowing (upstream behavior).

**Verified trace — `LocatorFacade.or_(other)`** (`and_` symmetric)**:
1. **Input**: `element.or_(other)` where `other` is a `LocatorFacade` built from the same page/frame facade.
2. **Step**: `self._call(lambda: self._locator.or_(other._locator))` → checkpoint: the raw inner locator passes inside the marshaled callable (uniform with `drag_to`); upstream composes `internal:or=` into the selector. **Passed.**
3. **Step** (error path): a frame mismatch between the branches raises upstream `Error("Locators must belong to the same frame.")` → checkpoint: the facade's zero-wrapping policy propagates it untouched; `is_pollable_failure` classifies it as a deterministic `PlaywrightError` (matches no pollable pattern) → classification, never the settle window. **Passed.**
4. **Output**: `LocatorFacade` of the union.

**Errors** (zero-wrapping policy — no facade error handling, P3):
- Upstream `Error("Locators must belong to the same frame.")` from `or_`/`and_` → propagate untouched → `format_step_error` renders `Error: Locators must belong to the same frame.` → not pollable → classification.
- Strict-mode violation on a later action/expectation over a multi-match composition (both `or_` branches present included) → `AssertionError`/`Error` carrying `strict mode violation` → `is_pollable_failure` returns False → classification; the settle window never retries it. **No facade code** — the guard is documented usage (`.first`/`.last`/`.nth`), decision P3.

**Edge cases**:
- `nth(-1)` — negative passes verbatim; upstream selects from the end (≡ `last`).
- `filter()` with every predicate absent — an identity narrowing; upstream returns an equivalent locator.
- Cross-frame `or_`/`and_` (a page locator composed with a frame-scoped one) — upstream raises the frame-mismatch Error; generated code builds locators from one facade, so this is a hand-writing edge only.
- A narrowed-empty result (`first` when nothing matches) — no error at composition; the eventual action/expectation times out or asserts, uniform with every locator.

**Placement** (design instruction): `first`/`last` properties and the private `_wrap_locator` right after `_call`; then `nth`, `filter`, `or_`, `and_` before `click` — mirroring the CODEMANIFEST ordering (locating family first, uniform with `PageFacade`). **`filter` is keyword-only** (`*` in the signature) with defaults `has_text=""`, `has_not_text=""`, `has=None`, `has_not=None` — upstream shape; the DSL signature does not encode keyword-onlyness and the practice row shows keyword usage.

- [x] **Contract tests** (add to `tests/driver/test_page.py`, class `TestPageFacadeContract`; expected to fail at this stage):

  `test_narrowing_surface_matches_contract` — **Setup**: import `LocatorFacade` from `prettyplay.driver`. **Input**: surface list `["first", "last", "nth", "filter", "or_", "and_"]`. **Trace**:
  ```
  for name in surface:
    → hasattr(LocatorFacade, name)            # each member exists on the class
  assert isinstance(getattr(LocatorFacade, "first"), property)   # P1: property shape
  assert isinstance(getattr(LocatorFacade, "last"), property)    # P1: property shape
  for name in ("nth", "filter", "or_", "and_"):
    assert not isinstance(getattr(LocatorFacade, name), property)  # method shape, upstream-parity
  ```
  **Assertions**: all hasattr checks pass; `first`/`last` are property objects (upstream shape), `nth`/`filter`/`or_`/`and_` are plain functions — asserted by the not-isinstance-property loop. **Sufficiency**: pins the P1 property decision — a regression to method-style `first()` (the shape the incident workaround would have needed) fails here.

  `test_narrowing_signatures_and_annotations_match_contract` — **Setup**: `inspect`, `get_type_hints` on `LocatorFacade`. **Input**: the six members. **Trace**:
  ```
  inspect.signature(LocatorFacade.nth).parameters      → ["self", "index"]
  inspect.signature(LocatorFacade.filter).parameters   → ["self", "has_text", "has_not_text", "has", "has_not"]
    parameters["has_text"].default  == ""
    parameters["has_not_text"].default == ""
    parameters["has"].default is None; parameters["has_not"].default is None
    parameters["has_text"].kind is inspect.Parameter.KEYWORD_ONLY        # upstream shape
  inspect.signature(LocatorFacade.or_).parameters      → ["self", "other"]
  inspect.signature(LocatorFacade.and_).parameters     → ["self", "other"]
  get_type_hints: nth["index"] is int, nth["return"] is LocatorFacade
    filter["has_text"] is str, filter["has"] == Optional[LocatorFacade]  # equality — holds on 3.10+ for both `X | None` and `Optional[X]`
    filter["return"] is LocatorFacade
    or_["other"] is LocatorFacade, or_["return"] is LocatorFacade (and_ symmetric)
    get_type_hints(LocatorFacade.first.fget)["return"] is LocatorFacade (last symmetric)
  ```
  **Assertions**: every line above holds. **Sufficiency**: the contract signatures are the API — parameter order, defaults, keyword-onlyness and types are what generated code compiles against.
- [x] **Interface verification (red first)**: run the two new tests against the unchanged class — `.venv/bin/pytest tests/driver/test_page.py -k narrowing -x` — both fail (`AttributeError`/missing members); this is the expected TDD state
- [x] **Code**: add private `_wrap_locator` to `LocatorFacade` right after `_call` (construct `LocatorFacade(raw)`, inherit `_worker` — the `PageFacade._wrap_locator` pattern)
- [x] **Code**: add `first` and `last` properties (`self._call(lambda: self._locator.first)` / `...last`, wrap the result) per the algorithm; Google docstrings in the file's voice
- [x] **Code**: add `nth(index: int) -> LocatorFacade` — `self._call(lambda: self._locator.nth(index))`, index passes verbatim, wrap
- [x] **Code**: add `filter` keyword-only (`*, has_text: str = "", has_not_text: str = "", has: LocatorFacade | None = None, has_not: LocatorFacade | None = None`) — build the applied kwargs inside ONE driver-thread closure (non-empty strings and non-`None` facades only; unwrap `has._locator`/`has_not._locator` at the boundary), call upstream `filter(**applied)`, wrap
- [x] **Code**: add `or_(other)` / `and_(other)` — `self._call(lambda: self._locator.or_(other._locator))` (symmetric for `and_`), wrap; upstream errors propagate untouched — NO facade-side strict-mode handling, validation, or error wrapping (P3)
- [x] **Interface verification**: `.venv/bin/pytest tests/driver/test_page.py -k narrowing -x` — both contract tests pass
- [x] **Logic tests** (extend the test-local `FakeLocator` in `tests/driver/test_page.py` with the narrowing members — record-and-return-self: `first`/`last` properties recording `("first",)`/`("last",)` and returning `self`; `nth(index)` recording `("nth", index)`; `filter(**kwargs)` recording `("filter", kwargs)`; `or_(target)` recording `("or_", target)`; `and_(target)` recording `("and_", target)`; optionally a fake whose `or_` raises the real `Error`):

  `test_first_and_last_delegate_and_wrap` (`TestPageFacadeLogic`) — **Setup**: `fake = FakeLocator(); element = LocatorFacade(fake)` (hand-built, `_worker=None` → inline). **Input**: `element.first`, then `.last` on the result. **Trace**:
  ```
  element.first
    → LocatorFacade._call(lambda: fake.first)     # inline — no worker
      → FakeLocator.first property records ("first",), returns fake
    → _wrap_locator(fake) → LocatorFacade (fresh facade object, _worker inherited)
  result.last
    → records ("last",) on the same fake
  ```
  **Assertions**: `fake.calls == [("first",), ("last",)]` (delegation order, single recording chain); `isinstance(result, LocatorFacade)`; `result is not element`; `result._locator is fake`; `result._worker is element._worker`. **Sufficiency**: proves the property delegates and the wrapped result is a full facade — the chain-composition invariant of the added Requirement.

  `test_nth_delegates_the_index_verbatim` — **Setup**: as above. **Input**: `element.nth(2)`; separately `element.nth(-1)`. **Trace**: `element.nth(2)` → `_call(lambda: fake.nth(2))` → fake records `("nth", 2)`, returns fake → wrapped; `element.nth(-1)` → fake records `("nth", -1)`. **Assertions**: `fake.calls == [("nth", 2)]` (fresh fake per case); negative passes through unchanged — the facade adds no clamping or rewriting. **Sufficiency**: guards the 0-based/negative-from-the-end contract — a sign-flip or clamp in the facade would break positional picks silently.

  `test_filter_applies_only_the_given_predicates` — **Setup**: `FakeLocator.filter(**kwargs)` records `("filter", kwargs)` and returns self; `other = LocatorFacade(fake_other)`. **Input**: four calls — `filter(has_text="Product X")`; `filter(has_not_text="Draft")`; `filter(has=other)`; `filter(has_text="X", has_not_text="Y", has=other, has_not=other)`; plus `filter()`. **Trace**:
  ```
  element.filter(has_text="Product X")
    → closure builds {"has_text": "Product X"} — the empty/default predicates stay absent
    → fake records ("filter", {"has_text": "Product X"})
  element.filter(has=other)
    → fake records ("filter", {"has": fake_other})     # the RAW inner locator, unwrapped at the boundary
  element.filter()
    → fake records ("filter", {})                        # identity narrowing
  ```
  **Assertions**: `("filter", {"has_text": "Product X"}) in fake.calls`; `("filter", {"has": fake_other}) in fake.calls` (boundary-internal unwrap); `("filter", {"has_text": "X", "has_not_text": "Y", "has": fake_other, "has_not": fake_other}) in fake.calls`; `("filter", {}) in fake.calls`; every result is a `LocatorFacade` wrapping fake. **Sufficiency**: the «empty — not applied / None — not applied» semantics and the inner-facade unwrap constraint are the whole content contract of `filter`; passing raw kwargs blindly would push `""`/`None` upstream and change matching.

  `test_or_and_delegate_the_raw_locator` — **Setup**: as above, `other` a second facade over `fake_other`. **Input**: `element.or_(other)`; `element.and_(other)`. **Trace**: `element.or_(other)` → `_call(lambda: fake.or_(fake_other))` → fake records `("or_", fake_other)` → wrapped; `element.and_(other)` → fake records `("and_", fake_other)` → wrapped. **Assertions**: recorded tuples match; results are fresh `LocatorFacade`s with the worker inherited. **Sufficiency**: the combinator contract is exactly «compose the two locators» — recording proves the inner facade unwraps inside the boundary, never outside.

  `test_narrowing_members_marshal_through_the_driver_thread` — **Setup**: `worker = RecordingWorker()`; `element = LocatorFacade(fake); element._worker = worker`; `other` similarly bound. **Input**: one call of each member: `.first`, `.last`, `.nth(1)`, `.filter(has_text="x")`, `.or_(other)`, `.and_(other)`. **Trace**: each member → `self._call(fn)` → `worker.run(fn)` (RecordingWorker executes and counts); 6 members → 6 worker.run invocations. **Assertions**: `len(worker.calls) == 6` (one `run` per member); results still wrap correctly. **Sufficiency**: the added Requirement — narrowing runs in the driver thread like every facade call — is the boundary invariant; a direct `self._locator.first` without `_call` would pass every logic test and break only here.

  `test_or_composition_green_and_both_present_strict_mode` (`tests/driver/test_page.py`) — **Setup**: hand-built `element = LocatorFacade(fake)`; `other = LocatorFacade(fake_other)`; the driver-test `FakeLocator` has no `expect_visible` — expectations ride the patched `prettyplay.driver.page.expect` (the pattern of `test_failed_expectation_raises_assertion_error`): case A — the patch returns a recording FakeExpectation whose `to_be_visible()` returns green; case B — the patch returns an expectation whose `to_be_visible()` raises `AssertionError("strict mode violation: locator resolved to 2 elements: …")`. **Input**: A: `element.or_(other).first.expect_visible()`; B: `element.or_(other).expect_visible()`. **Trace**:
  ```
  A: or_ composes ("or_", fake_other) → wrap → .first records ("first",) → wrap → patched expect → to_be_visible green
  B: or_ composes → wrap → patched expect → to_be_visible raises AssertionError("strict mode violation …")
    → pytest.raises captures it
    → is_pollable_failure(exc) → "strict mode violation" in text → False (not absorbed by any settle window)
  ```
  **Assertions**: A: `fake.calls == [("or_", fake_other), ("first",)]` — the canonical guard composes over the union; no raise. B: raises `AssertionError`; `"strict mode violation" in str(exc)`; `is_pollable_failure(exc) is False`. **Sufficiency**: decision P3 — `or_` keeps pure union semantics; the both-present case must surface the strict-mode violation (deterministic, classification-bound) and the positional narrowing must be the documented green path. Prevents anyone "fixing" the strict-mode case inside the facade.

  `test_or_frame_mismatch_propagates_untouched` (`tests/driver/test_page.py`) — **Setup**: `fake = FakeLocator()` whose `or_(target)` raises the real `Error("Locators must belong to the same frame.")` (`playwright.sync_api.Error`, already imported by the test file); `element = LocatorFacade(fake)`; `other = LocatorFacade(fake_other)` over a plain fake. Imports for the assertions: `is_pollable_failure` from `prettyplay.driver`, `format_step_error` from `prettyplay.engine` (the engine-owned render the Errors section names). **Input**: `element.or_(other)`. **Trace**:
  ```
  element.or_(other)
    → self._call(lambda: fake.or_(fake_other))   # one marshal, the unwrap stays inside the boundary
    → fake.or_ raises Error("Locators must belong to the same frame.")
    → no worker → _call does not swallow; the facade adds no wrapping (zero-wrapping, P3)
    → pytest.raises(Error) captures the original object
    → is_pollable_failure(exc): no "strict mode violation" in the text; not an AssertionError;
      isinstance(exc, PlaywrightError) is True but the text matches no timeout and no pollable pattern → False
  ```
  **Assertions**:
  ```
  with pytest.raises(Error, match="Locators must belong to the same frame."):
      element.or_(other)
  type(exc).__name__ == "Error"                     # untouched type — no wrapper added
  is_pollable_failure(exc) is False                 # deterministic → classification, never the settle window
  format_step_error(exc) == "Error: Locators must belong to the same frame."  # the typed render of the Errors section
  ```
  **Sufficiency**: pins the only eagerly-raised composition error of the family with three invariants at once — untouched propagation (P3 zero-wrapping), non-pollable classification (the frame-mismatch path of the pollable map), and the exact `format_step_error` render. Regression: wrapping/translating the error or accidentally adding it to the pollable map fails these asserts loudly (verified: no existing test covers "same frame" anywhere in the suite).
- [x] **Debugging**: `.venv/bin/pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: facade accessibility (`LocatorFacade` importable from `prettyplay.driver`; `__all__` unchanged), API shape (the two contract tests green), no raw Playwright object crosses the boundary (every narrowing member wraps before returning)
- [x] **Lint**: `.venv/bin/ruff check prettyplay/ tests/` — fix formatting, apply decomposition if necessary

### Task 2: The frozen mirrors in `prettyplay/engine/generator.py` — `SYSTEM_PROMPT` and `PAGE_API_SURFACE` (TDD coding)

Bring the two engine constants back to frozen-mirror parity with the already-updated practices. This is an editorial edit, no runtime logic: `StepGenerator._request` (`generator.py:583`) passes `prompt=SYSTEM_PROMPT, page_api=PAGE_API_SURFACE` to `LLMProvider.generate_step_code` — unchanged. The contract lines (engine CODEMANIFEST): «The page API surface listing sent to the provider mirrors `facade` from Imports exactly — the listing and the practice change together.» / «The system prompt sent to the provider is the frozen local mirror of `system_prompt` — the mirror and the practice change together.» The two existing mirror tests are the contract tests — they are red right now (the practices moved ahead of the constants).

**Usages relevant to this task:**
- `system_prompt` (`.goga/usages/prompts/generation.md`): the section after `---` is the prompt text — the constant must equal it verbatim.
- `facade` from Imports (`prettyplay/driver/.usages/facade.md`): the element table (25 rows) is the parity target of `PAGE_API_SURFACE`.
- `classification_prompt`: explicit non-goal — the classification system prompt is untouched; classification requests never carry the generation instructions.
- `conventions`: constant docstring comments (the frozen-mirror statements above the constants) stay as-is.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

**Algorithm** (an editorial edit, no runtime logic):

```
SYSTEM_PROMPT (generator.py AND steering.py, identical edits):
1. delete the line "- Locating by role and accessible name is preferred; …"
2. delete the line "- get_by_test_id and locator(selector) exist for elements without accessible names — …"
3. insert after "- For an assertion sentence end with an expectation call; …":
   "- Assertions happen only through the expectation calls of the facade — never a Python assert on a locator, never SDK-style state reads"
   → the prompt equals .goga/usages/prompts/generation.md after "---", verbatim

PAGE_API_SURFACE (both files, identical edits):
1. insert six rows at the head of the element section (before element.click(button)),
   purposes mirroring the facade practice table verbatim; the or_ row carries the
   strict-mode guard hint
   → every element row of the practice is present in the constant
```

The exact lines to delete from `SYSTEM_PROMPT` (`generator.py:46-47`):
```
- Locating by role and accessible name is preferred; by visible text next; by label or placeholder for form fields
- get_by_test_id and locator(selector) exist for elements without accessible names — the accessibility-first priority stands unless USER INSTRUCTIONS say otherwise
```
The exact line to insert immediately after `- For an assertion sentence end with an expectation call; for an action sentence perform the actions`:
```
- Assertions happen only through the expectation calls of the facade — never a Python assert on a locator, never SDK-style state reads
```

The six `PAGE_API_SURFACE` rows to insert at the head of the element section (before `element.click(button)`), purposes verbatim from the `facade` practice element table, em-dash separator, call column aligned to the section's column width where the row fits:
```
element.first                         — the first match — positional narrowing
element.last                          — the last match — positional narrowing
element.nth(index)                    — the match at a 0-based index; negative counts from the end
element.filter(has_text=..., has_not_text=..., has=..., has_not=...) — narrow by content — all predicates optional
element.or_(other)                    — union locator — matches either; when both branches may match, compose positional narrowing (first, last, nth) to satisfy strict mode
element.and_(other)                   — intersection locator — matches both
```
Keep `page.close` out (the standing exclusion).

**Verified trace — `SYSTEM_PROMPT`** (engine; steering symmetric):
1. **Input**: none — a module constant defined once at import of `generator.py`.
2. **Step**: `StepGenerator._request` passes `prompt=SYSTEM_PROMPT` to `LLMProvider.generate_step_code` → checkpoint: the constant equals the practice file's section after `---` verbatim; the two locating-strategy lines are gone, the assertion-mechanics line sits directly after the assertion-sentence rule; no other rule moved (surviving mechanics: fixed form, dialog/popup capture, iframe, scroll, no sleeps, RECOMMENDATION/USER GUIDANCE, STEP precision, output-only-code-block). **Passed.**
3. **Output**: the provider's system message. The change travels to both cells together — each holds its own local copy (the engine/steering annotations state the discipline).

Prompt-contract split: locating strategy now reaches the model only through the project's `generation_prompt` user instructions (USER INSTRUCTIONS block) — the system prompt no longer competes with them.

**Verified trace — `PAGE_API_SURFACE`** (engine; steering symmetric):
1. **Input**: none — module constant.
2. **Step**: `_request` passes `page_api=PAGE_API_SURFACE` → checkpoint: the element section gains six rows at its head mirroring the `facade` practice table verbatim (call column + purpose, em-dash separator); the `element.or_(other)` row carries the strict-mode guard hint — the plan's designated carrier of the guard guidance in the listing. **Passed.**
3. **Output**: the PAGE API block of every request — the model sees the narrowing calls as on-surface, which is what turns the incident idiom from an off-surface `AttributeError` into a green first candidate.

Mirror equality is mechanically enforced by `test_system_prompt_mirrors_the_generation_practice` (existing) and `test_page_api_surface_mirrors_facade_practice` (existing, count moves 19 → 25); members-exist by `test_page_api_surface_members_exist_on_the_facades` (regex-matches every line to an owning facade class — the six new lines assert `hasattr(LocatorFacade, ...)`; `first`/`last` satisfy `hasattr` as properties — green after Task 1).

- [ ] **Contract tests** (in `tests/engine/test_generator.py`, class `TestPromptConstants`; the two existing mirror tests are already red — keep them as the contract enforcement):
  - Rewrite `test_system_prompt_carries_the_new_rules` → `test_system_prompt_strategy_rules_are_gone`. **Setup**: import `SYSTEM_PROMPT` from `prettyplay.engine.generator`. **Input**: the constant text. **Trace**:
    ```
    assert "- Assertions happen only through the expectation calls of the facade — never a Python assert on a locator, never SDK-style state reads" in SYSTEM_PROMPT
    assert "Locating by role and accessible name is preferred" not in SYSTEM_PROMPT
    assert "accessibility-first priority" not in SYSTEM_PROMPT
    surviving mechanics present: dialogs / popups / iframe / scroll / no fixed delays rules, fixed form, output-only-code-block
    ```
    **Assertions**: as above — the new rule in, both removed rules out, the surviving sentence of each kept rule intact. **Sufficiency**: the prompt-strategy split is editorial — only string-level assertions pin it; without them a mirror edit could silently reintroduce a strategy line or drop a mechanics rule.
  - Rewrite `test_generation_prompt_carries_the_scroll_rule` → `test_generation_prompt_rule_order_survives_the_edit` (the old test anchors on the removed locating line and would raise `ValueError` after the edit). **Setup**: `SYSTEM_PROMPT`. **Input**: index anchors. **Trace**:
    ```
    assertion  = SYSTEM_PROMPT.index("- Assertions happen only through")   # replaces the removed locating anchor
    dialogs    = SYSTEM_PROMPT.index("- Dialogs: when the step verifies")
    scroll     = SYSTEM_PROMPT.index("- Scroll abilities exist")
    no_delays  = SYSTEM_PROMPT.index("- No fixed delays")
    assert assertion < dialogs < scroll < no_delays
    ```
    **Assertions**: the new rule sits exactly after the assertion-sentence rule, before the dialogs rule; the surviving mechanics keep their order. **Sufficiency**: the rewritten anchors pin the insertion point the plan specifies.
  - Extend `test_page_api_surface_lists_every_facade_call` with the six call strings and `test_page_api_surface_mirrors_facade_practice` count 19 → 25 (edge-case tests, see Logic step below).
- [ ] **Interface verification (red first)**: `.venv/bin/pytest tests/engine/test_generator.py -k "TestPromptConstants" -x` — the rewritten tests fail against the old constant (TDD red; the two existing mirror tests are already red)
- [ ] **Code**: apply the `SYSTEM_PROMPT` edit in `prettyplay/engine/generator.py` per the algorithm (two deletions, one insertion) — the result equals `.goga/usages/prompts/generation.md` after `---` verbatim; the docstring comment above the constant (the frozen-mirror statement) stays as-is
- [ ] **Code**: insert the six element rows at the head of the element section of `PAGE_API_SURFACE` in `prettyplay/engine/generator.py` per the exact rows above; `page.close` stays out
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/test_generator.py -k "TestPromptConstants" -x` — all constant tests pass, including `test_system_prompt_mirrors_the_generation_practice` (green again)
- [ ] **Logic tests** (edge-case extensions, class `TestPromptConstants`):

  `test_page_api_surface_covers_the_narrowing_family` — **Setup**: existing `TestPromptConstants`. **Input**: `PAGE_API_SURFACE`. **Trace**:
  ```
  extend test_page_api_surface_lists_every_facade_call with:
    "element.first", "element.last", "element.nth(index)",
    "element.filter(has_text=..., has_not_text=..., has=..., has_not=...)",
    "element.or_(other)", "element.and_(other)"
  update test_page_api_surface_mirrors_facade_practice:
    assert len(element_rows) == 25            # 19 + the six narrowing rows
  ```
  **Assertions**: each call string in `PAGE_API_SURFACE`; the practice table extraction counts 25 element rows; `"page.close" not in PAGE_API_SURFACE` still holds. **Sufficiency**: the listing is the model's only view of the surface — a missing row reproduces the incident even with the facade implemented.
- [ ] **Debugging**: `.venv/bin/pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: mirror equality (constant == practice after `---`; every element row of the practice present in the constant), no runtime read of `.goga/` (constants stay module-level), the request path (`_request`) untouched, `classification_prompt` untouched
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 3: Integration tests — the narrowing incident through the generation loop (engine package)

Verify the incident class end-to-end through the generation engine: the narrowing idiom generated as a first candidate runs green because the facade carries the member and the surface listing carries the row. This is the cross-entity scenario AC2 — driver surface (`first` from Task 1) + engine mirrors (Task 2) + the generation loop (settle, cache). No production code changes in this task; the engine test-local fakes gain narrowing passthroughs.

**Usages relevant to this task:**
- `conventions`: unit style — hand-built fakes, no mocks at logic level; `StubProvider` (scripted answers + recorded requests), `GeneratorFixture` (config/cache/budgets/reporter over `tmp_path`).
- `facade` from Imports: the fixed-form narrowing idioms (`page.get_by_role("row").first.expect_text("Paid")`, `page.get_by_role("listitem").filter(has_text="Product X").expect_visible()`) — the code shape under test.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

**Data flow under test (from the design, verbatim)**:

1. **Narrowing flow**: step code calls a locating method on `PageFacade`/`FrameFacade` → the raw `Locator` is wrapped into a `LocatorFacade` carrying `_worker` → a narrowing member marshals one callable into the driver thread, where the upstream composition runs (`first`/`last`/`nth`/`filter`/`or_`/`and_` are pure selector compositions — no browser I/O, but the marshal is uniform with every facade call) → the resulting raw `Locator` is wrapped into a fresh `LocatorFacade` with the same `_worker` → chains compose; the eventual action/expectation resolves with Playwright's own auto-wait.
2. **Prompt flow**: `SYSTEM_PROMPT`/`PAGE_API_SURFACE` are module constants read at import → every `generate`/`regenerate` request (`StepGenerator._request`) passes them to `LLMProvider.generate_step_code(prompt=..., page_api=...)` → the provider renders them as the system message and the PAGE API block. No runtime read of `.goga/` ever happens.

- [ ] **Test fakes extension**: extend the engine test-local `FakeLocator`/`FakePage` in `tests/engine/test_generator.py` with the narrowing members (record-and-return-self): `FakeLocator` gains `first` (property returning a green-expectation `FakeLocator`), and `FakePage.get_by_text` continues to return it — the AC2 code path `page.get_by_text("Welcome back").first.expect_visible()` must run without `AttributeError` and stay green when `assertion_message is None`
- [ ] **Integration test**: add `test_incident_narrowing_candidate_runs_green` (class `TestStepGeneratorLogic`). **Setup**: `GeneratorFixture(tmp_path, StubProvider([NARROWING_CODE]), limits=(3, 3))` where `NARROWING_CODE = "def step(page) -> None:\n    page.get_by_text('Welcome back').first.expect_visible()\n"`; the fixture's `FakePage`/`FakeLocator` extended with the narrowing members (record-and-return-self) and a green `expect_visible`. **Input**: `generator.generate(identity, "the «Welcome back» message appears", [], page, window)`. **Trace**:
  ```
  generate → budgets.try_generation ok → on_generation_started
    → _request: snapshot, SYSTEM_PROMPT, PAGE_API_SURFACE → provider.generate_step_code
    → StubProvider records the request, returns NARROWING_CODE
    → settle(run_step_code, NARROWING_CODE, page, window)
      → run_step_code compiles the module, resolves step(), calls step(page)
        → page.get_by_text("Welcome back") → FakeLocator
        → .first → narrowing member present — no AttributeError
        → .expect_visible() → green (no raise)
    → _store → CachedStep(code=NARROWING_CODE) → cache.save
  ```
  **Assertions**:
  ```
  result.code == NARROWING_CODE
  len(provider.calls) == 1                      # first candidate green — zero retries
  "element.first" in provider.calls[0]["page_api"]   # the surface listed the member (on-surface)
  loaded = fixture.cache.load(identity)         # StepCache has no save recording — load back
  loaded is not None and loaded.code.rstrip("\n") == NARROWING_CODE.rstrip("\n")  # serializer appends \n
  ```
  **Sufficiency**: the incident class itself — before the change, `.first` raised `AttributeError` on the real facade and the loop burned retries on off-surface code; this test pins the narrowing idiom as a green first candidate with the surface listing carrying the member.
- [ ] **Run validation**: `.venv/bin/pytest tests/engine/test_generator.py -x` — all engine tests green
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 4: The frozen mirrors in `prettyplay/engine/steering/steering.py` + steering mirror tests (TDD coding)

Apply the identical constant edits to the steering cell's own local copies and close the AC4 coverage gap: only the engine had mirror-equality coverage before — steering holds independent copies by design, so a one-sided edit would leave the dialog steering the model with a stale prompt silently. No steering dialog logic changes (`StepSteering._guided_request` at `steering.py:348` passes `prompt=SYSTEM_PROMPT, page_api=PAGE_API_SURFACE` — unchanged).

**Usages relevant to this task:**
- `system_prompt`: the single source; the steering constant must equal the practice section after `---` verbatim (and the engine copy).
- `facade` from Imports: the 25-row element table is the parity target of the steering `PAGE_API_SURFACE`.
- `conventions`: tests mirror `tests/engine/steering/test_steering.py`; the repo-file read pattern is `Path(__file__).resolve().parents[…]` as in the engine tests.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

The algorithm is an editorial edit, no runtime logic — the identical edits Task 2 applies to `generator.py`, applied to the steering cell's own local copies:

```
SYSTEM_PROMPT (steering.py):
1. delete the line "- Locating by role and accessible name is preferred; by visible text next; by label or placeholder for form fields"
2. delete the line "- get_by_test_id and locator(selector) exist for elements without accessible names — the accessibility-first priority stands unless USER INSTRUCTIONS say otherwise"
3. insert after "- For an assertion sentence end with an expectation call; for an action sentence perform the actions":
   "- Assertions happen only through the expectation calls of the facade — never a Python assert on a locator, never SDK-style state reads"
   → the prompt equals .goga/usages/prompts/generation.md after "---", verbatim

PAGE_API_SURFACE (steering.py):
1. insert six rows at the head of the element section (before element.click(button)),
   purposes mirroring the facade practice table verbatim; the or_ row carries the
   strict-mode guard hint
   → every element row of the practice is present in the constant
```

The six `PAGE_API_SURFACE` rows (identical to Task 2), purposes verbatim from the `facade` practice element table, em-dash separator, call column aligned to the section's column width where the row fits:
```
element.first                         — the first match — positional narrowing
element.last                          — the last match — positional narrowing
element.nth(index)                    — the match at a 0-based index; negative counts from the end
element.filter(has_text=..., has_not_text=..., has=..., has_not=...) — narrow by content — all predicates optional
element.or_(other)                    — union locator — matches either; when both branches may match, compose positional narrowing (first, last, nth) to satisfy strict mode
element.and_(other)                   — intersection locator — matches both
```
Keep `page.close` out (the standing exclusion).

The verified trace is the Task 2 trace with «steering symmetric»: `StepSteering._guided_request` passes the steering-local `SYSTEM_PROMPT`/`PAGE_API_SURFACE` to `LLMProvider.generate_step_code`; the steering copies equal the practice (and the engine copies). The steering cell contract lines (verbatim): «The system prompt sent to the provider is the frozen local mirror of `system_prompt` — the mirror and the practice change together.» / «The page API surface listing sent to the provider is the frozen local mirror of `facade` from Imports — the listing and the practice change together.»

- [ ] **Contract tests**: add `test_steering_mirrors_the_practices` to `tests/engine/steering/test_steering.py` (new). **Setup**: read `.goga/usages/prompts/generation.md` and `prettyplay/driver/.usages/facade.md` from the repo (the `Path(__file__).resolve().parents[…]` pattern of the engine tests; a local copy of the row-extraction helper `facade_surface_rows`). **Input**: steering `SYSTEM_PROMPT`, steering `PAGE_API_SURFACE`. **Trace**:
  ```
  practice = read generation.md → practice.split("---", 1)[1].strip()
  assert practice == steering SYSTEM_PROMPT
  element_rows = regex-extract the facade practice element table
  for row in element_rows: assert row.split("(", 1)[0] in steering PAGE_API_SURFACE
  assert steering SYSTEM_PROMPT == engine SYSTEM_PROMPT          # the two frozen copies agree
  assert steering PAGE_API_SURFACE == engine PAGE_API_SURFACE
  ```
  **Assertions**: the steering cell's own local copies equal the practices (and the engine copies) — closing the AC4 gap: only the engine had mirror-equality coverage before. **Sufficiency**: steering holds independent copies by design; without a local mirror test a one-sided edit would leave the dialog steering the model with a stale prompt silently.
- [ ] **Interface verification (red first)**: `.venv/bin/pytest tests/engine/steering/test_steering.py -k mirrors -x` — the new test fails against the still-old steering constants (TDD red)
- [ ] **Code**: apply the identical `SYSTEM_PROMPT` edit (two deletions, one insertion) to `prettyplay/engine/steering/steering.py` — the local copy equals the practice after `---` verbatim and the engine constant; the docstring comment above the constant (the frozen-mirror statement, «A local copy of the engine constant, not an import») stays as-is
- [ ] **Code**: insert the same six element rows at the head of the element section of the steering `PAGE_API_SURFACE`; `page.close` stays out
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/steering/test_steering.py -x` — the mirror test and the whole steering suite pass
- [ ] **Logic tests**: covered by `test_steering_mirrors_the_practices` (equality against practice, per-row membership, engine-parity) — an editorial constant has no further behavioral surface; the steering dialog logic tests are untouched and stay green
- [ ] **Debugging**: `.venv/bin/pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: steering constants == practices == engine constants; `_guided_request` path untouched; no runtime read of `.goga/`; the steering CODEMANIFEST untouched
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 5: `docs/reference/driver-facade.md` — public doc parity (infrastructure)

Bring the public documentation page to parity with the updated `facade` practice (`prettyplay/driver/.usages/facade.md`): the page is the public mirror of the practice and currently lags it (no narrowing rows, no narrowing example, no strict-mode rule, no narrowing idioms in the fixed-form paragraph). Documentation-only task — no production code, no nav changes.

**Usages relevant to this task:**
- `facade` (`prettyplay/driver/.usages/facade.md`): the parity source — the doc mirrors its tables, examples and rules in the doc's own style (backticked calls).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If the documentation does not match the contract, fix the documentation — never fix the contract.**

- [ ] Add the six element rows to the «Surface — element» table of `docs/reference/driver-facade.md` (backticked calls in the doc's style), at the head of the table, purposes from the practice verbatim: `element.first`, `element.last`, `element.nth(index)`, `element.filter(has_text=..., has_not_text=..., has=..., has_not=...)`, `element.or_(other)` (with the strict-mode guard hint), `element.and_(other)`
- [ ] Add the example block «Narrowing a locator — positional, content, combinators» after the «Locating without accessible names» block, mirroring the practice example (`.first.expect_text("Paid")`, `.last.expect_visible()`, `.nth(2).expect_text("Shipped")`, `.filter(has_text="Product X").expect_visible()`, `.and_(...)`, the `or_` guard comment)
- [ ] Add the strict-mode rule after the auto-wait bullet in «Rules», mirroring the practice rule: a locator resolving to several elements fails an action or expectation with the strict-mode violation — narrow positionally (`first`, `last`, `nth`); over an `or_` composition the positional narrowing is the canonical guard when both branches may match
- [ ] Extend the fixed-form paragraph («The fixed form of generated code») with the two narrowing idioms: `` `page.get_by_role("row").first.expect_text("Paid")` ``, `` `page.get_by_role("listitem").filter(has_text="Product X").expect_visible()` ``
- [ ] No nav changes (`mkdocs.yml` untouched); no other sections of the page change
- [ ] Verify parity: `grep -c "^| \`element\." docs/reference/driver-facade.md` → 25; the example block, the rule and the two idioms present — `.venv/bin/python - <<'EOF'` check or manual verification that every element row of `prettyplay/driver/.usages/facade.md` appears in the doc table (mod backticks) and that no other table changed
- [ ] Lint (docs scope): `.venv/bin/ruff check prettyplay/ tests/` stays clean (no code touched); `goga lint` — 10 cells, 0 errors

---

## Validation Commands

- `.venv/bin/pytest tests/ -x`: Run all tests (AC5 — the unchanged suites stay green: taxonomy, pollable map, healing, budgets, steering, cache; any ripple into classification/healing/budgets means an unplanned behavior change)
- `.venv/bin/pytest tests/driver/test_page.py -x`: Driver cell tests (contract, logic, marshaling, error paths)
- `.venv/bin/pytest tests/engine/test_generator.py tests/engine/steering/test_steering.py -x`: Engine + steering tests (mirrors, incident, dialog)
- `.venv/bin/ruff check prettyplay/ tests/`: Lint check
- `.venv/bin/python -c "from prettyplay.driver import LocatorFacade; from prettyplay.engine import StepGenerator; from prettyplay.engine.steering import StepSteering; assert hasattr(LocatorFacade, 'first') and hasattr(LocatorFacade, 'nth')"`: Facade accessibility and narrowing members present
- `goga lint`: Contracts stay clean (10 cells, 0 errors; CODEMANIFESTs untouched)

If the repo `.venv` does not match the execution host (it is a darwin/Python-3.14 build), recreate it first: `python3 -m venv .venv && .venv/bin/pip install -e ".[test]"`.

---

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location` — the six `LocatorFacade` members in `prettyplay/driver/page.py`; the two constants edited in `prettyplay/engine/generator.py` and `prettyplay/engine/steering/steering.py`
- [ ] Every contract entity is accessible from the facade — `LocatorFacade` importable from `prettyplay.driver` (unchanged `__all__`)
- [ ] Properties and methods match the declared API — `first`/`last` as properties; `nth(index: int)`; keyword-only `filter(has_text, has_not_text, has, has_not)` with the declared defaults and types; `or_(other)`/`and_(other)`
- [ ] Descriptions are reflected in behavior — optional-predicate filtering, verbatim index pass-through, union/intersection composition, zero-wrapping error propagation, driver-thread marshal returning a full `LocatorFacade`
- [ ] Contract dependencies are met — no new Import edges; `configuration` untouched; the frozen-mirror disciplines held (constants == practices in both cells)
- [ ] Re-exports are accessible from the facade — no re-export changes (none planned)
- [ ] Every coding task followed the TDD workflow (contract tests → code → verification → logic tests → debugging → re-verification → lint)
- [ ] Contract tests and logic tests cover facade, API, and behavior within each coding task — 15 test scenarios planned (Task 1: 9; Task 2: 4 rewrites/extensions; Task 3: 1 integration; Task 4: 1 new mirror test)
- [ ] Integration tests exist where cross-entity scenarios require them — the narrowing incident through the generation loop (Task 3)
- [ ] No package boundary was expanded — no new cells, no new interfaces at cell level, no excluded capabilities added (no route/evaluate/CDP/clock/HAR/tracing/raw input)
- [ ] `CODEMANIFEST` files were not modified (contract is read-only) — contracts already materialized by the apply stage
- [ ] All validation commands pass — full suite green, ruff clean, `goga lint` 0 errors
- [ ] Every Usages entry is mentioned in at least one task — `conventions` (Tasks 1–4; Task 5 is documentation-only), `playwright` (Task 1), `system_prompt` (Tasks 2, 4), `classification_prompt` (Task 2, non-goal), `facade` from Imports (Tasks 2, 3, 4, 5), `configuration` from Imports (Task 1 context, untouched)
