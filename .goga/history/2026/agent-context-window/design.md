# Design Document: `agent-context-window`

The step cycle carries an honest context window end to end: one continuous verbatim per-step attempt history (`StepAttempt` records) threading through generation, healing and steering; honest request inputs (the step type and the raw step sentence) into every request; a two-dimension compliance gate (instruction compliance + step adequacy) judging from the step type and the attempt history; and the replayability requirement in the generation system prompt.

Source of the contracts: the working-tree CODEMANIFEST changes on branch `agent-context-window` (materialized from `arch.md` by the apply-architecture stage). This design specifies **what to implement and how** — no implementation code is written at this stage.

---

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/llm/CODEMANIFEST`: `generate_step_code` gains `step_type` + `attempt_history`, drops `existing_code`/`error`/`guidance_history` (tail block order HISTORY, RECOMMENDATION, USER GUIDANCE); `check_instruction_compliance` gains `step_type` + `attempt_history` (user content: INSTRUCTIONS, STEP with its STEP TYPE line, ATTEMPT HISTORY, CODE); `ComplianceFinding` gains `dimension` (instruction|adequacy); `parse_compliance_verdict` validates the dimension — an old-shaped answer (no dimension) is malformed; both provider algorithms render the new inputs in full parity; header annotations add the step-type and attempt-history parity rules.
- `prettyplay/engine/CODEMANIFEST`: new Entity `StepAttempt` (`location: attempts.py`); `compliance_prompt` practice rewritten for two dimensions with STEP TYPE + ATTEMPT HISTORY inputs and dimension calibration; `StepGenerator.generate`/`regenerate`, `StepHealer.heal`, `check_step_compliance` gain `step_type`/`attempt_history` (regenerate drops `existing_code`/`error`); record-append and URL-bracket mechanics in the algorithms; new global annotation rules (continuous history, honest inputs, URL pairs, record append, replayability mirror).
- `prettyplay/engine/steering/CODEMANIFEST`: Imports add `StepAttempt` from `prettyplay/engine`; `steer` gains `step_text`, `step_type`, `attempt_history`; the dialog joins the shared per-step history (the dialog-local turn history is gone); write-back gate extended to both dimensions; URL bracketing per turn; a rejected turn records the same URL on both sides.
- `prettyplay/CODEMANIFEST`: Imports add `StepAttempt` from `prettyplay/engine`; `StepExecutor.execute` gains history creation (step 2), replay URL brackets (step 3), record-0 seeding before the heal delegation (step 4), honest-inputs threading into generate/heal/steer (steps 4–6) and three new requirements; the honest-inputs global annotation.

### New Entities

- `StepAttempt` — one verbatim record of the per-step attempt history; `prettyplay/engine/attempts.py` (new file). Five properties (`code`, `error`, `outcome`, `url_before`, `url_after`) + `render()`.

### Changed Entities

- `LLMProvider.generate_step_code` — new inputs `step_type: str`, `attempt_history: list[str]`; removed `existing_code`, `error`, `guidance_history`.
- `LLMProvider.check_instruction_compliance` — new inputs `step_type: str`, `attempt_history: list[str]`.
- `LLMProvider::OpenAIProvider`, `LLMProvider::AnthropicProvider` — algorithm texts updated; the frozen parity now covers the STEP TYPE line and the HISTORY/ATTEMPT HISTORY blocks.
- `ComplianceFinding` — new field `dimension`; `instruction` re-purposed as "the verbatim quote the finding names" (violated instruction **or** step-sentence fragment).
- `parse_compliance_verdict` — validates `dimension` of {instruction, adequacy}; old shape malformed.
- `StepGenerator.generate` / `StepGenerator.regenerate` — honest inputs + history threading, URL brackets, record appends.
- `check_step_compliance` — two-dimension gate; renders the history into the verdict request.
- `StepHealer.heal` — gains `step_text`, `step_type`, `attempt_history`; classification and regeneration receive the raw sentence.
- `classify_step_failure` — annotation wording only (the raw sentence as passed by the calling engine); signature and behavior unchanged.
- `StepSteering.steer` — shared history, honest inputs, two-dimension gate, per-turn URL brackets.
- `StepExecutor.execute` — owns the per-step attempt history; seeds record 0; threads honest inputs.

### Deleted Entities

- None. Removed **inputs** (not entities): `existing_code`, `error`, `guidance_history` of `generate_step_code`; `existing_code`, `error` of `StepGenerator.regenerate`.

### Usages and Annotations Changes

- `prettyplay/engine` `Usages.compliance_prompt`: fully rewritten — two dimensions, STEP TYPE and ATTEMPT HISTORY inputs, `dimension` in the answer schema, dimension calibration, attempt-history-as-ground-truth rule.
- `.goga/usages/prompts/generation.md` (project practice `system_prompt`): input list gains STEP TYPE (first line) and HISTORY (replacing CODE/ERROR); new replayability rule. The frozen `SYSTEM_PROMPT` mirrors in `generator.py` and `steering.py` must be re-synced (build stage).
- Global annotation rules added: continuous per-step history; honest inputs; mechanical URL pairs; record-append rule; replayability-lands-in-`system_prompt`; the two-dimension gate rule (engine); honest-inputs threading (root); shared-history rules (steering).
- Cell-level `.usages/` files (`providers.md`, `generation.md`, `healing.md`, `steering.md`, `steps.md`) were already updated by the apply stage — verified consistent (see `.usages/` Update).

## Applied Fixes

### Fixed CODEMANIFEST Defects

- None. The four-dimension consistency audit (interface↔type, type↔mutation, interface↔interface, annotations↔entity) over all changed contracts found no defects; `goga lint` reports 10 cells / 0 errors. No CODEMANIFEST edits were made at this stage.

### Resolved Design Decisions (user-approved)

1. **Guarded URL reads** — a failed bracketing `page.url` read (dead page, driver failure) degrades to the empty string on that side of the pair; the attempt itself proceeds normally. Mirrors the steering `_guarded_url` precedent; consistent with `StepAttempt`'s empty defaults. A mechanical read must never kill an otherwise-green attempt.
2. **Uniform five-field records** — `StepAttempt` stays exactly {code, error, outcome, url_before, url_after} across generation, healing and steering. Prior-turn engineer guidance messages are **not** preserved in the history (the former dialog-local record carried them); the current turn's message rides the USER GUIDANCE block. Confirmed deliberate — no contract change.

## Entity Interaction and Data Flow

### Interaction Diagram

```
PrettyPlay.step(text) / expect(text)                     [scenario.py, root cell]
  └─ StepExecutor.execute(step_text, step_type, page)    [executor.py, root cell]
       │  owns attempt_history: list[StepAttempt]  (created here, dies with the step)
       │
       ├─ cache HIT, replay green ── settle(run_step_code, cached.code)  [URL bracket]
       │
       ├─ cache HIT, replay FAILS ── record 0 = StepAttempt(cached.code, replay error,
       │                                outcome=original cached code, replay URL pair)
       │                            └─ StepHealer.heal(step, error, step_text, step_type,
       │                                 previous_steps, page, attempt_history, window)
       │                                 ├─ classify_step_failure(raw step_text) ── LLMProvider.classify_failure
       │                                 └─ rot|fixable ─ StepGenerator.regenerate(…, attempt_history, …)
       │
       ├─ cache MISS (non-strict) ──── StepGenerator.generate(identity, step_text, step_type,
       │                                 previous_steps, page, attempt_history, window)
       │                                 loop:
       │                                   LLMProvider.generate_step_code(…, step_type,
       │                                       attempt_history=rendered records, …)
       │                                   url_before → settle(run_step_code) → url_after
       │                                   failed attempt → attempt_history.append(StepAttempt)
       │                                   green → check_step_compliance(config, provider,
       │                                       step_text, step_type, code, attempt_history)
       │                                            └─ LLMProvider.check_instruction_compliance(…,
       │                                                 step_type, code, rendered history)
       │                                            └─ parse_compliance_verdict → findings
       │
       └─ IncurableStepError (non-strict, interactive) ── StepSteering.steer(failure, identity,
                step_text, step_type, previous_steps, page, attempt_history)
                loop: LLMProvider.generate_step_code(…, step_type, rendered shared history, guidance)
                      url_before → run_step_code (bare) → url_after
                      rejected/failed/blocked turn → attempt_history.append(StepAttempt)
                      green → check_step_compliance(…, step_type, …, attempt_history) → write-back
