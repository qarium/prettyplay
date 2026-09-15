# Plan: `agent-context-window`

Result of compiling the reviewed design document (`.goga/history/2026/agent-context-window/design.md`) into ralphex execution tasks. The contracts are final (working-tree CODEMANIFEST changes on branch `agent-context-window`, materialized by the apply-architecture stage, verified by the design-review stage: 13 entry-point stacks traced clean, `goga lint` 10 cells / 0 errors).

---

## Purpose

The step cycle carries an honest context window end to end: one continuous verbatim per-step attempt history (`StepAttempt` records) threading through generation, healing and steering; honest request inputs (the step type and the raw step sentence) into every request; a two-dimension compliance gate (instruction compliance + step adequacy) judging from the step type and the attempt history; and the replayability requirement in the generation system prompt.

After implementation the package provides:

- `StepAttempt` — one immutable verbatim record of the per-step attempt history (new entity, `prettyplay/engine/attempts.py`), rendered into every provider HISTORY / gate ATTEMPT HISTORY block.
- The LLM port (`prettyplay/llm`) with `step_type` + `attempt_history` inputs on generation and verdict requests, the `ComplianceFinding.dimension` field, strict dimension validation in `parse_compliance_verdict`, and absolute provider parity on the new inputs.
- The engine loops (`generate`/`regenerate`), the gate (`check_step_compliance`) and the healer (`heal`) growing and threading the shared history with URL-bracketed attempts.
- The steering dialog joining the shared per-step history (dialog-local turn history deleted) with per-turn URL brackets and the two-dimension write-back gate.
- The executor owning the history: created per step, record 0 seeded on a failed cached hit, honest inputs threaded into every engine call.

The most important gaps between contract and code: the port still carries the removed `existing_code`/`error`/`guidance_history` inputs; `ComplianceFinding` has no `dimension`; the engine loops and the executor never create or grow an attempt history; the steering dialog keeps a local `guidance_history`; the frozen prompt mirrors (`SYSTEM_PROMPT`, `COMPLIANCE_PROMPT`) are stale relative to the already-updated practice files.

Overall implementation strategy: dependency bottom-up (`prettyplay/llm` → `prettyplay/engine` → `prettyplay/engine/steering` → `prettyplay/executor.py`), one TDD task per contract location, the frozen-mirror re-syncs riding their owning tasks, and a final integration task running the full suite end to end.

## Context

### Contract Surface

All four `CODEMANIFEST` files below are **read-only** for the implementation agent — the contracts are final.

**Cell: `prettyplay/llm`** (contract file `prettyplay/llm/CODEMANIFEST`)

**Entity: `ComplianceFinding`**
- Type: class (`models.py`)
- Facade obligation: importable from `prettyplay.llm`
- Properties: `instruction -> str` (the verbatim quote the finding names — the violated instruction **or** the fragment of the step sentence the code fails to accomplish), `priority -> str` (high | medium | low; only high blocks, in both dimensions), `explanation -> str`, `dimension -> str` (**new** — instruction | adequacy)
- Semantic requirements: pydantic v2, kw_only, empty defaults; `priority` accepts exactly the three labels and `dimension` exactly the two; anything else never reaches this type — the parse fails loudly before.

**Routine: `parse_compliance_verdict(verdict_text: str) -> findings: list[ComplianceFinding]`**
- Type: function (`models.py`)
- Facade obligation: importable from `prettyplay.llm`
- Semantic requirements: strict single parsing point of the gate. Algorithm: parse the trimmed text as a JSON list of objects; validate every item — instruction, priority of the {high, medium, low} set, explanation, dimension of the {instruction, adequacy} set; a missing field, an unknown priority label or an unknown dimension is a malformed verdict; **an answer of the old shape — a finding without a dimension — is malformed, never a silent pass**; a malformed verdict raises `ComplianceVerdictError` carrying a 200-char collapsed fragment of the raw answer. Pure function: no state, no I/O, deterministic; no fence unwrapping, no protective fallback.
- New `_malformed` message wording: `…expected a JSON list of findings with instruction, priority high|medium|low, explanation and dimension instruction|adequacy; received fragment: …`

**Entity: `LLMProvider`**
- Type: class — the unified LLM port (`provider.py`)
- Facade obligation: importable from `prettyplay.llm`
- Methods (changed):
  - `generate_step_code(prompt, user_instructions, step_text, step_type, previous_steps, snapshot, page_url, screenshot, cheat_sheet, attempt_history, recommendation, guidance) -> code: str` — **new inputs** `step_type: str`, `attempt_history: list[str]`; **removed inputs** `existing_code`, `error`, `guidance_history`. `step_text` is the raw sentence, never the normalized addressing form. `attempt_history`: every record a complete multi-line verbatim record composed by the calling engine; the original cached code anchors the list as record 0 when it exists; non-empty — rendered as the HISTORY block after the USER INSTRUCTIONS block; empty — no block; no collapsing, no size limits; the list takes the place of the former existing_code, error and guidance_history inputs — the last record is the code being fixed. Fixed block order of a generation request: CHEAT SHEET, user instructions, HISTORY, RECOMMENDATION, USER GUIDANCE; the PAGE URL line renders immediately after the PAGE SNAPSHOT block; the STEP TYPE line renders immediately before the STEP line. The new inputs take no part in step addressing.
  - `check_instruction_compliance(prompt, user_instructions, step_text, step_type, code, attempt_history) -> verdict: list[ComplianceFinding]` — **new inputs** `step_type: str`, `attempt_history: list[str]`. One verdict request per successfully executed candidate judging two dimensions in one request; the answer parses strictly through `parse_compliance_verdict`; malformed → `ComplianceVerdictError`; SDK error → `LLMUnavailableError`. The user content carries four blocks in the fixed order INSTRUCTIONS, STEP, ATTEMPT HISTORY, CODE — with the STEP TYPE line immediately before the STEP line — identically in both implementations. The gate model is the effective generation model.
  - `classify_failure(...)` — unchanged.
- Imported dependencies: `Config` (prettyplay/config), `LLMUnavailableError`, `ComplianceVerdictError` (prettyplay/failures).

**Entity: `LLMProvider::OpenAIProvider(config)` / `LLMProvider::AnthropicProvider(config)`**
- Type: mutation of `LLMProvider` (`openai_provider.py` / `anthropic_provider.py`)
- Facade obligation: importable from `prettyplay.llm`
- Semantic requirements: full parity on the new inputs — the STEP TYPE line renders immediately before the STEP line on generation and verdict requests; the attempt-history records render as the HISTORY block placed after the USER INSTRUCTIONS block — every record verbatim, complete multi-line records, no collapsing; the remaining regeneration-only blocks render in the fixed order RECOMMENDATION, USER GUIDANCE; a non-empty input renders its named block, identically in both implementations. The compliance operation: INSTRUCTIONS, STEP (with its STEP TYPE line), ATTEMPT HISTORY and CODE blocks in this fixed order; one request through the effective generation model; the text answer parses strictly through `parse_compliance_verdict` — no fence unwrapping; a malformed verdict (an answer of the old shape included) raises `ComplianceVerdictError`. One SDK request per operation; SDK errors → `LLMUnavailableError` naming the provider.

**Routine: `create_provider(config)`** — untouched this round.

**Entity: `FailureClassification`** — untouched this round.

**Cell: `prettyplay/engine`** (contract file `prettyplay/engine/CODEMANIFEST`)

