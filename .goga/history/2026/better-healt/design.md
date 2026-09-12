# Design Document: `better-healt`

Bounded healing, settle polling and interactive steering of prettyplay — the implementation design
derived from the CODEMANIFEST contracts applied by the architecture stage (`arch.md`, `adr.md`).

---

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/failures/CODEMANIFEST`: the verdict label set grows to four (`fixable` added);
  `IncurableStepError` gains the `code: str` field (programmatic-only, never rendered).
- `prettyplay/reporting/CODEMANIFEST`: new hook `on_step_finished(step_text, step_type, outcome)`;
  hook events fire per step or per LLM attempt — never per execution retry; `fixable` in every
  category payload; `on_healed.explanation` widened to interactive healings.
- `prettyplay/config/CODEMANIFEST`: `Config` gains `polling_timeout: float | None`,
  `polling_delay: float`, `interactive: bool`; validation, env overrides
  (`PRETTYPLAY_POLLING_TIMEOUT`, `PRETTYPLAY_POLLING_DELAY`, `PRETTYPLAY_INTERACTIVE`) and the
  layered-merge rules for the three settings.
- `prettyplay/driver/CODEMANIFEST`: new Routine `is_pollable_failure(exc) -> bool` at `errors.py`
  — the fixed pollable map of the facade error surface.
- `prettyplay/llm/CODEMANIFEST`: `generate_step_code` gains `recommendation`, `guidance`,
  `guidance_history`; the regeneration block order is fixed (CODE, ERROR, RECOMMENDATION,
  USER GUIDANCE, HISTORY) identically in both providers; `FailureClassification` carries the
  four-label set with the unrecognized→incurable fallback.
- `prettyplay/engine/CODEMANIFEST`: `system_prompt` moves to the shared file
  `.goga/usages/prompts/generation.md`; bounded healing on failed checks and on exhaustion;
  the uniform decision table; `generate`/`regenerate`/`heal` gain `window: SettleWindow`
  (and `regenerate` gains `recommendation: str`); the raised `IncurableStepError` carries the
  failed step code.
- `prettyplay/CODEMANIFEST` (facade): imports `SettleWindow`/`settle` from `prettyplay/engine/polling`
  and `StepSteering` from `prettyplay/engine/steering`; `StepExecutor` gains `steering`;
  the `execute` algorithm gains the window (step 2), settle execution (step 3), the steering
  intercept (step 6) and `on_step_finished` (step 9); `PrettyPlay` composes `StepSteering`.

### New Entities

- `SettleWindow(timeout, delay)` — `prettyplay/engine/polling/window.py` — the settle horizon of one
  step execution.
- `settle(execute, code, page, window)` — `prettyplay/engine/polling/settle.py` — the re-execution
  loop absorbing transient page-state failures.
- `StepSteering(config, provider, cache, reporter)` — `prettyplay/engine/steering/steering.py` — the
  interactive steering REPL of a terminally stuck step.
- `is_pollable_failure(exc)` — `prettyplay/driver/errors.py` — the fixed pollable map.

### Changed Entities

- `IncurableStepError` — new `code: str` field + property; render unchanged (code excluded).
- `StepHooks` — new `on_step_finished` method (the contract grows to ten events).
- `Config` — three new validated fields.
- `load_config` — float/bool env parsing for the three settings; `None`-means-unset merge rule.
- `LLMProvider.generate_step_code` (port + both SDK implementations) — three new parameters.
- `_request.build_fields_text` / `CATEGORIES` — new blocks and the `fixable` label.
- `StepGenerator.generate` / `regenerate` / `_loop` — window threading, bounded healing, code field.
- `StepHealer.heal` — window param, `fixable` branch, code field on the rewrite.
- `StepExecutor.execute` / `_strict_failure` — window, settle, steering intercept, `on_step_finished`,
  code fields.
- `PrettyPlay.__init__` — composes `StepSteering`, threads it into the executor.
- `SYSTEM_PROMPT` (engine) — replaced with the content of `.goga/usages/prompts/generation.md`;
  `CLASSIFICATION_PROMPT` (engine) — gains the `fixable` line.

### Deleted Entities

- None. The inline `system_prompt` practice text of the engine manifest moved verbatim to
  `.goga/usages/prompts/generation.md` — no contract entity was deleted.

### Usages and Annotations Changes

- `.goga/usages/prompts/generation.md` (new, project level) — the single source of the generation
  system prompt; referenced by `engine` and `engine/steering` as `system_prompt`.
- `.goga/usages/cooks/playwright.md` — new "Error kinds — the driver error surface" section.
- Cell-level `.usages/` updated by the architecture stage and verified current here:
  `error_kinds.md` (driver, new), `settle.md` (polling, new), `steering.md` (steering, new),
  `taxonomy.md`, `hooks.md`, `configuration.md`, `budgets.md`, `generation.md`, `healing.md`,
  `classification.md`, `providers.md`, `lifecycle.md`, `steps.md`.

## Applied Fixes

### Fixed CODEMANIFEST Defects

- None. `goga lint` passes (10 cells, 0 errors); the four consistency dimensions (interface↔type,
  type↔mutation, interface↔interface, annotations↔entity) pass on every changed entity; every
  backtick reference resolves inside its document context; no import cycles exist
  (`engine → engine/polling`, `engine/steering → engine`, `facade → all`).

Two wording loosenesses were resolved interpretively (no edit possible without changing fixed
signatures — recorded here as binding readings, see also *Additional Instructions*):

1. `StepGenerator.regenerate` step 2 says "the verdict of the entry classification is carried" while
   `regenerate` receives no verdict and performs no classification. The only implementable reading
   (and the one `StepHealer.heal` step 6 states explicitly): `regenerate` raises with the verdict
   absent; the calling healer rewrites the error carrying its own entry verdict. No CODEMANIFEST
   change needed.
2. The `system_prompt` and page-API-surface texts are practice files, not runtime resources. The
   implementation materializes each as a frozen module constant mirroring the file verbatim — the
   established repo pattern (`PAGE_API_SURFACE` mirrors `driver/.usages/facade.md`). The steering
   cell holds its own copies (it imports neither constant from the engine contract). See
   *Additional Instructions* for the rationale.

## Entity Interaction and Data Flow

### Interaction Diagram

```
PrettyPlay (scenario.py)
  │  composes per test
  ├─ PrettyplayRuntime ── Config, RunBudgets, DriverSession, LLMProvider
  ├─ StepCache, StepReporter(+StepHooks)
  ├─ StepGenerator ────────────┐
  ├─ StepHealer ── delegates ──┤ regenerate(...)
  ├─ StepSteering ─────────────┘ provider.generate_step_code(guidance=…)
  └─ StepExecutor.execute(step_text, step_type, page)
       │ 1 window per step execution
       ├─ SettleWindow(timeout, delay)          [engine/polling/window.py]
       ├─ settle(run_step_code, code, page, window)   [engine/polling/settle.py]
       │     └─ is_pollable_failure(exc)             [driver/errors.py]
       ├─ cache hit  → settle → failure → StepHealer.heal(..., window)
       │                                │ classification (fixable included)
       │                                ├─ product_defect → ProductDefectError
       │                                ├─ incurable     → IncurableStepError(code)
       │                                └─ rot|fixable   → generator.regenerate(recommendation, window)
       ├─ cache miss → StepGenerator.generate(..., window)
       │     ├─ candidate → settle
       │     ├─ failed check → classify → decision table
       │     │     └─ rot|fixable → ONE try_healing-funded regeneration → final classification
       │     └─ exhaustion → classify → decision table → (extra regeneration | terminal)
       └─ IncurableStepError (non-strict, interactive) → StepSteering.steer(failure, identity, …)
             ├─ banner (snapshot fragment + screenshot path)
             ├─ local commands: snapshot | screenshot | error | code | quit
             ├─ guidance → provider.generate_step_code(guidance, guidance_history) → run_step_code
             ├─ green → cache write-back + on_healed → executor continues as success
             └─ quit/EOF/SIGINT/provider down → None → original failure propagates
