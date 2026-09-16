# Design Document: `step-group-and-step-params`

Pace control, step parameters and step groups of the prettyplay runtime. The input contracts:
the ADR (`adr.md`), the PRD (`prd.md`), the applied architecture plan (`arch.md`) and the
CODEMANIFEST state materialized by the apply stage (including the two consistency fixes of this
design pass, see [Applied Fixes](#applied-fixes)).

---

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/config/CODEMANIFEST`: `BrowserConfig` gains the `speed` field (int 0–100, default
  100) with loud range validation and the `speed -> int` property; the loader gains the
  `PRETTYPLAY_BROWSER_SPEED` env override (decimal integer, 0–100, loud on violation); header and
  footer sentences.
- `prettyplay/driver/CODEMANIFEST`: the pace paragraph — `speed` maps linearly to Playwright's
  native `slow_mo` (`int((100 − speed) × 30)` ms, 100 → 0) passed on both local launch and remote
  connect, every launch mode; `open_context` algorithm step 1 and a new requirement.
- `prettyplay/engine/polling/CODEMANIFEST`: `SettleWindow` gains `tries: int | None` with the
  `tries`/`count_bounded` properties and the two-mode `enabled`; `settle` gains the count-bounded
  loop head and the per-call counter requirements.
- `prettyplay/llm/CODEMANIFEST`: `generate_step_code` takes `previous_steps: list[ScenarioStep]`
  and `group_prompt: str | None`; `classify_failure` renamed `classify_step_failure` (nominal);
  new port operation `classify_group_failure`; new types `ScenarioStep`,
  `GroupFailureClassification` (five properties after the D2 fix — `degraded` included),
  `parse_group_failure_classification`; four parity header sentences.
- `prettyplay/cache/CODEMANIFEST`: `RunBudgets` gains `refresh_healing(identity)` and
  `open_group_cycle(group_key) -> allowed: bool` with the per-group cycle cap (`healing_limit`).
- `prettyplay/engine/CODEMANIFEST`: `ScenarioStep` import; typed `previous_steps` on
  `generate`/`regenerate`/`heal`; `group_prompt: str | None` on `generate`/`regenerate` with the
  group branches at the failed-check and budget-exhaustion points (classification suppressed);
  practice renames plus `group_framing`.
- `prettyplay/engine/groups/CODEMANIFEST` (NEW CELL): `GroupStepOutcome` (with `render`),
  `classify_group_failure` routine, `GroupRecovery.recover` — the diagnosis-driven recovery.
- `prettyplay/engine/steering/CODEMANIFEST`: `ScenarioStep` import; `steer` takes typed records
  and `group_prompt`; the group-context header sentence; practice renames plus `group_framing`.
- `prettyplay/CODEMANIFEST` (facade): `ScenarioStep` import; the engine/groups import block
  (`GroupRecovery`, `GroupStepOutcome`, usage `recovery`); `step`/`expect` gain keyword-only
  `tries`/`delay` with loud validation; new `group()` method; new `StepGroup` entity;
  `StepExecutor` gains `recovery` and the rewired `execute(..., group, tries, delay)`.
- `prettyplay/reporting/CODEMANIFEST`: the `on_healing_started` category vocabulary gains the
  group-diagnosis label `recoverable` (D1 fix of this pass).

### New Entities

- `ScenarioStep(sentence, group_prompt)` — `prettyplay/llm/models.py`. One typed record of the
  scenario context: the raw sentence plus its permanent group membership.
- `GroupFailureClassification(category, root_cause, earliest_step, recommendation, degraded)` —
  `prettyplay/llm/models.py`. The verdict of a group diagnosis; `degraded` is a library-set flag.
- `parse_group_failure_classification(verdict_text) -> GroupFailureClassification` —
  `prettyplay/llm/models.py`. The strict single parse point with conservative degradation.
- `GroupStepOutcome(sentence, step_type, tries, delay, outcome, url_before, url_after, identity)`
  — `prettyplay/engine/groups/outcome.py`. One verbatim trace record of a group step execution.
- `classify_group_failure(config, provider, group_prompt, traces, step_text, step_type,
  attempt_history, page) -> GroupFailureClassification` — `prettyplay/engine/groups/diagnosis.py`.
  Composes and sends the single diagnosis request.
- `GroupRecovery(config, provider, generator, cache, budgets, reporter)` —
  `prettyplay/engine/groups/recovery.py`. The recovery engine with `recover(...)`.
- `StepGroup(prompt, speed, delay, executor)` — `prettyplay/groups.py`. The authoring group
  object (context manager, `traces`, `step`/`expect`).

### Changed Entities

- `BrowserConfig` — `+speed: int` (0–100, default 100, loud validation).
- `load_config` — the env-override step and requirements cover `PRETTYPLAY_BROWSER_SPEED`.
- `DriverSession.open_context` / `_launch_engine` — `slow_mo` computed from `speed` rides the
  launch and the connect.
- `SettleWindow` — `+tries`, `+count_bounded`, two-mode `enabled`.
- `settle` — the count-bounded re-execution mode beside the time window.
- `LLMProvider.generate_step_code` — typed `previous_steps`, `+group_prompt`.
- `LLMProvider.classify_failure` → `classify_step_failure` — nominal rename, behavior identical.
- `LLMProvider.classify_group_failure` — the fourth port operation (both providers, full parity).
- `RunBudgets` — `+refresh_healing`, `+open_group_cycle`.
- `StepGenerator.generate` / `.regenerate` — typed context, `+group_prompt`, group branches.
- `StepHealer.heal` — typed context (group steps never reach the healer).
- `classify_step_failure` (engine routine) — calls the renamed port method.
- `StepSteering.steer` — typed context, `+group_prompt`, framing in the guided requests.
- `PrettyPlay` — `step`/`expect` `+tries`/`delay` (keyword-only, loud validation), `+group()`,
  composition wires `GroupRecovery` into the executor.
- `StepExecutor` — `+recovery`; `execute(+group, tries, delay)` with the quiet pre-step pause,
  the count-bounded window, the typed scenario context, the group failure routing and the trace
  recording.

### Deleted Entities

- None. The port method rename `classify_failure` → `classify_step_failure` removes the old
  method name from the contract; no type is deleted.

### Usages and Annotations Changes

- Renames (content byte-identical, C13 — verified R100): `.goga/usages/prompts/generation.md` →
  `step_generation.md`; `.goga/usages/prompts/cheatsheet.md` → `step_cheatsheet.md`; the
  `system_prompt`/`cheat_sheet` keys of `prettyplay/engine` and `prettyplay/engine/steering`
  point at the new paths.
- New practices: `.goga/usages/prompts/group_framing.md` (connected as `group_framing` by engine,
  engine/groups, steering), `.goga/usages/prompts/group_diagnosis.md` (connected as
  `group_diagnosis` by engine/groups).
- Already-updated cooks: `.goga/usages/cooks/playwright.md` (the pace/slow_mo section),
  `.goga/usages/cooks/json_repair.md` (the group diagnosis answer as the second salvage consumer).
- Cell `.usages/` updates: config `configuration.md` (speed TOML/env/Pace section), polling
  `settle.md` (count-bounded section), llm `providers.md`/`classification.md`, cache `budgets.md`
  (recovery budgets), engine `generation.md`/`healing.md`, steering `steering.md`, facade
  `steps.md` (step parameters, groups) and `lifecycle.md` (group recovery), new groups
  `recovery.md`.

## Applied Fixes

### Fixed CODEMANIFEST Defects

Both defects were found by the four-dimension consistency audit of this design pass, approved by
the user and applied before tracing:

- `prettyplay/reporting/CODEMANIFEST` (`on_healing_started`): before — "`category` is the
  classification label: rot, product_defect, fixable, incurable"; after — "… incurable — a group
  recovery row reports the diagnosis label recoverable". (reason: interface ↔ interface
  inconsistency — the groups cell fires the event per recovered step with the diagnosis label
  `recoverable`, which the untouched reporting contract's closed vocabulary did not admit; the
  event set itself stays unchanged, no new hook events.)
- `prettyplay/llm/CODEMANIFEST` (`GroupFailureClassification`): the type gains the library-set
  property `degraded -> bool` (False on every parsed answer, True only on the degradation path)
  and the matching requirement. (reason: annotations ↔ entity inconsistency — the groups routine
  is specified to log the degraded-answer WARNING, but it only receives the verdict object and can
  neither see the raw model answer nor detect the degradation; the flag makes the degradation
  observable at the contract boundary while the LLM answer shape stays four-field and the parse
  itself still never logs, exactly as its contract requires.)

### Fixed by the Design Review Pass

The design review (the stage after this document) traced every entry point and every test
scenario against the contracts and the current implementation; 8 remarks were found, all
approved and applied — none Critical or High, no traced control-flow chain broke:

- `prettyplay/engine/.usages/generation.md`: the compliance-gate bullet named the effective
  generation model — corrected to the effective classification model (the llm contract's
  requirement and the providers' behavior); the design's `.usages/` verification note updated.
- The diagnosis observability gap: the groups contract promises a structured log record for the
  diagnosis itself — the algorithms now pin `group_diagnosed` (INFO, category + earliest step)
  beside the degraded WARNING, in the routine algorithm, the recover algorithm, the routine
  trace, the Cross-cutting Logging list and the SC6 test assertions.
- `test_group_authoring_block_pauses_and_traces`: the sleep assertion `[2.0, 1.5, 0.5]` was
  unsatisfiable with a monkeypatched executor (the step's own delay is slept by the real executor
  cycle) — corrected to `[2.0, 1.5]` plus the recorded `delay=0.5` argument; the new
  `test_step_delay_pauses_quietly_after_started_event` covers the SC5 step-delay happy path at
  the executor level (started event → quiet pause → code, no output noise).
- `test_env_speed_out_of_range_fails_at_load`: the message names the dotted setting
  (`browser.speed`), never the env var name — the loader convention; the implementation note
  adds `browser.speed` to `_ALLOWED_TEXT` and records that out-of-range values fail at the
  pydantic field_validator.
- The `StepGroup` first-step marker is pinned as an internal delegation flag (set before each
  executor call), never `traces` non-empty — a first step dying without a trace record must not
  re-arm the entry pause.
- Two test-narrative inconsistencies fixed: the SC6 trace now lists `on_healing_started` before
  the regeneration (the algorithm's order), and the SC7 setup's case-B wording names the failed
  cached hit.
- `SettleWindow.has_remaining` is pinned as time-bounded-mode-only (the count-bounded loop
  checks its own counter) — in the design and in the polling CODEMANIFEST annotation.
- `prettyplay/engine/CODEMANIFEST` (`StepHealer.heal`): the `previous_steps` parameter
  annotation now says typed scenario records, matching the typed signature and every sibling
  annotation.

## Entity Interaction and Data Flow

### Interaction Diagram

```
                         author test
                             │
              PrettyPlay (facade, scenario.py)
                step/expect(tries, delay)   group(prompt, speed, delay)
                             │                     │ yields
                             ▼                     ▼
                      StepExecutor ────────► StepGroup (groups.py)
                       execute(text, type,     step/expect → executor.execute(…, group=self)
                       page, group, tries,     traces: list[GroupStepOutcome]
                       delay)                  pauses: entry delay + between-step pace
                        │    │        │
        ┌───────────────┘    │        └──────────────────┐
        ▼ (miss)             ▼ (hit failed)              ▼ (group step failed, non-strict)
  StepGenerator.generate  StepHealer.heal           GroupRecovery.recover
        │  regenerate ◄───┘ (ordinary steps)          │ 1 open_group_cycle (RunBudgets)
        │ group_prompt=None ⇒ ordinary paths          │ 2 classify_group_failure (routine)
        │ group_prompt set ⇒ framing, no             │    └► LLMProvider.classify_group_failure
        │   internal classification                   │        └► parse_group_failure_classification
        ▼                                              │ 3 earliest-step match (traces / previous_steps)
  LLMProvider.generate_step_code                       │ 4 refresh_healing × row (RunBudgets)
    (openai | anthropic, full parity)                  │ 5 row: generator.regenerate(group_prompt=…)
                                                       │    → compliance gate → cache write-back
  SettleWindow(tries) + settle — both modes            │ 6 repeat failure → new cycle (cap healing_limit)
  classify_step_failure (routine → port, renamed)      │ 7 return healed CachedStep
                                                       ▼
  StepSteering.steer(group_prompt) — the terminal gate after recovery
```

### Data Flows

1. **Pace (config → driver).** `BrowserConfig.speed` (file/env/override layers, validated 0–100)
   → `DriverSession._launch_engine` computes `slow_mo = int((100 − speed) × 30)` → passed to
   `engine.launch(...)` and `engine.connect(endpoint, slow_mo=...)`. One value per browser
   process, fixed for the run; identical on replays and strict runs.
2. **Step parameters (facade → polling).** `step(text, tries=N, delay=S)` → validation →
   `StepExecutor.execute(..., tries=N, delay=S)` → quiet pause after `on_step_started` →
   `SettleWindow(polling_timeout, polling_delay, tries=N)` → `settle` runs the count-bounded loop
   (cached code and every candidate each get their own full count).
3. **Typed scenario context (executor → every request).** `StepExecutor._scenario:
   list[ScenarioStep]`; appended after every executed step (sentence + group prompt of the
   enclosing group, empty for ordinary). Flows into `generate`/`regenerate`/`heal`/`steer`/
   `recover` → `LLMProvider.generate_step_code(previous_steps=…, group_prompt=…)` → both
   providers render `PREVIOUS STEPS` from the records (group entries marked) and the `GROUP
   PROMPT` block before it.
4. **Group failure routing (executor → groups → engine).** A group step fails (cached replay or
   generation) → executor appends the trace record (outcome failed) to `StepGroup.traces` →
   anchors the attempt history (record 0 on the cached-replay path) → `GroupRecovery.recover(
   group_prompt, traces, step_text, step_type, previous_steps, identity, attempt_history, page,
   window)` → diagnosis → row regeneration through `StepGenerator.regenerate` → per-step
   compliance gate + cache write-back → healed return continues the step as a success; a terminal
   failure reaches `StepSteering.steer` (group context) before propagating.
5. **Diagnosis verdict (provider → recovery).** `classify_group_failure` (groups routine)
   composes GROUP STEPS renders + HISTORY records + snapshot (+ screenshot) → port
   `classify_group_failure` (classification model, classification instructions) →
   `parse_group_failure_classification` → verdict (degraded answers: incurable + raw answer in
   `root_cause` + `degraded=True`) → the routine logs the WARNING on `degraded` → the recovery
   maps the verdict onto `FailureVerdict` for every terminal raise.

### Entity Dependencies

Initialization order (leaves → root, unchanged by this design): failures, reporting → config →
{llm, driver} → {cache, polling} → engine → {groups, steering} → facade. The new edge:
`StepExecutor` (facade) receives `GroupRecovery` (engine/groups), which itself consumes
`StepGenerator` (engine) — the steering pattern: a consumer of the engine is its child cell. No
import cycles (schema-verified): engine imports neither groups nor steering.

## Code Stack Trace

Traces of every contract entry point over the current implementation (commit 86d06df + the
applied working tree). Each checkpoint verifies type flow, mutation compatibility and interface
alignment; all defects found during tracing were resolved before this document was finalized.

### Trace: `BrowserConfig` construction with `speed`

#### Chain
1. **Input**: `BrowserConfig(speed=40)` (programmatic layer), or the file layer
   (`[tool.prettyplay.browser] speed = 40`), or env `PRETTYPLAY_BROWSER_SPEED=40`.
2. `load_config` merges the layers (file → env → programmatic overlay; explicitly set values
   win) → checkpoint: the browser-group merge already reaches inside the group (`browser.*`
   nested read); the new key rides the existing path — **passed**.
3. Env parse: `PRETTYPLAY_BROWSER_SPEED` parses as a decimal integer (mirrors
   `PRETTYPLAY_POLLING_DELAY` float parsing); an unparseable value raises at the env layer,
   an out-of-range value parses and fails at the pydantic field_validator — both surface as
   `ConfigurationError` naming the dotted setting (`browser.speed`), the received value and
   the accepted form; the implementation adds `browser.speed` to `_ALLOWED_TEXT` of the loader
   ("an integer 0-100 inclusive") so the rendered allowed text is authored, not the pydantic
   message → checkpoint: the loader already has both idioms (scalar-parse-and-raise and the
   one-line-per-setting validation render) — **passed**.
4. `BrowserConfig` pydantic validation: `speed: int = 100` with a `field_validator` rejecting
   non-int/bool and values outside 0–100 (message names the received value) → the wrapped
   `ConfigurationError` render (one line per invalid setting) → checkpoint: identical to the
   `name`/`endpoint` validators — **passed**.
5. **Output**: the validated group; `speed` readable as `config.browser.speed`.

#### Checkpoint Summary
- Layering reuse: passed — an ordinary browser-group value, no new mechanism.
- Loud-failure parity: passed — the received value is named, never a silent ignore.

### Trace: `DriverSession.open_context` → `_launch_engine` (slow_mo)

#### Chain
1. **Input**: first `open_context()` of the test (lazy start).
2. `_launch` starts the worker thread and Playwright inside it → unchanged.
3. `_launch_engine` reads `group = self._config.browser`; NEW: `slow_mo = int((100 -
   group.speed) * 30)` → checkpoint: `speed` is always a validated int 0–100, so `slow_mo` ∈
   [0, 3000]; 100 → 0 — **passed**.
4. Local launch: `engine.launch(headless=…, channel=…, slow_mo=slow_mo)` (plus the existing
   fullscreen `--start-maximized` arg); remote connect: `engine.connect(endpoint,
   slow_mo=slow_mo)` wrapped with the endpoint-naming error → checkpoint: Playwright's
   `launch`/`connect` both accept `slow_mo` (see `playwright` cook) — **passed**.
5. **Output**: one browser process running at the mapped pace for the whole test; contexts and
   pages unchanged.

#### Checkpoint Summary
- Every launch mode covered: passed — one computation, two call sites.
- `slow_mo=0` at speed 100: passed — behaviorally identical to today's no-argument form (SC1).

### Trace: `SettleWindow(timeout, delay, tries)` + `settle` (count mode)

#### Chain
1. **Input**: `StepExecutor.execute` builds `SettleWindow(config.polling_timeout,
   config.polling_delay, tries)` — `tries` is the declared count or None.
2. `count_bounded` → `tries is not None`; `enabled` → `(timeout is not None and timeout > 0) or
   count_bounded` → checkpoint: a count-bounded window with polling disabled (`timeout None`)
   is now enabled — required, otherwise count mode would be dead on default configs —
   **passed**.
3. `settle(execute, code, page, window)`: `window.start()` (idempotent time mark; unused by the
   count branch) → branch: `window.count_bounded` → local counter `executed = 0`; loop:
   `execute(code, page)`; success → return; failure → `executed += 1`; re-execute iff
   `window.enabled and is_pollable_failure(failure) and executed < window.tries` → log
   `settle_retry` (INFO, attempt counter, error text) → sleep `window.delay` → retry; else
   `raise` → checkpoint: the counter is local to the settle call — the cached code and every
   generated candidate each get their own full count; `tries=1` → no re-execution — **passed**.
4. Time mode (`tries=None`): byte-identical to today's loop (`enabled and pollable and
   has_remaining()`) → checkpoint: C13 — **passed**.
5. **Output**: transient failures absorbed inside the declared bound; exhaustion propagates the
   failure as-is to the caller (classification/recovery decide).

#### Checkpoint Summary
- Mode precedence: passed — a declared count replaces the time bound for that loop (never min
  of both).
- Budget isolation: passed — no LLM budget is ever consumed by re-execution.

### Trace: `LLMProvider.generate_step_code` (typed context + group framing)

#### Chain
1. **Input**: engine `StepGenerator._request` / steering `_guided_request` pass
   `previous_steps: list[ScenarioStep]`, `group_prompt: str | None` beside the unchanged inputs.
2. `_request.build_fields_text(..., previous_steps, group_prompt, ...)`: sections = `[STEP TYPE
   + STEP]`; NEW `GROUP PROMPT:` section when `group_prompt` is non-empty, inserted immediately
   before `PREVIOUS STEPS`; `_format_previous_steps` renders each record — ordinary `- {sentence}`
   (byte-identical to today, C13), group entry `- {sentence} [group step — {group_prompt}]`; then
   `PAGE SNAPSHOT`, `PAGE URL?`, `CHEAT SHEET`, `USER INSTRUCTIONS?`, `HISTORY?`,
   `RECOMMENDATION?`, `USER GUIDANCE?` → checkpoint: with `group_prompt=None` and ordinary
   records the built text is byte-identical to today — **passed**.
3. Both providers (`openai_provider`, `anthropic_provider`) call the same shared builder and wrap
   the result with their SDK payload (`openai_user_content` / anthropic blocks) → checkpoint:
   parity by construction — **passed**.
4. **Output**: the generated step code (unchanged extraction via `extract_code_block`).

#### Checkpoint Summary
- C13 byte-identity of ordinary requests: passed — the renderer changes only for group entries.
- Block order: passed — GROUP PROMPT immediately before PREVIOUS STEPS, exactly as the llm and
  `group_framing` contracts state.

### Trace: `LLMProvider.classify_group_failure` (new operation)

#### Chain
1. **Input**: the groups routine passes the system prompt (`group_diagnosis`), classification
   instructions, the group prompt, the GROUP STEPS renders (`GroupStepOutcome.render()` joined by
   blank lines), the failed step sentence, its rendered HISTORY records, the snapshot, optional
   screenshot.
2. `_request.build_group_diagnosis_fields(...)` (NEW, shared): fixed order `GROUP PROMPT`,
   `GROUP STEPS`, `STEP`, `HISTORY`, `PAGE SNAPSHOT`, then `USER INSTRUCTIONS` last; the
   screenshot rides the SDK image part beside the text → checkpoint: order pinned by the port
   contract, identical in both providers — **passed**.
3. One completion request through `config.effective_classification_model` → service failure →
   `LLMUnavailableError` naming the provider (existing mapping) → checkpoint — **passed**.
4. `parse_group_failure_classification(answer)`: trim → `json.loads` → on `ValueError` one
   `json_repair` salvage (a salvage-library failure degrades too) → semantic validation (dict,
   the four fields present and str, `category` ∈ {recoverable, product_defect, incurable}) →
   valid: `GroupFailureClassification(..., degraded=False)`; anything else: category `incurable`,
   `root_cause` = the raw answer, `earliest_step=""`, `recommendation` = the conservative
   guidance line, `degraded=True` → checkpoint: never synthesizes `recoverable`; mirrors
   `parse_compliance_verdict`'s salvage-once flow with the conservative-degradation difference
   (a malformed compliance verdict raises loudly, a malformed diagnosis degrades — each per its
   contract) — **passed**.
5. **Output**: the verdict object; `degraded` drives the caller's WARNING.

#### Checkpoint Summary
- Degradation observability: passed — the D2 flag closes the detection gap at the boundary.
- One request per diagnosis: passed — budgets belong to the calling engine.

### Trace: `RunBudgets.refresh_healing` / `open_group_cycle`

#### Chain
1. **Input**: `refresh_healing(identity)` / `open_group_cycle(group_key)` from the recovery.
2. `refresh_healing`: `self._healing_used[identity.filename] = 0` → the next `try_healing`
   calls draw from a renewed pool of the full `healing_limit` → checkpoint: ordinary per-step
   pools untouched otherwise — **passed**.
3. `open_group_cycle`: `used = self._group_cycles_used.get(group_key, 0)`; `used >=
   self._healing_limit` → False (the caller raises the terminal incurable); else increment and
   True → checkpoint: keyed by the group prompt string, per test (registry lifetime), capped by
   `healing_limit` — the loop is never infinite (C5) — **passed**.
4. **Output**: booleans; no persistence, process memory only.

#### Checkpoint Summary
- Worst case bounded: healing attempts per group step ≤ `healing_limit × healing_limit`
  (cycles × pool) — finite; ordinary steps' pools never consumed by recovery.

### Trace: `StepGenerator.generate` with `group_prompt`

#### Chain
1. **Input**: executor (miss path) passes `group_prompt=None` for ordinary steps, the group
   prompt for group steps.
2. `try_generation` → refused → `_exhaustion_outcome`: NEW group branch first — `group_prompt`
   non-empty → no classification, no funded regeneration: derive `(code, error)` from the last
   record (or the empty pair) → raise `IncurableStepError(step_text, "group step generation
   budget exhausted — the group recovery decides", error, code=code)` → checkpoint: colon-free
   authored reason; the executor routes it — **passed**.
3. Attempt: `_request(...)` — group framing rides the request (GROUP PROMPT + marked context)
   → `settle` under the step's window → green → compliance gate → high finding → record +
   retry (unchanged for group steps: the gate is a caching path, not a classification point);
   medium/low → WARNING + store.
4. Failed check (`AssertionError` survived the window): record appended → NEW group branch —
   no `classify_step_failure`, no `try_healing`-funded regeneration: raise
   `IncurableStepError(step_text, "group step check failed — the group recovery decides",
   error_field, code=code)` → checkpoint: the ordinary decision table is untouched behind the
   branch; `group_prompt=None` paths stay byte-identical (C13 regression pin) — **passed**.
5. Other candidate failure: record + retry (unchanged).
6. **Output**: a stored `CachedStep`, or the unclassified `IncurableStepError` for group steps,
   or the ordinary terminal kinds for ordinary steps.

#### Checkpoint Summary
- Suppression scope exact: failed-check and exhaustion points only; the compliance gate keeps
  guarding every caching path (C7).

### Trace: `StepGenerator.regenerate` with `group_prompt` (recovery rows)

#### Chain
1. **Input**: `GroupRecovery.recover` step 5 calls `regenerate(trace.identity, trace.sentence,
   trace.step_type, previous_steps, group_prompt, page, row_history, diagnosis.recommendation,
   SettleWindow(config.polling_timeout, config.polling_delay, trace.tries))`.
2. The healing loop (`_healing_loop`) is unchanged: `try_healing` per attempt (the cycle's
   `refresh_healing` renewed the pool), every request carries the recommendation + the group
   framing, failures append records and retry, green candidates pass the gate and store.
3. **Output**: the healed `CachedStep` per row step; exhaustion → `IncurableStepError` (the
   recovery catches it and re-enters a new cycle) → checkpoint: the row step's own window and
   identity come from its trace; the failed step's window parameter is not reused for earlier
   row steps — **passed**.

#### Checkpoint Summary
- Per-row attempt histories: the recovery composes each row step's history (see
  `GroupRecovery.recover` trace) — passed.

### Trace: `classify_group_failure` (groups routine)

#### Chain
1. **Input**: `recover` step 2 passes the group prompt, traces, the failed step sentence/type,
   its grown history, the page.
2. Snapshot (+ screenshot when `config.send_screenshots`) → GROUP STEPS renders
   (`trace.render()` per record) → HISTORY renders (`record.render()` per `StepAttempt`).
3. One port call: `provider.classify_group_failure(prompt=GROUP_DIAGNOSIS_PROMPT,
   user_instructions=config.classification_prompt, …)` — the frozen mirror of
   `group_diagnosis.md` (the section after `---`), cell-owned like `SYSTEM_PROMPT`.
4. `verdict.degraded` → log WARNING `group_diagnosis_degraded` with `extra={"group":
   group_prompt, "answer": verdict.root_cause}` (the raw answer rides `root_cause`); always log
   INFO `group_diagnosed` with `extra={"group": group_prompt, "category": verdict.category,
   "earliest": verdict.earliest_step}` — the structured record of the landed diagnosis.
5. **Output**: the verdict → checkpoint: `LLMUnavailableError` propagates untouched (explicit
   infrastructure failure, no retry) — **passed**.

#### Checkpoint Summary
- Honest inputs: the group prompt and every sentence reach the request verbatim (C8); the
  secrets rule covers the group prompt (C9) — it already flows only into requests/logs like step
  sentences.

### Trace: `GroupRecovery.recover`

#### Chain
1. **Input**: executor passes group prompt, traces (the failed step included, outcome failed),
   the failed step sentence/type, the typed scenario context, the identity, the anchored/grown
   history, the page, the failed step's window.
2. `open_group_cycle(group_prompt)` → False → raise `IncurableStepError` with the authored
   verdict (category incurable, explanation "the per-group recovery cycle cap is exhausted",
   colon-free) → checkpoint: one render (C6) — **passed**.
3. Diagnosis (routine above) → `product_defect` → `ProductDefectError` carrying the mapped
   verdict + the underlying error; `incurable` → `IncurableStepError` carrying them →
   checkpoint: verdict mapping — category as is; explanation ← `root_cause` plus the
   `earliest_step` quote when it names a step (`f"{root_cause} (earliest affected step:
   {earliest_step})"`); recommendation ← `recommendation` — **passed**.
4. Earliest-step match: exact string equality of `verdict.earliest_step` against each
   `trace.sentence` → the row start; else against each `previous_steps` sentence whose record is
   NOT a member of this group (`group_prompt` empty or different) → a hit raises the honest
   terminal `IncurableStepError` whose verdict names that step verbatim (explanation
   `f"the root lives outside the group — {sentence}"`, colon-free); no hit anywhere → the row is
   the failed step alone → checkpoint: exact verbatim matching only, no fuzzy matching —
   **passed**.
5. `refresh_healing(trace.identity)` for every row step.
6. Row (start … failed step, in trace order): per step — the declared `trace.delay` passes
   quietly; a per-row-step history is composed (the failed step reuses the passed-in grown
   history; every earlier row step gets a fresh list anchored by record 0 with its cached code
   loaded via `trace.identity` — `OUTCOME_ORIGINAL`, empty error when no cached step exists);
   `regenerate(...)` (framing + recommendation + `previous_steps` + the row window); green →
   gate → `cache` write-back inside the generator; `on_healing_started(step_text, "recoverable")`
   + `on_healed(step_text, explanation)` per recovered step; a structured INFO log record names
   the diagnosis and the row composition → checkpoint: reporting reuses healing events (D1
   vocabulary), no new hook events — **passed**.
7. A row step's `IncurableStepError` → caught → new cycle from step 2's entry (step 1 again)
   with the fresh failure state while cycles remain.
8. **Output**: the healed `CachedStep` of the failed step; the executor continues the step as a
   success.

#### Checkpoint Summary
- Forward-only recovery: passed — no rollback machinery; a re-planned action repeats its action
  (the frozen `system_prompt` replayability rule carries it).
- Trace immutability: passed — recovery re-executions do not mutate `StepGroup.traces` (the
  traces list is a snapshot for the diagnosis; later diagnoses see the honest original
  outcomes, and the fresh failure rides the attempt history).

### Trace: `StepSteering.steer` (typed context + group prompt)

#### Chain
1. **Input**: executor's terminal gate passes the failure, identity, sentence, type, typed
   `previous_steps`, `group_prompt`, page, anchored history.
2. Banner (unchanged), commands (unchanged); a guidance message builds the request via
   `_guided_request` — now passing `previous_steps` (typed) and `group_prompt` into
   `generate_step_code` → the framing renders per `group_framing` when non-empty → checkpoint:
   the dialog itself is unchanged; only the request composition widens — **passed**.
3. **Output**: healed step or None — unchanged semantics.

### Trace: `PrettyPlay.step` / `.expect` (`tries`/`delay`)

#### Chain
1. **Input**: `t.step("click Sign in", tries=3, delay=1.5)`.
2. `_validate_tries(3)` / `_validate_delay(1.5)` (shared facade helpers): `tries` — `None` passes;
   `isinstance(x, bool)` or not `isinstance(x, int)` or `x < 1` → `PrettyplayError` naming the
   parameter, the received value (`repr`), the allowed form ("a positive integer, keyword-only");
   `delay` — `None` passes; not `int | float` (bool excluded) or not finite or `< 0` → the same
   loud error ("a non-negative number of seconds, keyword-only") → checkpoint: identical
   validation reused by `StepGroup.step/expect` — **passed**.
3. `executor.execute(text, kind, self._ensure_page(), group=None, tries=tries, delay=delay)` →
   failures leave through `_raise_folded` (traceback folding unchanged, covers the new
   validation errors — they raise before the executor, inside the facade frame).
4. **Output**: the executed step; invalid parameters fail loudly at the call, before any page or
   LLM involvement.

### Trace: `PrettyPlay.group` + `StepGroup`

#### Chain
1. **Input**: `with t.group("accept cookies, fill and submit the order form", speed=30,
   delay=2) as g:`.
2. `group()` validates: `prompt` non-empty (empty → `PrettyplayError` at entry); `speed` None or
   a non-bool int 0–100 (outside → loud error naming the value and the 0–100 form); `delay` None
   or a non-negative finite number → constructs `StepGroup(prompt, speed, delay,
   self._executor)` and binds the test's lazy page opener (an implementation attribute
   `_open_page = self._ensure_page` — the contract constructor stays four-parameter; the group
   is only ever constructed by `group()`) → checkpoint: no ambient rerouting of the test object;
   group membership changes no step's cache address (C1 — the group prompt never enters
   `StepIdentity`) — **passed**.