```

### Data Flows

**Scenario A — cache miss (generation).**
`execute` creates `attempt_history = []` (step 2) → `generate` loops: snapshot + screenshot → provider request carrying `step_type`, raw `step_text`, `[r.render() for r in attempt_history]` → URL bracket → `settle(run_step_code)`:
- execution failure → append record (outcome `execution failed`, `format_step_error` text) → next iteration sees the grown history;
- failed check (AssertionError surviving the window) → append record (outcome `failed check`) → classification → decision table (terminal, or one funded regeneration carrying recommendation + grown history);
- green → gate; high finding of either dimension → append record (outcome `compliance blocked`, violation text in `error`) → retry with grown history; empty/medium/low → store `CachedStep`, return.
History dies with the step; only the `CachedStep` persists.

**Scenario B — failed cached hit (healing).**
`execute` brackets the replay with URL reads → on failure: `error_text = format_step_error`, record 0 = `StepAttempt(code=cached.code, error=error_text, outcome=original cached code, url_before, url_after)` appended → `heal(step, error_text, step_text, step_type, scenario, page, history, window)` → classification with the **raw** sentence → rot|fixable → `regenerate(identity, step_text, step_type, previous_steps, page, history, recommendation, window)` → the healing loop mirrors scenario A minus per-attempt classification; record 0 is never rebound.

**Scenario C — terminal failure, interactive steering.**
`IncurableStepError` caught in `execute` → interactive and non-strict → `steer(failure, identity, step_text, step_type, previous_steps, page, attempt_history)` — receives the history already grown by the engine loop (anchored by record 0 on the heal path). Each guidance turn: request with rendered shared history + USER GUIDANCE; engineer rejects → record (outcome `rejected by the engineer, not executed`, same URL both sides); approved → URL bracket around bare `run_step_code`; failure → record (`failed check`/`execution failed`); green → gate with the shared history; blocked → record (`compliance blocked`); passed → `CachedStep(identity)` write-back + `on_healed`, return healed → `execute` continues the step as a success.

### Entity Dependencies

Implementation order (bottom-up, mirrors the import graph): `prettyplay/llm` → `prettyplay/engine` (new `attempts.py` first, then generator/compliance/healer, then `__init__` facade export) → `prettyplay/engine/steering` → `prettyplay/executor.py` (root). `StepAttempt` is declared in `prettyplay/engine` and travels only along the pre-existing edges engine→steering and engine→root; zero new dependency edges. `PageFacade` needs no changes — `url` is an existing immediate-read property crossing the driver worker boundary.

## Code Stack Trace

All traces verified against the current implementation files; checkpoints marked **passed** introduce no CODEMANIFEST defect.

### Trace: `StepExecutor.execute`

#### Chain
1. **Input**: `PrettyPlay.step(text)`/`expect(text)` → `execute(step_text, step_text_type, page)`; `step_text` raw, `step_type` ∈ {action, assertion}.
2. Identity via `normalize_step_text` (addressing only), `SettleWindow` from polling settings; **`attempt_history: list[StepAttempt] = []`** created → checkpoint: history type matches `generate`/`heal`/`steer` signatures — **passed**.
3. Cache hit: `_read_url(page)` (guarded, empty string on failure) → `settle(run_step_code, cached.code, page, window)` → `_read_url(page)` → checkpoint: `PageFacade.url` exists, plain `str` crosses the worker boundary — **passed**. Strict miss → `IncurableStepError` (history unused — correct: nothing was attempted).
4. Hit failure: strict → `_strict_failure` classifies with the raw sentence (current code already passes the raw `step_text`; contract now pins it). Non-strict → `error_text = format_step_error(error)`; record 0 = `StepAttempt(code=cached.code, error=error_text, outcome=OUTCOME_ORIGINAL, url_before, url_after)` appended; `heal(cached, error_text, step_text, step_type, self._scenario, page, attempt_history, window)` → checkpoint: `heal` signature order matches the contract — **passed**.
5. Miss: `generate(identity, step_text, step_type, self._scenario, page, attempt_history, window)` → checkpoint: **passed**.
6. `IncurableStepError` from heal/generate → `_steer_or_raise(failure, identity, step_text, step_type, self._scenario, attempt_history, page)` → `steer(...)` receives the grown history → checkpoint: **passed**.
7. **Output**: success (scenario append, `on_step_passed`) or raise by kind; `on_step_finished` always fires once.

#### Checkpoint Summary
- History threading (create → seed → grow → steer): passed.
- Record 0 composed before the heal delegation — the original cached code can never be lost to a regeneration re-binding: passed.

### Trace: `StepGenerator.generate` (generation pool loop)

#### Chain
1. **Input**: executor step 5; `attempt_history` starts empty on this path.
2. `try_generation(identity)` refused → `_exhaustion_outcome` (see below). Granted → `attempt += 1`, `on_generation_started(step_text, attempt)`.
3. Snapshot (+ screenshot when enabled) → `_request` → `provider.generate_step_code(prompt=SYSTEM_PROMPT, user_instructions=config.generation_prompt, step_text=raw, step_type=step_type, previous_steps, snapshot, page_url=None, screenshot, cheat_sheet=CHEAT_SHEET, attempt_history=[r.render() for r in history], recommendation, guidance=None)` → checkpoint: rendered `list[str]` matches the port's `attempt_history: list[str]` — **passed**.
4. `url_before = _read_url(page)` → `settle(run_step_code, code, page, window)` (transient failures re-execute inside the window — the single pair covers them) → `url_after = _read_url(page)`.
5. AssertionError survived → append record (outcome `failed check`, error `str(check_failure)`); classify; decision table; funded regeneration carries recommendation + grown history (the failed-check record is already in it) → checkpoint: record precedes the funded request — **passed**.
6. Other exception → append record (outcome `execution failed`, error `format_step_error(exc)`); loop continues with the fresh snapshot + grown history.
7. Green → `check_step_compliance(config, provider, step_text, step_type, code, attempt_history)`; empty findings → `_store` → `CachedStep` (no record for a caching attempt — records exist only for attempts that produce no cached step); high finding of either dimension → append record (outcome `compliance blocked`, `_violation_text(finding)` in error) + `standing = finding`; retry. Medium/low → WARNING, store. Gate hard failures (`LLMUnavailableError`, `ComplianceVerdictError`) propagate uncached → checkpoint: **passed**.
8. Budget exhaustion with `standing` → `IncurableStepError` carrying the verdict built from the finding (category incurable; explanation `"{instruction} — {explanation}"`; recommendation `"satisfy the finding in the step code: {instruction}"`); reason `"generation attempt budget exhausted — {_reason_safe(instruction)}"` (colon-free, works for both dimensions — `instruction` holds the quote) → checkpoint: wording updated from "violated instruction" to dimension-neutral "the finding" per contract — **passed**.
9. **Output**: `CachedStep` or terminal raise by kind.

#### Checkpoint Summary
- Record-append points (execution failed / failed check / compliance blocked) match the closed outcome label set: passed.
- URL pair brackets the whole attempt including settle re-executions: passed.

### Trace: `StepGenerator.regenerate` (healing pool loop)

#### Chain
1. **Input**: healer step 5; `attempt_history` anchored by record 0. The loop's terminal-failure facts now derive from the history (`history[-1].code` / `history[-1].error`; empty-string fallback when somehow empty) — the signature no longer carries `existing_code`/`error` → checkpoint: no orphaned locals — **passed**.
2. `try_healing` refused → `IncurableStepError(step_text, "healing attempt budget exhausted", last_error, code=last_code)` — the healer attaches its entry verdict; no extra LLM request.
3. Request mirrors `generate` plus `recommendation`; URL bracket; settle; any failure (checks included) → append record (`failed check` for AssertionError, `execution failed` otherwise) → retry with grown history; no per-attempt classification (entry classification guards anti-masking).
4. Green → gate with the same two-dimension semantics; blocked → append `compliance blocked` record → retry.
5. **Output**: `CachedStep` or `IncurableStepError` (no standing-finding variant on this path — the healer's entry verdict is carried, per contract step 2).

#### Checkpoint Summary
- Record 0 never rebound: append-only access — passed.
- Healer contract step 5 ("the request carries the raw `step_text`, `step_type`, the classification recommendation and the anchored `attempt_history`") matches: passed.

### Trace: `check_step_compliance`

#### Chain
1. **Input**: `(config, provider, step_text, step_type, code, attempt_history)`; callers — generator loops, `_funded_regeneration`, steering step 7.
2. `generation_approve` off or `generation_prompt` empty → `[]`, zero provider calls (unchanged).
3. `provider.check_instruction_compliance(prompt=COMPLIANCE_PROMPT, user_instructions=config.generation_prompt, step_text, step_type, code, attempt_history=[r.render() for r in attempt_history])` → checkpoint: port input types match — **passed**.
4. **Output**: `list[ComplianceFinding]` (each with `dimension`); hard failures propagate untouched.

#### Checkpoint Summary
- The rendered history reaches the verdict request as the ATTEMPT HISTORY block: passed.
- `COMPLIANCE_PROMPT` must equal the rewritten `compliance_prompt` practice byte-for-byte (frozen mirror — build-stage sync, verified by test).

### Trace: `StepHealer.heal`

#### Chain
1. **Input**: `(step, error, step_text, step_type, previous_steps, page, attempt_history, window)`; record 0 already seeded by the executor.
2. `classify_step_failure(config, provider, step_text, step.code, error, page)` with the **raw** sentence — behavior change: the current implementation derives `step.identity.normalized_text`; the contract pins the raw sentence → checkpoint: signature unchanged, input semantics pinned — **passed**.
3. `on_healing_started`; product_defect → `ProductDefectError`; incurable → `IncurableStepError` (unchanged table).
4. rot|fixable → `generator.regenerate(identity=step.identity, step_text=step_text, step_type=step_type, previous_steps, page, attempt_history, recommendation=classification.recommendation, window)`; inner `IncurableStepError` → re-raise with the entry verdict (`raise … from inner`).
5. **Output**: healed `CachedStep` (`on_healed`) or terminal raise.

#### Checkpoint Summary
- The anchored history is threaded, not copied — dialog/loop appends remain visible to the caller: passed.

### Trace: `StepSteering.steer`

#### Chain
1. **Input**: `(failure, identity, step_text, step_type, previous_steps, page, attempt_history)` — the shared history from the executor.
2. Banner once: step sentence (the `step_text` parameter), failed code, terminal render, guarded URL, screenshot path, commands — unchanged presentation.
3. Guidance loop: local commands without LLM; a message builds `provider.generate_step_code(prompt=SYSTEM_PROMPT, user_instructions, step_text=step_text, step_type=step_type, previous_steps, snapshot, page_url=_guarded_url(page), screenshot, cheat_sheet=CHEAT_SHEET, attempt_history=[r.render() for r in attempt_history], recommendation=None, guidance=message)` — record 0 anchors the original failure; the CODE/ERROR inputs and the dialog-local `guidance_history` are gone → checkpoint: port signature match — **passed**.
4. `run? [y/N]`: not approved → append `StepAttempt(code, error="", outcome=OUTCOME_REJECTED, url_before=u, url_after=u)` where `u = _guarded_url(page)` read once — same URL both sides → checkpoint: contract step 5 — **passed**.
5. Approved → `url_before = _guarded_url(page)` → bare `run_step_code(code, page)` (no settle — the window never re-arms) → `url_after = _guarded_url(page)`. Exception → print, append record (`failed check` for AssertionError else `execution failed`, error = full outcome text) → prompt reopens.
6. Green → `check_step_compliance(config, provider, step_text, step_type, code, attempt_history)` — the gate sees prior records (this turn's record lands only on a block). Hard gate failure → line + WARNING → `return None`. High finding of either dimension → print violation, append record (`compliance blocked`) → prompt reopens. Medium/low → WARNING → `_write_back` (CachedStep(identity), save, `on_healed`) → return healed.
7. Provider unavailability of the request → dialog ends, `return None`; `LLMUnavailableError` never escapes the dialog.
8. **Output**: healed `CachedStep` or `None` (the executor propagates the original failure).

#### Checkpoint Summary
- A rejected, failed or gate-blocked turn always enters the shared history before the prompt reopens: passed.
- No budget consumed, no polling, guidance never persisted: passed (unchanged).

### Trace: `StepAttempt.render`

#### Chain
1. **Input**: the model instance (five fields).
2. Line 1 — the outcome label verbatim; line 2 — `"url: {url_before} -> {url_after}"`; part 3 — `"code:\n{code}"`; part 4 (only when `error` non-empty) — `"error:\n{error}"`; parts joined with newlines → checkpoint: every field complete and verbatim, no truncation — **passed**.
3. **Output**: the multi-line record text — the unit joined into the provider HISTORY block (`"\n".join(records)`) and the gate ATTEMPT HISTORY block.

### Trace: `parse_compliance_verdict`

#### Chain
1. **Input**: raw verdict text.
2. Trimmed `json.loads` → must be a `list` of `dict`s; each item: `instruction`, `priority` ∈ {high, medium, low}, `explanation`, `dimension` ∈ {instruction, adequacy} — all strings; any miss (including an old-shaped finding without `dimension`) → `_malformed` → `ComplianceVerdictError` carrying a 200-char collapsed fragment → checkpoint: old shape fails loudly, never a silent pass — **passed**.
3. **Output**: `list[ComplianceFinding]`; empty list — compliant and adequate.

### Trace: `LLMProvider.generate_step_code` / providers

#### Chain
1. **Input**: port signature `(prompt, user_instructions, step_text, step_type, previous_steps, snapshot, page_url, screenshot, cheat_sheet, attempt_history, recommendation, guidance)`.
2. `build_fields_text` (shared by both providers): scenario part = `STEP TYPE: {step_type}` line directly above the `STEP:` block, PREVIOUS STEPS, PAGE SNAPSHOT, optional `PAGE URL: {url}` line; then CHEAT SHEET; then optional USER INSTRUCTIONS; then optional `HISTORY:\n{records joined by newlines}`; then optional RECOMMENDATION; then optional USER GUIDANCE → checkpoint: block order = contract requirement (CHEAT SHEET, user instructions, HISTORY, RECOMMENDATION, USER GUIDANCE; PAGE URL after PAGE SNAPSHOT; STEP TYPE before STEP) — **passed**.
3. One SDK request (openai `chat.completions.create` / anthropic `messages.create`); generation answer unwraps the first fenced block; SDK error → `LLMUnavailableError`.
4. **Output**: `code: str` (identical semantics in both providers — parity).

### Trace: `LLMProvider.check_instruction_compliance` / providers

#### Chain
1. **Input**: `(prompt, user_instructions, step_text, step_type, code, attempt_history)`.
2. `build_compliance_fields`: `INSTRUCTIONS:` block, `STEP TYPE: {step_type}` line directly above the `STEP:` block, optional `ATTEMPT HISTORY:\n{records}` (empty history — no block), `CODE:` block → checkpoint: four-block fixed order with the STEP TYPE line — **passed**.
3. One request via the **effective generation model**; answer → `parse_compliance_verdict` (no fence unwrapping); malformed (old shape included) → `ComplianceVerdictError`; SDK error → `LLMUnavailableError`.
4. **Output**: `list[ComplianceFinding]`.

### Trace: `classify_step_failure`

Unchanged mechanics (snapshot + screenshot + provider `classify_failure` with `classification_prompt` as system prompt and `classification_prompt` setting as USER INSTRUCTIONS, placed last). The **raw** step sentence flows in from all calling paths (executor strict path already raw; heal now raw; generator paths already raw). No STEP TYPE line on classification requests — the llm header pins STEP TYPE to generation and verdict requests only — **passed**.

## Algorithm Design

### `StepAttempt` (new — `prettyplay/engine/attempts.py`)

**Responsibility**: one immutable verbatim record of the per-step attempt history; the unit the provider HISTORY block and the gate ATTEMPT HISTORY block render.

**Model**:
```python
OUTCOME_ORIGINAL = "original cached code"
OUTCOME_FAILED_CHECK = "failed check"
OUTCOME_EXECUTION_FAILED = "execution failed"
OUTCOME_COMPLIANCE_BLOCKED = "compliance blocked"
OUTCOME_REJECTED = "rejected by the engineer, not executed"

