# Design Document: `better-healt-2`

Topic: **Driver locator narrowing & prompt strategy split** — locator narrowing joins the driver mirror; locating strategy moves wholly to user instructions.
Source plan: `.goga/history/2026/better-healt-2/arch.md`. Contracts materialized by the apply stage; this document specifies the implementation.

---

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/driver/CODEMANIFEST`: `LocatorFacade` — one added Requirement line (the narrowing members marshal through the driver thread and return a full `LocatorFacade`), a new `properties` block (`first`, `last`), four new methods at the head of `methods` (`nth`, `filter`, `or_`, `and_`). All other types, the header and the footer unchanged.
- `prettyplay/engine/CODEMANIFEST`: one added global annotation line — the `system_prompt` frozen-mirror discipline.
- `prettyplay/engine/steering/CODEMANIFEST`: two added global annotation lines — the `system_prompt` and `facade` frozen-mirror disciplines.

### New Entities

- None at the contract level. Six new members inside the existing `LocatorFacade` (see below); no new cells, no new types, no new Import edges.

### Changed Entities

- `LocatorFacade` (`prettyplay/driver/page.py`) — gains the narrowing family:
  - `first -> LocatorFacade` (property) — first match in document order.
  - `last -> LocatorFacade` (property) — last match in document order.
  - `nth(index: int) -> element: LocatorFacade` — 0-based positional pick, negative counts from the end.
  - `filter(has_text: str, has_not_text: str, has: LocatorFacade | None, has_not: LocatorFacade | None) -> element: LocatorFacade` — content narrowing; predicates optional, combine as a logical and; string arguments only (no regex), no `visible` predicate — pinned decision P2.
  - `or_(other: LocatorFacade) -> element: LocatorFacade` — union locator; both-branches-present raises the strict-mode violation like any multi-match locator (guard: positional narrowing over the composition) — pinned decision P3.
  - `and_(other: LocatorFacade) -> element: LocatorFacade` — intersection locator.
- `StepGenerator` (unchanged code paths; frozen constants change):
  - `SYSTEM_PROMPT` in `prettyplay/engine/generator.py` — loses the two locating-strategy rules, gains the assertion-mechanics rule.
  - `PAGE_API_SURFACE` in `prettyplay/engine/generator.py` — six element rows at the head of the element section.
- `StepSteering` (unchanged code paths; frozen constants change): the same two constants in `prettyplay/engine/steering/steering.py`, cell-owned local copies.

### Deleted Entities

- None.

### Usages and Annotations Changes

- `.goga/usages/prompts/generation.md` (project-level practice, `system_prompt`): the two locating-strategy rules removed (locating strategy belongs exclusively to the project's `generation_prompt` user instructions); one assertion-mechanics rule added immediately after the assertion-sentence rule. Everything else verbatim.
- `prettyplay/driver/.usages/facade.md`: six rows at the head of «Surface — element», one example block («Narrowing a locator — positional, content, combinators») after «Locating without accessible names», one rule after the auto-wait rule (strict-mode violation → positional narrowing; over `or_` the canonical guard).
- `prettyplay/engine/.usages/generation.md`: two narrowing idioms inserted into «The fixed form» idiom list (after the locator idioms, before «and alike»).
- `.goga/usages/cooks/playwright.md`: new section «Locator narrowing — positional, content, combinators» with rules (already on disk — the cook was updated ahead of this change).
- `prettyplay/engine/steering/.usages/` — intentionally absent (plan decision: the steering practice documents the REPL surface and lists no step-code idioms).

## Applied Fixes

### Fixed CODEMANIFEST Defects

- None. The Phase 3 audit (DSL syntax, `location` rules, annotation reference resolution, four consistency dimensions) and the Phase 4 re-checks surfaced no defects: `goga lint` reports 10 cells, 0 errors; all backtick references in the added annotations resolve within their document contexts; every practice is referenced from at least one annotation.

---

## Entity Interaction and Data Flow

### Interaction Diagram

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

### Data Flows

1. **Narrowing flow (new)**: step code calls a locating method on `PageFacade`/`FrameFacade` → the raw `Locator` is wrapped into a `LocatorFacade` carrying `_worker` → a narrowing member marshals one callable into the driver thread, where the upstream composition runs (`first`/`last`/`nth`/`filter`/`or_`/`and_` are pure selector compositions — no browser I/O, but the marshal is uniform with every facade call) → the resulting raw `Locator` is wrapped into a fresh `LocatorFacade` with the same `_worker` → chains compose; the eventual action/expectation resolves with Playwright's own auto-wait.
2. **Prompt flow (changed content, unchanged path)**: `SYSTEM_PROMPT`/`PAGE_API_SURFACE` are module constants read at import → every `generate`/`regenerate` request (`StepGenerator._request`) and every guided request (`StepSteering._guided_request`) passes them to `LLMProvider.generate_step_code(prompt=..., page_api=...)` → the provider renders them as the system message and the PAGE API block. No runtime read of `.goga/` ever happens — the constants are frozen local mirrors, changed only together with the practices.
3. **Failure flow (unchanged, narrowing-relevant)**: an action or expectation over a locator resolving to several elements — including an `or_`-composition with both branches present — raises the strict-mode violation; `is_pollable_failure` recognizes `"strict mode violation"` in the text and returns False (deterministic) → the failure goes straight to classification, never to the settle window.

### Entity Dependencies

- `prettyplay/driver` ← `prettyplay/config` (untouched). Leaf of the touched cluster; implement first.
- `prettyplay/engine` ← `prettyplay/driver` (`PageFacade` type + `facade` practice) and the project practice `system_prompt`. Mirrors in `generator.py` change with the practices.
- `prettyplay/engine/steering` ← `prettyplay/driver`, `prettyplay/engine` (`run_step_code`). Its own copies of both mirrors change with the practices.
- Import edges unchanged (schema-verified); no cycles.

---

## Code Stack Trace

Verified against the installed Playwright 1.62.0 source (`playwright/_impl/_locator.py`, `playwright/sync_api/_generated.py`): `first`/`last` are properties returning a new `Locator`; `nth(index: int)` returns a `Locator`; `filter(*, has_text, has_not_text, has, has_not, visible)` is keyword-only with `None` defaults; `or_(locator)`/`and_(locator)` return a `Locator` and raise `Error("Locators must belong to the same frame.")` on a frame mismatch.

### Trace: `LocatorFacade.first` (property; `last` symmetric)

#### Chain
1. **Input**: generated step code evaluates `element.first` on a `LocatorFacade` produced by a locating method.
2. **Step**: the property getter runs `self._call(lambda: self._locator.first)` — the access of the upstream property happens inside the driver thread callable → checkpoint: marshaling uniform with every facade call (contract Requirement); the upstream getter performs a pure selector composition (`selector >> nth=0`), no browser I/O, so the marshal is safe and side-effect-free. **Passed.**
3. **Step**: the raw `Locator` result passes to `LocatorFacade._wrap_locator` → checkpoint: type flow `Locator` → `LocatorFacade`, `_worker` inherited so the next chain link marshals to the same thread. **Passed.**
4. **Output**: a full `LocatorFacade`; the incident idiom `page.get_by_text("Welcome back").first.expect_visible()` stays literal (decision P1). Auto-wait is preserved by construction — waiting lives in Playwright's locator resolution at action/expectation time, not in composition.

#### Checkpoint Summary
- Driver-thread marshal: passed (one `_call` per access).
- Boundary: passed (no raw object crosses — the raw `Locator` exists only inside the marshaled callable and the private wrapper).
- Chain composability: passed (the wrapped result carries `_worker`; every existing action/expectation method applies).

### Trace: `LocatorFacade.nth(index)`

#### Chain
1. **Input**: `element.nth(2)` (or a negative `element.nth(-1)`).
2. **Step**: `self._call(lambda: self._locator.nth(index))` → checkpoint: `index: int` passes through verbatim; upstream encodes `nth={index}` in the selector, where negative counts from the end — matches the contract annotation. **Passed.**
3. **Step**: wrap the raw result → checkpoint: same as `first`. **Passed.**
4. **Output**: `LocatorFacade` of the positional pick; `nth(0)` ≡ `first`, `nth(-1)` ≡ `last`.

#### Checkpoint Summary
- Signature/semantic parity: passed. Boundary and marshaling: passed.

### Trace: `LocatorFacade.filter(has_text, has_not_text, has, has_not)`

#### Chain
1. **Input**: `element.filter(has_text="Product X")` — keyword call (the practice row and upstream are keyword-shaped).
2. **Step**: the method builds the applied-predicate set inside one marshaled closure: `has_text`/`has_not_text` enter only when non-empty, `has`/`has_not` enter only when not `None`, and the inner facades unwrap to their raw locators (`has._locator`) exactly at the boundary → checkpoint: contract semantics «empty — not applied» / «None — not applied» map to absent upstream kwargs; the Constraint «inner locators are facades — no raw Playwright object crosses the boundary» holds because the unwrap happens inside the driver-thread callable, the same pattern as `drag_to(target)`. **Passed.**
3. **Step**: upstream `filter(**applied)` composes the content predicate into the selector chain; predicates combine as a logical and → checkpoint: upstream semantics match the contract. String arguments only — regex and `visible` stay unmirrored (decision P2; consistent with the facade's string-only `expect_text`). **Passed.**
4. **Step**: wrap the raw result → **Passed.**
5. **Output**: `LocatorFacade` narrowed by content; `filter()` with no applied predicate is an identity narrowing (upstream behavior).

#### Checkpoint Summary
- Keyword-only parameters with defaults (upstream shape): passed — the DSL signature is free-form and does not encode keyword-onlyness; the annotation's optionality and the practice's keyword row govern.
- Type flow: `has: LocatorFacade | None` declared and satisfied; unwrap is boundary-internal. Passed.

### Trace: `LocatorFacade.or_(other)` (`and_` symmetric)

#### Chain
1. **Input**: `element.or_(other)` where `other` is a `LocatorFacade` built from the same page/frame facade.
2. **Step**: `self._call(lambda: self._locator.or_(other._locator))` → checkpoint: the raw inner locator passes inside the marshaled callable (uniform with `drag_to`); upstream composes `internal:or=` into the selector. **Passed.**
3. **Step** (error path): a frame mismatch between the branches raises upstream `Error("Locators must belong to the same frame.")` → checkpoint: the facade's zero-wrapping policy propagates it untouched; `is_pollable_failure` classifies it as a deterministic `PlaywrightError` (matches no pollable pattern) → classification, never the settle window. **Passed.**
4. **Output**: `LocatorFacade` of the union.

#### Checkpoint Summary
- Interface contract alignment: passed — the union facade feeds the same actions/expectations; when both branches match, the strict-mode violation raises exactly like any multi-match locator (decision P3: no custom facade behavior; the canonical guard `.or_(...).first` is documentation, not code).

### Trace: `SYSTEM_PROMPT` (engine; steering symmetric)

#### Chain
1. **Input**: none — a module constant defined once at import of `generator.py` (resp. `steering.py`).
2. **Step**: `StepGenerator._request` passes `prompt=SYSTEM_PROMPT` to `LLMProvider.generate_step_code` → checkpoint: the constant equals the practice file's section after `---` verbatim; the two locating-strategy lines are gone, the assertion-mechanics line sits directly after the assertion-sentence rule; no other rule moved (surviving mechanics: fixed form, dialog/popup capture, iframe, scroll, no sleeps, RECOMMENDATION/USER GUIDANCE, STEP precision, output-only-code-block). **Passed.**
3. **Output**: the provider's system message. The change travels to both cells together — each holds its own local copy (the new engine/steering annotations state the discipline).

#### Checkpoint Summary
- Mirror equality: mechanically enforced by `test_system_prompt_mirrors_the_generation_practice` (engine, existing) and new steering mirror tests.
- Prompt-contract split: locating strategy now reaches the model only through the project's `generation_prompt` user instructions (USER INSTRUCTIONS block) — the system prompt no longer competes with them.

### Trace: `PAGE_API_SURFACE` (engine; steering symmetric)

#### Chain
1. **Input**: none — module constant.
2. **Step**: `_request` passes `page_api=PAGE_API_SURFACE` → checkpoint: the element section gains six rows at its head mirroring the `facade` practice table verbatim (call column + purpose, em-dash separator); the `element.or_(other)` row carries the strict-mode guard hint — the plan's designated carrier of the guard guidance in the listing. **Passed.**
3. **Output**: the PAGE API block of every request — the model sees the narrowing calls as on-surface, which is what turns the incident idiom from an off-surface `AttributeError` into a green first candidate.

#### Checkpoint Summary
- Practice ↔ constant parity: enforced by `test_page_api_surface_mirrors_facade_practice` (row extraction over the practice tables) — the element row count assertion moves 19 → 25.
- Members-exist check: `test_page_api_surface_members_exist_on_the_facades` regex-matches every line to an owning facade class — the six new lines assert `hasattr(LocatorFacade, ...)`; `first`/`last` satisfy `hasattr` as properties.

---

## Algorithm Design

### `LocatorFacade` — the narrowing family

**Responsibility**: mirror the Playwright locator-narrowing family as full facade members — every member is one marshaled delegation returning a wrapped `LocatorFacade`, so chains compose and the boundary stays closed.

**Algorithm** (per member; `wrap` = build `LocatorFacade(raw)`, inherit `_worker`):
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

**Errors:**
- Upstream `Error("Locators must belong to the same frame.")` from `or_`/`and_` → propagate untouched (zero-wrapping facade policy) → `format_step_error` renders `Error: Locators must belong to the same frame.` → not pollable → classification.
- Strict-mode violation on a later action/expectation over a multi-match composition (both `or_` branches present included) → `AssertionError`/`Error` carrying `strict mode violation` → `is_pollable_failure` returns False → classification; the settle window never retries it. No facade code — the guard is documented usage (`.first`/`.last`/`.nth`), decision P3.

**Edge Cases:**
- `nth(-1)` — negative passes verbatim; upstream selects from the end (≡ `last`).
- `filter()` with every predicate absent — an identity narrowing; upstream returns an equivalent locator.
- Cross-frame `or_`/`and_` (a page locator composed with a frame-scoped one) — upstream raises the frame-mismatch Error; generated code builds locators from one facade, so this is a hand-writing edge only.
- A narrowed-empty result (`first` when nothing matches) — no error at composition; the eventual action/expectation times out or asserts, uniform with every locator.

### `SYSTEM_PROMPT` / `PAGE_API_SURFACE` — the frozen mirrors

**Responsibility**: cell-owned local copies of the two practices, changed only together with them.

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

**Errors**: none — constants.

**Edge Cases**: none. The docstring comments above the constants (the frozen-mirror statements) stay as-is — they already state the discipline the new annotations encode.

---

## Cross-cutting Concerns

- **Error handling**: unchanged global strategy — the facade adds no wrapping, no translation; upstream exceptions propagate as-is. The strict-mode violation path (not pollable → classification) and the frame-mismatch path (deterministic PlaywrightError → classification) already work with the existing `is_pollable_failure` map — `errors.py` needs no change.
- **Logging**: none at the facade level (established); no new log points. The engine/steering paths log nothing new.
- **Validation**: none added — parity pass-through members add no facade-side validation (the empty-string/None predicate convention is argument filtering, not validation).
- **Caching**: unaffected — the step cache stores code text; narrowing changes no addressing (instructions take no part in the step address, so existing cached steps stay valid).
- **Concurrency**: the driver-thread marshal via `self._call` — strictly sequential, one `_call` per member access, the calling thread never adopts the Playwright event loop. No new shared state (the `_worker` inheritance is the existing pattern).

---

## Usages Analysis

### `conventions` (project practice, both engine cells + driver)
- **What it provides**: Python code-writing rules — relative imports, Google docstrings, blank-line block separation, pytest structure.
- **Where used**: all new facade members, both constant edits, all test additions.
- **Why chosen**: mandatory project-wide.
- **How exactly**: docstrings with Args/Returns; `from __future__ import annotations` already present; tests mirror `tests/<package>/test_<module>.py`.

### `playwright` (project cook, driver)
- **What it provides**: the sync-API lifecycle, locator semantics, auto-wait, strict mode — now including the «Locator narrowing» section (properties `first`/`last`, `nth`, `filter` predicates, `or_`/`and_`, strict-mode guard rule).
- **Where used**: `LocatorFacade` narrowing members (every annotation references it).
- **Why chosen**: the parity source of truth.
- **How exactly**: delegation to `Locator.first/last/nth/filter/or_/and_` as verified in the installed 1.62.0 package.

### `system_prompt` (project practice, engine + steering)
- **What it provides**: the generation system prompt — the single source; both cells render it verbatim.
- **Where used**: `SYSTEM_PROMPT` in `generator.py` and `steering.py`; referenced by the global annotations of both cells.
- **Why chosen**: the prompt-strategy split — content lives here, mirrors change with it.
- **How exactly**: the section after `---` is the prompt text; mirror equality is test-enforced.

### `classification_prompt` (inline practice, engine)
- **What it provides**: the classification system prompt. Unchanged by this change; classification requests never carry the generation instructions.

### Imported Usages
- `facade` from `prettyplay/driver` — engine and steering import it as the single source of the page API surface; the imported file at `prettyplay/driver/.usages/facade.md` is already updated (six rows, example, strict-mode rule). Traceable cross-cell link: the updated practice drives the `PAGE_API_SURFACE` updates in both consumers.
- `configuration` from `prettyplay/config` — driver import; screen/browser-group settings. Untouched by narrowing (the facade surface is identical in every mode).

---

## `.usages/` Update

### Cell: `prettyplay/driver`

#### Existing Files — Consistency
- **`facade.md`** → `prettyplay/driver/.usages/facade.md`
  - Status: current — the apply stage added the six element rows, the narrowing example and the strict-mode rule; API names match the updated CODEMANIFEST member-for-member (verified: `first`, `last`, `nth(index)`, `filter(has_text=…, has_not_text=…, has=…, has_not=…)`, `or_(other)`, `and_(other)`).
  - Additions needed: none.
  - Updates needed: none.
- **`error_kinds.md`** → unchanged by plan; the pollable map semantics cover the new error paths as-is.

### Cell: `prettyplay/engine`

#### Existing Files — Consistency
- **`generation.md`** → `prettyplay/engine/.usages/generation.md`
  - Status: current — the two narrowing idioms sit in the fixed-form list.
  - Additions needed: none. Updates needed: none.
- **`healing.md`** → unchanged (narrowing reaches healing only through regenerated code, not through the healing contract).

### Cell: `prettyplay/engine/steering`

- No `.usages/` directory — by plan decision; nothing to create (narrowing reaches guided regeneration through the `facade` practice carried in the request listing).

### Public documentation (not a cell `.usages/`, listed for completeness)
- **`docs/reference/driver-facade.md`** — outdated relative to the updated `facade` practice; the implementation stage brings it to parity (see Additional Instructions).

---

## Test Stack Trace

### General Setup

- Unit style: hand-built fakes, no mocks at logic level (project conventions). The driver tests construct facades directly over `FakeLocator` (`_worker=None` → inline calls) or over `RecordingWorker` for marshaling checks.
- Engine tests: `StubProvider` (scripted answers + recorded requests), `GeneratorFixture` (config/cache/budgets/reporter over `tmp_path`), `FakePage`/`FakeLocator` boundaries.
- Validation commands: `pytest tests/ -x` (in the venv), `ruff check prettyplay/ tests/`.

### Source File Registry

Files under test: `prettyplay/driver/page.py` (LocatorFacade), `prettyplay/engine/generator.py` (constants + loop), `prettyplay/engine/steering/steering.py` (constants + dialog), plus the practice files read as data by the mirror tests (`.goga/usages/prompts/generation.md`, `prettyplay/driver/.usages/facade.md`).

---

### Positive Tests

#### `test_narrowing_surface_matches_contract` (AC1 — tests/driver/test_page.py, TestPageFacadeContract)

**Setup**: import `LocatorFacade` from `prettyplay.driver`.

**Input**: surface list `["first", "last", "nth", "filter", "or_", "and_"]`.

**Trace**:
```
for name in surface:
  → hasattr(LocatorFacade, name)            # each member exists on the class
