# Plan: `step-group-and-step-params`

## Purpose

Implement pace control, step parameters and step groups of the prettyplay runtime against the
already-materialized contracts: the browser `speed` setting mapped to Playwright's native
`slow_mo`, the keyword-only `tries`/`delay` step parameters (the count-bounded settle mode and the
quiet pre-step pause), the typed scenario records (`ScenarioStep`), and the group authoring block
(`StepGroup`) with its diagnosis-driven recovery (the new `prettyplay/engine/groups` cell).

After implementation the library provides: layered pace configuration with loud validation;
per-step retry counts and start pauses; group blocks with entry/pace pauses and verbatim execution
traces; group-aware generation framing (GROUP PROMPT block, group-marked PREVIOUS STEPS) with the
internal classification points suppressed for group steps; one group-level diagnosis request per
recovery cycle with conservative degradation; a group-scoped, forward-only, compliance-gated
recovery row with bounded cycles and fresh healing pools; strict mode untouched; and every
`group_prompt=None`/`group=None` path byte-identical to today (C13 regression pins).

Strategy: implement in the dependency order config → driver → polling → llm → cache → engine →
groups → steering → facade (each cell's contract is self-contained after the previous ones); TDD
per task (contract tests first, then code, then logic tests); integration tests and the public
docs follow-up close the plan.

## Context

### Contract Surface

The contracts are the CODEMANIFEST files already materialized in the working tree (apply stage +
the two design-pass fixes: the reporting `recoverable` vocabulary and the `degraded` flag) and
verified by the design-review pass. **They are read-only for the implementation agent.**

**Entity: `ScenarioStep(sentence: str, group_prompt: str)`** (NEW)
- Type: class (pydantic model); Declared `location`: `prettyplay/llm/models.py`
- Facade obligation: importable from `prettyplay.llm`
- Properties: `sentence -> str` (raw sentence, verbatim), `group_prompt -> str` (empty — ordinary step)
- Semantics: the immutable unit of the scenario context; pydantic v2, `kw_only`, frozen, empty
  defaults; appended by the executor, never rewritten — membership is a property of the record
- Used by: executor (`_scenario`), generator, healer, steering, recovery (`previous_steps`)

**Entity: `GroupFailureClassification(category: str, root_cause: str, earliest_step: str, recommendation: str)`** (NEW)
- Type: class (pydantic model); Declared `location`: `prettyplay/llm/models.py`
- Facade obligation: importable from `prettyplay.llm`
- Properties: the four fields plus `degraded -> bool` — library-set (False on every parsed answer,
  True only on the degradation path); never part of the model answer
- Semantics: the verdict of a group diagnosis; `category` ∈ {recoverable, product_defect,
  incurable}; a degraded answer carries the conservative incurable with the raw answer in
  `root_cause`

**Routine: `parse_group_failure_classification(verdict_text: str) -> diagnosis: GroupFailureClassification`** (NEW)
- Declared `location`: `prettyplay/llm/models.py`; facade: importable from `prettyplay.llm`
- Semantics: the strict single parse point with conservative degradation — trim → `json.loads` →
  one `json_repair` salvage → semantic validation → valid: `degraded=False`; anything else:
  category incurable, `root_cause` = the raw answer, `earliest_step=""`, the conservative
  recommendation line, `degraded=True`. Never raises, never synthesizes recoverable

**Entity: `GroupStepOutcome(sentence: str, step_type: str, tries: int | None, delay: float | None, outcome: str, url_before: str, url_after: str, identity: StepIdentity)`** (NEW)
- Type: class (pydantic model); Declared `location`: `prettyplay/engine/groups/outcome.py`
- Facade obligation: importable from `prettyplay.engine.groups`
- Properties: the eight fields (`identity` required — no neutral empty default, the
  `CachedStep.identity` precedent)
- Methods: `render() -> record: str` — the sentence line (verbatim) → the outcome line → the URL
  line (`url: {url_before} -> {url_after}`); no collapsing, no truncation; `identity` never renders
- Semantics: one verbatim trace record of a group step execution; immutable once appended;
  pydantic v2, `kw_only`, frozen

**Routine: `classify_group_failure(config: Config, provider: LLMProvider, group_prompt: str, traces: list[GroupStepOutcome], step_text: str, step_type: str, attempt_history: list[StepAttempt], page: PageFacade) -> diagnosis: GroupFailureClassification`** (NEW)
- Declared `location`: `prettyplay/engine/groups/diagnosis.py`; facade: importable from
  `prettyplay.engine.groups`
- Semantics: compose and send the single diagnosis request — snapshot (+ screenshot when
  `send_screenshots`), GROUP STEPS renders, HISTORY renders, one port call with
  `GROUP_DIAGNOSIS_PROMPT` as the system prompt and the classification instructions as user
  instructions; logs WARNING `group_diagnosis_degraded` on the flag and INFO `group_diagnosed`
  (category, earliest step) always; `LLMUnavailableError` propagates (no retry)

**Entity: `GroupRecovery(config: Config, provider: LLMProvider, generator: StepGenerator, cache: StepCache, budgets: RunBudgets, reporter: StepReporter)`** (NEW)
- Type: class; Declared `location`: `prettyplay/engine/groups/recovery.py`
- Facade obligation: importable from `prettyplay.engine.groups`
- Methods: `recover(group_prompt, traces, step_text, step_type, previous_steps, identity, attempt_history, page, window) -> step: CachedStep` — the 7-step algorithm (cycle cap → diagnosis → verdict mapping/terminal raises → earliest-step row match → refresh_healing × row → sequential row regeneration with gate, write-back, healing events, log records → repeat-failure re-entry → healed return)
- Semantics: diagnosis-driven, group-scoped, forward-only recovery; one render per terminal
  failure; no new failure kinds; ordinary per-step pools never consumed; strict mode never invokes

**Entity: `StepGroup(prompt: str, speed: int | None, delay: float | None, executor: StepExecutor)`** (NEW)
- Type: class (context manager); Declared `location`: `prettyplay/groups.py`
- Facade obligation: importable from `prettyplay` (root facade `__all__`)
- Properties: `prompt -> str`, `traces -> list[GroupStepOutcome]` (appended by the executor)
- Methods: `step(text, tries, delay)`, `expect(text, tries, delay)` — validate like the facade,
  delegate to `executor.execute(..., group=self, tries, delay)`
- Semantics: entry/exit INFO framing records (`group_started`/`group_finished`); lazy entry pause
  before the first delegated step; between-step pause `int((100 − speed) × 30)` ms when speed
  declared — library-level sleeps, never slow_mo; never suppresses; the first-step marker is an
  internal delegation flag, never read from `traces`

**Entity: `BrowserConfig`** (CHANGED)
- `location`: `prettyplay/config/models.py`; facade: importable from `prettyplay.config` and `prettyplay`
- Gains `speed: int` (0–100 inclusive, default 100, loud `field_validator` rejecting non-int/bool
  and out-of-range values naming the received value) and the `speed -> int` property

**Routine: `load_config`** (CHANGED)
- `location`: `prettyplay/config/loader.py`
- Gains the `PRETTYPLAY_BROWSER_SPEED` env override (decimal integer, 0–100, loud on violation)
  and the `browser.speed` `_ALLOWED_TEXT` entry ("an integer 0-100 inclusive"); violations name
  the dotted setting `browser.speed` — never the env var name

**Entity: `DriverSession`** (CHANGED)
- `location`: `prettyplay/driver/session.py`
- `_launch_engine` computes `slow_mo = int((100 − speed) × 30)` and passes it on both the local
  `engine.launch(...)` and the remote `engine.connect(endpoint, slow_mo=...)` — every launch mode

**Entity: `SettleWindow`** (CHANGED)
- `location`: `prettyplay/engine/polling/window.py`; facade: importable from `prettyplay.engine.polling`
- Gains `tries: int | None` (default None — the time-bounded mode of today), the
  `count_bounded -> bool` property (`tries is not None`), and the two-mode `enabled` (a positive
  timeout OR count-bounded); `has_remaining` stays time-bounded-mode-only

**Routine: `settle`** (CHANGED)
- `location`: `prettyplay/engine/polling/settle.py`
- Gains the count-bounded loop head: a local per-call counter; re-execute iff
  `window.enabled and is_pollable_failure and executed < window.tries`; exhaustion propagates the
  failure as-is; `settle_retry` records uniform across modes

**Entity: `LLMProvider`** (CHANGED)
- `location`: `prettyplay/llm/provider.py`
- `generate_step_code` takes `previous_steps: list[ScenarioStep]` and `group_prompt: str | None`
  (between `step_type`/`snapshot` per the contract signature)
- `classify_failure` renamed `classify_step_failure` (nominal, behavior identical)
- NEW method `classify_group_failure(prompt, user_instructions, group_prompt, group_steps, step_text, attempt_history, snapshot, screenshot) -> GroupFailureClassification` — the fourth port operation, full parity in both providers

**Entity: `OpenAIProvider` / `AnthropicProvider`** (CHANGED)
- `location`: `prettyplay/llm/openai_provider.py`, `prettyplay/llm/anthropic_provider.py`
- All port changes above, full parity; the diagnosis request through the effective classification
  model; `build_group_diagnosis_fields` shared

**Routine: `build_fields_text` + new `build_group_diagnosis_fields`** (CHANGED/NEW, internal shared builders)
- `location`: `prettyplay/llm/_request.py`
- `build_fields_text` takes typed `previous_steps: list[ScenarioStep]` and `group_prompt`; the
  GROUP PROMPT section renders immediately before PREVIOUS STEPS when non-empty; the typed
  `_format_previous_steps` marks group entries (`- {sentence} [group step — {group_prompt}]`),
  ordinary entries stay `- {sentence}` (byte-identical, C13)
- `build_group_diagnosis_fields`: fixed order GROUP PROMPT, GROUP STEPS, STEP, HISTORY,
  PAGE SNAPSHOT, USER INSTRUCTIONS last (the screenshot rides the SDK image part)

**Entity: `RunBudgets`** (CHANGED)
- `location`: `prettyplay/cache/budgets.py`; facade: importable from `prettyplay.cache`
- Gains `refresh_healing(identity)` (reset the step's healing pool to the full `healing_limit`)
  and `open_group_cycle(group_key) -> allowed: bool` (per-group cycle cap = `healing_limit`, keyed
  by the group prompt, per test/registry lifetime)

**Entity: `StepGenerator`** (CHANGED)
- `location`: `prettyplay/engine/generator.py`; facade: importable from `prettyplay.engine`
- `generate(identity, step_text, step_type, previous_steps: list[ScenarioStep], group_prompt: str | None, page, attempt_history, window)` and `regenerate(..., previous_steps, group_prompt, page, attempt_history, recommendation, window)` — typed context, group framing on requests, the group branches at the failed-check and budget-exhaustion points (classification suppressed, unclassified `IncurableStepError`)

**Entity: `StepHealer`** (CHANGED)
- `location`: `prettyplay/engine/healer.py`
- `heal(step, error, step_text, step_type, previous_steps: list[ScenarioStep], page, attempt_history, window)` — typed records only; group steps never reach the healer

**Routine: `classify_step_failure` (engine)** (CHANGED)
- `location`: `prettyplay/engine/classification.py`
- Calls the renamed port method `classify_step_failure`; behavior identical

**Entity: `StepSteering`** (CHANGED)
- `location`: `prettyplay/engine/steering/steering.py`; facade: importable from `prettyplay.engine.steering`
- `steer(failure, identity, step_text, step_type, previous_steps: list[ScenarioStep], group_prompt: str | None, page, attempt_history)` — typed records and the group prompt ride `_guided_request` into `generate_step_code`; the dialog itself is unchanged

**Entity: `PrettyPlay`** (CHANGED)
- `location`: `prettyplay/scenario.py`
- `step`/`expect` gain keyword-only `tries: int | None` / `delay: float | None` with loud shared
  validation (`_validate_tries`/`_validate_delay`); NEW `group(prompt, speed=None, delay=None) -> StepGroup`; the composition wires `GroupRecovery` into the executor

**Entity: `StepExecutor`** (CHANGED)
- `location`: `prettyplay/executor.py`; facade: importable from `prettyplay`
- Constructor gains `recovery: GroupRecovery` (after `steering`, before `budgets`, per the
  contract); `execute(step_text, step_type, page, group=None, tries=None, delay=None)` — the quiet
  `delay` after `on_step_started`, the window built with `tries`, the group URL bracket, the group
  failure routing (strict → group recovery → ordinary heal; steering the terminal gate with group
  context), the typed `ScenarioStep` append, the group trace recording; `_scenario:
  list[ScenarioStep]`

### Re-exports

- `->PrettyConfig: {}`, `->BrowserConfig: {}`, `->StepHooks: {}` — unchanged embeddings on the
  root facade (`prettyplay/__init__.py` `__all__`); must stay importable from `prettyplay`.
  `StepGroup` joins the root `__all__` as a new facade entity (not an embedding — a declared
  entity of the root cell).

### Usages Context

- `conventions` (`.goga/usages/conventions.md`): the project's Python code and test rules —
  pydantic `kw_only` models, relative imports, logging through `prettyplay`, docstrings, test
  structure. Applies to every changed cell (global annotations).
- `pydantic` (`.goga/usages/cooks/pydantic.md`): model/validator patterns for settings — the
  `speed` field_validator mirrors the existing `_validate_name` idiom.
- `playwright` (`.goga/usages/cooks/playwright.md`): the genuine sync API rules, now including
  the pace section — `slow_mo` at launch/connect, the formula, and the "never slow_mo for group
  pace" rule (library-level `time.sleep` for group pauses).
- `json_repair` (`.goga/usages/cooks/json_repair.md`): the salvage-once pattern; the group
  diagnosis answer is the second consumer with the conservative-degradation tail.
- `openai` / `anthropic` (`.goga/usages/cooks/{openai,anthropic}.md`): the SDK request/mapping
  patterns of both provider implementations (parity by construction).
- `system_prompt` → `.goga/usages/prompts/step_generation.md` (renamed from `generation.md`,
  content byte-identical, C13): the frozen generation system prompt mirrored in `generator.py`
  and `steering.py` (`SYSTEM_PROMPT`); the mirror comment paths update to the renamed file.
- `cheat_sheet` → `.goga/usages/prompts/step_cheatsheet.md` (renamed from `cheatsheet.md`):
  identical treatment — byte-identical mirror constants.
- `group_framing` (`.goga/usages/prompts/group_framing.md`, NEW): the additive framing contract —
  the GROUP PROMPT block immediately before PREVIOUS STEPS and the permanent marking of group
  entries; the single source connected by engine, engine/groups and steering.
- `group_diagnosis` (`.goga/usages/prompts/group_diagnosis.md`, NEW): the diagnosis system prompt
  (the fixed answer JSON, the category calibration, the verbatim-quote rule) — the frozen mirror
  `GROUP_DIAGNOSIS_PROMPT` in `diagnosis.py` (the section after `---`, cell-owned like
  `SYSTEM_PROMPT`).
- `classification_prompt` / `compliance_prompt` (engine, inline): unchanged (C13); the
  classification prompt keeps serving `classify_step_failure`; the diagnosis uses
  `group_diagnosis` as its system message (the classification *instructions* still ride the
  diagnosis user content).

### Imported Usages

- `recovery` from `prettyplay/engine/groups` (imported by the facade): the group cycle the
  executor delegates to. Source: `prettyplay/engine/groups/.usages/recovery.md` (exists, matches
  the contract). Relevant to Tasks 13–14.
- `generation`, `healing` from `prettyplay/engine`, `taxonomy` from `prettyplay/failures`,
  `hooks` from `prettyplay/reporting`, `classification` from `prettyplay/llm` — pre-existing
  facade/engine imports; contents unchanged by this topic except as noted.

### Local Usages

None planned. All cell-level `.usages/` files were already updated by the apply stage and
verified current by the design review pass (config `configuration.md`, polling `settle.md`, llm
`providers.md`/`classification.md`, cache `budgets.md`, engine `generation.md`/`healing.md`,
steering `steering.md`, facade `steps.md`/`lifecycle.md`, groups `recovery.md`). No creation or
update tasks. The global practices renamed/added under `.goga/usages/prompts/` also already exist
in the working tree.

### External Dependencies

- `pydantic` v2 — models and validators (config, llm, groups).
- `playwright` (sync API) — `launch(slow_mo=…)`, `connect(endpoint, slow_mo=…)`.
- `json_repair` — the salvage-once parse tail.
- `openai` / `anthropic` SDKs — the provider implementations.
- `pytest` — the test framework; `ruff` — lint/format; `goga` CLI — `goga lint` / `goga schema`
  gates; `mkdocs` — the public docs follow-up.

### Interaction Diagram (verbatim from the design document)

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

### Data Flows (verbatim from the design document)

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

Initialization order (leaves → root): failures, reporting → config → {llm, driver} → {cache,
polling} → engine → {groups, steering} → facade. The new edge: `StepExecutor` (facade) receives
`GroupRecovery` (engine/groups), which itself consumes `StepGenerator` (engine) — the steering
pattern: a consumer of the engine is its child cell. No import cycles (schema-verified): engine
imports neither groups nor steering.

## Facts

- All 11 CODEMANIFESTs are already materialized in the working tree (config, driver, polling,
  llm, cache, engine, engine/groups NEW, steering, facade, reporting) — `goga lint` reports
  11 cells, 0 errors. They are read-only for the implementation agent.
- The renamed/global practices already exist in the working tree:
  `.goga/usages/prompts/step_generation.md` and `step_cheatsheet.md` (git R100 renames,
  content byte-identical), plus the new `group_framing.md` and `group_diagnosis.md`.
- `prettyplay/engine/groups/` currently contains only `CODEMANIFEST` and `.usages/recovery.md` —
  no Python code. The cell needs `__init__.py`, `outcome.py`, `diagnosis.py`, `recovery.py`.
- The current mirror pins in `tests/engine/test_generator.py` and
  `tests/engine/steering/test_steering.py` still reference the OLD practice paths
  (`generation.md`, `cheatsheet.md`) — those files no longer exist, so the pins must be repointed
  at the renamed paths (constants unchanged) early in the engine/steering tasks.
- The existing `_request.build_fields_text` takes `previous_steps: list[str]`; the executor's
  `_scenario` is `list[str]` — both become typed (`list[ScenarioStep]`).
- `SettleWindow` currently has a two-parameter constructor; `tries: int | None = None` keeps every
  existing call site byte-identical (the contract's "None — the time-bounded mode of today").
- The port method `classify_failure` is called today by `prettyplay/engine/classification.py`
  (the single call site); both providers implement it.
- The recovery's row step identities and windows come from the trace records
  (`trace.identity`, `trace.tries`, `trace.delay`) — the failed step's window parameter is not
  reused for earlier row steps.
- `StepGroup` binds the owning test's lazy page opener as an internal attribute (`_open_page`)
  set by `group()`; the declared constructor signature stays four-parameter.
- Group membership changes no step's cache address (C1 — the group prompt never enters
  `StepIdentity`); the worst-case bound of healing attempts per group step is
  `healing_limit × healing_limit` (cycles × pool) — finite.
- Project gates (from the design): `pytest tests/ -x` green, `ruff check` clean, `goga lint`
  0 errors, `goga schema` unchanged except the new groups cell and its facade edge.
- Environment note: the committed `.venv` symlinks point at a non-existent Homebrew path in this
  sandbox; the validation commands below are the project's canonical gates — run them in a working
  project environment (`pip install -e .[dev]` or equivalent if the runner environment lacks deps).

## Gap Analysis

- Missing contract entities (no code exists): `ScenarioStep`, `GroupFailureClassification`,
  `parse_group_failure_classification`, `GroupStepOutcome`, `classify_group_failure` (routine),
  `GroupRecovery`, `StepGroup`, `prettyplay/groups.py`, the whole `prettyplay/engine/groups/`
  Python cell, `LLMProvider.classify_group_failure`, `build_group_diagnosis_fields`,
  `RunBudgets.refresh_healing`/`open_group_cycle`/`_group_cycles_used`.
- Missing facade exposure: `StepGroup` on `prettyplay/__init__.py` `__all__`;
  `ScenarioStep`/`GroupFailureClassification`/`parse_group_failure_classification` on
  `prettyplay/llm/__init__.py` `__all__`; the groups cell facade
  (`prettyplay/engine/groups/__init__.py`).
- API mismatches: `generate_step_code` lacks `group_prompt` and takes untyped `previous_steps`;
  `classify_failure` not yet renamed (port + engine routine call site); `generate`/`regenerate`/
  `heal`/`steer` take `previous_steps: list[str]` and no `group_prompt`; `execute` lacks
  `group`/`tries`/`delay`; `StepExecutor` lacks `recovery`; `BrowserConfig` lacks `speed`;
  `SettleWindow` lacks `tries`/`count_bounded`; `load_config` lacks the env override and the
  `_ALLOWED_TEXT` entry; `_launch_engine` passes no `slow_mo`.
- Behavioral mismatches: no group branches in the generator (group steps would hit the ordinary
  classification table); no group routing in the executor (no trace records, no recovery
  delegation, no URL bracket, no typed scenario append, no quiet delay); `settle` has only the
  time-bounded loop; `enabled` is false when polling is disabled even with `tries` declared
  (count mode would be dead on default configs).
- Existing code that can be reused: the heal/steering intercept chain (`_steer_or_raise` — widen
  with `group_prompt`); the loader's scalar-parse-and-raise and one-line-per-setting validation
  render idioms; `_read_url`; the compliance gate and cache write-back paths inside the generator
  (the row regeneration reuses `regenerate` unchanged); the strict path (untouched);
  `StepAttempt`/`OUTCOME_ORIGINAL` for record 0 anchoring.
- Test coverage gaps: all 17 design test scenarios are new; the mirror pins point at renamed
  (missing) paths and must be repointed; no tests exist for any new entity; the executor/scenario
  suites must gain the group routing/authoring coverage while keeping every ordinary-path pin
  green (C13).
- No CODEMANIFEST changes are needed or allowed; no `.usages/` file changes are needed.

---

## Tasks

> **Package ordering rule**: coding tasks for each package are completed before starting the next. Within each coding task, contract tests are written first (TDD workflow).

### Task 1: `BrowserConfig.speed` — the pace setting with loud range validation (config)

The config cell's browser group gains the `speed` field: `int`, 0–100 inclusive, default 100
(full speed — behavior identical to today), validated by a pydantic `field_validator` that
rejects non-int/bool and out-of-range values with the received value named — never a silent
ignore. This mirrors the existing `_validate_name`/`_validate_endpoint` validator idiom of
`prettyplay/config/models.py` exactly. The field satisfies the `speed -> int` property
obligation. `BrowserConfig` is already re-exported by the root facade — no facade change.

Design trace (verified): `BrowserConfig(speed=40)` programmatic, or the file layer, or env
(added in Task 2) → pydantic validation: `speed: int = 100` with a `field_validator` rejecting
non-int/bool and values outside 0–100 (message names the received value) → the wrapped
`ConfigurationError` render (one line per invalid setting) — identical to the `name`/`endpoint`
validators. Loud-failure parity: the received value is named, never a silent ignore.

**Usages relevant to this task:**
- `conventions`: pydantic `kw_only` models, docstring rules, test structure.
- `pydantic`: the model/validator patterns for settings — `field_validator("speed")` mirroring
  `_validate_name`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/config/test_models.py` — `BrowserConfig` exposes `speed`
  (default 100); `from prettyplay.config import BrowserConfig` importable; constructing with
  `speed=0` and `speed=100` passes; constructing with `speed=-1`, `speed=101`, `speed=True`,
  `speed="fast"`, `speed=1.5` raises `ValidationError` whose message contains the received value
  (expected to fail at this stage — the field does not exist)
- [x] **Code**: add `speed: int = 100` to `BrowserConfig` in `prettyplay/config/models.py` with a
  `@field_validator("speed")` rejecting bool, non-int and out-of-range values (ValueError naming
  the received value, mirroring `_validate_name`); extend the class docstring Attributes with the
  pace semantics (100 — full speed, default; lower values slow the run linearly; 0 — the slowest
  supported pace; valid 0–100 inclusive)
- [x] **Interface verification**: `pytest tests/config/test_models.py -q` — all pass
- [x] **Logic tests**: positive — `speed=40` accepted and readable as `config.browser.speed`;
  edge — the 0 and 100 bounds pass; negative — the loud message names the received value for
  every rejected form (bool excluded explicitly: `isinstance(value, bool)` check before the int
  check)
- [x] **Debugging**: `pytest tests/config/ -q` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: `speed` is an int 0–100 with default 100; `kw_only`
  construction preserved (`model_config` unchanged); the root facade still imports
  (`python -c "from prettyplay import BrowserConfig"`)
- [x] **Lint**: `ruff check prettyplay/config tests/config && ruff format --check prettyplay/config tests/config` — fix formatting if necessary

### Task 2: `load_config` — the `PRETTYPLAY_BROWSER_SPEED` env override (config)

The loader gains the pace env override, mirroring the existing scalar env parse idioms:
`PRETTYPLAY_BROWSER_SPEED` parses as a decimal integer (the `PRETTYPLAY_POLLING_DELAY` float
idiom); an unparseable value raises at the env layer, an out-of-range value parses and fails at
the pydantic `field_validator` — both surface as `ConfigurationError` naming the dotted setting
(`browser.speed`), the received value and the accepted form. The loader change adds
`browser.speed` to `_ALLOWED_TEXT` ("an integer 0-100 inclusive") so the rendered allowed text is
authored, not the pydantic message. The message names the dotted setting, never the env var name
(the loader convention).

Design trace (verified): `load_config` merges the layers (file → env → programmatic overlay;
explicitly set values win) — the browser-group merge already reaches inside the group; the new
key rides the existing path. Env parse: mirrors the scalar-parse-and-raise and the
one-line-per-setting validation render idioms the loader already has.

**Usages relevant to this task:**
- `conventions`: loader error style — the dotted setting name, the received value, the allowed form.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/config/test_loader.py` — the env name is recognized
  (`PRETTYPLAY_BROWSER_SPEED`), the dotted name `browser.speed` is admitted by the loader's
  validation render vocabulary (expected to fail at this stage)
- [x] **Code**: extend the env override table and `_ALLOWED_TEXT` in `prettyplay/config/loader.py`
  with `browser.speed` → "an integer 0-100 inclusive"; parse `PRETTYPLAY_BROWSER_SPEED` as a
  decimal integer (int parse-and-raise idiom, mirroring the polling-delay scalar parse); update
  the loader docstring/env-name listing
- [x] **Interface verification**: `pytest tests/config/test_loader.py -q` — all pass
- [x] **Logic tests** — the two design scenarios, verbatim:
  - `test_browser_speed_loads_from_every_layer`: Setup — `tmp_path` pyproject with
    `[tool.prettyplay.browser] speed = 40`; monkeypatch env `PRETTYPLAY_BROWSER_SPEED=70`; a
    `PrettyConfig(browser=BrowserConfig(speed=90))` overlay. Input — three `load_config` calls
    (file only; file+env; file+env+overlay). Assertions — `config.browser.speed == 40 / 70 / 90`
    respectively (the merge reaches inside the browser group for the new key; explicitly set
    programmatic values win). Sufficiency: SC2 — the pace is an ordinary layered setting.
  - `test_env_speed_out_of_range_fails_at_load`: Setup — monkeypatch env
    `PRETTYPLAY_BROWSER_SPEED=101` and `=abc`. Assertions — raises `ConfigurationError`; the
    message names `browser.speed` (the dotted setting — the loader convention, never the env var
    name), the received value (101 / 'abc'), the accepted form; no `Config` constructed (the env
    var itself is proven by the monkeypatch setup). Sufficiency: SC2's loud-failure half — the
    pace never silently ignores a bad value. Implementation note (design-pinned): an out-of-range
    value parses at the env layer and fails at the pydantic `field_validator`, rendering through
    the one-line-per-setting validation path.
- [x] **Debugging**: `pytest tests/config/ -q` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: existing loader behaviors unchanged (removed-flat-key
  rejection, overlay merge, other env names); `python -c "from prettyplay.config import load_config"`
- [x] **Lint**: `ruff check prettyplay/config tests/config && ruff format --check prettyplay/config tests/config`

### Task 3: `DriverSession._launch_engine` — `slow_mo` at both launch and connect (driver)

The pace rides the browser start: `_launch_engine` reads `group = self._config.browser`, computes
`slow_mo = int((100 - group.speed) * 30)` and passes it on both call sites — the local
`engine.launch(..., slow_mo=slow_mo)` (plus the existing fullscreen `--start-maximized` arg) and
the remote `engine.connect(endpoint, slow_mo=slow_mo)` (wrapped with the endpoint-naming error).
`speed` is always a validated int 0–100, so `slow_mo` ∈ [0, 3000]; 100 → 0 (behaviorally
identical to today's no-argument form, SC1). One computation, two call sites — every launch mode
covered. One value per browser process, fixed for the run; the fixed-delays rule for generated
step code is untouched (slow_mo is a browser-process start parameter, not a code wait).

**Usages relevant to this task:**
- `playwright` (the cook's pace/slow_mo section): `launch`/`connect` both accept `slow_mo`; the
  percent→ms formula; "never slow_mo for group pace" (group pauses come in Task 14 as plain
  library sleeps).
- `configuration` (from Imports, `prettyplay/config/.usages/configuration.md`): the browser-group
  settings the session reads — the pace (`speed`) among them.
- `conventions`: driver-thread rules unchanged — the computation happens once at launch inside
  the driver thread.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/driver/test_session.py` — `DriverSession` with
  `Config(browser=BrowserConfig(speed=40))` launches and connects with the recorded `slow_mo`
  kwarg (expected to fail at this stage)
- [x] **Code**: in `prettyplay/driver/session.py` `_launch_engine` — compute
  `slow_mo = int((100 - group.speed) * 30)` after reading the browser group; pass
  `slow_mo=slow_mo` to `engine.connect(endpoint, slow_mo=slow_mo)` (inside the existing
  endpoint-wrapped try) and add `"slow_mo": slow_mo` to the local `launch_kwargs`; extend the
  method docstring with the pace sentence
- [x] **Interface verification**: `pytest tests/driver/test_session.py -q` — all pass
- [x] **Logic tests** — the design scenario, verbatim:
  - `test_driver_launch_and_connect_pass_slow_mo`: Setup — a `DriverSession` with
    `Config(browser=BrowserConfig(speed=40))`; the Playwright engines monkeypatched with
    recording fakes (local launch and ws connect cases). Input — `open_context()` twice — once
    with an empty endpoint, once with a ws endpoint. Trace — `open_context() → _launch() →
    _launch_engine(playwright)`; `slow_mo = int((100 − 40) × 30) = 1800`; local:
    `engine.launch(headless=True, slow_mo=1800)` recorded; remote:
    `engine.connect("ws://…", slow_mo=1800)` recorded. Assertions — recorded launch
    `kwargs["slow_mo"] == 1800`; recorded connect `kwargs["slow_mo"] == 1800`; `speed=100 →
    slow_mo == 0` (passed identically; behaviorally today's default). Sufficiency: SC1 — the
    mapping and the every-launch-mode requirement; prevents a pace that only slows one mode or
    drifts from the linear formula.
- [x] **Debugging**: `pytest tests/driver/ -q` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: the screen-mode branches, the channel launch, the
  endpoint-naming error and the dialog registration are unchanged;
  `python -c "from prettyplay.driver import DriverSession"`
- [x] **Lint**: `ruff check prettyplay/driver tests/driver && ruff format --check prettyplay/driver tests/driver`

### Task 4: `SettleWindow` count-bounded mode + the `settle` count loop (engine/polling)

The settle window gains the declared count mode beside the time window, and `settle` gains the
count-bounded loop head with a per-call local counter.

`SettleWindow(timeout, delay, tries=None)`: `count_bounded` ⇔ `tries is not None`; `enabled` ⇔
`(timeout is not None and timeout > 0) or count_bounded` — a count-bounded window with polling
disabled (`timeout=None`) is now enabled (otherwise count mode would be dead on default
configs); `has_remaining` belongs to the time-bounded mode alone (the count-bounded loop checks
its own local counter and never consults the clock) — pinned in the polling contract annotation.

`settle` (verified design algorithm):
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
The counter is local to the settle call — the cached code and every generated candidate each get
their own full count; `tries=1` → no re-execution. Exhaustion propagates the failure object
as-is; no LLM budget is ever consumed by re-execution.

**Usages relevant to this task:**
- `conventions`: the logger `prettyplay`, INFO records with `extra` metadata, test structure.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/engine/polling/test_window.py` — `SettleWindow` accepts the
  third parameter (`tries`), exposes `count_bounded` and `tries`; in
  `tests/engine/polling/test_settle.py` — `settle` honors a count-bounded window (expected to
  fail at this stage)
- [x] **Code**: `prettyplay/engine/polling/window.py` — `__init__(self, timeout, delay,
  tries: int | None = None)`, the `count_bounded` property, the two-mode `enabled`, docstrings
  (`has_remaining` documented as time-bounded-mode-only); `prettyplay/engine/polling/settle.py`
  — the count branch per the algorithm above (local `executed` counter, `executed <
  window.tries` bound, `settle_retry` records uniform with the time mode)
- [x] **Interface verification**: `pytest tests/engine/polling/ -q` — all pass
- [x] **Logic tests** — the design scenario, verbatim, plus the window pins:
  - `test_settle_count_bounded_reexecutes_and_exhausts`: Setup —
    `SettleWindow(timeout=None, delay=0, tries=3)`; an `execute` stub failing twice with a
    pollable error, then succeeding (case A) and always failing (case B);
    `is_pollable_failure` satisfied by the error type. Input — `settle(execute, "code",
    page_stub, window)`. Trace — `settle → window.start()`; execute #1 → pollable failure →
    settle_retry logged → sleep(0); execute #2 → pollable failure → settle_retry logged →
    sleep(0); execute #3 → success → return (case A: 3 executions total); case B: execute #3
    fails → executed(3) == tries(3) → raise the original failure. Assertions — case A returns,
    `execute.call_count == 3`; case B raises the original error, `call_count == 3`; two
    settle_retry INFO records in the caplog in both cases; a fresh settle call with a new window
    counts from zero again. Sufficiency: SC3/SC4 — the count bound replaces the time bound,
    retries are log-only, the exhaustion propagates honestly; the per-call counter prevents
    budget multiplication.
  - Window properties: `count_bounded` True/False by `tries`; `enabled` True with
    `timeout=None, tries=2` (count mode alive on default configs) and with `timeout=5.0,
    tries=None`; `has_remaining` never called by the count branch (time-mode-only semantics).
  - Time-mode byte-identity (C13 pin): the existing time-mode settle tests stay green unchanged.
- [x] **Debugging**: `pytest tests/engine/polling/ -q` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: `from prettyplay.engine.polling import SettleWindow, settle`
  facade importable; existing two-argument `SettleWindow(...)` constructions still valid
  (default `tries=None`)
- [x] **Lint**: `ruff check prettyplay/engine/polling tests/engine/polling && ruff format --check prettyplay/engine/polling tests/engine/polling`

### Task 5: `ScenarioStep`, `GroupFailureClassification`, `parse_group_failure_classification` (llm)

Three new models in `prettyplay/llm/models.py`, exported on the cell facade.

`ScenarioStep` (verified design algorithm): pydantic v2, `kw_only`, frozen; `sentence: str = ""`,
`group_prompt: str = ""`. Appended by the executor, never rewritten (C13 honesty: membership is a
property of the record, never a mutation of the sentence).

`parse_group_failure_classification` (verified design algorithm):
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
Errors: none raised — every failure mode degrades (the compliance-verdict counterpart raises
`ComplianceVerdictError`; the diagnosis counterpart degrades because a retry cycle is not worth a
hard stop and must never be granted on garbage). Edge cases: markdown-fenced JSON (salvage
handles); extra fields — ignored only when the four required fields validate; `recoverable` never
synthesized by the parse. `GroupFailureClassification` carries `degraded -> bool` (default False,
library-set — the D2 fix; the WARNING naming the degraded raw answer is logged by the calling
engine, not here; the parse itself never logs).

**Usages relevant to this task:**
- `json_repair`: the salvage-once pattern — `json.loads` → one `repair_loads` → strict semantic
  validation → degrade; parity with `parse_compliance_verdict`'s salvage-once flow with the
  conservative-degradation difference.
- `conventions`: pydantic `kw_only` models with empty defaults, frozen records, test structure.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/llm/test_models.py` — `from prettyplay.llm import
  ScenarioStep, GroupFailureClassification, parse_group_failure_classification`;
  `ScenarioStep(sentence=…, group_prompt=…)` kw_only construction; `GroupFailureClassification`
  exposes the five properties including `degraded` (expected to fail at this stage)
- [x] **Code**: add the two models and the parse routine to `prettyplay/llm/models.py` per the
  algorithms above (a frozen `GROUP_CATEGORIES = frozenset({"recoverable", "product_defect",
  "incurable"})` constant; the degraded verdict composed per the pinned constants); export the
  three names from `prettyplay/llm/__init__.py` `__all__`
- [x] **Interface verification**: `pytest tests/llm/test_models.py -q` — all pass
- [x] **Logic tests** — the design scenario, verbatim, plus the model pins:
  - `test_parse_group_failure_classification_valid_and_degraded`: Setup — none (pure function).
    Input — a valid JSON answer; a single-quoted glitch; a prose answer; a wrong-label answer.
    Trace — valid parses to `verdict(degraded=False)`; glitched JSON → json_repair salvage →
    same validation → `verdict(degraded=False)`; `parse("the app is broken")` → no JSON shape,
    salvage cannot shape it → degraded verdict; `parse('{"category":"maybe", …}')` → unknown
    label → degraded verdict. Assertions — valid: `category=="recoverable"`, `degraded is False`;
    degraded: `category=="incurable"`, `root_cause == the raw text`, `degraded is True`,
    `earliest_step==""`; never recoverable from a degraded path. Sufficiency: the conservative
    degradation is the anti-masking backbone of the recovery (SC8); the flag (D2) is what the
    routine's WARNING keys on.
  - `ScenarioStep` immutability: frozen — assignment raises; empty defaults construct.
  - Salvage-library failure degrades too (monkeypatch `repair_loads` to raise — a third-party
    exception never crosses the parse).
- [x] **Debugging**: `pytest tests/llm/ -q` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: pure function (no state, no I/O, deterministic); the parse
  never logs; the existing `parse_compliance_verdict` untouched
- [x] **Lint**: `ruff check prettyplay/llm tests/llm && ruff format --check prettyplay/llm tests/llm`

### Task 6: Port widening — typed context, `group_prompt`, the `classify_step_failure` rename, the `classify_group_failure` operation, both providers (llm)

The port contract changes: `generate_step_code` takes
`previous_steps: list[ScenarioStep]` and `group_prompt: str | None` (contract signature:
`prompt, user_instructions, step_text, step_type, previous_steps, group_prompt, snapshot,
page_url, screenshot, cheat_sheet, attempt_history, recommendation, guidance`); `classify_failure`
is renamed `classify_step_failure` (nominal — behavior identical); the new fourth operation
`classify_group_failure(prompt, user_instructions, group_prompt, group_steps, step_text,
attempt_history, snapshot, screenshot) -> GroupFailureClassification`.

Shared builders in `prettyplay/llm/_request.py` (verified design algorithm):
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
```
With `group_prompt=None` and ordinary records the built text is byte-identical to today (C13).
Both providers call the same shared builders and wrap the result with their SDK payload — parity
by construction. The diagnosis request rides `config.effective_classification_model`; a service
failure → `LLMUnavailableError` naming the provider (existing mapping); the answer parses
strictly through `parse_group_failure_classification` inside the provider implementation.

**Usages relevant to this task:**
- `openai` / `anthropic`: the SDK request/mapping patterns — the diagnosis user content wraps
  through `openai_user_content` / the anthropic blocks exactly like a classification request with
  a screenshot.
- `conventions`: parity requirements, docstring rules.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/llm/test_provider.py` — the port exposes
  `generate_step_code` (widened signature), `classify_step_failure` (renamed; `classify_failure`
  absent), `classify_group_failure`, `check_instruction_compliance`; in
  `tests/llm/test_openai_provider.py` and `tests/llm/test_anthropic_provider.py` — both
  implementations expose all four operations (expected to fail at this stage)
- [x] **Code**: `prettyplay/llm/provider.py` — widen `generate_step_code` (typed
  `previous_steps`, `group_prompt` in the contract position), rename `classify_failure` →
  `classify_step_failure`, add the `classify_group_failure` abstract method; `_request.py` —
  `build_fields_text(+group_prompt, typed previous_steps)` with the GROUP PROMPT section and the
  typed `_format_previous_steps`, plus the new `build_group_diagnosis_fields`;
  `openai_provider.py`/`anthropic_provider.py` — thread the new inputs, implement the diagnosis
  operation (classification model, SDK image part, parse through
  `parse_group_failure_classification`, SDK error → `LLMUnavailableError`)
- [x] **Interface verification**: `pytest tests/llm/ -q` — all pass
- [x] **Logic tests** — the design scenario, verbatim, plus the parity/rename pins:
  - `test_typed_scenario_records_render_marked_and_plain`: Setup — `build_fields_text` with a
    mixed record list; `group_prompt=None` and set. Input — `[ScenarioStep("open the login page",
    ""), ScenarioStep("fill the email field", "the order form group")]`. Trace — with
    `group_prompt=None`: `PREVIOUS STEPS: "- open the login page\n- fill the email field [group
    step — the order form group]"` (the membership is a property of the record, rendered even
    without a current group framing); with `group_prompt="the order form group"`: GROUP PROMPT
    block present immediately before PREVIOUS STEPS; the same marked entries; all-ordinary
    records with `group_prompt=None` → byte-identical to the pre-change render (C13 pin).
    Assertions — the ordinary-only render equals the pinned legacy string; the GROUP PROMPT block
    index == len-1 before PREVIOUS STEPS; the marked line contains the group prompt verbatim.
    Sufficiency: the permanent-marking semantics and the C13 byte-identity of untouched paths —
    the strongest regression pin of the request layer.
  - `build_group_diagnosis_fields` order pin: GROUP PROMPT, GROUP STEPS, STEP, HISTORY,
    PAGE SNAPSHOT, USER INSTRUCTIONS last; empty `user_instructions` — no block.
  - Both providers: the diagnosis request routes through the effective classification model and
    parses through `parse_group_failure_classification` (a garbage answer degrades inside the
    provider, never raises across the port); parity — identical user content in both.
  - The rename: `classify_step_failure` behavior identical to the former `classify_failure`
    (existing classification tests repointed, green).
  - Byte-identity (C13): every existing `build_fields_text`/provider test with ordinary inputs
    stays green unchanged.
- [x] **Debugging**: `pytest tests/llm/ -q` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: facade — `python -c "from prettyplay.llm import LLMProvider,
  create_provider, OpenAIProvider, AnthropicProvider"`; the one-request-per-attempt rule covers
  the diagnosis; the new inputs take no part in step addressing
- [x] **Lint**: `ruff check prettyplay/llm tests/llm && ruff format --check prettyplay/llm tests/llm`

### Task 7: `RunBudgets.refresh_healing` + `open_group_cycle` (cache)

The per-test attempt registry gains the recovery budget operations (verified design algorithm):
```
refresh_healing(identity): _healing_used[identity.filename] ← 0
open_group_cycle(group_key):
  used ← _group_cycles_used.get(group_key, 0)
  IF used >= _healing_limit: return False
  _group_cycles_used[group_key] ← used + 1; return True
```
`refresh_healing` renews the step's pool to the full `healing_limit` (ordinary per-step pools
untouched otherwise); `open_group_cycle` is keyed by the group prompt string, per test (registry
lifetime), capped by `healing_limit` — the recovery loop is never infinite (C5). Worst case
bounded: healing attempts per group step ≤ `healing_limit × healing_limit` (cycles × pool).
Booleans; no persistence, process memory only.

**Usages relevant to this task:**
- `conventions`: registry idioms (`identity.filename` keying), test structure.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/cache/test_budgets.py` — `RunBudgets` exposes
  `refresh_healing` and `open_group_cycle` with the contract signatures (expected to fail at
  this stage)
- [x] **Code**: add the two methods and the `_group_cycles_used: dict[str, int]` registry to
  `prettyplay/cache/budgets.py` per the algorithm; extend the class docstring (the cap counts
  recovery cycles per group per test, never per step)
- [x] **Interface verification**: `pytest tests/cache/test_budgets.py -q` — all pass
- [x] **Logic tests**: positive — `refresh_healing` renews an exhausted pool (a subsequent
  `try_healing` returns True for the full `healing_limit` count again); `open_group_cycle`
  returns True and increments. Negative — the cap: the (`healing_limit`+1)-th call returns False.
  Edge cases (design-pinned) — two groups with the same prompt share one cap (the key is the
  prompt — deliberate); the same group entered twice in one test shares its cap; a fresh
  `RunBudgets` instance (a new test) starts all counters at zero; ordinary `try_generation`/
  `try_healing` pools never consumed by the recovery operations
- [x] **Debugging**: `pytest tests/cache/ -q` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: `python -c "from prettyplay.cache import RunBudgets"`; the
  existing `try_generation`/`try_healing` behavior unchanged
- [x] **Lint**: `ruff check prettyplay/cache tests/cache && ruff format --check prettyplay/cache tests/cache`

### Task 8: Engine — typed context threading, `group_prompt`, the group branches, the routine rename, the mirror paths (engine)

The engine cell threads the typed scenario records and the group framing, and suppresses its
internal classification points for group steps.

Signatures (contract): `generate(identity, step_text, step_type, previous_steps:
list[ScenarioStep], group_prompt: str | None, page, attempt_history, window)` and
`regenerate(identity, step_text, step_type, previous_steps, group_prompt, page, attempt_history,
recommendation, window)`; `heal(step, error, step_text, step_type, previous_steps:
list[ScenarioStep], page, attempt_history, window)`; the `classify_step_failure` routine
(`prettyplay/engine/classification.py`) calls the renamed port method — behavior identical.

Group branches (verified design algorithm):
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
The raised `IncurableStepError` carries no verdict — the group diagnosis supplies the verdict
later; `LLMUnavailableError` and `ComplianceVerdictError` propagate unchanged (they are not
classification points). The compliance gate still guards every group candidate (a caching path,
not a classification point — C7): attempt → `_request` with framing → settle → green → gate →
high finding → record + retry; medium/low → WARNING + store. With `group_prompt=None` every
request, classification point and budget draw is byte-identical to today (C13 regression pin).
The healing loop of `regenerate` is unchanged (used by the recovery rows in Task 11). The
`SYSTEM_PROMPT`/`CHEAT_SHEET` mirror comment paths in `generator.py` update to
`step_generation.md`/`step_cheatsheet.md` (constants byte-identical — C13); the test pins
repoint (only the path in the pin's comment changes).

**Usages relevant to this task:**
- `system_prompt` (`step_generation.md`): the frozen generation system prompt — the mirror
  comment path updates, the constant does not change; group framing rides the user content,
  never the system prompt.
- `cheat_sheet` (`step_cheatsheet.md`): identical treatment.
- `group_framing`: the additive framing of generation/regeneration requests of group steps —
  rendered by the provider builders (Task 6); the generator passes `group_prompt` through.
- `classification` (from Imports, `prettyplay/llm/.usages/classification.md`): the healing
  decision categories of the ordinary decision table that stays behind the new group branches.
- `classification_prompt` / `compliance_prompt` (inline): unchanged — the classification prompt
  keeps serving `classify_step_failure` (the diagnosis uses `group_diagnosis`, not this prompt).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/engine/test_generator.py` — `generate`/`regenerate` accept
  the typed `previous_steps` and `group_prompt` (signature shape); in
  `tests/engine/test_healer.py` — `heal` accepts typed records; in
  `tests/engine/test_classification.py` — the routine calls the port's `classify_step_failure`
  (expected to fail at this stage)
- [x] **Code**: `prettyplay/engine/generator.py` — widen `generate`/`regenerate` (and the
  internal threading: `_generation_loop`, `_healing_loop`, `_request`, `_exhaustion_outcome`,
  the failed-check handler) with `previous_steps: list[ScenarioStep]` and `group_prompt:
  str | None`; add the two group branches per the algorithm (colon-free authored reasons,
  `verdict=None`, the code field carrying the candidate/last code); `healer.py` — typed
  `previous_steps`; `classification.py` — the renamed port call; update the mirror comment
  paths; repoint the practice-path constants in the test pins
- [x] **Interface verification**: `pytest tests/engine/test_generator.py tests/engine/test_healer.py tests/engine/test_classification.py -q` — all pass
- [x] **Logic tests** — the design scenario, verbatim, plus the C13 pins:
  - `test_generate_group_step_suppresses_classification_and_raises_unclassified`: Setup — real
    `StepGenerator` with a fake provider: first candidate raises an `AssertionError` that
    survives the window; the fake provider's `classify_step_failure` raises `AssertionError`
    (must never be called); budgets real (`generation_attempts=1`). Input — `generate(identity,
    "fill the email field", "action", scenario_records, group_prompt="accept cookies…",
    page_stub, [], window)`. Trace — generate → try_generation ok → request (framing rendered) →
    settle → AssertionError → history record (failed check) → group branch:
    `IncurableStepError(reason="group step check failed — the group recovery decides", code=
    candidate, error=full text, verdict=None)`. Assertions — `pytest.raises(IncurableStepError)`;
    `exc.verdict is None`; `exc.code == candidate code`; `provider.classify_step_failure` not
    called; `budgets.try_healing` never drew; with `group_prompt=None` the ordinary path still
    classifies (the C13 counterpart fixture). Sufficiency: pins the suppression contract — no
    classification request, no healing-funded regeneration inside a group.
  - The exhaustion branch: refused generation pool with `group_prompt` set → the unclassified
    `IncurableStepError` with the last-record facts (empty pair when no candidate ever ran);
    ordinary path → the ordinary exhaustion table (existing tests stay green).
  - The compliance gate still guards group candidates (medium/low finding → WARNING + store;
    high → record + retry — C7).
  - `heal` typed threading: the regeneration request renders the typed records (marked entries
    per membership) — group steps never reach the healer (executor-level pin comes in Task 13).
  - The rename: `classify_step_failure` (routine) still classifies through the renamed port
    method — existing classification tests repointed and green.
  - Mirror pins: the `SYSTEM_PROMPT`/`CHEAT_SHEET` constants equal the renamed practice files
    (byte-identity — C13; the pin paths now `step_generation.md`/`step_cheatsheet.md`).
- [x] **Debugging**: `pytest tests/engine/ -q` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: `python -c "from prettyplay.engine import StepGenerator,
  StepHealer, classify_step_failure"`; the ordinary decision table untouched behind the branches
- [x] **Lint**: `ruff check prettyplay/engine tests/engine && ruff format --check prettyplay/engine tests/engine`

### Task 9: The groups cell — infrastructure + `GroupStepOutcome` (engine/groups)

The new cell's structure and the verbatim trace unit. Create the package
`prettyplay/engine/groups/` with `__init__.py` (the facade — `__all__` listing the cell
contract names) and `outcome.py`.

`GroupStepOutcome` (design): pydantic v2, `kw_only`, frozen; `identity` has no neutral empty
default → a required field (the `CachedStep.identity` precedent; the "empty defaults"
conventions line applies to the neutral-typed fields). `render()` (verified algorithm): the
sentence line (verbatim) → the outcome line (`outcome: passed | failed`) → the URL line
(`url: {url_before} -> {url_after}`). No collapsing, no truncation; `identity` never renders.
One verbatim trace record of a group step's execution — the unit the GROUP STEPS block of the
diagnosis request renders; immutable once appended.

**Usages relevant to this task:**
- `conventions`: pydantic `kw_only` frozen models, relative imports, docstrings, test structure.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: create `tests/engine/groups/__init__.py` and
  `tests/engine/groups/test_outcome.py` — `from prettyplay.engine.groups import
  GroupStepOutcome` importable; kw_only construction with all eight fields; `render()` on the
  facade (expected to fail at this stage — the package does not exist)
- [x] **Code**: create `prettyplay/engine/groups/__init__.py` (docstring + `__all__` starting
  with `GroupStepOutcome`) and `prettyplay/engine/groups/outcome.py` — the model and `render()`
  per the algorithm, typed `identity: StepIdentity` (imported from `...cache`)
- [x] **Interface verification**: `pytest tests/engine/groups/test_outcome.py -q` — all pass
- [x] **Logic tests**: positive — `render()` produces exactly the three pinned lines with the
  sentence verbatim, `outcome: failed`/`outcome: passed`, `url: {before} -> {after}`; negative —
  `identity` never appears in the render; edge — no truncation of long sentences/URLs;
  immutability — assignment raises (frozen); `identity` required (construction without it raises)
- [x] **Debugging**: `pytest tests/engine/groups/ -q` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: facade —
  `python -c "from prettyplay.engine.groups import GroupStepOutcome"`; `goga schema` still
  reports the groups cell and its facade edge (no structural drift)
- [x] **Lint**: `ruff check prettyplay/engine/groups tests/engine/groups && ruff format --check prettyplay/engine/groups tests/engine/groups` — check and format clean on every Python file;
  the two `ruff format` complaints under the cell are the pre-existing read-only `.usages/*.md`
  markdown files (unchanged from the apply stage — same situation Task 8 documented; the plan
  forbids touching `.usages/` files)

### Task 10: `classify_group_failure` routine + the `GROUP_DIAGNOSIS_PROMPT` mirror (engine/groups)

The single diagnosis request of the recovery, in `prettyplay/engine/groups/diagnosis.py`.

The frozen mirror: `GROUP_DIAGNOSIS_PROMPT` — the section after `---` of
`.goga/usages/prompts/group_diagnosis.md`, cell-owned like `SYSTEM_PROMPT` (the groups cell
modules mirror the steering pattern: frozen prompt constant owned by the cell, no runtime read of
`.goga/`, relative imports per `conventions`); a prompt-mirror test pins it.

The routine (verified design algorithm):
```
1. snapshot ← page.aria_snapshot(); screenshot ← page.screenshot() when config.send_screenshots
2. group_steps ← [trace.render() for trace in traces]; history ← [record.render() for record in
   attempt_history]
3. verdict ← provider.classify_group_failure(prompt=GROUP_DIAGNOSIS_PROMPT, user_instructions=
   config.classification_prompt (when non-empty), group_prompt, group_steps, step_text, history,
   snapshot, screenshot)
4. IF verdict.degraded: logger.warning("group_diagnosis_degraded",
   extra={"group": group_prompt, "answer": verdict.root_cause})
5. logger.info("group_diagnosed", extra={"group": group_prompt, "category": verdict.category,
   "earliest": verdict.earliest_step})
6. return verdict
```
Errors: `LLMUnavailableError` propagates — an explicit infrastructure failure, no retry. Honest
inputs: the group prompt and every sentence reach the request verbatim (C8); the secrets rule
covers the group prompt (C9) — it flows only into requests/logs like step sentences.

**Usages relevant to this task:**
- `group_diagnosis`: the diagnosis system prompt — the frozen mirror source (the section after
  `---`); applied as the system message of the one diagnosis request.
- `conventions`: the frozen-mirror pattern, the logger `prettyplay` with `extra` metadata.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: create `tests/engine/groups/test_diagnosis.py` — `from
  prettyplay.engine.groups import classify_group_failure` importable; the routine returns the
  provider verdict; `GROUP_DIAGNOSIS_PROMPT` exists and equals the practice file section
  (expected to fail at this stage)
- [x] **Code**: create `prettyplay/engine/groups/diagnosis.py` — the frozen
  `GROUP_DIAGNOSIS_PROMPT` mirror (with the mirror comment naming the source path) and the
  routine per the algorithm; export `classify_group_failure` on the cell facade `__all__`
- [x] **Interface verification**: `pytest tests/engine/groups/test_diagnosis.py -q` — all pass
- [x] **Logic tests**: positive — the port receives `prompt=GROUP_DIAGNOSIS_PROMPT`, the
  classification instructions as `user_instructions` when non-empty, the group prompt verbatim,
  the GROUP STEPS renders (`trace.render()` per record), the HISTORY renders, the snapshot, the
  screenshot only when `send_screenshots`; the INFO `group_diagnosed` record carries
  `extra={"group", "category", "earliest"}` (the structured record of the landed diagnosis —
  design-review pin). Negative — a degraded verdict logs WARNING `group_diagnosis_degraded` with
  `extra={"group", "answer"}` (the raw answer rides `root_cause`) and still returns the verdict;
  `LLMUnavailableError` propagates untouched (no retry, no swallow). Edge — empty
  `user_instructions` → the request carries no instructions block (provider-side rendering)
- [x] **Debugging**: `pytest tests/engine/groups/ -q` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: facade —
  `python -c "from prettyplay.engine.groups import classify_group_failure"`; the mirror constant
  byte-equals the practice section
- [x] **Lint**: `ruff check prettyplay/engine/groups tests/engine/groups && ruff format --check prettyplay/engine/groups tests/engine/groups`

### Task 11: `GroupRecovery.recover` — the diagnosis-driven recovery engine (engine/groups)

The recovery engine, in `prettyplay/engine/groups/recovery.py`. `GroupRecovery(config, provider,
generator, cache, budgets, reporter)` — the recovery shares the generator/cache/budgets/reporter
of the test.

`recover(group_prompt, traces, step_text, step_type, previous_steps, identity, attempt_history,
page, window) -> step: CachedStep` (verified design algorithm):
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
Verdict mapping (every terminal raise): `category` as is; `explanation` ← `root_cause` plus
`(earliest affected step: {earliest_step})` when the quote named a group step; `recommendation`
← `recommendation`. Authored reasons/explanations stay colon-free; one render per failure (C6).
Errors: `ProductDefectError` (anti-masking — the loud test failure), `IncurableStepError`
(out-of-mandate root, refused cycle, terminal diagnosis, or the cycle cap after repeat
failures), `LLMUnavailableError` (propagates; steering does not intercept it). Edge cases: the
failed step is the row start (single-step row); an earlier row step has no cached code (record 0
anchors an empty code — the regeneration request still carries the recommendation and framing);
`previous_steps` empty (a group at the very start of a test). The recovery re-executions never
mutate `StepGroup.traces` (the traces list is a snapshot for the diagnosis; later diagnoses see
the honest original outcomes, and the fresh failure rides the attempt history). The row step's
own window and identity come from its trace; the failed step's window parameter is not reused
for earlier row steps.

**Usages relevant to this task:**
- `group_framing`: the row regeneration requests carry the framing (`group_prompt` passed into
  `regenerate`).
- `group_diagnosis` (via the Task 10 routine): the diagnosis the recovery opens every cycle with.
- `conventions`: the logger records, the colon-free authored reasons, test structure.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: create `tests/engine/groups/test_recovery.py` — `from
  prettyplay.engine.groups import GroupRecovery` importable; `recover` signature per the
  contract; returns the healed `CachedStep` of the failed step (expected to fail at this stage)
- [x] **Code**: create `prettyplay/engine/groups/recovery.py` — `GroupRecovery` per the
  algorithm above (the exact-match earliest-step resolution against `trace.sentence` first, then
  against `previous_steps` sentences whose record is NOT a member of this group; the per-row
  histories with record 0 anchored by the cached code loaded via `trace.identity` —
  `OUTCOME_ORIGINAL`, empty error when no cached step exists; the cycle re-entry on a row
  `IncurableStepError`); export `GroupRecovery` on the cell facade `__all__`
- [x] **Interface verification**: `pytest tests/engine/groups/test_recovery.py -q` — all pass
- [x] **Logic tests** — the four design scenarios, verbatim:
  - `test_recover_reference_scenario_goes_green` (SC6): Setup — fake provider:
    `classify_group_failure` answers recoverable with `earliest_step` quoting the fill step;
    `generate_step_code` returns working code for the row (recorded calls); real
    `RunBudgets(3, 2)`, real cache under `tmp_path`, fake page; `GroupStepOutcome` traces of
    «accept the cookie banner» (passed), «fill the email field» (passed), «submit the form»
    (passed), «the status shows order confirmed» (failed). Input — `recovery.recover(
    group_prompt, traces, "the status shows order confirmed", "assertion", previous_steps,
    identity, history, page, window)`. Trace — `open_group_cycle → True (cycle 1)`; diagnosis →
    recoverable, earliest = the fill step; row = fill, submit, check-the-status;
    `refresh_healing × 3` → pools renewed; per row step: delay sleep →
    `on_healing_started(sentence, "recoverable")` → regenerate (framing + recommendation) →
    execute green → gate → cache write-back → `on_healed(sentence, explanation)`; return the
    healed step of the failed step. Assertions — regenerate called 3 times in trace order with
    group_prompt and the diagnosis recommendation; every row step's cached code present under
    tmp_path; hooks saw 3× `on_healing_started(category="recoverable")` and 3× `on_healed`; a
    `group_row_recovered` INFO record per step; one `group_diagnosed` INFO record with category
    "recoverable" naming the fill step as earliest; `open_group_cycle` consumed exactly one
    cycle; the returned step's identity == the failed step's. Sufficiency: SC6 — the reference
    scenario recovers end to end: the row is group-scoped, the write-back is per step, the
    reporting is loud.
  - `test_recovery_refused_cycle_and_outside_root_are_terminal`: Setup — recovery with
    `RunBudgets(3, 2)` pre-exhausted for the group (case A: 2 cycles already opened); fake
    diagnosis answering incurable with `earliest_step` quoting a step from before the group
    (case B). Input — `recover(...)` in both cases. Trace — A: `open_group_cycle → False →
    IncurableStepError(verdict: cap exhausted, colon-free)`; B: diagnosis ok → earliest_step
    matches a previous_steps sentence outside the group → `IncurableStepError(verdict naming
    that step verbatim)`. Assertions — A: category "incurable", explanation contains "cycle
    cap"; no diagnosis request made; B: explanation contains the quoted outside sentence; no
    regeneration happened; both: exactly one render. Sufficiency: SC8 — no doomed cycles: the
    cap and the out-of-mandate root end the run honestly instead of looping. (The
    executor-level half — "the steering gate still receives the failure" — lands in Task 13.)
  - `test_repeat_failure_reenters_new_cycle_until_cap`: Setup — fake provider: diagnosis answers
    recoverable every time; `generate_step_code` always fails the row; `RunBudgets(3, 2)`.
    Input — `recover(...)`. Trace — cycle 1: open → diagnose → row → regeneration fails →
    `IncurableStepError` caught → cycle 2; cycle 2: open → diagnose → row → fails → cycle 3
    refused → `IncurableStepError(cycle cap exhausted, verdict authored by the recovery)`.
    Assertions — `open_group_cycle` called exactly `healing_limit(2)+1` times (the last
    refuses); `classify_group_failure` called exactly 2 times; the terminal error carries the
    cap verdict; no row step was written to the cache. Sufficiency: SC8's no-loops half —
    bounded autonomy (C5) with the fresh-pool-per-cycle mechanism actually exercised across
    cycles.
  - `test_earliest_step_no_match_degrades_to_failed_step_row`: Setup — diagnosis answering
    recoverable with `earliest_step` matching nothing verbatim. Input — `recover(...)`. Trace —
    no trace sentence equals the quote; no outside sentence equals it → row = the failed step
    only. Assertions — regenerate called once, for the failed step's identity;
    `refresh_healing` called for it only. Sufficiency: the no-match fallback keeps the recovery
    group-scoped without dying.
  - Edge pins: a single-step row (the failed step is the row start); an earlier row step with
    no cached code (record 0 anchors an empty code); `product_defect` raises
    `ProductDefectError` carrying the mapped verdict (anti-masking); the traces list object is
    not mutated by the recovery.
- [x] **Debugging**: `pytest tests/engine/groups/ -q` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: facade —
  `python -c "from prettyplay.engine.groups import GroupRecovery, GroupStepOutcome,
  classify_group_failure"`; the ordinary per-step healing pools of non-group steps are never
  consumed (the row refreshes only its own identities)
- [x] **Lint**: `ruff check prettyplay/engine/groups tests/engine/groups && ruff format --check prettyplay/engine/groups tests/engine/groups`

### Task 12: `StepSteering.steer` — typed context + the group prompt (engine/steering)

The steering dialog's request composition widens; the dialog itself is unchanged. `steer(failure,
identity, step_text, step_type, previous_steps: list[ScenarioStep], group_prompt: str | None,
page, attempt_history)` — a guidance message builds the request via `_guided_request`, now
passing the typed `previous_steps` and `group_prompt` into `generate_step_code`; the framing
renders per `group_framing` when non-empty (the GROUP PROMPT block and the group-marked scenario
context). The banner, the commands, the confirmation flow and the gate are unchanged. Output:
healed step or None — unchanged semantics. The `SYSTEM_PROMPT`/`CHEAT_SHEET` mirror comment paths
in `steering.py` update to `step_generation.md`/`step_cheatsheet.md` (constants byte-identical —
C13); the steering test pins repoint.

**Usages relevant to this task:**
- `group_framing`: the guided requests of a group step carry the framing — the single source
  with the engine and groups cells.
- `system_prompt` / `cheat_sheet` (renamed paths): the frozen mirrors — comment paths update,
  constants unchanged.
- `conventions`: request composition rules, test structure.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/engine/steering/test_steering.py` — `steer` accepts the typed
  `previous_steps` and the `group_prompt` parameter (signature shape); the guided request
  threads them into `generate_step_code` (expected to fail at this stage)
