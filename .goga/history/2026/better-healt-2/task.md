# Locator narrowing joins the driver mirror; locating strategy moves wholly to user instructions

## Current State

- `LocatorFacade` (`prettyplay/driver/page.py`, contract in `prettyplay/driver/CODEMANIFEST`) mirrors interactions and expectations but carries no narrowing family: no positional selection (first/last/nth), no content filtering (filter), no combinators (or_/and_). Generated step code expressing "the first row" chains Playwright's `.first` and raises AttributeError — the intent is inexpressible on the surface and the retries burn attempt budget inside the generation loop (the incident).
- The generation system prompt (`.goga/usages/prompts/generation.md`) carries two library-authored locating-strategy lines (accessibility-first priority) — contradicting the decided channel: locating strategy belongs exclusively to the project's `generation_prompt` user instructions.
- The prompt carries no assertion mechanics rule: nothing forbids a Python assert on a locator or SDK-style state reads.
- The cook usage `.goga/usages/cooks/playwright.md` covers the Playwright narrowing family (updated with this task).

## Description

Two changes close the incident class:

1. **Driver mirror extension.** `LocatorFacade` gains the full Playwright locator-narrowing family: positional selection (`first`, `last`, `nth`), content filtering (`filter`), and the `or_`/`and_` combinators. Every member returns a `LocatorFacade`, marshals through the driver thread, exposes no raw Playwright objects, and preserves auto-wait. The `prettyplay/driver` CODEMANIFEST and the `facade.md` surface listing change together with the code — and the new surface reaches generation through the frozen `PAGE_API_SURFACE` mirror constants of the engine and steering cells, which change only together with the practice file (no runtime read of `.goga/` ever happens).
2. **Generation prompt edit.** The system prompt loses the accessibility-priority lines (locating strategy moves wholly to the project's `generation_prompt` user instructions; the model decides when they are absent) and gains one mechanics rule: assertions happen only through expect_* facade calls — never a Python assert on a locator, never SDK-style state reads.

## Scope

**In scope:**
- LocatorFacade narrowing family: positional selection (first, last, nth), content filtering (filter), combinators (or_, and_)
- Driver CODEMANIFEST contract update for the family
- `facade.md` surface listing update (element table) — together with the contract change
- Frozen-mirror constant updates: `SYSTEM_PROMPT` and `PAGE_API_SURFACE` in `prettyplay/engine/generator.py` and `prettyplay/engine/steering/steering.py` change together with their practice files — each cell holds its own local copy, no runtime read of `.goga/`
- Public docs surface mirror: the surface tables of `docs/reference/driver-facade.md` (the mkdocs «Driver facade» page) gain the family together with the facade
- Generation system prompt edit: remove the locating-strategy lines, add the assertion mechanics rule
- Tests per AC1–AC5 (unit parity, incident regression, disjunction scenario, prompt contract, non-regression)

**Out of scope:**
- Failure taxonomy, classification, pollable map, healing, budgets, steering behavior, step cache — untouched (beyond the steering frozen-mirror constants of In scope)
- Static pre-execution validator of candidates against the surface listing (rejected in the ADR)
- Raw input devices and the other excluded capabilities — the parity exclusions stand

## Acceptance Criteria

From the approved ADR:

1. Unit parity of the narrowing family inside the facade invariants (driver-thread marshaling, returns `LocatorFacade`, no raw objects, auto-wait preserved).
2. Incident regression, integration: a step whose locator matches N elements generates on-surface narrowing code and goes green, with no off-surface AttributeError retries in the loop.
3. Disjunction scenario, integration: «text ‚one' or text ‚two'» generates an or_-composition that goes green, the both-present strict-mode case included.
4. Prompt contract: the system prompt carries no locating-strategy rules, carries the assertion mechanics rule, and each provider-bound PAGE API listing — the engine and the steering frozen mirror — equals the `facade` practice.
5. Non-regression: the existing test suite stays green — taxonomy, pollable map, healing, budgets, steering, cache unchanged.

## Stack

- **Frameworks:** pytest (tests), ruff (lint)
- **Libraries:** Playwright sync API (existing), pydantic (existing)
- **Infrastructure:** none

## External Dependencies

| Component | Usage file | Status |
|-----------|------------|--------|
| Playwright | `.goga/usages/cooks/playwright.md` | updated (locator narrowing section) |

## Risks and Constraints

- Strict-mode composition semantics for `or_` when both branches match is unresolved — a design-stage decision; the canonical guard (positional narrowing over the composition) must work regardless.
- Parity principle: mirror names follow Playwright; `first`/`last` are properties in upstream Playwright Python — the facade should follow the upstream shape where the fixed-form step code allows.
- The prompt edit is an editorial split, not a rewrite: the mechanics that stay (fixed form, dialog/popup capture, no sleeps) must be untouched.
- Python 3.10+ compatibility; project conventions apply (relative imports, Google-style docstrings).

## Scope Estimate

Single task — one cohesive iteration: driver mirror extension + prompt edit + tests. The parts are coupled by the listing-equals-practice invariant (surface listing, contract and prompt change together).

## Existing Architecture

- `prettyplay/driver` — the impacted cell: `LocatorFacade` (`page.py`), the CODEMANIFEST contract, the `.usages/facade.md` practice.
- `prettyplay/engine` and `prettyplay/engine/steering` — no CODEMANIFEST signature changes expected, but the code is touched directly: each cell holds cell-owned frozen mirrors — `SYSTEM_PROMPT` (of the shared `system_prompt` practice, `.goga/usages/prompts/generation.md`) and `PAGE_API_SURFACE` (of the driver `facade` practice) — and both constants change only together with their practice files.
- The page API surface listing sent to providers is the frozen `PAGE_API_SURFACE` mirror of the `facade` practice, held locally by the engine and the steering cells — the engine annotation «the listing and the practice change together» encodes the sync discipline.

## Notes

Illustrative idioms from the ADR (non-normative; exact signatures are a design-stage decision):

```python
# the .first incident — was an AttributeError, becomes on-surface
page.get_by_text("Welcome back").first.expect_visible()

# assertions only through expect_* — no Python assert, no is_visible()
page.get_by_role("button", name="Sign in").expect_visible()

# positional narrowing
page.get_by_role("row").first.expect_text("Paid")

# content filtering
page.get_by_role("listitem").filter(has_text="Product X").expect_visible()

# disjunction — "text ‚one' or text ‚two' is present" (first guards strict mode
# when both branches match; composition semantics to be pinned at design stage)
page.get_by_text("one").or_(page.get_by_text("two")).first.expect_visible()

# intersection
page.get_by_role("button").and_(page.get_by_text("Save")).expect_enabled()
```

Strategy guidance — e.g. "the UI is marked up with data-test-id, prefer get_by_test_id" — lives in the project's `generation_prompt` user instructions, never in the library prompt.

Open points carried to design/plan:

- Exact mirror names, signatures and the parameter surface of the family members (e.g. which filter arguments are mirrored) and their CODEMANIFEST placement.
- Strict-mode composition semantics for disjunction when both branches match.
- The editorial split of the current system prompt lines: mechanics stay (fixed form, expect_* assertions, dialog/popup capture, no sleeps), strategy goes (locating priority).

Source ADR: `.goga/history/2026/better-healt-2/adr.md`.
