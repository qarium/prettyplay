# Fix the interactive steering loop: engineer-approved turns, full context window, URL visibility

Source of truth: the approved ADR at `.goga/history/2026/fix-interactive-loop/adr.md` (all eight
decisions) and the TODO repro at `.goga/history/2026/fix-interactive-loop/todo.md`. This task
translates the ADR into one change.

## Current State

The interactive steering dialog (`StepSteering`, cell `prettyplay/engine/steering`) takes engineer
guidance over a terminally stuck step but never heals it. Verified in code during discovery:

- The turn model executes regenerated code immediately: the generated code is never shown to the
  engineer, there is no approval gate, and a failed turn surfaces as a single `turn failed: ...`
  line before returning to the guidance prompt.
- The regenerated request carries no page URL anywhere — not in the request blocks, not in the
  dialog banner — and the page handle contract (`PageFacade`, cell `prettyplay/driver`) exposes no
  URL read (only the run primitive, `aria_snapshot`, `screenshot`, `close`).
- The request's CODE/ERROR blocks stay anchored to the original failure on every turn (kept by
  design), but the turn history the model sees is collapsed rather than full, so the model re-reads
  the CAPTCHA-time error forever and re-does the whole step (observed:
  `Page.reload: Timeout 30000ms exceeded`).
- The system prompt's import rule ("Import only from playwright.sync_api — no other imports")
  fights the model's regex instinct — the model reliably reaches for `re` and hits
  `NameError: name 're' is not defined`; nothing in the execution runtime restricts imports either
  way (verified: plain `exec`, full builtins, no audit hooks). The `re.compile(...)` examples live
  in the playwright practice (`cooks/playwright.md`), which the model never sees — the request
  itself carries no regex advice.
- The terminal error render (`render_terminal_message`, cell `prettyplay/failures`) carries no
  received/cause/Call log detail, pads label alignment with `ljust` (ignoring terminal width), and
  the steering banner embeds a 20-line accessibility-snapshot fragment that makes the error output
  effectively unreadable.

## Description

Rebuild the steering loop around engineer approval and a full, honest context window — all four
TODO problems in one change, per the ADR:

1. **Turn model — generate, show, approve, execute.** Every guidance turn: regenerate → show the
   generated code to the engineer → confirmation prompt `run? [y/N]` (all dialog strings stay
   English, as today) → on `y` execute against the live page (green → compliance gate → cache
   write-back; red → show the error → back to the guidance prompt); on `n`, Enter or `quit` the
   turn is aborted without execution and the dialog returns to the guidance prompt.
2. **Rejected code is history.** An engineer-rejected candidate enters the history as a completed
   turn with the outcome `rejected by the engineer, not executed` — otherwise the model would
   re-propose the same code next turn.
3. **Full context window.** History records are full and untruncated: engineer message → the
   complete generated code → the complete outcome (full error text or compliance-violation text).
   No line-collapsing, no size limits — dialog length is bounded by the human. The CODE/ERROR
   blocks of the request keep carrying the original failure on every turn — the anchor the
   engineer's guidance refers to.
4. **Page URL is first-class context.** The current page URL joins every guided regeneration
   request (its own line beside PAGE SNAPSHOT) and the dialog banner. The URL is printed in the
   banner only, not per turn.
5. **Import policy — align the prompt with the runtime.** Generated step code may import from
   playwright.sync_api and the Python standard library; third-party libraries stay forbidden.
   Imports are global only: at the top level of the code block, before `def step`, never inside
   the function body. The rule changes in the shared system prompt (engine and steering together,
   frozen mirrors included) and the cheat sheet gains URL idioms.
6. **Terminal error render — decomposed, snapshot-free, unpadded.** One shared render for all
   terminal failures (engine, healing, steering alike); see the approved template below.
7. **Dialog banner — short and readable.** step, code, error (the new render), URL, screenshot
   path, commands. The 20-line snapshot fragment is removed; the full snapshot stays available
   behind the `snapshot` command and in the LLM request.
8. **`Page.reload: Timeout 30000ms exceeded`** — a consequence of the model's blind context
   (re-doing the whole step), addressed by decisions 3–5; no dedicated timeout handling.

## Examples — approved target artifacts

**Terminal error render template (verbatim, ADR decision 6):**

```
<full exception class name>: <reason>
---
step: <step sentence>
error: <expectation / error kind>
---
received: <actual value, when the underlying error carries one>
cause: <error cause>
Call log:
  - <call log lines>
---
explanation: <verdict explanation>
recommendation: <verdict recommendation>
```