- [x] **Code**: `prettyplay/engine/steering/steering.py` — widen `steer` and `_guided_request`
  (`previous_steps: list[ScenarioStep]`, `group_prompt: str | None` in the contract position);
  pass both into `generate_step_code`; update the mirror comment paths; repoint the practice
  paths in the test pins
- [x] **Interface verification**: `pytest tests/engine/steering/ -q` — all pass
- [x] **Logic tests**: positive — a guided request of a group step carries `group_prompt` and
  the typed records (the provider renders the GROUP PROMPT block and the marked entries);
  negative/byte-identity (C13) — with `group_prompt=None` and ordinary records the guided
  request payload is byte-identical to today (the ordinary dialog tests stay green unchanged);
  edge — the dialog flow (banner, commands, y/N confirmation, rejected-candidate records) is
  unchanged; the mirror pins green against the renamed paths
- [x] **Debugging**: `pytest tests/engine/steering/ -q` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: `python -c "from prettyplay.engine.steering import
  StepSteering"`; the gate still guards the write-back; interactive attempts still consume no
  budgets
- [x] **Lint**: `ruff check prettyplay/engine/steering tests/engine/steering && ruff format --check prettyplay/engine/steering tests/engine/steering`

### Task 13: `StepExecutor` — the rewired cycle + the composition wiring (facade)

