# Plan: `fix-interactive-loop`

Result of compiling the design document `.goga/history/2026/fix-interactive-loop/design.md`
(after the design-review alignment) into ralphex-compatible execution tasks.

---

## Purpose

Rebuild the interactive steering loop around engineer-approved turns, a full context window and
URL visibility, plus the shared decomposed terminal-error render, the plumbing URL read, the
import-policy alignment and the LLM request-composition changes.

After implementation the library provides:

- a decomposed, structured terminal-failure render (first line = terminal class + authored reason;
  conditional `received:`/`cause:`/`Call log:` details section; unpadded verdict block) composed
  once at exception construction and consumed verbatim by the exception text, the log record and
  the `on_step_failed` hook payload;
- `PageFacade.url` — the current URL as one immediate read unit inside the driver worker thread;
- a `page_url` input on the LLM port rendered as a `PAGE URL` line after the page snapshot, plus
  verbatim multi-line HISTORY turn records in guided requests;
- a nine-step steering dialog: banner with step/code/render/URL/screenshot-path/commands, a strict
  `run? [y/N]` approval gate (nothing runs unseen), full untruncated turn history records, and the
  fresh URL in every guided request.

The contract layer (`CODEMANIFEST` files, `.goga/usages/` practices, cell-level `.usages/`) is
**already materialized in the working tree** by the apply-architecture and design-review stages.
The most important contract-to-code gaps: every new/changed contract entity is unimplemented; the
four frozen prompt mirrors (`SYSTEM_PROMPT`/`CHEAT_SHEET` in `generator.py` and `steering.py`) are
stale relative to the already-updated practice files (textually verified — the mirror tests are
currently red); ~9 test files carry the old signatures and old expectations.

Implementation strategy: leaf-to-root per the design's Entity Dependencies (failures → driver →
llm → engine → steering → reporting), each task leaving the tree importable and the touched test
modules green, TDD inside every task.

## Context

### Contract Surface

**Cell: `prettyplay/failures`** (locations relative to the cell root; facade = `prettyplay.failures`)

**Entity: `decompose_error_text`** (NEW — Routine)
- Type: function; Declared `location`: `errors.py` (`prettyplay/failures/errors.py`)
- Signature: `decompose_error_text(error: str) -> parts: ErrorParts`
- Facade obligation: importable from `prettyplay.failures`, listed in `__all__`
- Semantic requirements: pure recognition of the full underlying error text into the render parts
  — no state, no I/O, never raises on any input; the empty string yields all-empty parts; the
  first-line dotted-identifier class prefix; the fixed shapes `Actual value:` / `Caused by:` /
  `Call log:` recognized by prefix only, never by position; unrecognized shapes leave parts empty.
- Imported dependencies: none; `re` (stdlib) joins the module for the class-prefix shape
- Annotation context: file level `Use \`conventions\` …`, `Use \`playwright\` for the error message
  shapes the decomposition recognizes` → the shapes come from the "Message anatomy of a failed
  expectation" section of the `playwright` practice

**Entity: `ErrorParts`** (NEW — Entity)
- Type: class; Declared `location`: `errors.py`
- Signature: `ErrorParts(class_name: str, reason: str, received: str, cause: str, call_log: str)`
- Facade obligation: importable from `prettyplay.failures`, listed in `__all__` (nine names total)
- Properties: `class_name`, `reason`, `received`, `cause`, `call_log` — all `-> str`, all `""` when absent
- Semantic requirements: pydantic v2 model, `kw_only=True`, empty-string defaults (the
  `conventions` data-model rule); no behavior beyond the data shape; `FailureVerdict` stays a
  frozen dataclass — the two coexist in `errors.py` deliberately

**Entity: `render_terminal_message`** (CHANGED — Routine)
- Signature: `render_terminal_message(error_class: str, reason: str, step_text: str, error: str, verdict: FailureVerdict | None) -> text: str` — `error_class` FIRST, five parameters
- Behavioral change: first line `f"{error_class}: {reason}"`; the `error:` line becomes the
  decomposed headline (`f"{parts.class_name}: {parts.reason}"` when `class_name` non-empty, else
  `parts.reason`); a conditional details section (`received:` / `cause:` / `Call log:` + verbatim
  lines) appears between the step section and the verdict block; no label padding anywhere
- Requirements (fixed block order: first line, step/error, details, verdict; details omitted
  entirely when no detail part present; both step and headline empty → whole step section omitted,
  no bare separator; the render ends without a trailing separator; never embed step code or a page
  snapshot)

**Entity: `FailureVerdict.render`** (CHANGED — method)
- Labels at column zero (`explanation:`, `recommendation:`), two-space continuation indent for
  embedded newlines, category still dropped; empty string when both fields are empty; the
  `_VERDICT_LABEL_WIDTH` alignment constant dies with the change

**Entities: `PrettyplayError::ProductDefectError` / `PrettyplayError::IncurableStepError`** (CHANGED constructors)
- Unchanged signatures and attribute contracts (`message` keeps the primary reason, not the render;
  `IncurableStepError.code` untouched by rendering); the render call gains the first argument
  `type(self).__qualname__` — the **short class name** (user-approved design decision q2; NOT the
  module-qualified dotted path); `IncurableStepError` keeps the render-only fallback verdict
  (`FailureVerdict("incurable", "", _FALLBACK_GUIDANCE)`) when `verdict is None`, without mutating
  `self.verdict`

**Cell: `prettyplay/driver`** (facade = `prettyplay.driver`)

**Entity: `PageFacade.url`** (NEW — property)
- Type: `@property`; Declared `location`: `page.py` (`prettyplay/driver/page.py`)
- Signature: `url -> str`
- Facade obligation: `PageFacade` already exported; the named plumbing members are fixed at
  exactly five: run, url, aria_snapshot, screenshot, close
- Semantic requirements: the current URL — an immediate read (the `playwright` practice rule),
  executed inside the driver worker thread as one unit through the run primitive of the handle
  (`self._call(lambda: self._page.url)` — `_call` is the one-unit machinery behind `run`); the
  calling thread never adopts the Playwright event loop; reads serialize with every other unit of
  the session; plain string back, never a Playwright object; an empty string never occurs on a
  live page; a closed page raises — the caller guards

**Cell: `prettyplay/llm`** (facade = `prettyplay.llm`)

**Entity: `LLMProvider.generate_step_code`** (CHANGED — port method)
- Signature grows `page_url: str | None` inserted AFTER `snapshot` (contract order), before `screenshot`
- `page_url`: non-empty — rendered by the provider implementations as its own `PAGE URL` line
  immediately after the `PAGE SNAPSHOT` block of the user content, identically in both; None — no
  line; supplied by the interactive steering only
- `guidance_history` semantics change: full multi-line turn records (engineer message, complete
  generated code, complete outcome) composed by the calling steering; rendered verbatim, no
  collapsing, no size limits
- The `code` return docstring wording: "imports from playwright.sync_api and the Python standard
  library only, global at the top level of the code block" (corrected import policy)
- The new inputs take no part in step addressing: a cached step never regenerates because they changed

**Entities: `LLMProvider::OpenAIProvider` / `LLMProvider::AnthropicProvider`** (CHANGED — identical extension)
- Both implementations gain the parameter and forward it to the shared `build_fields_text` BY
  KEYWORD (`page_url=page_url`) — positional forwarding across the widened signature is the drift
  risk the keyword form removes; parity by construction: one shared builder, both providers identical

