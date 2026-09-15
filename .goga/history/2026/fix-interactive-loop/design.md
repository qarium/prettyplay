# Design Document: `fix-interactive-loop`

Rebuild of the interactive steering loop around engineer-approved turns, a full context window and
URL visibility — plus the shared decomposed terminal-error render, the plumbing URL read, the
import-policy alignment and the LLM request-composition changes. Source of truth: the CODEMANIFEST
contracts as materialized by the apply-architecture stage; the ADR (`.goga/history/2026/fix-interactive-loop/adr.md`,
all eight decisions) behind them.

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/failures/CODEMANIFEST` — new practice `playwright` (error-shape recognition); new
  Routine `decompose_error_text`; new Entity `ErrorParts`; `render_terminal_message` gains the
  `error_class` parameter and the decomposed details section; `FailureVerdict.render` drops column
  alignment; both terminal mutations pass their own class name into the render.
- `prettyplay/driver/CODEMANIFEST` — `PageFacade` gains the `url` property (worker-thread immediate
  read); the plumbing paragraph fixes the named members at exactly five: run, url, aria_snapshot,
  screenshot, close.
- `prettyplay/llm/CODEMANIFEST` — `LLMProvider.generate_step_code` gains `page_url: str | None`
  (after `snapshot`); `guidance_history` semantics become full multi-line turn records; two new
  parity paragraphs (PAGE URL line, HISTORY verbatim); both provider Algorithms extended identically.
- `prettyplay/engine/CODEMANIFEST` — the fixed-form import policy (playwright.sync_api + the Python
  standard library, global imports only, prompt rule, no runtime enforcement); the first-line render
  fragment; `StepGenerator.generate` step 3 passes `page_url` None.
- `prettyplay/engine/steering/CODEMANIFEST` — the turn model (generate → show → approve → execute);
  rejected-turn history records; full untruncated history; URL in every request and in the banner;
  the `steer` Algorithm rewritten to nine steps.
- `prettyplay/reporting/CODEMANIFEST` — wording only: the render description in the document
  annotations and in `on_step_failed` names the new template sections.

### New Entities

- `decompose_error_text(error: str) -> parts: ErrorParts` — pure recognition of the underlying
  error text into render parts. Location: `prettyplay/failures/errors.py`.
- `ErrorParts(class_name, reason, received, cause, call_log)` — the decomposed parts data shape.
  Location: `prettyplay/failures/errors.py`. pydantic v2, `kw_only=True`, empty-string defaults.
- `PageFacade.url -> str` — property; the current URL read as one unit inside the driver worker
  thread. Location: `prettyplay/driver/page.py`.

### Changed Entities

- `render_terminal_message(error_class, reason, step_text, error, verdict)` — first line =
  `error_class` + authored reason; the `error:` line becomes the decomposed headline; a conditional
  `received:`/`cause:`/`Call log:` details section appears; no label padding.
- `FailureVerdict.render()` — labels at column zero, two-space continuation indent, category still
  dropped.
- `PrettyplayError::ProductDefectError` / `PrettyplayError::IncurableStepError` — pass their own
  full class name as `error_class` to the render.
- `LLMProvider.generate_step_code` (+ both SDK implementations, + `build_fields_text`) — the
  `page_url` input; HISTORY carries verbatim multi-line records.
- `StepGenerator._request` (implementation-level) — passes `page_url=None`, uniform with
  `guidance=None`.
- `StepSteering.steer` — the nine-step turn algorithm with the approval gate, full history records
  and the URL plumbing; the banner redesign.

### Deleted Entities

- None. Implementation-level deletions inside `prettyplay/engine/steering/steering.py`:
  `_snapshot_fragment`, `_SNAPSHOT_FRAGMENT_LINES` and `_first_line` become dead code once the
  banner drops the fragment and the history stops collapsing — remove them (ruff would flag them).

### Usages and Annotations Changes

- `.goga/usages/cooks/playwright.md` — already carries the import-policy contour and the
  `page.url` immediate-read rule plus the "Message anatomy of a failed expectation" shapes the
  decomposition recognizes (applied during task formulation / apply-architecture; do not duplicate).
- `.goga/usages/prompts/generation.md` — the import rule, the PAGE URL input line and the HISTORY
  record description (single source of the system prompt).
- `.goga/usages/prompts/cheatsheet.md` — the URL idioms (`page.url` immediate read beside the
  waiting forms; `assert "/dashboard" in page.url`).
- Cell-level `.usages/` updated together with the contracts: `failures/taxonomy.md`,
  `driver/plumbing.md`, `llm/providers.md`, `engine/generation.md`, `engine/healing.md`,
  `engine/steering/steering.md`, `reporting/hooks.md`, root `steps.md` and `lifecycle.md`.

## Applied Fixes

### Fixed CODEMANIFEST Defects

- `prettyplay/llm/CODEMANIFEST` (`generate_step_code`, `code` return annotation):
  "— imports from playwright.sync_api only;" → "— imports from playwright.sync_api and the Python
  standard library only, global at the top level of the code block;"
  (reason: Interface ↔ Interface inconsistency — the llm cell described the generated code under the
  old import policy while the engine cell defines the new fixed form; user-approved, dialog q1).
- Design decision recorded (user-approved, dialog q2): **`error_class` is the short class name**
  (`type(self).__qualname__`, e.g. `IncurableStepError`) — not the module-qualified dotted path.
  Consequential documentation alignment applied: `prettyplay/failures/.usages/taxonomy.md` and
  `prettyplay/engine/steering/.usages/steering.md` example first lines changed from
  `prettyplay.failures.errors.ProductDefectError:`/`…IncurableStepError:` to the short form.
- `goga lint` after the fixes: cells 10, errors 0.

### Design-Review Alignment (design-review stage)

- Wording alignment (user-approved, review dialog q6): every live contract and usage phrase "the
  full class name of the terminal failure" now reads "the class name of the terminal failure" —
  matching the approved short-name decision (dialog q2 of the code-design stage); sites:
  `prettyplay/failures/CODEMANIFEST` (×4), `prettyplay/engine/CODEMANIFEST`,
  `prettyplay/reporting/CODEMANIFEST` (×2), `failures/.usages/taxonomy.md`,
  `reporting/.usages/hooks.md`, `engine/.usages/healing.md`, root `steps.md`, `lifecycle.md`;
  `arch.md` stays the historical snapshot. `goga lint` after: cells 10, errors 0.
- `decompose_error_text` Algorithm step 4a (review dialog q1): the received-continuation
  terminator now names every recognized shape line ("Actual value:", "Caused by:", "Call log:") —
  consistent with the trace and the multiple-Actual-value-blocks edge case.
- Regression surface extended (review dialog q4): `tests/llm/test_provider.py` (exact port
  signature), `tests/engine/test_healer.py`, `tests/test_integration.py`,
  `tests/test_scenario.py` (fake port signatures exercised through the real engine),
  `tests/test_executor.py` (optional symmetry); the PAGE URL line test parametrizes over
  `[None, ""]`.
- New test scenario `test_decompose_extracts_cause_line` (review dialog q5): the `Caused by:`
  shape and the `cause:` render line were previously untested.
- `test_steer_rejected_turn_records_and_never_executes` split into the abort twin and the record
  twin (review dialog q2): the original stdin script ended the dialog before any second request,
  so the next-request history assertion was unassertable.
- `engine/steering/.usages/steering.md` example screenshot path now shows the real
  `prettyplay-steering-` prefix (review dialog q3).

## Entity Interaction and Data Flow

### Interaction Diagram

```
                       StepExecutor (root cell)
                       │ IncurableStepError, interactive on, non-strict
                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ StepSteering.steer(failure, identity, previous_steps, page)                   │