class StepAttempt(BaseModel):
    model_config = ConfigDict(kw_only=True, frozen=True)   # immutable once appended
    code: str = ""
    error: str = ""
    outcome: str = ""                                       # closed set via the constants above
    url_before: str = ""
    url_after: str = ""
```
- pydantic v2, `kw_only`, empty defaults (conventions); `frozen=True` realizes "a record is immutable once appended: no rewriting, no truncation".
- The outcome labels are the five contract labels verbatim, exposed as module constants; every construction site uses a constant (closed-set discipline, uniform with `ComplianceFinding` whose labels are validated one step before construction).

**`render() -> record: str`** — pinned format:
```
{outcome}
url: {url_before} -> {url_after}
code:
{code}
error:
{error}
```
The `error:` part is omitted entirely when `error` is empty. No collapsing, no size limits, no truncation of any field; the `code:`/`error:` markers separate the two free-text parts (the contract calls them parts).

**Errors**: none (pure data + rendering).

**Edge cases**:
- empty `error` → record without the error part;
- empty URLs (guarded read failed) → `url:  -> ` — the pair stays visible, truthfully empty.

### Guarded URL read (`_read_url` / `_guarded_url` — per cell, private)

**Responsibility**: the mechanical bracketing read; never fails an attempt (resolved decision 1).

```python
def _read_url(page: PageFacade) -> str:   # engine: attempts.py or generator.py; root: executor.py
    try:
        return page.url
    except Exception:
        return ""                          # a dead page never kills the attempt; the pair degrades honestly