```

### Data Flows

- **Window flow**: `Config.polling_timeout/polling_delay` → `SettleWindow` created in
  `StepExecutor.execute` step 2 → threaded into `settle` (cached hit), `generate`, `heal`,
  `regenerate`. One window per step execution; `settle` starts it at the first execution.
- **Failure flow**: step-code exception → `settle` (pollable + remaining → re-execute) →
  non-pollable/expired → `format_step_error` → classification (`FailureClassification`, 4 labels) →
  `FailureVerdict` → terminal error (`ProductDefectError` | `IncurableStepError(reason, error, code,
  verdict)`) → one render → `on_step_failed` + `on_step_verdict` + raise → `on_step_finished`.
- **Steering flow**: `IncurableStepError` caught by the executor gate → `steer` → banner →
  guidance line → regeneration request (`existing_code=failure.code`, `error=failure.error`,
  `guidance=message`, `guidance_history=turns`, `recommendation=None`) → `run_step_code` (no settle)
  → green: `CachedStep` + `cache.save` + `on_healed` → executor success path; red: history append →
  prompt; exit: `None` → original failure.
- **Budget flow**: unchanged `RunBudgets`; new spenders — the bounded regenerations of the generate
  loop call `try_healing` directly (exactly one each); settle re-executions and steering turns
  spend nothing.
- **Hook flow**: `on_step_started` → (`on_generation_started` per LLM attempt | `on_healing_started`
  → `on_healed` | neither on a pure cache hit) → `on_step_passed` | (`on_step_failed` →
  `on_step_verdict`?) → `on_step_finished` — always last, exactly once.

### Entity Dependencies

Initialization order (leaves first, matches the contract import map):

1. `failures`, `reporting` (no deps) — unchanged.
2. `config` → failures; `driver` → config; `llm` → config, failures — unchanged.
3. `cache` → config, reporting — unchanged.
4. **`engine/polling` → driver** (`PageFacade`, `is_pollable_failure`) — new.
5. `engine` → cache, config, driver, failures, llm, reporting, **engine/polling**.
6. **`engine/steering` → cache, config, driver, engine, failures, llm, reporting** — new.
7. `prettyplay` facade → all of the above.

Python package layout mirrors this: `prettyplay/engine/polling/` and `prettyplay/engine/steering/`
are subpackages of `prettyplay.engine`; their modules import with relative paths
(`from ...driver import PageFacade`, `from ..execution import run_step_code`) — no import cycle:
`engine` imports `engine.polling` only; `engine.steering` imports `engine`; nothing imports
`engine.steering` except the facade (`scenario.py`, `executor.py`).

## Code Stack Trace

### Trace: `StepExecutor.execute` (the changed owner of the step cycle)

#### Chain
1. **Input**: `PrettyPlay.step/expect` calls `execute(step_text, step_type, page)`; the facade has
   already folded nothing — folding happens at the `PrettyPlay` boundary after the raise.
2. `reporter.emit("on_step_started", …)` → hooks + INFO log → checkpoint: payload matches the
   `StepHooks.on_step_started` contract — passed.
3. `identity = StepIdentity(cache_key, step_type, normalize_step_text(step_text))`;
   `window = SettleWindow(config.polling_timeout, config.polling_delay)` → checkpoint:
   `SettleWindow(timeout: float | None, delay: float)` constructor matches the polling contract and
   the `Config` property types (`float | None`, `float`) — passed.
4. `cached = cache.load(identity)`:
   - **strict + miss** → `raise IncurableStepError(step_text, _STRICT_MISS_REASON, "", code="", verdict=None)`
     → checkpoint: contract step 3 "the error field empty, the verdict absent" and the failures
     contract "the strict cache miss carries none" for code — passed.
   - **hit** → `settle(run_step_code, cached.code, page, window)` → checkpoint: `settle` signature
     `(execute: Callable[[str, PageFacade], None], code: str, page: PageFacade, window: SettleWindow)`
     — `run_step_code(code, page)` matches the callable type; strict replay included per the
     requirement "the settle window still applies to the cached code" — passed.
   - **hit execution failure** → `error_text = format_step_error(error)`:
     - strict → `_strict_failure(...)` (classification-only; see its own trace)
     - else → `healer.heal(cached, error_text, self._scenario, page, window)` → checkpoint: heal
       signature `(step, error, previous_steps, page, window)` — passed.
   - **miss (non-strict)** → `generator.generate(identity, step_text, self._scenario, page, window)`
     → checkpoint: generate signature — passed.
5. **Steering intercept** wraps the two engine calls (4 hit-failure heal path, 4 miss generate
   path): `except IncurableStepError as failure:` → gate `config.interactive and not config.strict`
   → `healed = steering.steer(failure, identity, self._scenario, page)` → checkpoint: steer
   signature `(failure, identity, previous_steps, page)`; `ProductDefectError` and
   `LLMUnavailableError` are not `IncurableStepError` so the except clause never intercepts them —
   the "never on product_defect / never when the LLM is unavailable / never in replay-strict" gate
   holds structurally — passed. `healed is None` → `raise failure` (original, unchanged);
   healed → fall through to success.
6. `self._scenario.append(step_text)`; `reporter.emit("on_step_passed", …)` → checkpoint: fires on
   engine success and on steering-healed success ("a healed return continues as success") — passed.
7. **except path**: `on_step_failed` with `str(error)` (the render, never re-composed); when the
   error is `ProductDefectError`/`IncurableStepError` with a verdict → `on_step_verdict` with the
   three verdict fields from the verdict object → `raise` → checkpoint: payload and order match the
   hooks contract — passed.
8. **finally**: `reporter.emit("on_step_finished", {"step_text", "step_type", "outcome"})` where
   `outcome` is `"passed"` iff step 6 ran → fires exactly once, after every other event, on pass,
   on failure and on the strict miss → checkpoint: contract step 9 and "on_step_finished fires
   exactly once per step" — passed.
9. **Output**: `None` on success; `ProductDefectError` / `IncurableStepError` / `LLMUnavailableError`
   by kind on failure — the facade folds the traceback and re-raises.

#### Checkpoint Summary
- Window construction and threading: passed (types align at every call site).
- Steering gate: passed (structural exclusion of product_defect / LLM-unavailable / strict).
- `on_step_finished` ordering and exactly-once: passed (emitted in `finally`, after the verdict
  event; the outcome flag is set only on the success path).

### Trace: `settle` (new, `engine/polling/settle.py`)

#### Chain
1. **Input**: caller passes `execute=run_step_code` (engine loop or executor), the code text, the
   page facade, and the window created for this step execution.
2. `window.start()` → the first execution marks the window start; idempotent so later attempts
   never shift it → checkpoint: `SettleWindow.start` requirement — passed.
3. `execute(code, page)` → success → **return** (step code worked) → checkpoint: no hook events on
   any path — polling imports no reporting type (schema: polling → driver only); visibility is the
   log alone — passed.
4. On `Exception`: evaluate `window.enabled and is_pollable_failure(exc) and window.has_remaining()`:
   - True → `logger.info("settle_retry", extra={"attempt": n, "error": str(exc)})` where `n` is the
     1-based ordinal of the failed execution → `time.sleep(window.delay)` → repeat from 3.
   - False → `raise` (the original exception object, as-is) → checkpoint: "Never swallow, translate
     or retry a non-pollable failure" — the identical exception object propagates; `BaseException`
     (KeyboardInterrupt, SIGINT) is never caught — passed.
5. **Output**: `None` on success; the last exception unchanged on give-up. No LLM calls, no budget
   consumption (no budgets object exists in this cell).

#### Checkpoint Summary
- Window never kills a running attempt: `has_remaining` is checked only before a repetition —
  passed.
- Disabled window (`timeout` None or 0): `enabled` False → single execution, the failure propagates
  immediately — passed.

### Trace: `SettleWindow` (new, `engine/polling/window.py`)

#### Chain
1. **Input**: `SettleWindow(timeout=config.polling_timeout, delay=config.polling_delay)` —
   `(float | None, float)`.
2. `start()`: `if self._started_at is None: self._started_at = time.monotonic()` → idempotent;
   monotonic clock immune to wall-clock jumps → checkpoint: contract "Idempotent: only the first
   call wins" — passed.
3. `has_remaining()`: `enabled and started and (monotonic() - started) < timeout` → False when
   disabled/not started/expired → checkpoint: contract semantics incl. "the first execution may
   consume the whole window" (strict `<`, expiry checked before each repetition only) — passed.
4. `enabled`: `timeout is not None and timeout > 0` → 0 is an explicit disable, uniform with None —
   passed.
5. **Output**: pure time bookkeeping; no I/O, no logging, thread-agnostic (created and used on the
   test thread only).

### Trace: `is_pollable_failure` (new, `driver/errors.py`)

#### Chain
1. **Input**: the exception object raised by failed step code — it crossed the driver-thread
   boundary as the original object (`PlaywrightWorker.run` re-raises `task.error` verbatim), so
   playwright `Error` instances and facade `AssertionError`s arrive with their types intact →
   checkpoint: thread marshaling preserves exception identity/type — verified in
   `driver/session.py` — passed.
2. `text = str(exc)`; ambiguity first: `"strict mode violation" in text` → **False** (deterministic
   locator ambiguity — waiting will not collapse N elements to one; checked before the
   AssertionError rule so an ambiguity-styled AssertionError is also refused) → checkpoint:
   contract algorithm step 3 — passed.
3. `isinstance(exc, AssertionError)` → **True** (a failed expectation: the check executed and did
   not hold; the state may catch up) → checkpoint: contract step 1 — passed.
4. `isinstance(exc, PlaywrightError)` and the message matches the fixed pollable pattern set
   (case-insensitive substrings / one regex, lowercased; verified against the installed Playwright
   driver bundle — every pattern matches a real message):
   - timeout — `re.search(r"timeout \d+m?s exceeded", lower)`
   - element state — `element is not visible`, `element is not enabled`,
     `element is outside of the viewport`, `element is not attached`, `frame has been detached`,
     `detached from document`
   - navigation / context — `execution context was destroyed`, `target closed`,
     `interrupted by another navigation`, `navigation interrupted the evaluation`
   → **True** → checkpoint: contract step 2 and the `playwright` usage "Error kinds" section —
   the map covers the documented kind table incl. the navigation-interrupted and detached-frame
   messages (the earlier draft's `element has been detached` matched no real Playwright message
   and is dropped) — passed.
5. Anything else (Python-level `SyntaxError`/`NameError`/`TypeError`, unknown playwright kinds,
   arbitrary exceptions) → **False** — the conservative default goes to classification →
   checkpoint: contract steps 4–5 — passed.
6. **Output**: `bool`, pure and deterministic on the exception alone; no state, no I/O, no
   settings, no LLM.

### Trace: `StepGenerator.generate` (changed)

#### Chain
1. **Input**: `(identity, step_text, previous_steps, page, window)` from the executor miss path.
2. Loop: `budgets.try_generation(identity)` refused → exhaustion path (step 8 of the contract,
   below). Granted → attempt counter += 1 → `reporter.emit("on_generation_started", {step_text,
   attempt})` — once per LLM request regardless of the settle re-executions inside it →
   checkpoint: reporting contract "per LLM attempt" — passed.
3. Collect inputs: `page.aria_snapshot()`, screenshot iff `config.send_screenshots`;
   `provider.generate_step_code(prompt=SYSTEM_PROMPT, user_instructions=config.generation_prompt,
   step_text, previous_steps, snapshot, screenshot, page_api=PAGE_API_SURFACE, existing_code,
   error, recommendation=None, guidance=None, guidance_history=[])` → checkpoint: port signature
   carries the three new params; engine paths pass `None`/`None`/`[]` (no RECOMMENDATION/GUIDANCE/
   HISTORY blocks on plain generation) — passed.
4. `settle(run_step_code, code, page, window)` → success → `CachedStep(identity, code, created_at)`
   → `cache.save` → **return** → checkpoint: candidate executions run under the window — passed.
5. `AssertionError` that survived the window (a failed check) → classify (`_classify` with the
   quiet LLM-unavailable skip) → decision table:
   - `product_defect` → `raise ProductDefectError(step_text, verdict.explanation, error_field,
     verdict)` from None.
   - `incurable` → `raise IncurableStepError(step_text, reason="candidate check failed — <first
     line>", error_field, code=candidate_code, verdict)`.
   - `rot`/`fixable` → **bounded healing**: `try_healing(identity)`:
     - refused → `raise IncurableStepError(step_text, "healing attempt budget exhausted",
       error_field, code=candidate_code, verdict)`.
     - granted → ONE regeneration request (counter += 1, `on_generation_started` fires — it is an
       LLM attempt) carrying `existing_code=candidate_code`, `error=error_field`,
       `recommendation=verdict.recommendation` → settle-execute:
       - success → store → **return** the healed step.
       - failure (any kind) → ONE final classification deciding only the terminal kind:
         `product_defect` → `ProductDefectError` (final verdict); anything else →
         `IncurableStepError` (final verdict, code = the failed regenerated candidate; the reason
         authored by the failure kind — an AssertionError repeat keeps "candidate check failed —
         <first line>", any other failure uses "candidate failed — <first line>"); LLM
         unavailable at this classification → WARNING → `IncurableStepError` without a verdict
         (conservative default, uniform with the unrecognized-label fallback; the reason keeps the
         contract wording "candidate check failed — <first line>"). The provider
         request of the funded regeneration stands outside the failure capture: an
         `LLMUnavailableError` of the request itself propagates immediately — no retry, no final
         classification (uniform with the loop requirement); "failure" means the execution failure
         of the funded candidate under `settle`, its text formatted by `format_step_error`.
   → checkpoint: "exactly one regeneration funded from the healing budget … no further
   regeneration" — the funded attempt is a single inline request, not the `regenerate` loop (which
   retries; see interpretive note 3) — passed.
6. Any other candidate failure → `existing_code, error = code, format_step_error(exc)` → repeat
   from 2 with the fresh error and the fresh snapshot → checkpoint: contract step 7 — passed.
7. **Exhaustion path** (step 2 refused, generation pool): last-candidate classification:
   `product_defect` → `ProductDefectError`; `incurable` → `IncurableStepError(reason="generation
   attempt budget exhausted")`; `rot`/`fixable` → one extra `try_healing`-funded
   recommendation-carrying regeneration — refused funding → terminal with the verdict; repeat
   failure → terminal `IncurableStepError` carrying the exhaustion verdict, **no reclassification**;
   LLM unavailable → WARNING → `IncurableStepError` without a verdict. `code` = the last candidate.
8. **Output**: `CachedStep` (stored) | terminal error carrying verdict/error/code.

#### Checkpoint Summary
- Anti-masking preserved: `product_defect` never regenerates — passed.
- Budget invariant: a legitimately failing assertion costs at most one failed-check classification
  + one healing-funded regeneration + one final classification — passed.
- The `code` field on every generation-path `IncurableStepError` = the last candidate code — passed.

### Trace: `StepGenerator.regenerate` (changed)

#### Chain
1. **Input**: `(identity, step_text, previous_steps, page, existing_code, error, recommendation,
   window)` — called only by `StepHealer.heal` (rot/fixable branch).
2. The same loop as `generate` with the contract's four differences: every request carries
   `existing_code`, `error` and `recommendation` (+ user instructions when non-empty); attempts
   spend `try_healing`; executions run under `settle` with `window`; **every** failed attempt — a
   failed check included — retries with the fresh error and snapshot while attempts remain (no
   per-attempt classification inside the loop; the entry classification already guards
   anti-masking) → checkpoint: behavior change vs the old loop (which stopped at AssertionError) is
   exactly the contract text — passed.
3. Budget exhaustion → `raise IncurableStepError(step_text, "healing attempt budget exhausted",
   error, code=last candidate, verdict=None)` — no classification; the calling healer attaches the
   entry verdict (see interpretive note 1) → checkpoint: heal step 6 "no extra LLM request is made"
   — passed.
4. **Output**: stored `CachedStep` | `IncurableStepError(verdict=None)` | `LLMUnavailableError`
   (provider request failure — no retry).

### Trace: `StepHealer.heal` (changed)

#### Chain
1. **Input**: `(step: CachedStep, error, previous_steps, page, window)` from the executor
   hit-failure path (non-strict).
2. `classification = classify_step_failure(config, provider, step.identity.normalized_text,
   step.code, error, page)` — `LLMUnavailableError` propagates (explicit infrastructure failure).
3. `verdict = FailureVerdict(category, explanation, recommendation)`; emit `on_healing_started`
   with the category (four labels now).
4. Decision table:
   - `product_defect` → `raise ProductDefectError(step_text, explanation, error, verdict)`.
   - `incurable` → `raise IncurableStepError(step_text, explanation, error, code=step.code,
     verdict)`.
   - `rot`/`fixable` → `healed = generator.regenerate(identity, step_text, previous_steps, page,
     existing_code=step.code, error, recommendation=classification.recommendation, window)`:
     - `IncurableStepError` (exhaustion, verdict None) → rewrite:
       `raise IncurableStepError(step_text, inner.reason, inner.error, code=step.code, verdict)`
       from inner — the entry verdict + the cached step code.
     - success → emit `on_healed(step_text, explanation)` → **return** the healed step.
5. **Output**: healed `CachedStep` (already stored) | terminal error.

### Trace: `StepSteering.steer` (new, `engine/steering/steering.py`)

#### Chain
1. **Input**: the executor gate calls `steer(failure: IncurableStepError, identity, previous_steps,
   page)` right before the failure would propagate. `failure` carries `step_text`, `reason`,
   `error`, `code`, optional `verdict` → checkpoint: every field read by the banner exists on the
   failures contract — passed.
2. Banner: the step sentence, the failed code (`failure.code`), the underlying error
   (`failure.error`), the verdict (`explanation` + `recommendation` when present), the first 20
   lines of a fresh `page.aria_snapshot()`, and the path of a full PNG written to a temporary file
   (`tempfile` directory, name `prettyplay-steering-*.png`) → print to stdout; log
   `steering_opened` (INFO, step_text) → checkpoint: contract step 1 "a fragment of the fresh
   accessibility snapshot, a screenshot path" — fragment size fixed at 20 lines (ADR unresolved
   item 3) — passed. Every page interaction of the dialog (the banner snapshot and screenshot,
   the `snapshot`/`screenshot` commands, the request-time snapshot) is individually guarded: a
   failed interaction prints its own failure text (e.g. `snapshot unavailable: <error>`) in place
   of the output and the dialog continues — no `Exception` ever escapes `steer`; the only exits
   are a healed step or None (`BaseException` — the honest interrupt — still escapes).
