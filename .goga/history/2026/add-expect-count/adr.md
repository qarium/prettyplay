# Open the standard Playwright API to generated step code

---
status: accepted
date: 2026-09-13
---

The step-generation engine constrained generated code to prettyplay's facade — a
Playwright-mirroring surface with method-style `expect_*` assertions frozen in
`PAGE_API_SURFACE` (65 calls mirrored across the generator, steering, `facade.md`
and parity tests). Models know real Playwright, so they kept hitting the artificial
boundary: the motivating case was a step calling `locator.count()` — real Playwright,
absent from the facade — a hard non-pollable `AttributeError` that burns generation
attempts, while the only count assertion, `expect_count(n)`, is exact equality and
cannot express "the page shows a list of videos" without a fragile exact number.
We decided to solve this at the root: generated step code gets the genuine
Playwright sync API, and the facade mirror leaves the generation path for good.

## Decisions

- **Mechanism**: the whole step executes inside the driver worker thread as one
  `worker.run(...)`; step code receives the genuine sync `Page`. The caller thread
  never touches Playwright — the IPython/Jupyter guarantee holds.
- **Assertions**: every standard form is allowed — waiting `expect(...)` chains and
  immediate reads with plain Python asserts (`locator.count() > 1`). The prompt
  advises waiting forms for dynamic content; nothing is enforced at runtime.
- **Imports**: `from playwright.sync_api import ...` only — a prompt rule, no hard gate.
- **Safety core survives**: the fixed form `def step(page)`; no fixed delays or sleeps;
  no `page.close()`/`context.close()` — the runtime owns the page lifecycle.
- **No stateful "bookmarks" in generated code**: `page.route`, `page.clock`,
  `add_init_script`, tracing, HAR and CDP are excluded by one prompt rule — their
  effects outlive the step on the page shared by the whole test, and a cached step
  would poison every later step far from the cause.
- **prettyplay extras leave the generation contour**: the scroll family,
  `expect_dialog` and the `expect_*` sugar are gone from generated code; scrolling
  and dialogs use stock Playwright means.
- **Cheat-sheet instead of boundary**: the request carries a compact reminder of
  useful idioms (locator factories, actions, waits, count forms, dialog/popup
  idioms) as *guidance*, not an allowlist — everything standard stays allowed. The
  error-driven regeneration loop is the second line of defense against hallucinated
  calls.
- **Author escape hatch**: the page API is reachable from the `PrettyPlay` object so
  a human can perform the excluded actions explicitly (shape unresolved — see open
  questions).
- **No cache compatibility**: the step cache has no value; every example regenerates
  on the new engine.
- **One coherent breaking change**: `PAGE_API_SURFACE` with both frozen copies, the
  parity/mirror tests and the doc mirror are removed and rewritten in a single
  series — no staged deprecation.
- **Acceptance**: the youtube example runs green on the new engine (including the
  "list of videos" expectation through standard count forms) plus unit tests of the
  new execution boundary plus docs; if the environment lacks keys or network, unit
  level is accepted and recorded.

## Considered Options

- **Expand the facade** with an at-least count form (the original framing of this
  task): rejected — it patches one symptom of a recurring class of failures
  ("this call is not on the surface").
- **Transparent passthrough facade** (delegation to the wrapped Playwright objects):
  provisionally accepted, then rejected after the threading analysis — non-locator
  returns (`page.keyboard`, `locator.element_handle()`, `page.context`,
  `page.request`) leak worker-bound handles, and wrapping them re-creates the
  managed surface one layer down: the same micromanagement, moved.

## Consequences

- Breaking for cached steps — accepted, the cache is a disposable artifact.
- The driver facade survives only as internal runtime plumbing (snapshot,
  screenshot, close); its published role "the only page API generated code may use"
  ends, together with its 65-row mirror and the tests pinning it.
- `is_pollable_failure` and the settle window need no semantic change:
  `AssertionError` and Playwright timeouts behave identically under the standard API.
- The generation prompt source (`.goga/usages/prompts/generation.md`), the generator
  and steering copies, and the driver-facade docs are rewritten in the same series.

## Open Questions (for the design and plan stages)

- The exact shape of author-facing page access from `PrettyPlay` — it must cross the
  worker thread boundary.
- The provider contract: the fate of the `page_api` slot in the generation request
  (does it carry the cheat-sheet; is it renamed).
- The driver cell contract after the facade demotion — what remains internal.
- The cheat-sheet's content and home — which document stores it and what mirrors it.
- The mechanics of handing the worker to `run_step_code` / the executor.