The executor owns the new routing. Constructor gains `recovery: GroupRecovery` (contract order:
`cache_key, cache, generator, healer, steering, recovery, budgets, reporter, config, provider`).
`execute(step_text, step_type, page, group=None, tries=None, delay=None)` (verified design
trace, the deltas):
1. `on_step_started` → NEW: a declared `delay` sleeps quietly here (after the started event,
   before the cycle proceeds; a step never reached never pauses) — uniform for the first step,
   following steps and recovery rows (the recovery applies the row step's declared delay itself).
2. Identity (unchanged triple — C1), `SettleWindow(polling_timeout, polling_delay, tries)`,
   empty attempt history; a group step's URL bracket opens (`url_before = _read_url(page)` —
   recorded for the trace).
3. Cache hit → `settle(run_step_code, cached.code, page, window)` → failure → strict: the
   classification-only path unchanged; non-strict + group: append the trace record (outcome
   failed, `url_after` read on the failure) → anchor record 0 (original cached code, formatted
   replay error, the replay URL pair) → `recovery.recover(group.prompt, group.traces, step_text,
   step_type, self._scenario, identity, attempt_history, page, window)` → healed ⇒ continue as
   success; terminal `IncurableStepError` ⇒ the steering gate with the group context;
   non-strict + ordinary: the heal path exactly as today.