**Entity: `StepAttempt` (NEW)**
- Type: class (`attempts.py` — new file)
- Facade obligation: importable from `prettyplay.engine`
- Constructor: `StepAttempt(code: str, error: str, outcome: str, url_before: str, url_after: str)` — pydantic v2, kw_only, empty defaults; **frozen — a record is immutable once appended: no rewriting, no truncation**.
- Properties: `code -> str` (the complete candidate code of the attempt, verbatim), `error -> str` (the complete failure text — the execution error, the failed check text, or the gate violation text; empty on no error), `outcome -> str` (the closed label set of five labels: `original cached code`, `failed check`, `execution failed`, `compliance blocked`, `rejected by the engineer, not executed`), `url_before -> str`, `url_after -> str` (the page URL read immediately before/after the attempt's execution).
- Method: `render() -> record: str` — Algorithm: 1. the outcome line — the label verbatim; 2. the URL line — url_before, an arrow, url_after; 3. the complete code; 4. a non-empty error renders the complete error text; empty — no error part. Requirements: no collapsing, no size limits, no truncation of any field.

**Entity: `StepGenerator(config, provider, cache, budgets, reporter)`**
- Type: class (`generator.py`)
- Facade obligation: importable from `prettyplay.engine`
- Methods (changed):
  - `generate(identity, step_text, step_type, previous_steps, page, attempt_history, window) -> step: CachedStep` — the generation loop; appends a record after every attempt that does not produce a cached step (outcomes: `failed check`, `execution failed`, `compliance blocked`); every request carries the raw sentence, the step type and the rendered history; URL pair brackets each attempt including settle re-executions; the gate blocks on a high finding of either dimension; budget exhaustion with a standing high finding raises `IncurableStepError` carrying the verdict built from the finding.
  - `regenerate(identity, step_text, step_type, previous_steps, page, attempt_history, recommendation, window) -> step: CachedStep` — the healing loop; **removed inputs** `existing_code`, `error`; the anchored history (record 0 = the original cached code) is never rebound; every failure (checks included) appends its record and retries; no per-attempt classification; exhaustion raises `IncurableStepError` whose terminal-failure facts derive from `history[-1]`.
- Semantic requirements carried from the contract annotations: one continuous per-step attempt history threads through generation, healing and steering — no collapsing, no truncation, no size limits; honest inputs (the step type and the raw sentence) reach every request; a record is appended after every attempt that does not produce a cached step; the replayability requirement lands in `system_prompt` and its frozen mirror; medium/low findings pass with a visible WARNING; the gate consumes no attempt budget.

**Routine: `check_step_compliance(config, provider, step_text, step_type, code, attempt_history) -> findings: list[ComplianceFinding]`**
- Type: function (`compliance.py`)
- Facade obligation: importable from `prettyplay.engine`
- Semantic requirements: the single two-dimension gate of every caching path. Algorithm: 1. the generation_approve setting is off or the generation_prompt setting is empty — return an empty list with zero provider calls; 2. ask the provider port `check_instruction_compliance` passing `compliance_prompt` as the system prompt, the effective config generation_prompt as the user instructions, `step_text`, `step_type`, `code` and the rendered `attempt_history`; 3. return the findings. Never called for replayed cached code; hard failures propagate; no attempt budget consumed here.

**Entity: `StepHealer(config, provider, generator, cache, budgets, reporter)`**
- Type: class (`healer.py`)
- Facade obligation: importable from `prettyplay.engine`
- Method (changed): `heal(step, error, step_text, step_type, previous_steps, page, attempt_history, window) -> step: CachedStep` — classify via `classify_step_failure` passing the **raw** `step_text` (never `identity.normalized_text`); the decision table is unchanged (product_defect → `ProductDefectError`; incurable → `IncurableStepError`; rot | fixable → `generator.regenerate` carrying the raw sentence, the step type, the classification recommendation and the anchored history, threaded by reference); a regeneration budget exhaustion inside step 5 surfaces as `IncurableStepError` carrying the verdict of the entry classification — no extra LLM request.

**Routine: `classify_step_failure(config, provider, step_text, code, error, page)`**
- Type: function (`classification.py`)
- Facade obligation: importable from `prettyplay.engine`
- Change: **annotation wording only** — `step_text` is "the raw sentence of the failed step as passed by the calling engine"; signature and behavior unchanged.

**Routines: `format_step_error` (text.py), `run_step_code` (execution.py)** — unchanged.

**Cell: `prettyplay/engine/steering`** (contract file `prettyplay/engine/steering/CODEMANIFEST`)

**Entity: `StepSteering(config, provider, cache, reporter | None)`**
- Type: class (`steering.py`)
- Facade obligation: importable from `prettyplay.engine.steering`
- Imports (changed): adds `StepAttempt` from `prettyplay/engine`.
- Method (changed): `steer(failure, identity, step_text, step_type, previous_steps, page, attempt_history) -> healed: CachedStep | None` — the dialog joins the one shared per-step attempt history passed by the executor (the dialog-local turn history and the `_turn_record` helper are gone); every guidance turn is a regeneration request carrying the honest inputs plus the grown history; record 0 anchors the original failure; `run? [y/N]` — a rejected turn appends a record with outcome `rejected by the engineer, not executed` and the same URL on both sides; an approved turn brackets a bare `run_step_code` (no settle) with URL reads; a failed turn appends `failed check` / `execution failed`; a green turn passes `check_step_compliance` with the step type and the shared history — a high finding of either dimension never reaches the cache (record `compliance blocked`, prompt reopens); medium/low pass with a WARNING then the write-back; gate hard failures end the dialog (`return None`); provider unavailability of the request → dialog ends, `return None`. Constraints: never persist the guidance into the cache file; never introduce history size limits, line collapsing or record truncation.

**Cell: `prettyplay` (root)** (contract file `prettyplay/CODEMANIFEST`)

**Entity: `StepExecutor(cache_key, cache, generator, healer, steering, budgets, reporter, config, provider)`**
- Type: class (`executor.py`)
- Facade obligation: internal to the root cell (driven by `PrettyPlay.step`/`expect`)
- Imports (changed): adds `StepAttempt` from `prettyplay/engine`.
- Method (changed): `execute(step_text, step_type, page)` — step 2 creates the per-step attempt history (an empty `StepAttempt` record list); step 3 brackets the cached replay with guarded URL reads; step 4 seeds record 0 on a failed cached hit (outcome `original cached code`, the cached code, the `format_step_error` text, the replay URL pair) **before** the heal delegation; steps 4–6 thread the raw sentence, the step type and the history into heal / generate / steer; the strict path is untouched except the (already raw) sentence into classification.
- Requirements (new): the raw step sentence reaches every engine call verbatim — generate, heal and steer alike; the casefolded normalization is an addressing key only; the per-step attempt history lives exactly one step execution; record 0 is composed before the heal delegation — a regeneration never loses the original cached code.

**Entities untouched**: `PrettyPlay` (scenario.py), `PrettyplayRuntime` (runtime.py), the re-exports below.

### Re-exports

- `->PrettyConfig: {}`, `->BrowserConfig: {}`, `->StepHooks: {}` (root facade) — unchanged, already importable from `prettyplay`. No work.
- **New facade obligation**: `StepAttempt` must be importable from `prettyplay.engine` (added to `__all__` of `prettyplay/engine/__init__.py` in Task 4). The root cell imports it from `prettyplay/engine` (already declared in its `Imports` — no re-export block required at the root facade).

### Usages Context

- `conventions` (`.goga/usages/conventions.md`) — Python code/test conventions: relative imports, pydantic v2 kw_only + empty defaults, Google docstrings, logging, test structure mirroring `tests/<pkg>/test_<module>.py`. Binding for every changed cell. `StepAttempt`/`ComplianceFinding` follow the pydantic rules; `from .attempts import StepAttempt` relative imports.
- `system_prompt` (`.goga/usages/prompts/generation.md`) — the generation system prompt. **The file is already updated** (STEP TYPE first input line, HISTORY replacing CODE/ERROR, the replayability rule) by the apply stage; the frozen `SYSTEM_PROMPT` mirrors in `generator.py` and `steering.py` are **stale and must be re-synced** (Tasks 6 and 8): the section after `---` mirrored byte-for-byte; cell-owned local copies, no runtime read of `.goga/`.
- `cheat_sheet` (`.goga/usages/prompts/cheatsheet.md`) — the compact Playwright sync API reference. Unchanged; whole-file frozen mirrors in `generator.py` and `steering.py` already current.
- `classification_prompt` (inline, engine header) — unchanged; frozen mirror `CLASSIFICATION_PROMPT` in `classification.py` already current.
- `compliance_prompt` (inline, engine header) — **rewritten** (two dimensions, STEP TYPE + ATTEMPT HISTORY inputs, `dimension` in the answer schema, dimension calibration, priority calibration, the attempt-history-as-ground-truth rule). The frozen mirror `COMPLIANCE_PROMPT` in `compliance.py` is **stale and must be re-synced** (Task 5) byte-for-byte (the block-scalar text).
- `openai` (`.goga/usages/cooks/openai.md`) / `anthropic` (`.goga/usages/cooks/anthropic.md`) — SDK call patterns and error mapping. Unchanged; one request per operation, SDK errors → `LLMUnavailableError`.

### Imported Usages

- `classification` from `prettyplay/llm` — source path `prettyplay/llm/.usages/classification.md`; the healing decision categories; referenced by the engine global annotations. Unchanged this round.
- `hooks`, `taxonomy` from `prettyplay/reporting` / `prettyplay/failures` (imported by the root cell) — unchanged.
- `generation`, `healing` from `prettyplay/engine` (imported by the root cell) — describe the cycles the executor delegates to; already updated by the apply stage; verified current by the design review.

### Local Usages

The design document's `.usages/` Update audit found every relevant cell-level usage file **current** (updated by the apply stage; verified by the design-review stage). No creation or update tasks are planned:

- `prettyplay/llm/.usages/providers.md` — current (step-type and attempt-history parity, HISTORY tail order, dimension verdict format).
- `prettyplay/llm/.usages/classification.md` — untouched by design (classification contract unchanged).
- `prettyplay/engine/.usages/generation.md` — current (attempt history, honest inputs, two-dimension gate, URL brackets, bounded healing with grown history).
- `prettyplay/engine/.usages/healing.md` — current (anchored history, raw sentence threading).
- `prettyplay/engine/steering/.usages/steering.md` — current (shared history, rejected-turn record, two-dimension gate).
- `prettyplay/.usages/steps.md` — current (honest step context section, addressing note). `prettyplay/.usages/lifecycle.md` — untouched by design.
- New files: **none** — no new consumer-facing functional domain; the attempt history is internal (steps.md already documents it at the author level).

### External Dependencies

- `pydantic` v2 — `StepAttempt`, `ComplianceFinding` models (`ConfigDict(kw_only=True, frozen=True)`).
- `openai` / `anthropic` SDKs — the two provider implementations (see `openai` / `anthropic` usages).
- `playwright` — driver cell (`PageFacade.url` — an existing immediate-read property; the driver cell needs no changes).
- `pytest` — the test framework (existing idioms: `StubProvider`, `ComplianceStubProvider`, `FakePage`, SDK-client stubs).

## Facts

- Branch `agent-context-window`; the working tree already carries the final contracts: 4 changed `CODEMANIFEST` files, 5 updated cell-level `.usages/` files, and the updated `.goga/usages/prompts/generation.md` (apply-architecture stage). `goga lint`: 10 cells / 0 errors; the design-review stage found no CODEMANIFEST defects.
- `PageFacade.url` is an existing immediate-read property crossing the driver worker boundary as a plain `str` — the driver cell needs no change.
- The frozen-mirror tests already exist and extract the practice text for byte-for-byte comparison: `tests/engine/test_compliance.py::test_compliance_prompt_is_a_frozen_constant` + `test_compliance_prompt_mirror_matches_the_code_manifest_practice`, `tests/engine/test_generator.py::test_generation_prompt_is_frozen_text` + `test_system_prompt_mirrors_the_generation_practice` + `test_cheat_sheet_mirrors_the_practice`, `tests/engine/steering/test_steering.py::test_steering_mirrors_the_practices`. Because the practice files are already new, these tests **fail until the mirrors are re-synced** — extend them to the new text anchors, do not reinvent the pattern.
- Virtualenv at `.venv` with `python`, `pytest`, `ruff` (ruff: line-length 120, target py310).
- Existing engine-test idioms: `StubProvider` / `ComplianceStubProvider` classes record provider kwargs; `FakePage` fakes the page facade with recorded calls (currently **no** `url` property — Task 4 adds one returning a scripted value or raising); provider tests stub the SDK clients at the import point.
- `StepAttempt` travels only along the pre-existing dependency edges engine→steering and engine→root; **zero new dependency edges** between cells.
- Implementation order fixed by the design (dependency bottom-up): `prettyplay/llm` (models → `_request` → provider → both providers) → `prettyplay/engine` (new `attempts.py` first, then compliance / generator / healer(+classification docstring), `__init__` export) → `prettyplay/engine/steering/steering.py` → `prettyplay/executor.py` → integration.
- **Do not touch**: `prettyplay/llm/.usages/classification.md`, `prettyplay/.usages/lifecycle.md`, `.goga/usages/prompts/cheatsheet.md`, any `CODEMANIFEST` (the contracts are final), `PageFacade`, the failure taxonomy, the cache cell, budgets, polling, the classification port operation and its prompt.
- **Keep the removed inputs removed**: no `existing_code` / `error` / `guidance_history` parameters may survive anywhere (port, providers, engine loops, stubs, tests). The steering `_turn_record` helper is deleted, not adapted.
- **Guarded URL reads** (resolved design decision 1): a failed bracketing `page.url` read (dead page, driver failure) degrades to the empty string on that side; the attempt itself proceeds normally. Engine `_read_url(page) -> str`, executor `_read_url(page) -> str` (each cell-local, private); steering keeps `_guarded_url(page) -> str | None` for the request input and uses it for the brackets with `or ""`. Three tiny cell-local helpers — the contracts declare no shared routine; do not create a cross-cell export.
- **Uniform five-field records** (resolved design decision 2): `StepAttempt` stays exactly {code, error, outcome, url_before, url_after} across generation, healing and steering. Prior-turn engineer guidance messages are not preserved in the history; the current turn's message rides the USER GUIDANCE block. Deliberate — no contract change.
- **Records are append-only and per-step**: `StepAttempt` frozen; the history list is confined to the executor's call tree; nothing from the history is ever persisted to the cache file or dumped to logs (log only counts/outcomes; payloads can be large and may carry page data).
- **Wording pins** (authored, colon-free reasons): `"healing attempt budget exhausted"`; `f"generation attempt budget exhausted — {_reason_safe(instruction)}"`; violation text `f"{dimension} violation: {instruction} — {explanation}"`; exhaustion recommendation `f"satisfy the finding in the step code: {instruction}"`.
- Until Tasks 4–9 complete, the suite-wide `pytest tests/` is red by design (the port signature changes land before their engine/root callers adapt). Each task's validation scope is its own package's tests; Task 10 runs the full suite.

## Gap Analysis

- **Missing contract entities**: `prettyplay/engine/attempts.py` (new file) with `StepAttempt` + the five outcome-label constants; the `StepAttempt` export in `prettyplay/engine/__init__.py` (`__all__`).
- **Missing facade exposure**: `from prettyplay.engine import StepAttempt` currently fails.
- **API mismatches (llm)**: `LLMProvider.generate_step_code` still takes `existing_code`/`error`/`guidance_history` and lacks `step_type`/`attempt_history`; `check_instruction_compliance` lacks `step_type`/`attempt_history`; `build_fields_text` renders CODE/ERROR blocks and a steering-only HISTORY tail; `build_compliance_fields(user_instructions, step_text, code)` renders three blocks without the STEP TYPE line and the ATTEMPT HISTORY block; `ComplianceFinding` lacks `dimension`; `parse_compliance_verdict` does not validate a dimension; the `_malformed` message predates the dimension.
- **API mismatches (engine)**: `StepGenerator.generate`/`regenerate` lack `step_type`/`attempt_history` (regenerate still takes `existing_code`/`error`); `check_step_compliance` lacks `step_type`/`attempt_history`; `StepHealer.heal` lacks `step_text`/`step_type`/`attempt_history`; `steer` lacks `step_text`/`step_type`/`attempt_history` and keeps `_turn_record` + a dialog-local `history: list[str]` passed as `guidance_history`.
- **Behavioral mismatches**: the heal path derives `step.identity.normalized_text` for classification instead of the raw sentence; no attempt records are ever appended; no URL brackets around attempts; `_violation_text` and the exhaustion wording are single-dimension ("violated instruction"); the steering rejected turn does not record a same-URL pair; regenerate's terminal facts come from the removed parameters instead of `history[-1]`.
- **Stale frozen mirrors**: `SYSTEM_PROMPT` in `generator.py` (still documents CODE/ERROR inputs) and in `steering.py` (old HISTORY wording); `COMPLIANCE_PROMPT` in `compliance.py` (single-dimension text). The mirror tests fail until re-synced.
- **Existing code that can be reused**: the whole loop skeletons (`_generation_loop`, `_healing_loop`, `_failed_check_outcome`, `_exhaustion_outcome`, `_funded_regeneration`, `_request`, `_store`, `_classify`), the settle integration, the budget/decision tables, `format_step_error`, the steering banner/local commands/approval gate, the executor cycle, the test fixture idioms and the mirror-test patterns.
- **Test coverage gaps**: 24 scenarios from the design (15 positive, 3 negative, 6 edge) plus the frozen-mirror test extensions; existing tests referencing the removed inputs need mechanical updates as each task lands.
- **Missing visibility**: none — all changed files are tracked in git on the branch.

---

## Tasks

> **Package ordering rule**: coding tasks for each package are completed before starting the next. Within each coding task, contract tests are written first (TDD workflow).
>
> **CODEMANIFEST files are read-only contract definitions — never modify them.** If implementation does not match the contract, fix the implementation.
>
> **Validation scoping**: until Task 10, run each task's scoped test command; the suite-wide run is deferred to Task 10 because the port signature changes land before their engine/root callers adapt.

### Task 1: `ComplianceFinding.dimension` and strict dimension validation in `parse_compliance_verdict` (prettyplay/llm — models)

Context: the first change of the `prettyplay/llm` cell — the verdict data model gains the two-dimension field and the parser enforces it. Contract entities: `ComplianceFinding` (property `dimension -> str` added), `parse_compliance_verdict` (validates `dimension` of {instruction, adequacy}; an old-shaped answer — a finding without a dimension — is malformed, never a silent pass). Location: `prettyplay/llm/models.py`. The findings' labels are validated one step before construction — `ComplianceFinding` itself keeps empty defaults per the pydantic conventions; introduce `COMPLIANCE_DIMENSIONS = frozenset({"instruction", "adequacy"})` as the closed set the parser checks against. The `_malformed` message becomes `…expected a JSON list of findings with instruction, priority high|medium|low, explanation and dimension instruction|adequacy; received fragment: …` (keep the existing 200-char collapsed-fragment mechanics).

**Usages relevant to this task:**
- `conventions` (`.goga/usages/conventions.md`): pydantic v2 models stay kw_only with empty defaults; Google docstrings; tests in `tests/llm/test_models.py` mirroring the module.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/llm/test_models.py`, expected to fail at this stage): facade import `from prettyplay.llm import ComplianceFinding, parse_compliance_verdict`; API shape — `ComplianceFinding` accepts a `dimension` keyword and exposes it as a `str` property alongside `instruction`/`priority`/`explanation`; `parse_compliance_verdict` signature unchanged
- [ ] **Code**: add `dimension: str = ""` to `ComplianceFinding` with its docstring (the finding dimension: instruction or adequacy — which side of the gate produced the finding)
- [ ] **Code**: add `COMPLIANCE_DIMENSIONS = frozenset({"instruction", "adequacy"})` and extend `parse_compliance_verdict` item validation: `dimension` must be a string within the set; missing (an old-shaped finding) or unknown → `_malformed`
- [ ] **Code**: update the `_malformed` message wording to the dimension-aware text above
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/llm/test_models.py -x` — contract tests pass
- [ ] **Logic tests** (add to `tests/llm/test_models.py`; scenarios verbatim from the design):
  - [ ] `test_parse_compliance_verdict_accepts_both_dimensions` — **Setup**: none. **Input**: `'[{"instruction": "Prefer id attributes", "priority": "high", "explanation": "locates by text", "dimension": "instruction"}, {"instruction": "click the «Sign in» button", "priority": "low", "explanation": "only checks state", "dimension": "adequacy"}]'`. **Trace**: `parse_compliance_verdict(text)` → json.loads → list of 2 dicts → item 1: dimension "instruction" ∈ COMPLIANCE_DIMENSIONS → ComplianceFinding; item 2: dimension "adequacy" ∈ COMPLIANCE_DIMENSIONS → ComplianceFinding. **Assertions**: `len(findings) == 2`; `findings[0].dimension == "instruction" and findings[0].priority == "high"`; `findings[1].dimension == "adequacy" and findings[1].priority == "low"`
  - [ ] `test_parse_compliance_verdict_rejects_old_shape_without_dimension` — **Setup**: none. **Input**: `'[{"instruction": "Prefer id attributes", "priority": "high", "explanation": "locates by text"}]'`. **Trace**: json ok, list ok, item dict ok → item.get("dimension") is None → not a str → `_malformed` → raise `ComplianceVerdictError`. **Assertions**: `pytest.raises(ComplianceVerdictError)` — message contains "dimension" and a fragment of the raw answer
  - [ ] `test_parse_compliance_verdict_rejects_unknown_dimension` — **Setup**: none. **Input**: `'[{"instruction": "x", "priority": "high", "explanation": "y", "dimension": "quality"}]'`. **Trace**: "quality" ∉ {"instruction", "adequacy"} → `_malformed` → raise. **Assertions**: `pytest.raises(ComplianceVerdictError)`
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/llm/test_models.py -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: facade import works; `ComplianceFinding` exposes `dimension`; the parser validates the closed set
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/llm/models.py tests/llm/test_models.py` — fix formatting if necessary

### Task 2: `build_fields_text` and `build_compliance_fields` with the step-type line and the attempt-history blocks (prettyplay/llm — request builders)

Context: the shared plain-text request builders of both providers gain the new inputs and the fixed block layouts. These are internal helpers of the llm cell (internal decomposition under the port contract — public surface unchanged). `build_fields_text(user_instructions, step_text, step_type, previous_steps, snapshot, page_url, cheat_sheet, attempt_history, recommendation, guidance)`: the scenario part opens with the `STEP TYPE: {step_type}` line **directly above** the `STEP:` block (the STEP TYPE line rides inside the scenario section — immediately before the STEP line, no blank line between); then PREVIOUS STEPS, PAGE SNAPSHOT, optional `PAGE URL: {url}` line after PAGE SNAPSHOT; then CHEAT SHEET; then optional USER INSTRUCTIONS; then optional `HISTORY:\n` + records joined by `\n`; then optional RECOMMENDATION; then optional USER GUIDANCE. Sections joined by `\n\n`. The former CODE/ERROR blocks and the steering-only HISTORY tail are gone. `build_compliance_fields(user_instructions, step_text, step_type, attempt_history, code)`: `INSTRUCTIONS:` block; the `STEP TYPE: {step_type}` line directly above the `STEP:` block; `ATTEMPT HISTORY:\n` + records (omitted when the list is empty); `CODE:` block — fixed four-block order. `build_classification_fields` unchanged. Update the existing `tests/llm/test_request.py` cases that reference the removed parameters.

**Usages relevant to this task:**
- `conventions`: docstring style, test mirroring in `tests/llm/test_request.py`.
- The llm CODEMANIFEST header annotations (step-type and attempt-history parity rules) — the builders are where the parity is physically realized.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/llm/test_request.py`, expected to fail at this stage): `build_fields_text` and `build_compliance_fields` accept the new parameter lists (keyword-callable with `step_type` and `attempt_history`; the removed `existing_code`/`error`/`guidance_history` gone)
- [ ] **Code**: rework `build_fields_text` — STEP TYPE line inside the scenario section directly above STEP; drop CODE/ERROR; HISTORY block after USER INSTRUCTIONS, records joined by `\n`, only when the list is non-empty; RECOMMENDATION then USER GUIDANCE
- [ ] **Code**: rework `build_compliance_fields` — four blocks INSTRUCTIONS, STEP (with its STEP TYPE line), ATTEMPT HISTORY (only when non-empty), CODE
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/llm/test_request.py -x` — contract tests pass
- [ ] **Logic tests** (add to `tests/llm/test_request.py`; scenarios verbatim from the design):
  - [ ] `test_build_fields_text_renders_step_type_line_directly_above_step` — **Setup**: none (pure builder). **Input**: `build_fields_text(user_instructions="Prefer id attributes", step_text="open the page", step_type="assertion", previous_steps=[], snapshot="- snap", page_url=None, cheat_sheet="# sheet", attempt_history=[], recommendation=None, guidance=None)`. **Trace**: sections: `"STEP TYPE: assertion\nSTEP:\nopen the page"` (the STEP TYPE line rides inside the scenario section — immediately before the STEP line, no blank line between), `"PREVIOUS STEPS:\n(none)"`, `"PAGE SNAPSHOT:\n- snap"`, `"CHEAT SHEET:\n# sheet"`, `"USER INSTRUCTIONS:\nPrefer id attributes"` → `"\n\n".join(sections)`. **Assertions**: `text.startswith("STEP TYPE: assertion\nSTEP:\nopen the page")`; `"PAGE URL" not in text` (None URL — no line); `"HISTORY" not in text` (empty history — no block); `"RECOMMENDATION" not in text and "USER GUIDANCE" not in text`
  - [ ] `test_build_fields_text_renders_history_between_instructions_and_recommendation` — **Setup**: one rendered record string `"execution failed\nurl: https://a.example -> https://b.example\ncode:\n...\nerror:\nboom"`. **Input**: `build_fields_text(..., user_instructions="Prefer id", attempt_history=[record], recommendation="use role locators", guidance="focus on the button")`. **Trace**: HISTORY section: `"HISTORY:\n" + record`; order: ... CHEAT SHEET, USER INSTRUCTIONS, HISTORY, RECOMMENDATION, USER GUIDANCE. **Assertions**: `index("USER INSTRUCTIONS:") < index("HISTORY:") < index("RECOMMENDATION:") < index("USER GUIDANCE:")`; `"HISTORY:\nexecution failed\nurl: https://a.example -> https://b.example" in text`
  - [ ] `test_build_compliance_fields_renders_four_blocks_with_step_type_line` — **Setup**: one record string. **Input**: `build_compliance_fields("Prefer id attributes", "the «Welcome back» message appears", "assertion", [record], code)`. **Trace**: `"INSTRUCTIONS:\n..."`, `"STEP TYPE: assertion\nSTEP:\n..."`, `"ATTEMPT HISTORY:\n"+record`, `"CODE:\n"+code`. **Assertions**: `text.index("INSTRUCTIONS:") < text.index("STEP TYPE:") < text.index("STEP:") < text.index("ATTEMPT HISTORY:") < text.index("CODE:")`; `text.startswith("INSTRUCTIONS:")`; `"STEP TYPE: assertion\nSTEP:" in text`
  - [ ] `test_build_compliance_fields_omits_attempt_history_block_when_empty` — **Setup**: none. **Input**: `build_compliance_fields("Prefer id attributes", "open the page", "action", [], code)`. **Trace**: sections INSTRUCTIONS, STEP TYPE+STEP, CODE (no ATTEMPT HISTORY). **Assertions**: `"ATTEMPT HISTORY" not in text`
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/llm/test_request.py -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: block orders match the port contract requirement (CHEAT SHEET, user instructions, HISTORY, RECOMMENDATION, USER GUIDANCE; PAGE URL after PAGE SNAPSHOT; STEP TYPE before STEP; compliance: INSTRUCTIONS, STEP, ATTEMPT HISTORY, CODE)
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/llm/_request.py tests/llm/test_request.py` — fix formatting if necessary