**Entity: `build_fields_text`** (CHANGED — internal shared builder, `prettyplay/llm/_request.py`)
- Parameter `page_url: str | None` after `snapshot`; the scenario part becomes
  `[STEP, PREVIOUS STEPS, PAGE SNAPSHOT] + ([f"PAGE URL: {page_url}"] when page_url else []) + [CHEAT SHEET] …`;
  the fixed tail order (CODE, ERROR, RECOMMENDATION, USER GUIDANCE, HISTORY) is untouched; HISTORY
  mechanism unchanged (`"HISTORY:\n" + "\n".join(guidance_history)`)

**Cell: `prettyplay/engine`** (facade = `prettyplay.engine`)

**Entity: `StepGenerator._request`** (CHANGED — implementation-level call composition, `prettyplay/engine/generator.py`)
- The `generate_step_code` call adds `page_url=None` beside `guidance=None` (comment: the URL
  input is steering-only — uniform with the guidance None); `regenerate`/`_funded_regeneration`
  share `_request`/the same call shape, so every engine request is covered
- `SYSTEM_PROMPT` / `CHEAT_SHEET` frozen mirrors ← the practices, verbatim (see Re-exports/mirror
  discipline below)

**Cell: `prettyplay/engine/steering`** (facade = `prettyplay.engine.steering`)

**Entity: `StepSteering.steer`** (REWRITTEN — the nine-step turn algorithm; full algorithm in Task 6)
- The turn model: generate → show the complete code → strict approval gate → execute; rejected and
  failed turns append full records to the history and the prompt reopens; URL in every request and
  in the banner (banner only, never per turn); no snapshot fragment in the banner; dead helpers
  (`_snapshot_fragment`, `_SNAPSHOT_FRAGMENT_LINES`, `_first_line`) removed

**Cell: `prettyplay/reporting`** (facade = `prettyplay.reporting`)

**Entity: `StepHooks.on_step_failed`** (wording-level)
- No behavioral change: `StepExecutor.execute` already emits `str(error)` — the render, verbatim —
  into the payload and the reporter logs it; optional docstring alignment naming the template
  sections, mirroring the contract sentence

### Entity Interaction and Data Flow (verbatim from the design)

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

Implementation order (leaf → root, every step leaves the tree importable):

1. `prettyplay/failures` — `decompose_error_text`, `ErrorParts`, the render changes, the facade
   exports.
2. `prettyplay/driver` — `PageFacade.url`.
3. `prettyplay/llm` — the port signature, `build_fields_text`, both providers.
4. `prettyplay/engine` — the `SYSTEM_PROMPT`/`CHEAT_SHEET` mirrors, `_request` passes
   `page_url=None`.
5. `prettyplay/engine/steering` — the `SYSTEM_PROMPT`/`CHEAT_SHEET` mirrors, the `steer` rewrite.
6. `prettyplay/reporting` — no code change; optional docstring wording for `on_step_failed`.
7. Root usages — already updated by apply-architecture; no further work.

### Re-exports

- Name: `ErrorParts`, `decompose_error_text` — Source: defined in `prettyplay/failures/errors.py`;
  Facade obligation: importable from `prettyplay.failures`; `__all__` grows from seven to nine
  names (alphabetical, existing style). No other cell's facade changes.

### Usages Context

- `conventions` (`.goga/usages/conventions.md`): mandatory code rules — relative intra-package
  imports; pydantic data models with `kw_only=True` and empty defaults (`None` only for explicit
  absence); Google-style docstrings on every public function/method/class; logging with
  `logging`, lowercase structured events with `extra` metadata; tests mirror the source tree
  (`tests/<pkg>/test_<module>.py`, `class Test<Component>:` grouping, self-documenting names);
  one blank line between logical blocks inside bodies. Relevant to every changed file; `ErrorParts`
  applies the data-model rule directly.
- `playwright` (`.goga/usages/cooks/playwright.md`) — failures cell: the "Message anatomy of a
  failed expectation" section is the authority for the decomposition shapes (`Actual value:`,
  `Caused by:`, `Call log:` blocks, the expectation headline) and the dotted error-head surface
  (`TimeoutError:`, `Page.reload:`). Already carries the import-policy contour — do not duplicate.
- `playwright` — driver cell (already connected): the `page.url` immediate-read rule (beside
  `to_have_url`/`wait_for_url`) — the plumbing property is the library-side twin of that rule.
- `system_prompt` (`.goga/usages/prompts/generation.md`): the single source of the
  generation/regeneration system prompt — already updated (the import rule, the `- PAGE URL:`
  input line, the HISTORY record description). Used by both frozen mirrors.
- `cheat_sheet` (`.goga/usages/prompts/cheatsheet.md`): the compact API reference — already
  updated with the URL idioms (`page.url` beside the waiting forms; `assert "/dashboard" in
  page.url`). Used by both `CHEAT_SHEET` mirrors (whole-file verbatim).

### Imported Usages

- `configuration` from `prettyplay/config` (driver cell) — unchanged; the browser-group settings
  context for the session. No implementation impact in this plan.
- `classification` from `prettyplay/llm` (engine cell) — unchanged; the healing decision
  categories. No implementation impact in this plan.

### Local Usages

No new `.usages/` files. Per the design's `.usages/` Update section every cell-level usage file is
already current (updated together with the contracts by apply-architecture; the design-review
stage aligned wording): `failures/taxonomy.md`, `driver/plumbing.md`, `llm/providers.md`,
`engine/generation.md`, `engine/healing.md`, `engine/steering/steering.md`,
`reporting/hooks.md`, root `steps.md` and `lifecycle.md`. **No task touches them.**

### External Dependencies

- `pydantic>=2.7` — `ErrorParts` (`BaseModel`, `ConfigDict(kw_only=True)`)
- `playwright>=1.49` — `Page.url` immediate read (sync API); `PlaywrightError` in test fakes
- `openai>=1.30`, `anthropic>=0.28` — provider SDKs (request composition only; no new SDK surface)
- `pytest>=8.0`, `ruff>=0.15.0` — test/lint gate (project virtualenv)
- `re` (stdlib) — the class-prefix shape in `errors.py`

## Facts

- The contract layer is already materialized and uncommitted in the working tree: 10 CODEMANIFEST
  files, the root practices (`generation.md`, `cheatsheet.md`, `cooks/playwright.md`,
  `conventions.md`) and the cell-level `.usages/` files. `goga lint` after the design-review
  fixes: cells 10, errors 0. They are READ-ONLY for the implementation agent.
- Verified textually: all four frozen mirrors are stale — `generator.SYSTEM_PROMPT`,
  `steering.SYSTEM_PROMPT` (≠ post-`---` section of `generation.md`), `generator.CHEAT_SHEET`,
  `steering.CHEAT_SHEET` (≠ `cheatsheet.md`). The mirror tests
  (`test_system_prompt_mirrors_the_generation_practice`, `test_cheat_sheet_mirrors_the_practice`,
  `test_steering_mirrors_the_practices`) are currently red. They go green only when the constants
  are re-copied verbatim (Tasks 5 and 6).
- `render_terminal_message` currently has four parameters (no `error_class`, no details section);
  `FailureVerdict.render` aligns to `_VERDICT_LABEL_WIDTH = len("recommendation:")`.
- `tests/driver/test_page.py` currently asserts `url` is DELETED
  (`test_deleted_members_are_gone` lists it) and the handle surface is exactly
  `{"run", "aria_snapshot", "screenshot", "close"}` — both assertions flip in Task 3.
- `generate_step_code` (port + both providers + `build_fields_text`) currently has no `page_url`;
  `tests/llm/test_provider.py` asserts the exact parameter list (`GENERATE_STEP_CODE_PARAMS`).
