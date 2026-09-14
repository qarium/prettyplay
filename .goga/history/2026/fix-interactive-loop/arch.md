# Architecture Plan — fix-interactive-loop

Engineer-approved steering turns, full context window, URL visibility. Source of truth: the
approved ADR (`adr.md`) and task file (`task.md`) of this topic; all eight decisions are
binding for this plan. Language: python (`goga-cell-python`). Base usages for every manifest:
`conventions: .goga/usages/conventions.md` + base annotation «Use `conventions` for code
writing rules and testing.» The playwright practice (`.goga/usages/cooks/playwright.md`) is
already updated (import policy + `page.url` immediate-read rule) — do NOT duplicate that edit.

Key user decisions taken during brainstorm:
1. Error-text decomposition lives in `prettyplay/failures` as a new routine (q1=A).
2. HISTORY stays `list[str]` of complete records composed by steering (q4=A).
3. Render line 1 carries the full class name of the TERMINAL failure + the authored reason (q6=A);
   the underlying error decomposes into the `error:` headline + conditional details section.
4. `PageFacade` URL read is a property `url -> str` (q7=A).

## Implementation Order

| # | Cell | Modified/Created | Rationale |
|---|---|---|---|
| 1 | prettyplay/failures | modified (+2 members) | Leaf (no Imports); every other changed cell consumes its render |
| 2 | prettyplay/driver | modified (+1 property) | Depends only on config (unchanged); steering consumes the new `url` |
| 3 | prettyplay/llm | modified (signature + parity) | Depends on config + failures (ready); steering consumes the new input |
| 4 | prettyplay/engine | modified (document level) | Fixed-form import policy; prompt practices + engine mirror change here |
| 5 | prettyplay/engine/steering | modified (algorithm) | Consumes failures render, driver url, llm page_url, engine members + steering mirror |
| 6 | prettyplay/reporting | modified (wording) | Wording-only leaf; last to keep the render description truthful at all times |
| 7 | prettyplay (root) | modified (usage wording only) | Docs describe the render; stays truthful — changes last, after the render it describes exists |

Practice files `.goga/usages/prompts/generation.md` and `.goga/usages/prompts/cheatsheet.md`
change together with step 4/5 (the frozen mirrors are mandated by the engine and steering
manifests — mirror drift is the main regression risk).

## Artifacts

### 1. prettyplay/failures (modified)

**CODEMANIFEST** — `prettyplay/failures/CODEMANIFEST`:

Header:
- ADD to `Usages`:
  ```yaml
    playwright: .goga/usages/cooks/playwright.md
  ```
- ADD after the base annotation line:
  ```yaml
    Use `playwright` for the error message shapes the decomposition recognizes.
  ```
- REPLACE the three render paragraphs (template, one-render, colon rule) with:
  ```yaml
    The rendered message of a terminal failure follows the single structured template: the first line — the full class name of the terminal failure and the authored reason; then --- separated blocks: the step section (step/error), the conditional details section (received/cause/Call log), the verdict block. No label padding; a page snapshot never appears in any terminal error output.
    One render — produced at exception construction through `render_terminal_message` from the decomposed parts of the underlying error — feeds the exception message, the log record and the on_step_failed hook payload; consumers never re-compose.
    Reason texts authored by the engines and the executor are written without colons — the authored-reason part of the first line stays parseable.
  ```

Body — ADD two new types (after `PrettyplayError`):

