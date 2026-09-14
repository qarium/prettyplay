# Fix the interactive steering loop: engineer-approved turns, full context window, URL visibility

The interactive steering dialog of prettyplay never healed a terminally stuck step (the TODO
repro: a manually solved Google CAPTCHA followed by "I solved the captcha" still failed every
turn). Root causes found in code: the regenerated code was never shown to the engineer, the
model's request carried no page URL and a context frozen at the original failure (the model
re-read the CAPTCHA-time error forever and re-did the whole step), and the prompt's import rule
("playwright.sync_api only") fights the model's regex instinct with no runtime enforcement —
producing `NameError: name 're' is not defined`. We decided to rebuild the turn model around
engineer approval and a full, honest context window, and to treat these four problems as one
change accepted by the TODO repro scenario.

## Decisions

1. **Turn model — generate, show, approve, execute.** Every guidance turn: regenerate → show
   the generated code to the engineer → confirmation prompt `run? [y/N]` (all dialog strings
   stay English, as today) → on `y` execute against the live page (green → compliance gate →
   cache write-back; red → show the error → back to the guidance prompt); on `n`, Enter or
   `quit` the turn is aborted without execution and the dialog returns to the guidance prompt.
2. **Rejected code is history.** An engineer-rejected candidate enters the history as a
   completed turn with the outcome "rejected by the engineer, not executed" — otherwise the
   model would re-propose the same code next turn and the loop would never converge.
3. **Full context window.** History records are full and untruncated: engineer message → the
   complete generated code → the complete outcome (full error text or compliance-violation
   text). No line-collapsing, no size limits — dialog length is bounded by the human. The
   CODE/ERROR blocks of the request keep carrying the original failure on every turn: it is
   the anchor the engineer's guidance refers to ("I solved the captcha" must stay readable to
   the model). Rejected by the cheaper alternatives (one-line history summaries — the model
   repeats itself; replacing CODE/ERROR with the latest attempt — guidance loses its referent).
4. **Page URL is first-class context.** The current page URL joins every guided regeneration
   request (its own line beside PAGE SNAPSHOT) and the dialog banner. The accessibility
   snapshot (body tree, no URL) was verified fresh per turn — the blindness was the missing
   URL plus the frozen CODE/ERROR, not snapshot staleness. The URL is printed in the banner
   only, not per turn.
5. **Import policy — align the prompt with the runtime.** Generated step code may import from
   playwright.sync_api and the Python standard library; third-party libraries stay forbidden.
   Imports are global only: at the top level of the code block, before `def step`, never
   inside the function body. Nothing in the execution environment restricts imports (verified:
   plain `exec`, full builtins, no audit hooks) — the old prompt-only ban produced NameErrors,
   not safety. The rule changes in the shared system prompt (engine and steering together) and
   the cheat sheet gains URL idioms (`to_have_url("**/…**")`, `assert "/…" in page.url`). A
   static AST pre-execution check of candidates was considered and deferred.
6. **Terminal error render — decomposed, snapshot-free, unpadded.** One shared render for all
   terminal failures (engine, healing, steering alike):

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
   (Playwright expect failures do); otherwise only the step section's `error:` line remains.
   Label padding (`ljust`) is removed — it ignored terminal width. A page snapshot never
   appears in any terminal error output.
7. **Dialog banner — short and readable.** step, code, error (the new render), URL, screenshot
   path, commands. The 20-line snapshot fragment is removed from the banner (the TODO itself:
   it "adds no informative value"); the full snapshot stays available on demand behind the
   `snapshot` command and in the LLM request.
8. **`Page.reload: Timeout 30000ms exceeded`** — treated as a consequence of the model's blind
   context (re-doing the whole step), addressed by decisions 3–5; no dedicated timeout
   handling is introduced.

## Acceptance

The TODO repro scenario: Google → query → CAPTCHA fails the step → the engineer solves the
CAPTCHA manually → "I solved the captcha" → the step goes green → the healed step passes the
compliance gate and is written back to the cache.

## Open questions (out of scope here — for the design/contract stages)

- How the current URL is plumbed to the dialog and the request (the page handle currently
  exposes no URL read; adding one is a contract change, not decided here).
- How the full-history records and the approval gate map onto the steering contract's request
  blocks and turn algorithm.
- How `received`/`cause`/`Call log:` are extracted from the underlying error text.