4. Cache miss → strict: the unchanged incurable miss; non-strict: `generator.generate(identity,
   step_text, step_type, self._scenario, group.prompt if group else None, page, attempt_history,
   window)` → `IncurableStepError` ⇒ group: the recovery delegation (as step 3) ⇒ ordinary: the
   steering gate as today.
5. Success path: append `ScenarioStep(sentence=step_text, group_prompt=group.prompt if group
   else "")` to `_scenario` (typed, permanent membership); a group step's trace record appended
   (outcome passed, the bracket's `url_after` read after execution).
6. `on_step_passed` / failure reporting (one-render policy unchanged) / `on_step_finished` in the
   `finally` — unchanged.

`_steer_or_raise` widens with `group_prompt`. `_scenario: list[ScenarioStep]` (typed). Routing
precedence: strict → group recovery → ordinary heal; steering stays the terminal gate for a
still-terminal group failure. Group URL brackets: the executor brackets every group step with
the URL pair regardless of outcome (a plain cache-hit pass gains the closing read — trace-only,
no request impact). `group=None` → every path byte-identical to today (C13 regression pin); an
invalid `tries`/`delay` never reaches the executor (facade validation, Task 14). A group step in
strict mode — the strict branch wins, no recovery, no framing. Since `StepGroup` lands in Task
14, type the parameter without importing it at runtime (a `TYPE_CHECKING` import or the
duck-typed attributes `group.prompt`/`group.traces` suffice; the contract type is `StepGroup |
None`).

The composition (`PrettyPlay.__init__`, contract algorithm step 5–6): construct
`GroupRecovery(self._runtime.config, self._runtime.provider, self._generator, self._cache,
self._runtime.budgets, self._reporter)` and pass it to `StepExecutor` in the contract position.

**Usages relevant to this task:**
- `recovery` (from Imports, `prettyplay/engine/groups/.usages/recovery.md`): the group cycle the
  executor delegates to — when recovery runs, the cycle, the reporting.
- `generation` / `healing` (from Imports): the engine cycles the ordinary paths delegate to.
- `taxonomy` (from Imports): the failure kinds the executor propagates.
- `hooks` (from Imports, `prettyplay/reporting/.usages/hooks.md`): the hook contract of the
  events the executor's cycle reports — unchanged by the group routing (the recovery reuses
  on_healing_started/on_healed).