3. `__enter__`: one INFO framing log record (`group_started`, `extra={"group": prompt}`); the
   entry `delay` is NOT slept here — it is applied lazily immediately before the group's first
   executed step, so a zero-step group is a quiet no-op → checkpoint — **passed**.
4. `g.step(text, tries=None, delay=None)`: validation as the facade → between-step pace: before
   the call, if at least one group step was already delegated (the internal delegation flag)
   and `speed` is declared → quiet `time.sleep(int((100 − speed) × 30) / 1000)`; before the
   FIRST group step → the group entry `delay` (when declared) → mark the delegation →
   `executor.execute(text, "action", self._open_page(), group=self,
   tries, delay)` → checkpoint: library-level pauses, never `slow_mo` (which cannot change
   mid-run) — **passed**.
5. `__exit__`: one INFO framing log record (`group_finished`); never suppresses; also runs on
   the exception path (the closing record is unconditional once entry logged).
6. **Output**: `traces` — one `GroupStepOutcome` per executed group step (appended by the
   executor), the recovery's row source.

### Trace: `StepExecutor.execute` (rewired cycle)

#### Chain
1. **Input**: `(step_text, step_type, page, group=None, tries=None, delay=None)`.
2. `on_step_started` → NEW: a declared `delay` sleeps quietly here (after the started event,
   before the cycle proceeds; a step never reached never pauses) → checkpoint: the pause is
   uniform for the first step, following steps and recovery rows (the recovery applies the row
   step's declared delay itself) — **passed**.
3. Identity (unchanged triple — C1), `SettleWindow(polling_timeout, polling_delay, tries)`,
   empty attempt history; a group step's URL bracket opens (`url_before = _read_url(page)` —
   recorded for the trace).