```yaml
"decompose_error_text(error: str) -> parts: ErrorParts":
  location: errors.py
  annotations: |
    Decompose the full underlying error text of a failed step into the parts of the
    terminal render — recognition only, no state, no I/O.

    `error`: the full underlying error text as formatted by the engine error-text
    policy; empty — all parts empty.
    `parts`: the decomposed parts.

    Algorithm:
    1. An empty `error` yields all-empty parts
    2. Extract the leading exception class prefix — a dotted-identifier head of the
    first line (see `playwright` for the error surface); present — it becomes
    `class_name`, the first-line remainder becomes `reason`; absent — the whole first
    line becomes `reason`, `class_name` stays empty
    3. In the remainder extract the detail parts by their fixed shapes (see
    `playwright`): the received line(s), the cause line, the Call log block — every
    extracted part is removed from the reason tail
    4. Unrecognized shapes leave the parts empty — graceful degradation, never a raise

    Requirements:
    - Pure function: deterministic on `error` alone
    - Multi-line detail values are preserved verbatim inside their parts

"ErrorParts(class_name: str, reason: str, received: str, cause: str, call_log: str)":
  location: errors.py
  annotations: |
    The decomposed parts of a terminal failure's underlying error — the data shape
    `render_terminal_message` renders.

    `class_name`: the exception class prefix of the underlying error; empty — the
    text carries none.
    `reason`: the underlying error headline — the expectation of a failed check or
    the message head of a typed error.
    `received`: the actual-value detail; empty — absent.
    `cause`: the error-cause detail; empty — absent.
    `call_log`: the Call log block; empty — absent.

    Requirements:
    - pydantic v2, kw_only, empty defaults (see `conventions`)
  properties:
    "class_name -> str": |
      The exception class prefix of the underlying error; empty — none.
    "reason -> str": |
      The underlying error headline.
    "received -> str": |
      The actual-value detail; empty — absent.
    "cause -> str": |
      The error-cause detail; empty — absent.
    "call_log -> str": |
      The Call log block; empty — absent.
```

Body — REPLACE `render_terminal_message` entirely:

```yaml
"render_terminal_message(error_class: str, reason: str, step_text: str, error: str, verdict: FailureVerdict | None) -> text: str":
  location: errors.py
  annotations: |
    Compose the single structured render of a terminal failure — the one text used
    by the exception message, the log record and the on_step_failed hook payload.

    `error_class`: the full class name of the terminal failure being rendered —
    passed by the raising type; the render embeds it so log records and hook
    payloads carry the kind without the runner prefix.
    `reason`: the authored primary reason — written without colons.
    `step_text`: the sentence of the failed step; empty — no step line.
    `error`: the full underlying error text; decomposed through
    `decompose_error_text`; empty — no error line, no details section.
    `verdict`: the optional `FailureVerdict`; None or an empty render — no verdict
    block.
    `text`: the rendered message.

    Algorithm:
    1. First line: `error_class` and `reason`
    2. Step section: the --- separator, then the step: line for a non-empty
    `step_text` and the error: line — the decomposed headline: class_name and
    reason of the parts when class_name is non-empty, the parts reason alone
    otherwise
    3. Details section: only when at least one of received/cause/call_log of the
    parts is non-empty — the --- separator, then the received: line, the cause:
    line, the Call log: block with its lines indented
    4. Verdict section: when `verdict` renders non-empty — the --- separator, then
    the verdict block render
    5. Join the lines

    Requirements:
    - The block order is fixed: first line, step/error, details, verdict
    - The details section is omitted entirely when no detail part is present
    - Both step and error empty — the whole step section is omitted, no bare
    separator
    - The render ends without a trailing separator

    Constraints:
    - Never embed the step code — it lives in the cache and the log
    - Never embed a page snapshot in any terminal error output
    - No label padding — labels render at column zero
```

Body — REPLACE the `render` method of `FailureVerdict`:

```yaml
  methods:
    "render() -> text: str": |
      Render the verdict block of the structured terminal message — the explanation
      and recommendation lines.

      `text`: the rendered verdict block; empty when both fields are empty.

      Algorithm:
      1. Build one line per non-empty field: explanation: and recommendation: — no
      column alignment, labels at column zero; multi-line continuations indent by
      two spaces
      2. Join the lines

      Requirements:
      - The category line is dropped: the category travels in the structured fields
      of the on_step_verdict event, never in the render
      - Labels are stable lowercase words — integrators parse them
```

Body — `ProductDefectError` and `IncurableStepError`: signatures and properties unchanged;
REPLACE in Requirements (both, with the matching param name):

```yaml
    - The rendered message is composed through `render_terminal_message` from `message`, `step_text`, `error` and `verdict`, passing its own full class name as the error class
```

(IncurableStepError variant names `reason` instead of `message`; the fallback-recommendation
requirement stays.)