### Task 3: LLM port signatures and both provider implementations in full parity (prettyplay/llm — provider + openai + anthropic)

Context: the port methods change signature and both SDK implementations carry the new inputs through with absolute parity. Contract entities: `LLMProvider.generate_step_code` (new `step_type: str`, `attempt_history: list[str]`; **removed** `existing_code`, `error`, `guidance_history`), `LLMProvider.check_instruction_compliance` (new `step_type: str`, `attempt_history: list[str]`), `LLMProvider::OpenAIProvider`, `LLMProvider::AnthropicProvider` (algorithm texts updated; the frozen parity now covers the STEP TYPE line and the HISTORY/ATTEMPT HISTORY blocks). Locations: `prettyplay/llm/provider.py` (abstract port, docstrings per contract; `create_provider` untouched), `prettyplay/llm/openai_provider.py`, `prettyplay/llm/anthropic_provider.py`. Both providers: signatures updated, field builders from Task 2 called with the new inputs, the compliance operation passes `step_type` + `attempt_history` through the **effective generation model** → `parse_compliance_verdict` (no fence unwrapping); one SDK request per operation; SDK errors → `LLMUnavailableError`. Classification untouched. Update the existing `tests/llm/test_provider.py`, `tests/llm/test_openai_provider.py`, `tests/llm/test_anthropic_provider.py` to the new signatures — **no removed parameter may survive in any stub or test**.