```
The steering cell keeps its existing `_guarded_url` (returns `str | None` for the request input) and reuses it for the brackets (None → ""). Three tiny cell-local helpers rather than a new cross-cell export — the contracts declare no shared routine.

### `StepGenerator` (changed)

**Responsibility**: the generation/healing loops, now growing the per-step attempt history and carrying honest inputs.

**Algorithm** (`generate` pool):
```
1. history = attempt_history (owned by the executor)
2. LOOP:
   a. IF NOT budgets.try_generation(identity): → _exhaustion_outcome
   b. attempt += 1; report on_generation_started(step_text, attempt)
   c. snapshot (+screenshot); code = provider.generate_step_code(
        SYSTEM_PROMPT, config.generation_prompt, step_text, step_type,
        previous_steps, snapshot, page_url=None, screenshot, CHEAT_SHEET,
        attempt_history=[r.render() for r in history], recommendation, guidance=None)
   d. url_before = _read_url(page)
      settle(run_step_code, code, page, window)          # one pair covers settle re-executions
      url_after = _read_url(page)
   e. IF AssertionError:
        history.append(StepAttempt(code, str(exc), OUTCOME_FAILED_CHECK, url_before, url_after))
        → _failed_check_outcome (classify → decision table; funded regeneration carries
          recommendation + the grown history; its own failed attempt appends its record too)
   f. ELIF other Exception:
        history.append(StepAttempt(code, format_step_error(exc), OUTCOME_EXECUTION_FAILED, url_before, url_after))
        standing = None; continue
   g. ELSE (green):
        findings = check_step_compliance(config, provider, step_text, step_type, code, history)
        high = first finding with priority == "high"      # either dimension blocks
        IF high:
          history.append(StepAttempt(code, _violation_text(high), OUTCOME_COMPLIANCE_BLOCKED, url_before, url_after))
          standing = high; continue
        IF findings: WARNING (medium/low, dimension-aware)
        return _store(identity, code)
```
**`regenerate` (healing pool)**: same loop shape with `try_healing`, `recommendation` on every request, every failure (checks included) appending its record and retrying, no per-attempt classification, no standing state; exhaustion raises `IncurableStepError(step_text, "healing attempt budget exhausted", last_record.error, code=last_record.code)` with the last facts derived from `history[-1]` (empty-string fallback when the history is empty).

**`_violation_text(finding)`** (dimension-aware, rides the record's error field):
`f"{finding.dimension} violation: {finding.instruction} — {finding.explanation}"`
(e.g. `instruction violation: Prefer id attributes — locates by text` / `adequacy violation: click the «Sign in» button — code only checks an already-achieved state`).

**Exhaustion with a standing finding** (wording updated to the contract's dimension-neutral text):
- verdict: `FailureVerdict(category="incurable", explanation=f"{finding.instruction} — {finding.explanation}", recommendation=f"satisfy the finding in the step code: {finding.instruction}")`
- reason: `f"generation attempt budget exhausted — {_reason_safe(finding.instruction)}"` (colon-free)
- error field: `_violation_text(finding)`

**Errors**: unchanged taxonomy — `LLMUnavailableError` (request: immediate; classification: quiet WARNING skip), `ComplianceVerdictError` (propagates, nothing cached), `ProductDefectError`/`IncurableStepError` per the decision table.

**Edge cases**:
- empty history (first attempt) → no HISTORY block;
- URL read failure → empty side(s), attempt proceeds (decision 1);
- a green attempt never appends a record (records exist only for attempts producing no cached step).

### `check_step_compliance` (changed)

**Responsibility**: the single two-dimension gate of every caching path.

**Algorithm**:
```
1. IF NOT config.generation_approve OR NOT config.generation_prompt: return []   # zero calls
2. return provider.check_instruction_compliance(
     prompt=COMPLIANCE_PROMPT,                     # frozen mirror of the compliance_prompt practice
     user_instructions=config.generation_prompt,
     step_text=step_text, step_type=step_type, code=code,
     attempt_history=[r.render() for r in attempt_history])
```
**Errors**: `LLMUnavailableError`/`ComplianceVerdictError` propagate — never swallowed, never cached.
**Edge cases**: gate off / empty instructions → fully the old behavior; empty history → no ATTEMPT HISTORY block in the request.

### `StepHealer.heal` (changed)

**Algorithm**:
```
1. classification = classify_step_failure(config, provider, step_text, step.code, error, page)
   # step_text is the RAW sentence parameter — never identity.normalized_text again
2. report on_healing_started(category)
3. product_defect → ProductDefectError(verdict, error)
4. incurable      → IncurableStepError(verdict, error, code=step.code)
5. rot|fixable    → generator.regenerate(identity=step.identity, step_text, step_type,
                      previous_steps, page, attempt_history, recommendation, window)
   inner IncurableStepError → re-raise carrying THIS classification's verdict, from inner
6. report on_healed; return healed
```
**Edge cases**: record 0 already seeded by the executor — `heal` never re-seeds; the history object is threaded (mutations by `regenerate` remain visible to the executor for the steering intercept).

### `StepSteering.steer` (changed)

**Algorithm**:
```
1. banner once (step sentence from the step_text parameter, failure.code, str(failure),
   guarded URL, screenshot path, commands)
2. LOOP:
   a. read guidance; quit/EOF/SIGINT/unreadable stdin → return None
   b. local command (snapshot|screenshot|error|code) → serve, re-prompt
   c. code = provider.generate_step_code(SYSTEM_PROMPT, config.generation_prompt, step_text,
        step_type, previous_steps, snapshot, page_url=_guarded_url(page), screenshot,
        CHEAT_SHEET, attempt_history=[r.render() for r in history], recommendation=None,
        guidance=message)
      LLMUnavailableError → print, return None
   d. show code; run? [y/N]:
      NOT approved → u = _guarded_url(page) or ""
                     history.append(StepAttempt(code, "", OUTCOME_REJECTED, u, u)); continue
   e. url_before = _guarded_url(page) or ""
      run_step_code(code, page)                  # bare — the window never re-arms
      url_after  = _guarded_url(page) or ""
      Exception → print; history.append(StepAttempt(code, outcome_text, full outcome,
                    url_before, url_after))       # failed check | execution failed; continue
   f. findings = check_step_compliance(config, provider, step_text, step_type, code, history)
      hard failure → print + WARNING → return None
      high (either dimension) → print violation;
                    history.append(StepAttempt(code, _violation_text(high),
                    OUTCOME_COMPLIANCE_BLOCKED, url_before, url_after)); continue
      medium/low → WARNING
   g. write-back: CachedStep(identity, code); save; on_healed; return step
```
The old `_turn_record` helper and the dialog-local `history: list[str]` are deleted.

**Edge cases**: rejected turn — same URL both sides; the gate sees the history without the current turn's record (the candidate rides the CODE block); the dialog never outlives the failure (every exit heals or returns None).

### `StepExecutor.execute` (changed)

**Algorithm** (delta only):
```
step 2: attempt_history: list[StepAttempt] = []
step 3: hit → url_before = _read_url(page); settle(run_step_code, cached.code, page, window);
        url_after = _read_url(page)
step 4: hit failure, non-strict →
          error_text = format_step_error(error)
          attempt_history.append(StepAttempt(code=cached.code, error=error_text,
                                 outcome=OUTCOME_ORIGINAL, url_before=url_before, url_after=url_after))
          healer.heal(cached, error_text, step_text, step_type, self._scenario, page,
                      attempt_history, window)
step 5: miss → generator.generate(identity, step_text, step_type, self._scenario, page,
                      attempt_history, window)
step 6: IncurableStepError → _steer_or_raise(failure, identity, step_text, step_type,
                      self._scenario, attempt_history, page)