- Fake/stub ports carrying the old signature live in: `tests/engine/steering/test_steering.py`
  (`FakeProvider`), `tests/engine/test_generator.py` (`StubProvider`),
  `tests/engine/test_healer.py`, `tests/test_integration.py`, `tests/test_scenario.py`,
  `tests/test_executor.py`. The engine-driven ones break with `TypeError` once `_request` passes
  the `page_url` keyword (Task 5); the steering one breaks at the port-parity level (Task 6).
- The current steering history collapses red turns to the first line
  (`f"{message} => {_first_line(str(outcome))}"`) and the banner shows an `intent:` line, verdict
  lines and a 20-line snapshot fragment — all replaced by this plan.
- The executor (`prettyplay/executor.py`) calls `steer(failure, identity, previous_steps, page)`
  and propagates the original failure on None — signature unchanged, no executor change needed.
- `FailureVerdict` is a frozen dataclass and stays one (its own contract is unchanged); only
  `ErrorParts` is pydantic.
- The example repro `example/tests/test_youtube.py` (working tree) is the manual acceptance
  scenario for the interactive loop (live browser + provider keys — outside pytest).
- Test/lint commands run in the project virtualenv (`.venv`); the committed `.venv` is a macOS
  artifact — on a machine where it is broken, recreate it (`python -m venv .venv &&
  .venv/bin/pip install -e ".[test]"`) before running the gate.

## Gap Analysis

- Missing contract entities: `decompose_error_text`, `ErrorParts` (failures), `PageFacade.url`
  (driver) — none exist in code.
- Missing facade exposure: `ErrorParts`, `decompose_error_text` absent from
  `prettyplay.failures.__all__` (seven names; contract says nine).
- API mismatches: `render_terminal_message` signature (4 vs contract 5 params, `error_class`
  first); `generate_step_code` missing `page_url` (port, both providers, `build_fields_text`);
  `StepGenerator._request` does not pass `page_url=None`; `StepSteering.steer` implements the old
  auto-execute loop (no approval gate, collapsed history, fragment banner, no URL).
- Behavioral mismatches: no details section / no decomposed headline in the render; verdict label
  padding; terminal constructors pass no class name; mirrors stale; engine/steering requests carry
  no URL; HISTORY records collapsed.
- Existing code that can be reused: `_call` worker-unit machinery (driver) — the url property is
  one expression over it; `build_fields_text` section-list shape — one conditional insert; the
  steering skeleton (banner/prompt/local commands/gate/write-back helpers, guarded reads) — the
  rewrite keeps the collaborators and most helpers, replacing the loop body, banner and history.
- Test coverage gaps: every design test scenario in "Test Stack Trace" is new or changed (32
  scenarios); the regression surface spans `tests/failures/test_errors.py`,
  `tests/driver/test_page.py`, `tests/llm/{test_provider,test_request,test_openai_provider,
  test_anthropic_provider}.py`, `tests/engine/test_generator.py`, `tests/engine/test_healer.py`,
  `tests/engine/steering/test_steering.py`, `tests/test_integration.py`,
  `tests/test_scenario.py`, `tests/test_executor.py`.