Footer: unchanged.

**Cell usage file** — `prettyplay/failures/.usages/taxonomy.md`: REPLACE the section
«The structured failure message» with:

```md
## The structured failure message

ProductDefectError and IncurableStepError render one structured message — the same text
reaches the exception message, the log record and the `error` field of the `on_step_failed`
hook event:

```text
prettyplay.failures.errors.ProductDefectError: the "Sign in" button stayed invisible after submitting the form
---
step: Check that the "Sign in" button appears
error: Locator expected to be visible
---
received: <actual value — only when the underlying error carries one>
cause: <error cause>
Call log:
  - waiting for locator("button[name='Sign in']")
---
explanation: the page has no element with role button and name "Sign in"
recommendation: check the selector or the button text in the application
```

- The first line carries the full class name of the terminal failure and the authored
  reason — the render is self-sufficient in log records and hook payloads where no runner
  prefix exists
- The `step:`/`error:` section carries the step sentence and the decomposed headline of the
  underlying error (its expectation or kind); for failed checks the `error:` text never
  carries an AssertionError prefix; the section is omitted entirely when both are empty
- The details section — `received:`/`cause:`/`Call log:` — appears only when the underlying
  error carries those parts (Playwright expect failures do); otherwise the whole section is
  omitted
- No label padding anywhere — labels render at column zero; multi-line verdict values
  indent by two spaces
- A page snapshot never appears in any terminal error output
- The `category:` line is gone — the category travels in the structured fields of
  `on_step_verdict`, never in the render; IncurableStepError without a verdict keeps the
  fallback `recommendation:` line
- The failed step's code is never included — it lives in the cache and the `code` field of
  IncurableStepError
```

All other sections of taxonomy.md unchanged.

**Practice file** — `.goga/usages/cooks/playwright.md` (project level), section «Error kinds —
the driver error surface», ADD after the kinds list — the recognition shapes the new
decomposition consumes (a new edit; the already-applied import-policy and `page.url` edits
are NOT duplicated):

```md
Message anatomy of a failed expectation — the fixed shapes the terminal render decomposes:

- the expectation headline — the first line of the failed `expect(...)` message
  (e.g. `Locator expected to be visible`)
- the actual-value line(s) — `Actual value: …` under the headline
- the error-cause line — `Caused by: …` chained under the headline
- the Call log block — a `Call log:` line followed by indented `- waiting for …`
  / `- verifying …` entries

A message may carry any subset; the shapes are recognized by their fixed prefixes,
never by position alone.
```

### 2. prettyplay/driver (modified)

**CODEMANIFEST** — `prettyplay/driver/CODEMANIFEST`:

Header: unchanged (Imports and Usages stay; `playwright` already connected).

Global Annotations — REPLACE the plumbing paragraph with:

```yaml
  The page handle of this cell is internal runtime plumbing — the worker-thread run primitive, the URL read, the accessibility snapshot, the screenshot, the context close, the only crossing points of the worker boundary; the named plumbing members are exactly these five — run, url, aria_snapshot, screenshot, close; no proxying or delegation of any other page member exists — the handle is plumbing, not a managed surface.
```

Body — `PageFacade`: ADD the properties block (before `methods`):

```yaml
  properties:
    "url -> str": |
      The current URL of the page — an immediate read (see `playwright`), executed
      inside the driver worker thread as one unit through the run primitive of this
      handle.

      Requirements:
      - The value is the genuine page.url of the live page; an empty string never
      occurs on a live page
      - The calling thread never adopts the Playwright event loop
      - Reads run sequentially with every other unit of the session
```

All other members, `DriverSession`, `is_pollable_failure`, footer: unchanged.

**Cell usage file** — `prettyplay/driver/.usages/plumbing.md`:

- Handle members table gains the row:
  ```md
  | page.url | the current page URL — an immediate read through the worker-thread run primitive |
  ```
  (placed between `page.run(action)` and `page.aria_snapshot()`)
- ADD after the `page.run` example in «The worker boundary»:
  ```md
  Immediate reads such as `page.url` cross the boundary the same way — one unit through the
  run primitive, plain string back; the calling thread never adopts the Playwright event loop.
  ```