assert isinstance(getattr(LocatorFacade, "first"), property)   # P1: property shape
assert isinstance(getattr(LocatorFacade, "last"), property)    # P1: property shape
for name in ("nth", "filter", "or_", "and_"):
  assert not isinstance(getattr(LocatorFacade, name), property)  # method shape, upstream-parity
```

**Assertions**:
```
all hasattr checks pass; first/last are property objects (upstream shape),
nth/filter/or_/and_ are plain functions — asserted by the not-isinstance-property loop
```

**Sufficiency**: pins the P1 property decision — a regression to method-style `first()` (the shape the incident workaround would have needed) fails here.

---

#### `test_narrowing_signatures_and_annotations_match_contract` (AC1)

**Setup**: `inspect`, `get_type_hints` on `LocatorFacade`.

**Input**: the six members.

**Trace**:
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

**Assertions**: every line above holds.

**Sufficiency**: the contract signatures are the API — parameter order, defaults, keyword-onlyness and types are what generated code compiles against.

---

#### `test_first_and_last_delegate_and_wrap` (AC1 — TestPageFacadeLogic)

**Setup**: `fake = FakeLocator(); element = LocatorFacade(fake)` (hand-built, `_worker=None` → inline).

**Input**: `element.first`, then `.last` on the result.

**Trace**:
```
element.first
  → LocatorFacade._call(lambda: fake.first)     # inline — no worker
    → FakeLocator.first property records ("first",), returns fake
  → _wrap_locator(fake) → LocatorFacade (fresh facade object, _worker inherited)