- Visibility: all changed files are tracked in git on branch `fix-interactive-loop`; the contract
  edits are uncommitted working-tree changes — leave them as they are (they belong to this
  feature's committed diff, assembled by the pipeline).

---

## Tasks

> **Package ordering rule**: coding tasks for each package are completed before starting the next.
> Within each coding task, contract tests are written first (TDD workflow). Order:
> failures → driver → llm → engine → steering → reporting → integration sweep.

### Task 1: `decompose_error_text` + `ErrorParts` + facade exports (failures)

Decompose the full underlying error text of a failed step into the render parts — the pure
recognition half of the failures-cell change. Two NEW contract entities in
`prettyplay/failures/errors.py` plus two facade exports in `prettyplay/failures/__init__.py`.
Nothing existing changes behavior in this task: `render_terminal_message` keeps its old four
parameter signature until Task 2, so the tree stays green after this task.

**Usages relevant to this task:**
- `conventions`: pydantic v2 data model with `kw_only=True` and empty-string defaults; relative
  intra-package imports; Google-style docstrings; test naming `test_<what>_<scenario>` under
  `class Test<Component>:`.
- `playwright` (failures cell): the "Message anatomy of a failed expectation" section is the
  authority for the recognized shapes — match prefixes exactly, never positions.

**CRITICAL: `CODEMANIFEST` files and `.goga/usages/` practices — read-only contract definitions.
Do NOT modify them. If implementation does not match the contract, fix the implementation — never
fix the contract.**

- [x] **STEP 0 — Declaration**: declare this task (Task 1, failures cell) before starting
- [x] **Contract tests**: in `tests/failures/test_errors.py` — `from prettyplay.failures import
  ErrorParts, decompose_error_text` importable and both in `__all__`; update
  `test_all_seven_names_importable_from_facade` → nine names (rename to
  `test_all_nine_names_importable_from_facade`) and `test_facade_all_lists_seven_names` →
  `test_facade_all_lists_nine_names` asserting the exact nine-name list (alphabetical:
  ComplianceVerdictError, ErrorParts, FailureVerdict, IncurableStepError, LLMUnavailableError,
  PrettyplayError, ProductDefectError, decompose_error_text, render_terminal_message); new
  signature test: `list(inspect.signature(decompose_error_text).parameters) == ["error"]`;
  `ErrorParts` constructor is keyword-only with five `str` fields (expected to fail at this stage)
- [x] **Code**: in `prettyplay/failures/errors.py` — add `import re` and
  `from pydantic import BaseModel, ConfigDict`; define the class-prefix shape
  `_CLASS_HEAD = re.compile(r"^([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*):(?:\s+(.*))?$")`
- [x] **Code**: implement `ErrorParts(BaseModel)` with
  `model_config = ConfigDict(kw_only=True)` and five `str` fields (`class_name`, `reason`,
  `received`, `cause`, `call_log`) each defaulting `""`; docstring per the contract annotations
- [x] **Code**: implement `decompose_error_text(error: str) -> ErrorParts` exactly per the design
  algorithm:
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
  Never raises on any input (total, deterministic, no I/O). The whitespace-or-EOL requirement
  after the colon in step 3 is what keeps `net::ERR_…` heads unrecognized (the second colon
  breaks the shape) — the whole line stays the reason.
- [x] **Code**: in `prettyplay/failures/__init__.py` — add `ErrorParts` and `decompose_error_text`
  to the import block and `__all__` (nine names, alphabetical order)
- [x] **Interface verification**: `pytest tests/failures/test_errors.py -q` — the new contract
  tests pass; `python -c "from prettyplay.failures import ErrorParts, decompose_error_text"`
  (project virtualenv)
- [x] **Logic tests**: in `tests/failures/test_errors.py` (new `class TestDecomposeErrorText:`
  and extend where natural) — the design scenarios, representative text reused across them:
  ```
  Locator expected to be visible
  Actual value: display:none
  Call log:
    - waiting for get_by_role("button", name="Sign in")
  ```
  - `test_decompose_extracts_all_parts_of_an_expect_failure`: parts.class_name == "",
    reason == "Locator expected to be visible", received == "display:none", cause == "",
    call_log == '  - waiting for get_by_role("button", name="Sign in")'
  - `test_decompose_extracts_typed_error_head`: input
    `"TimeoutError: Timeout 30000ms exceeded\n=========================== logs ====…"` →
    class_name == "TimeoutError", reason == "Timeout 30000ms exceeded", received == "",
    call_log == "" (the logs appendix ignored)
  - `test_decompose_extracts_cause_line` (decompose half): input
    `"TimeoutError: Page.goto failed\nCaused by: net::ERR_CONNECTION_REFUSED at https://x.test"` →
    class_name == "TimeoutError", reason == "Page.goto failed", received == "",
    cause == "net::ERR_CONNECTION_REFUSED at https://x.test", call_log == ""
    (the render-side `cause:` assertion joins this test in Task 2)
  - `test_decompose_unrecognized_shapes_leave_parts_empty`: input
    `"weird failure text\nno shapes here"` → class_name == "", reason == "weird failure text",
    received == cause == call_log == "", no exception
  - `test_decompose_empty_error_yields_all_empty_parts`: input `""` → all five fields `""`
  - `test_decompose_multiline_actual_value_is_preserved`: an `Actual value:` continuing on
    following lines until `Call log:` → received keeps every continuation line verbatim,
    `\n`-joined
  - `test_decompose_net_error_head_is_not_a_class`: input
    `"net::ERR_CONNECTION_REFUSED at https://x.test"` → class_name == "", reason == the whole line
  - `test_error_parts_is_pydantic_kw_only_with_empty_defaults`: `ErrorParts(class_name="X")`
    leaves the other four `""`; `ErrorParts(reason="r", class_name="c")` works; positional
    construction raises `TypeError`
- [x] **Debugging**: `pytest tests/failures/test_errors.py -x` — fix implementation code until all
  tests pass (do NOT fix test expectations to match broken code)
- [x] **Contract re-verification**: facade nine names; pure total routine; pydantic kw_only shape;
  no existing failure behavior changed (the old render tests still pass untouched)
- [x] **Lint**: `ruff check prettyplay/failures tests/failures` — fix formatting if necessary
- [x] **STEP 8 — Completion**: mark the checkboxes complete; submit for review

### Task 2: the decomposed render — `render_terminal_message`, `FailureVerdict.render`, terminal constructors (failures)

Rework the render half of the failures cell, now that `decompose_error_text` exists. Same
`location` (`prettyplay/failures/errors.py`); the facade does not change further. Three contract
changes land together because they form one output text: the routine signature + template, the
verdict block, and the constructors feeding `type(self).__qualname__`.

**Usages relevant to this task:**
- `conventions`: docstring updates for changed signatures; Google style; test naming.
- `playwright`: the shapes feeding the details section (already pinned by Task 1).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If
implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **STEP 0 — Declaration**: declare this task (Task 2, failures cell) before starting
- [x] **Contract tests**: in `tests/failures/test_errors.py` — update
  `test_render_terminal_message_signature_is_four_parameters` → five parameters
  `["error_class", "reason", "step_text", "error", "verdict"]`; `FailureVerdict.render` stays a
  callable method (expected to fail at this stage)
- [x] **Code**: `render_terminal_message` — new signature (`error_class` first) and template
  exactly per the design algorithm:
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
  Pure; docstring updated (five Args; the details-section and omission rules). Note the
  `error:` line semantics: for a failed check the underlying error carries no AssertionError
  prefix (`format_step_error` policy) so `class_name` stays empty and the headline is the
  expectation text alone; for typed errors the prefix reconstructs the kind.
- [x] **Code**: `FailureVerdict.render` — drop the alignment: labels at column zero, two-space
  continuation indent; delete the `_VERDICT_LABEL_WIDTH` constant:
  ```
  for (label, value) in (("explanation", e), ("recommendation", r)):
      if value: emit f"{label}: {value.replace('\n', '\n  ')}"
  join with "\n"
  ```
- [x] **Code**: `ProductDefectError.__init__` / `IncurableStepError.__init__` — the render call
  gains the first argument `type(self).__qualname__` (the SHORT class name — user-approved
  decision; do NOT switch to the module-qualified dotted path); attributes stored exactly as
  today; `IncurableStepError` keeps the render-only fallback verdict when `verdict is None`
  (`self.verdict` stays None); update docstrings; `type(self).__qualname__` is correct under
  subclassing (renders the actual raised type)
- [x] **Interface verification**: `pytest tests/failures/test_errors.py -q` — contract tests pass
- [x] **Logic tests**: in `tests/failures/test_errors.py` — the design scenarios:
  - `test_render_composes_the_full_template`: verdict =
    `FailureVerdict("fixable", "the button is behind the modal", "dismiss the modal first")`,
    error = the representative expect-failure text; input
    `render_terminal_message("IncurableStepError", "the generation budget is exhausted",
    "click Checkout", error, verdict)`; assert the exact 11-line equality (joined with `\n`):
    first line `IncurableStepError: the generation budget is exhausted`, then
    `---`, `step: click Checkout`, `error: Locator expected to be visible`, `---`,
    `received: display:none`, `Call log:`,
    `  - waiting for get_by_role("button", name="Sign in")`, `---`,
    `explanation: the button is behind the modal`, `recommendation: dismiss the modal first`;
    labels at column zero, no padding
  - `test_render_omits_the_details_section_without_parts`: input error
    `"TimeoutError: Timeout 30000ms exceeded"`, verdict None → output is exactly
    `"IncurableStepError: <reason>\n---\nstep: <step>\nerror: TimeoutError: Timeout 30000ms exceeded"`
    — no second `---` block, no `received:`/`cause:`/`Call log:` lines
  - `test_verdict_render_labels_at_column_zero_with_two_space_continuations`:
    `FailureVerdict("rot", "two\nlines", "do X")` →
    `render() == "explanation: two\n  lines\nrecommendation: do X"`
  - `test_product_defect_first_line_carries_its_own_class_name`:
    `ProductDefectError("s", "the button stayed invisible", "", None)` →
    `str(exc).splitlines()[0] == "ProductDefectError: the button stayed invisible"`;
    `exc.message == "the button stayed invisible"`; the same shape test for `IncurableStepError`
    additionally asserts the fallback `recommendation:` line renders when the verdict is None
  - `test_render_error_line_reconstructs_typed_headline`: error
    `"Page.reload: Timeout 30000ms exceeded"` → the `error:` line reads
    `error: Page.reload: Timeout 30000ms exceeded` (dotted head preserved inside the headline,
    distinct from the first line's terminal class)
  - `test_render_empty_error_omits_step_error_entirely_when_step_also_empty`: `error=""`,
    `step_text=""`, verdict None → output is exactly the first line — no `---` anywhere
  - `test_verdict_render_empty_fields_yield_empty_block`: `FailureVerdict("rot", "", "")` →
    `render() == ""` and a render with that verdict carries no verdict section
  - extend `test_decompose_extracts_cause_line` (Task 1) with the render half:
    `render_terminal_message("IncurableStepError", "r", "s", input, None)` contains the line
    `cause: net::ERR_CONNECTION_REFUSED at https://x.test` between the `---` separators of the
    details section
  - update the existing render-shape expectations to the new template (they pin the same
    contract, now five-param and decomposed): `test_render_terminal_message_full_template`,
    `test_verdict_render_alignment_and_multiline`,
    `test_render_terminal_message_block_omission`,
    `test_render_lists_aligned_fields_without_category` (column-zero labels + two-space
    continuations), `test_no_code_error_renders_the_pre_change_form`,
    `test_verdict_bearing_error_with_code_renders_verdict_block_without_code` — every call site
    grows the `error_class` argument; `str(error)` first lines now carry the terminal class name
- [x] **Debugging**: `pytest tests/failures/test_errors.py -x` — fix implementation until green;
  then `pytest tests/ -x` to surface cross-suite consumers of the render (executor/reporter
  assertions on `str(error)` shapes) and align those expectations to the new template — the
  render contract itself never bends
- [x] **Contract re-verification**: one render feeds exception message + `on_step_failed`
  payload + log record (no re-composition — `render_terminal_message` is called only from the two
  constructors); block order fixed; omission rules; no step code / snapshot embedded; no label
  padding; short class name on the first line
- [x] **Lint**: `ruff check prettyplay/failures tests/failures` — fix formatting; confirm
  `_VERDICT_LABEL_WIDTH` is gone
- [x] **STEP 8 — Completion**: mark the checkboxes complete; submit for review

### Task 3: `PageFacade.url` — the worker-thread URL read (driver)

One NEW contract property in `prettyplay/driver/page.py`. The plumbing member set is fixed at
exactly five (run, url, aria_snapshot, screenshot, close) — the tests currently assert the old
four-member set and that `url` is deleted; both flip here. Insert the property BEFORE the methods
block (properties first — the contract lists it under `properties`).

**Usages relevant to this task:**
- `playwright` (driver cell): the `page.url` immediate-read rule — a plain read, no waiting form.
- `configuration` from Imports (driver cell): unchanged in this task — the browser-group settings
  context of the session; the property reads no settings.
- `conventions`: docstring (Google style, `Returns:` section), test naming.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If
implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **STEP 0 — Declaration**: declare this task (Task 3, driver cell) before starting
- [x] **Contract tests**: in `tests/driver/test_page.py` — update
  `test_page_handle_surface_matches_contract`: public set ==
  `{"url", "run", "aria_snapshot", "screenshot", "close"}`; update
  `test_deleted_members_are_gone`: remove `"url"` from the deleted list; new:
  `url` is a `property` on `PageFacade` with return annotation `str` (expected to fail)
- [x] **Code**: in `prettyplay/driver/page.py`, insert before the methods block:
  ```
  @property
  def url(self) -> str:
      return self._call(lambda: self._page.url)
  ```
  Docstring: the current URL — an immediate read executed as one unit inside the driver worker
  thread; plain string back. `_call` is the one-unit machinery behind `run` (the same the other
  plumbing members use): with a worker it queues one unit on the driver thread and re-raises the
  outcome as-is; without a worker (tests) it runs inline; the unit's `finally` runs the deferred
  dialog pass
- [x] **Interface verification**: `pytest tests/driver/test_page.py -q` — contract tests pass
- [x] **Logic tests**: in `tests/driver/test_page.py` —
  `test_page_facade_url_reads_through_the_worker_unit`: `FakeRawPage` grows a `url` attribute
  (`"https://shop.example.com/cart"`); a hand-built `PageFacade` over it returns the value
  (inline path); a handle bound to a worker records exactly one queued unit containing the read —
  follow the file's existing worker idioms (`PlaywrightWorker` with `seen_threads` recording, or a
  recording fake worker with `run(unit)` capturing the callable); nothing else runs concurrently;
  extend `test_kept_members_of_a_live_handle_marshal_to_the_driver_thread` with the `url` read
  (runs on the worker thread, never the calling thread)
- [x] **Debugging**: `pytest tests/driver/test_page.py -x` — fix implementation until green
- [x] **Contract re-verification**: the calling thread never adopts the event loop; the read
  serializes with every other unit; a plain `str` returns (no Playwright object crosses the
  boundary); no member proxies beyond the five named plumbing members
- [x] **Lint**: `ruff check prettyplay/driver tests/driver` — fix formatting if necessary
- [x] **STEP 8 — Completion**: mark the checkboxes complete; submit for review

### Task 4: the `page_url` input through the port, the shared builder and both providers (llm)

One contract change across the four files of the llm cell: the port stub
(`prettyplay/llm/provider.py`), the shared builder (`prettyplay/llm/_request.py`), and both SDK
implementations (`prettyplay/llm/openai_provider.py`, `prettyplay/llm/anthropic_provider.py`).
Provider parity is by construction: one shared builder, both implementations identical; the
keyword forwarding (`page_url=page_url`) removes the positional-drift risk across the widened
signature.

**Usages relevant to this task:**
- `conventions`: docstring updates mirror the contract wording; `# noqa: PLR0913, PLR0917`
  comments on the widened signatures follow the existing style.
- The corrected import policy wording ("imports from playwright.sync_api and the Python standard
  library only, global at the top level of the code block") comes verbatim from the llm
  CODEMANIFEST `code` return annotation — copy it, do not paraphrase.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If
implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **STEP 0 — Declaration**: declare this task (Task 4, llm cell) before starting
- [x] **Contract tests**: in `tests/llm/test_provider.py` — `GENERATE_STEP_CODE_PARAMS` grows
  `"page_url"` right after `"snapshot"` (the exact port-signature assert); the existing adjacency
  asserts keep holding with the insertion; both provider files'
  `test_generate_step_code_signature_matches_port` keep passing once implementations grow the
  parameter identically (expected to fail at this stage)
- [x] **Code**: `prettyplay/llm/provider.py` — insert `page_url: str | None` after `snapshot` in
  `LLMProvider.generate_step_code`; docstring gains the `page_url` semantics (non-empty — its own
  PAGE URL line immediately after the PAGE SNAPSHOT block, identically in both; None — no line;
  supplied by the interactive steering only), the `guidance_history` full-record semantics (each
  record a complete multi-line turn: engineer message, complete generated code, complete outcome;
  verbatim, no collapsing, no size limits) and the corrected import-policy wording of the `code`
  return
- [x] **Code**: `prettyplay/llm/_request.py` — `build_fields_text` gains `page_url: str | None`
  after `snapshot`; the scenario part becomes
  `[STEP, PREVIOUS STEPS, PAGE SNAPSHOT] + ([f"PAGE URL: {page_url}"] when page_url else []) +
  [CHEAT SHEET] …` — the rest untouched; docstring updated
- [x] **Code**: both providers — `generate_step_code` gains the parameter (after `snapshot`);
  forward `page_url=page_url` BY KEYWORD to the shared `build_fields_text`; docstrings updated
  identically (parity)
- [x] **Interface verification**: `pytest tests/llm -q` — contract tests pass
- [x] **Logic tests**:
  - `tests/llm/test_request.py` — `test_build_fields_places_page_url_line_after_snapshot`:
    `build_fields_text(user_instructions="", step_text="s", previous_steps=[], snapshot="- body",
    page_url="https://x.test/a", cheat_sheet="CS", existing_code=None, error=None,
    recommendation=None, guidance=None, guidance_history=[])` → the section order is
    `STEP … PREVIOUS STEPS … PAGE SNAPSHOT …` then `"PAGE URL: https://x.test/a"` as its own
    paragraph, then `CHEAT SHEET:`; parametrize the no-line case over `[None, ""]` — no `PAGE URL`
    substring appears anywhere
  - `tests/llm/test_request.py` — `test_history_block_renders_full_multi_line_records`:
    `guidance_history=[record1, record2]` where record1 embeds a multi-line code block and a
    multi-line outcome → the HISTORY section contains both records verbatim — every line of the
    code and the outcome present, order preserved, no truncation markers
  - `tests/llm/test_provider.py` — `TestSteeringInputsParity`: the shared parity test grows the
    `page_url="https://…"` kwarg and asserts the PAGE URL line in both rendered user texts
  - `tests/llm/test_openai_provider.py` / `tests/llm/test_anthropic_provider.py` — every
    `generate_step_code` call fixture gains `page_url` (None or a URL per scenario); a request
    with a URL carries the PAGE URL line after the snapshot, a None request carries none
- [x] **Debugging**: `pytest tests/llm -x` — fix implementation until green
- [x] **Contract re-verification**: block order of a generation request is fixed (CHEAT SHEET,
  user instructions, CODE, ERROR, RECOMMENDATION, USER GUIDANCE, HISTORY); the PAGE URL line
  renders in the scenario part immediately after PAGE SNAPSHOT; the fixed order of the
  regeneration tail is unchanged; the new inputs take no part in step addressing
- [x] **Lint**: `ruff check prettyplay/llm tests/llm` — fix formatting if necessary
- [x] **STEP 8 — Completion**: mark the checkboxes complete; submit for review

### Task 5: engine frozen mirrors + `page_url=None` + engine-driven fake updates (engine)

Two changes in `prettyplay/engine/generator.py`: re-copy the frozen mirrors (currently stale —
the mirror tests are red) and add `page_url=None` to `_request`. The moment `_request` passes the
keyword, every engine-driven fake port without the parameter raises `TypeError` — the fake
updates land in this task, not as a follow-up.

**Usages relevant to this task:**
- `system_prompt` (`.goga/usages/prompts/generation.md`): the single source — the mirror is the
  post-`---` section, verbatim. Mirror discipline: copy-paste from the file, never hand-edit
  prose; the mirror tests are the acceptance.
- `cheat_sheet` (`.goga/usages/prompts/cheatsheet.md`): the whole file, verbatim (no `---`
  separator — no extraction logic to drift).
- Do NOT edit the practice files themselves — they are already current (apply-architecture did
  the practice side; only the mirrors and the code change now).
- `classification` from Imports (engine cell): unchanged in this task — the healing decision
  categories; no classification behavior changes here.

**CRITICAL: `CODEMANIFEST` files and `.goga/usages/` practices — read-only contract definitions.
Do NOT modify them. If implementation does not match the contract, fix the implementation — never
fix the contract.**

- [x] **STEP 0 — Declaration**: declare this task (Task 5, engine cell) before starting
- [x] **Contract tests**: the existing mirror tests are the contract tests (currently red):
  `test_system_prompt_mirrors_the_generation_practice` and
  `test_cheat_sheet_mirrors_the_practice` in `tests/engine/test_generator.py` — they compare the
  constants against the practice files and define done for the mirror half
- [x] **Code**: `prettyplay/engine/generator.py` — `SYSTEM_PROMPT` ← the section after the `---`
  separator of `.goga/usages/prompts/generation.md`, verbatim (adds: the `- PAGE URL:` input line
  after `- PAGE SNAPSHOT:`; the HISTORY input line carrying "each record carries the full engineer
  message, the complete generated code and the complete outcome of the turn"; the new import rule
  "Import from playwright.sync_api and the Python standard library only — no third-party
  libraries; imports are global only: at the top level of the code block, before `def step`,
  never inside the function body"); `CHEAT_SHEET` ← `.goga/usages/prompts/cheatsheet.md` whole
  file, verbatim (adds `page.url  # the current URL — an immediate read beside the waiting forms`
  in "Navigation and waits" and `assert "/dashboard" in page.url` in "Immediate reads with plain
  asserts")
- [x] **Code**: `StepGenerator._request` — the `generate_step_code` call adds `page_url=None`
  beside `guidance=None`, with the comment that the URL input is steering-only — uniform with the
  guidance None; `regenerate`/`_funded_regeneration` share `_request`, so every engine request is
  covered
- [x] **Interface verification**: `pytest tests/engine/test_generator.py -q` — mirror tests pass
- [x] **Logic tests**:
  - `tests/engine/test_generator.py` — `StubProvider.generate_step_code` grows `page_url:
    str | None = None` (after `snapshot`) and records it in the calls dict; new
    `test_engine_requests_pass_page_url_none`: generator over the recording stub, a `FakePage`,
    budgets allowing one attempt; `generate(identity, "step", [], page, window)` with a green
    candidate and the gate off → the recorded call dict has `page_url is None` (uniform with
    `guidance is None`); the existing request-composition tests keep passing
  - `tests/engine/test_healer.py`, `tests/test_integration.py`, `tests/test_scenario.py` — every
    fake port's `generate_step_code` grows the `page_url` parameter (contract order, after
    `snapshot`); the recording dicts record it; engine-driven paths assert `page_url is None`
    where requests are recorded (the real `StepGenerator._request` passes the keyword; a fake
    without the parameter raises `TypeError`)
  - `tests/test_executor.py` — the three strict-mode stub providers carry the port signature for
    symmetry (never called for generation — optional, but keeps the stubs honest)
- [x] **Debugging**: `pytest tests/engine tests/test_integration.py tests/test_scenario.py
  tests/test_executor.py -x` — fix implementation until green
- [x] **Contract re-verification**: engine CODEMANIFEST `generate` step 3 ("page_url None — the
  URL input is steering-only, uniform with guidance None"); the mirrors equal the practices
  byte-for-byte; no engine request carries a URL or guidance
- [x] **Lint**: `ruff check prettyplay/engine tests/engine` — fix formatting if necessary
- [x] **STEP 8 — Completion**: mark the checkboxes complete; submit for review

### Task 6: the nine-step `steer` rewrite — approval gate, full history, URL plumbing (steering)

The core of the feature: `prettyplay/engine/steering/steering.py`. The turn model becomes
generate → show → approve → execute; rejected and failed turns append full records; the fresh URL
rides every request and the banner; the fragment machinery dies. `StepSteering.__init__`,
`_write_back`, `_screenshot_file`, `_guarded_snapshot`, `_guarded_screenshot_bytes`,
`_read_guidance` and the local-command set stay; the loop body, banner and history change.
Facade and constructor signature unchanged (the executor calls stay valid).

**Usages relevant to this task:**
- `system_prompt` / `cheat_sheet`: the frozen local mirrors — copy verbatim from the practice
  files (same content as Task 5's engine mirrors; a local copy, never an import — frozen mirrors
  stay cell-owned); `test_steering_mirrors_the_practices` is the acceptance.
- `conventions`: logging style (`steering_opened`, `steering_guidance`, `steering_declined` at
  INFO with `extra` metadata; WARNING for compliance events); test naming; English dialog strings.

**CRITICAL: `CODEMANIFEST` files and `.goga/usages/` practices — read-only contract definitions.
Do NOT modify them. If implementation does not match the contract, fix the implementation — never
fix the contract.**

- [ ] **STEP 0 — Declaration**: declare this task (Task 6, steering cell) before starting
- [ ] **Contract tests**: `test_steering_mirrors_the_practices` (currently red) — the steering
  `SYSTEM_PROMPT` equals the post-`---` section of `generation.md`, `CHEAT_SHEET` equals the whole
  `cheatsheet.md`; `FakeProvider.generate_step_code` grows the `page_url` parameter and records
  it; `FakePage` grows `url` (property or plain attribute), `DeadPage.url` raises
  `PlaywrightError("Target closed")`
- [ ] **Code**: re-copy `SYSTEM_PROMPT` and `CHEAT_SHEET` verbatim from the practice files (same
  bytes as the engine mirrors in Task 5)
- [ ] **Code**: implement `steer` exactly per the design algorithm:
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
  Pinned semantics: CODE/ERROR anchored to the original failure every turn (`failure.code`,
  `failure.error`); `recommendation=None` (the verdict diagnosis stays banner-only — the live
  guidance replaces it); `KeyboardInterrupt` during execution escapes directly (no swallow); the
  gate sits outside every exception-swallowing try; no re-execution of the same code; no budget,
  no polling
- [ ] **Code**: the record format `_turn_record(message, code, outcome)`:
  ```
  engineer message: <message>
  code:
  <complete code>
  outcome: <complete outcome>
  ```
- [ ] **Code**: the helpers —
  - `_confirm_run(code) -> bool` — prints `generated code:` + the code, returns
    `input("run? [y/N] ").strip() == "y"`; raises EOFError/KeyboardInterrupt/OSError upward
  - `_guarded_url(page) -> str | None` — `try: return page.url except Exception as failure:
    print(f"url unavailable: {failure}"); return None`
  - `_banner_line(label, text)` — label `ljust` to the banner column (`len("commands:")` = 9) +
    one space; continuation lines indented to the value column (the banner's own presentation
    padding — the render inside stays unpadded)
  - the banner: `── step "<step_text>" — about to raise IncurableStepError ──`, then the aligned
    `code:` (the failed code), `error:` (`str(failure)` — the full terminal render, continuation
    lines indented to the value column), `url:` (guarded `page.url`; a failed read prints
    `url unavailable: <failure>` and the line is omitted), `shot:` (the temporary screenshot path
    when one was taken), `commands: snapshot | screenshot | error | code | quit`. No snapshot
    fragment, no separate verdict lines (the render already carries
    explanation/recommendation), no `intent:` line (the header names the step).
    `logger.info("steering_opened", extra={"step_text": …})`
  - the progress line becomes `print("regenerating with USER GUIDANCE")` (execution now waits for
    approval — the old "executing against the live page" tail would lie)
  - the guided request `_guided_request` collects the fresh snapshot (guarded), the screenshot
    when `send_screenshots` (guarded), the fresh URL (`_guarded_url(page)` — None on failure),
    and calls `generate_step_code(prompt=SYSTEM_PROMPT,
    user_instructions=config.generation_prompt, step_text=failure.step_text, previous_steps,
    snapshot, page_url=url, screenshot, cheat_sheet=CHEAT_SHEET, existing_code=failure.code,
    error=failure.error, recommendation=None, guidance=message, guidance_history=history)`
  - delete `_snapshot_fragment`, `_SNAPSHOT_FRAGMENT_LINES`, `_first_line`; leave no unused
    imports (ruff enforces)
- [ ] **Interface verification**: `pytest tests/engine/steering/test_steering.py -q` — contract
  tests pass (mirrors green, facade unchanged)
- [ ] **Logic tests**: in `tests/engine/steering/test_steering.py` — every turn test feeds the
  approval answer after each guidance line via the existing `_script_input` queue. The design
  scenarios:
  - `test_steer_green_approved_turn_heals`: FakeProvider returns working code; stdin
    `["I solved the captcha", "y"]`; gate off; writable tmp cache → returns a `CachedStep` with
    the candidate code; cache holds it under identity; reporter saw `on_healed`; `run_step_code`
    executed exactly once; stdout contains the complete code before the approval prompt
  - `test_steer_request_carries_the_current_url`: FakePage.url =
    `"https://www.google.com/sorry?continuation=…"`, one green turn → the recorded request dict
    has `page_url == "https://www.google.com/sorry?…"`; the banner stdout `url:` line shows the
    same value; no per-turn URL print occurs
  - `test_steer_banner_shows_render_and_url_without_snapshot_fragment` (replaces
    `test_steer_banner_fragment_truncates_but_snapshot_command_prints_all`): failure with a
    verdict; FakePage snapshot of 30 lines → banner stdout contains the `error:` line with
    `str(failure)`'s first line (`IncurableStepError: <reason>`), the `url:` line, the
    `commands:` line; contains NO line of the accessibility snapshot; the `snapshot` command
    still prints all 30 lines
  - `test_steer_rejected_turn_never_executes_and_declines` (abort twin): FakeProvider returns
    code; stdin `["try this", "n", "quit"]` → returns None; `run_step_code` never called; nothing
    cached; stdout shows the complete code before the approval prompt
  - `test_steer_rejected_turn_records_and_the_next_request_carries_it` (record twin):
    FakeProvider answers `[code1, code2]` (the second green); stdin
    `["try this", "n", "try hovering first", "y"]` → turn 1 rejected → record appended → prompt
    reopens → turn 2 approved → green → heals; assert `provider.calls[1]["guidance_history"]` ==
    `["engineer message: try this\ncode:\n<code1>\noutcome: rejected by the engineer, not
    executed"]` (the exact rejected record reaches the next request); `run_step_code` called
    exactly once (only the approved turn executes); the healed step is cached
  - `test_steer_enter_and_quit_at_approval_abort_the_turn`: parametrized stdin
    `["msg", "", "quit"]` (Enter at approval) and `["msg", "quit", "quit"]` → both behave as the
    rejected turn — record appended, no execution
  - `test_steer_approval_eof_or_sigint_declines_the_dialog`: stdin guidance line then `input`
    raising `EOFError` at the approval prompt → returns None; no execution; `steering_declined`
    logged; the original failure propagates from the executor
  - `test_steer_red_turn_records_the_full_outcome`: FakeProvider returns code raising
    `AssertionError("Locator expected to be visible\nActual value: none\nCall log:\n  -
    waiting…")`; stdin `["msg", "y", "quit"]` → returns None; stdout shows the complete
    multi-line outcome; the history record's outcome part equals `str(outcome)` verbatim (all
    four lines); no re-execution (`run_step_code` called once)
  - `test_steer_high_finding_records_the_complete_violation`: compliance verdict `[HIGH_FINDING]`;
    stdin `["msg", "y", "quit"]` → no cache write; stdout names the instruction; the record
    outcome carries the full violation text
    (`violated instruction: <instruction> — <explanation>`)
  - `test_steer_dead_page_url_degrades`: `DeadPage` (url and snapshot raise) → the dialog
    survives — banner prints the url-unavailable notice, omits the `url:` line; requests record
    `page_url is None`; the dialog still completes a scripted green turn
  - `test_steer_provider_unavailable_ends_dialog` (exists — keep): FakeProvider raising
    `LLMUnavailableError`; stdin `["msg"]` → returns None; no approval prompt shown (the dialog
    ends before it)
  - update the existing turn tests to the new loop: `test_steer_green_turn_*`,
    `test_steer_gate_off_config_makes_zero_compliance_calls`,
    `test_steer_red_turn_appends_history_and_next_request_carries_it` (new record format),
    `test_steer_failed_execution_returns_to_the_prompt_without_re_execution` (full-outcome
    record), `test_steer_sigint_during_guided_execution_escapes_directly`,
    `test_steer_quit_eof_sigint_return_none`, `test_steer_local_commands_served_without_llm`,
    `test_steer_survives_dead_page_banner_and_commands`,
    `test_steer_blank_guidance_line_reprompts_without_llm`,
    `test_steer_no_candidate_failure_empty_code`, `test_steer_banner_renders_*` (drop
    fragment/verdict/intent assertions; assert render + URL), `test_steer_guided_request_*`
    (recorded dicts grow `page_url`)
- [ ] **Debugging**: `pytest tests/engine/steering/test_steering.py -x` — fix implementation
  until green
- [ ] **Contract re-verification**: no code executes without the engineer approval of this turn
  (the execution call is structurally unreachable without a `y`); a rejected or failed turn
  always enters the history before the guidance prompt reopens; no budget, no polling; the
  history/guidance never persist (the cache file never sees them; `page_url` and history take no
  part in step addressing); no new cross-cell imports — `format_step_error` is deliberately NOT
  imported into steering (the red-turn outcome stays `str(outcome)` verbatim); `run_step_code`
  and `check_step_compliance` signatures unchanged
- [ ] **Lint**: `ruff check prettyplay/engine/steering tests/engine/steering` — fix formatting;
  confirm `_snapshot_fragment`, `_SNAPSHOT_FRAGMENT_LINES`, `_first_line` are gone and no unused
  imports remain
- [ ] **STEP 8 — Completion**: mark the checkboxes complete; submit for review

### Task 7: `on_step_failed` docstring alignment (reporting)

Wording-level alignment in `prettyplay/reporting/hooks.py`: the CODEMANIFEST now names the render
template sections in the `on_step_failed` annotation; the code already complies behaviorally
(`StepExecutor.execute` emits `str(error)` verbatim into the payload; the reporter logs it — no
re-composition anywhere). This task only aligns the docstring.

**Usages relevant to this task:**
- `conventions`: Google-style docstrings.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If
implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] STEP 0 — Declaration: declare this task (Task 7, reporting cell) before starting
- [ ] Code: extend the `on_step_failed` docstring to name the section list, mirroring the
  contract sentence: the first line with the class name of the terminal failure and the authored
  reason, the `---` separated step/error section, the conditional received/cause/Call log
  details section and the unpadded verdict block — displayed verbatim by integrators
- [ ] Verify: `pytest tests/reporting -q` — unchanged, all green (wording only)
- [ ] Lint: `ruff check prettyplay/reporting` — fix formatting if necessary
- [ ] Completion: mark the checkboxes complete; submit for review

### Task 8: Integration verification — full-suite regression sweep and manual acceptance

Cross-cell verification after every cell is done: the whole render flows from the terminal
constructors through the executor into hooks/logs; every engine request carries `page_url=None`
while every steering request carries the URL; the approval gate holds end-to-end; the frozen
mirrors match the practices in both cells.

**Usages relevant to this task:**
- `conventions`: validation commands run in the project virtualenv.

**CRITICAL: `CODEMANIFEST` files and `.goga/usages/` practices — read-only contract definitions.
Do NOT modify them. If implementation does not match the contract, fix the implementation — never
fix the contract.**

- [ ] Full suite: `pytest tests/ -x` — every module green (failures, driver, llm, engine,
  steering, reporting, integration, scenario, executor, runtime)
- [ ] Facade check: `python -c "from prettyplay.failures import ErrorParts, decompose_error_text"`
  and `python -c "from prettyplay.driver import PageFacade; assert isinstance(PageFacade.url,
  property)"` — the new surface is importable
- [ ] Lint gate: `ruff check prettyplay tests` — clean (no dead code, no unused imports:
  `_VERDICT_LABEL_WIDTH`, `_snapshot_fragment`, `_SNAPSHOT_FRAGMENT_LINES`, `_first_line` gone)
- [ ] Cross-entity scenario: the render composed at construction equals `str(error)` in the
  `on_step_failed` payload and the log record (covered by `tests/failures`,
  `tests/reporting`, `tests/test_executor.py` — confirm no assertion was weakened to pass)
- [ ] Cross-entity scenario: engine vs steering request composition — engine paths record
  `page_url is None` (`tests/engine/*`), steering paths record the URL
  (`tests/engine/steering/test_steering.py`)
- [ ] Mirror discipline final check: all four constants equal the practice files byte-for-byte
  (the four mirror tests, all green)
- [ ] Manual acceptance (environment-gated — live browser + provider keys; outside pytest): run
  the example repro `example/tests/test_youtube.py` with interactive steering enabled; drive one
  rejected turn (`n`) then one approved green turn (`y`); observe the banner (render + URL),
  the approval prompt showing the complete code, and the healed write-back — the TODO repro in
  miniature
- [ ] Run validation: record the outcome of every command above; on any failure, fix the
  implementation (never the contract, never the test expectations' intent)

---

## Validation Commands

All commands run in the project virtualenv (recreate it first if the committed `.venv` is a
broken artifact of another machine: `python -m venv .venv && .venv/bin/pip install -e ".[test]"`).

- `pytest tests/failures/test_errors.py -q`: failures cell (Tasks 1–2)
- `pytest tests/driver/test_page.py -q`: driver cell (Task 3)
- `pytest tests/llm -q`: llm cell (Task 4)
- `pytest tests/engine tests/test_integration.py tests/test_scenario.py tests/test_executor.py -q`:
  engine cell + engine-driven regression surface (Task 5)
- `pytest tests/engine/steering/test_steering.py -q`: steering cell (Task 6)
- `pytest tests/reporting -q`: reporting cell (Task 7)
- `pytest tests/ -x`: Run all tests — the exit gate (Task 8)
- `ruff check prettyplay tests`: Lint check — the exit gate (Task 8)
- `python -c "from prettyplay.failures import ErrorParts, decompose_error_text"`: Facade
  accessibility — the new failures exports
- `python -c "from prettyplay.driver import PageFacade; assert isinstance(PageFacade.url, property)"`:
  Facade accessibility — the new driver property

---

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location` (`decompose_error_text`,
      `ErrorParts`, `render_terminal_message`, `FailureVerdict.render`, both terminal
      constructors in `prettyplay/failures/errors.py`; `PageFacade.url` in
      `prettyplay/driver/page.py`; the port/builder/providers in `prettyplay/llm/*`;
      `StepGenerator._request` + mirrors in `prettyplay/engine/generator.py`; the `steer` rewrite
      + mirrors in `prettyplay/engine/steering/steering.py`)
- [ ] Every contract entity is accessible from the facade (`ErrorParts`,
      `decompose_error_text` in `prettyplay.failures.__all__` — nine names)
- [ ] Properties and methods match the declared API (five-parameter `render_terminal_message`
      with `error_class` first; `page_url: str | None` after `snapshot` across the port, both
      providers and `build_fields_text`; `PageFacade.url -> str`)
- [ ] Descriptions are reflected in behavior (the decomposed details section; the strict `y`
      approval gate; full verbatim history records; the URL in every steering request and the
      banner; `page_url=None` on every engine request; the short class name on the render first
      line)
- [ ] Contract dependencies are met (no new cross-cell import edges; steering keeps importing
      `PageFacade`, `LLMProvider`, `run_step_code`, `check_step_compliance` over existing edges)
- [ ] Re-exports are accessible from the facade (the two new failures names)
- [ ] Every coding task followed the TDD workflow (contract tests → code → verification → logic
      tests → debugging → re-verification → lint)
- [ ] Contract tests and logic tests cover facade, API, and behavior within each coding task
      (32 design scenarios + the updated regression surface across ~10 test files)
- [ ] Integration tests exist where cross-entity scenarios require them (per-cell suites cover
      the cross-entity flows; Task 8 verifies the sweep end-to-end)
- [ ] No package boundary was expanded (no new cells, no new facade names beyond the failures
      exports, no CODEMANIFEST edits)
- [ ] `CODEMANIFEST` files and `.goga/usages/` practices were not modified (contract is
      read-only; the working-tree contract edits belong to the pipeline, not the implementer)
- [ ] All validation commands pass (`pytest tests/ -x`, `ruff check prettyplay tests`, both
      facade checks)
- [ ] Every Usages entry is mentioned in at least one task (`conventions`, `playwright`
      failures+driver, `system_prompt`, `cheat_sheet`, imported `configuration`, `classification`)
