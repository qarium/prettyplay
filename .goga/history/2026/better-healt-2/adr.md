# Locator narrowing joins the driver mirror; locating strategy moves wholly to user instructions

Generated step code chained Playwright's `.first` on `LocatorFacade` and raised AttributeError: the facade surface could not address one match among many, and the system prompt carried library-authored accessibility-priority rules that contradicted the designed channel for such guidance. We extend the parity mirror of the driver with the full Playwright locator-narrowing family — positional selection (first/last/nth), content filtering, and the or_/and_ combinators — so multi-match steps («the first row», «text ‚one' or text ‚two'») become expressible as on-surface code; the page API surface listing reaches generation automatically under the listing-equals-practice invariant. The generation system prompt loses the accessibility-priority lines (a past framing error: locating strategy belongs exclusively to the project's generation_prompt user instructions, and the model decides when they are absent) and gains one mechanics rule: assertions happen only through expect_* facade calls — never a Python assert on a locator, never SDK-style state reads. A deterministic pre-execution validator of candidates against the surface listing was considered and rejected: it would duplicate the surface in code and risk false positives, while the existing fresh-error retry loop already feeds the exact AttributeError back to the model within a bounded attempt budget. Failure taxonomy, classification, healing, budgets, steering and the step cache are untouched.

## Enabled idioms (illustrative; exact signatures are a design-stage decision)

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

## Acceptance

1. Unit parity of the narrowing family inside the facade invariants (driver-thread marshaling, returns `LocatorFacade`, no raw objects, auto-wait preserved).
2. Incident regression, integration: a step whose locator matches N elements generates on-surface narrowing code and goes green, with no off-surface AttributeError retries in the loop.
3. Disjunction scenario, integration: «text ‚one' or text ‚two'» generates an or_-composition that goes green, the both-present strict-mode case included.
4. Prompt contract: the system prompt carries no locating-strategy rules, carries the assertion mechanics rule, and the provider-bound PAGE API listing equals the `facade` practice.
5. Non-regression: the existing test suite stays green — taxonomy, pollable map, healing, budgets, steering, cache unchanged.

## Open questions (design/plan stages)

- Exact mirror names, signatures and the parameter surface of the family members (e.g. which filter arguments are mirrored) and their CODEMANIFEST placement.
- Strict-mode composition semantics for disjunction when both branches match.
- The editorial split of the current system prompt lines: mechanics stay (fixed form, expect_* assertions, dialog/popup capture, no sleeps), strategy goes (locating priority).