### 3. prettyplay/llm (modified)

**CODEMANIFEST** — `prettyplay/llm/CODEMANIFEST`:

Header: unchanged.

Global Annotations — ADD two paragraphs (after the cheat-sheet parity paragraph):

```yaml
  The page-URL input participates in both provider implementations with identical semantics: a non-empty page_url of a generation request renders as its own PAGE URL line immediately after the PAGE SNAPSHOT block of the user content; None or empty — no line; a parity requirement, not a capability difference.
  The HISTORY block renders every accumulated steering turn record verbatim — each record is a complete multi-line turn (engineer message, complete generated code, complete outcome) composed by the calling steering; no collapsing, no size limits; a parity requirement, not a capability difference.
```

Body — `LLMProvider.generate_step_code`: REPLACE the signature and the two param docs; ADD
one Requirements bullet:

```yaml
    "generate_step_code(prompt: str, user_instructions: str, step_text: str, previous_steps: list[str], snapshot: str, page_url: str | None, screenshot: bytes | None, cheat_sheet: str, existing_code: str | None, error: str | None, recommendation: str | None, guidance: str | None, guidance_history: list[str]) -> code: str": |
```

```yaml
      `page_url`: the current URL of the page; non-empty — rendered by the provider
      implementations as its own PAGE URL line immediately after the PAGE SNAPSHOT block,
      identically in both; None — no line; supplied by the interactive steering only.
```

```yaml
      `guidance_history`: the accumulated steering turns — each a complete multi-line turn
      record: the engineer message, the complete generated code, the complete outcome;
      composed by the calling steering; non-empty — rendered as a separate HISTORY block
      after the USER GUIDANCE block, every record verbatim, no collapsing, no size limits;
      empty — no block.
```

```yaml
      - The PAGE URL line renders in the scenario part — immediately after the PAGE
        SNAPSHOT block; the fixed order of the regeneration tail (CODE, ERROR,
        RECOMMENDATION, USER GUIDANCE, HISTORY) is unchanged
```

(The existing requirement «The new inputs take no part in step addressing: a cached step
never regenerates because they changed» stays the single addressing rule — `page_url`
is covered by it as a new input.)

Body — `OpenAIProvider` and `AnthropicProvider`, Algorithm step 1: EXTEND the request-build
wording with:

```yaml
    …the scenario inputs; a non-empty page_url renders as its own PAGE URL line immediately
    after the PAGE SNAPSHOT block; the HISTORY block renders every accumulated steering
    turn record verbatim — complete multi-line records, no collapsing; a non-empty input
    renders its named block, identically in both implementations…
```

All other types and footer: unchanged.

**Cell usage file** — `prettyplay/llm/.usages/providers.md`: in «Parity», REPLACE the
regeneration-block paragraph and ADD one paragraph:

```md
Regeneration block parity: a regeneration request may carry extra blocks after CODE and ERROR — RECOMMENDATION (the classification diagnosis), USER GUIDANCE (the engineer message of the interactive steering) and HISTORY (the accumulated steering turns), in this fixed order. Every HISTORY record is a complete multi-line turn — engineer message, complete generated code, complete outcome — rendered verbatim, never collapsed, never size-limited; the dialog length is bounded by the human. Both providers render every non-empty block identically at the same position. A parity requirement, not a capability difference.

Page-URL parity: a generation request with a non-empty page URL renders it as its own PAGE URL line immediately after the PAGE SNAPSHOT block — identically in both providers. The URL reaches guided regeneration requests of the interactive steering only. A parity requirement, not a capability difference.
```

### 4. prettyplay/engine (modified, document level)

**CODEMANIFEST** — `prettyplay/engine/CODEMANIFEST`:

Header: unchanged. Body: NO type changes (all six types unchanged).

Implementation note — the request composition of `StepGenerator` passes `page_url=None`
in every `generate_step_code` call (the URL input is steering-only, uniform with
`guidance=None`); no other engine code changes.

Global Annotations — REPLACE inside the fixed-form paragraph:

old fragment:
```yaml
  the function body works through the standard Playwright sync API, importing from playwright.sync_api only — a prompt rule carried by `system_prompt`;
```