result.last
  → records ("last",) on the same fake
```

**Assertions**:
```
fake.calls == [("first",), ("last",)]           # delegation order, single recording chain
isinstance(result, LocatorFacade); result is not element
result._locator is fake; result._worker is element._worker
```

**Sufficiency**: proves the property delegates and the wrapped result is a full facade — the chain-composition invariant of the added Requirement.

---

#### `test_nth_delegates_the_index_verbatim` (AC1)

**Setup**: as above.

**Input**: `element.nth(2)`; separately `element.nth(-1)`.

**Trace**:
```
element.nth(2) → _call(lambda: fake.nth(2)) → fake records ("nth", 2), returns fake → wrapped
element.nth(-1) → fake records ("nth", -1)
```

**Assertions**: `fake.calls == [("nth", 2)]` (fresh fake per case); negative passes through unchanged — the facade adds no clamping or rewriting.

**Sufficiency**: guards the 0-based/negative-from-the-end contract — a sign-flip or clamp in the facade would break positional picks silently.

---

#### `test_filter_applies_only_the_given_predicates` (AC1)

**Setup**: `FakeLocator.filter(**kwargs)` records `("filter", kwargs)` and returns self; `other = LocatorFacade(fake_other)`.

**Input**: four calls — `filter(has_text="Product X")`; `filter(has_not_text="Draft")`; `filter(has=other)`; `filter(has_text="X", has_not_text="Y", has=other, has_not=other)`; plus `filter()`.

**Trace**:
```
element.filter(has_text="Product X")
  → closure builds {"has_text": "Product X"} — the empty/default predicates stay absent
  → fake records ("filter", {"has_text": "Product X"})