│                                                                              │
│  banner ── page.url ──────────────► PageFacade.url ─► [driver worker thread] │
│          ── str(failure) ◄─ IncurableStepError (render composed at raising)  │
│                                                                              │
│  loop:  guidance line                                                        │
│    ├─ local command (snapshot|screenshot|error|code) — no LLM                │
│    ├─ _guided_request ─► LLMProvider.generate_step_code(                     │
│    │        …, snapshot, page_url=page.url, screenshot, cheat_sheet,         │
│    │        existing_code=failure.code, error=failure.error,                 │
│    │        guidance=message, guidance_history=full records)                 │
│    │          ├─ OpenAIProvider / AnthropicProvider                          │
│    │          │    └─ build_fields_text: PAGE URL line after PAGE SNAPSHOT;  │
│    │          │       HISTORY block with verbatim multi-line records         │
│    │          └─◄ code                                                       │
│    ├─ approval gate: print(code) → input("run? [y/N] ")                      │
│    │      y ─► run_step_code(code, page) ─► [driver worker thread]           │
│    │      else ─► history record: outcome "rejected by the engineer,         │
│    │               not executed" → prompt reopens                            │
│    ├─ red execution ─► full-outcome history record → prompt reopens          │
│    └─ green ─► check_step_compliance (engine) ─► StepCache.save              │
│                 └─ StepReporter.emit("on_healed")                            │
└──────────────────────────────────────────────────────────────────────────────┘

failures cell (leaf):
  ProductDefectError / IncurableStepError.__init__
    └─► render_terminal_message(error_class=type(self).__qualname__, reason,
                                step_text, error, verdict)
          ├─► decompose_error_text(error) ─► ErrorParts(class_name, reason,
          │                                    received, cause, call_log)
          └─► FailureVerdict.render()  (unpadded block)
  One render feeds: exception message ─ executor str(error) ─ on_step_failed
  payload + log record. Consumers never re-compose.
