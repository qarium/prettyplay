# Open the standard Playwright API to generated step code

## Current State

- prettyplay confines generated step code to `PageFacade` — a Playwright-mirroring facade whose 65-call surface is frozen in the `PAGE_API_SURFACE` constant.
- The surface is mirrored in four places: `prettyplay/engine/generator.py` (the constant), `prettyplay/engine/steering/steering.py` (a frozen copy), the driver facade usage doc (`facade.md`), and the parity tests (`tests/engine/test_generator.py`, `tests/engine/steering/test_steering.py`).
- Step code executes via `run_step_code(code, page)` on the caller thread against the facade; every facade call marshals into the dedicated driver worker thread (`PlaywrightWorker.run`).
- The motivating failure: a step asserting "the page shows a list of videos" calls `locator.count()` — real Playwright, absent from the facade — producing a hard non-pollable `AttributeError` that burns generation attempts. The only count assertion, `expect_count(n)`, is exact equality and cannot express "a list" without a fragile exact number.

## Description

Generated step code gets the genuine Playwright sync API. The whole step executes inside the driver worker thread as a single `worker.run(...)` call and receives the real sync `Page`; the caller thread never touches Playwright (the IPython/Jupyter guarantee holds). The facade mirror leaves the generation path for good; the driver facade survives only as internal runtime plumbing (snapshot, screenshot, close). The page API stays reachable for the author from the `PrettyPlay` object — a human can perform the excluded actions explicitly; the exact shape is deferred to the design stage. This is one coherent breaking change: `PAGE_API_SURFACE` with both frozen copies, the parity/mirror tests and the doc mirror are removed and rewritten in a single series — no staged deprecation. The step cache is a disposable artifact: no compatibility, every example regenerates on the new engine.

Target look of generated step code (the motivating case):

```python
from playwright.sync_api import expect


def step(page) -> None:
    videos = page.get_by_role("listitem")
    expect(videos.first).to_be_visible()
    assert videos.count() > 1
```

Characteristic prohibition — a stateful call whose effect outlives the step on the page shared by the whole test:

```python
# FORBIDDEN in generated code — poisons the shared page for later steps
page.route("**/api/videos", handler)
```

## Scope

**In scope:**

- New execution boundary: the whole step runs inside the driver worker thread as one `worker.run(...)`; step code receives the genuine sync `Page`; the calling thread never adopts the Playwright event loop
- Prompt rewrite of `.goga/usages/prompts/generation.md`: standard Playwright allowed; a compact cheat-sheet of useful idioms (locator factories, actions, waits, count forms, dialog/popup idioms) carried as guidance, not an allowlist; imports restricted to `from playwright.sync_api import ...` as a prompt rule (no hard gate); safety core — fixed form `def step(page)`, no fixed delays or sleeps, no `page.close()`/`context.close()` (the runtime owns the page lifecycle); stateful "bookmarks" excluded by one prompt rule — `page.route`, `page.clock`, `add_init_script`, tracing, HAR, CDP; waiting `expect(...)` forms advised for dynamic content, immediate reads with plain Python asserts allowed
- prettyplay extras leave the generation contour: the scroll family, `expect_dialog` and the `expect_*` sugar are gone from generated code; scrolling and dialogs use stock Playwright means
- Single coherent breaking change: remove `PAGE_API_SURFACE` with both frozen copies (engine, steering), the parity/mirror tests and the doc mirror — no staged deprecation
- Driver facade demoted to internal runtime plumbing (snapshot, screenshot, close)
- Author escape hatch: the page API reachable from the `PrettyPlay` object so a human can perform the excluded actions explicitly (exact shape deferred to the design stage)
- Cache non-compatibility: the cache is disposable; every example regenerates on the new engine
- Update `.goga/usages/cooks/playwright.md` in the same series as the code (approved content sketch — see Notes)
- Rewrite the generation prompt source, the generator/steering prompt copies and the driver-facade docs in the same series
- Unit tests of the new execution boundary; the youtube example regenerated and green on the new engine, including the "list of videos" expectation through standard count forms

**Out of scope:**

- Expanding the facade with an at-least count form (the original task framing — rejected in the ADR)
- Transparent passthrough facade (rejected in the ADR after the threading analysis)
- Staged deprecation or cache migration
- Semantic changes to `is_pollable_failure` and the settle window — `AssertionError` and Playwright timeouts behave identically under the standard API
- The async API
- Runtime gating of imports/exclusions — prompt rules only; the error-driven regeneration loop is the second line of defense against hallucinated calls

## Acceptance Criteria

- The youtube example runs green on the new engine, including the "list of videos" expectation expressed through standard count forms (`expect(...).to_be_visible()`, `assert locator.count() > 1`); if the environment lacks keys or network, the unit level is accepted and the fact is recorded
- Unit tests cover the new execution boundary: the step executes wholly inside the worker thread, the step code receives the genuine sync `Page`, the calling thread never touches Playwright
- `PAGE_API_SURFACE` and its mirrors are gone — engine constant, steering copy, parity/mirror tests, doc mirror — one series, no leftovers
- The rewritten generation prompt carries: the standard-API allowance, the cheat-sheet guidance, the import rule, the safety core, the stateful exclusions
- The step cache is treated as disposable; examples regenerate (no compatibility shims)
- Docs updated in the same series: the generation prompt source, the generator/steering copies, the driver-facade docs, the `playwright.md` cook
- The author escape hatch exists: the page API is reachable from `PrettyPlay` and crosses the worker-thread boundary (the exact shape per the design stage)
- Full test suite green (`pytest tests/ -x`), ruff clean