The details section appears only when the underlying error carries received/cause/Call log
(Playwright expect failures do); otherwise only the step section's `error:` line remains. Label
padding (`ljust`) is removed. A page snapshot never appears in any terminal error output.

**Dialog strings (English, as the whole dialog):** the approval prompt `run? [y/N]`; the rejected
turn outcome recorded in the history — `rejected by the engineer, not executed`.

**Import rule for the shared system prompt:** allowed — `playwright.sync_api` and the Python
standard library; forbidden — third-party libraries; imports are global only, at the top level of
the code block, before `def step`, never inside the function body.

**URL idioms for the cheat sheet:** `to_have_url("**/…**")`, `assert "/…" in page.url`.

## Scope

**In scope:**

- The `StepSteering` turn algorithm rewrite: show → approve → execute, rejected-turn history
  records, full untruncated turn history, URL in every regeneration request.
- The banner redesign: URL added, snapshot fragment removed.
- The URL read on the page handle (`PageFacade`, cell `prettyplay/driver`) — the contract change
  is in scope, its mechanics are a design-stage open question.
- The new shared terminal error render in `prettyplay/failures` (`render_terminal_message`,
  `FailureVerdict.render`) and its adoption across engine, healing and steering failure paths.
- The import-policy and URL-idiom changes in the shared system prompt and cheat sheet, together
  with their frozen mirrors — the engine constant (`prettyplay/engine/generator.py`) and the
  steering local copy (`prettyplay/engine/steering/steering.py`) — and the URL/history request
  composition of `prettyplay/llm`.
- The matching updates of the affected practices and cell usages (change together with the
  contracts): `prompts/generation.md`, `prompts/cheatsheet.md`; engine usages `generation.md`
  (the fixed-form import rule) and `healing.md` (the verdict render description); llm usage
  `providers.md` (the regeneration block parity); cell usages `steering.md`, `taxonomy.md`,
  `plumbing.md`, `error_kinds.md` as needed.
- Tests across all four zones per the project conventions.

**Out of scope:**

- A static AST pre-execution check of generated candidates (explicitly deferred by ADR decision 5).
- Any runtime import enforcement mechanism (the policy stays prompt-level).
- Dedicated handling for `Page.reload: Timeout` (ADR decision 8).
- Persisting guidance or dialog history anywhere beyond the live dialog (the guidance stays
  one-shot and never enters the cache file).

## Acceptance Criteria

- The TODO repro heals: Google → query → CAPTCHA fails the step → the engineer solves the CAPTCHA
  manually → guidance "I solved the captcha" → the regenerated code is shown → approved with `y` →
  executed against the live page → the step goes green → the healed step passes the compliance
  gate and is written back to the cache.
- Every guidance turn shows the complete generated code before execution and asks `run? [y/N]`;
  `n`, Enter or `quit` aborts the turn without execution and returns to the guidance prompt.
- A rejected candidate is recorded in the history as a completed turn with the outcome
  `rejected by the engineer, not executed`.
- History records are full and untruncated (message → complete code → complete outcome); the
  request's CODE/ERROR blocks keep carrying the original failure on every turn.
- Every guided regeneration request and the dialog banner carry the current page URL.
- The system prompt (engine and steering mirrors) states the new import policy; the cheat sheet
  carries the URL idioms; generated code with a top-level `import re` before `def step` runs
  without a NameError.
- All terminal failures render through the approved template: full exception class name + reason
  on the first line, the step section, the conditional `received:`/`cause:`/`Call log:` section,
  no label padding, no page snapshot in any terminal error output — one render shared by the
  exception message, the log record and the hook payload.
- The banner shows step, code, error, URL, screenshot path and commands — without the snapshot
  fragment; the `snapshot` command still prints the full accessibility snapshot.
- Interactive attempts consume no generation or healing budgets; the settle window never re-arms
  inside the dialog.
- `pytest tests/ -x` and `ruff check` pass in the project virtualenv.

## Stack

- **Frameworks:** pytest (test runner — existing)
- **Libraries:** playwright (sync API — existing hard dependency; `page.url` read via the
  worker-thread run primitive), openai + anthropic SDKs (existing LLM ports, full parity — request
  composition changes, no SDK-pattern changes), pydantic (existing data models)
- **Infrastructure:** none — no new services, databases or brokers; the interactive REPL stays on
  plain stdin

## External Dependencies

| Component  | Usage file                        | Status                                      |
|------------|-----------------------------------|---------------------------------------------|
| playwright | `.goga/usages/cooks/playwright.md` | updated (import policy paragraph + `page.url` immediate-read rule) |
| openai     | `.goga/usages/cooks/openai.md`     | existing — covers, no change                |
| anthropic  | `.goga/usages/cooks/anthropic.md`  | existing — covers, no change                |
| pydantic   | `.goga/usages/cooks/pydantic.md`   | existing — covers, no change                |