new fragment:
```yaml
  the function body works through the standard Playwright sync API; imports allowed from playwright.sync_api and the Python standard library only — third-party libraries are forbidden; imports are global only: at the top level of the code block, before def step, never inside the function body — a prompt rule carried by `system_prompt`, no runtime enforcement;
```

Global Annotations — REPLACE inside the terminal-failures paragraph:

old fragment:
```yaml
  reason and message texts are authored without colons — the first line of the rendered message is the primary reason alone;
```

new fragment:
```yaml
  reason and message texts are authored without colons — the first line of the rendered message carries the terminal failure's full class name and the authored reason;
```

Footer: unchanged.

**Practice file** — `.goga/usages/prompts/generation.md` (project level):

- REPLACE the import rule line:
  ```md
  - Import from playwright.sync_api and the Python standard library only — no third-party
    libraries; imports are global only: at the top level of the code block, before `def
    step`, never inside the function body
  ```
  (replaces «- Import only from playwright.sync_api — no other imports, no other libraries»)
- ADD to the input list after `- PAGE SNAPSHOT:`:
  ```md
  - PAGE URL: the current URL of the page, when present
  ```
- REPLACE the HISTORY input line:
  ```md
  - HISTORY: the accumulated steering turns, when present — each record carries the full
    engineer message, the complete generated code and the complete outcome of the turn
  ```

**Practice file** — `.goga/usages/prompts/cheatsheet.md` (project level):

- «Waiting assertions — expect chains»: keep `to_have_url("**/dashboard")`
- «Immediate reads with plain asserts»: ADD `assert "/dashboard" in page.url`
- «Navigation and waits»: note `page.url` as an immediate read beside the waiting forms

Frozen mirrors (mandated by the manifests, change together with the practices): the engine
constant in `prettyplay/engine/generator.py` and the steering local copy in
`prettyplay/engine/steering/steering.py`.

**Cell usage files**:

- `prettyplay/engine/.usages/generation.md` — «The fixed form» opening replaced:
  ```md
  Generated code is one function receiving exactly one argument — the genuine sync Playwright Page — importing from
  playwright.sync_api and the Python standard library only (third-party libraries forbidden; imports global only, at the
  top level of the code block, before `def step`, never inside the function body) and working through the standard API: …
  ```
  (rest of the section unchanged)
- `prettyplay/engine/.usages/healing.md` — «Verdicts» first sentence replaced:
  ```md
  Every terminal failure carries its verdict in full and the full underlying error in the error field: the exception
  message is the structured render — the first line carries the full class name of the terminal failure and the authored
  reason, then the `---` separated step/error section, the conditional received/cause/Call log details section and the
  unpadded verdict block; the same text reaches on_step_verdict (structured fields) and the log record. IncurableStepError
  also carries the failed step code in the code field — a programmatic field, never rendered.
  ```

### 5. prettyplay/engine/steering (modified)

**CODEMANIFEST** — `prettyplay/engine/steering/CODEMANIFEST`:

Header: unchanged (Imports stay; `system_prompt`/`cheat_sheet` connections stay).

Global Annotations — REPLACE the turn paragraph and ADD the new paragraphs:

```yaml
  Every guidance turn is a regeneration request carrying a USER GUIDANCE block plus the conversation history; the complete generated code is shown to the engineer before any execution and confirmed with the `run? [y/N]` prompt — nothing runs unseen; `y` executes against the live page, `n`, Enter or `quit` aborts the turn without execution; every executed turn has a measurable green or red outcome; no free-form conversation.
  An engineer-rejected candidate enters the history as a completed turn with the outcome `rejected by the engineer, not executed` — the model never re-proposes it blind.
  The history records are full and untruncated: the engineer message, the complete generated code, the complete outcome (the full error text or the compliance-violation text); no line-collapsing, no size limits — the dialog length is bounded by the human.
  The CODE and ERROR blocks of every request keep carrying the original failure — the anchor the engineer guidance refers to.
  The current page URL joins every guided regeneration request (its own line beside the page snapshot) and the dialog banner — the banner only, never per turn; the banner carries the step, the failed code, the terminal error render, the URL, the screenshot path and the commands — never a snapshot fragment; the full snapshot stays behind the `snapshot` command and in the request.
```