## Stack

- **Frameworks:** none beyond the existing (a pure library change)
- **Libraries:** Playwright sync API (existing hard dependency — its use expands to generated step code), pydantic (existing); pytest and ruff (existing dev tooling — the acceptance runs `pytest tests/ -x` and ruff)
- **Infrastructure:** none

## External Dependencies

| Component | Usage file | Status |
|-----------|------------|--------|
| Playwright sync API | `.goga/usages/cooks/playwright.md` | updated (within the task, same series as the code) |
| Generation prompt | `.goga/usages/prompts/generation.md` | rewritten (the task's own artifact) |

No new external dependencies.

## Risks and Constraints

- Breaking change for every cached step — accepted by the ADR; the cache is a disposable artifact
- The threading invariant is the load-bearing constraint: all Playwright objects are fiber-bound to the dedicated worker thread; only `PlaywrightWorker.run` may cross. Any design leaking worker-bound handles to the caller thread recreates the rejected passthrough problem
- The runtime dialog router and stock dialog captures must be reconciled: the per-page routing handler resolves every dialog no armed capture claims, and a stock `page.expect_event("dialog")` in generated code arms nothing the router sees — double-handling is a live design hazard the design stage must resolve (the accept_dialogs semantics stay honest)
- Prompt-only enforcement (imports, exclusions) means the error-driven regeneration loop must stay healthy — it is the second line of defense against hallucinated calls
- `AssertionError` from plain Python asserts and Playwright timeouts must keep flowing through the existing failure classification unchanged
- Acceptance of the youtube example depends on LLM keys and network; their absence degrades acceptance to the unit level (recorded, not silent)

## Scope Estimate

Single task — high size, one coherent breaking change. The mechanism (the worker-thread execution boundary) and all its ripples (prompt, surface removal, facade demotion, escape hatch, cache disposal, docs, example) belong to one series; splitting would desynchronize the surface mirrors, which the ADR explicitly forbids. Internal work ordering is a matter for the design/plan stages, not task decomposition.

## Existing Architecture

Affected cells:

- `prettyplay/driver` — `DriverSession`, `PageFacade` (facade demotion; the worker hand-off mechanics is an open design question)
- `prettyplay/engine` — `StepGenerator` (the `PAGE_API_SURFACE` constant, the request `page_api` slot — fate deferred to design), `run_step_code` (the new execution boundary), prompt rendering
- `prettyplay/engine/polling` — `settle` (wraps `run_step_code` and threads `page` through its contract; design-dependent — only a design keeping `run_step_code(code, PageFacade)` leaves it untouched; semantics unchanged)
- `prettyplay/engine/steering` — `StepSteering` (the surface copy, prompt rendering)
- `prettyplay/llm` — `LLMProvider` (the `page_api` slot of `generate_step_code`: its post-facade fate — cheat-sheet carrier or rename — and its facade-specific annotation text change here)
- `prettyplay` (root) — `PrettyPlay` (the author escape hatch), `StepExecutor`, `PrettyplayRuntime`

Project usages: `.goga/usages/prompts/generation.md` (rewrite), `.goga/usages/cooks/playwright.md` (update). Example: the youtube example under `example/` (regenerated).

## Notes

- Source ADR: `.goga/history/2026/add-expect-count/adr.md` (status: accepted, 2026-09-13)
- Open questions deliberately deferred to the design/plan stages (from the ADR): the exact shape of author-facing page access from `PrettyPlay` (must cross the worker thread boundary); the fate of the `page_api` slot in the generation request (does it carry the cheat-sheet; is it renamed); the driver cell contract after the facade demotion; the cheat-sheet's content and home (which document stores it and what mirrors it); the mechanics of handing the worker to `run_step_code`/the executor
- Approved `playwright.md` update sketch (apply within the task, same series as the code): a new leading section "Generated step code — the standard API contour" (worker-thread execution, genuine sync `Page`, import rule, safety core, stateful exclusions, waiting-vs-immediate assertion guidance); Interactions — drop the "raw input devices outside the facade surface" rule (raw input devices are standard Playwright, reachable in generated code; element press stays the default guidance); Dialogs — facade `expect_dialog` references replaced with stock means (`page.expect_event("dialog")` / `page.on("dialog")`), the per-page routing handler stays runtime behavior; Popups — drop the "facade-wrapped pages" phrasing (stock `expect_popup`, pages directly usable); Frames — drop "no raw frame objects cross the facade boundary"; the Rules footer synced with the new contour
- Grooming decisions (this stage): formulation and boundaries confirmed; both code examples included in the task; stack unchanged (no new dependencies); the `playwright.md` update scheduled in-task rather than applied at grooming time (the doc must not precede implementation); single task, no subtask breakdown