**Usages relevant to this task:**
- `openai` (`.goga/usages/cooks/openai.md`) / `anthropic` (`.goga/usages/cooks/anthropic.md`): SDK call patterns and the error mapping — one request per operation, SDK errors → `LLMUnavailableError`.
- `conventions`: docstrings, test mirroring.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/llm/test_provider.py` + the provider test files, expected to fail at this stage): the port declares `generate_step_code(..., step_type, ..., attempt_history, recommendation, guidance)` and `check_instruction_compliance(..., step_type, code, attempt_history)`; the removed parameters are gone from the abstract signatures
- [ ] **Code**: update `provider.py` port signatures + docstrings (parameter semantics per the contract: `step_type` renders as the STEP TYPE line immediately before the STEP line; `attempt_history` renders as the HISTORY block after the USER INSTRUCTIONS block / the ATTEMPT HISTORY block of the verdict request; the list takes the place of the former existing_code, error and guidance_history inputs)
- [ ] **Code**: update `openai_provider.py` — both operations pass `step_type` + `attempt_history` into the Task-2 builders; compliance request goes through the effective generation model
- [ ] **Code**: update `anthropic_provider.py` — same changes, full parity (the SDK-forced max_tokens cap aside)
- [ ] **Code**: update the existing provider tests' stubs and call sites to the new signatures (remove every `existing_code`/`error`/`guidance_history` argument)
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/llm/ -x` — all llm tests pass
- [ ] **Logic tests** (add the parity scenario to `tests/llm/`; verbatim from the design):
  - [ ] `test_providers_render_identical_user_content_for_the_new_inputs` — **Setup**: both providers with SDK clients stubbed at the import point; identical inputs including `step_type="assertion"` and two rendered records; capture the `messages` payload each SDK client receives. **Input**: `generate_step_code(...)` and `check_instruction_compliance(...)` on both providers with the same arguments. **Trace**: `OpenAIProvider.generate_step_code(args)` → openai client receives messages=[system, user(text)]; `AnthropicProvider.generate_step_code(args)` → anthropic client receives system=..., messages=[user(text)]; same user text, field for field; the same pair for the compliance operation. **Assertions**: `openai_user_text == anthropic_user_text` (generation); `openai_compliance_text == anthropic_compliance_text` (verdict); both contain `"STEP TYPE: assertion"` and the HISTORY/ATTEMPT HISTORY blocks at the same positions
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/llm/ -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: parity absolute — same operations, same inputs, same output shapes, same failure taxonomy; the provider choice is a configuration decision, never a capability difference
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/llm/ tests/llm/` — fix formatting if necessary

### Task 4: new entity `StepAttempt` in `prettyplay/engine/attempts.py` with the facade export and the guarded URL read (prettyplay/engine — infrastructure + entity)

Context: the new contract entity of the engine cell — one verbatim record of the per-step attempt history; the unit the provider HISTORY block and the gate ATTEMPT HISTORY block render. Location: `prettyplay/engine/attempts.py` (**new file**). Model (verbatim from the design):

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

pydantic v2, `kw_only`, empty defaults (conventions); `frozen=True` realizes "a record is immutable once appended: no rewriting, no truncation". The outcome labels are the five contract labels verbatim, exposed as module constants; every construction site uses a constant (closed-set discipline, uniform with `ComplianceFinding` whose labels are validated one step before construction). `render() -> str` pinned format: line 1 — the outcome label verbatim; line 2 — `"url: {url_before} -> {url_after}"`; part 3 — `"code:\n{code}"`; part 4 (only when `error` non-empty) — `"error:\n{error}"`; parts joined with newlines. No collapsing, no size limits, no truncation of any field; the `code:`/`error:` markers separate the two free-text parts. Also add the cell-local guarded URL read (resolved design decision 1):

```python
def _read_url(page: PageFacade) -> str:
    try:
        return page.url
    except Exception:
        return ""                          # a dead page never kills the attempt; the pair degrades honestly