(The paragraphs on budget-free attempts, one-shot guidance, nothing hangs, the compliance
gate and the opt-in conditions stay unchanged.)

Body — `StepSteering.steer`: signature unchanged; REPLACE the annotation:

```yaml
    "steer(failure: IncurableStepError, identity: StepIdentity, previous_steps: list[str], page: PageFacade) -> healed: CachedStep | None": |
      Run the steering dialog over a terminal failure.

      `failure`: the terminal failure about to propagate — the source of the step sentence, the failed code, the underlying error and the verdict.
      `identity`: the address of the stuck step — the healed step is written back under it.
      `previous_steps`: the sentences of the previous steps of the test — scenario context for regeneration.
      `page`: the live page facade of the test.
      `healed`: the healed cached step on a successful guided execution; None — the dialog declined or died: the caller propagates the original failure.

      Algorithm:
      1. Render the context banner once: the step sentence, the failed code, the terminal error render of `failure`, the current URL read from `page`, a screenshot path, the commands — no snapshot fragment
      2. Read the guidance line; quit, EOF, SIGINT or an unreadable stdin — return None
      3. A local command runs without the LLM: snapshot — the full accessibility snapshot; screenshot — a full PNG written to a temporary file with the path printed; error and code — the stored texts; back to step 2
      4. A guidance message builds one regeneration request via the provider: `system_prompt` as the system prompt, the cheat-sheet from `cheat_sheet`, the step sentence of `failure` and `previous_steps` as the scenario context, the fresh accessibility snapshot plus the screenshot when the project settings enable screenshots, the current URL read from `page` as the page URL input, the user instructions — the effective config generation_prompt — when non-empty, existing_code and error taken from the original failure of `failure` on every turn, the message as the guidance and the accumulated turns as the guidance history — every record the full engineer message, complete code and complete outcome
      5. Show the complete generated code to the engineer, then the confirmation prompt `run? [y/N]`: `y` — proceed to step 6; `n`, Enter or `quit` — the turn is aborted without execution, the rejected candidate enters the history as a completed turn with the outcome `rejected by the engineer, not executed`, back to step 2
      6. Execute the candidate via `run_step_code` against `page` — the whole step runs inside the driver worker thread; the settle window never re-arms inside the dialog
      7. Success: gate the executed candidate through `check_step_compliance` — the gate switch off or empty generation instructions yield an empty findings list with zero provider calls. An empty findings list: build `CachedStep` with `identity`, save it to the cache, report on_healed with an explanation naming the interactive healing, return the healed step. A high finding: no write-back — show the violation in the dialog (the finding instruction and explanation), append the completed turn — message, complete code, complete violation text — to the history, return to step 2. Medium and low findings pass with a WARNING naming the instructions, then the write-back. The gate hard failures — provider unavailability and a malformed verdict — end the dialog after showing the gate failure line in the dialog and logging a WARNING through the library logger naming the step and the gate failure: return None, the original terminal failure propagates; nothing is cached
      8. A failed execution: show the complete error, append the completed turn — message, complete code, complete outcome — to the history, return to step 2 — no re-execution of the same code, the settle window never re-arms
      9. Provider unavailability of the request: the dialog ends, return None

      Requirements:
      - The write-back happens only after a successful execution and a passed compliance gate
      - No code executes without the engineer approval of this turn
      - A rejected or failed turn always enters the history before the guidance prompt reopens
      - No generation or healing budget is consumed; no polling applies
      - The dialog never outlives the failure: every exit path either heals or returns None

      Constraints:
      - Never persist the guidance into the cache file
      - Never introduce history size limits or line collapsing
```

Footer: unchanged.

**Cell usage file** — `prettyplay/engine/steering/.usages/steering.md`: REPLACE the section
«The dialog» with:

```md
## The dialog

```text
── step "click Checkout" — about to raise IncurableStepError ──────────
code:     videos = page.get_by_role("listitem")
          expect(videos.first).to_be_visible()
          assert videos.count() > 1