element.filter(has=other)
  → fake records ("filter", {"has": fake_other})     # the RAW inner locator, unwrapped at the boundary
element.filter()
  → fake records ("filter", {})                        # identity narrowing
```

**Assertions**:
```
("filter", {"has_text": "Product X"}) in fake.calls
("filter", {"has": fake_other}) in fake.calls          # boundary-internal unwrap
("filter", {"has_text": "X", "has_not_text": "Y", "has": fake_other, "has_not": fake_other}) in fake.calls
("filter", {}) in fake.calls
every result is a LocatorFacade wrapping fake
```

**Sufficiency**: the «empty — not applied / None — not applied» semantics and the inner-facade unwrap constraint are the whole content contract of `filter`; passing raw kwargs blindly would push `""`/`None` upstream and change matching.

---

#### `test_or_and_delegate_the_raw_locator` (AC1)

**Setup**: as above, `other` a second facade over `fake_other`.

**Input**: `element.or_(other)`; `element.and_(other)`.

**Trace**:
```
element.or_(other)  → _call(lambda: fake.or_(fake_other)) → fake records ("or_", fake_other) → wrapped
element.and_(other) → fake records ("and_", fake_other) → wrapped
```

**Assertions**: recorded tuples match; results are fresh `LocatorFacade`s with the worker inherited.

**Sufficiency**: the combinator contract is exactly «compose the two locators» — recording proves the inner facade unwraps inside the boundary, never outside.

---

#### `test_narrowing_members_marshal_through_the_driver_thread` (AC1)

**Setup**: `worker = RecordingWorker()`; `element = LocatorFacade(fake); element._worker = worker`; `other` similarly bound.

**Input**: one call of each member: `.first`, `.last`, `.nth(1)`, `.filter(has_text="x")`, `.or_(other)`, `.and_(other)`.

**Trace**:
```
each member → self._call(fn) → worker.run(fn)   # RecordingWorker executes and counts
6 members → 6 worker.run invocations
```

**Assertions**: `len(worker.calls) == 6` (one `run` per member — the RecordingWorker records every marshaled callable); results still wrap correctly.

**Sufficiency**: the added Requirement — narrowing runs in the driver thread like every facade call — is the boundary invariant; a direct `self._locator.first` without `_call` would pass every logic test and break only here.

---

#### `test_incident_narrowing_candidate_runs_green` (AC2 — tests/engine/test_generator.py)

**Setup**: `GeneratorFixture(tmp_path, StubProvider([NARROWING_CODE]), limits=(3, 3))` where
`NARROWING_CODE = "def step(page) -> None:\n    page.get_by_text('Welcome back').first.expect_visible()\n"`;
the fixture's `FakePage`/`FakeLocator` extended with the narrowing members (record-and-return-self) and a green `expect_visible`.

**Input**: `generator.generate(identity, "the «Welcome back» message appears", [], page, window)`.

**Trace**:
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

---

#### `test_or_composition_green_and_both_present_strict_mode` (AC3 — tests/driver/test_page.py)

**Setup**: hand-built `element = LocatorFacade(fake)`; `other = LocatorFacade(fake_other)`; the driver-test
`FakeLocator` has no `expect_visible` — expectations ride the patched `prettyplay.driver.page.expect`
(the pattern of `test_failed_expectation_raises_assertion_error`): case A — the patch returns a recording
FakeExpectation whose `to_be_visible()` returns green; case B — the patch returns an expectation whose
`to_be_visible()` raises `AssertionError("strict mode violation: locator resolved to 2 elements: …")`.

**Input**: A: `element.or_(other).first.expect_visible()`; B: `element.or_(other).expect_visible()`.

**Trace**:
```
A: or_ composes ("or_", fake_other) → wrap → .first records ("first",) → wrap → patched expect → to_be_visible green
B: or_ composes → wrap → patched expect → to_be_visible raises AssertionError("strict mode violation …")
  → pytest.raises captures it
  → is_pollable_failure(exc) → "strict mode violation" in text → False (not absorbed by any settle window)