- `conventions`: the logger, the one-render policy, test structure.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/test_executor.py` — `StepExecutor` accepts `recovery`;
  `execute` accepts `group`, `tries`, `delay`; the typed `_scenario` grows `ScenarioStep`
  records (expected to fail at this stage)
- [x] **Code**: `prettyplay/executor.py` — the constructor param, the rewired `execute` per the
  trace above (the quiet delay, the window with `tries`, the group URL bracket, the trace-record
  appends on failure and success, the group routing with record-0 anchoring before the recovery
  delegation, the widened `_steer_or_raise`, the typed `_scenario` append);
  `prettyplay/scenario.py` — construct and wire `GroupRecovery` into `StepExecutor`
- [x] **Interface verification**: `pytest tests/test_executor.py -q` — all pass
- [x] **Logic tests** — the two design scenarios, verbatim, plus the C13 pins:
  - `test_executor_routes_group_failure_to_recovery_before_steering`: Setup — an executor with:
    a cache hit whose code fails (pollable-exhausted), a recovery fake returning a healed step,
    a steering fake that must stay uncalled; group object with traces. Input — `execute("the
    status shows order confirmed", "assertion", page, group=g, tries=None, delay=None)`. Trace —
    `on_step_started → identity → window → cache hit → settle fails → trace appended (failed) →
    record 0 anchored → recovery.recover(...) → healed returned → ScenarioStep(sentence,
    group_prompt) appended → on_step_passed → on_step_finished(passed)`. Assertions —
    `recovery.recover` received (group_prompt, `g.traces` incl. the failed record, sentence,
    type, scenario, identity, history, page, window); `steering.steer` not called; a second
    case: recovery raises `IncurableStepError` → `steering.steer` called with group_prompt; a
    third: strict mode → recovery never called, classification-only path as today. Sufficiency:
    the routing precedence (strict → recovery → steering) is the contract's core control flow;
    SC7's strict half is pinned by the third case.
  - `test_step_delay_pauses_quietly_after_started_event` (SC5): Setup — an executor with a
    cache hit whose code executes green (a fake settle/run stub); a hooks fake appending
    `("event", name)` and a monkeypatched `time.sleep` appending `("sleep", seconds)` into one
    shared recording list. Input — `execute("open the inbox", "action", page, group=None,
    tries=None, delay=1.5)`. Trace — `on_step_started` emitted → `sleep(1.5)` — the only sleep,
    quiet → identity → window → cache hit → settle executes the cached code → success →
    ScenarioStep appended → `on_step_passed` → `on_step_finished(passed)`. Assertions —
    recorded == `[("event", "on_step_started"), ("sleep", 1.5), ("event", "on_step_passed"),
    ("event", "on_step_finished")]`; no log record of the pause exists (caplog carries only the
    lifecycle events) — the pause is quiet. Sufficiency: SC5 — pins the ordering (the started
    event fires, then the declared seconds pass, then the code runs) and the quietness; the
    regression catches a pause moved before the started event or after the code, or a pause that
    becomes output noise. A step never reached never pauses is covered by the zero-steps case
    of the authoring test (Task 14).
  - C13 pins: `group=None, tries=None, delay=None` → every existing executor test stays green
    unchanged (the ordinary heal path, the steering gate, the strict path); the window built
    with `tries` threads into the cached replay and the generation path (a `tries=N` cached
    execution gets its own full count — pin with a failing-then-succeeding stub).
  - The group trace records: a failed group step appends `outcome=failed` with the URL pair
    read on the failure; a passed group step appends `outcome=passed` with the closing read
    after execution; ordinary steps never touch a trace list.
- [x] **Debugging**: `pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: `python -c "from prettyplay import StepExecutor"`;
  `python -c "import prettyplay"` (the composition wiring imports cleanly); the scenario
  context lives per test as typed records
- [x] **Lint**: `ruff check prettyplay tests && ruff format --check prettyplay tests`

### Task 14: `StepGroup` + the facade authoring surface — `tries`/`delay`, `group()` (facade)

The authoring surface: `step`/`expect` gain keyword-only `tries`/`delay` with loud shared
validation, and `group()` yields the authoring group object.

The shared validators (verified design trace): `_validate_tries(3)` / `_validate_delay(1.5)`
(facade-level helpers): `tries` — `None` passes; `isinstance(x, bool)` or not
`isinstance(x, int)` or `x < 1` → `PrettyplayError` naming the parameter, the received value
(`repr`), the allowed form ("a positive integer, keyword-only"); `delay` — `None` passes; not
`int | float` (bool excluded) or not finite or `< 0` → the same loud error ("a non-negative
number of seconds, keyword-only"). Identical validation reused by `StepGroup.step/expect`.
Failures leave through `_raise_folded` (traceback folding unchanged, covers the new validation
errors — they raise before the executor, inside the facade frame); invalid parameters fail
loudly at the call, before any page or LLM involvement.

`group(prompt, speed=None, delay=None)` (verified design trace): validates — `prompt` non-empty
(empty → `PrettyplayError` at entry); `speed` None or a non-bool int 0–100 (outside → loud error
naming the value and the 0–100 form); `delay` None or a non-negative finite number → constructs
`StepGroup(prompt, speed, delay, self._executor)` and binds the test's lazy page opener (an
implementation attribute `_open_page = self._ensure_page` — the contract constructor stays
four-parameter; the group is only ever constructed by `group()`). No ambient rerouting of the
test object; group membership changes no step's cache address (C1).

`StepGroup` (verified design algorithm):
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
pause for a later step of the same group. The entry `delay` is NOT slept on `__enter__` — it is
applied lazily immediately before the group's first executed step, so a zero-step group is a
quiet no-op (entry/exit records only). Edge cases: `speed=None` → no between-step pauses;
`delay=None` → no entry pause; both may combine. Library-level pauses, never `slow_mo` (which
cannot change mid-run). The closing record is unconditional once entry logged (also on the
exception path). `traces` — one `GroupStepOutcome` per executed group step (appended by the
executor from Task 13), the recovery's row source.

Export `StepGroup` from the root facade (`prettyplay/__init__.py` `__all__`).

**Usages relevant to this task:**
- `playwright` (the pace section): the "never slow_mo for group pace" rule — plain
  `time.sleep(int((100 − speed) × 30) / 1000)` between group steps.
- `recovery` (from Imports): the group cycle the delegated steps route to.
- `conventions`: the logger records with `extra`, loud validation messages, test structure.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/test_scenario.py` — `t.step`/`t.expect` accept keyword-only
  `tries`/`delay`; `t.group(...)` returns a `StepGroup` supporting the context manager protocol
  with `step`/`expect`/`traces`/`prompt`; `from prettyplay import StepGroup` importable
  (expected to fail at this stage)
- [x] **Code**: create `prettyplay/groups.py` — `StepGroup` per the algorithm (the delegation
  flag, the lazy entry pause, the between-step pace, the framing records, the `_open_page`
  binding attribute); `prettyplay/scenario.py` — the `_validate_tries`/`_validate_delay` shared
  helpers, the widened `step`/`expect` (keyword-only parameters, delegation with `tries`/
  `delay`), the `group()` factory; `prettyplay/__init__.py` — export `StepGroup` in `__all__`
- [x] **Interface verification**: `pytest tests/test_scenario.py -q` — all pass
- [x] **Logic tests** — the two design scenarios, verbatim:
  - `test_step_parameters_validate_loudly`: Setup — a `PrettyPlay` with a monkeypatched executor
    (must not be reached). Input — `t.step("x", tries=0)`, `tries=-1`, `tries=True`,
    `tries="3"`, `delay=-0.5`, `delay="slow"`, `t.expect(...)` variants, `t.group("")`,
    `t.group("p", speed=101)`, `t.group("p", speed="fast")`, `t.group("p", delay=-1)`,
    `g.step("x", tries=0)`. Trace — step/expect/group/StepGroup.step → the shared validators →
    `PrettyplayError` raised at the call. Assertions — each raises `PrettyplayError`; the
    message names the parameter, `repr(value)` and the allowed form ("tries", "0", "a positive
    integer" etc.); the executor was never invoked. Sufficiency: the loud-failure parity of the
    authoring surface; prevents silent coercion of bad parameters into a broken run.
  - `test_group_authoring_block_pauses_and_traces`: Setup — a `PrettyPlay` with a monkeypatched
    executor recording `execute` calls; `time.sleep` monkeypatched with a recorder. Input —
    ```
    with t.group("the checkout flow", speed=50, delay=2) as g:
        g.step("accept the cookie banner")
        g.step("fill the email field", delay=0.5)
    ```
    Trace — `group()` validates (prompt non-empty, speed 0–100, delay ≥ 0) → `StepGroup` bound;
    `__enter__` → group_started INFO; `g.step` #1 → entry delay 2 s slept once →
    `executor.execute(…, group=g, tries=None, delay=None)`; `g.step` #2 → between-step pause
    `int((100−50)×30)/1000 = 1.5 s` → `executor.execute(…, delay=0.5)`; `__exit__` →
    group_finished INFO. Assertions — sleeps recorded: `[2.0, 1.5]` (entry pause, pace pause —
    both slept by StepGroup; the step's own declared delay is slept by the real executor cycle,
    which this facade-level test replaces); the recording executor received `group=self` on both
    calls, `delay=None/tries=None` on the first, `delay=0.5` on the second; `g.traces` grew per
    executed step; zero steps ⇒ no sleep at all, both framing records still logged;
    `t.step("outside")` after the block → `group=None` (no ambient rerouting). Sufficiency: the
    group pace/pause semantics (never slow_mo), the lazy entry pause (an empty group never
    pauses), the trace growth and the addressing isolation a consumer observes.
  - Edge pins: `speed=None`/`delay=None` combinations (no pauses); the exception path still
    logs `group_finished`; a `PrettyplayError` from validation carries the folded traceback.
- [x] **Debugging**: `pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: `python -c "from prettyplay import PrettyPlay, StepGroup"`;
  the root `__all__` still exports `PrettyPlay, StepHooks, PrettyConfig, BrowserConfig,
  PrettyplayRuntime, StepExecutor` (+ `StepGroup`)
- [x] **Lint**: `ruff check prettyplay tests && ruff format --check prettyplay tests`

### Task 15: Integration tests — group replay, strict isolation, the cross-cell mirror pins

Cross-cell scenarios spanning multiple cells, as separate integration tests. The shared fixtures
land in `tests/conftest.py` (design General Setup): `scenario_records()` (a typed
`list[ScenarioStep]` mix of ordinary and group entries), `group_traces()` (a
`list[GroupStepOutcome]` over a 3-step group); unit tests fake `PageFacade` (a stub exposing
`url`, `aria_snapshot()`, `screenshot()`), fake providers subclassing `LLMProvider` with canned
answers, `StepCache` under `tmp_path`, real `RunBudgets`.

**Usages relevant to this task:**
- `system_prompt` / `cheat_sheet` / `group_diagnosis` (the practice files): the frozen mirrors —
  the cross-cell pin proves the constants never drift from the single sources.
- `conventions`: test structure, fakes.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] Create/extend the fixtures `scenario_records()` and `group_traces()` in `tests/conftest.py`
  (the design's third shared fixture — a recovery-ready executor — is deliberately not a
  conftest fixture: Tasks 11 and 13 build their recovery-ready executor setups inline with
  their own fakes, keeping each TDD task self-contained)
- [x] Test cross-entity interaction — the design scenario, verbatim:
  `test_group_replay_is_llm_free_and_strict_never_recovers` (SC7): Setup — a group whose three
  steps are all cached under `tmp_path`; a provider fake that fails the test on any call; strict
  off (case A) and strict on with a failed cached hit (case B — the classification-only path).
  Input — `with t.group("the flow") as g: g.step(...); g.step(...); g.expect(...)`. Trace — A:
  three cache hits → settle executes → traces appended (passed) → no provider call; B: strict, a
  failed cached hit case added → `classify_step_failure` called once (the only LLM call),
  `recovery.recover` never invoked. Assertions — A: `provider.call_count == 0`; three traces;
  steps green; B: recovery not called; the strict classification-only outcome raised by kind.
  Sufficiency: SC7 + C2 — group membership changes no cache address and no replay behavior;
  strict keeps its classification-only path.
- [x] Test cross-cell mirror pin — the design scenario, verbatim:
  `test_prompt_mirrors_after_rename`: Setup — the mirror constants of `generator.py`,
  `steering.py`, `diagnosis.py`. Input — compare against `step_generation.md` (after `---`),
  `step_cheatsheet.md` (whole file), `group_diagnosis.md` (after `---`). Trace — read practice
  file → extract per the mirror rule → assert equal to the constant. Assertions — all mirrors
  byte-equal; the renamed files' content equals the pre-rename content (the git R100 record plus
  the pin). Sufficiency: C13 — the frozen prompts never drift, and the rename changed no byte.
- [x] Test edge case: the typed scenario context end-to-end — an ordinary step followed by a
  group step then an ordinary step: the third step's generation request renders the group
  entry marked (permanent membership) even outside the group (C13 honesty pin, executor →
  generator → provider fake recording `previous_steps`)
- [x] Run validation: `pytest tests/ -x` — the full suite green (every ordinary-path pin from
  the pre-change suite included)

### Task 16: Public MkDocs surface follow-up (docs, non-cell)

The design's additional instruction: update the public MkDocs surface as a non-cell follow-up —
the configuration page (the `speed` setting: the TOML example, the env table row
`PRETTYPLAY_BROWSER_SPEED`, the Pace section with the layering example and the loud-failure
note), the writing-steps guide (the `tries`/`delay` step parameters), a groups page (the group
authoring block, the pauses, the recovery cycle) and the self-healing reference (the group
recovery routing and the `recoverable` vocabulary). No cell code, no CODEMANIFEST, no `.usages/`
changes — public documentation only, matching the already-current cell `.usages/` content.

**Usages relevant to this task:**
- The cell `.usages/` files (facade `steps.md`/`lifecycle.md`, config `configuration.md`, groups
  `recovery.md`) — the authoritative consumer-level descriptions to mirror publicly.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them.**

- [ ] Update `docs/configuration.md` — the `browser.speed` setting (TOML, the env table row, the
  Pace section with the layering example and the loud-failure note)
- [ ] Update `docs/guides/writing-steps.md` — the keyword-only `tries`/`delay` step parameters
  (the count-bounded re-execution, the quiet pre-step pause)
- [ ] Create the groups page (e.g. `docs/reference/groups.md`) — the group authoring block
  (prompt, speed, delay, traces), the pauses (entry + between-step pace, never slow_mo), the
  diagnosis-driven recovery cycle, the budgets; add it to `mkdocs.yml` nav
- [ ] Update `docs/reference/self-healing.md` — the group recovery routing (strict → recovery →
  heal, steering the terminal gate) and the `on_healing_started` `recoverable` label
- [ ] Verify: the mkdocs nav contains the new page and every referenced code sample imports
  cleanly (`python -c "import prettyplay"`); `mkdocs build --strict` if the tool is available

---

## Validation Commands

- `pytest tests/engine/polling tests/config tests/driver tests/llm tests/cache -q`: Task-scoped suites (Tasks 1–7)
- `pytest tests/engine -q`: The engine, groups and steering suites (Tasks 8–12)
- `pytest tests/ -x`: Run all tests — the full gate (every task's debugging step; Tasks 13–16)
- `ruff check . && ruff format --check .`: Lint and format check (every task's lint step)
- `python -c "from prettyplay import PrettyPlay, StepGroup, StepExecutor, PrettyConfig, BrowserConfig, StepHooks, PrettyplayRuntime"`: Root facade accessibility
- `python -c "from prettyplay.llm import LLMProvider, ScenarioStep, GroupFailureClassification, parse_group_failure_classification"` and `python -c "from prettyplay.engine.groups import GroupStepOutcome, classify_group_failure, GroupRecovery"`: Cell facade accessibility
- `goga lint`: 11 cells, 0 errors (the manifests were not modified)
- `goga schema`: The cell structure unchanged — the groups cell and its facade edge intact, no cycles

---

## Completion Criteria

- [x] Every contract entity is implemented in the correct `location`
- [x] Every contract entity is accessible from the facade (cell `__all__` + root `__all__` with `StepGroup`)
- [x] Properties and methods match the declared API (signatures incl. keyword-only `tries`/`delay`, the renamed `classify_step_failure`, the four port operations)
- [x] Descriptions are reflected in behavior (the pinned render forms, the group-branch reason strings, the verdict mapping, the log records)
- [x] Contract dependencies are met (config → llm/driver → cache/polling → engine → groups/steering → facade; no import cycles)
- [x] Re-exports are accessible from the facade (`PrettyConfig`, `BrowserConfig`, `StepHooks`)
- [x] Every coding task followed the TDD workflow (contract tests → code → verification → logic tests → debugging → re-verification → lint)
- [x] Contract tests and logic tests cover facade, API, and behavior within each coding task
- [x] Integration tests exist where cross-entity scenarios require them (Task 15: SC7, the mirror pins, the typed-context end-to-end)
- [x] All 17 design test scenarios exist and pass (SC1–SC8 coverage as mapped in the tasks)
- [x] Every `group_prompt=None`/`group=None`/`tries=None`/`delay=None` path is byte-identical to today (the C13 regression pins stay green)
- [x] No package boundary was expanded (no new cells beyond the contracted `prettyplay/engine/groups`)
- [x] `CODEMANIFEST` files were not modified (contract is read-only)
- [x] No `.usages/` file was modified (all current by the design review)
- [x] All validation commands pass (`pytest tests/ -x`, `ruff check`, `goga lint`, `goga schema`)
- [x] Every Usages entry is mentioned in at least one task (`conventions`, `pydantic`, `playwright`, `json_repair`, `openai`, `anthropic`, `system_prompt`, `cheat_sheet`, `group_framing`, `group_diagnosis`, `classification_prompt`, `compliance_prompt`, imported `recovery`/`generation`/`healing`/`taxonomy`/`hooks`/`classification`)
- [ ] The public MkDocs surface is updated (Task 16)