## Risks and Constraints

- The `PageFacade` URL read crosses the driver worker-thread boundary — the plumbing mechanics
  (a property through the run primitive vs. a method) are a design-stage open question; the
  contract constraint "no member proxies" of the handle must hold.
- The frozen local mirrors of the system prompt and cheat sheet — the engine constant
  (`prettyplay/engine/generator.py`) and the steering local copy
  (`prettyplay/engine/steering/steering.py`) — must change together with the practices — the
  manifests mandate it; mirror drift is the main regression risk. Engine and steering share the
  same prompt: an import-rule change affects generation and healing too, not only steering.
- `received:`/`cause:`/`Call log:` extraction from the underlying error text is an open question
  for the design stage; the render template must degrade gracefully when the error carries none.
- The render is shared by all terminal failures — every consumer of terminal failure output
  (exception message, log record, `on_step_failed` hook payload, existing tests asserting the old
  format) is affected by the template change.
- Full untruncated history is bounded by the human only — no size limits may be introduced.
- Python 3.10+ compatibility and all conventions of `.goga/usages/conventions.md` apply.

## Scope Estimate

Single task (approved): one coherent behavioral change, one acceptance scenario, four cells
(`prettyplay/engine/steering`, `prettyplay/failures`, `prettyplay/driver`, `prettyplay/engine`)
plus the request-composition changes of `prettyplay/llm`, roughly 7–9 contract members touched. The internal coupling
is deliberate: the banner consumes the new render; the turn model consumes the URL; splitting
would create sequential blocking between artificial parts. Per-cell decomposition happens in the
downstream contract stages (brainstorm / design / plan), not here.

## Existing Architecture

Affected cells and integration requirements:

- `prettyplay/engine/steering` — `StepSteering.steer`: the turn algorithm rewrite (show → approve
  → execute), full history records, rejected-turn records, URL in the request, banner redesign;
  the CODEMANIFEST algorithm of `steer` changes accordingly.
- `prettyplay/failures` — `render_terminal_message` and `FailureVerdict.render`: the new template;
  the one-render rule (exception message, log record, hook payload — consumers never re-compose)
  stays.
- `prettyplay/driver` — `PageFacade`: a URL read that runs inside the driver worker thread; the
  "no member proxies" constraint of the handle contract holds.
- `prettyplay/engine` — the shared generation system prompt and error-text policy
  (`format_step_error`); the import-policy and URL-idiom changes land here for generation and
  healing alike.
- `prettyplay/llm` — the request-composition changes: the URL input of `generate_step_code`
  (`provider.py`) rendered on its own line beside PAGE SNAPSHOT, and the full untruncated
  history records changing the HISTORY block semantics (`_request.py`, both provider
  implementations). The cell carries no prompt mirrors — the system prompt and cheat sheet
  arrive as parameters from the calling engine; the mirrors live in `prettyplay/engine`
  (`generator.py`) and `prettyplay/engine/steering` (`steering.py`).
- `prettyplay/reporting` — no contract change expected: `on_step_failed` keeps consuming the
  one render verbatim, and the payload content changes with the new template; the manifest
  annotations and hooks docstrings describing the render structure (the primary reason line,
  the step/error block, the verdict block) need a matching wording update; verify no
  re-composition sneaks in.
- Practices changing together with the contracts: `.goga/usages/prompts/generation.md`,
  `.goga/usages/prompts/cheatsheet.md`; engine usages `generation.md` (the fixed-form import
  rule) and `healing.md` (the verdict render description); llm usage `providers.md` (the
  regeneration block parity); cell usages `steering.md`, `taxonomy.md`, `plumbing.md`,
  `error_kinds.md` as needed.

## Notes

- All decisions, rejected alternatives and the acceptance scenario live in the ADR; this task adds
  no new decisions.
- Open questions intentionally left to the design/contract stages (recorded in the ADR): the URL
  plumbing mechanics through `PageFacade`; how the full-history records and the approval gate map
  onto the steering contract's request blocks and turn algorithm; how `received`/`cause`/
  `Call log:` are extracted from the underlying error text and how its class name maps onto the
  first line of the template.
- Dialog strings stay English; the steering dialog remains opt-in, budget-free and never triggered
  on product_defect, in replay-strict, or when the LLM is unavailable.
- During formulation the playwright practice was already updated (import policy paragraph and the
  `page.url` immediate-read rule) — the implementation must not duplicate that edit.