```
The strict path is untouched except the (already raw) sentence into classification. `step`, `expect`, `run_on_page`, hooks, renders, `on_step_finished` — unchanged.

### LLM port + providers (changed)

- `provider.py`: port method signatures updated (docstrings per contract); `create_provider` untouched.
- `_request.py`:
  - `build_fields_text(user_instructions, step_text, step_type, previous_steps, snapshot, page_url, cheat_sheet, attempt_history, recommendation, guidance)` — scenario part opens with the `STEP TYPE: {step_type}` line directly above the `STEP:` block; optional `PAGE URL:` line after PAGE SNAPSHOT; CHEAT SHEET; optional USER INSTRUCTIONS; optional `HISTORY:\n` + records joined by `\n`; optional RECOMMENDATION; optional USER GUIDANCE. Sections joined by `\n\n`.
  - `build_compliance_fields(user_instructions, step_text, step_type, attempt_history, code)` — `INSTRUCTIONS:` block; `STEP TYPE: {step_type}` line directly above the `STEP:` block; `ATTEMPT HISTORY:\n` + records (omitted when the list is empty); `CODE:` block.
  - `build_classification_fields` — unchanged.
- `models.py`: `ComplianceFinding` gains `dimension: str = ""`; `COMPLIANCE_DIMENSIONS = frozenset({"instruction", "adequacy"})`; `parse_compliance_verdict` validates it (non-str or unknown label → `_malformed`); the `_malformed` message becomes `…expected a JSON list of findings with instruction, priority high|medium|low, explanation and dimension instruction|adequacy; received fragment: …`.
- `openai_provider.py` / `anthropic_provider.py`: signatures updated, field builders called with the new inputs, compliance operation passes `step_type` + `attempt_history` through the effective generation model → `parse_compliance_verdict`. Parity absolute; classification untouched.

## Cross-cutting Concerns

- **Error handling**: taxonomy unchanged (`LLMUnavailableError`, `ComplianceVerdictError`, `ProductDefectError`, `IncurableStepError`); the gate hard failures never cache; quiet verdict skips (WARNING) unchanged; **new**: bracketing URL reads are guarded — degrade to `""`, never fail an attempt (decision 1).
- **Logging**: existing logger `prettyplay` and event names; medium/low findings WARNING now renders the dimension: `f"{finding.priority} {finding.dimension}: {finding.instruction} — {finding.explanation}"`; steering events unchanged; no secrets in logs.
- **Validation**: `parse_compliance_verdict` validates the dimension set loudly (old shape malformed); `StepAttempt` outcome labels are the closed constant set (construction discipline, uniform with `ComplianceFinding`); step addressing (normalize_step_text) untouched by any new input.
- **Caching**: none added; the attempt history is per-step in-memory only, never persisted (the steering constraint "never persist the guidance" generalizes: no record ever reaches the cache file).
- **Concurrency**: no change — every page interaction (URL reads included) crosses the driver worker boundary through `PageFacade` primitives, sequentially with steps; no shared mutable state across threads (the history list is confined to the executor's call tree).

## Usages Analysis

### `conventions`
- **What it provides**: Python code/test conventions (relative imports, pydantic kw_only + empty defaults, Google docstrings, logging, test structure mirroring).
- **Where used**: every changed cell's global annotations.
- **Why chosen**: project-wide binding standard.
- **How exactly**: `StepAttempt`/`ComplianceFinding` follow the pydantic rules; new tests mirror `tests/<pkg>/test_<module>.py`; `from .attempts import StepAttempt` relative imports.

### `system_prompt` (`.goga/usages/prompts/generation.md`)
- **What it provides**: the generation system prompt — now with STEP TYPE + HISTORY inputs and the replayability rule.
- **Where used**: `StepGenerator` (engine), `StepSteering` (steering) as the frozen `SYSTEM_PROMPT` mirrors.
- **Why chosen**: single source of the prompt; mirrors change only together with the file.
- **How exactly**: the section after `---` is mirrored byte-for-byte in `generator.py` and `steering.py` (cell-owned local copies; no runtime read of `.goga/`).

### `cheat_sheet` (`.goga/usages/prompts/cheatsheet.md`)
- **What it provides**: the compact Playwright sync API reference.
- **Where used**: every generation/regeneration/guided request (CHEAT SHEET block).
- **Why chosen / how exactly**: unchanged — whole-file frozen mirrors in `generator.py` and `steering.py`.

### `classification_prompt` / `compliance_prompt` (inline, engine header)
- **What they provide**: the classification and two-dimension compliance system prompts.
- **Where used**: `classify_step_failure` (`classification.py` frozen mirror), `check_step_compliance` (`COMPLIANCE_PROMPT` frozen mirror — **must be re-synced** to the rewritten practice).
- **Why chosen**: inline practices local to the engine cell; the frozen-mirror rule keeps prompt and constant in lockstep.
- **How exactly**: byte-equal mirrors; `test_compliance_prompt_is_a_frozen_constant` extended to the new text anchors.

### `openai` / `anthropic` (`.goga/usages/cooks/*.md`)
- **What they provide**: SDK call patterns and error mapping.
- **Where used**: the two provider implementations.
- **Why chosen / how exactly**: unchanged — one request per operation, SDK errors → `LLMUnavailableError`.

### Imported Usages
- `classification` from `prettyplay/llm` — the healing decision categories; path `prettyplay/llm/.usages/classification.md`; referenced by the engine global annotations (`Use \`classification\` from Imports for the healing decision categories`). Unchanged this round.
- `taxonomy`, `hooks`, `generation`, `healing` imported by the root cell — unchanged; `generation`/`healing` describe the cycles the executor delegates to (already updated by the apply stage).

## `.usages/` Update

### Cell: `prettyplay/llm`
#### Existing Files — Consistency
- **`providers.md`** → `prettyplay/llm/.usages/providers.md` — Status: **current** (updated by the apply stage; step-type and attempt-history parity, HISTORY tail order, dimension verdict format verified). Additions/Updates needed: none.
- **`classification.md`** — untouched by design (classification contract unchanged).

### Cell: `prettyplay/engine`
#### Existing Files — Consistency
- **`generation.md`** — Status: **current** (attempt history, honest inputs, two-dimension gate, URL brackets, bounded healing with grown history all present). Additions/Updates needed: none.
- **`healing.md`** — Status: **current** (anchored history, raw sentence threading verified). Additions/Updates needed: none.

### Cell: `prettyplay/engine/steering`
#### Existing Files — Consistency
- **`steering.md`** — Status: **current** (shared history, rejected-turn record, two-dimension gate verified). Additions/Updates needed: none.

### Cell: `prettyplay` (root)
#### Existing Files — Consistency
- **`steps.md`** — Status: **current** (honest step context section, addressing note verified). Additions/Updates needed: none.
- **`lifecycle.md`** — untouched by design (no lifecycle change).

#### New Files
- None — no new consumer-facing functional domain; the attempt history is internal (steps.md already documents it at the author level).

## Test Stack Trace

### General Setup

- Existing idioms: `StubProvider`/`ComplianceStubProvider` classes record provider kwargs; `FakePage` (engine tests) fakes the facade with recorded calls; provider tests stub the SDK clients; conventions: `tests/<pkg>/test_<module>.py`, `Test<Component>` classes, `test_<what>_<scenario>` names.
- `FakePage` gains a `url` property (returns a scripted value or raises) for the URL-bracket tests; the engine/root stub providers' `generate_step_code`/`check_instruction_compliance` record the new kwargs (`step_type`, `attempt_history`) and drop the removed ones.
- Frozen-mirror tests extract the practice text (generation.md after `---`; the `compliance_prompt` block from the engine CODEMANIFEST) and compare byte-for-byte.

### Source File Registry

New: `prettyplay/engine/attempts.py`, `tests/engine/test_attempts.py`.
Changed: `prettyplay/llm/{models,_request,provider,openai_provider,anthropic_provider}.py`; `prettyplay/engine/{generator,compliance,healer,classification,__init__}.py`; `prettyplay/engine/steering/steering.py`; `prettyplay/executor.py`; the matching test files `tests/llm/test_{models,request,provider,openai_provider,anthropic_provider}.py`, `tests/engine/test_{generator,compliance,healer}.py`, `tests/engine/steering/test_steering.py`, `tests/test_executor.py`.

---

### Positive Tests

#### `test_render_renders_every_field_verbatim`

**Setup**: none (pure model).

**Input**: `StepAttempt(code="def step(page) -> None:\n    page.goto('https://a.example')\n", error="TimeoutError: click timed out", outcome=OUTCOME_EXECUTION_FAILED, url_before="https://a.example", url_after="https://b.example")`

**Trace**:
```
attempt.render()
  → outcome line: "execution failed"
  → url line: "url: https://a.example -> https://b.example"
  → code part: "code:\n" + the two-line code, untouched
  → error part: "error:\nTimeoutError: click timed out"
  → join with newlines
```

**Assertions**:
```
record == "execution failed\nurl: https://a.example -> https://b.example\ncode:\ndef step(page) -> None:\n    page.goto('https://a.example')\nerror:\nTimeoutError: click timed out"
```

**Sufficiency**: pins the record format every HISTORY/ATTEMPT HISTORY block renders; a format drift silently changes every LLM request — this regression test locks the contract's render algorithm.

---

#### `test_parse_compliance_verdict_accepts_both_dimensions`

**Setup**: none.

**Input**: `'[{"instruction": "Prefer id attributes", "priority": "high", "explanation": "locates by text", "dimension": "instruction"}, {"instruction": "click the «Sign in» button", "priority": "low", "explanation": "only checks state", "dimension": "adequacy"}]'`

**Trace**:
```
parse_compliance_verdict(text)
  → json.loads → list of 2 dicts
  → item 1: dimension "instruction" ∈ COMPLIANCE_DIMENSIONS → ComplianceFinding(...)
  → item 2: dimension "adequacy" ∈ COMPLIANCE_DIMENSIONS → ComplianceFinding(...)
```

**Assertions**:
```
len(findings) == 2
findings[0].dimension == "instruction" and findings[0].priority == "high"
findings[1].dimension == "adequacy" and findings[1].priority == "low"
```

**Sufficiency**: the two-dimension verdict must parse both label kinds — the gate's blocking logic depends on finding objects carrying a valid dimension.

---

#### `test_build_fields_text_renders_step_type_line_directly_above_step`

**Setup**: none (pure builder).

**Input**: `build_fields_text(user_instructions="Prefer id attributes", step_text="open the page", step_type="assertion", previous_steps=[], snapshot="- snap", page_url=None, cheat_sheet="# sheet", attempt_history=[], recommendation=None, guidance=None)`

**Trace**:
```
build_fields_text(...)
  → sections: "STEP TYPE: assertion\nSTEP:\nopen the page"   (the STEP TYPE line rides inside
    the scenario section — immediately before the STEP line, no blank line between),
    "PREVIOUS STEPS:\n(none)",
    "PAGE SNAPSHOT:\n- snap", "CHEAT SHEET:\n# sheet", "USER INSTRUCTIONS:\nPrefer id attributes"
  → "\n\n".join(sections)
```

**Assertions**:
```
text.startswith("STEP TYPE: assertion\nSTEP:\nopen the page")
"PAGE URL" not in text          # None URL — no line
"HISTORY" not in text           # empty history — no block
"RECOMMENDATION" not in text and "USER GUIDANCE" not in text
```

**Sufficiency**: the STEP TYPE line placement ("immediately before the STEP line") and the a-non-empty-input-renders-its-block rule are parity requirements of both providers — a drift breaks the honest-inputs contract.

---

#### `test_build_fields_text_renders_history_between_instructions_and_recommendation`

**Setup**: one rendered record string `"execution failed\nurl: https://a.example -> https://b.example\ncode:\n...\nerror:\nboom"`.

**Input**: `build_fields_text(..., user_instructions="Prefer id", attempt_history=[record], recommendation="use role locators", guidance="focus on the button")`

**Trace**:
```
build_fields_text(...)
  → HISTORY section: "HISTORY:\n" + record
  → order: ... CHEAT SHEET, USER INSTRUCTIONS, HISTORY, RECOMMENDATION, USER GUIDANCE
```

**Assertions**:
```
index("USER INSTRUCTIONS:") < index("HISTORY:") < index("RECOMMENDATION:") < index("USER GUIDANCE:")
"HISTORY:\nexecution failed\nurl: https://a.example -> https://b.example" in text
```

**Sufficiency**: pins the fixed regeneration tail order (HISTORY, RECOMMENDATION, USER GUIDANCE) — the single most load-bearing layout change of the port.

---

#### `test_build_compliance_fields_renders_four_blocks_with_step_type_line`

**Setup**: one record string.

**Input**: `build_compliance_fields("Prefer id attributes", "the «Welcome back» message appears", "assertion", [record], code)`

**Trace**:
```
build_compliance_fields(...)
  → "INSTRUCTIONS:\n...", "STEP TYPE: assertion\nSTEP:\n...", "ATTEMPT HISTORY:\n"+record, "CODE:\n"+code
```

**Assertions**:
```
text.index("INSTRUCTIONS:") < text.index("STEP TYPE:") < text.index("STEP:") < text.index("ATTEMPT HISTORY:") < text.index("CODE:")
text.startswith("INSTRUCTIONS:")
"STEP TYPE: assertion\nSTEP:" in text
```

**Sufficiency**: the verdict request's fixed four-block order with the STEP TYPE line — the gate prompt instructs the reviewer by these very block names.

---

#### `test_check_step_compliance_passes_step_type_and_rendered_history`

**Setup**: `ComplianceStubProvider` recording kwargs; `Config(generation_prompt="Prefer id attributes")`; two `StepAttempt` records (record 0 original + one failed check).

**Input**: `check_step_compliance(config, provider, "click the «Sign in» button", "action", code, [record0, record1])`

**Trace**:
```
check_step_compliance(...)
  → switch on, instructions non-empty
  → provider.check_instruction_compliance(prompt=COMPLIANCE_PROMPT, user_instructions="Prefer id attributes",
      step_text="click the «Sign in» button", step_type="action", code=code,
      attempt_history=[record0.render(), record1.render()])
```

**Assertions**:
```
call["step_type"] == "action"
call["attempt_history"] == [record0.render(), record1.render()]
call["prompt"] == COMPLIANCE_PROMPT
```

**Sufficiency**: the gate is the single bridge between engine records and the port — a missing render or a wrong type silently strips the adequacy dimension's ground truth.

---

#### `test_generate_appends_execution_failed_record_and_retries_with_grown_history`

**Setup**: `StubProvider(answers=[bad_code, good_code], compliance_verdicts=[[]])`; `FakePage` with `url` cycling `"https://a.example"`/`"https://b.example"`; `RunBudgets` with room; tmp_path cache.

**Input**: `generator.generate(identity, "open the videos page", "action", [], page, history=[], window)` where `bad_code` raises `RuntimeError("boom")` on execution.

**Trace**:
```
generate(...)
  attempt 1: request (attempt_history=[]) → bad_code
    url bracket → settle raises RuntimeError
    → history.append(StepAttempt(bad_code, "RuntimeError: boom", OUTCOME_EXECUTION_FAILED, a, b))
  attempt 2: request (attempt_history=[rendered record]) → good_code
    url bracket → settle green → gate returns []
  → _store → CachedStep
```

**Assertions**:
```
provider.calls[0]["attempt_history"] == []
provider.calls[1]["attempt_history"] == [history[0].render()]
history[0].outcome == OUTCOME_EXECUTION_FAILED
history[0].error == "RuntimeError: boom" and history[0].code == bad_code
len(history) == 1                     # the green attempt never records
```

**Sufficiency**: the core mechanic — a failed attempt lands as a verbatim record and the retry request carries it; without it the model re-proposes blind.

---

#### `test_generate_appends_compliance_blocked_record_on_high_adequacy_finding`

**Setup**: `StubProvider(answers=[code_checking_only], compliance_verdicts=[[ComplianceFinding(instruction="click the «Sign in» button", priority="high", explanation="code only checks an already-achieved state", dimension="adequacy")], []])`; second answer green+compliant.

**Input**: `generate(identity, "click the «Sign in» button", "action", [], page, [], window)`

**Trace**:
```
attempt 1: green execution → gate → high adequacy finding
  → history.append(StepAttempt(code, "adequacy violation: click the «Sign in» button — ...",
        OUTCOME_COMPLIANCE_BLOCKED, url_before, url_after)); standing = finding
attempt 2: request carries the grown history → green → gate [] → store
```

**Assertions**:
```
history[0].outcome == OUTCOME_COMPLIANCE_BLOCKED
history[0].error.startswith("adequacy violation: click the «Sign in» button")
provider.calls[1]["attempt_history"] == [history[0].render()]
```

**Sufficiency**: an adequacy high finding must block exactly like an instruction finding, with the violation text riding the record's error field — the anti-already-achieved-state guarantee of the whole feature.

---

#### `test_regenerate_never_loses_record_zero_through_retries`

**Setup**: `StubProvider(answers=[failing, green])`; anchored `history = [StepAttempt(code=cached_code, error="old rot", outcome=OUTCOME_ORIGINAL, ...)]`.

**Input**: `generator.regenerate(identity, "click the «Sign in» button", "action", [], page, history, "use role locators", window)`

**Trace**:
```
attempt 1: request carries [record0.render()] → candidate fails
  → history.append(record1)                     # record 0 untouched at index 0
attempt 2: request carries [record0.render(), record1.render()] → green → gate → store
```

**Assertions**:
```
history[0].code == cached_code and history[0].outcome == OUTCOME_ORIGINAL
provider.calls[0]["attempt_history"] == [history[0].render()]
provider.calls[1]["attempt_history"] == [history[0].render(), history[1].render()]
```

**Sufficiency**: the anchoring requirement — a regeneration must never lose the original cached code the engineer guidance and the classification refer to.

---

#### `test_heal_passes_raw_sentence_and_anchored_history_into_regenerate`

**Setup**: `StubProvider` scripted with a rot classification; `StepHealer` wrapping the generator; anchored history with record 0.

**Input**: `healer.heal(cached_step, error_text, "Click the «Sign IN» button", "action", [], page, history, window)` (note the non-normalized casing).

**Trace**:
```
heal(...)
  → classify_step_failure(..., step_text="Click the «Sign IN» button", ...)   # raw, not normalized_text
  → rot → generator.regenerate(..., step_text="Click the «Sign IN» button", step_type="action",
      attempt_history=history, recommendation="use role locators", ...)
```

**Assertions**:
```
provider.classify_failure_calls[0]["step_text"] == "Click the «Sign IN» button"
generator received the same raw sentence (recorded by the stub)
history object passed by reference — record 0 intact
```

**Sufficiency**: the heal path previously derived the normalized sentence; the honest-inputs contract requires the raw sentence in classification and every regeneration request.

---

#### `test_execute_seeds_record_zero_on_failed_cached_hit`

**Setup**: executor fixtures (fake cache returning a cached step, fake healer recording kwargs); `FakePage.url` returns `"https://a.example"` then `"https://b.example"`; cached code raises on replay.

**Input**: `executor.execute("Click the «Sign in» button", "action", page)`

**Trace**:
```
execute(...)
  → hit; url_before read; settle raises; url_after read
  → history.append(StepAttempt(code=cached.code, error=format_step_error(exc),
        outcome=OUTCOME_ORIGINAL, url_before="https://a.example", url_after="https://b.example"))
  → healer.heal(cached, error_text, "Click the «Sign in» button", "action", scenario, page, history, window)
```

**Assertions**:
```
healer received attempt_history with exactly one record before the call
record.outcome == OUTCOME_ORIGINAL and record.code == cached.code
record.url_before == "https://a.example" and record.url_after == "https://b.example"
healer received step_text="Click the «Sign in» button" (raw) and step_type="action"
```

**Sufficiency**: record 0 is composed before the heal delegation — the contract's "a regeneration never loses the original cached code" starts here.

---

#### `test_execute_passes_empty_history_and_raw_sentence_to_generate`

**Setup**: executor fixtures; fake cache miss; fake generator recording kwargs.

**Input**: `executor.execute("Open the LOGIN page", "action", page)`

**Trace**:
```
execute(...) → miss → generator.generate(identity, "Open the LOGIN page", "action", scenario, page, history=[], window)
```

**Assertions**:
```
generator received step_text="Open the LOGIN page"          # raw, not casefolded
generator received step_type="action" and attempt_history == []
identity.normalized_text == "open the login page"           # addressing still normalized
```

**Sufficiency**: the honest-inputs/threading rule — the raw sentence reaches the engine while the normalization stays an addressing key only.

---

#### `test_steer_appends_rejected_record_with_same_url_on_both_sides`

**Setup**: steering fixtures (stdin scripted "fix the button\nn\nquit"); `FakePage.url` returns `"https://s.example"`; stub provider returns code.

**Input**: `steering.steer(failure, identity, "click the «Sign in» button", "action", [], page, history)` with an anchored record 0.

**Trace**:
```
steer(...)
  turn 1: request (attempt_history=[record0.render()], guidance="fix the button", step_type="action")
  → run? n → u = "https://s.example"
  → history.append(StepAttempt(code, "", OUTCOME_REJECTED, "https://s.example", "https://s.example"))
  → prompt reopens → quit → return None
```

**Assertions**:
```
history[1].outcome == OUTCOME_REJECTED and history[1].error == ""
history[1].url_before == history[1].url_after == "https://s.example"
provider.calls[0]["step_type"] == "action"
provider.calls[0]["guidance"] == "fix the button"
```

**Sufficiency**: a rejected turn must enter the shared history as a completed record with the identical URL pair — the model never re-proposes it blind.

---

#### `test_steer_gates_with_shared_history_and_blocks_on_high_finding`

**Setup**: stdin "try again\ny\nonce more\ny\nquit"; provider answers two candidates; compliance verdicts scripted [[high instruction finding], []] — the first gate call blocks, the second passes.

**Input**: `steer(failure, identity, step_text, "action", [], page, history)` (anchored record 0).

**Trace**:
```
turn 1: request → approved → run green → gate → high instruction finding
  → no write-back; history.append(StepAttempt(code, "instruction violation: ...", OUTCOME_COMPLIANCE_BLOCKED, u, u))
turn 2: request carries [record0, blocked record] → approved → green → gate [] → write-back → return healed
```

**Assertions**:
```
cache.save called once, after the second gate pass
provider.calls[1]["attempt_history"] == [history[0].render(), history[1].render()]
history[1].outcome == OUTCOME_COMPLIANCE_BLOCKED
```

**Sufficiency**: the write-back gate on both dimensions with the shared history — a high finding of either dimension never reaches the cache, and the next turn sees the blocked record.

---

#### `test_providers_render_identical_user_content_for_the_new_inputs` (parity)

**Setup**: both providers with SDK clients stubbed at the import point; identical inputs including `step_type="assertion"` and two rendered records; capture the `messages` payload each SDK client receives.

**Input**: `generate_step_code(...)` and `check_instruction_compliance(...)` on both providers with the same arguments.

**Trace**:
```
OpenAIProvider.generate_step_code(args) → openai client receives messages=[system, user(text)]
AnthropicProvider.generate_step_code(args) → anthropic client receives system=..., messages=[user(text)]
→ same user text, field for field; the same pair for the compliance operation
```

**Assertions**:
```
openai_user_text == anthropic_user_text            # generation
openai_compliance_text == anthropic_compliance_text  # verdict
both contain "STEP TYPE: assertion" and the HISTORY/ATTEMPT HISTORY blocks at the same positions
```

**Sufficiency**: provider parity is an absolute contract requirement of the port; the new inputs must not become a capability difference.

---

### Negative Tests

#### `test_parse_compliance_verdict_rejects_old_shape_without_dimension`

**Setup**: none.

**Input**: `'[{"instruction": "Prefer id attributes", "priority": "high", "explanation": "locates by text"}]'`

**Trace**:
```
parse_compliance_verdict(text)
  → json ok, list ok, item dict ok
  → item.get("dimension") is None → not a str → _malformed
  → raise ComplianceVerdictError
```

**Assertions**:
```
pytest.raises(ComplianceVerdictError) — message contains "dimension" and a fragment of the raw answer
```

**Sufficiency**: an old-shaped verdict model answer must fail loudly — never a silent pass of unchecked code; this is the migration guard of the whole verdict format change.

---

#### `test_parse_compliance_verdict_rejects_unknown_dimension`

**Setup**: none.

**Input**: `'[{"instruction": "x", "priority": "high", "explanation": "y", "dimension": "quality"}]'`

**Trace**:
```
parse_compliance_verdict(text) → "quality" ∉ {"instruction", "adequacy"} → _malformed → raise
```

**Assertions**:
```
pytest.raises(ComplianceVerdictError)
```

**Sufficiency**: the dimension is a closed set — an invented label would corrupt the blocking semantics (callers test only priority, but statistics/consumers rely on the two labels).

---

#### `test_build_compliance_fields_omits_attempt_history_block_when_empty`

**Setup**: none.

**Input**: `build_compliance_fields("Prefer id attributes", "open the page", "action", [], code)`

**Trace**:
```
build_compliance_fields(...) → sections INSTRUCTIONS, STEP TYPE+STEP, CODE (no ATTEMPT HISTORY)
```

**Assertions**:
```
"ATTEMPT HISTORY" not in text
```

**Sufficiency**: a first-attempt green candidate gates with an empty history — the block must vanish, matching the gate prompt's "when present".

---

### Edge Case Tests

#### `test_render_omits_error_part_when_error_empty`

**Setup**: none.

**Input**: `StepAttempt(code="def step(page) -> None:\n    ...", error="", outcome=OUTCOME_REJECTED, url_before="u", url_after="u")`

**Trace**:
```
render() → outcome line, url line, code part; error empty → no error part
```

**Assertions**:
```
record == "rejected by the engineer, not executed\nurl: u -> u\ncode:\ndef step(page) -> None:\n    ..."
"error:" not in record
```

**Sufficiency**: rejected turns carry no error — a spurious empty `error:` part would mislead the verdict model into expecting failure text.

---

#### `test_render_keeps_the_empty_url_pair_visible`

**Setup**: none (pure model).

**Input**: `StepAttempt(code="def step(page) -> None:\n    ...", error="TimeoutError: click timed out", outcome=OUTCOME_FAILED_CHECK, url_before="", url_after="")`

**Trace**:
```
render()
  → outcome line "failed check"
  → url line "url:  -> "   (both sides empty — the pair stays visible, truthfully empty;
     no dropping of the line, no placeholder)
  → code part; error part
```

**Assertions**:
```
record.splitlines()[0] == "failed check"
record.splitlines()[1] == "url:  -> "
```

**Sufficiency**: resolved decision 1 degrades a dead-page read to the empty string — the rendered record must keep the (truthfully empty) URL pair rather than drop the line, so the verdict model sees that no URL change was observed; pins the exact two-space rendering.

---

#### `test_url_read_failure_degrades_to_empty_string_and_attempt_proceeds`

**Setup**: `FakePage` whose `url` property raises `RuntimeError("page crashed")`; `StubProvider(answers=[green], compliance_verdicts=[[]])`.

**Input**: `generator.generate(identity, "open the page", "action", [], page, [], window)`

**Trace**:
```
attempt 1: url_before read raises → "" ; settle green ; url_after read raises → ""
→ gate [] → store → CachedStep returned (no raise)
```

**Assertions**:
```
result.code == green_code
history == []                       # green attempt records nothing; the failed reads never surface
```

**Sufficiency**: resolved decision 1 — a mechanical read must never kill an otherwise-green attempt; guards exist at every bracket site (engine, executor, steering).

---

#### `test_execute_creates_history_per_step_and_never_carries_it_across_steps`

**Setup**: executor fixtures; two consecutive cache-miss steps.

**Input**: `execute("open the page", "action", page)` then `execute("click the button", "action", page)`

**Trace**:
```
step 1 → generator receives history_a == []
step 2 → generator receives history_b == []     # a fresh list, not history_a grown
```

**Assertions**:
```
generator.calls[0]["attempt_history"] == [] and generator.calls[1]["attempt_history"] == []
the two lists are distinct objects (identity check via the recorded call args or a marker append)
```

**Sufficiency**: the per-step lifetime requirement — a leaked history would poison the next step's requests with unrelated attempts.

---

#### `test_generation_exhaustion_with_standing_adequacy_finding_names_the_step_fragment`

**Setup**: `RunBudgets` allowing exactly one generation attempt and refusing healing; provider answer green-executing but the gate returns a high adequacy finding every time it is called.

**Input**: `generate(identity, "click the «Sign in» button", "action", [], page, [], window)`

**Trace**:
```
attempt 1: green → gate high adequacy → record appended; standing = finding
loop: try_generation refused → _exhaustion_outcome(standing)
→ IncurableStepError with verdict(category="incurable",
     explanation="click the «Sign in» button — code only checks an already-achieved state",
     recommendation="satisfy the finding in the step code: click the «Sign in» button")
```

**Assertions**:
```
exc.verdict.category == "incurable"
exc.verdict.recommendation.startswith("satisfy the finding in the step code:")
"generation attempt budget exhausted" in exc.reason and ":" not in exc.reason
exc.error.startswith("adequacy violation:")
```

**Sufficiency**: the exhaustion-with-standing-finding wording changed to dimension-neutral text — an adequacy finding at exhaustion must terminate naming the unaccomplished step, colon-free per the first-line contract.

---

#### `test_regenerate_exhaustion_derives_terminal_facts_from_last_record`

**Setup**: `StubProvider(answers=[failing_code])` — `failing_code` raises `RuntimeError("boom")` on execution; `RunBudgets` allowing exactly one healing attempt; anchored `history = [StepAttempt(code=cached_code, error="old rot", outcome=OUTCOME_ORIGINAL, url_before="https://a.example", url_after="https://b.example")]`; tmp_path cache; `FakePage` with `url` returning fixed values.

**Input**: `generator.regenerate(identity, "click the «Sign in» button", "action", [], page, history, "use role locators", window)`

**Trace**:
```
regenerate(...)
  try_healing granted (attempt 1) → request carries [record0.render()] → failing_code
    url bracket → settle raises RuntimeError
    → history.append(StepAttempt(failing_code, "RuntimeError: boom",
          OUTCOME_EXECUTION_FAILED, url_before, url_after))
  loop: try_healing refused
  → raise IncurableStepError(step_text, "healing attempt budget exhausted",
      history[-1].error, code=history[-1].code)   # verdict None — the healer attaches the entry verdict
```

**Assertions**:
```
pytest.raises(IncurableStepError) as exc_info
exc_info.value.reason == "healing attempt budget exhausted"
exc_info.value.code == failing_code and exc_info.value.error == "RuntimeError: boom"
exc_info.value.verdict is None
len(history) == 2 and history[0].code == cached_code and history[0].outcome == OUTCOME_ORIGINAL
```

**Sufficiency**: the terminal-failure facts switched source — from the removed `existing_code`/`error` parameters to the history; without this test an implementation could re-introduce the removed inputs or report record 0's stale facts at exhaustion.

## Additional Instructions for the Implementation Agent

- **Implementation order** (dependency bottom-up): 1) `prettyplay/llm` (models → _request → provider → both providers); 2) `prettyplay/engine/attempts.py` (new), then `generator.py`, `compliance.py`, `healer.py`, `classification.py` docstring, `__init__.py` export of `StepAttempt`; 3) `prettyplay/engine/steering/steering.py`; 4) `prettyplay/executor.py`; 5) tests in the same order; 6) frozen-mirror sync.
- **Frozen mirrors** (byte-equal, change only together with their source): `SYSTEM_PROMPT` in `generator.py` and `steering.py` = `.goga/usages/prompts/generation.md` after the `---` separator; `CHEAT_SHEET` (both cells) = the whole `.goga/usages/prompts/cheatsheet.md`; `COMPLIANCE_PROMPT` in `compliance.py` = the `compliance_prompt` practice of `prettyplay/engine/CODEMANIFEST` (the block-scalar text). The mirror test pattern already exists — extend, don't reinvent.
- **Do not touch**: `prettyplay/llm/.usages/classification.md`, `prettyplay/.usages/lifecycle.md`, `.goga/usages/prompts/cheatsheet.md`, any CODEMANIFEST (the contracts are final), `PageFacade`, the failure taxonomy, the cache cell, budgets, polling, the classification port operation and its prompt.
- **Keep the removed inputs removed**: no `existing_code`/`error`/`guidance_history` parameters may survive anywhere (port, providers, stubs, tests). The steering `_turn_record` helper is deleted, not adapted.
- **Guarded URL reads** (decision 1): every bracket site uses the guard — engine `_read_url`, executor `_read_url`, steering `_guarded_url` (None → ""). Never let a bracket read raise.
- **Records are append-only** (`StepAttempt` frozen) and confined to one step execution; nothing from the history is ever persisted to the cache file or logs (log only counts/outcomes if at all; no record dumps — payloads can be large and may carry page data).
- **Validation commands** (virtualenv): `pytest tests/ -x`, `ruff check prettyplay/ tests/`; facade checks: `python -c "from prettyplay.engine import StepAttempt"`, `python -c "from prettyplay import PrettyPlay"`.
- **Wording pins** (authored, colon-free reasons): `"healing attempt budget exhausted"`, `"generation attempt budget exhausted — {reason_safe(quote)}"`, violation text `f"{dimension} violation: {instruction} — {explanation}"`, exhaustion recommendation `f"satisfy the finding in the step code: {instruction}"`.
- The architecture plan (`.goga/history/2026/agent-context-window/arch.md`) and the apply-stage summary remain the record of *why*; this document is the record of *how*.