```

**Assertions**:
```
A: fake.calls == [("or_", fake_other), ("first",)] — the canonical guard composes over the union; no raise
B: raises AssertionError; "strict mode violation" in str(exc); is_pollable_failure(exc) is False
```

**Sufficiency**: decision P3 — `or_` keeps pure union semantics; the both-present case must surface the strict-mode violation (deterministic, classification-bound) and the positional narrowing must be the documented green path. Prevents anyone "fixing" the strict-mode case inside the facade.

---

#### `test_or_frame_mismatch_propagates_untouched` (AC3 supplement — tests/driver/test_page.py)

**Setup**: `fake = FakeLocator()` whose `or_(target)` raises the real `Error("Locators must belong to the same frame.")`
(`playwright.sync_api.Error`, already imported by the test file); `element = LocatorFacade(fake)`; `other = LocatorFacade(fake_other)`
over a plain fake. Imports for the assertions: `is_pollable_failure` from `prettyplay.driver`,
`format_step_error` from `prettyplay.engine` (the engine-owned render the Errors section names).

**Input**: `element.or_(other)`.

**Trace**:
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

**Sufficiency**: pins the only eagerly-raised composition error of the family with three invariants at once —
untouched propagation (P3 zero-wrapping), non-pollable classification (the frame-mismatch path of the pollable map),
and the exact `format_step_error` render. Regression: wrapping/translating the error or accidentally adding it to the
pollable map fails these asserts loudly (verified: no existing test covers "same frame" anywhere in the suite).

---

### Negative Tests

#### `test_system_prompt_strategy_rules_are_gone` (AC4 — tests/engine/test_generator.py; rewrite of `test_system_prompt_carries_the_new_rules`)

**Setup**: import `SYSTEM_PROMPT` from `prettyplay.engine.generator`.

**Input**: the constant text.

**Trace**:
```
assert "- Assertions happen only through the expectation calls of the facade — never a Python assert on a locator, never SDK-style state reads" in SYSTEM_PROMPT
assert "Locating by role and accessible name is preferred" not in SYSTEM_PROMPT
assert "accessibility-first priority" not in SYSTEM_PROMPT
surviving mechanics present: dialogs / popups / iframe / scroll / no fixed delays rules, fixed form, output-only-code-block
```

**Assertions**: as above — the new rule in, both removed rules out, the surviving sentence of each kept rule intact.

**Sufficiency**: the prompt-strategy split is editorial — only string-level assertions pin it; without them a mirror edit could silently reintroduce a strategy line or drop a mechanics rule.

---

#### `test_steering_mirrors_the_practices` (AC4 — tests/engine/steering/test_steering.py, new)

**Setup**: read `.goga/usages/prompts/generation.md` and `prettyplay/driver/.usages/facade.md` from the repo (the `Path(__file__).resolve().parents[…]` pattern of the engine tests; a local copy of the row-extraction helper).

**Input**: steering `SYSTEM_PROMPT`, steering `PAGE_API_SURFACE`.

**Trace**:
```
practice = read generation.md → practice.split("---", 1)[1].strip()
assert practice == steering SYSTEM_PROMPT
element_rows = regex-extract the facade practice element table
for row in element_rows: assert row.split("(", 1)[0] in steering PAGE_API_SURFACE
assert steering SYSTEM_PROMPT == engine SYSTEM_PROMPT          # the two frozen copies agree
assert steering PAGE_API_SURFACE == engine PAGE_API_SURFACE
```

**Assertions**: the steering cell's own local copies equal the practices (and the engine copies) — closing the AC4 gap: only the engine had mirror-equality coverage before.

**Sufficiency**: steering holds independent copies by design; without a local mirror test a one-sided edit would leave the dialog steering the model with a stale prompt silently.

---

### Edge Case Tests

#### `test_page_api_surface_covers_the_narrowing_family` (AC4 — tests/engine/test_generator.py; extension)

**Setup**: existing `TestPromptConstants`.

**Input**: `PAGE_API_SURFACE`.

**Trace**:
```
extend test_page_api_surface_lists_every_facade_call with:
  "element.first", "element.last", "element.nth(index)",
  "element.filter(has_text=..., has_not_text=..., has=..., has_not=...)",
  "element.or_(other)", "element.and_(other)"