4. Cache hit → `settle(run_step_code, cached.code, page, window)` → failure → strict:
   classification-only path unchanged; non-strict + group: append the trace record (outcome
   failed, `url_after` read on the failure) → anchor record 0 (original cached code, formatted
   replay error, the replay URL pair) → `recovery.recover(group.prompt, group.traces,
   step_text, step_type, self._scenario, identity, attempt_history, page, window)` → healed ⇒
   continue as success; terminal `IncurableStepError` ⇒ the steering gate with the group
   context; non-strict + ordinary: the heal path exactly as today.
5. Cache miss → strict: the unchanged incurable miss; non-strict:
   `generator.generate(identity, step_text, step_type, self._scenario, group.prompt if group
   else None, page, attempt_history, window)` → `IncurableStepError` ⇒ group: the recovery
   delegation (as step 4) ⇒ ordinary: the steering gate as today.
6. Success path: append `ScenarioStep(sentence=step_text, group_prompt=group.prompt if group
   else "")` to `_scenario` (typed, permanent membership); a group step's trace record appended
   (outcome passed, the bracket's `url_after` read after execution).
7. `on_step_passed` / failure reporting (the one-render policy unchanged) / `on_step_finished`
   in the `finally` — unchanged.
8. **Output**: the executed step; the typed scenario context and the group traces grow by one.

#### Checkpoint Summary
- Routing precedence: strict → group recovery → ordinary heal; steering stays the terminal gate
  for a still-terminal group failure — passed.
- Group URL brackets: the executor brackets every group step with the URL pair regardless of
  outcome (a plain cache-hit pass gains the closing read — trace-only, no request impact).

### Trace: `PrettyPlay.__init__` (composition)

#### Chain
1. `load_config` → runtime → reporter → cache (unchanged).
2. `StepGenerator`, `StepHealer`, `StepSteering` (unchanged order/arguments) → NEW
   `GroupRecovery(self._runtime.config, self._runtime.provider, self._generator, self._cache,
   self._runtime.budgets, self._reporter)` → `StepExecutor(..., self._recovery, ...)` →
   checkpoint: the recovery shares the generator/cache/budgets/reporter of the test — one
   visibility point, one write-back store, one registry — **passed**.

## Algorithm Design

### `SettleWindow` / `settle` (polling)

**Responsibility**: bound the re-execution loop of one code unit by time or by count.

**Algorithm:**
```
1. count_bounded ⇔ tries is not None
2. enabled ⇔ (timeout set and > 0) OR count_bounded
3. settle: window.start()
4. IF window.count_bounded:
     executed ← 0
     LOOP:
       execute(code, page); success → return
       executed ← executed + 1
       IF window.enabled AND is_pollable_failure AND executed < window.tries:
         log settle_retry (INFO, attempt=executed, error); sleep(window.delay); continue
       raise
   ELSE (time mode — byte-identical to today):
     LOOP:
       execute(code, page); success → return
       IF window.enabled AND is_pollable_failure AND window.has_remaining():
         log settle_retry (INFO); sleep(window.delay); continue
       raise
```

**Errors:** exhaustion propagates the original failure object as-is — the classification/recovery
path decides.

`has_remaining` belongs to the time-bounded mode alone: the count-bounded loop checks its own
local counter (`executed < window.tries`) and never consults the clock — a count-bounded window
with polling disabled (`timeout=None`) has no time horizon at all, and `has_remaining` is never
called on it.

**Edge cases:** `tries=1` → single execution, no re-execution; count mode with polling disabled
(`timeout=None`) → still enabled; non-pollable failures never re-execute.

### `ScenarioStep` (llm)

**Responsibility**: the immutable unit of the scenario context.

**Algorithm:** pydantic v2, `kw_only`, `frozen`; `sentence: str = ""`, `group_prompt: str = ""`.
Appended by the executor, never rewritten (C13 honesty: membership is a property of the record,
never a mutation of the sentence).

### `GroupFailureClassification` + `parse_group_failure_classification` (llm)

**Algorithm (parse):**
```
1. text ← verdict_text.strip()
2. data ← json.loads(text); on ValueError → data ← json_repair.loads(text)
   (a salvage-library exception degrades — never crosses the boundary)
3. IF data is a dict AND its category/root_cause/earliest_step/recommendation are all str
   AND category ∈ {recoverable, product_defect, incurable}:
     return verdict(degraded=False)
4. ELSE return verdict(category=incurable, root_cause=text, earliest_step="",
                       recommendation="re-run the group step or check the provider answer",
                       degraded=True)
```

**Errors:** none raised — every failure mode degrades (the compliance-verdict counterpart raises
`ComplianceVerdictError`; the diagnosis counterpart degrades because a retry cycle is not worth a
hard stop and must never be granted on garbage).

**Edge cases:** markdown-fenced JSON (salvage handles); extra fields — ignored only when the four
required fields validate; `recoverable` never synthesized by the parse.

### `LLMProvider` generation rendering (both providers)

**Algorithm (request composition, shared builders):**
```
generation/regeneration/guided:
  sections ← [STEP TYPE + STEP]
  IF group_prompt non-empty: sections ← [.., "GROUP PROMPT:\n{group_prompt}"]   ← before PREVIOUS STEPS
  sections ← [.., PREVIOUS STEPS (typed records), PAGE SNAPSHOT, PAGE URL?, CHEAT SHEET,
              USER INSTRUCTIONS?, HISTORY?, RECOMMENDATION?, USER GUIDANCE?]
  PREVIOUS STEPS entry: group_prompt empty → "- {sentence}"      (byte-identical, C13)
                        group_prompt set   → "- {sentence} [group step — {group_prompt}]"
group diagnosis (new builder):
  sections ← [GROUP PROMPT, GROUP STEPS, STEP, HISTORY, PAGE SNAPSHOT,
              (SCREENSHOT rides the SDK image part), USER INSTRUCTIONS last]
  GROUP STEPS entry: trace.render() = "{sentence}\noutcome: {outcome}\nurl: {url_before} -> {url_after}",
                     entries joined by a blank line
```

### `RunBudgets` (cache)

**Algorithm:**
```
refresh_healing(identity): _healing_used[identity.filename] ← 0
open_group_cycle(group_key):
  used ← _group_cycles_used.get(group_key, 0)
  IF used >= _healing_limit: return False
  _group_cycles_used[group_key] ← used + 1; return True
```

**Edge cases:** two groups with the same prompt share one cap (the key is the prompt —
deliberate); the same group entered twice in one test shares its cap.

### `StepGenerator` group branches (engine)

**Algorithm:**
```
failed-check handler:
  append record(outcome=failed check, full failure text, URL pair)
  IF group_prompt non-empty:
    raise IncurableStepError(reason="group step check failed — the group recovery decides",
                             error=full failure text, code=candidate code)     ← unclassified
  ELSE: the ordinary decision table (classification, verdict kinds, one funded regeneration)

exhaustion handler:
  IF group_prompt non-empty:
    (code, error) ← last record facts (empty pair when no candidate ever ran)
    raise IncurableStepError(reason="group step generation budget exhausted — the group recovery decides",
                             error=error, code=code)                            ← unclassified
  ELSE: the ordinary exhaustion table
```

**Errors:** the raised `IncurableStepError` carries no verdict — the group diagnosis supplies the
verdict later; `LLMUnavailableError` and `ComplianceVerdictError` propagate unchanged (they are
not classification points).

### `GroupStepOutcome` (groups)

**Responsibility**: the verbatim trace unit; pydantic v2, `kw_only`, `frozen`; `identity` has no
neutral empty default → a required field (the `CachedStep.identity` precedent; the "empty
defaults" conventions line applies to the neutral-typed fields).

**Algorithm (render):** the sentence line (verbatim) → the outcome line (`outcome: passed |
failed`) → the URL line (`url: {url_before} -> {url_after}`). No collapsing, no truncation;
`identity` never renders.

### `classify_group_failure` routine (groups)

**Algorithm:**
```
1. snapshot ← page.aria_snapshot(); screenshot ← page.screenshot() when config.send_screenshots
2. group_steps ← [trace.render() for trace in traces]; history ← [record.render() for record in
   attempt_history]
3. verdict ← provider.classify_group_failure(prompt=GROUP_DIAGNOSIS_PROMPT (the frozen mirror of
   group_diagnosis.md after ---), user_instructions=config.classification_prompt, group_prompt,
   group_steps, step_text, history, snapshot, screenshot)
4. IF verdict.degraded: logger.warning("group_diagnosis_degraded",
   extra={"group": group_prompt, "answer": verdict.root_cause})
5. logger.info("group_diagnosed", extra={"group": group_prompt, "category": verdict.category,
   "earliest": verdict.earliest_step})
6. return verdict
```

**Errors:** `LLMUnavailableError` propagates — an explicit infrastructure failure, no retry.

### `GroupRecovery.recover` (groups)

**Algorithm:**
```
1. IF NOT budgets.open_group_cycle(group_prompt):
     raise IncurableStepError(step_text, "the per-group recovery cycle cap is exhausted", "",
       verdict=FailureVerdict("incurable", "the per-group recovery cycle cap is exhausted",
       "raise healing_attempts or rework the group"))
2. verdict ← classify_group_failure(config, provider, group_prompt, traces, step_text,
   step_type, attempt_history, page)   ← the routine logs the group_diagnosed INFO record
   IF verdict.category = product_defect:
     raise ProductDefectError(step_text, verdict.explanation-mapped, underlying error, mapped verdict)
   IF verdict.category = incurable:
     raise IncurableStepError(step_text, mapped explanation, underlying error, code=last code,
       verdict=mapped verdict)
3. row_start ← match verdict.earliest_step:
     exact == some trace.sentence → that trace's index
     exact == some previous_steps sentence of ANOTHER group (or an ordinary step)
       → raise IncurableStepError(verdict naming that step verbatim:
          explanation=f"the root lives outside the group — {sentence}")
     no match → the failed step itself (the last trace)
4. FOR each trace in traces[row_start …]: budgets.refresh_healing(trace.identity)
5. FOR each trace in traces[row_start …] (sequential, the failed step last):
     sleep(trace.delay) when declared                      ← quiet, library-level
     row_history ← the failed step's passed-in grown history | a fresh list anchored by record 0
                   (the cached code loaded via trace.identity; empty code when no cached step)
     row_window ← SettleWindow(config.polling_timeout, config.polling_delay, trace.tries)
     reporter.on_healing_started(trace.sentence, "recoverable")
     step ← generator.regenerate(trace.identity, trace.sentence, trace.step_type, previous_steps,
                                 group_prompt, page, row_history, verdict.recommendation, row_window)
       ↑ executes candidates immediately on the current page; gates and stores per step
     reporter.on_healed(trace.sentence, explanation)
     logger.info("group_row_recovered", extra={"group": group_prompt, "step": trace.sentence,
       "earliest": verdict.earliest_step})
   On IncurableStepError from a row step: the failure state is fresh (the row history grew)
   → GO TO 1 (a new cycle: cap-checked, diagnosis re-run)
6. return the failed step's healed CachedStep
```

**Verdict mapping (every terminal raise):** `category` as is; `explanation` ← `root_cause` plus
`(earliest affected step: {earliest_step})` when the quote named a group step; `recommendation` ←
`recommendation`. Authored reasons/explanations stay colon-free; one render per failure (C6).

**Errors:** `ProductDefectError` (anti-masking — the loud test failure), `IncurableStepError`
(out-of-mandate root, refused cycle, terminal diagnosis, or the cycle cap after repeat
failures), `LLMUnavailableError` (propagates; steering does not intercept it).

**Edge cases:** the failed step is the row start (single-step row); an earlier row step has no
cached code (record 0 anchors an empty code — the regeneration request still carries the
recommendation and framing); `previous_steps` empty (a group at the very start of a test).

### `StepGroup` (facade)

**Algorithm:**
```
__enter__:  log group_started (INFO, extra={"group": prompt}); return self
step/expect(text, tries=None, delay=None):
  _validate_tries/_validate_delay (shared with the facade methods)
  IF no step delegated yet AND group delay declared: sleep(delay)             ← lazy entry pause
  ELIF ≥1 step delegated AND speed declared: sleep(int((100 − speed) × 30) / 1000)
  mark a step delegated; executor.execute(text, kind, _open_page(), group=self, tries, delay)
__exit__:   log group_finished (INFO); never suppress
```

The first-step marker is an internal delegation flag — set when a `step`/`expect` call is about
to delegate to the executor, before the call. It is never read from `traces`: a first step that
dies without a trace record (an infrastructure or gate hard failure) must not re-arm the entry
pause for a later step of the same group.

**Edge cases:** zero steps → entry/exit records only, no pause, no trace; `speed=None` → no
between-step pauses; `delay=None` → no entry pause; both may combine.

### `StepExecutor.execute` (facade)

**Algorithm:** the nine contract steps; the deltas — the quiet `delay` after `on_step_started`;
the window built with `tries`; the group URL bracket; the group branch of step 4 (recovery
instead of the healer, trace appended before the delegation); the group framing input of step 5;
the intercept chain of step 6 (recovery first for a group step, steering the terminal gate,
both receiving the group context); the typed `ScenarioStep` append of step 7.

**Edge cases:** a group step in strict mode — the strict branch wins, no recovery, no framing;
`group=None` → every path byte-identical to today (C13 regression pin); an invalid `tries`/
`delay` never reaches the executor (facade validation).

## Cross-cutting Concerns

- **Error handling**: the taxonomy is closed (C6 — no new failure kinds); the group branches
  raise the unclassified `IncurableStepError` and the recovery authors verdicts for its terminal
  raises; the diagnosis degrade path never raises across the parse boundary; the traceback
  folding at the facade covers the new validation errors.
- **Logging**: `settle_retry` (INFO) covers both modes; `group_started`/`group_finished` (INFO)
  frame the block; `group_diagnosed` (INFO) per landed diagnosis (category, earliest step);
  `group_diagnosis_degraded` (WARNING) on the flag; `group_row_recovered` (INFO)
  per recovered step; the existing `compliance findings passed` (WARNING) and healing events
  unchanged. All records carry contextual `extra` metadata; the group prompt is treated exactly
  like step sentences under the secrets rule (C9).
- **Validation**: facade-level, loud, at the call — `tries` (positive non-bool int), `delay`
  (non-negative finite non-bool number), group `prompt` (non-empty), group `speed` (0–100
  non-bool int), `PRETTYPLAY_BROWSER_SPEED` (decimal integer 0–100) — every message names the
  parameter, the received value and the allowed form; no silent ignores.
- **Caching**: unchanged addressing (C1 — the group prompt never enters `StepIdentity`); every
  recovered row step passes the two-dimension compliance gate before its per-step write-back
  (C7); the recovery budgets live in process memory only.
- **Concurrency**: nothing new crosses threads — every step, pause and recovery re-execution
  runs on the caller thread; page work marshals through the driver worker as today; the
  `slow_mo` value is computed once at launch inside the driver thread.

## Usages Analysis

### `conventions`
- **What it provides**: the project's Python code and test rules (pydantic kw_only models,
  relative imports, logging, docstrings, test structure).
- **Where used**: every changed cell (global annotations).
- **Why chosen**: the single source of engineering rules.
- **How exactly**: `BrowserConfig.speed` validator, `ScenarioStep`/`GroupFailureClassification`/
  `GroupStepOutcome` models, the new `groups`/`recovery`/`diagnosis`/`outcome` modules, all tests.

### `pydantic` (config)
- **What it provides**: model/validator patterns for settings.
- **Where used**: `BrowserConfig.speed` (field + `field_validator` with the received value named).
- **Why chosen**: the config cell already validates through pydantic.
- **How exactly**: `field_validator("speed")` mirroring `_validate_name`.

### `playwright` (driver)
- **What it provides**: the genuine sync API rules — now including the pace section
  (`slow_mo` at launch/connect, the formula, the "never slow_mo for group pace" rule).
- **Where used**: `DriverSession._launch_engine` (`launch(slow_mo=…)`, `connect(endpoint,
  slow_mo=…)`), `StepGroup` between-step pauses (plain library sleeps).
- **Why chosen**: the driver cell renders every Playwright fact through this cook.
- **How exactly**: one `slow_mo` computation, two call sites; `time.sleep` for group pauses.

### `json_repair` (llm)
- **What it provides**: the salvage-once pattern for malformed JSON model answers; the group
  diagnosis answer is the second consumer with the conservative-degradation tail.
- **Where used**: `parse_group_failure_classification`.
- **Why chosen**: parity with the compliance verdict parse.
- **How exactly**: `json.loads` → one `repair_loads` → strict semantic validation → degrade.

### `openai` / `anthropic` (llm)
- **What it provides**: the SDK request/mapping patterns of both implementations.
- **Where used**: `generate_step_code` (new inputs), `classify_step_failure` (rename),
  `classify_group_failure` (new) in both providers.
- **Why chosen**: the parity requirement — both providers share `_request` builders.
- **How exactly**: `build_fields_text(+group_prompt)` with the typed `_format_previous_steps`;
  the new `build_group_diagnosis_fields`; the classification-model routing.

### `system_prompt` (engine, steering — `step_generation.md`)
- **What it provides**: the frozen generation system prompt (byte-identical content, C13).
- **Where used**: `SYSTEM_PROMPT` mirrors in `generator.py` and `steering.py` — the mirror
  comment paths update to the renamed file; prompt-mirror pins extend to the new paths.
- **Why chosen**: the single source of the generation prompt.
- **How exactly**: unchanged rendering; group framing rides the user content, never the system
  prompt.

### `cheat_sheet` (engine, steering — `step_cheatsheet.md`)
- Identical treatment: renamed file, byte-identical mirror constants (C13).

### `group_framing` (engine, groups, steering)
- **What it provides**: the additive framing contract — the GROUP PROMPT block before PREVIOUS
  STEPS and the permanent marking of group entries.
- **Where used**: `generate`/`regenerate` requests (engine), row regeneration requests (groups),
  guided requests (steering); rendered by the provider builders.
- **Why chosen**: the single source so the block structure and the marking change together.
- **How exactly**: the pinned render forms above; ordinary entries stay byte-identical.

### `group_diagnosis` (groups)
- **What it provides**: the diagnosis system prompt (the fixed answer JSON, the category
  calibration, the verbatim-quote rule).
- **Where used**: `GROUP_DIAGNOSIS_PROMPT` — the frozen mirror in `diagnosis.py` (the section
  after `---`, cell-owned like the engine mirrors; a prompt-mirror test pins it).
- **Why chosen**: content is the single source; the cell renders it verbatim.
- **How exactly**: applied as the system message of the one diagnosis request.

### `classification_prompt` / `compliance_prompt` (engine, inline)
- Unchanged (C13) — the inline practices stay inline; the classification prompt keeps serving
  `classify_step_failure`; the diagnosis uses `group_diagnosis`, not this prompt, as its system
  message (the classification *instructions* still ride the diagnosis user content).

### Imported Usages
- `recovery` from `prettyplay/engine/groups` — the facade annotations reference it for the group
  cycle the executor delegates to. Path: `prettyplay/engine/groups/.usages/recovery.md` (exists,
  matches the contract).
- `generation`, `healing` from `prettyplay/engine`, `taxonomy` from `prettyplay/failures`,
  `hooks` from `prettyplay/reporting`, `classification` from `prettyplay/llm` — pre-existing
  imports of the facade/engine; contents unchanged by this topic except as noted below.

## `.usages/` Update

All cell-level usage files were already updated by the apply stage; this design pass verified
them against the (post-fix) contracts — no further changes required.

### Cell: `prettyplay/config`
- **`configuration.md`** → current. The TOML example carries `speed = 100`, the env table row
  `PRETTYPLAY_BROWSER_SPEED`, the Pace section with the layering example and the loud-failure
  note.

### Cell: `prettyplay/engine/polling`
- **`settle.md`** → current. The "Count-bounded re-execution (tries)" section matches the
  contract (per-call counter, settle_retry records, no LLM budget).

### Cell: `prettyplay/llm`
- **`providers.md`** → current. The parity sentence names the four operations; the rename note,
  the typed scenario-context note and "The group diagnosis operation" section match the
  contracts. Note for the implementation agent: the section may optionally mention the
  `degraded` flag — not required, it is a library-internal detail.
- **`classification.md`** → current. The example calls `classify_step_failure`.

### Cell: `prettyplay/cache`
- **`budgets.md`** → current. The "Recovery budgets (groups)" section matches
  `refresh_healing`/`open_group_cycle`.

### Cell: `prettyplay/engine`
- **`generation.md`** → current after one fix of this review pass: the compliance-gate bullet
  named the effective generation model — corrected to the effective classification model, the
  llm contract's requirement and the provider implementations' behavior. The typed example and
  the "Group steps (framing, no per-step classification)" section match the engine contract.
- **`healing.md`** → current. The typed example and the group-never-reaches-the-healer rule.

### Cell: `prettyplay/engine/groups` (new)
- **`recovery.md`** → current and complete (when recovery runs, the cycle, reporting).

### Cell: `prettyplay/engine/steering`
- **`steering.md`** → current. The group-context note in the dialog section.

### Cell: `prettyplay` (facade)
- **`steps.md`** → current. "Step parameters" and "Groups" sections match the authoring surface.
- **`lifecycle.md`** → current. The "Group recovery" section matches the routing and budgets.

## Test Stack Trace

### General Setup

- Unit tests run without a browser: `PageFacade` is faked (a stub exposing `url`,
  `aria_snapshot()`, `screenshot()`); providers are fakes subclassing `LLMProvider` with
  canned answers; `StepCache` writes under `tmp_path`; `RunBudgets` real.
- The frozen-mirror pins extend: `step_generation.md`/`step_cheatsheet.md` mirror constants
  (byte-identity after the rename — C13), plus the new `group_diagnosis.md` mirror; the two
  renamed files' pins keep pointing at the same constants, only the path in the pin's comment
  changes.
- New fixtures: `scenario_records()` (a typed `list[ScenarioStep]` mix of ordinary and group
  entries), `group_traces()` (a `list[GroupStepOutcome]` over a 3-step group), a recovery-ready
  executor built with a fake provider/generator.

### Source File Registry

Under test: `prettyplay/config/models.py`, `prettyplay/config/loader.py`,
`prettyplay/driver/session.py`, `prettyplay/engine/polling/window.py`,
`prettyplay/engine/polling/settle.py`, `prettyplay/llm/models.py`,
`prettyplay/llm/provider.py`, `prettyplay/llm/_request.py`,
`prettyplay/llm/openai_provider.py`, `prettyplay/llm/anthropic_provider.py`,
`prettyplay/cache/budgets.py`, `prettyplay/engine/generator.py`,
`prettyplay/engine/healer.py`, `prettyplay/engine/classification.py`,
`prettyplay/engine/steering/steering.py`, `prettyplay/engine/groups/outcome.py`,
`prettyplay/engine/groups/diagnosis.py`, `prettyplay/engine/groups/recovery.py`,
`prettyplay/executor.py`, `prettyplay/groups.py`, `prettyplay/scenario.py`.

---

### Positive Tests

#### `test_browser_speed_loads_from_every_layer`

**Setup**: `tmp_path` pyproject with `[tool.prettyplay.browser] speed = 40`; monkeypatch env
`PRETTYPLAY_BROWSER_SPEED=70`; a `PrettyConfig(browser=BrowserConfig(speed=90))` overlay.

**Input**: three `load_config` calls — file only, file+env, file+env+overlay.

**Trace**:
```
load_config(pyproject)            # file layer
  → BrowserConfig(speed=40)       # validated 0–100
load_config(+env PRETTYPLAY_BROWSER_SPEED=70)
  → env wins over file → speed=70
load_config(+overlay BrowserConfig(speed=90))
  → explicit programmatic value wins → speed=90
```

**Assertions**:
```
config.browser.speed == 40 / 70 / 90 respectively
```

**Sufficiency**: SC2 — the pace is an ordinary layered setting; guards the merge reaching inside
the browser group for the new key.

---

#### `test_driver_launch_and_connect_pass_slow_mo`

**Setup**: a `DriverSession` with `Config(browser=BrowserConfig(speed=40))`; the Playwright
engines monkeypatched with recording fakes (local launch and ws connect cases).

**Input**: `open_context()` twice — once with an empty endpoint, once with a ws endpoint.

**Trace**:
```
open_context() → _launch() → _launch_engine(playwright)
  slow_mo = int((100 − 40) × 30) = 1800
  local: engine.launch(headless=True, slow_mo=1800)          # recorded
  remote: engine.connect("ws://…", slow_mo=1800)              # recorded
```

**Assertions**:
```
recorded launch kwargs["slow_mo"] == 1800; recorded connect kwargs["slow_mo"] == 1800
speed=100 → slow_mo == 0 (passed identically; behaviorally today's default)
```

**Sufficiency**: SC1 — the mapping and the every-launch-mode requirement; prevents a pace that
only slows one mode or drifts from the linear formula.

---

#### `test_settle_count_bounded_reexecutes_and_exhausts`

**Setup**: `SettleWindow(timeout=None, delay=0, tries=3)`; an `execute` stub failing twice with a
pollable error, then succeeding (case A) and always failing (case B); `is_pollable_failure`
satisfied by the error type.

**Input**: `settle(execute, "code", page_stub, window)`.

**Trace**:
```
settle → window.start()
  execute #1 → pollable failure → settle_retry logged → sleep(0)
  execute #2 → pollable failure → settle_retry logged → sleep(0)
  execute #3 → success → return            (case A: 3 executions total)
case B: execute #3 fails → executed(3) == tries(3) → raise the original failure
```

**Assertions**:
```
case A returns, execute.call_count == 3; case B raises the original error, call_count == 3
two settle_retry INFO records in the caplog in both cases; a fresh settle call with a new window
counts from zero again
```

**Sufficiency**: SC3/SC4 — the count bound replaces the time bound, retries are log-only, the
exhaustion propagates honestly; the per-call counter prevents budget multiplication.

---

#### `test_generate_group_step_suppresses_classification_and_raises_unclassified`

**Setup**: real `StepGenerator` with a fake provider: first candidate raises an `AssertionError`
that survives the window; the fake provider's `classify_step_failure` raises `AssertionError`
(must never be called); budgets real (`generation_attempts=1`).

**Input**: `generate(identity, "fill the email field", "action", scenario_records,
group_prompt="accept cookies…", page_stub, [], window)`.

**Trace**:
```
generate → try_generation ok → request (framing rendered) → settle → AssertionError
  → history record (failed check)
  → group branch: IncurableStepError(reason="group step check failed — the group recovery decides",
    code=candidate, error=full text, verdict=None)
```

**Assertions**:
```
pytest.raises(IncurableStepError); exc.verdict is None; exc.code == candidate code
provider.classify_step_failure not called; budgets.try_healing never drew
with group_prompt=None the ordinary path still classifies (the C13 counterpart fixture)
```

**Sufficiency**: pins the suppression contract — no classification request, no healing-funded
regeneration inside a group; the byte-identity pin guards the ordinary path.

---

#### `test_parse_group_failure_classification_valid_and_degraded`

**Setup**: none (pure function).

**Input**: a valid JSON answer; a single-quoted glitch; a prose answer; a wrong-label answer.

**Trace**:
```
parse('{"category":"recoverable","root_cause":"fill never landed","earliest_step":"fill the
email field","recommendation":"regenerate the fill"}') → verdict(degraded=False)
parse glitched JSON → json_repair salvage → same validation → verdict(degraded=False)
parse("the app is broken") → no JSON shape, salvage cannot shape it → degraded verdict
parse('{"category":"maybe", …}') → unknown label → degraded verdict
```

**Assertions**:
```
valid: category=="recoverable", degraded is False
degraded: category=="incurable", root_cause == the raw text, degraded is True, earliest_step==""
never recoverable from a degraded path
```

**Sufficiency**: the conservative degradation is the anti-masking backbone of the recovery
(SC8); the flag (D2) is what the routine's WARNING keys on.

---

#### `test_recover_reference_scenario_goes_green` (SC6)

**Setup**: fake provider: `classify_group_failure` answers recoverable with `earliest_step`
quoting the fill step; `generate_step_code` returns working code for the row (recorded calls);
real `RunBudgets(3, 2)`, real cache under `tmp_path`, fake page; `GroupStepOutcome` traces of
«accept the cookie banner» (passed), «fill the email field» (passed), «submit the form» (passed),
«the status shows order confirmed» (failed).

**Input**: `recovery.recover(group_prompt, traces, "the status shows order confirmed",
"assertion", previous_steps, identity, history, page, window)`.

**Trace**:
```
open_group_cycle → True (cycle 1)
diagnosis → recoverable, earliest = the fill step
row = fill, submit, check-the-status
refresh_healing × 3 → pools renewed
per row step: delay sleep → on_healing_started(sentence, "recoverable") → regenerate (framing +
  recommendation) → execute green → gate → cache write-back → on_healed(sentence, explanation)
return the healed step of the failed step
```

**Assertions**:
```
regenerate called 3 times in trace order with group_prompt and the diagnosis recommendation
every row step's cached code present under tmp_path; hooks saw 3× on_healing_started(category=
"recoverable") and 3× on_healed; a group_row_recovered INFO record per step; one
group_diagnosed INFO record with category "recoverable" naming the fill step as earliest
open_group_cycle consumed exactly one cycle; the returned step's identity == the failed step's
```

**Sufficiency**: SC6 — the reference scenario recovers end to end: the row is group-scoped, the
write-back is per step, the reporting is loud.

---

#### `test_group_authoring_block_pauses_and_traces`

**Setup**: a `PrettyPlay` with a monkeypatched executor recording `execute` calls; `time.sleep`
monkeypatched with a recorder.

**Input**:
```
with t.group("the checkout flow", speed=50, delay=2) as g:
    g.step("accept the cookie banner")
    g.step("fill the email field", delay=0.5)
```

**Trace**:
```
group() validates (prompt non-empty, speed 0–100, delay ≥ 0) → StepGroup bound
__enter__ → group_started INFO
g.step #1 → entry delay 2 s slept once → executor.execute(…, group=g, tries=None, delay=None)
g.step #2 → between-step pause int((100−50)×30)/1000 = 1.5 s → executor.execute(…, delay=0.5)
__exit__ → group_finished INFO
```

**Assertions**:
```
sleeps recorded: [2.0, 1.5]  (entry pause, pace pause — both slept by StepGroup; the step's own
declared delay is slept by the real executor cycle, which this facade-level test replaces)
the recording executor received group=self on both calls, delay=None/tries=None on the first,
delay=0.5 on the second; g.traces grew per executed step
zero steps ⇒ no sleep at all, both framing records still logged
t.step("outside") after the block → group=None (no ambient rerouting)
```

**Sufficiency**: the group pace/pause semantics (never slow_mo), the lazy entry pause (an empty
group never pauses), the trace growth and the addressing isolation a consumer observes.

---

#### `test_executor_routes_group_failure_to_recovery_before_steering`

**Setup**: an executor with: a cache hit whose code fails (pollable-exhausted), a recovery fake
returning a healed step, a steering fake that must stay uncalled; group object with traces.

**Input**: `execute("the status shows order confirmed", "assertion", page, group=g,
tries=None, delay=None)`.

**Trace**:
```
on_step_started → identity → window → cache hit → settle fails
→ trace appended (failed) → record 0 anchored → recovery.recover(...) → healed returned
→ ScenarioStep(sentence, group_prompt) appended → on_step_passed → on_step_finished(passed)
```

**Assertions**:
```
recovery.recover received (group_prompt, g.traces incl. the failed record, sentence, type,
scenario, identity, history, page, window); steering.steer not called
a second case: recovery raises IncurableStepError → steering.steer called with group_prompt;
a third: strict mode → recovery never called, classification-only path as today
```

**Sufficiency**: the routing precedence (strict → recovery → steering) is the contract's core
control flow; SC7's strict half is pinned by the third case.

---

#### `test_step_delay_pauses_quietly_after_started_event` (SC5)

**Setup**: an executor with a cache hit whose code executes green (a fake settle/run stub); a
hooks fake appending `("event", name)` and a monkeypatched `time.sleep` appending
`("sleep", seconds)` into one shared recording list.

**Input**: `execute("open the inbox", "action", page, group=None, tries=None, delay=1.5)`.

**Trace**:
```
on_step_started emitted → sleep(1.5) — the only sleep, quiet → identity → window →
cache hit → settle executes the cached code → success → ScenarioStep appended →
on_step_passed → on_step_finished(passed)
```

**Assertions**:
```
recorded == [("event", "on_step_started"), ("sleep", 1.5), ("event", "on_step_passed"),
             ("event", "on_step_finished")]
no log record of the pause exists (caplog carries only the lifecycle events) — the pause is quiet
```

**Sufficiency**: SC5 — pins the ordering (the started event fires, then the declared seconds
pass, then the code runs) and the quietness; the regression catches a pause moved before the
started event or after the code, or a pause that becomes output noise. A step never reached
never pauses is covered by the zero-steps case of the authoring test above.

---

### Negative Tests

#### `test_step_parameters_validate_loudly`

**Setup**: a `PrettyPlay` with a monkeypatched executor (must not be reached).

**Input**: `t.step("x", tries=0)`, `tries=-1`, `tries=True`, `tries="3"`, `delay=-0.5`,
`delay="slow"`, `t.expect(...)` variants, `t.group("")`, `t.group("p", speed=101)`,
`t.group("p", speed="fast")`, `t.group("p", delay=-1)`, `g.step("x", tries=0)`.

**Trace**:
```
step/expect/group/StepGroup.step → the shared validators → PrettyplayError raised at the call
```

**Assertions**:
```
each raises PrettyplayError; the message names the parameter, repr(value) and the allowed form
("tries", "0", "a positive integer" etc.); the executor was never invoked
```

**Sufficiency**: the loud-failure parity of the authoring surface; prevents silent coercion of
bad parameters into a broken run.

---

#### `test_recovery_refused_cycle_and_outside_root_are_terminal`

**Setup**: recovery with `RunBudgets(3, 2)` pre-exhausted for the group (case A: 2 cycles
already opened); fake diagnosis answering incurable with `earliest_step` quoting a step from
before the group (case B).

**Input**: `recover(...)` in both cases.

**Trace**:
```
A: open_group_cycle → False → IncurableStepError(verdict: cap exhausted, colon-free)
B: diagnosis ok → earliest_step matches a previous_steps sentence outside the group
   → IncurableStepError(verdict naming that step verbatim)
```

**Assertions**:
```
A: category "incurable", explanation contains "cycle cap"; no diagnosis request made
B: explanation contains the quoted outside sentence; no regeneration happened
both: exactly one render; the steering gate still receives the failure (executor-level fixture)
```

**Sufficiency**: SC8 — no doomed cycles: the cap and the out-of-mandate root end the run
honestly instead of looping.

---

#### `test_env_speed_out_of_range_fails_at_load`

**Setup**: monkeypatch env `PRETTYPLAY_BROWSER_SPEED=101` and `=abc`.

**Input**: `load_config(pyproject)`.

**Trace**:
```
env parse → not 0–100 / not a decimal integer → ConfigurationError
```

**Assertions**:
```
raises ConfigurationError; the message names browser.speed (the dotted setting — the loader
convention, never the env var name), the received value (101 / 'abc'), the accepted form;
the env var itself is proven by the monkeypatch setup; no Config constructed
```

**Sufficiency**: SC2's loud-failure half — the pace never silently ignores a bad value.

---

### Edge Case Tests

#### `test_typed_scenario_records_render_marked_and_plain`

**Setup**: `build_fields_text` with a mixed record list; `group_prompt=None` and set.

**Input**: `[ScenarioStep("open the login page", ""), ScenarioStep("fill the email field",
"the order form group")]`.

**Trace**:
```
build_fields_text(..., group_prompt=None)
  → PREVIOUS STEPS: "- open the login page\n- fill the email field [group step — the order
    form group]"      ← the membership is a property of the record, rendered even without a
    current group framing
build_fields_text(..., group_prompt="the order form group")
  → GROUP PROMPT block present immediately before PREVIOUS STEPS; the same marked entries
all-ordinary records, group_prompt=None → byte-identical to the pre-change render (C13 pin)
```

**Assertions**:
```
the ordinary-only render equals the pinned legacy string; the GROUP PROMPT block index ==
len-1 before PREVIOUS STEPS; the marked line contains the group prompt verbatim
```

**Sufficiency**: the permanent-marking semantics and the C13 byte-identity of untouched paths —
the strongest regression pin of the request layer.

---

#### `test_group_replay_is_llm_free_and_strict_never_recovers` (SC7)

**Setup**: a group whose three steps are all cached under `tmp_path`; a provider fake that
fails the test on any call; strict off (case A) and strict on with a failed cached hit
(case B — the classification-only path).

**Input**: `with t.group("the flow") as g: g.step(...); g.step(...); g.expect(...)`.

**Trace**:
```
A: three cache hits → settle executes → traces appended (passed) → no provider call
B: strict, a failed cached hit case added → classify_step_failure called once (the only LLM
   call), recovery.recover never invoked
```

**Assertions**:
```
A: provider.call_count == 0; three traces; steps green
B: recovery not called; the strict classification-only outcome raised by kind
```

**Sufficiency**: SC7 + C2 — group membership changes no cache address and no replay behavior;
strict keeps its classification-only path.

---

#### `test_repeat_failure_reenters_new_cycle_until_cap`

**Setup**: fake provider: diagnosis answers recoverable every time; `generate_step_code` always
fails the row; `RunBudgets(3, 2)`.

**Input**: `recover(...)`.

**Trace**:
```
cycle 1: open → diagnose → row → regeneration fails → IncurableStepError caught → cycle 2
cycle 2: open → diagnose → row → fails → cycle 3 refused → IncurableStepError(cycle cap
exhausted, verdict authored by the recovery)
```

**Assertions**:
```
open_group_cycle called exactly healing_limit(2)+1 times (the last refuses);
classify_group_failure called exactly 2 times; the terminal error carries the cap verdict;
no row step was written to the cache
```

**Sufficiency**: SC8's no-loops half — bounded autonomy (C5) with the fresh-pool-per-cycle
mechanism actually exercised across cycles.

---

#### `test_earliest_step_no_match_degrades_to_failed_step_row`

**Setup**: diagnosis answering recoverable with `earliest_step` matching nothing verbatim.

**Input**: `recover(...)`.

**Trace**:
```
no trace sentence equals the quote; no outside sentence equals it → row = the failed step only
```

**Assertions**:
```
regenerate called once, for the failed step's identity; refresh_healing called for it only
```

**Sufficiency**: the no-match fallback keeps the recovery group-scoped without dying.

---

#### `test_prompt_mirrors_after_rename`

**Setup**: the mirror constants of `generator.py`, `steering.py`, `diagnosis.py`.

**Input**: compare against `step_generation.md` (after `---`), `step_cheatsheet.md` (whole
file), `group_diagnosis.md` (after `---`).

**Trace**:
```
read practice file → extract per the mirror rule → assert equal to the constant
```

**Assertions**:
```
all mirrors byte-equal; the renamed files' content equals the pre-rename content (the git R100
record plus the pin)
```

**Sufficiency**: C13 — the frozen prompts never drift, and the rename changed no byte.

## Additional Instructions for the Implementation Agent

- Implement in the plan's artifact order (config → driver → polling → llm → cache → engine →
  groups → steering → facade); each cell's contract is self-contained after the previous ones.