error:    prettyplay.failures.errors.IncurableStepError: the generation budget is exhausted
          ---
          step: click Checkout
          error: TimeoutError: Timeout 10000ms exceeded
          ---
          received: … / cause: … / Call log: …
          ---
          explanation: the button is behind the "Terms" modal
          recommendation: dismiss the modal first, then click
url:      https://shop.example.com/cart
shot:     /tmp/prettyplay-shot-abc123.png

commands: snapshot | screenshot | error | code | quit
guidance> the modal has id=terms — close it via page.get_by_label("Close").click() first
⟳ regenerating with USER GUIDANCE — the complete candidate code is printed
run? [y/N] y
✓ step green — healed step written to the cache
```

- The banner shows the step, the failed code, the terminal error render, the current page
  URL, the screenshot path and the commands — no snapshot fragment; the full snapshot
  stays behind the `snapshot` command and in every request
- Local commands answer without the LLM: `snapshot` prints the full accessibility snapshot,
  `screenshot` writes a full PNG to a temporary file and prints the path, `error` and `code`
  reprint the stored texts
- Every other line is guidance: one regeneration request carrying a USER GUIDANCE block,
  the current page URL and the full conversation history — the original failure stays the
  CODE/ERROR anchor of every request
- Every turn shows the complete generated code and asks `run? [y/N]`: `y` executes against
  the live page; `n`, Enter or `quit` aborts the turn without execution and the guidance
  prompt reopens — the rejected candidate lands in the history as a completed turn with the
  outcome `rejected by the engineer, not executed`
- Every completed turn — executed or rejected — enters the history in full: the engineer
  message, the complete code, the complete outcome; nothing is collapsed or truncated
- A red turn shows the complete error and returns to the guidance prompt immediately — no
  re-execution loop, the settle window does not re-arm inside the dialog
- `quit`, EOF (Ctrl+D), SIGINT (Ctrl+C) and an unreadable stdin (a captured CI stream) end
  the dialog and the original terminal failure propagates — nothing hangs
```

Sections «When the dialog opens», «Effects», «The compliance gate of a guided heal» and
«Rules» stay unchanged.

### 6. prettyplay/reporting (modified, wording only)

**CODEMANIFEST** — `prettyplay/reporting/CODEMANIFEST`:

- Global Annotations — REPLACE the render sentence:
  ```yaml
    The error field of the on_step_failed event and its log record carry the full structured render of the terminal failure — the same multi-line text the raised exception carries: the first line with the full class name of the terminal failure and the authored reason, the --- separated step/error section, the conditional received/cause/Call log details section and the unpadded verdict block; integrators display it verbatim.
  ```
- `on_step_failed` method annotation — REPLACE with:
  ```yaml
      The step failed; `error` is the full rendered failure message — the same structured
      text carried by the raised exception and the log record: the first line with the
      full class name of the terminal failure and the authored reason, the --- separated
      step/error section, the conditional received/cause/Call log details section and the
      unpadded verdict block; display it verbatim.
  ```

No signature changes. Footer unchanged.

**Cell usage file** — `prettyplay/reporting/.usages/hooks.md`: REPLACE the paragraph under
the events table (line 24):

```md
`error` carries the full structured render of the terminal failure — the same multi-line text the raised exception carries and the log record writes: the first line with the full class name of the terminal failure and the authored reason, the `---` separated step/error section, the conditional received/cause/Call log details section and the unpadded verdict block. Display it verbatim in reports; do not parse it — structured data arrives through on_step_verdict fields. In strict mode on_generation_started and on_healing_started never fire: classification is the only LLM call.
```

### 7. prettyplay (root — usage wording only)

No CODEMANIFEST change (the root annotations are render-agnostic and stay truthful); two
usage fragments describe the old render and change with it.

**Cell usage files**:

- `prettyplay/.usages/steps.md` — REPLACE the render fragment of the reporting sentence:
  ```md
  A failed step renders one structured message — the first line with the full class name of
  the terminal failure and the authored reason, the `---` separated step/error section, the
  conditional received/cause/Call log details section and the unpadded verdict block —
  identical in the runner output, the log and the on_step_failed hook.
  ```
