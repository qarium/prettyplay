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
The step wins, the router is last — deterministic inside the worker thread. The drain of one unit is bounded: a page
that fires a fresh dialog for every resolution leaves the excess pending for the next unit tail — no unit runs forever.

## Rules

- One browser process per test; contexts stay isolated
- Driving is strictly sequential: one run at a time
- No fixed delays anywhere in runtime plumbing — waits live in locators and expectations of step code