```

(`PageFacade` imported from `..driver`.) Facade obligation: add `StepAttempt` to `prettyplay/engine/__init__.py` imports and `__all__`. Also extend the engine test fixtures: `FakePage` gains a `url` property (returns a scripted value or raises) for the URL-bracket tests of Tasks 6–8 (the executor-test `FakePage` is extended in its own task). New test file `tests/engine/test_attempts.py`.

**Usages relevant to this task:**
- `conventions`: pydantic v2 `kw_only` + empty defaults; relative imports (`from .attempts import StepAttempt` inside the cell); tests mirror `tests/engine/test_attempts.py`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (new file `tests/engine/test_attempts.py`, expected to fail at this stage): facade accessibility `from prettyplay.engine import StepAttempt`; API shape — the five keyword-only properties with `str` types and empty defaults, the `render() -> str` method, the frozen model (mutation raises)
- [ ] **Code**: create `prettyplay/engine/attempts.py` with the five outcome constants, `StepAttempt` (model above) and `render()` per the pinned format
- [ ] **Code**: add the private `_read_url(page: PageFacade) -> str` guarded read to `attempts.py`
- [ ] **Code**: export `StepAttempt` from `prettyplay/engine/__init__.py` (`__all__` updated)
- [ ] **Code**: extend the engine-test `FakePage` with a `url` property (scripted value or raise)
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/engine/test_attempts.py -x` and `.venv/bin/python -c "from prettyplay.engine import StepAttempt"` — contract tests pass, facade import works
- [ ] **Logic tests** (in `tests/engine/test_attempts.py`; scenarios verbatim from the design):
  - [ ] `test_render_renders_every_field_verbatim` — **Setup**: none (pure model). **Input**: `StepAttempt(code="def step(page) -> None:\n    page.goto('https://a.example')\n", error="TimeoutError: click timed out", outcome=OUTCOME_EXECUTION_FAILED, url_before="https://a.example", url_after="https://b.example")`. **Trace**: `attempt.render()` → outcome line: "execution failed"; url line: "url: https://a.example -> https://b.example"; code part: "code:\n" + the two-line code, untouched; error part: "error:\nTimeoutError: click timed out"; join with newlines. **Assertions**: `record == "execution failed\nurl: https://a.example -> https://b.example\ncode:\ndef step(page) -> None:\n    page.goto('https://a.example')\nerror:\nTimeoutError: click timed out"`
  - [ ] `test_render_omits_error_part_when_error_empty` — **Setup**: none. **Input**: `StepAttempt(code="def step(page) -> None:\n    ...", error="", outcome=OUTCOME_REJECTED, url_before="u", url_after="u")`. **Trace**: render() → outcome line, url line, code part; error empty → no error part. **Assertions**: `record == "rejected by the engineer, not executed\nurl: u -> u\ncode:\ndef step(page) -> None:\n    ..."`; `"error:" not in record`
  - [ ] `test_render_keeps_the_empty_url_pair_visible` — **Setup**: none (pure model). **Input**: `StepAttempt(code="def step(page) -> None:\n    ...", error="TimeoutError: click timed out", outcome=OUTCOME_FAILED_CHECK, url_before="", url_after="")`. **Trace**: render() → outcome line "failed check"; url line "url:  -> " (both sides empty — the pair stays visible, truthfully empty; no dropping of the line, no placeholder); code part; error part. **Assertions**: `record.splitlines()[0] == "failed check"`; `record.splitlines()[1] == "url:  -> "`
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/engine/test_attempts.py -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: `StepAttempt` importable from `prettyplay.engine`; five properties + `render()` match the declared API; frozen
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/attempts.py prettyplay/engine/__init__.py tests/engine/test_attempts.py` — fix formatting if necessary

### Task 5: `check_step_compliance` two-dimension gate and the `COMPLIANCE_PROMPT` frozen-mirror re-sync (prettyplay/engine — compliance)

Context: the single gate of every caching path gains the step type and the rendered history, and its system prompt mirror must be re-synced to the rewritten `compliance_prompt` practice. Contract entity: `check_step_compliance(config, provider, step_text, step_type, code, attempt_history) -> findings: list[ComplianceFinding]` (location `prettyplay/engine/compliance.py`). Algorithm (verbatim from the design):

```
1. IF NOT config.generation_approve OR NOT config.generation_prompt: return []   # zero calls
2. return provider.check_instruction_compliance(
     prompt=COMPLIANCE_PROMPT,                     # frozen mirror of the compliance_prompt practice
     user_instructions=config.generation_prompt,
     step_text=step_text, step_type=step_type, code=code,
     attempt_history=[r.render() for r in attempt_history])
```

Errors: `LLMUnavailableError`/`ComplianceVerdictError` propagate — never swallowed, never cached. Edge cases: gate off / empty instructions → fully the old behavior; empty history → no ATTEMPT HISTORY block in the request. The frozen mirror: `COMPLIANCE_PROMPT` must equal the rewritten `compliance_prompt` practice of `prettyplay/engine/CODEMANIFEST` byte-for-byte (the block-scalar text) — the existing mirror tests (`test_compliance_prompt_is_a_frozen_constant`, `test_compliance_prompt_mirror_matches_the_code_manifest_practice`) are extended to the new text anchors; the mirror test pattern already exists — extend, don't reinvent. Update the existing `tests/engine/test_compliance.py` call sites to the new signature.

**Usages relevant to this task:**
- `compliance_prompt` (inline practice, engine CODEMANIFEST header) — the two-dimension gate system prompt; the frozen-mirror rule keeps prompt and constant in lockstep.
- `conventions`: test mirroring in `tests/engine/test_compliance.py`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/engine/test_compliance.py`, expected to fail at this stage): `check_step_compliance` accepts `step_type` and `attempt_history` (keyword-callable); `COMPLIANCE_PROMPT` equals the `compliance_prompt` block-scalar of the engine CODEMANIFEST byte-for-byte
- [ ] **Code**: update `check_step_compliance` — new parameters threaded into the provider call with the rendered history
- [ ] **Code**: re-sync `COMPLIANCE_PROMPT` to the rewritten two-dimension practice text
- [ ] **Code**: extend the frozen-mirror tests to the new text anchors; update existing call sites in the test file
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/engine/test_compliance.py -x` — contract tests pass
- [ ] **Logic tests** (add to `tests/engine/test_compliance.py`; scenario verbatim from the design):
  - [ ] `test_check_step_compliance_passes_step_type_and_rendered_history` — **Setup**: `ComplianceStubProvider` recording kwargs; `Config(generation_prompt="Prefer id attributes")`; two `StepAttempt` records (record 0 original + one failed check). **Input**: `check_step_compliance(config, provider, "click the «Sign in» button", "action", code, [record0, record1])`. **Trace**: switch on, instructions non-empty → `provider.check_instruction_compliance(prompt=COMPLIANCE_PROMPT, user_instructions="Prefer id attributes", step_text="click the «Sign in» button", step_type="action", code=code, attempt_history=[record0.render(), record1.render()])`. **Assertions**: `call["step_type"] == "action"`; `call["attempt_history"] == [record0.render(), record1.render()]`; `call["prompt"] == COMPLIANCE_PROMPT`
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/engine/test_compliance.py -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: gate off → zero provider calls; hard failures propagate; never called for replayed cached code (callers' responsibility, verified in Tasks 6/8/9)
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/compliance.py tests/engine/test_compliance.py` — fix formatting if necessary

### Task 6: `StepGenerator.generate`/`regenerate` — history growth, URL brackets, two-dimension gate, exhaustion wording, `SYSTEM_PROMPT` re-sync (prettyplay/engine — generator)

Context: the generation/healing loops now grow the per-step attempt history and carry honest inputs. Contract entities: `StepGenerator.generate(identity, step_text, step_type, previous_steps, page, attempt_history, window)` and `StepGenerator.regenerate(identity, step_text, step_type, previous_steps, page, attempt_history, recommendation, window)` — **removed inputs** `existing_code`/`error`. Location: `prettyplay/engine/generator.py`. Algorithm (`generate` pool, verbatim from the design):

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

**`regenerate` (healing pool)**: same loop shape with `try_healing`, `recommendation` on every request, every failure (checks included) appending its record and retrying, no per-attempt classification, no standing state; exhaustion raises `IncurableStepError(step_text, "healing attempt budget exhausted", last_record.error, code=last_record.code)` with the last facts derived from `history[-1]` (empty-string fallback when the history is empty). The loop's terminal-failure facts now derive from the history (`history[-1].code` / `history[-1].error`) — the signature no longer carries `existing_code`/`error`.