- The two CODEMANIFEST fixes of this design pass (reporting `recoverable` vocabulary, the
  `degraded` flag) are already applied to the manifests — implement against them, not against
  the older `arch.md` text.
- Keep every `group_prompt=None` path byte-identical to today (requests, classification points,
  budgets) — the C13 pins are regression tests, not documentation.
- The exact render forms pinned here (GROUP PROMPT block, the `[group step — …]` marking, the
  GROUP STEPS trace render, the diagnosis block order, the group-branch reason strings) are the
  contract-level formats; the prompt-mirror and request-builder tests must pin them verbatim.
- `StepGroup` binds the owning test's lazy page opener at `group()` (an internal attribute); the
  declared constructor signature stays four-parameter — do not widen it.
- The loader change adds `browser.speed` to `_ALLOWED_TEXT` ("an integer 0-100 inclusive");
  an out-of-range env value fails at the pydantic field_validator and renders through the
  one-line-per-setting validation path naming the dotted setting — never the env var name.
- The `groups` cell modules mirror the steering pattern: frozen prompt constant owned by the
  cell, no runtime read of `.goga/`, relative imports per `conventions`.
- Update the public MkDocs surface (configuration, writing-steps, a groups page, self-healing)
  as a non-cell follow-up; the two cooks are already updated in the working tree.
- Project gates: `pytest tests/ -x` green, `ruff check` clean, `goga lint` 0 errors, `goga
  schema` unchanged except the new groups cell and its facade edge.