3. Prompt loop: `input("guidance> ")` wrapped for `EOFError` and `KeyboardInterrupt` → both, and
   the literal command `quit`, → log `steering_declined` → **return None** → checkpoint: "quit, EOF
   and SIGINT end the dialog and the original terminal failure propagates"; SIGINT during
   `input()` arrives as KeyboardInterrupt and is never swallowed into a heal — passed. A blank or
   whitespace-only line is a re-prompt: no `steering_guidance` record, no LLM request, no history
   entry — back to reading the guidance line.
4. Local commands (no LLM): `snapshot` → print the full accessibility snapshot; `screenshot` →
   write a full PNG to a temporary file and print the path; `error` → print `failure.error`;
   `code` → print `failure.code`; then back to 3 → checkpoint: contract step 3 — passed.
5. A guidance message → log `steering_guidance` (INFO, message — one-shot, never persisted) →
   build one request: `provider.generate_step_code(prompt=SYSTEM_PROMPT, user_instructions=
   config.generation_prompt, step_text=failure.step_text, previous_steps, snapshot=fresh
   aria_snapshot, screenshot when config.send_screenshots, page_api=PAGE_API_SURFACE,
   existing_code=failure.code, error=failure.error, recommendation=None, guidance=message,
   guidance_history=history)` → checkpoint: port signature; `recommendation=None` — the steering
   contract enumerates the request contents and names guidance + history, not the recommendation
   (the verdict diagnosis is banner-only; the live guidance replaces it) — passed.
   `LLMUnavailableError` → the dialog ends → **return None** (contract step 8).
6. `run_step_code(code, page)` — a bare execution, no `settle`, no window → checkpoint: "the
   settle window never re-arms inside the dialog" — passed.
7. Success → `CachedStep(identity, code, created_at)` → `cache.save` → emit `on_healed` with an
   explanation naming the interactive healing (e.g. "healed interactively by engineer guidance") →
   **return** the healed step → checkpoint: write-back only after a successful execution; the
   guidance text never enters the cache file (the payload carries only step_text + explanation) —
   passed.
8. Failure → print the outcome; `history.append(f"{message} => {first line of str(outcome)}")` →
   back to 3 → checkpoint: every turn has a measurable green/red outcome; HISTORY block grows —
   passed.
9. **Output**: healed `CachedStep | None`. No `RunBudgets` object exists in this class — budgets
   are structurally unspendable here.

### Trace: `load_config` — the three new settings (changed)

#### Chain
1. **Input**: pyproject `[tool.prettyplay]` + environment + optional programmatic `PrettyConfig`.
2. File layer: `polling_timeout = 6.0` / `polling_delay = 0.25` / `interactive = true` ride the
   ordinary section merge → `Config(**merged)` validates.
3. Env layer: `_ENV_NAMES` grows `polling_timeout`, `polling_delay`, `interactive`;
   `_parse_env_scalar` gains `_FLOAT_ENV_SETTINGS = {"polling_timeout", "polling_delay"}` —
   `float(raw)` with the loud `ConfigurationError(f"{setting}: received {raw!r} — allowed: a
   decimal float")` on `ValueError`; `interactive` joins `_BOOL_ENV_SETTINGS` (true/false/1/0,
   case-insensitive) → checkpoint: contract loader step 6 + "floats parse as decimal floats" —
   passed. `"0"` → `0.0` — the explicit disable.
4. Validation (`Config` field validators): `polling_timeout` None or a finite `>= 0`
   (`math.isfinite`) — a negative or non-finite value (env `inf`/`1e400` parses to `float("inf")`)
   fails loudly with the received value; `polling_delay >= 0` (0 allowed, finite);
   `_ALLOWED_TEXT` grows `polling_timeout: "None or a non-negative number (finite)"`,
   `polling_delay: "a non-negative number"`, `interactive: "a boolean"` → checkpoint: the render
   names setting, value, allowed form — passed.
5. Programmatic merge (`_apply_overrides`): the participant rule gains one clause — `value is None`
   → skip. `PrettyConfig(polling_timeout=0.0)` is in `model_fields_set`, is not None → participates
   → overrides the file layer (explicit disable wins). `PrettyConfig(polling_timeout=None)` →
   skipped → indistinguishable from unset. `PrettyConfig(interactive=False)` → participates (bools
   have no "empty" form) → overrides a file `interactive = true` → checkpoint: contract
   "an explicit False or 0.0 overrides the file layer too" + the None constraint — passed.
6. **Output**: validated `Config` with the three fields resolved.

### Trace: `LLMProvider.generate_step_code` + `_request.build_fields_text` (changed)

#### Chain
1. **Input**: the engine/steering request with `recommendation: str | None`, `guidance: str | None`,
   `guidance_history: list[str]`.
2. `build_fields_text(...)` renders the sections in the fixed order: STEP, PREVIOUS STEPS, PAGE
   SNAPSHOT, PAGE API, USER INSTRUCTIONS (non-empty), CODE (`existing_code is not None`), ERROR
   (`error is not None`), RECOMMENDATION (non-empty), USER GUIDANCE (non-empty), HISTORY
   (non-empty — entries joined with newlines) → checkpoint: contract "block order … CODE, ERROR,
   RECOMMENDATION, USER GUIDANCE, HISTORY — a non-empty input renders its named block, identically
   in both implementations" — one shared builder guarantees the parity — passed.
3. Both providers (`OpenAIProvider`, `AnthropicProvider`) forward the three new params verbatim to
   the shared builder; nothing provider-specific sees them → checkpoint: parity requirement —
   passed. The new inputs take no part in step addressing (they never reach the cache key) —
   structurally true: addressing happens in `StepIdentity`/`StepCache` from the step triple only.
4. Classification side: `CATEGORIES` grows `fixable`; `parse_classification_line` accepts it;
   an unrecognized label still returns None → `unparsable_classification()` → category `incurable`
   → checkpoint: "an unrecognized label … parses to incurable — an unknown verdict never grants a
   regeneration" — passed.
5. **Output**: request text; `code: str` of the fixed form (fence unwrapping unchanged).

### Trace: `IncurableStepError` construction (changed)

#### Chain
1. **Input**: raisers pass `(step_text, reason, error, code, verdict)`; `code: str = ""` default
   (conventions: empty default; None is reserved for explicit absence and code's absence is the
   empty string).
2. Fields stored: `code` joins the public attributes; every existing raiser updated (executor
   strict paths, generator loop + bounded healing, healer rewrite, executor strict miss with
   `code=""`).
3. `render_terminal_message(reason, step_text, error, render_verdict)` — unchanged signature: `code`
   never enters the render → checkpoint: "never rendered, never carried by hook or log payloads" —
   `on_step_failed` payload is `str(error)` (the render) and the log record is the same render;
   `code` reaches neither — passed.
4. **Output**: the exception; `info.value.code` for programmatic consumers (taxonomy.md example
   already documents it).

### Trace: hook event sequence incl. `on_step_finished`

#### Chain
1. **Input**: any step execution (pass, engine failure, strict failure, steering-healed).
2. Sequence on pass: `on_step_started` → [`on_generation_started`×N attempts] or
   [`on_healing_started` → `on_healed`] or nothing (pure cache hit, settle included) →
   `on_step_passed` → `on_step_finished(outcome="passed")`.
3. Sequence on failure: `on_step_started` → … → `on_step_failed` → `on_step_verdict` (iff verdict) →
   `on_step_finished(outcome="failed")` → raise. The steering-healed case is a pass: the intercept
   heals before any failure event fires.
4. Settle re-executions emit **no** hook events anywhere in every sequence — their visibility is
   the `settle_retry` log record alone → checkpoint: reporting contract "never per execution
   retry" — passed.
5. **Output**: `StepHooks` subclasses observe exactly one `on_step_finished` per step, last.

## Algorithm Design

### `SettleWindow`

**Responsibility**: the settle horizon of one step execution — when re-executing the same step code
may still help and how long to pause between re-executions.

**Algorithm:**
```
1. CONSTRUCT(timeout: float | None, delay: float):
   - keep timeout, delay as public attributes
   - _started_at = None                        # not started
2. enabled -> bool:
   - RETURN timeout is not None and timeout > 0
3. start():
   - IF _started_at is None: _started_at = time.monotonic()   # idempotent
4. has_remaining() -> bool:
   - IF not enabled or _started_at is None: RETURN False
   - RETURN (time.monotonic() - _started_at) < timeout
```