- `prettyplay/.usages/lifecycle.md` — REPLACE the first sentence of the render paragraph:
  ```md
  ProductDefectError and IncurableStepError render one structured message — the first line
  with the full class name of the terminal failure and the authored reason, the `---`
  separated step/error section, the conditional received/cause/Call log details section and
  the unpadded verdict block — and the same text reaches the exception message, the
  on_step_failed hook event and the log.
  ```

## Dependency Map

```text
config      failures    reporting          (leaves; ★ = modified)
   │            │            │
   ▼            │            │
  driver★       │            │
   │            ▼            │
   │          llm★ ◄── failures
   ├── cache ◄── config, reporting
   └── polling ◄── driver
        │
        ▼
     engine★ ◄── config, reporting, failures, driver, cache, llm, polling
        │
        ▼
 engine/steering★ ◄── cache, config, driver(PageFacade.url — NEW consumption),
        │               engine(run_step_code, check_step_compliance),
        │               failures(IncurableStepError), llm(generate_step_code —
        │               page_url — NEW consumption), reporting
        ▼
  prettyplay (root — usage wording only, no contract change)
```

New inter-cell imports: NONE. New members travel over existing edges: `PageFacade.url`
(driver → steering, engine), `generate_step_code.page_url` (llm → steering),
`ErrorParts`/`decompose_error_text` (internal to failures).

## Verification Checklist

Per artifact, after implementation:

1. **prettyplay/failures**
   - `goga lint` passes; render fixtures: a Playwright expect failure renders the details
     section; an error without details omits it entirely; empty step+error omits the step
     section; no trailing separator; no `ljust` anywhere
   - `render_terminal_message` output is byte-identical across exception message, log
     record and hook payload (one render, consumers never re-compose)
   - ProductDefectError/IncurableStepError pass their own full class name; authored reasons
     stay colon-free; IncurableStepError fallback recommendation intact without a verdict
   - Unit tests: decompose_error_text pure-function cases (typed head, expect-failure tail
     with received/cause/Call log, absent parts, empty input)
2. **prettyplay/driver**
   - `url` reads the genuine page.url inside the worker thread (re-entrant crossing still
     rejected); calling thread never adopts the event loop; plumbing table updated
3. **prettyplay/llm**
   - Both providers render the PAGE URL line immediately after PAGE SNAPSHOT, identically
     (parity test); HISTORY records render verbatim, multi-line, uncollapsed; block order
     unchanged; page_url takes no part in step addressing
4. **prettyplay/engine**
   - The frozen mirror equals the `system_prompt` practice text; the fixed-form annotation
     states the new import policy; a generated candidate with top-level `import re` before
     `def step` runs without NameError
   - The engine request composition passes `page_url=None` (the terminal-failures
     annotation carries the new first-line wording)
5. **prettyplay/engine/steering**
   - The steering local prompt mirror equals the practice text (no drift)
   - Turn flow: code shown in full → `run? [y/N]`; `n`/Enter/`quit` at the approval prompt
     aborts without execution and records the rejected turn; executed turn red → full error
     + full record in history; original CODE/ERROR anchor on every request; URL in every
     request and in the banner only; settle never re-arms; budgets untouched
   - Banner shows step, code, error, URL, screenshot path, commands — no snapshot fragment;
     `snapshot` command prints the full snapshot
6. **prettyplay/reporting**
   - Render wording matches the new template; no re-composition in consumers
7. **prettyplay (root)**
   - steps.md and lifecycle.md render wording matches the new template; the CODEMANIFEST
     is untouched
8. **Practices**
   - prompts/generation.md import rule + PAGE URL + HISTORY lines in place; cheatsheet URL
     idioms present; cooks/playwright.md: the import-policy and `page.url` edits NOT
     duplicated, the Error kinds anatomy ADD applied
9. **Global**
   - `pytest tests/ -x` and `ruff check` pass in the project virtualenv
   - The TODO repro scenario heals end-to-end (acceptance): CAPTCHA solved manually →
     guidance → code shown → `y` → green → compliance gate → cache write-back