**`_violation_text(finding)`** (dimension-aware, rides the record's error field): `f"{finding.dimension} violation: {finding.instruction} — {finding.explanation}"` (e.g. `instruction violation: Prefer id attributes — locates by text` / `adequacy violation: click the «Sign in» button — code only checks an already-achieved state`). The medium/low WARNING renders the dimension: `f"{finding.priority} {finding.dimension}: {finding.instruction} — {finding.explanation}"`.

**Exhaustion with a standing finding** (wording updated to the contract's dimension-neutral text): verdict `FailureVerdict(category="incurable", explanation=f"{finding.instruction} — {finding.explanation}", recommendation=f"satisfy the finding in the step code: {finding.instruction}")`; reason `f"generation attempt budget exhausted — {_reason_safe(finding.instruction)}"` (colon-free); error field `_violation_text(finding)`.

Errors: unchanged taxonomy — `LLMUnavailableError` (request: immediate; classification: quiet WARNING skip), `ComplianceVerdictError` (propagates, nothing cached), `ProductDefectError`/`IncurableStepError` per the decision table. Edge cases: empty history (first attempt) → no HISTORY block; URL read failure → empty side(s), attempt proceeds (decision 1); a green attempt never appends a record (records exist only for attempts producing no cached step).

The frozen `SYSTEM_PROMPT` mirror in `generator.py` is stale (still documents CODE/ERROR inputs) — re-sync byte-for-byte with `.goga/usages/prompts/generation.md` after the `---` separator; the existing mirror tests (`test_generation_prompt_is_frozen_text`, `test_system_prompt_mirrors_the_generation_practice`) enforce it. Update the existing `tests/engine/test_generator.py` suite and its `StubProvider`/`ComplianceStubProvider` to the new signatures — the stubs record the new kwargs (`step_type`, `attempt_history`) and drop the removed ones.

**Usages relevant to this task:**
- `system_prompt` (`.goga/usages/prompts/generation.md`): the section after `---` mirrored byte-for-byte as `SYSTEM_PROMPT`; the mirror and the practice change together.
- `cheat_sheet` (`.goga/usages/prompts/cheatsheet.md`): the whole-file frozen mirror `CHEAT_SHEET` — already current, unchanged.
- `conventions`: test mirroring in `tests/engine/test_generator.py`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/engine/test_generator.py`, expected to fail at this stage): `generate`/`regenerate` accept `step_type` and `attempt_history` (keyword-callable); `regenerate` no longer accepts `existing_code`/`error`; `SYSTEM_PROMPT` mirrors `.goga/usages/prompts/generation.md` after `---` byte-for-byte
- [ ] **Code**: update `_request` (the engine-side request assembly) to the port signature — `step_type`, `attempt_history=[r.render() for r in history]`, `page_url=None`, `guidance=None`; removed parameters gone everywhere
- [ ] **Code**: implement the URL bracket in both loops (`url_before = _read_url(page)` → `settle(...)` → `url_after = _read_url(page)`) using `_read_url` from Task 4
- [ ] **Code**: implement the three record-append points in `_generation_loop` (failed check / execution failed / compliance blocked) and the retry-with-grown-history mechanics; `standing` state for the gate-blocked candidate
- [ ] **Code**: rework `_healing_loop` — anchored history threaded, every failure appends and retries, terminal facts from `history[-1]`, exhaustion `IncurableStepError(step_text, "healing attempt budget exhausted", ...)`
- [ ] **Code**: update `_violation_text` and `_medium_warning` to the dimension-aware wording; update `_exhaustion_outcome`'s standing-finding wording (dimension-neutral reason, colon-free)
- [ ] **Code**: re-sync the `SYSTEM_PROMPT` frozen mirror; update the existing generator tests + stub providers to the new signatures
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/engine/test_generator.py -x` — contract tests pass
- [ ] **Logic tests** (add to `tests/engine/test_generator.py`; scenarios verbatim from the design):
  - [ ] `test_generate_appends_execution_failed_record_and_retries_with_grown_history` — **Setup**: `StubProvider(answers=[bad_code, good_code], compliance_verdicts=[[]])`; `FakePage` with `url` cycling `"https://a.example"`/`"https://b.example"`; `RunBudgets` with room; tmp_path cache. **Input**: `generator.generate(identity, "open the videos page", "action", [], page, history=[], window)` where `bad_code` raises `RuntimeError("boom")` on execution. **Trace**: attempt 1: request (attempt_history=[]) → bad_code; url bracket → settle raises RuntimeError → `history.append(StepAttempt(bad_code, "RuntimeError: boom", OUTCOME_EXECUTION_FAILED, a, b))`; attempt 2: request (attempt_history=[rendered record]) → good_code; url bracket → settle green → gate returns [] → `_store` → CachedStep. **Assertions**: `provider.calls[0]["attempt_history"] == []`; `provider.calls[1]["attempt_history"] == [history[0].render()]`; `history[0].outcome == OUTCOME_EXECUTION_FAILED`; `history[0].error == "RuntimeError: boom" and history[0].code == bad_code`; `len(history) == 1` (the green attempt never records)
  - [ ] `test_generate_appends_compliance_blocked_record_on_high_adequacy_finding` — **Setup**: `StubProvider(answers=[code_checking_only, green], compliance_verdicts=[[ComplianceFinding(instruction="click the «Sign in» button", priority="high", explanation="code only checks an already-achieved state", dimension="adequacy")], []])`. **Input**: `generate(identity, "click the «Sign in» button", "action", [], page, [], window)`. **Trace**: attempt 1: green execution → gate → high adequacy finding → `history.append(StepAttempt(code, "adequacy violation: click the «Sign in» button — ...", OUTCOME_COMPLIANCE_BLOCKED, url_before, url_after))`; standing = finding; attempt 2: request carries the grown history → green → gate [] → store. **Assertions**: `history[0].outcome == OUTCOME_COMPLIANCE_BLOCKED`; `history[0].error.startswith("adequacy violation: click the «Sign in» button")`; `provider.calls[1]["attempt_history"] == [history[0].render()]`
  - [ ] `test_regenerate_never_loses_record_zero_through_retries` — **Setup**: `StubProvider(answers=[failing, green])`; anchored `history = [StepAttempt(code=cached_code, error="old rot", outcome=OUTCOME_ORIGINAL, ...)]`. **Input**: `generator.regenerate(identity, "click the «Sign in» button", "action", [], page, history, "use role locators", window)`. **Trace**: attempt 1: request carries [record0.render()] → candidate fails → `history.append(record1)` (record 0 untouched at index 0); attempt 2: request carries [record0.render(), record1.render()] → green → gate → store. **Assertions**: `history[0].code == cached_code and history[0].outcome == OUTCOME_ORIGINAL`; `provider.calls[0]["attempt_history"] == [history[0].render()]`; `provider.calls[1]["attempt_history"] == [history[0].render(), history[1].render()]`
  - [ ] `test_url_read_failure_degrades_to_empty_string_and_attempt_proceeds` — **Setup**: `FakePage` whose `url` property raises `RuntimeError("page crashed")`; `StubProvider(answers=[green], compliance_verdicts=[[]])`. **Input**: `generator.generate(identity, "open the page", "action", [], page, [], window)`. **Trace**: attempt 1: url_before read raises → "" ; settle green ; url_after read raises → "" → gate [] → store → CachedStep returned (no raise). **Assertions**: `result.code == green_code`; `history == []` (green attempt records nothing; the failed reads never surface)
  - [ ] `test_generation_exhaustion_with_standing_adequacy_finding_names_the_step_fragment` — **Setup**: `RunBudgets` allowing exactly one generation attempt and refusing healing; provider answer green-executing but the gate returns a high adequacy finding every time it is called. **Input**: `generate(identity, "click the «Sign in» button", "action", [], page, [], window)`. **Trace**: attempt 1: green → gate high adequacy → record appended; standing = finding; loop: try_generation refused → `_exhaustion_outcome(standing)` → `IncurableStepError` with verdict(category="incurable", explanation="click the «Sign in» button — code only checks an already-achieved state", recommendation="satisfy the finding in the step code: click the «Sign in» button"). **Assertions**: `exc.verdict.category == "incurable"`; `exc.verdict.recommendation.startswith("satisfy the finding in the step code:")`; `"generation attempt budget exhausted" in exc.reason and ":" not in exc.reason`; `exc.error.startswith("adequacy violation:")`
  - [ ] `test_regenerate_exhaustion_derives_terminal_facts_from_last_record` — **Setup**: `StubProvider(answers=[failing_code])` — `failing_code` raises `RuntimeError("boom")` on execution; `RunBudgets` allowing exactly one healing attempt; anchored `history = [StepAttempt(code=cached_code, error="old rot", outcome=OUTCOME_ORIGINAL, url_before="https://a.example", url_after="https://b.example")]`; tmp_path cache; `FakePage` with `url` returning fixed values. **Input**: `generator.regenerate(identity, "click the «Sign in» button", "action", [], page, history, "use role locators", window)`. **Trace**: try_healing granted (attempt 1) → request carries [record0.render()] → failing_code; url bracket → settle raises RuntimeError → `history.append(StepAttempt(failing_code, "RuntimeError: boom", OUTCOME_EXECUTION_FAILED, url_before, url_after))`; loop: try_healing refused → `raise IncurableStepError(step_text, "healing attempt budget exhausted", history[-1].error, code=history[-1].code)` (verdict None — the healer attaches the entry verdict). **Assertions**: `pytest.raises(IncurableStepError) as exc_info`; `exc_info.value.reason == "healing attempt budget exhausted"`; `exc_info.value.code == failing_code and exc_info.value.error == "RuntimeError: boom"`; `exc_info.value.verdict is None`; `len(history) == 2 and history[0].code == cached_code and history[0].outcome == OUTCOME_ORIGINAL`
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/engine/test_generator.py -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: every request carries the raw sentence, the step type and the rendered history; the closed outcome label set; the exhaustion wording pins; the frozen mirrors byte-equal
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/generator.py tests/engine/test_generator.py` — fix formatting, apply decomposition if necessary

### Task 7: `StepHealer.heal` with honest inputs and the anchored history; `classify_step_failure` docstring pin (prettyplay/engine — healer + classification)

Context: the healing engine forwards the raw sentence, the step type and the anchored history into classification and regeneration. Contract entities: `StepHealer.heal(step, error, step_text, step_type, previous_steps, page, attempt_history, window) -> step: CachedStep` (location `prettyplay/engine/healer.py`); `classify_step_failure` (location `prettyplay/engine/classification.py`) — annotation wording only: `step_text` is the raw sentence as passed by the calling engine; signature and behavior unchanged. Algorithm (verbatim from the design):

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

Edge cases: record 0 already seeded by the executor — `heal` never re-seeds; the history object is threaded (mutations by `regenerate` remain visible to the executor for the steering intercept). **Behavior change**: the current implementation derives `step.identity.normalized_text` for classification — the contract pins the raw sentence. Update the existing `tests/engine/test_healer.py` call sites to the new signature.

**Usages relevant to this task:**
- `classification` (imported from `prettyplay/llm`, path `prettyplay/llm/.usages/classification.md`) — the healing decision categories (rot, product_defect, fixable, incurable).
- `classification_prompt` (inline practice, engine CODEMANIFEST header) — the classification system prompt; its frozen mirror `CLASSIFICATION_PROMPT` in `classification.py` is already current and must stay byte-equal while the docstring is touched.
- `conventions`: test mirroring in `tests/engine/test_healer.py`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/engine/test_healer.py`, expected to fail at this stage): `heal` accepts `step_text`, `step_type` and `attempt_history` in the contract order (keyword-callable)
- [ ] **Code**: update `StepHealer.heal` — new parameters; classification receives the raw `step_text` parameter; `regenerate` called with the threaded history and the step type; inner `IncurableStepError` re-raised carrying the entry verdict (`raise … from inner`)
- [ ] **Code**: update the `classify_step_failure` docstring in `classification.py` to pin the raw-sentence semantics (wording only — signature and behavior unchanged)
- [ ] **Code**: update the existing healer tests to the new signature
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/engine/test_healer.py tests/engine/test_classification.py -x` — contract tests pass
- [ ] **Logic tests** (add to `tests/engine/test_healer.py`; scenario verbatim from the design):
  - [ ] `test_heal_passes_raw_sentence_and_anchored_history_into_regenerate` — **Setup**: `StubProvider` scripted with a rot classification; `StepHealer` wrapping the generator; anchored history with record 0. **Input**: `healer.heal(cached_step, error_text, "Click the «Sign IN» button", "action", [], page, history, window)` (note the non-normalized casing). **Trace**: `heal(...)` → `classify_step_failure(..., step_text="Click the «Sign IN» button", ...)` (raw, not normalized_text) → rot → `generator.regenerate(..., step_text="Click the «Sign IN» button", step_type="action", attempt_history=history, recommendation="use role locators", ...)`. **Assertions**: `provider.classify_failure_calls[0]["step_text"] == "Click the «Sign IN» button"`; generator received the same raw sentence (recorded by the stub); history object passed by reference — record 0 intact
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/engine/test_healer.py tests/engine/test_classification.py -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: the decision table unchanged (product_defect never healed); record 0 never re-seeded; the history threaded, not copied
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/healer.py prettyplay/engine/classification.py tests/engine/test_healer.py` — fix formatting if necessary

### Task 8: `StepSteering.steer` joins the shared history with per-turn URL brackets and the two-dimension write-back gate (prettyplay/engine/steering)

Context: the interactive steering dialog drops its local turn history and joins the one shared per-step attempt history. Contract entity: `StepSteering.steer(failure, identity, step_text, step_type, previous_steps, page, attempt_history) -> healed: CachedStep | None` (location `prettyplay/engine/steering/steering.py`; the cell's Imports add `StepAttempt` from `prettyplay/engine`). Algorithm (verbatim from the design):

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

The old `_turn_record` helper and the dialog-local `history: list[str]` are **deleted** (not adapted). Edge cases: rejected turn — same URL both sides; the gate sees the history without the current turn's record (the candidate rides the CODE block); the dialog never outlives the failure (every exit heals or returns None). The frozen `SYSTEM_PROMPT` mirror in `steering.py` is stale (old HISTORY wording) — re-sync byte-for-byte with `.goga/usages/prompts/generation.md` after `---` (the existing `test_steering_mirrors_the_practices` enforces it). Update the existing `tests/engine/steering/test_steering.py` fixtures and stubs to the new signature.

**Usages relevant to this task:**
- `system_prompt` (`.goga/usages/prompts/generation.md`): the frozen `SYSTEM_PROMPT` mirror re-synced byte-for-byte after `---`.
- `cheat_sheet`: the whole-file frozen mirror — already current.
- `conventions`: test mirroring in `tests/engine/steering/test_steering.py`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/engine/steering/test_steering.py`, expected to fail at this stage): `steer` accepts `step_text`, `step_type` and `attempt_history` in the contract order; `_turn_record` gone; the `SYSTEM_PROMPT` mirror byte-equal to the practice
- [ ] **Code**: update the guidance-turn request — `step_text`, `step_type`, `attempt_history=[r.render() for r in history]`, `recommendation=None`, `guidance=message`; no `guidance_history` anywhere
- [ ] **Code**: implement the per-turn URL brackets via `_guarded_url(page) or ""` (rejected turn — one read, same value both sides; approved turn — before/after the bare `run_step_code`)
- [ ] **Code**: implement the record appends (rejected / failed check / execution failed / compliance blocked) into the shared history; delete `_turn_record` and the dialog-local history
- [ ] **Code**: gate the write-back through `check_step_compliance` with the step type and the shared history — high of either dimension blocks (no write-back, record, re-prompt); hard failure → line + WARNING → `return None`
- [ ] **Code**: re-sync the `SYSTEM_PROMPT` mirror; update the existing steering tests to the new signature
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/engine/steering/test_steering.py -x` — contract tests pass
- [ ] **Logic tests** (add to `tests/engine/steering/test_steering.py`; scenarios verbatim from the design):
  - [ ] `test_steer_appends_rejected_record_with_same_url_on_both_sides` — **Setup**: steering fixtures (stdin scripted "fix the button\nn\nquit"); `FakePage.url` returns `"https://s.example"`; stub provider returns code. **Input**: `steering.steer(failure, identity, "click the «Sign in» button", "action", [], page, history)` with an anchored record 0. **Trace**: turn 1: request (attempt_history=[record0.render()], guidance="fix the button", step_type="action") → run? n → u = "https://s.example" → `history.append(StepAttempt(code, "", OUTCOME_REJECTED, "https://s.example", "https://s.example"))` → prompt reopens → quit → return None. **Assertions**: `history[1].outcome == OUTCOME_REJECTED and history[1].error == ""`; `history[1].url_before == history[1].url_after == "https://s.example"`; `provider.calls[0]["step_type"] == "action"`; `provider.calls[0]["guidance"] == "fix the button"`
  - [ ] `test_steer_gates_with_shared_history_and_blocks_on_high_finding` — **Setup**: stdin "try again\ny\nonce more\ny\nquit"; provider answers two candidates; compliance verdicts scripted [[high instruction finding], []] — the first gate call blocks, the second passes. **Input**: `steer(failure, identity, step_text, "action", [], page, history)` (anchored record 0). **Trace**: turn 1: request → approved → run green → gate → high instruction finding → no write-back; `history.append(StepAttempt(code, "instruction violation: ...", OUTCOME_COMPLIANCE_BLOCKED, u, u))`; turn 2: request carries [record0, blocked record] → approved → green → gate [] → write-back → return healed. **Assertions**: `cache.save called once, after the second gate pass`; `provider.calls[1]["attempt_history"] == [history[0].render(), history[1].render()]`; `history[1].outcome == OUTCOME_COMPLIANCE_BLOCKED`
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/engine/steering/test_steering.py -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: no budget consumed, no polling, guidance never persisted; every exit path heals or returns None; record truncation nowhere
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/steering/steering.py tests/engine/steering/test_steering.py` — fix formatting, apply decomposition if necessary

### Task 9: `StepExecutor.execute` owns the per-step attempt history and threads honest inputs (prettyplay — root executor)

Context: the executor creates the history, seeds record 0 on a failed cached hit, brackets the replay, and threads the raw sentence + step type + history into every engine call. Contract entity: `StepExecutor.execute(step_text, step_type, page)` (location `prettyplay/executor.py`; the root cell's Imports add `StepAttempt` from `prettyplay/engine`). Algorithm (delta only, verbatim from the design):

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
                      self._scenario, page, attempt_history)
```

The strict path is untouched except the (already raw) sentence into classification. `step`, `expect`, `run_on_page`, hooks, renders, `on_step_finished` — unchanged. Add the root-cell-local `_read_url(page) -> str` guarded read (same three-line guard as the engine's; cell-local, private — the contracts declare no shared routine). The interaction diagram this task implements (verbatim from the design):

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

Update the existing `tests/test_executor.py` fixtures (fake generator/healer/steering recording kwargs) to the new call shapes.

**Usages relevant to this task:**
- `generation`, `healing` (imported from `prettyplay/engine`, paths `prettyplay/engine/.usages/generation.md` / `healing.md`) — the engine cycles the executor delegates to; already updated by the apply stage.
- `taxonomy` (imported from `prettyplay/failures`) — the failure kinds the step methods propagate.
- `hooks` (imported from `prettyplay/reporting`) — the reporter events the cycle fires (`on_step_started`, `on_step_passed`, `on_step_failed`, `on_step_verdict`, `on_step_finished`) — all unchanged by this task; the event sequence must survive the threading changes intact.
- `conventions`: test mirroring in `tests/test_executor.py`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/test_executor.py`, expected to fail at this stage): `execute(step_text, step_type, page)` signature unchanged; the executor delegates with the contract call shapes — `generate(identity, step_text, step_type, scenario, page, attempt_history, window)`, `heal(cached, error_text, step_text, step_type, scenario, page, attempt_history, window)`, `steer(failure, identity, step_text, step_type, scenario, page, attempt_history)`
- [ ] **Code**: import `StepAttempt` (and the outcome constants) from `prettyplay.engine`; create the per-step history in step 2 (fresh empty list per execution)
- [ ] **Code**: bracket the cached replay with the guarded `_read_url` reads (step 3); seed record 0 on a non-strict hit failure before the heal delegation (step 4)
- [ ] **Code**: thread the raw sentence, the step type and the history into generate / heal / `_steer_or_raise` → `steer` (steps 4–6)
- [ ] **Code**: update the existing executor tests' fake engines to record the new kwargs
- [ ] **Code**: extend the executor-test `FakePage` with a `url` property (a scripted value or raise) as the URL-bracket tests require
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/test_executor.py -x` — contract tests pass
- [ ] **Logic tests** (add to `tests/test_executor.py`; scenarios verbatim from the design):
  - [ ] `test_execute_seeds_record_zero_on_failed_cached_hit` — **Setup**: executor fixtures (fake cache returning a cached step, fake healer recording kwargs); `FakePage.url` returns `"https://a.example"` then `"https://b.example"`; cached code raises on replay. **Input**: `executor.execute("Click the «Sign in» button", "action", page)`. **Trace**: hit; url_before read; settle raises; url_after read → `history.append(StepAttempt(code=cached.code, error=format_step_error(exc), outcome=OUTCOME_ORIGINAL, url_before="https://a.example", url_after="https://b.example"))` → `healer.heal(cached, error_text, "Click the «Sign in» button", "action", scenario, page, history, window)`. **Assertions**: healer received attempt_history with exactly one record before the call; `record.outcome == OUTCOME_ORIGINAL and record.code == cached.code`; `record.url_before == "https://a.example" and record.url_after == "https://b.example"`; healer received step_text="Click the «Sign in» button" (raw) and step_type="action"
  - [ ] `test_execute_passes_empty_history_and_raw_sentence_to_generate` — **Setup**: executor fixtures; fake cache miss; fake generator recording kwargs. **Input**: `executor.execute("Open the LOGIN page", "action", page)`. **Trace**: miss → `generator.generate(identity, "Open the LOGIN page", "action", scenario, page, history=[], window)`. **Assertions**: generator received step_text="Open the LOGIN page" (raw, not casefolded); generator received step_type="action" and attempt_history == []; `identity.normalized_text == "open the login page"` (addressing still normalized)
  - [ ] `test_execute_creates_history_per_step_and_never_carries_it_across_steps` — **Setup**: executor fixtures; two consecutive cache-miss steps. **Input**: `execute("open the page", "action", page)` then `execute("click the button", "action", page)`. **Trace**: step 1 → generator receives history_a == []; step 2 → generator receives history_b == [] (a fresh list, not history_a grown). **Assertions**: `generator.calls[0]["attempt_history"] == [] and generator.calls[1]["attempt_history"] == []`; the two lists are distinct objects (identity check via the recorded call args or a marker append)
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/test_executor.py -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: the strict path untouched; `on_step_finished` fires exactly once per step; record 0 composed before the heal delegation
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/executor.py tests/test_executor.py` — fix formatting if necessary

### Task 10: Integration tests for the end-to-end step cycle with the shared attempt history

Context: after every coding task, verify the full chain end to end — the three data-flow scenarios of the design exercised through the public facade with stubbed providers, and the whole suite green under the new signatures. The integration suite `tests/test_integration.py` already exists with SDK-stubbed providers; its stubs and call expectations must be updated to the new port signature (no `existing_code`/`error`/`guidance_history` anywhere; the new `step_type`/`attempt_history` kwargs recorded and asserted where the cycles carry them).

**Usages relevant to this task:**
- `conventions`: integration tests at `tests/test_integration.py`, `Test<Component>` classes, `test_<what>_<scenario>` names.
- The existing idioms: stubbed provider classes recording kwargs; tmp_path caches; scripted stdin for the interactive dialog (`test_interactive_steering_heals_a_stuck_step_end_to_end`).

**Data flows to verify (verbatim from the design):**

**Scenario A — cache miss (generation).** `execute` creates `attempt_history = []` (step 2) → `generate` loops: snapshot + screenshot → provider request carrying `step_type`, raw `step_text`, `[r.render() for r in attempt_history]` → URL bracket → `settle(run_step_code)`: execution failure → append record (outcome `execution failed`, `format_step_error` text) → next iteration sees the grown history; failed check (AssertionError surviving the window) → append record (outcome `failed check`) → classification → decision table (terminal, or one funded regeneration carrying recommendation + grown history); green → gate; high finding of either dimension → append record (outcome `compliance blocked`, violation text in `error`) → retry with grown history; empty/medium/low → store `CachedStep`, return. History dies with the step; only the `CachedStep` persists.

**Scenario B — failed cached hit (healing).** `execute` brackets the replay with URL reads → on failure: `error_text = format_step_error`, record 0 = `StepAttempt(code=cached.code, error=error_text, outcome=original cached code, url_before, url_after)` appended → `heal(step, error_text, step_text, step_type, scenario, page, history, window)` → classification with the **raw** sentence → rot|fixable → `regenerate(identity, step_text, step_type, previous_steps, page, history, recommendation, window)` → the healing loop mirrors scenario A minus per-attempt classification; record 0 is never rebound.

**Scenario C — terminal failure, interactive steering.** `IncurableStepError` caught in `execute` → interactive and non-strict → `steer(failure, identity, step_text, step_type, previous_steps, page, attempt_history)` — receives the history already grown by the engine loop (anchored by record 0 on the heal path). Each guidance turn: request with rendered shared history + USER GUIDANCE; engineer rejects → record (outcome `rejected by the engineer, not executed`, same URL both sides); approved → URL bracket around bare `run_step_code`; failure → record (`failed check`/`execution failed`); green → gate with the shared history; blocked → record (`compliance blocked`); passed → `CachedStep(identity)` write-back + `on_healed`, return healed → `execute` continues the step as a success.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] Update the integration-suite provider stubs to the new port signature; assert `step_type` reaches generation and verdict requests end to end
- [ ] Test Scenario A end to end: a cache-miss step whose first candidate fails and whose retry request carries the grown rendered history; the green candidate stores a `CachedStep`; the history never reaches the cache file
- [ ] Test Scenario B end to end: a failed cached hit seeds record 0 and heals through regeneration; the raw sentence reaches the classification request; record 0 stays intact through the healed write-back
- [ ] Test Scenario C end to end (scripted stdin): a stuck step steered to a healed write-back — the shared history threads engine records into the dialog requests; the write-back passes the two-dimension gate; the declined path propagates the original failure
- [ ] Test edge case: a high adequacy finding blocks the write-back end to end (never cached), mirroring the unit-level guarantee at the facade level
- [ ] Run validation: `.venv/bin/python -m pytest tests/ -x` — the full suite passes
- [ ] Lint: `.venv/bin/ruff check prettyplay/ tests/` — fix formatting if necessary

---

## Validation Commands

- `.venv/bin/python -m pytest tests/llm/test_models.py -x`: Task 1 — the verdict model and parser
- `.venv/bin/python -m pytest tests/llm/test_request.py -x`: Task 2 — the request field builders
- `.venv/bin/python -m pytest tests/llm/ -x`: Task 3 — the port and both providers (incl. parity)
- `.venv/bin/python -m pytest tests/engine/test_attempts.py -x`: Task 4 — the attempt record
- `.venv/bin/python -m pytest tests/engine/test_compliance.py -x`: Task 5 — the two-dimension gate + the COMPLIANCE_PROMPT mirror
- `.venv/bin/python -m pytest tests/engine/test_generator.py -x`: Task 6 — the generation/healing loops
- `.venv/bin/python -m pytest tests/engine/test_healer.py tests/engine/test_classification.py -x`: Task 7 — the healer and the classification pin
- `.venv/bin/python -m pytest tests/engine/steering/test_steering.py -x`: Task 8 — the steering dialog
- `.venv/bin/python -m pytest tests/test_executor.py -x`: Task 9 — the executor threading
- `.venv/bin/python -m pytest tests/ -x`: Run all tests (Task 10 and any task's final check)
- `.venv/bin/ruff check prettyplay/ tests/`: Lint check
- `.venv/bin/python -c "from prettyplay.engine import StepAttempt"`: Facade check — the new engine entity
- `.venv/bin/python -c "from prettyplay import PrettyPlay"`: Facade check — the root facade
- `goga lint`: CODEMANIFEST consistency (10 cells, 0 errors — contracts untouched)

---

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location` (`StepAttempt` in `prettyplay/engine/attempts.py`; all changed signatures in their declared locations)
- [ ] Every contract entity is accessible from the facade (`StepAttempt` importable from `prettyplay.engine`; `PrettyPlay` importable from `prettyplay`)
- [ ] Properties and methods match the declared API (port signatures, engine method signatures, `steer`, `execute` call shapes)
- [ ] Descriptions are reflected in behavior (render format, block orders, outcome label set, guarded reads, anchoring, two-dimension gate)
- [ ] Contract dependencies are met (`StepAttempt` travels only along the pre-existing edges engine→steering and engine→root; zero new dependency edges)
- [ ] Re-exports are accessible from the facade (`PrettyConfig`, `BrowserConfig`, `StepHooks` — unchanged)
- [ ] Every coding task followed the TDD workflow (contract tests → code → verification → logic tests → debugging → re-verification → lint)
- [ ] Contract tests and logic tests cover facade, API, and behavior within each coding task
- [ ] Integration tests exist where cross-entity scenarios require them (Task 10: scenarios A/B/C)
- [ ] No package boundary was expanded (no new cells, no new cross-cell exports — the guarded URL reads stay cell-local)
- [ ] `CODEMANIFEST` files were not modified (contract is read-only)
- [ ] All validation commands pass
- [ ] Every Usages entry is mentioned in at least one task (`conventions`, `system_prompt`, `cheat_sheet`, `classification_prompt`, `compliance_prompt`, `openai`, `anthropic`, imported `classification`, `hooks`, `taxonomy`, `generation`, `healing`)
- [ ] The removed inputs survive nowhere (port, providers, engine loops, stubs, tests): `existing_code`, `error` (of `generate_step_code`/`regenerate`), `guidance_history`; the steering `_turn_record` helper is deleted
- [ ] The frozen mirrors are byte-equal (`SYSTEM_PROMPT` in `generator.py` and `steering.py`, `COMPLIANCE_PROMPT` in `compliance.py`, `CHEAT_SHEET` unchanged)
- [ ] Nothing from the attempt history is persisted to the cache file or dumped to logs