**Errors:** none — pure bookkeeping.

**Edge Cases:**
- `timeout=0` → `enabled` False → equivalent to None (explicit disable).
- First execution longer than the window → `has_remaining` False at the first failure → no repetition.
- `delay=0` → `time.sleep(0)` — repetition without a pause.

### `settle`

**Responsibility**: execute step code under the settle window; absorb transient page-state failures
by re-executing the same code; propagate everything else as-is.

**Algorithm:**
```
1. window.start()
2. LOOP:
   - TRY execute(code, page) → RETURN                    # the step code worked
   - EXCEPT Exception as failure:
     - attempt += 1                                       # 1-based ordinal of the failed execution
     - IF window.enabled AND is_pollable_failure(failure) AND window.has_remaining():
       - logger.info("settle_retry", extra={"attempt": attempt, "error": str(failure)})
       - time.sleep(window.delay)
       - CONTINUE LOOP                                    # repeat from 2
     - RAISE failure                                      # as-is, no translation
```

**Errors:** the original exception object propagates unchanged; `BaseException` (KeyboardInterrupt)
is never caught.

**Edge Cases:**
- Disabled window → exactly one execution.
- Pollable failure at window end → propagates (the caller's classification path decides it).
- `delay=0` → tight but bounded by the timeout.

### `is_pollable_failure`

**Responsibility**: the fixed pollable map — recognition only, no LLM, no settings.

**Algorithm:**
```
1. text = str(exc)
2. IF "strict mode violation" in text: RETURN False        # locator ambiguity — deterministic
3. IF isinstance(exc, AssertionError): RETURN True         # failed expectation — pollable
4. IF isinstance(exc, PlaywrightError) AND matches_pollable(text): RETURN True
   matches_pollable (lowercased text, fixed set — every pattern matches a real message
   of the installed Playwright driver):
   - re.search(r"timeout \d+m?s exceeded", lower)
   - "element is not visible" | "element is not enabled" | "element is outside of the viewport"
     | "element is not attached" | "frame has been detached" | "detached from document"
   - "execution context was destroyed" | "target closed" | "interrupted by another navigation"
     | "navigation interrupted the evaluation"
5. RETURN False                                            # Python-level, unknown — conservative
```

**Errors:** none — pure function.

**Edge Cases:**
- An `AssertionError` whose text names a strict-mode violation → step 2 wins → False.
- A non-playwright exception carrying a timeout-looking message → step 4 requires the playwright
  type → False (type + pattern, never pattern alone).

### `StepSteering`

**Responsibility**: the opt-in human-in-the-loop escape hatch of a terminally stuck step.

**Algorithm:**
```
CONSTRUCT: keep config, provider, cache; reporter is None — substitute the hook-less default
           reporter (StepReporter([])), so an omitted reporter never breaks the healed-step report.

1. steer(failure, identity, previous_steps, page):
   - history = []
   - render banner: step sentence, failure.code, failure.error,
     verdict explanation+recommendation (when present), first 20 lines of page.aria_snapshot(),
     path of a full PNG written to a temporary file
   - every page interaction of the dialog (the banner snapshot/screenshot, the snapshot/screenshot
     commands, the request-time snapshot) is individually guarded: a failed interaction prints
     its own failure text (e.g. `snapshot unavailable: <error>`) and the dialog continues
   - log steering_opened (INFO, step_text)
2. LOOP:
   - TRY message = input("guidance> ")
     EXCEPT (EOFError, KeyboardInterrupt): log steering_declined; RETURN None
   - IF message.strip() == "quit": log steering_declined; RETURN None
   - IF not message.strip(): CONTINUE      # blank line — re-prompt, no LLM request, no history
   - local commands (no LLM): snapshot | screenshot | error | code → serve, CONTINUE
   - log steering_guidance (INFO, message)
   - TRY code = provider.generate_step_code(
        prompt=SYSTEM_PROMPT, user_instructions=config.generation_prompt,
        step_text=failure.step_text, previous_steps, snapshot=page.aria_snapshot(),
        screenshot (iff config.send_screenshots), page_api=PAGE_API_SURFACE,
        existing_code=failure.code, error=failure.error,
        recommendation=None, guidance=message, guidance_history=history)
     EXCEPT LLMUnavailableError: print outcome; RETURN None
   - TRY run_step_code(code, page)                         # bare — no settle, no window
     EXCEPT Exception as outcome:
       - print the outcome
       - history.append(f"{message} => {first line of str(outcome)}")
       - CONTINUE
   - step = CachedStep(identity, code, date.today().isoformat())
   - cache.save(step)
   - reporter.emit("on_healed", {"step_text": failure.step_text,
       "explanation": "healed interactively by engineer guidance"})
   - RETURN step
```

**Errors:** every exit path heals or returns None; the original terminal failure always propagates
from the caller (`healed is None` → `raise failure`).

**Edge Cases:**
- `failure.code == ""` (no-candidate exhaustion) → the banner and `code` command show an empty
  code block; requests carry `existing_code=""`.
- `failure.verdict is None` → no verdict block in the banner.
- A dead page (e.g. the window expired on `Target closed`) → the banner and command interactions
  degrade to their own failure text; no `Exception` escapes `steer`: every exit path heals or
  returns None (the steering contract requirement).
- A blank or whitespace-only guidance line → a re-prompt: no LLM request, no history entry, no
  `steering_guidance` record.
- SIGINT arrives during `input()` or the provider request → KeyboardInterrupt on the request path
  is a plain exception (not LLMUnavailableError) → shown as a red outcome turn? No — SIGINT policy:
  KeyboardInterrupt must never be swallowed into a loop; `run_step_code`/provider failures are
  `Exception`, while KeyboardInterrupt is BaseException and escapes `steer` directly — the executor
  `finally` still fires `on_step_finished`, the original terminal failure is replaced by the
  KeyboardInterrupt (an honest interrupt, "nothing hangs").

### `StepExecutor.execute` (changed)

**Responsibility**: the owner of the step cycle — now with the settle window, the steering gate and
the closing event.

**Algorithm:**
```
1. outcome = "failed"
2. TRY:
   a. emit on_step_started(step_text, step_type)
   b. identity = StepIdentity(cache_key, step_type, normalize_step_text(step_text))
      window = SettleWindow(config.polling_timeout, config.polling_delay)
   c. cached = cache.load(identity)
   d. IF cached is not None:
      - TRY settle(run_step_code, cached.code, page, window)
        EXCEPT Exception as error:
          - error_text = format_step_error(error)
          - IF config.strict: _strict_failure(step_text, step_type, cached, error_text, page)  # raises
          - ELSE: TRY healer.heal(cached, error_text, _scenario, page, window)
                  EXCEPT IncurableStepError as failure: _steer_or_raise(failure, identity, page)
   e. ELIF config.strict:
      - raise IncurableStepError(step_text, _STRICT_MISS_REASON, "", code="", verdict=None)
   f. ELSE:
      - TRY generator.generate(identity, step_text, _scenario, page, window)
        EXCEPT IncurableStepError as failure: _steer_or_raise(failure, identity, page)
   g. _scenario.append(step_text)
   h. emit on_step_passed(step_text, step_type); outcome = "passed"
   EXCEPT Exception as error:
   i. emit on_step_failed(step_text, step_type, str(error))
   j. IF isinstance(error, (ProductDefectError, IncurableStepError)) and error.verdict:
      - emit on_step_verdict(step_text, verdict.category, verdict.explanation, verdict.recommendation)
   k. RAISE
   FINALLY:
   l. emit on_step_finished(step_text, step_type, outcome)

_steer_or_raise(failure, identity, page):
   - IF not (config.interactive and not config.strict): RAISE failure
   - healed = steering.steer(failure, identity, _scenario, page)
   - IF healed is None: RAISE failure
   - RETURN healed                                     # continues as success

_strict_failure(step_text, step_type, step, error_text, page):     # unchanged shape, code added
   - classification = classify_step_failure(...)        # LLMUnavailableError → WARNING + raise by step type
   - product_defect → ProductDefectError(step_text, explanation, error_text, verdict)
   - else (rot, fixable, incurable) → IncurableStepError(step_text, explanation, error_text,
     code=step.code, verdict)
```

**Errors:** by kind — `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError`; the
steering gate catches exactly `IncurableStepError` on non-strict interactive runs.

**Edge Cases:**
- A steering-healed step appends to the scenario, fires `on_step_passed` and
  `on_step_finished("passed")` — the cache write-back already happened inside the dialog.
- Strict + interactive config: the gate's `not config.strict` clause keeps the dialog shut.
- `on_step_started` itself raising (log misconfiguration): the `finally` still closes the step with
  `outcome="failed"` — exactly once regardless of outcome.

### `StepGenerator` (changed)

**Responsibility:** generate and store working step code; the bounded-healing rules live here.

**Algorithm (generate → `_loop`, generation pool):**
```
1. LOOP:
   - IF not budgets.try_generation(identity): exhaustion(step_text, code, error, page)   # raises
   - attempt += 1; emit on_generation_started(step_text, attempt)
   - code = _request(step_text, previous_steps, page, existing_code, error,
                     recommendation=None, guidance=None, history=[])
   - TRY settle(run_step_code, code, page, window) → save CachedStep → RETURN
   - EXCEPT AssertionError as check_failure:                  # failed check, survived the window
       error_field = str(check_failure)
       verdict = _classify(step_text, code, error_field, page)   # quiet skip → None
       IF verdict is None: raise IncurableStepError(reason="candidate check failed — <line>",
           error_field, code=code, verdict=None)
       IF verdict.category == "product_defect": raise ProductDefectError(explanation, error_field, verdict)
       IF verdict.category == "incurable": raise IncurableStepError(reason="candidate check failed — <line>",
           error_field, code=code, verdict)
       # rot | fixable → bounded healing:
       IF not budgets.try_healing(identity):
           raise IncurableStepError(reason="healing attempt budget exhausted", error_field, code=code, verdict)
       healed = _funded_regeneration(step_text, previous_steps, page, existing_code=code,
           error=error_field, recommendation=verdict.recommendation, window, attempt_ref)   # ONE request
       IF healed is not None: RETURN healed                   # stored inside
       # repeat failure → one final classification, terminal kind only:
       final = _classify(step_text, last_code, last_error_field, page)
       IF final is not None and final.category == "product_defect":
           raise ProductDefectError(final.explanation, last_error_field, final)
       raise IncurableStepError(reason=<kind-authored>, last_error_field,
           code=last_code, verdict=final)
       # kind-authored reason: an AssertionError repeat — "candidate check failed — <first line>";
       #   any other failure — "candidate failed — <first line>"; the quiet-skip path (final is
       #   None, LLM unavailable) keeps "candidate check failed — <first line>" — contract wording
   - EXCEPT Exception as candidate_error:
       existing_code, error = code, format_step_error(candidate_error)   # retry with fresh error

2. exhaustion(...):    # generation pool refused
   - IF error is None: raise IncurableStepError("generation attempt budget exhausted", "", code="", None)
   - verdict = _classify(step_text, code, error, page)
   - IF verdict is None: raise IncurableStepError("generation attempt budget exhausted", error, code, None)
   - product_defect → ProductDefectError(explanation, error, verdict)
   - incurable      → IncurableStepError("generation attempt budget exhausted", error, code, verdict)
   - rot | fixable:
       IF not budgets.try_healing(identity): raise IncurableStepError("healing attempt budget exhausted",
           error, code, verdict)
       healed = _funded_regeneration(..., recommendation=verdict.recommendation, ...)
       IF healed is not None: RETURN healed
       raise IncurableStepError("generation attempt budget exhausted", <repeat failure text>,
           code=<failed candidate>, verdict)          # no reclassification
```

`_funded_regeneration(...)`: one attempt (attempt += 1, emit `on_generation_started`), one provider
request carrying `existing_code`/`error`/`recommendation`, one `settle` execution; success →
`CachedStep` + `cache.save` + return; failure of the execution — never of the provider request,
whose `LLMUnavailableError` propagates immediately — returns None together with the failed code
and the `format_step_error` text for the caller's terminal handling.

**Algorithm (regenerate → `_loop`, healing pool):** the same loop, `spend = try_healing`, every
request carries `existing_code`/`error`/`recommendation`; **every** failed attempt (failed checks
included) takes the retry branch; exhaustion raises `IncurableStepError("healing attempt budget
exhausted", error, code, verdict=None)`.

**Errors:** as traced; `LLMUnavailableError` from a provider generation request propagates
immediately (no retry on it) — unchanged.

**Edge Cases:**
- `attempt` counts LLM requests of the pool run: loop attempts + the funded regeneration(s) —
  `on_generation_started` fires for each.
- The settle window is shared: the funded regeneration runs under the same `window` (it is the same
  step execution).

### `StepHealer.heal` (changed)

**Responsibility:** classify a failed cached step; the verdict decides the branch.

**Algorithm:**
```
1. classification = classify_step_failure(config, provider, step.identity.normalized_text,
   step.code, error, page)                # LLMUnavailableError propagates
2. verdict = FailureVerdict(category, explanation, recommendation)
3. emit on_healing_started(step_text, category)
4. product_defect → raise ProductDefectError(step_text, explanation, error, verdict)
5. incurable      → raise IncurableStepError(step_text, explanation, error, code=step.code, verdict)
6. rot | fixable:
   - TRY healed = generator.regenerate(identity, step_text, previous_steps, page,
       existing_code=step.code, error, recommendation=classification.recommendation, window)
   - EXCEPT IncurableStepError as inner:        # exhaustion, verdict None
       raise IncurableStepError(step_text, inner.reason, inner.error, code=step.code, verdict) from inner
   - emit on_healed(step_text, explanation); RETURN healed
```

**Errors:** as traced.

**Edge Cases:** a failed check inside the regeneration loop now retries instead of classifying —
the entry classification already guards the anti-masking.

### `Config` + `load_config` (changed)

**Algorithm:** three new fields with validators:
```
polling_timeout: float | None = None      # validator: None or a finite >= 0 (math.isfinite) — a
                                          # negative or non-finite value (inf/nan, e.g. env "inf")
                                          # fails loudly; else "must be None or a non-negative number"
polling_delay: float = 0.5                # validator: >= 0 (finite), else "must be a non-negative number"
interactive: bool = False
```
Loader: `_ENV_NAMES` += the three; `_BOOL_ENV_SETTINGS` += `interactive`;
`_FLOAT_ENV_SETTINGS = {"polling_timeout", "polling_delay"}` (`float(raw)`, loud failure);
`_ALLOWED_TEXT` += the three; `_apply_overrides` gains `if value is None: continue` before the
string-emptiness check.

**Errors:** loud `ConfigurationError` naming setting, received value, allowed form; the pydantic
`ValidationError` stays chained.

**Edge Cases:** env `PRETTYPLAY_POLLING_TIMEOUT=0` → `0.0` (explicit disable); a set-but-empty env
value → unparseable float → loud failure (no silent ignore); env `inf`/`1e400` → non-finite →
loud validation failure (an infinite settle window is never constructible).

### `LLMProvider` + `_request` + both providers (changed)

**Algorithm:** `generate_step_code` port signature grows `recommendation: str | None`,
`guidance: str | None`, `guidance_history: list[str]` (no defaults — callers pass explicitly,
uniform with `existing_code`/`error`); both implementations forward verbatim to
`build_fields_text`, which appends the three optional blocks after ERROR in the fixed order;
`CATEGORIES` = {rot, product_defect, fixable, incurable}.

**Errors:** unchanged (`LLMUnavailableError` mapping, empty-completion refusal).

### `IncurableStepError` (changed)

**Algorithm:** `__init__(self, step_text, reason, error="", code="", verdict=None)`; new property
`code -> str`; the render path is untouched. All raisers updated: executor (strict miss `""`,
strict failure `step.code`), generator (last candidate), healer rewrite (`step.code`).

### `StepHooks` (changed)

**Algorithm:** new no-op `on_step_finished(self, step_text: str, step_type: str, outcome: str)`,
placed between `on_step_verdict` and `on_generation_started` (the contract order); the class
docstring grows to "ten prettyplay events".

## Cross-cutting Concerns

- **Error handling**: the taxonomy is unchanged (`PrettyplayError` base; three step kinds +
  `ConfigurationError`). New rules: settle never translates — the original exception object
  propagates; the steering gate catches exactly `IncurableStepError`; every steering exit heals or
  returns None; KeyboardInterrupt is never swallowed anywhere (settle catches `Exception` only;
  the REPL treats it as a decline at the `input()` boundary only).
- **Logging** (logger `prettyplay`, lowercase event names, contextual metadata via `extra`):
  - INFO `settle_retry` — `{"attempt": int, "error": str}` — per repetition, no hook event.
  - INFO `steering_opened` / `steering_guidance` / `steering_declined` — `{"step_text": str}` /
    `{"step_text": str, "message": str}` / `{"step_text": str}` — the guidance is one-shot in the
    log and never persisted anywhere else.
  - All hook events log at their lifecycle level via the reporter: `on_step_finished`,
    `on_step_failed` and the verdict events are INFO — step lifecycle per the reporting contract;
    `_WARNING_EVENTS` stays `{"on_cache_skipped"}`; a failed hook call still logs WARNING from the
    emit fan-out.
  - No secrets: step sentences, code and guidance land in logs/cache — the existing rule covers the
    new guidance text.
- **Validation**: `polling_timeout`/`polling_delay`/`interactive` validate at the pydantic boundary
  with the loud actionable render; env parsing fails loudly by field type; nothing else validates
  at runtime (`SettleWindow` trusts the validated config).
- **Caching**: mechanics unchanged (`StepCache`, `CachedStep`, deterministic address). New writes:
  the steering green turn writes back under the stuck step's `identity` — only after a successful
  execution; guidance never enters the cache file. Settle re-executions and steering turns never
  touch budgets.
- **Concurrency**: no new threads. The REPL runs on the test thread; every page interaction
  marshals to the single driver thread exactly as before (`input()` blocks only the test thread);
  `SettleWindow` is single-thread bookkeeping (created, started and read on the test thread);
  `time.monotonic()` for the window.

## Usages Analysis

### `conventions` (project, `.goga/usages/conventions.md`)
- **What it provides**: Python code/test rules — relative intra-package imports, pydantic kw_only
  models with empty defaults, Google docstrings, logging discipline, blank-line block separation,
  test structure mirroring source.
- **Where used**: every cell (global annotations); all new modules and tests follow it.
- **Why chosen**: the project-wide mandatory standard.
- **How exactly**: pydantic `kw_only=True` + empty defaults for the new `Config` fields; relative
  imports (`from ...driver import …`, `from ..execution import …`); `tests/engine/polling/…`,
  `tests/engine/steering/…`, `tests/driver/test_errors.py` mirror the source tree; Google docstrings
  on every new public callable.

### `system_prompt` (project, `.goga/usages/prompts/generation.md`)
- **What it provides**: the single source of the generation/regeneration system prompt — now with
  the RECOMMENDATION / USER GUIDANCE / HISTORY input lines and the guidance-following rule.
- **Where used**: `StepGenerator` (every generation/regeneration/funded request) and `StepSteering`
  (every guided request) — both render it verbatim as the system message.
- **Why chosen**: one prompt for both requesting cells; the file evolves independently of the
  manifests.
- **How exactly**: frozen module constants (`SYSTEM_PROMPT` in `generator.py` and in
  `steering.py`) mirroring the file verbatim, changed only together with it — the established
  `PAGE_API_SURFACE` pattern. A runtime file read is rejected: `.goga/` is repo-level and absent
  from an installed wheel; an engine-contract export of the constant is rejected: it would reopen
  the applied contract for a non-contractual implementation detail.

### `playwright` (project, `.goga/usages/cooks/playwright.md`)
- **What it provides**: the sync-API lifecycle, locator/auto-wait semantics, and — new — the error
  kinds section: exception types and message signatures of the driver error surface.
- **Where used**: the whole driver cell; `is_pollable_failure` bases its fixed map on the error
  kinds table verbatim.
- **Why chosen**: the driver parity source.
- **How exactly**: `from playwright.sync_api import Error as PlaywrightError`; the pattern set of
  the pollable map mirrors the documented kinds one-to-one.

### `facade` (imported from `prettyplay/driver/.usages/facade.md`)
- **What it provides**: the page/element/dialog/frame surface listing — the calls step code may
  make.
- **Where used**: engine (PAGE_API_SURFACE, sent with every request) and — new — steering (its own
  `PAGE_API_SURFACE` copy, same mirroring rule); also the steering turn executions work through the
  same facade.
- **Why chosen/imported**: the single source of the request-time page API listing.
- **How exactly**: both constants change only together with `facade.md`.

### `taxonomy` (imported from `prettyplay/failures/.usages/taxonomy.md`)
- **What it provides**: the failure kinds, the four verdict categories, the structured render, the
  `code` field contract for programmatic consumers.
- **Where used**: facade (step/expect raises), executor strict paths, steering banner fields.
- **Why chosen/imported**: integrator-facing failure semantics.
- **How exactly**: `info.value.code` consumed programmatically; the render never parsed.

### `hooks` (imported from `prettyplay/reporting/.usages/hooks.md`)
- **What it provides**: the ten-event callback contract, attempt semantics, the verbatim error
  payload rule.
- **Where used**: facade (constructor `hooks`, `add_hooks`), reporter fan-out, steering `on_healed`.
- **Why chosen/imported**: the integrator visibility surface.
- **How exactly**: `on_step_finished` closes every step exactly once.

### `generation`, `healing` (imported from `prettyplay/engine/.usages/{generation,healing}.md`)
- **What they provide**: the generate/heal call shapes with `window`, the decision table, the
  bounded-healing rules, budget semantics.
- **Where used**: facade executor delegation.
- **Why chosen/imported**: the engine cycles the executor delegates to.
- **How exactly**: as traced in the executor/generator/healer algorithms.

### `classification` (imported from `prettyplay/llm/.usages/classification.md`) — engine
- **What it provides**: the four categories + the unrecognized→incurable fallback, the call shape.
- **Where used**: `classify_step_failure`, both provider parsers.
- **Why chosen/imported**: classification semantics shared by both engines.

### Local practices of the new cells
- `prettyplay/engine/polling/.usages/settle.md` — consumer doc for the window/settle (already
  current with the contract; the code example matches the final signatures).
- `prettyplay/engine/steering/.usages/steering.md` — consumer doc for the REPL (current; one
  editorial fix pending, see `.usages/` Update).
- `prettyplay/driver/.usages/error_kinds.md` — consumer doc for the pollable map (current; not
  imported by any cell — consumer documentation only, the accepted `budgets.md` pattern).

## `.usages/` Update

### Cell: `prettyplay/engine/steering`

#### Existing Files — Consistency
- **`steering.md`** → `prettyplay/engine/steering/.usages/steering.md`
  - Status: current in substance; one editorial defect.
  - Updates needed: "the settle window does not re-arms inside the dialog" → "does not re-arm"
    (grammar; introduced by the architecture stage). Apply during implementation.

### Cell: all other affected cells

#### Existing Files — Consistency
- `prettyplay/failures/.usages/taxonomy.md`, `prettyplay/reporting/.usages/hooks.md`,
  `prettyplay/config/.usages/configuration.md`, `prettyplay/cache/.usages/budgets.md`,
  `prettyplay/engine/.usages/generation.md`, `prettyplay/engine/.usages/healing.md`,
  `prettyplay/llm/.usages/classification.md`, `prettyplay/llm/.usages/providers.md`,
  `prettyplay/.usages/lifecycle.md`, `prettyplay/.usages/steps.md`,
  `prettyplay/driver/.usages/error_kinds.md`, `prettyplay/engine/polling/.usages/settle.md`
  - Status: current — updated by the architecture stage and verified against the CODEMANIFESTs
    here (label sets, signatures with `window`, hook table incl. `on_step_finished`, env table,
    budget rules, dialog semantics). No additions or updates needed.

#### New Files
- None. Every new functional domain already has its file (`settle.md`, `steering.md`,
  `error_kinds.md`); no CODEMANIFEST `Usages` entry points at an own `.usages/` file.

## Test Stack Trace

### General Setup

- Existing shared fixtures: `tests/conftest.py` (`_no_runtime_atexit` autouse; `write_pyproject`
  helper). New test packages need `__init__.py`: `tests/engine/polling/`, `tests/engine/steering/`.
- Fakes used across the new tests (pattern of the existing suite — `SimpleNamespace`/`mock.Mock`,
  no real browser, no real LLM):
  - `FakePage` — `SimpleNamespace(aria_snapshot=lambda: "- button \"Pay\"", screenshot=lambda: b"png")`.
  - Recording provider fake — captures `generate_step_code`/`classify_failure` kwargs, returns
    scripted code / scripted `FailureClassification`; `side_effect=LLMUnavailableError(...)` for
    unavailability cases.
  - Recording hooks — a `StepHooks` subclass appending `(event, payload)` tuples to a list.
- Polling tests use `window = SettleWindow(timeout=…, delay=0)` and, where time must pass,
  monkeypatch `prettyplay.engine.polling.window.time` (monotonic counter) — no real sleeps beyond
  `sleep(0)`.
- Steering tests monkeypatch `builtins.input` (a scripted answer queue) and
  `prettyplay.engine.steering.steering.SYSTEM_PROMPT` stays real; temp files via `tmp_path`.

### Source File Registry

New: `prettyplay/engine/polling/{__init__,window,settle}.py`,
`prettyplay/engine/steering/{__init__,steering}.py`, `prettyplay/driver/errors.py`.
Changed: `prettyplay/failures/errors.py`, `prettyplay/reporting/hooks.py`,
`prettyplay/config/{models,loader}.py`, `prettyplay/driver/__init__.py`,
`prettyplay/llm/{provider,_request,openai_provider,anthropic_provider,models}.py`,
`prettyplay/engine/{generator,healer,classification}.py`, `prettyplay/executor.py`,
`prettyplay/scenario.py`.

---

### Positive Tests

#### `test_settle_retries_pollable_failure_until_success`

**Setup**: `window = SettleWindow(timeout=5.0, delay=0)`; a fake `execute` raising
`PlaywrightError("Timeout 10000ms exceeded")` on the first two calls, succeeding on the third;
`FakePage`.

**Input**: `settle(execute=flaky, code="def step(page):\n    ...", page=fake_page, window=window)`

**Trace**:
```
settle(execute, code, page, window)
  → window.start()                        # _started_at set once
  → execute(code, page)                   # attempt 1 — raises Timeout
    is_pollable_failure(TimeoutError text) → True; has_remaining() → True
    logger.info("settle_retry", extra={"attempt": 1, "error": "Timeout 10000ms exceeded"})
    time.sleep(0)
  → execute(code, page)                   # attempt 2 — raises again
    settle_retry attempt=2; sleep(0)
  → execute(code, page)                   # attempt 3 — returns None
  → return None
```

**Assertions**:
```
execute.call_count == 3
caplog has two INFO records named "settle_retry" with attempt 1 and 2
no exception raised
```

**Sufficiency**: the core polling contract — a transient failure re-executes the same code inside
the window until success; prevents regressions where settle gives up on pollable failures or
re-executes after success.

#### `test_settle_passes_code_and_page_to_execute`

**Setup**: `window = SettleWindow(timeout=None, delay=0.5)`; `execute = mock.Mock()`.

**Input**: `settle(execute, code="CODE", page=fake_page, window=window)`.

**Trace**:
```
settle → window.start() (no-op booking) → execute("CODE", fake_page) → return
```

**Assertions**: `execute.assert_called_once_with("CODE", fake_page)`.

**Sufficiency**: binds the callable contract `Callable[[str, PageFacade], None]` — a wrong
argument order or a wrapper breaks every caller silently otherwise.

#### `test_generate_failed_check_rot_grants_one_funded_regeneration`

**Setup**: generator with recording provider fake; `RunBudgets(generation_limit=3, healing_limit=2)`;
first candidate raises `AssertionError("button is hidden")` (survives a disabled window);
classification scripted `rot` with recommendation `"retry with an id locator"`; the funded
regeneration returns working code.

**Input**: `generator.generate(identity, "click Pay", [], fake_page, SettleWindow(None, 0.5))`

**Trace**:
```
generate → try_generation → True (attempt 1, on_generation_started)
  → provider.generate_step_code(..., existing_code=None, error=None, recommendation=None) → "def step(page): raise AssertionError"
  → settle(...) → AssertionError
  → _classify → FailureClassification("rot", "…", "retry with an id locator")
  → try_healing → True
  → attempt 2, on_generation_started; provider.generate_step_code(
      existing_code="def step(page): raise AssertionError", error="button is hidden",
      recommendation="retry with an id locator") → working code
  → settle → success → cache.save(CachedStep) → return
```

**Assertions**:
```
provider.generate_step_code.call_count == 2
second call kwargs["recommendation"] == "retry with an id locator"
on_generation_started emitted twice (attempts 1 and 2)
cache.save called once with the healed code
on_healing_started never emitted (the heal engine was not used)
```

**Sufficiency**: the heart of bounded healing — a rot failed check buys exactly one
healing-funded, recommendation-carrying regeneration inside the generate loop; prevents both
unbounded regeneration of failing assertions and losing the diagnosis.

#### `test_exhaustion_rot_verdict_grants_extra_regeneration_and_repeat_failure_is_terminal`

**Setup**: generation budget 1; candidate always fails with `TypeError("bad code")`;
classification scripted `rot`; the funded regeneration also fails.

**Input**: `generate(identity, "fill the form", [], fake_page, SettleWindow(None, 0.5))`

**Trace**:
```
attempt 1 → TypeError → retry branch
try_generation refused → exhaustion path
  → _classify → rot
  → try_healing → True → funded regeneration (attempt 2) → TypeError
  → raise IncurableStepError(reason="generation attempt budget exhausted",
      error="TypeError: bad code", code=<funded candidate>, verdict=rot verdict)
```

**Assertions**:
```
pytest.raises(IncurableStepError) with .verdict.category == "rot"
.code == the funded candidate code
provider.generate_step_code.call_count == 2  (1 loop + 1 funded; no third)
```

**Sufficiency**: pins the exhaustion rule — exactly one extra regeneration, a repeat failure
terminal without reclassification (no third LLM request).

#### `test_heal_fixable_category_regenerates_with_recommendation`

**Setup**: healer + generator with recording fakes; classification scripted `fixable`
(recommendation `"use an unambiguous role locator"`); `CachedStep` with `code="old"`.

**Input**: `healer.heal(step, error="strict mode violation: locator resolved to 2 elements", [], fake_page, SettleWindow(None, 0.5))`

**Trace**:
```
heal → classify → fixability verdict → on_healing_started(category="fixable")
  → generator.regenerate(..., existing_code="old", error=…,
      recommendation="use an unambiguous role locator", window=window) → healed step
  → on_healed → return healed
```

**Assertions**:
```
regenerate called with recommendation="use an unambiguous role locator" and window=window
on_healing_started payload category == "fixable"
returned step is the regenerated one
```

**Sufficiency**: wires the new fourth category through the healing path with its diagnosis —
the consequence the category exists for.

#### `test_steer_green_turn_writes_back_and_reports_healed`

**Setup**: `StepSteering(config, provider_fake, cache_fake, reporter_fake)`; `input` scripted
`["dismiss the modal first"]`; provider returns working code; `run_step_code` monkeypatched to
succeed; failure = `IncurableStepError("click Pay", "budget exhausted", "Timeout…", code="old",
verdict=None)`.

**Input**: `steering.steer(failure, identity, [], fake_page)`

**Trace**:
```
steer → banner (snapshot fragment, temp PNG path) → steering_opened log
  → input → "dismiss the modal first" → steering_guidance log
  → provider.generate_step_code(..., existing_code="old", error="Timeout…",
      recommendation=None, guidance="dismiss the modal first", guidance_history=[])
  → run_step_code → success
  → cache.save(CachedStep(identity, code)) → on_healed(step_text="click Pay", explanation=…)
  → return step
```

**Assertions**:
```
returned step.code == the generated code; cache.save called once with identity
on_healed payload explanation mentions the interactive healing
provider kwargs["guidance"] == "dismiss the modal first"; kwargs["recommendation"] is None
```

**Sufficiency**: the steering happy path — guidance → regeneration → live execution → write-back
only after success; prevents write-backs of unverified code or losing the guidance block.

#### `test_steer_red_turn_appends_history_and_next_request_carries_it`

**Setup**: as above; `input` scripted `["try hovering first", "then click"]`; provider returns
failing code on the first guidance turn, working code on the second.

**Input**: `steer(failure, identity, [], fake_page)`

**Trace**:
```
turn 1: request guidance_history=[] → execution fails → outcome printed →
        history ["try hovering first => <outcome first line>"]
turn 2: request guidance_history=["try hovering first => …"] → success → write-back → return
```

**Assertions**:
```
second provider call kwargs["guidance_history"] == ["try hovering first => …"]
provider.generate_step_code.call_count == 2
```

**Sufficiency**: the HISTORY block contract — the model sees the accumulated turns; prevents
stateless steering where every turn repeats the same mistake.

#### `test_execute_steering_intercept_healed_continues_as_success`

**Setup**: executor with `config = Config(strict=False, interactive=True, polling_timeout=None)`;
cache returns a hit whose code always fails; healer fake raises `IncurableStepError`; steering fake
returns a healed `CachedStep`; recording hooks.

**Input**: `executor.execute("click Pay", "action", fake_page)`

**Trace**:
```
execute → on_step_started → window (disabled) → settle → failure
  → heal → raises IncurableStepError
  → gate: interactive and not strict → steer → healed
  → scenario append → on_step_passed → on_step_finished(outcome="passed")
```

**Assertions**:
```
steering.steer called once with the IncurableStepError instance
hooks sequence ends ["on_step_started", "on_step_passed", "on_step_finished"]
outcome == "passed"; no raise
```

**Sufficiency**: the intercept contract — a healed dialog turns the terminal failure into a
normal pass with the closing event; prevents the healed step still failing the test.

#### `test_execute_reports_on_step_finished_last_on_failure_with_verdict`

**Setup**: executor with a generator fake raising `IncurableStepError(..., verdict=verdict)`;
recording hooks; `interactive=False`.

**Input**: `executor.execute("open the docs", "action", fake_page)` (cache miss, non-strict)

**Trace**:
```
on_step_started → generate → IncurableStepError
  → on_step_failed(error=render) → on_step_verdict(category, explanation, recommendation)
  → on_step_finished(outcome="failed") → raise
```

**Assertions**:
```
events == ["on_step_started", "on_step_failed", "on_step_verdict", "on_step_finished"]
last payload {"step_text": "open the docs", "step_type": "action", "outcome": "failed"}
```

**Sufficiency**: the closing-event ordering — after the verdict, exactly once, regardless of
outcome; an integrator's CI timers/metrics rely on the last-event position.

#### `test_load_config_env_parses_polling_and_interactive`

**Setup**: `write_pyproject()` (empty section); env `PRETTYPLAY_POLLING_TIMEOUT=8`,
`PRETTYPLAY_POLLING_DELAY=0.25`, `PRETTYPLAY_INTERACTIVE=true`.

**Input**: `load_config(pyproject_path)`

**Trace**:
```
load_config → section {} → env collected → _parse_env_scalar:
  polling_timeout → float("8") → 8.0; polling_delay → 0.25; interactive → True
  → Config(**merged) validates → return
```

**Assertions**:
```
config.polling_timeout == 8.0; config.polling_delay == 0.25; config.interactive is True
```

Boundary row (second case): env `PRETTYPLAY_POLLING_TIMEOUT=0` → `config.polling_timeout == 0.0`
— the explicit disable parses to the float zero, not None.

**Sufficiency**: the three env overrides parse by field type — the CI wiring of both features —
and the zero boundary of the disable stays distinguishable from None.

#### `test_build_fields_renders_new_blocks_in_fixed_order`

**Setup**: direct call to `_request.build_fields_text`.

**Input**: all blocks non-empty — `user_instructions="style"`, `existing_code="old"`,
`error="err"`, `recommendation="rec"`, `guidance="do this"`, `guidance_history=["h1", "h2"]`.

**Trace**:
```
build_fields_text → sections joined with blank lines in order:
STEP, PREVIOUS STEPS, PAGE SNAPSHOT, PAGE API, USER INSTRUCTIONS, CODE, ERROR,
RECOMMENDATION, USER GUIDANCE, HISTORY
```

**Assertions**:
```
text.index("PAGE API:") < text.index("USER INSTRUCTIONS:") < text.index("CODE:")
  < text.index("ERROR:") < text.index("RECOMMENDATION:") < text.index("USER GUIDANCE:")
  < text.index("HISTORY:")
"HISTORY:\nh1\nh2" in text
```

**Sufficiency**: the fixed block order is a parity contract of both providers; a reordered block
silently degrades regeneration quality for one provider only.

#### `test_parse_classification_accepts_fixable_label`

**Setup/Input**: `parse_classification_line("fixable | ambiguous locator | use role locator")`

**Trace**: line split on `|` → category in CATEGORIES (fixable added) → triple returned.

**Assertions**: result == `("fixable", "ambiguous locator", "use role locator")`.

**Sufficiency**: the fourth label must parse — otherwise every fixable verdict falls to the
incurable fallback and healing never runs.

#### `test_is_pollable_failure_map` (parametrized table)

**Setup**: exceptions constructed with the exact messages.

**Input** (parametrize):
```
PlaywrightError("Locator.click: Timeout 10000ms exceeded.")              → True
PlaywrightError("element is not visible")                                 → True
PlaywrightError("element is not enabled")                                 → True
PlaywrightError("Execution context was destroyed, most likely…")          → True
PlaywrightError("Target closed")                                          → True
PlaywrightError("Frame has been detached.")                               → True
PlaywrightError("… was interrupted by another navigation to …")           → True
AssertionError("Locator expected to be visible")                          → True
PlaywrightError("strict mode violation: locator resolved to 2 elements")  → False
AssertionError("strict mode violation: locator resolved to 2 elements")   → False
NameError("name 'paeg' is not defined")                                   → False
PlaywrightError("something never seen before")                            → False
```

**Trace**: each row → `is_pollable_failure(exc)` → bool by the fixed map (ambiguity check first,
AssertionError second, playwright pattern set third, conservative False).

**Assertions**: `is_pollable_failure(exc) is expected` per row.

**Sufficiency**: the pollable map is the entire polling correctness surface — one table pins every
documented kind and the conservative default (conventions: boundary tables via parametrize).

---

### Negative Tests

#### `test_settle_propagates_non_pollable_failure_immediately`

**Setup**: `window = SettleWindow(timeout=5.0, delay=0)`; `execute` raises
`PlaywrightError("strict mode violation: locator resolved to 2 elements")`.

**Input**: `settle(execute, "code", fake_page, window)`

**Trace**: attempt 1 → ambiguity → not pollable → `raise` (the same object).

**Assertions**:
```
pytest.raises(Exception) as info: info.value is the original exception object
execute.call_count == 1; no settle_retry records
```

**Sufficiency**: deterministic failures must reach classification untouched — a retried ambiguity
wastes the window and delays the verdict.

#### `test_generate_failed_check_refused_funding_is_terminal`

**Setup**: `RunBudgets(generation_limit=3, healing_limit=0)`; candidate fails the check;
classification scripted `rot`.

**Input**: `generate(identity, "click Pay", [], fake_page, SettleWindow(None, 0.5))`

**Trace**: failed check → rot verdict → `try_healing` refused →
`IncurableStepError(reason="healing attempt budget exhausted", verdict=rot verdict)`.

**Assertions**:
```
pytest.raises(IncurableStepError).value.reason == "healing attempt budget exhausted"
.verdict.category == "rot"; provider.generate_step_code.call_count == 1  (no unfunded request)
```

**Sufficiency**: no unfunded regeneration ever runs — the budget invariant the usage file states.

#### `test_steer_quit_eof_sigint_return_none` (parametrized: quit / EOF / SIGINT)

**Setup**: steering with `input` fake raising `KeyboardInterrupt` or returning `"quit"` /
raising `EOFError`; provider fake would answer if asked.

**Input**: `steer(failure, identity, [], fake_page)`

**Trace**: prompt → exit condition → `steering_declined` log → return None; executor side:
`_steer_or_raise` re-raises the original failure.

**Assertions**: `steer(...) is None`; `provider.generate_step_code` not called; nothing hangs.

**Sufficiency**: the nothing-hangs guarantee — CI safety of the opt-in REPL.

#### `test_steer_provider_unavailable_ends_dialog`

**Setup**: provider fake `side_effect=LLMUnavailableError("llm unavailable: openai")`; `input`
returns a guidance line.

**Input**: `steer(failure, identity, [], fake_page)`

**Trace**: guidance → request raises → dialog ends → return None.

**Assertions**: `steer(...) is None`; executor propagates the original IncurableStepError.

**Sufficiency**: the gate's "never when the LLM is unavailable" — the dialog must not loop on a
dead provider.

#### `test_execute_steering_intercept_never_on_product_defect_llm_strict_or_off` (parametrized)

**Setup**: four executor configurations: heal raises `ProductDefectError`; generate raises
`LLMUnavailableError`; strict config with a failing cached step; `interactive=False` with an
`IncurableStepError`. Steering fake would heal.

**Input**: `executor.execute(...)` per case.

**Trace**: each terminal error escapes the `except IncurableStepError` clause (or the gate
refuses) → propagates; steering.steer never called.

**Assertions**: `steering.steer.assert_not_called()`; the original error kind propagates.

**Sufficiency**: the four negative gate clauses — a dialog must never repaint a red test green,
never open in replay-strict, never on infrastructure failure, never when off.

#### `test_config_rejects_negative_polling_values` (parametrized)

**Setup**: `pytest.raises(ValidationError)` — `Config(polling_timeout=-1.0)`,
`Config(polling_delay=-0.5)`.

**Input**: direct construction.

**Trace**: field validator fails → ValidationError.

**Assertions**: raises with the field named; `Config(polling_timeout=0.0, polling_delay=0)` valid.

**Sufficiency**: the load-time validation contract — negative windows are nonsense and must fail
loudly, zero must stay legal (explicit disable).

#### `test_load_config_env_rejects_unparseable_float` (parametrized: `soon` | `inf`)

**Setup**: `write_pyproject()`; env `PRETTYPLAY_POLLING_TIMEOUT=soon` (then `inf`).

**Input**: `load_config(pyproject_path)`.

**Trace**: `soon` → `_parse_env_scalar` → `float("soon")` ValueError → loud `ConfigurationError`;
`inf` → `float("inf")` parses → the field validator rejects the non-finite value → loud
`ConfigurationError`.

**Assertions**: `soon` — message contains `polling_timeout`, `received 'soon'`, `a decimal float`;
`inf` — message contains `polling_timeout` and `received inf` (non-finite refused).

**Sufficiency**: no silent ignore of a bad env override, and no infinite settle window is ever
constructible (the loader + validation contract).

---

### Edge Case Tests

#### `test_window_state_table` (parametrized)

**Setup/Input**:
```
SettleWindow(None, 0.5): enabled False; has_remaining False before and after start
SettleWindow(0, 0.5):    enabled False                            # 0 — explicit disable
SettleWindow(5.0, 0.5):  not started → has_remaining False; started, monotonic+2  → True;
                         monotonic+5 → False                       # exact boundary — strict <
                         monotonic+6 → False                       # expired
```

**Trace**: pure state machine on a monkeypatched monotonic clock.

**Assertions**: each row's `enabled`/`has_remaining` values exactly.

**Sufficiency**: the window gates repetitions — off-by-one at the boundary (`<` vs `<=`) either
never retries or retries forever at the edge.

#### `test_window_start_is_idempotent`

**Setup**: `SettleWindow(5.0, 0.5)`; monkeypatched monotonic returning 1.0 then 9.0.

**Input**: `start(); start()`.

**Assertions**: `_started_at == 1.0` — the second call never shifts the window start.

**Sufficiency**: "later executions of the same step never shift the start" — a restarted window
would extend polling beyond the configured horizon.

#### `test_settle_disabled_window_single_execution`

**Setup**: `SettleWindow(None, 0)`; `execute` raises a pollable timeout forever.

**Input**: `settle(execute, "code", page, window)`.

**Assertions**: `execute.call_count == 1`; the exception propagates; no settle_retry records.

**Sufficiency**: the default configuration (polling off) must behave exactly as today — polling is
strictly opt-in.

#### `test_explicit_zero_and_false_override_the_file_layer`

**Setup**: `write_pyproject(polling_timeout=8.0, interactive=True)`;
`overrides = PrettyConfig(polling_timeout=0.0, interactive=False)`.

**Input**: `load_config(pyproject_path, overrides)`.

**Trace**: both fields in `model_fields_set`, not None, not empty strings → participate → win.

**Assertions**: `config.polling_timeout == 0.0`; `config.interactive is False`.

**Sufficiency**: the per-test escape hatch — disabling polling/steering for one test against the
project file.

#### `test_explicit_none_polling_timeout_is_indistinguishable_from_unset`

**Setup**: `write_pyproject(polling_timeout=8.0)`; `overrides = PrettyConfig(polling_timeout=None)`.

**Input**: `load_config(pyproject_path, overrides)`.

**Trace**: `value is None` → skipped by the merge → the file layer survives.

**Assertions**: `config.polling_timeout == 8.0`.

**Sufficiency**: the documented constraint — None means unset, 0.0 is the only per-test disable;
a naive merge would silently kill polling for that test.

#### `test_incurable_code_field_absent_from_render_and_hook_payload`

**Setup**: `IncurableStepError("click Pay", "budget exhausted", "Timeout …", code="def step(page): boom()", verdict=None)`; recording hooks through an executor failure.

**Input**: `str(exc)`; the `on_step_failed` payload of the executor path.

**Assertions**: `"def step(page): boom()" not in str(exc)`; not in the hook payload;
`exc.code == "def step(page): boom()"`.

**Sufficiency**: the programmatic-only contract — a leaked code block would break the structured
render integrators parse.

#### `test_strict_failure_carries_cached_code_and_miss_carries_empty`

**Setup**: strict executor; a cached failing step (classification scripted `rot`) and a cache miss.

**Input**: `execute(...)` twice (parametrized scenario).

**Assertions**: cached-failure `IncurableStepError.code == cached.code`; cache-miss
`IncurableStepError.code == ""`.

**Sufficiency**: the failures contract "the cached step code on the strict failure paths … the
strict cache miss carries none".

#### `test_on_generation_started_fires_once_despite_settle_retries`

**Setup**: generator with a candidate that fails twice with a pollable timeout then succeeds;
`window = SettleWindow(timeout=10.0, delay=0)`.

**Input**: `generate(identity, "click Pay", [], fake_page, window)`.

**Assertions**: `on_generation_started` emitted exactly once; two `settle_retry` log records;
budgets spent exactly one generation attempt.

**Sufficiency**: "hook events fire per step or per LLM attempt — never per execution retry"; also
pins that settle re-executions are budget-free.

#### `test_steer_local_commands_served_without_llm`

**Setup**: `input` scripted `["code", "error", "snapshot", "screenshot", "quit"]`; provider fake
would answer if asked; `fake_page`.

**Input**: `steer(failure, identity, [], fake_page)`.

**Assertions**: `provider.generate_step_code` not called; `steer` returns None; the outputs
(captured stdout) contain the failed code, the error text, the snapshot, and a printed temp PNG
path that exists on disk.

**Sufficiency**: local inspection must never cost an LLM request — and `screenshot` must really
write the file it prints.

#### `test_prettyplay_composes_steering_and_threads_it_into_the_executor`

**Setup**: `PrettyPlay(cache_key="k", config=PrettyConfig(interactive=True))` with monkeypatched
engine/driver boundaries (no browser, no LLM).

**Input**: construction.

**Assertions**: `isinstance(executor._steering, StepSteering)`; the same instance is passed to the
`StepExecutor` constructor; steering holds the same cache and reporter objects as the healer.

**Sufficiency**: the facade composition contract (steps 5–6) — a missing wiring silently disables
steering with no error.

#### `test_scenario_and_full_integration_green_path_with_window`

**Setup**: `tests/test_integration.py` extension — a scripted provider over a fake page;
`PrettyConfig(polling_timeout=6.0)`.

**Input**: `test.step("open the page"); test.expect("the heading is visible")`.

**Trace**: full cycle — window per step, cache write, hooks sequence ending with
`on_step_finished("passed")` per step.

**Assertions**: both steps pass; hook sequence per step is
`[on_step_started, on_generation_started, on_cache_saved?, on_step_passed, on_step_finished]`.

**Sufficiency**: the end-to-end wiring of both features through the public facade.

#### `test_strict_replay_settle_absorbs_transient_cached_failure`

**Setup**: executor with `Config(strict=True, polling_timeout=10.0, polling_delay=0)`; cache
returns a hit; `run_step_code` monkeypatched to raise `PlaywrightError("Timeout 10000ms
exceeded")` on the first call and pass on the second; recording hooks; a provider fake that would
record any call.

**Input**: `executor.execute("click Pay", "action", fake_page)`.

**Trace**:
```
on_step_started → window (enabled) → settle(run_step_code, cached.code, page, window)
  → pollable failure → settle_retry (attempt=1) → sleep(0) → re-execution → success
  → on_step_passed → on_step_finished(outcome="passed")
```

**Assertions**:
```
no exception raised
hooks sequence == ["on_step_started", "on_step_passed", "on_step_finished"]
caplog carries exactly one "settle_retry" record
provider.generate_step_code.assert_not_called() and provider.classify_failure.assert_not_called()
```

**Sufficiency**: pins "replay-strict included: re-executing cached code is execution, not
generation" — the most-cited polling-integration rule; the regression it prevents is strict runs
failing (and classifying) on transient states the window should absorb.

#### `test_steer_survives_dead_page_banner_and_commands`

**Setup**: `FakePage` whose `aria_snapshot`/`screenshot` raise `PlaywrightError("Target closed")`;
`input` scripted `["snapshot", "quit"]`; provider fake would answer if asked; failure =
`IncurableStepError("click Pay", "budget exhausted", "Timeout…", code="old", verdict=None)`.

**Input**: `steering.steer(failure, identity, [], fake_page)`.

**Trace**:
```
banner → aria_snapshot raises → degradation line printed ("snapshot unavailable: Target closed")
  → steering_opened logged → "snapshot" command → snapshot raises → degradation line printed
  → "quit" → steering_declined → return None
```

**Assertions**:
```
steer(...) is None — nothing raised out of the dialog
captured stdout contains "snapshot unavailable: Target closed"
steering_declined log record present; no on_healed emitted
```

**Sufficiency**: the steering contract "every exit path either heals or returns None" — a dead
page must not displace the original terminal failure with a raw PlaywrightError.

#### `test_steer_blank_guidance_line_reprompts_without_llm`

**Setup**: `input` scripted `["", "   ", "quit"]`; provider fake would answer if asked; FakePage.

**Input**: `steer(failure, identity, [], fake_page)`.

**Trace**: banner → empty line → re-prompt (no log, no request) → whitespace line → re-prompt →
`quit` → `steering_declined` → None.

**Assertions**:
```
steer(...) is None
provider.generate_step_code.assert_not_called()
caplog carries no "steering_guidance" record
```

**Sufficiency**: the human-input boundary — an accidental Enter costs no LLM request and writes
no empty guidance into the log.

#### `test_steer_no_candidate_failure_empty_code`

**Setup**: failure = `IncurableStepError("click Pay", "generation attempt budget exhausted", "",
code="", verdict=None)`; `input` scripted `["code", "<a guidance line>"]`; provider returns
working code; `run_step_code` monkeypatched to succeed.

**Input**: `steer(failure, identity, [], fake_page)`.

**Trace**: banner renders an empty code block → `code` command prints the empty block → guidance
→ request with `existing_code=""` → execution succeeds → write-back → on_healed → return step.

**Assertions**:
```
provider kwargs["existing_code"] == ""
captured stdout contains the empty code block of the banner and the `code` command
returned step.code == the generated code; cache.save called once
```

**Sufficiency**: the no-candidate exhaustion boundary — the dialog stays usable when there is no
failed code to show, and the request degrades to plain regeneration inputs.

#### `test_execute_step_finished_fires_on_keyboard_interrupt`

**Setup**: executor with `Config(strict=False, interactive=True)`; cache miss; generator fake
raises `IncurableStepError(...)`; steering fake's `steer` raises `KeyboardInterrupt` (SIGINT inside
the dialog); recording hooks.