update test_page_api_surface_mirrors_facade_practice:
  assert len(element_rows) == 25            # 19 + the six narrowing rows
```

**Assertions**: each call string in `PAGE_API_SURFACE`; the practice table extraction counts 25 element rows; `"page.close" not in PAGE_API_SURFACE` still holds.

**Sufficiency**: the listing is the model's only view of the surface — a missing row reproduces the incident even with the facade implemented.

---

#### `test_generation_prompt_rule_order_survives_the_edit` (AC4 — fix of `test_generation_prompt_carries_the_scroll_rule`)

**Setup**: `SYSTEM_PROMPT`.

**Input**: index anchors.

**Trace**:
```
assertion  = SYSTEM_PROMPT.index("- Assertions happen only through")   # replaces the removed locating anchor
dialogs    = SYSTEM_PROMPT.index("- Dialogs: when the step verifies")
scroll     = SYSTEM_PROMPT.index("- Scroll abilities exist")
no_delays  = SYSTEM_PROMPT.index("- No fixed delays")
assert assertion < dialogs < scroll < no_delays
```

**Assertions**: the new rule sits exactly after the assertion-sentence rule, before the dialogs rule; the surviving mechanics keep their order.

**Sufficiency**: the old test anchored on the removed line and would raise `ValueError` after the edit; the rewritten anchors pin the insertion point the plan specifies.

---

#### `test_existing_suite_stays_green` (AC5)

**Setup**: full suite + lint.

**Input**: `pytest tests/ -x`; `ruff check prettyplay/ tests/`.

**Trace**: unchanged suites (taxonomy, pollable map, healing, budgets, steering, cache) run against the updated files — no behavioral change reaches them: `is_pollable_failure` untouched, engine loops untouched, constants content-only.

**Assertions**: zero failures; ruff clean.

**Sufficiency**: the change is additive at the facade and editorial at the mirrors — any ripple into classification/healing/budgets means an unplanned behavior change.

---

## Additional Instructions for the Implementation Agent

- **Order**: (1) `prettyplay/driver/page.py` — the six members; (2) both prompt constants in `generator.py` and `steering.py` (identical edits, cell-owned copies); (3) `docs/reference/driver-facade.md`; (4) tests. Run `pytest tests/ -x` and `ruff check` after each stage; `goga lint` at the end (contracts already clean).
- **page.py member placement**: `first`/`last` properties and `_wrap_locator` right after `_call`; then `nth`, `filter`, `or_`, `and_` before `click` — mirroring the CODEMANIFEST ordering (locating family first, uniform with `PageFacade`).
- **Docstrings**: Google style, the file's established voice (``Args``/``Returns``; constraint notes in the prose, e.g. the `or_` strict-mode requirement).
- **`filter` is keyword-only** (`*` in the signature) with defaults `has_text=""`, `has_not_text=""`, `has=None`, `has_not=None` — upstream shape; the DSL signature does not encode keyword-onlyness and the practice row shows keyword usage.
- **Do not** add facade-side strict-mode handling, validation, or error wrapping for the narrowing family — P3 pins pure upstream semantics; the guard is documentation (`facade` practice, cook, doc).
- **`PAGE_API_SURFACE` rows** mirror the `facade` practice purposes verbatim, em-dash separator; the `element.or_(other)` row carries the full guard hint (the plan's carrier). Keep `page.close` out.
- **`docs/reference/driver-facade.md`**: six element rows (backticked calls in the doc's style) at the head of «Surface — element»; the «Narrowing a locator — positional, content, combinators» example block after «Locating without accessible names»; the strict-mode rule after the auto-wait bullet in Rules; the fixed-form paragraph gains the two narrowing idioms. No nav changes.
- **Tests to touch**: extend `tests/driver/test_page.py` (FakeLocator narrowing members — record-and-return-self; contract + logic + marshaling tests as specified; the frame-mismatch propagation test with a fake `or_` raising the real `Error`); rewrite the two anchored prompt tests and extend the two surface tests in `tests/engine/test_generator.py` (`element_rows` 19 → 25); add the steering mirror tests; extend the engine test-local `FakeLocator`/`FakePage` with narrowing passthroughs for the AC2 scenario.
- **Verification checklist**: the arch plan's checklist items AC1–AC5 map to the test scenarios above; the excluded-capabilities invariant (no route/evaluate/CDP/clock/HAR/tracing/raw input) is unaffected — the family introduces none of them.
- **No changes** to: `prettyplay/driver/errors.py`, engine loops/healer/classification, steering dialog logic, cell Imports/Usages headers, the cook (already updated), `__init__.py` exports (`LocatorFacade` already exported).