```

### Data Flows

1. **Terminal failure construction** (engine healing path, strict path, generation exhaustion):
   the raiser authors a colon-free reason, passes `step_text`, the full underlying error (already
   formatted by `format_step_error`) and the optional verdict → the exception composes its message
   through `render_terminal_message` once at construction → `str(error)` is the render → the
   executor emits it as the `error` field of `on_step_failed` and the log record carries it.
2. **URL flow**: `PageFacade.url` (driver worker thread) → steering banner (once, at dialog open)
   and every guided regeneration request (fresh read per request) → `build_fields_text` renders the
   `PAGE URL: <url>` line immediately after the PAGE SNAPSHOT block → both providers carry it in the
   user content. The engine passes `page_url=None` — generation/healing requests never carry it.
3. **Guidance turn**: engineer message → regeneration request (CODE/ERROR anchored to the original
   failure every turn, USER GUIDANCE = the message, HISTORY = all prior full records) → generated
   code → shown in full → `run? [y/N]` → on `y` executed via `run_step_code` (worker thread, no
   settle window) → green passes the compliance gate → `CachedStep` write-back + `on_healed`; red or
   rejected appends the full turn record to the history and the prompt reopens.
4. **History flow**: `list[str]` of full records, each
   `engineer message: <message>\ncode:\n<complete code>\noutcome: <complete outcome>` — passed as
   `guidance_history` verbatim; the HISTORY block renders every record with no collapsing and no
   size limits.

### Entity Dependencies

Implementation order (leaf → root, every step leaves the tree importable):

1. `prettyplay/failures` — `decompose_error_text`, `ErrorParts`, the render changes, the facade
   exports (`decompose_error_text`, `ErrorParts` join `__init__` and `__all__`).
2. `prettyplay/driver` — `PageFacade.url`.
3. `prettyplay/llm` — the port signature, `build_fields_text`, both providers.
4. `prettyplay/engine` — the `SYSTEM_PROMPT`/`CHEAT_SHEET` mirrors, `_request` passes
   `page_url=None`.
5. `prettyplay/engine/steering` — the `SYSTEM_PROMPT`/`CHEAT_SHEET` mirrors, the `steer` rewrite.
6. `prettyplay/reporting` — no code change; optional docstring wording for `on_step_failed`.
7. Root usages — already updated by apply-architecture; no further work.

No new cell-to-cell import edges: every new member travels over an existing edge (steering already
imports `PageFacade` from driver and `LLMProvider` from llm; the render is intra-cell).

## Code Stack Trace

### Trace: `render_terminal_message` (changed Routine)

#### Chain

1. **Input**: a terminal-failure constructor (`ProductDefectError.__init__` /
   `IncurableStepError.__init__`) calls
   `render_terminal_message(type(self).__qualname__, message_or_reason, step_text, error, verdict)`.
   → checkpoint: signature matches the contract (five parameters, `error_class` first) — **passed**.
2. **Step**: `parts = decompose_error_text(error)` — the full underlying error text decomposed into
   `ErrorParts`; `error == ""` yields all-empty parts.
   → checkpoint: `decompose_error_text` is pure and total (never raises) — **passed** (see its trace).
3. **Step**: first line `f"{error_class}: {reason}"` — the short class name (design decision q2)
   plus the authored colon-free reason.
   → checkpoint: the first-line contract ("full class name and the authored reason") — **passed**;
   the runner-prefix duplication in pytest is accepted per ADR decision 6 (log records and hook
   payloads carry the kind without any prefix).
4. **Step**: step section — appended only when `step_text` or the decomposed headline is non-empty:
   `---`, `step: <step_text>`, `error: <headline>` where headline =
   `f"{parts.class_name}: {parts.reason}"` when `class_name` is non-empty else `parts.reason`.
   → checkpoint: for a failed check the underlying error carries no AssertionError prefix
   (`format_step_error` policy) so `class_name` stays empty and the headline is the expectation
   text alone; for typed errors (`TimeoutError: …`) the prefix reconstructs the kind — **passed**.
5. **Step**: details section — only when at least one of `received`/`cause`/`call_log` is non-empty:
   `---`, `received: <value>`, `cause: <value>`, `Call log:` + the part's lines verbatim (they keep
   their source indentation).
   → checkpoint: section order matches the ADR template (received, cause, Call log); values
   preserved verbatim — **passed**.
6. **Step**: verdict section — when `verdict.render()` is non-empty: `---`, the block.
   → checkpoint: `FailureVerdict.render` returns "" for an all-empty verdict → no bare separator —
   **passed**.
7. **Output**: `"\n".join(lines)` — the single render; the caller stores it as the exception args,
   nothing else re-composes.

#### Checkpoint Summary

- Type flow constructor → render: `FailureVerdict | None` handled at both call sites; the
  `IncurableStepError` fallback verdict keeps the recommendation line without mutating
  `self.verdict` — **passed**.
- Output ↔ consumers: `str(exc)` (executor `on_step_failed`), the log record and the hook payload
  all consume the same string — **passed**, no re-composition anywhere (verified by grep:
  `render_terminal_message` is called only from the two constructors).

### Trace: `decompose_error_text` (new Routine)

#### Chain

1. **Input**: the `error` string exactly as formatted by the engine error-text policy
   (`format_step_error`): AssertionError messages verbatim (Playwright expect failures carry
   headline + `Actual value:` + `Call log:` shapes); typed failures carry a
   `TypeName: message` head. Empty string allowed.
   → checkpoint: the input surface is fully specified by the existing policy — **passed**.
2. **Step**: `error == ""` → `ErrorParts()` (all fields default ""). → checkpoint: contract
   algorithm step 1 — **passed**.
3. **Step**: first line matched against the class-prefix shape
   `^([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*):(?:\s+(.*))?$` — a dotted identifier followed by a colon and
   then whitespace or end-of-line. Present → `class_name` = the identifier, `reason` = the remainder;
   absent → `reason` = the whole first line, `class_name` = "".
   → checkpoint: "a dotted-identifier head of the first line" — **passed**. The
   whitespace-or-EOL requirement after the colon keeps `net::ERR_…` heads unrecognized (the second
   colon breaks the shape) — graceful, the whole line stays the reason. Recognized examples:
   `TimeoutError: Timeout 30000ms exceeded`, `Page.reload: Timeout 30000ms exceeded`.
4. **Step**: the remaining lines scanned top-down; shapes recognized by their fixed prefixes
   (never by position):
   - `Actual value: …` → `received` starts with the value text; continuation lines join it verbatim
     until a blank line or the next recognized shape line;
   - `Caused by: …` → `cause` = the line's value text;
   - `Call log:` → `call_log` = every subsequent line that is blank or indented (starts with
     whitespace), verbatim with leading spaces, trailing blank lines trimmed; a non-indented
     non-blank line ends the block.
   → checkpoint: exactly the shapes documented in `playwright` ("Message anatomy of a failed
   expectation") — **passed**. An `Actual value:` directly followed by `Call log:` stops the
   received part at the shape line — the canonical Playwright layout.
5. **Step**: unrecognized lines are ignored — no part is filled, nothing raises (graceful
   degradation, contract algorithm step 4). E.g. the `==== logs ====` appendix of navigation
   timeouts fills no part and does not reach the render (the full text still travels in the
   exception's `error` field for programmatic consumers).
   → checkpoint: total, deterministic, no I/O — **passed**.
6. **Output**: the populated `ErrorParts` → consumed by `render_terminal_message` only.

#### Checkpoint Summary

- Purity: deterministic on `error` alone — **passed**.
- Multi-line preservation: received continuations and call-log indentation preserved verbatim —
  **passed**.

### Trace: `ErrorParts` (new Entity)

Construction is keyword-only with empty-string defaults (pydantic v2 per `conventions`):
`ErrorParts(class_name="TimeoutError", reason="Timeout 30000ms exceeded")` is valid. Properties are
the five plain string fields. No behavior beyond the data shape. → checkpoint: pydantic + kw_only +
empty defaults = the conventions data-model rule; `FailureVerdict` stays a frozen dataclass (its own
contract is unchanged — the two coexist in `errors.py` deliberately) — **passed**.

### Trace: `FailureVerdict.render` (changed method)

1. **Input**: the verdict value object (`explanation`, `recommendation`, either possibly empty).
2. **Step**: for each non-empty field, one line `f"{label}: {value}"` with every embedded newline
   replaced by `"\n  "` (two-space continuation indent); labels at column zero — `explanation:`
   then `recommendation:`.
3. **Output**: lines joined with `"\n"`; empty string when both fields are empty.
   → checkpoint: no `ljust`, no fixed label column (the `_VERDICT_LABEL_WIDTH` constant and the
   alignment continuation die with the change); stable lowercase labels preserved for integrator
   parsing — **passed**.

### Trace: `ProductDefectError.__init__` / `IncurableStepError.__init__` (changed constructors)

1. **Input**: unchanged signatures (`step_text, message|reason, error, [code,] verdict`).
2. **Step**: attributes stored exactly as today (`message` keeps the primary reason, not the render;
   `IncurableStepError.code` untouched by rendering).
3. **Step**: the render call gains the first argument: `render_terminal_message(
   type(self).__qualname__, message_or_reason, step_text, error, verdict_or_fallback)`.
   For `IncurableStepError` the render-only fallback verdict (`FailureVerdict("incurable", "",
   _FALLBACK_GUIDANCE)`) is applied when `verdict is None` — unchanged behavior, so the
   recommendation line keeps the message actionable.
   → checkpoint: "passing its own full class name as the error class" — **passed** (short-name form
   per q2); `type(self).__qualname__` is correct under subclassing (renders the actual raised type).
4. **Output**: `Exception.__init__(self, render)` — the traceback boundary folding is untouched
   (`__traceback__` handling is the runner's; no library frames are added).

### Trace: `PageFacade.url` (new property)

1. **Input**: a read from the calling thread (`steering._render_banner` or `_guided_request`, or a
   hand-built handle in tests).
2. **Step**: `return self._call(lambda: self._page.url)` — `_call` is the one-unit machinery behind
   `run` (the same the other plumbing members use): with a worker it queues one unit on the driver
   thread and re-raises the outcome as-is; the unit's `finally` runs the deferred dialog pass;
   without a worker (tests) it runs inline.
   → checkpoint: "executed inside the driver worker thread as one unit through the run primitive" —
   **passed** (`run` itself delegates to `_call`; the property uses the shared unit path, uniform
   with `aria_snapshot`/`screenshot`/`close`). The calling thread never adopts the event loop;
   reads serialize with every other unit of the session — **passed**.
3. **Step**: `page.url` is a plain Playwright immediate read — a `str` returns; no Playwright object
   crosses the boundary.
   → checkpoint: the return type is plain data — **passed**; on a live page the value is never ""
   (even `about:blank` is non-empty); a closed page raises — the caller guards (steering degrades).
4. **Output**: the URL string.

### Trace: `LLMProvider.generate_step_code` / `build_fields_text` / both providers (changed)

1. **Input**: the calling engine or steering supplies `page_url: str | None` (keyword; after
   `snapshot` in the contract signature order). Engine: `None`. Steering: the fresh guarded read.
2. **Step**: the port stub (`provider.py`), `OpenAIProvider.generate_step_code` and
   `AnthropicProvider.generate_step_code` all gain the parameter; both implementations forward it to
   the shared `build_fields_text` (keyword argument — positional forwarding across the widened
   signature is the drift risk the keyword form removes).
   → checkpoint: parity by construction — one shared builder, both providers identical — **passed**.
3. **Step**: `build_fields_text` renders the scenario part:
   `STEP` / `PREVIOUS STEPS` / `PAGE SNAPSHOT` sections as today, then — only when `page_url` is
   truthy — the single-line section `PAGE URL: <page_url>`, then the `CHEAT SHEET` block, then the
   unchanged optional/regeneration blocks. `None` or `""` → no line.
   → checkpoint: "its own PAGE URL line immediately after the PAGE SNAPSHOT block" — **passed**;
   the fixed tail order (CODE, ERROR, RECOMMENDATION, USER GUIDANCE, HISTORY) is untouched —
   **passed**.
4. **Step**: HISTORY — mechanism unchanged (`"HISTORY:\n" + "\n".join(guidance_history)`): the
   records themselves are now full multi-line turn texts composed by the steering; joining with
   `"\n"` renders each verbatim with no collapsing.
   → checkpoint: "every record verbatim, no collapsing, no size limits" — **passed** (the provider
   imposes no transformation whatsoever on the records).
5. **Output**: the user content text → wrapped per-SDK (`openai_user_content` / anthropic
   `_user_content`) → one request → fenced-block extraction unchanged.
6. **Docstring alignment**: the `code` return docstrings of the port and both providers adopt the
   corrected import-policy wording (sync_api + standard library, global at the top of the code
   block) — matching the fixed CODEMANIFEST line (Applied Fixes).

### Trace: `StepGenerator._request` (changed call composition)

1. **Input**: the loop state (`existing_code`, `error`, `recommendation`) — unchanged.
2. **Step**: the `generate_step_code` call adds `page_url=None` beside `guidance=None` (comment:
   the URL input is steering-only — uniform with the guidance None).
   → checkpoint: engine CODEMANIFEST `generate` step 3 ("page_url None — the URL input is
   steering-only, uniform with guidance None") — **passed**; `regenerate`/`_funded_regeneration`
   share `_request`/the same call shape, so every engine request is covered — **passed**.
3. **Output**: candidate code — unchanged path.

### Trace: `StepSteering.steer` (rewritten method)

#### Chain

1. **Input**: `failure: IncurableStepError`, `identity`, `previous_steps`, `page: PageFacade` —
   the executor calls this exactly when the failure would propagate (interactive on, non-strict).
2. **Step (banner)**: `_render_banner(failure, page)` once —
   `── step "<step_text>" — about to raise IncurableStepError ──`, then the aligned banner lines
   `code:` (the failed code), `error:` (the value `str(failure)` — the full terminal render, its
   continuation lines indented to the value column), `url:` (guarded `page.url` read; a failed read
   prints `url unavailable: <failure>` and the line is omitted), `shot:` (the temporary screenshot
   path when one was taken), `commands: snapshot | screenshot | error | code | quit`. No snapshot
   fragment, no separate verdict lines (the render already carries explanation/recommendation), no
   `intent:` line (the header names the step). `logger.info("steering_opened", …)`.
   → checkpoint: the banner carries exactly step, code, render, URL, screenshot path, commands —
   contract step 1 — **passed**; every page interaction guarded (a dead page degrades, the dialog
   survives — existing behavior preserved).
3. **Step (prompt)**: `_read_guidance(failure)` — `quit`/EOF/SIGINT/unreadable stdin →
   `logger.info("steering_declined", …)`, return None. Blank line → re-prompt. Local command →
   served without the LLM (unchanged four commands; `error` and `code` reprint the stored texts).
   → checkpoint: contract steps 2–3 — **passed**.
4. **Step (request)**: `_guided_request` collects the fresh snapshot (guarded), the screenshot when
   `send_screenshots` (guarded), **the fresh URL** (`_guarded_url(page)` — None on failure), and
   calls `generate_step_code(prompt=SYSTEM_PROMPT, user_instructions=config.generation_prompt,
   step_text=failure.step_text, previous_steps, snapshot, page_url=url, screenshot, cheat_sheet=
   CHEAT_SHEET, existing_code=failure.code, error=failure.error, recommendation=None,
   guidance=message, guidance_history=history)`. `LLMUnavailableError` → print the failure, return
   None (contract step 9).
   → checkpoint: CODE/ERROR anchored to the original failure every turn (`failure.code`,
   `failure.error` — already the current behavior, now contract-pinned); URL present in every
   request; the verdict diagnosis stays banner-only (`recommendation=None` — the live guidance
   replaces it) — **passed**.
5. **Step (approval gate)**: `_confirm_run(code)` prints the complete generated code, then reads
   `input("run? [y/N] ")`. `strip() == "y"` → proceed; **anything else** — `n`, `N`, Enter, `quit`,
   any other text — aborts the turn: the record `_turn_record(message, code, "rejected by the
   engineer, not executed")` enters the history and the guidance prompt reopens (contract step 5,
   including the literal `quit` → back to step 2). EOF/SIGINT/unreadable stdin at the approval
   prompt → `steering_declined` logged, the dialog ends returning None (nothing hangs; uniform with
   the guidance prompt).
   → checkpoint: "No code executes without the engineer approval of this turn" — the execution call
   is structurally unreachable without a `y` — **passed**; strict-`y` parsing is the conservative
   reading of `run? [y/N]` (nothing runs unseen on a typo).
6. **Step (execution)**: `run_step_code(code, page)` bare — the whole step inside the driver worker
   thread, no settle window, no budget. An exception (not KeyboardInterrupt-swallowed: SIGINT during
   execution escapes directly, unchanged) → print the complete outcome
   (`print(f"turn failed: {outcome}")` — the full multi-line text), append
   `_turn_record(message, code, str(outcome))` — the full error text verbatim — and return to the
   prompt. No re-execution of the same code.
   → checkpoint: contract steps 6 and 8 — **passed**. Outcome text = `str(outcome)` verbatim (the
   complete text the exception carries). Considered alternative — routing through
   `format_step_error` for a typed prefix — rejected: it would add a name to the steering Imports
   list for a display nuance the model does not need; the full verbatim text satisfies "the complete
   outcome".
7. **Step (gate)**: on green, `check_step_compliance` sits outside every exception-swallowing try —
   its hard failures (`LLMUnavailableError`, `ComplianceVerdictError`) print the gate failure line,
   log a WARNING naming the step and the failure, return None (contract step 7 tail). A high finding
   → no write-back, show the violation, append the full record with the complete violation text,
   reopen the prompt. Medium/low → WARNING, then write-back.
   → checkpoint: unchanged semantics, now with full records — **passed**.
8. **Step (write-back)**: `_write_back` — `CachedStep(identity, code, date)`, `cache.save`,
   `on_healed` with the interactive-healing explanation, the read-only-cache notice — unchanged.
9. **Output**: the healed `CachedStep`, or None on every decline path; the caller (`_steer_or_raise`)
   propagates the original failure object on None.

#### Checkpoint Summary

- Type flow steering → llm: `page_url: str | None` matches the port contract; `guidance_history`
  records are plain strings — **passed**.
- Interface alignment steering → engine: `run_step_code(code, page)` and
  `check_step_compliance(config, provider, step_text, code)` signatures unchanged — **passed**.
- Contract ↔ code: the turn never executes unapproved code; every rejected/failed turn records
  before the prompt reopens; no budget, no polling — **passed**.

### Trace: the frozen mirrors (`SYSTEM_PROMPT`, `CHEAT_SHEET` — engine and steering)

1. `prettyplay/engine/generator.py` `SYSTEM_PROMPT` ← the section after the `---` separator of
   `.goga/usages/prompts/generation.md`, verbatim: the new import rule ("Import from
   playwright.sync_api and the Python standard library only — no third-party libraries; imports are
   global only: at the top level of the code block, before `def step`, never inside the function
   body"), the new `- PAGE URL:` input line after `- PAGE SNAPSHOT:`, the HISTORY input line
   carrying "each record carries the full engineer message, the complete generated code and the
   complete outcome of the turn".
2. `prettyplay/engine/steering/steering.py` `SYSTEM_PROMPT` ← the same section, verbatim (a local
   copy, never an import — frozen mirrors stay cell-owned).
3. Both `CHEAT_SHEET` constants ← `.goga/usages/prompts/cheatsheet.md` whole-file verbatim (the
   practice has no `---` separator): adds `page.url  # the current URL — an immediate read beside
   the waiting forms` in "Navigation and waits" and `assert "/dashboard" in page.url` in "Immediate
   reads with plain asserts".
   → checkpoint: the existing mirror tests (`test_steering_mirrors_the_practices`, the generator
   mirror equivalents) compare the constants against the files — the mirrors change together with
   the practices or those tests fail — **passed** (mirror drift is the top regression risk; the
   tests are the guard).

### Trace: `StepHooks.on_step_failed` / `StepReporter` (wording-level)

`StepExecutor.execute` already emits `str(error)` — the render, verbatim — into the payload and the
reporter already logs the payload. No behavioral change; the CODEMANIFEST wording names the new
sections. Optional: extend the `on_step_failed` docstring in `prettyplay/reporting/hooks.py` to name
the section list, mirroring the contract sentence. → checkpoint: no re-composition sneaks in —
**passed** (verified by reading the emit path).

## Algorithm Design

### `decompose_error_text`

**Responsibility**: pure recognition of the underlying error text into the render parts.

**Algorithm:**
```
1. error == "" → return ErrorParts() (all fields empty)
2. lines = error.splitlines()
3. first-line class prefix: match ^([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*):(?:\s+(.*))?$
   → match: class_name = m[1], reason = m[2] or ""
   → no match: class_name = "", reason = the whole first line
4. scan lines[1:] top-down, by fixed prefixes only:
   a. line starts with "Actual value:" → received = text after the prefix;
      consume following lines into received (verbatim, "\n"-joined) while they are
      non-blank and not a recognized shape line ("Actual value:", "Caused by:", "Call log:")
   b. line starts with "Caused by:" → cause = text after the prefix (single line)
   c. line == "Call log:" or starts with "Call log:" → call_log = every following
      line that is blank or starts with whitespace, verbatim, trailing blanks
      trimmed; the block ends at a non-indented non-blank line or EOF
   d. any other line → ignored (graceful degradation)
5. return ErrorParts(class_name, reason, received, cause, call_log)
```

**Errors:** none — never raises on any input.

**Edge Cases:**
- Empty string → all-empty parts. Whitespace-only → treated as non-empty text, no shapes, empty
  parts except reason = the line.
- `net::ERR_…` head → the double colon breaks the class shape → whole first line is the reason.
- Multi-line actual values → preserved verbatim inside `received`.
- Multiple `Actual value:` blocks → the last scan wins for `received` (Playwright emits one);
  deterministic either way.

### `ErrorParts`

**Responsibility**: the data shape the render draws from. pydantic v2 model, `model_config =
ConfigDict(kw_only=True)`, five `str` fields defaulting to `""`. Exported from
`prettyplay.failures` beside `decompose_error_text`.

### `render_terminal_message`

**Responsibility**: compose the one structured render.

**Algorithm:**
```
1. parts = decompose_error_text(error)
2. lines = [f"{error_class}: {reason}" if reason else error_class]
3. headline = f"{parts.class_name}: {parts.reason}" if parts.class_name else parts.reason
4. IF step_text or headline:
     lines += ["---"]
     IF step_text: lines += [f"step: {step_text}"]
     IF headline:  lines += [f"error: {headline}"]
5. IF parts.received or parts.cause or parts.call_log:
     lines += ["---"]
     IF parts.received: lines += [f"received: {parts.received}"]
     IF parts.cause:    lines += [f"cause: {parts.cause}"]
     IF parts.call_log: lines += ["Call log:"] + parts.call_log.splitlines()
6. block = verdict.render() if verdict is not None else ""
   IF block: lines += ["---", block]
7. return "\n".join(lines)
```

**Errors:** none (pure).

**Edge Cases:**
- `error=""` → no error line, no details section; step-only section when `step_text` non-empty.
- Both `step_text` and headline empty → the whole step section omitted, no bare separator.
- Verdict with both fields empty → empty block → no verdict section.
- The render ends without a trailing separator (join only; no section appended after the last
  non-empty one).

### `FailureVerdict.render`

```
for (label, value) in (("explanation", e), ("recommendation", r)):
    if value: emit f"{label}: {value.replace('\n', '\n  ')}"
join with "\n"
```

### `ProductDefectError` / `IncurableStepError`

Unchanged attribute contracts; the render call becomes
`render_terminal_message(type(self).__qualname__, <reason>, step_text, error, <verdict>)` —
`IncurableStepError` keeps the render-only fallback verdict when `verdict is None`. The
`_VERDICT_LABEL_WIDTH` constant dies with the alignment.

### `PageFacade.url`

```
@property
def url(self) -> str:
    return self._call(lambda: self._page.url)
```
Insert before the methods block (properties first — the contract lists it under `properties`).
Docstring: the current URL — an immediate read executed as one unit inside the driver worker
thread; plain string back.

### `LLMProvider.generate_step_code` + `build_fields_text` + providers

- Port stub and both implementations: parameter `page_url: str | None` inserted after `snapshot`
  (contract order); docstrings updated (`page_url` semantics; `guidance_history` full-record
  semantics; corrected import-policy wording of `code`).
- `build_fields_text`: parameter after `snapshot`; the scenario part becomes
  `[STEP, PREVIOUS STEPS, PAGE SNAPSHOT] + ([f"PAGE URL: {page_url}"] when page_url else []) +
  [CHEAT SHEET] …` — the rest untouched.
- Providers forward `page_url=page_url` by keyword to the shared builder.

### `StepGenerator`

- `_request`: add `page_url=None` to the `generate_step_code` call (comment: steering-only input,
  uniform with `guidance=None`).
- `SYSTEM_PROMPT` / `CHEAT_SHEET` mirrors ← the practices, verbatim (see the mirror trace).

### `StepSteering`

**Responsibility**: the approved-turn REPL over a terminally stuck step.

**Algorithm (steer):**
```
1. banner once (step header; code; error = str(failure); url = guarded page.url;
   shot = temp screenshot path when taken; commands) — no snapshot fragment
2. LOOP:
   read guidance line; quit/EOF/SIGINT/unreadable stdin → return None
   blank → re-prompt; local command → serve, re-prompt
3. request: fresh snapshot (+ screenshot per settings) + fresh guarded URL +
   original failure.code/.error + message + full history → generate_step_code
   provider unavailable → print, return None
4. approval: print the complete code; input "run? [y/N] "
   EOF/SIGINT/OSError → log steering_declined, return None
   answer.strip() != "y" → history += record(message, code,
     "rejected by the engineer, not executed"); re-prompt
5. execute run_step_code(code, page) bare (worker thread, no settle)
   exception → print the complete outcome; history += record(message, code,
   str(outcome)); re-prompt
6. green → check_step_compliance
   hard gate failure → print + WARNING log; return None
   high finding → print violation; history += record(message, code, violation text); re-prompt
   medium/low → WARNING
7. write-back: CachedStep(identity, code); cache.save; on_healed; return step
```

**Record format** (`_turn_record(message, code, outcome)`):
```
engineer message: <message>
code:
<complete code>
outcome: <complete outcome>
```

**Helpers:**
- `_confirm_run(code) -> bool` — prints `generated code:` + the code, returns
  `input("run? [y/N] ").strip() == "y"`; raises EOFError/KeyboardInterrupt/OSError upward.
- `_guarded_url(page) -> str | None` — `try: return page.url except Exception as failure:
  print(f"url unavailable: {failure}"); return None`.
- `_banner_line(label, text)` — label `ljust` to the banner column (`len("commands:")` = 9) + one
  space; continuation lines indented to the value column (the banner's own presentation padding —
  the render inside stays unpadded).
- The progress line becomes `regenerating with USER GUIDANCE` (execution now waits for approval —
  the old "executing against the live page" tail would lie).
- Deleted: `_snapshot_fragment`, `_SNAPSHOT_FRAGMENT_LINES`, `_first_line`.

**Errors:**
- `LLMUnavailableError` (request) / gate hard failures → dialog ends, None, original failure
  propagates from the executor.
- Execution exceptions → red turn, never escape.
- `KeyboardInterrupt` during execution → escapes directly (no swallow).

**Edge Cases:**
- Empty `failure.code` (no candidate ever existed) → banner prints an empty code block — survive,
  as today.
- Dead page → URL degrades (notice + omitted line; `page_url=None` in requests), snapshot/screenshot
  degrade as today.
- `quit` at the approval prompt → aborted turn + rejected record, back to the guidance prompt (the
  engineer quits again to leave) — the contract's literal step 5.

### Reporting

No algorithm change. Optional docstring wording in `hooks.py::on_step_failed` naming the template
sections.

## Cross-cutting Concerns

- **Error handling**: `decompose_error_text` and `render_terminal_message` are total and pure —
  rendering can never fail a failure path. Steering guards every page read (`url`, snapshot,
  screenshot); the gate hard failures and provider unavailability end the dialog declined; the
  original terminal failure always propagates unchanged on decline.
- **Logging**: `steering_opened`, `steering_guidance`, `steering_declined` at INFO with
  `step_text`/`guidance` extras; `compliance findings passed` and `compliance gate failed` at
  WARNING; nothing new logged with the URL (it is page state, not a secret; it appears in the
  banner and requests only). No secrets in any record (unchanged rule).
- **Validation**: `ErrorParts` validates through pydantic; every other input surface unchanged.
- **Caching**: the healed write-back still happens only after execution + gate; guidance and
  history are never persisted (the cache file never sees them); the cache address takes no part in
  the new inputs (`page_url`, history) — a cached step never regenerates because they changed.
- **Concurrency**: `PageFacade.url` is one queued unit on the single driver thread — serialized with
  every other unit; the calling thread never adopts the Playwright event loop (the IPython/Jupyter
  guarantee). The dialog itself is single-threaded (stdin + the worker queue).

## Usages Analysis

### `conventions` (`.goga/usages/conventions.md`)
- **What it provides**: code writing rules — relative imports, pydantic data models (kw_only, empty
  defaults), logging style, testing discipline.
- **Where used**: every changed file; `ErrorParts` directly applies the data-model rule.
- **Why chosen**: project-wide mandate.
- **How exactly**: `ErrorParts(BaseModel)` with `ConfigDict(kw_only=True)` and `""` defaults.

### `playwright` (`.goga/usages/cooks/playwright.md`) — failures cell
- **What it provides**: the "Message anatomy of a failed expectation" — the fixed shapes
  (`Actual value:`, `Caused by:`, `Call log:` blocks, the expectation headline) the decomposition
  recognizes; the dotted error-head surface (`TimeoutError:`, `Page.reload:`).
- **Where used**: `decompose_error_text` (its Algorithm references the shapes by prefix).
- **Why chosen**: the recognition contract must match the real Playwright message surface — the
  practice is the authority.
- **How exactly**: prefix matching per the anatomy section; never by position.

### `playwright` — driver cell (already connected)
- The `page.url` immediate-read rule (beside `to_have_url`/`wait_for_url`) — the plumbing property
  is the library-side twin of that rule.

### `system_prompt` (`.goga/usages/prompts/generation.md`)
- **What it provides**: the single source of the generation/regeneration system prompt — now with
  the new import rule, the PAGE URL input line and the HISTORY record description.
- **Where used**: `StepGenerator.SYSTEM_PROMPT` (frozen mirror), `StepSteering.SYSTEM_PROMPT`
  (frozen local copy).
- **Why chosen / how**: the mirror rule — the constants change only together with the file; the
  mirror tests enforce equality.

### `cheat_sheet` (`.goga/usages/prompts/cheatsheet.md`)
- **What it provides**: the compact API reference — now with the URL idioms.
- **Where used**: both `CHEAT_SHEET` mirrors (whole-file verbatim copy).

### Imported Usages
- `configuration` from `prettyplay/config` (driver) — unchanged; the browser-group settings
  context for the session.
- `classification` from `prettyplay/llm` (engine) — unchanged; the healing decision categories.

## `.usages/` Update

### Cell: `prettyplay/failures`

- **`taxonomy.md`** → current (updated by apply-architecture; this stage aligned the example first
  line to the short class name). No further changes.

### Cell: `prettyplay/driver`

- **`plumbing.md`** → current: the handle-members table already lists `page.url` with the
  worker-thread semantics. No changes.

### Cell: `prettyplay/llm`

- **`providers.md`** → current: the page-URL parity and the HISTORY verbatim paragraphs are in
  place. No changes.

### Cell: `prettyplay/engine`

- **`generation.md`**, **`healing.md`** → current (import rule; verdict render description). No
  changes.

### Cell: `prettyplay/engine/steering`

- **`steering.md`** → current after this stage's alignment (the banner example's error first line
  now shows the short class name; the approval flow, full history and URL are documented). No
  further changes.

### Cell: `prettyplay/reporting`

- **`hooks.md`** → current (the render section list). No changes.

### Root: `prettyplay`

- **`steps.md`**, **`lifecycle.md`** → current. No changes.

No new `.usages/` files: every change lives inside an existing functional domain of an existing
file.

## Test Stack Trace

### General Setup

- Style: existing suite conventions — `FakePage`/`DeadPage` fakes growing a `url` attribute
  (property or plain attribute; `DeadPage.url` raises `PlaywrightError("Target closed")`);
  `FakeProvider` records every `generate_step_code` call dict (now including `page_url`) and returns
  scripted candidates; stdin driven through `mock.patch.object(builtins, "input", side_effect=[…])`
  — each guidance line is followed by its approval answer; screenshots cleaned by the autouse
  fixture.
- A representative full Playwright expect-failure text used across decomposition tests:
  ```
  Locator expected to be visible
  Actual value: display:none
  Call log:
    - waiting for get_by_role("button", name="Sign in")
  ```

### Source File Registry

`prettyplay/failures/errors.py`, `prettyplay/failures/__init__.py`,
`prettyplay/driver/page.py`, `prettyplay/llm/provider.py`, `prettyplay/llm/_request.py`,
`prettyplay/llm/openai_provider.py`, `prettyplay/llm/anthropic_provider.py`,
`prettyplay/engine/generator.py`, `prettyplay/engine/steering/steering.py`,
`prettyplay/reporting/hooks.py` (docstring only).

### Existing tests requiring updates (regression surface)

- `tests/failures/test_errors.py`: `test_render_terminal_message_signature_is_four_parameters` →
  five; `test_render_lists_aligned_fields_without_category` → column-zero labels + two-space
  continuations; `test_facade_all_lists_seven_names` / `test_all_seven_names_importable_from_facade`
  → nine names (`ErrorParts`, `decompose_error_text`); render-shape assertions move to the new
  template.
- `tests/engine/steering/test_steering.py`: every turn test feeds the approval answer after each
  guidance line; banner tests drop the fragment/verdict assertions and assert URL + render;
  `test_steer_banner_fragment_truncates_but_snapshot_command_prints_all` → replaced by the
  no-fragment test; the FakeProvider signature grows `page_url`; FakePage grows `url`.
- `tests/llm/test_request.py`, `tests/llm/test_openai_provider.py`, `tests/llm/test_anthropic_provider.py`:
  the `page_url` parameter and the PAGE URL line assertions; parity cases extended.
- `tests/engine/test_generator.py`: the request-recording fake gains `page_url`; assert `None` on
  engine paths; mirror tests pick up the practice changes automatically.
- `tests/llm/test_provider.py`: `GENERATE_STEP_CODE_PARAMS` grows `page_url` right after `snapshot`
  (the exact port-signature assert); the screenshot→cheat_sheet→existing_code adjacency asserts
  keep holding with the insertion.
- `tests/engine/test_healer.py`, `tests/test_integration.py`, `tests/test_scenario.py`: every fake
  port implementation's `generate_step_code` gains the `page_url` parameter (contract order); the
  recording dicts record it — engine-driven paths assert `page_url is None` where requests are
  recorded (the real `StepGenerator._request` passes the keyword; a fake without the parameter
  raises `TypeError`).
- `tests/test_executor.py`: the three strict-mode stub providers carry the port signature for
  symmetry (never called for generation — optional but keeps the stubs honest).
- `tests/llm/test_request.py` (extension of the PAGE URL line case): parametrize over
  `[None, ""]` — the contract says None or empty renders no line.

---

### Positive Tests

#### `test_decompose_extracts_all_parts_of_an_expect_failure`

**Setup**: none (pure function).

**Input**: the representative expect-failure text above.

**Trace**:
```
decompose_error_text(text)
  → first line "Locator expected to be visible" — no dotted-class head → reason
  → "Actual value: display:none" → received; stops at "Call log:"
  → "Call log:" block → call_log = '  - waiting for get_by_role("button", name="Sign in")'
  → ErrorParts(class_name="", reason="Locator expected to be visible",
               received="display:none", cause="", call_log="  - waiting for …")
```

**Assertions**:
```
parts.class_name == ""
parts.reason == "Locator expected to be visible"
parts.received == "display:none"
parts.cause == ""
parts.call_log == '  - waiting for get_by_role("button", name="Sign in")'
```

**Sufficiency**: pins the recognition contract — the shapes the render's details section depends
on; a regex refactor that breaks any shape fails here.

#### `test_decompose_extracts_typed_error_head`

**Setup**: none.

**Input**: `"TimeoutError: Timeout 30000ms exceeded\n=========================== logs ====…"`.

**Trace**:
```
decompose_error_text(error)
  → dotted head "TimeoutError" + remainder "Timeout 30000ms exceeded"
  → the logs appendix — no recognized shape → ignored
```

**Assertions**: `parts.class_name == "TimeoutError"`,
`parts.reason == "Timeout 30000ms exceeded"`, `parts.received == ""`, `parts.call_log == ""`.

**Sufficiency**: the typed-error path of `format_step_error` output; guards the headline
reconstruction of the `error:` line.

#### `test_decompose_extracts_cause_line`

**Setup**: none (pure function).

**Input**: `"TimeoutError: Page.goto failed\nCaused by: net::ERR_CONNECTION_REFUSED at https://x.test"`.

**Trace**: first line matches the dotted head → class_name="TimeoutError", reason="Page.goto
failed"; the second line hits the fixed "Caused by:" prefix →
cause="net::ERR_CONNECTION_REFUSED at https://x.test"; no Actual value/Call log shapes;
ErrorParts(class_name="TimeoutError", reason="Page.goto failed", received="",
cause="net::ERR_CONNECTION_REFUSED at https://x.test", call_log="").

**Assertions**:
```
parts.class_name == "TimeoutError"
parts.reason == "Page.goto failed"
parts.received == ""
parts.cause == "net::ERR_CONNECTION_REFUSED at https://x.test"
parts.call_log == ""
```
plus the render side: `render_terminal_message("IncurableStepError", "r", "s", input, None)`
contains the line `cause: net::ERR_CONNECTION_REFUSED at https://x.test` between the `---`
separators of the details section.

**Sufficiency**: pins the third fixed shape of the recognition contract — without it a refactor
dropping the Caused by branch passes silently and the render loses the cause line.

#### `test_render_composes_the_full_template`

**Setup**: `verdict = FailureVerdict("fixable", "the button is behind the modal", "dismiss the modal first")`;
`error` = the expect-failure text.

**Input**: `render_terminal_message("IncurableStepError", "the generation budget is exhausted", "click Checkout", error, verdict)`.

**Trace**:
```
  → decompose_error_text(error) → parts
  → first line "IncurableStepError: the generation budget is exhausted"
  → step section: "---", "step: click Checkout",
    "error: Locator expected to be visible"
  → details: "---", "received: display:none", "Call log:",
    "  - waiting for get_by_role(\"button\", name=\"Sign in\")"
  → verdict: "---", "explanation: the button is behind the modal",
    "recommendation: dismiss the modal first"
```

**Assertions**: the exact 11-line equality (joined with "\n"), first line carries the short class
name, labels at column zero, no padding.

**Sufficiency**: the approved ADR template end-to-end; every consumer (exception text, log, hook)
is this string.

#### `test_render_omits_the_details_section_without_parts`

**Input**: `error="TimeoutError: Timeout 30000ms exceeded"`, verdict None.

**Assertions**: output is exactly
`"IncurableStepError: <reason>\n---\nstep: <step>\nerror: TimeoutError: Timeout 30000ms exceeded"`
— no second `---` block, no `received:`/`cause:`/`Call log:` lines.

**Sufficiency**: the conditional section rule; prevents bare separators and ghost labels.

#### `test_verdict_render_labels_at_column_zero_with_two_space_continuations`

**Input**: `FailureVerdict("rot", "two\nlines", "do X")`.

**Assertions**: `render() == "explanation: two\n  lines\nrecommendation: do X"`.

**Sufficiency**: the unpadded contract; the old `ljust` alignment is gone.

#### `test_product_defect_first_line_carries_its_own_class_name`

**Input**: `ProductDefectError("s", "the button stayed invisible", "", None)`.

**Assertions**: `str(exc).splitlines()[0] == "ProductDefectError: the button stayed invisible"`;
`exc.message == "the button stayed invisible"` (the attribute keeps the reason, not the render).

**Sufficiency**: the error_class plumbing and the attribute contract; the same shape test runs for
`IncurableStepError` (which additionally asserts the fallback `recommendation:` line renders when
the verdict is None).

#### `test_page_facade_url_reads_through_the_worker_unit`

**Setup**: `FakePage` with `url = "https://shop.example.com/cart"`; a `PageFacade` hand-built over
it (inline path), and one bound to a fake worker recording queued units.

**Input**: `handle.url`.

**Trace**: `url` → `_call(lambda: page.url)` → the unit executes (worker or inline) → plain string
back; with the fake worker: exactly one queued unit containing the read.

**Assertions**: returns `"https://shop.example.com/cart"`; the fake worker saw one unit; nothing
else ran concurrently.

**Sufficiency**: the worker-boundary contract of the read — the calling thread never adopts the
event loop; the read serializes with other units.

#### `test_build_fields_places_page_url_line_after_snapshot`

**Setup/Input**: `build_fields_text(user_instructions="", step_text="s", previous_steps=[],
snapshot="- body", page_url="https://x.test/a", cheat_sheet="CS", existing_code=None, error=None,
recommendation=None, guidance=None, guidance_history=[])`.

**Assertions**: the section order in the result is `STEP … PREVIOUS STEPS … PAGE SNAPSHOT …` then
`"PAGE URL: https://x.test/a"` as its own paragraph, then `CHEAT SHEET:`; with `page_url=None` no
`PAGE URL` substring appears anywhere.

**Sufficiency**: the placement contract both providers inherit through the shared builder.

#### `test_history_block_renders_full_multi_line_records`

**Input**: `guidance_history=[record1, record2]` where record1 embeds a multi-line code block and a
multi-line outcome.

**Assertions**: the HISTORY section contains both records verbatim — every line of the code and the
outcome present, order preserved, no truncation markers.

**Sufficiency**: the no-collapsing rule at the request-composition layer.

#### `test_engine_requests_pass_page_url_none`

**Setup**: generator over a recording `FakeProvider`, a `FakePage`, budgets allowing one attempt.

**Input**: `generate(identity, "step", [], page, window)` with a green candidate and the gate off.

**Assertions**: the recorded call dict has `page_url is None` (uniform with `guidance is None`).

**Sufficiency**: the engine-side uniformity the contract's step 3 pins; prevents URL leaking into
generation/healing requests.

#### `test_steer_green_approved_turn_heals`

**Setup**: FakeProvider returns working code; stdin: `["I solved the captcha", "y"]`; gate off;
writable tmp cache.

**Input**: `steer(failure, identity, [], page)`.

**Trace**:
```
banner (once) → guidance "I solved the captcha" → request (page_url=url, existing_code=failure.code,
error=failure.error) → code printed → "y" → run_step_code green → gate empty →
CachedStep saved → on_healed → return step
```

**Assertions**: returns a `CachedStep` with the candidate code; `cache` holds it under `identity`;
the reporter saw `on_healed`; `run_step_code` executed exactly once; stdout contains the complete
code before the approval prompt.

**Sufficiency**: the TODO repro in miniature — the approval-gated happy path.

#### `test_steer_request_carries_the_current_url`

**Setup**: FakePage.url = `"https://www.google.com/sorry?continuation=…"`, one green turn.

**Assertions**: the recorded request dict has `page_url == "https://www.google.com/sorry?…"`;
the banner stdout line `url:` shows the same value; no per-turn URL print occurs.

**Sufficiency**: decision 4 — URL in every request and the banner only.

#### `test_steer_banner_shows_render_and_url_without_snapshot_fragment`

**Setup**: failure with a verdict; FakePage snapshot of 30 lines.

**Assertions**: banner stdout contains the `error:` line with `str(failure)`'s first line
(`IncurableStepError: <reason>`), the `url:` line, the `commands:` line; contains **no** line of
the accessibility snapshot; the `snapshot` command still prints all 30 lines.

**Sufficiency**: decision 7 — the short banner; the fragment machinery is really gone.

#### `test_mirrors_match_the_practices`

**Setup**: existing mirror tests read the two practice files.

**Assertions**: `generator.SYSTEM_PROMPT` == the post-`---` section of `generation.md`;
`steering.SYSTEM_PROMPT` == the same; both `CHEAT_SHEET` constants == `cheatsheet.md` whole file;
the import-rule line and the PAGE URL input line are present in both prompts.

**Sufficiency**: mirror drift is the top regression risk of the whole change.

---

### Negative Tests

#### `test_steer_rejected_turn_records_and_never_executes`

Two twins:

**Abort twin** — Setup: FakeProvider returns code; stdin: `["try this", "n", "quit"]`.
Input: `steer(failure, …)`.
Assertions: returns None; `run_step_code` never called; nothing cached; stdout shows the complete
code before the approval prompt.

**Record twin** — Setup: FakeProvider answers=`[code1, code2]` (the second green); stdin:
`["try this", "n", "try hovering first", "y"]`.
Trace: turn 1 rejected → record appended → prompt reopens → turn 2 approved → green → heals.
Assertions: `provider.calls[1]["guidance_history"]` ==
`["engineer message: try this\ncode:\n<code1>\noutcome: rejected by the engineer, not executed"]`
(the exact rejected record reaches the next request); `run_step_code` called exactly once (only the
approved turn executes); the healed step is cached.

**Sufficiency**: decision 2 — the model never re-proposes rejected code blind; nothing runs unseen;
the rejected record provably travels to the next request.

#### `test_steer_enter_and_quit_at_approval_abort_the_turn`

**Setup**: stdin: `["msg", "", "quit"]` (Enter at approval), and a twin with `["msg", "quit", "quit"]`.

**Assertions**: both behave as the rejected turn — record appended, no execution.

**Sufficiency**: the conservative `run? [y/N]` parsing — only an exact `y` runs.

#### `test_steer_approval_eof_or_sigint_declines_the_dialog`

**Setup**: stdin: guidance line then `input` raising `EOFError` at the approval prompt.

**Assertions**: returns None; no execution; `steering_declined` logged; the original failure
propagates from the executor.

**Sufficiency**: nothing hangs at the new prompt.

#### `test_steer_red_turn_records_the_full_outcome`

**Setup**: FakeProvider returns code raising `AssertionError("Locator expected to be visible\nActual value: none\nCall log:\n  - waiting…")`;
stdin: `["msg", "y", "quit"]`.

**Assertions**: returns None; stdout shows the complete multi-line outcome; the history record's
outcome part equals `str(outcome)` verbatim (all four lines); no re-execution (`run_step_code`
called once).

**Sufficiency**: decision 3 — the full honest context window; the old first-line collapse is gone.

#### `test_steer_high_finding_records_the_complete_violation`

**Setup**: compliance verdict `[HIGH_FINDING]`; stdin: `["msg", "y", "quit"]`.

**Assertions**: no cache write; stdout names the instruction; the record outcome carries the full
violation text (`violated instruction: <instruction> — <explanation>`).

**Sufficiency**: the rejected-by-gate turn is history too — the model steers away from the
violation.

#### `test_steer_dead_page_url_degrades`

**Setup**: `DeadPage` (url and snapshot raise).

**Assertions**: the dialog survives — banner prints the url-unavailable notice, omits the `url:`
line; requests record `page_url is None`; the dialog still completes a scripted green turn.

**Sufficiency**: the guarded-read rule; a dead page never kills the dialog.

#### `test_steer_provider_unavailable_ends_dialog`

**Setup**: FakeProvider raising `LLMUnavailableError`; stdin: `["msg"]`.

**Assertions**: returns None; no approval prompt shown (the dialog ends before it).

**Sufficiency**: contract step 9 — the provider failure precedes the gate.

#### `test_decompose_unrecognized_shapes_leave_parts_empty`

**Input**: `"weird failure text\nno shapes here"`.

**Assertions**: `class_name == ""`, `reason == "weird failure text"`, `received == cause ==
call_log == ""`; no exception.

**Sufficiency**: graceful degradation — rendering never raises on unknown error text.

---

### Edge Case Tests

#### `test_decompose_empty_error_yields_all_empty_parts`

**Input**: `""`. **Assertions**: all five fields `""`. **Sufficiency**: contract algorithm step 1.

#### `test_decompose_multiline_actual_value_is_preserved`

**Input**: an error whose `Actual value:` continues on following lines until `Call log:`.

**Assertions**: `received` keeps every continuation line verbatim, `\n`-joined.

**Sufficiency**: the verbatim-preservation requirement.

#### `test_decompose_net_error_head_is_not_a_class`

**Input**: `"net::ERR_CONNECTION_REFUSED at https://x.test"`.

**Assertions**: `class_name == ""`, `reason ==` the whole line.

**Sufficiency**: the colon-after-identifier rule keeps protocol error codes out of the class slot.

#### `test_render_empty_error_omits_step_error_entirely_when_step_also_empty`

**Input**: `error=""`, `step_text=""`, verdict None.

**Assertions**: output is exactly the first line — no `---` anywhere.

**Sufficiency**: no bare separators, the closing rule of the template.

#### `test_verdict_render_empty_fields_yield_empty_block`

**Input**: `FailureVerdict("rot", "", "")`.

**Assertions**: `render() == ""` and a render with that verdict carries no verdict section.

**Sufficiency**: the conditional verdict section.

#### `test_error_parts_is_pydantic_kw_only_with_empty_defaults`

**Input**: `ErrorParts(class_name="X")`.

**Assertions**: the other four fields are `""`; `ErrorParts(reason="r", class_name="c")` works;
positional construction raises `TypeError`.

**Sufficiency**: the conventions data-model rule the contract pins.

#### `test_facade_exports_the_two_new_names`

**Assertions**: `from prettyplay.failures import ErrorParts, decompose_error_text` works; both are
in `__all__` (nine names total).

**Sufficiency**: the cell facade contract.

#### `test_render_error_line_reconstructs_typed_headline`

**Input**: `error="Page.reload: Timeout 30000ms exceeded"`.

**Assertions**: the `error:` line reads `error: Page.reload: Timeout 30000ms exceeded` — the
dotted head is preserved inside the headline, distinct from the first line's terminal class.

**Sufficiency**: the TODO's observed error text renders exactly as the ADR example shows.

## Additional Instructions for the Implementation Agent

- Follow the implementation order of Entity Dependencies; after each step the tree must stay
  importable and `ruff check` + the touched test modules green.
- Mirror discipline: `SYSTEM_PROMPT` and `CHEAT_SHEET` constants are copied verbatim from the
  practice files (`generation.md` after `---`; `cheatsheet.md` whole file) — never hand-edited
  prose; the mirror tests are the acceptance.
- The render first line uses the **short class name** (`type(self).__qualname__`) — user-approved
  decision (dialog q2); do not switch to the dotted module path.
- Strict approval parsing: only `answer.strip() == "y"` executes; every other answer (n, Enter,
  quit, anything else) aborts the turn with the rejected record. EOF/SIGINT/unreadable stdin at the
  approval prompt ends the dialog declined.
- All dialog strings stay English (`run? [y/N]`, `rejected by the engineer, not executed`,
  `generated code:`, `turn failed:`, `regenerating with USER GUIDANCE`).
- Do not duplicate the already-applied practice edits (playwright.md import-policy paragraph,
  `page.url` rule, prompts files) — the practices are the source; only the mirrors and the code
  change now.
- Remove the dead steering helpers (`_snapshot_fragment`, `_SNAPSHOT_FRAGMENT_LINES`,
  `_first_line`) and the failures `_VERDICT_LABEL_WIDTH`; leave no unused imports (`re` joins
  `errors.py` for the class-prefix shape).
- No new cross-cell imports: `format_step_error` is deliberately not imported into steering (the
  red-turn outcome stays `str(outcome)` verbatim — design decision, see the steer trace).
- The steering history and guidance never persist anywhere; `page_url` and history take no part in
  step addressing.
- Update the existing tests listed in the regression surface as part of the change, not as a
  follow-up; `pytest tests/ -x` and `ruff check` in the project virtualenv are the exit gate, plus
  the TODO repro scenario as the final manual acceptance.