**Input**: `executor.execute("click Pay", "action", fake_page)`.

**Trace**: on_step_started → generate → IncurableStepError → gate passes → steer raises
KeyboardInterrupt (BaseException — not caught by the steering gate or the executor's `except
Exception`) → `finally` emits `on_step_finished(outcome="failed")` → KeyboardInterrupt propagates.

**Assertions**:
```
pytest.raises(KeyboardInterrupt)
hooks sequence ends with ("on_step_finished", {"step_text": "click Pay", "step_type": "action",
"outcome": "failed"})
no on_step_failed event (the interrupt is not a step failure)
```

**Sufficiency**: the documented SIGINT policy — the interrupt is honest (never swallowed into a
loop or a heal) and the closing event still fires exactly once.

## Additional Instructions for the Implementation Agent

- **Binding interpretive decisions** (from the design traces; follow exactly):
  1. `regenerate` raises budget-exhaustion `IncurableStepError` with `verdict=None`; the healer
     rewrites it carrying the entry verdict and `step.code`. Never add a verdict parameter to
     `regenerate` — the contract signature is fixed.
  2. `SYSTEM_PROMPT` and `PAGE_API_SURFACE` exist as frozen constants in `engine/generator.py`
     and, duplicated verbatim, in `engine/steering/steering.py`. Both copies change only together
     with `.goga/usages/prompts/generation.md` and `driver/.usages/facade.md` respectively —
     mirror the existing `PAGE_API_SURFACE` comment style. Do not read `.goga/` at runtime.
  3. The generate-loop bounded regenerations (failed-check rot/fixable and exhaustion rot/fixable)
     are single inline requests funded by an explicit `try_healing` check — they are NOT calls to
     `regenerate` (whose loop retries). Each fires `on_generation_started` (an LLM attempt) and
     runs under the same settle window.
  4. Steering requests pass `recommendation=None` — the steering contract enumerates guidance and
     history only; the verdict diagnosis is banner-only.
  5. The settle `attempt` counter is the 1-based ordinal of the failed execution that triggers the
     repetition.
  6. `_apply_overrides` gains the `value is None → skip` clause; keep the string-emptiness clause
     after it.
  7. `is_pollable_failure` checks the ambiguity message first, then `AssertionError`, then
     `PlaywrightError` type + the fixed pattern set (lowercased matching); everything else is
     conservatively False.
  8. `IncurableStepError.__init__` inserts `code: str = ""` between `error` and `verdict`; update
     every raiser (executor strict paths and miss, generator loop/exhaustion/funded paths, healer
     rewrite). `ProductDefectError` gains nothing.
  9. The pollable pattern set is the verified one (algorithm `matches_pollable`): the detach
     family is `element is not attached` | `frame has been detached` | `detached from document`
     (the draft's `element has been detached` matches no real Playwright message — do not
     implement it); navigation/context adds `interrupted by another navigation` and `navigation
     interrupted the evaluation`.
  10. A blank or whitespace-only guidance line in the steering dialog is a re-prompt: no log
      record, no LLM request, no history entry.
  11. `polling_timeout` validation requires a finite value (`math.isfinite`) — env `inf`/`1e400`
      fails loudly; `_ALLOWED_TEXT` reads "None or a non-negative number (finite)".
  12. Every page interaction of the steering dialog (banner snapshot/screenshot, the
      `snapshot`/`screenshot` commands, the request-time snapshot) is individually guarded: a
      failed interaction prints its own failure text and the dialog continues — no `Exception`
      escapes `steer`. `StepSteering(reporter=None)` substitutes `StepReporter([])`.
  13. The repeat-failure terminal reason of the generate loop is kind-authored: an AssertionError
      repeat keeps "candidate check failed — <first line>"; any other failure uses "candidate
      failed — <first line>"; the quiet-skip path keeps the contract wording "candidate check
      failed — <first line>".
- **Presentation constants resolved for the ADR's open items**: snapshot fragment = first 20 lines
  of `page.aria_snapshot()`; screenshots (banner and command) write a full PNG to the `tempfile`
  system directory as `prettyplay-steering-*.png` and print the path; a history line is
  `f"{guidance} => {first line of str(outcome)}"`. Recommended `polling_timeout` guidance: the
  window must exceed the facade's longest internal wait the engineer wants to absorb (Playwright
  expect default 5 s) — the documented example value 6.0 covers one exhausted expectation plus one
  re-execution; note in docs that a 30 s action wait consumes any sane window alone, so polling
  targets expectation/element-state races.
- **Editorial fix**: `prettyplay/engine/steering/.usages/steering.md` — "does not re-arms" →
  "does not re-arm".
- **Package wiring**: create `prettyplay/engine/polling/__init__.py` (exports `SettleWindow`,
  `settle`), `prettyplay/engine/steering/__init__.py` (exports `StepSteering`),
  `prettyplay/driver/errors.py`; extend `prettyplay/driver/__init__.py` with `is_pollable_failure`.
  Steering imports `run_step_code` from `..execution` (module path, not the engine package
  `__init__`). `prettyplay/__init__.py` needs no change — the facade contract re-exports nothing
  new.
- **Validation gates**: `pytest tests/ -x` and `ruff check prettyplay/` must pass; `goga lint`
  stays at 0 errors (no CODEMANIFEST changes are needed — this design found no contract defects).
