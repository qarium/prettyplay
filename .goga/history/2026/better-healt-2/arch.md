# Architecture Plan — Driver locator narrowing & prompt strategy split

Task: «Locator narrowing joins the driver mirror; locating strategy moves wholly to user instructions»
Source task: `.goga/history/2026/better-healt-2/task.md`; ADR: `.goga/history/2026/better-healt-2/adr.md`.

## Topic

Short name: **Driver locator narrowing & prompt strategy split**.
Plan path: `.goga/history/2026/better-healt-2/arch.md`.

Two coupled changes close the incident class:

1. **Driver mirror extension** — `LocatorFacade` gains the full Playwright locator-narrowing family: positional selection (`first`, `last` — properties; `nth(index)` — method), content filtering (`filter`), combinators (`or_`, `and_`). Every member returns a `LocatorFacade`, marshals through the driver thread, exposes no raw Playwright objects, preserves auto-wait.
2. **Generation prompt editorial split** — the system prompt loses the two library-authored locating-strategy lines (locating strategy belongs exclusively to the project's `generation_prompt` user instructions) and gains one assertion mechanics rule: assertions happen only through `expect_*` facade calls — never a Python assert on a locator, never SDK-style state reads.

Pinned design decisions:

- **P1** — `first`/`last` are properties (upstream Playwright Python shape; the incident idiom `page.get_by_text("Welcome back").first.expect_visible()` stays literal).
- **P2** — `filter` mirrors all four upstream predicates: `has_text: str`, `has_not_text: str` (empty string — not applied), `has: LocatorFacade | None`, `has_not: LocatorFacade | None` (None — not applied). No regex arguments — string arguments only, uniform with the rest of the facade.
- **P3** — `or_` keeps upstream union semantics with no custom behavior: an action or expectation over a composition matching elements of both branches raises the strict-mode violation like any multi-match locator; positional narrowing over the composition (`.or_(...).first`) is the canonical guard, documented in the `facade` practice — never implemented as facade code.

## Implementation Order

1. **`prettyplay/driver`** [MODIFIED] — the leaf of the touched cluster (its only Import — `prettyplay/config` — is untouched). The contract change and its `facade` practice define what the consumer cells mirror; designed first.
2. **`.goga/usages/prompts/generation.md`** [MODIFIED, project-level practice] — the second practice source; changes together with its `SYSTEM_PROMPT` mirrors. Attached below to its primary consumer for ordering purposes.
3. **`prettyplay/engine`** [MODIFIED] — depends on `prettyplay/driver` (types + `facade` practice); holds the frozen `SYSTEM_PROMPT` and `PAGE_API_SURFACE` mirrors in `generator.py`.
4. **`prettyplay/engine/steering`** [MODIFIED] — depends on `prettyplay/driver` and `prettyplay/engine`; holds its own copies of the same mirrors in `steering.py`.

No cell is created anew; all changes are modifications of existing cells and practices.

---

## Artifacts

### Cell: `prettyplay/driver` [MODIFIED]

#### CODEMANIFEST diff — `prettyplay/driver/CODEMANIFEST`

Header (Imports / Usages / Annotations), the types `DriverSession`, `PageFacade`, `DialogFacade`, `FrameFacade`, the routine `is_pollable_failure`, and the Footer are unchanged. All changes are inside `LocatorFacade`:

**ADD** one line to the `LocatorFacade` Requirements (after the auto-wait requirement):

```yaml
    - The narrowing members — first, last, nth, filter, or_ and and_ — run in the driver thread like every facade call and return a full LocatorFacade: chains compose and no raw Playwright object crosses the boundary
```

**ADD** the `properties` block to `LocatorFacade` (the type currently has none):

```yaml
  properties:
    "first -> LocatorFacade": |
      The first match of this locator in document order — the positional narrowing selecting one element among many (see `playwright`).
    "last -> LocatorFacade": |
      The last match of this locator in document order (see `playwright`).
```

**ADD** four methods at the head of the `LocatorFacade` `methods` block (before `click`; locating family first, uniform with `PageFacade` ordering):

```yaml
    "nth(index: int) -> element: LocatorFacade": |
      Select the match at `index` — the positional narrowing.

      `index`: 0-based position; negative counts from the end (see `playwright`).
    "filter(has_text: str, has_not_text: str, has: LocatorFacade | None, has_not: LocatorFacade | None) -> element: LocatorFacade": |
      Narrow this locator by element content — the predicates are optional and combine as a logical and (see `playwright`).

      `has_text`: keep elements whose text contains this string; empty — not applied.
      `has_not_text`: drop elements whose text contains this string; empty — not applied.
      `has`: keep elements containing a match of this inner locator; None — not applied.
      `has_not`: drop elements containing a match of this inner locator; None — not applied.

      Constraints:
      - The inner locators of `has` and `has_not` are facades — no raw Playwright object crosses the boundary.
    "or_(other: LocatorFacade) -> element: LocatorFacade": |
      The union locator — matches what this locator or `other` matches (see `playwright`).

      `other`: the alternative `LocatorFacade`.

      Requirements:
      - An action or expectation over a composition matching elements of both branches raises the strict-mode violation like any multi-match locator — positional narrowing over the composition is the canonical guard (see `playwright`).
    "and_(other: LocatorFacade) -> element: LocatorFacade": |
      The intersection locator — matches elements matching both this locator and `other` (see `playwright`).

      `other`: the intersecting `LocatorFacade`.
```

The 19 existing methods (`click` … `expect_attribute`) are unchanged.

#### `.usages` diff — `prettyplay/driver/.usages/facade.md`

**ADD** six rows at the head of the «Surface — element» table (before `element.click`):

```markdown
| element.first | the first match — positional narrowing |
| element.last | the last match — positional narrowing |
| element.nth(index) | the match at a 0-based index; negative counts from the end |
| element.filter(has_text=..., has_not_text=..., has=..., has_not=...) | narrow by content — all predicates optional |
| element.or_(other) | union locator — matches either; when both branches may match, compose positional narrowing (first, last, nth) to satisfy strict mode |
| element.and_(other) | intersection locator — matches both |
```

**ADD** an example block after «Locating without accessible names» in the Example section:

```markdown
Narrowing a locator — positional, content, combinators:
```

```python
page.get_by_role("row").first.expect_text("Paid")
page.get_by_role("listitem").last.expect_visible()
page.get_by_role("row").nth(2).expect_text("Shipped")
page.get_by_role("listitem").filter(has_text="Product X").expect_visible()
page.get_by_role("button").and_(page.get_by_text("Save")).expect_enabled()

# disjunction with the strict-mode guard — both texts may be present
page.get_by_text("one").or_(page.get_by_text("two")).first.expect_visible()
```

**ADD** one rule to the Rules section (after the auto-wait rule):

```markdown
- A locator resolving to several elements fails an action or expectation with the strict-mode violation — narrow positionally (first, last, nth) to address one match; over an or_ composition the positional narrowing is the canonical guard when both branches may match
```

`error_kinds.md` is unchanged.

### Project-level practice: `.goga/usages/prompts/generation.md` [MODIFIED]

**REMOVE** the two locating-strategy rules:

```markdown
- Locating by role and accessible name is preferred; by visible text next; by label or placeholder for form fields
- get_by_test_id and locator(selector) exist for elements without accessible names — the accessibility-first priority stands unless USER INSTRUCTIONS say otherwise
```

**ADD** one assertion mechanics rule immediately after «For an assertion sentence end with an expectation call; for an action sentence perform the actions»:

```markdown
- Assertions happen only through the expectation calls of the facade — never a Python assert on a locator, never SDK-style state reads
```

Everything else stays verbatim: the fixed form, dialog/popup capture, iframe scoping, scroll abilities, no sleeps, RECOMMENDATION/USER GUIDANCE handling, STEP precision, output-only-code-block. The strict-mode guard guidance is not added here — the guard hint travels with the `element.or_(other)` row of the PAGE API listing; the full rule lives in the `facade` practice for engineers.

### Cell: `prettyplay/engine` [MODIFIED]

#### CODEMANIFEST diff — `prettyplay/engine/CODEMANIFEST`

Imports, Usages, the Body (`StepGenerator`, `format_step_error`, `run_step_code`, `classify_step_failure`, `StepHealer`), and the Footer are unchanged.

**ADD** one line to the global Annotations, immediately after «The page API surface listing sent to the provider mirrors `facade` from Imports exactly — the listing and the practice change together.»:

```yaml
  The system prompt sent to the provider is the frozen local mirror of `system_prompt` — the mirror and the practice change together.
```

#### `.usages` diff — `prettyplay/engine/.usages/generation.md`

**UPDATE** the «The fixed form» section — insert two narrowing idioms into the idiom list (after the locator idioms, before «and alike»):

```markdown
`page.get_by_role("row").first.expect_text("Paid")`, `page.get_by_role("listitem").filter(has_text="Product X").expect_visible()`
```

`healing.md` is unchanged.

### Cell: `prettyplay/engine/steering` [MODIFIED]

#### CODEMANIFEST diff — `prettyplay/engine/steering/CODEMANIFEST`

Imports, Usages, the Body (`StepSteering`), and the Footer are unchanged.

**ADD** two lines to the global Annotations, immediately after the three `Use …` lines (the mirror-discipline block before the behavioral lines):

```yaml
  The system prompt sent to the provider is the frozen local mirror of `system_prompt` — the mirror and the practice change together.
  The page API surface listing sent to the provider is the frozen local mirror of `facade` from Imports — the listing and the practice change together.
```

#### `.usages` — unchanged

`steering.md` stays as is: it documents the REPL surface and lists no step-code idioms; narrowing reaches guided regeneration through the `facade` practice carried in the request listing.

---

## Dependency Map

```
                     ┌───────────────────────────┐
                     │  prettyplay/config        │  (unchanged)
                     └─────────────┬─────────────┘
                                   │ Config + configuration
                                   ▼
                     ┌───────────────────────────┐
   practice:         │  prettyplay/driver    [M] │  LocatorFacade: narrowing family
   playwright (cook) │  CODEMANIFEST + facade.md│  contract and practice together
   (already updated) └──────┬─────────────┬─────┘
                            │             │ PageFacade + facade
                            │             ▼                    ▼
                            │   ┌──────────────────┐  ┌────────────────────────┐
                            │   │ prettyplay/engine │  │ prettyplay/engine/     │
                            │   │ [M] +1 annotation │  │ steering [M] +2 annot. │
                            │   │ generator.py:     │  │ steering.py:           │
                            │   │ SYSTEM_PROMPT +   │  │ SYSTEM_PROMPT +        │
                            │   │ PAGE_API_SURFACE  │  │ PAGE_API_SURFACE       │
                            │   └────────┬─────────┘  └──────────▲─────────────┘
                            │            │ run_step_code         │
                            │            └───────────────────────┘

  Practice sync (not Imports — mirror discipline encoded in annotations):
  .goga/usages/prompts/generation.md [M] ──(SYSTEM_PROMPT)──────> engine, steering
  prettyplay/driver/.usages/facade.md  [M] ──(PAGE_API_SURFACE)─> engine, steering
  docs/reference/driver-facade.md      [M] ──(public mirror)────> human consumers
```

No circular dependencies. Import edges are unchanged from the current schema.

## Verification Checklist

After implementing each artifact:

- [ ] `goga lint` passes for all three CODEMANIFESTs (driver, engine, steering).
- [ ] Driver contract: the six new members exist exactly as specified; no existing signature, annotation or type changed beyond the single added `LocatorFacade` Requirement.
- [ ] Driver implementation invariants (AC1): every narrowing member marshals through the driver thread, returns a full `LocatorFacade`, exposes no raw Playwright object, preserves auto-wait; `first`/`last` are properties; `nth` is 0-based with negative-from-the-end; `filter` combines predicates as a logical and.
- [ ] Frozen mirrors (AC4): `SYSTEM_PROMPT` in `generator.py` and `steering.py` equals the updated `generation.md` practice; `PAGE_API_SURFACE` in both files equals the updated `facade` practice — each cell holds its own local copy, no runtime read of `.goga/`.
- [ ] Prompt contract (AC4): no locating-strategy rules remain; the assertion mechanics rule is present; the surviving mechanics (fixed form, dialog/popup capture, iframe, scroll, no sleeps) are untouched.
- [ ] Public docs: `docs/reference/driver-facade.md` element table gains the six members together with the facade; example section reflects the narrowing idioms.
- [ ] Tests: AC1 unit parity of the family inside the facade invariants; AC2 incident regression — a step matching N elements generates on-surface narrowing code, green, no off-surface AttributeError retries; AC3 disjunction — `or_`-composition green including the both-present strict-mode case; AC4 prompt/mirror equality assertions; AC5 — the existing suite stays green (taxonomy, pollable map, healing, budgets, steering, cache unchanged).
- [ ] Excluded capabilities remain absent: the narrowing family introduces no route/request interception, evaluate, CDP, clock, HAR, tracing or raw input devices.
