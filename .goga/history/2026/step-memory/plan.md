# Plan: `step-memory`

Result of compiling `.goga/history/2026/step-memory/design.md` (design review applied) into a ralphex execution plan.
Topic directory: `.goga/history/2026/step-memory/`. Base branch: `origin/0.0.x` (all changes in the working tree).

## Purpose

Implement the step-memory feature across eight cells of `prettyplay`: Jinja step templates with the `{% var %}` capture extension, the per-test `StepMemory` of captured observations, deterministic validation of returned step results, prepared-instruction threading through every engine and LLM request, keyword-only `vars` on the facade/group step surface, result carriage through `settle`/`run_step_code`, recovery row re-rendering, and steering turn validation.

After implementation the package provides: template sentences render to `PreparedStep` products before every cycle (authoring errors surface before any browser execution), captures publish only after validation plus the compliance gate, every LLM request and raised failure carries the prepared instruction (never raw Jinja), and the cache addresses steps by their raw template source.

Strategy: leaf cells first (`cache` → `polling` → `renderer` → `llm` → `engine` → `groups` → `steering` → root facade/executor), one TDD task per contract location, with the project conventions (`.goga/usages/conventions.md`) enforced as mandatory rules (see "Mandatory Rules") and a REPL-driven inner loop per task (see "REPL Cycle Rules").

## Context

### Contract Surface

#### Cell: `prettyplay/cache`

**Entity: `normalize_step_text(text: str) -> normalized: str`** (changed)
- Type: function; `location: text.py`
- Template/ordinary split: a sentence containing any of `{{`, `{%`, `{#` → NFC + trim only (verbatim otherwise — case-sensitive names, significant expression whitespace); otherwise the unchanged pipeline (NFC, trim, collapse internal whitespace, casefold).
- Pure, deterministic on `text` alone; runtime values never enter the address.
- Global annotation (cell): identity stays on the original template sentence; runtime values never enter the address.

#### Cell: `prettyplay/engine/polling`

**Entity: `settle(execute: Callable[[str, PageFacade], dict[str, str] | None], code: str, page: PageFacade, window: SettleWindow) -> result: dict[str, str] | None`** (changed)
- Type: function; `location: settle.py`
- Carries the successful execution's result through untouched — including the result of a successful count-mode retry; the loop never inspects, validates or alters the result; validation belongs to the calling cycle.
- Everything else unchanged: pollable filter, settle_retry INFO records, per-call zero counter in count mode.

#### Cell: `prettyplay/engine/renderer` (NEW)

**Entity: `PreparedStep(instruction: str, inputs: dict[str, str], declarations: list[str])`**
- Type: class (pydantic v2, `kw_only=True`, `frozen=True`, empty defaults); `location: render.py`
- Properties: `instruction -> str`, `inputs -> dict[str, str]`, `declarations -> list[str]`, `has_declarations -> bool` (a plain property, not a field).
- Facade obligation: importable from `prettyplay.engine.renderer`.

**Entity: `render_step(text: str, step_type: str, memory: StepMemory, vars: dict[str, str] | None) -> prepared: PreparedStep`**
- Type: function; `location: render.py`; `jinja2` import lives here
- The render point of every step execution and recovery re-invocation. Per-call Jinja `Environment(autoescape=False, undefined=StrictUndefined, extensions=[VarExtension])`; `template.render(snapshot, vars=inputs)`; all authoring errors raise `PrettyplayError` naming the problem and the offending name, before any browser execution. Constraints: no browser/LLM/page access; no mutation of `memory`.

**Entity: `StepMemory()`**
- Type: class (plain mutable class — not pydantic); `location: memory.py`
- Methods: `snapshot() -> values: dict[str, str]` (stable copy), `publish(captures: dict[str, str])` (atomic replace-or-keep; names never removed; one call per accepted execution).
- Facade obligation: importable from `prettyplay.engine.renderer`.

**Entity: `validate_step_result(prepared: PreparedStep, result: object) -> captures: dict[str, str]`**
- Type: function; `location: validation.py`
- Deterministic gate: no declarations → None accepted (`{}`), non-None → violation; declarations → None → violation; non-dict → violation ("result must be a dictionary") before key inspection; key set equality (order-free) with `declarations`; every value `str` and non-blank. Violations raise `AssertionError` with the deterministic text. Never fabricates or repairs.

Renderer facade: `__init__.py` exposes `PreparedStep`, `render_step`, `StepMemory`, `validate_step_result` through `__all__` (relative imports only).

#### Cell: `prettyplay/llm`

**Entity: `ScenarioStep(sentence: str, instruction: str, group_prompt: str)`** (changed)
- `location: models.py`; pydantic v2, kw_only, frozen, empty defaults
- New `instruction` field: the prepared instruction recorded at execution; equals `sentence` for a non-template step; the only field requests render.

**Entity: `LLMProvider` methods** (changed signatures)
- `generate_step_code(prompt, user_instructions, instruction, step_type, previous_steps, group_prompt, inputs: dict[str, str], declarations: list[str], snapshot, page_url, screenshot, cheat_sheet, attempt_history, recommendation, guidance) -> code: str` — `step_text` renamed to `instruction`, plus `inputs` and `declarations`.
- `check_instruction_compliance(prompt, user_instructions, instruction, step_type, inputs, declarations, code, attempt_history) -> verdict: list[ComplianceFinding]` — same three prepared-step primitives.
- `classify_step_failure(...)` — signature unchanged; `step_text` is now the prepared instruction (semantics only).
- `classify_group_failure(prompt, user_instructions, group_prompt, group_steps, previous_steps: list[ScenarioStep], step_text, attempt_history, snapshot, screenshot) -> diagnosis` — gains `previous_steps`.
- Block order (fixed, defect-D1 lock): STEP TYPE line, STEP line, then INPUTS (when non-empty) and RESULTS (when non-empty) immediately after the STEP line; GROUP PROMPT immediately before PREVIOUS STEPS; PAGE URL immediately after PAGE SNAPSHOT. Compliance order: INSTRUCTIONS, STEP TYPE + STEP, optional INPUTS, optional RESULTS, ATTEMPT HISTORY, CODE. Group diagnosis: GROUP PROMPT, optional PREVIOUS STEPS, GROUP STEPS, STEP, HISTORY, PAGE SNAPSHOT, optional SCREENSHOT, USER INSTRUCTIONS last.
- `_request.py` builders: `build_fields_text(..., inputs, declarations, ...)`; `_previous_step_line(record)` renders `record.instruction` (+ group marking); `build_group_diagnosis_fields(..., previous_steps)`; `build_compliance_fields(..., inputs, declarations)`.
- Provider parity is absolute: both implementations compose identically.

#### Cell: `prettyplay/engine`

**Entity: `run_step_code(code: str, page: PageFacade) -> result: dict[str, str] | None`** (changed)
- `location: execution.py` — returns the step function's result as-is (plain data).

**Entity: `StepGenerator.generate / regenerate`** (changed signatures)
- `generate(identity, prepared: PreparedStep, step_type, previous_steps, group_prompt, page, attempt_history, window, memory: StepMemory) -> step: CachedStep`
- `regenerate(identity, prepared, step_type, previous_steps, group_prompt, page, attempt_history, recommendation, window, memory) -> step: CachedStep`
- Acceptance ordering inside the loops: execute (settle) → `validate_step_result` (violation ≡ failed check, record with the violation text) → `check_step_compliance` (high finding blocks; hard failures propagate) → `memory.publish(captures)` exactly once → store → return.

**Entity: `check_step_compliance(config, provider, prepared: PreparedStep, step_type, code, attempt_history) -> findings`** (changed)
- `location: compliance.py` — takes the render product; the inline `compliance_prompt` (already updated in the CODEMANIFEST) gains INPUTS/RESULTS inputs and the RESULTS exact-key return-contract rule; frozen mirror `COMPLIANCE_PROMPT` updated in lockstep.

**Entity: `StepHealer.heal(step, error, prepared: PreparedStep, step_type, previous_steps, page, attempt_history, window, memory: StepMemory) -> step: CachedStep`** (changed)
- `location: healer.py` — classification sees the prepared instruction; regeneration threads `prepared` + `memory`.

**Entity: `classify_step_failure(config, provider, step_text, code, error, page)`** — signature unchanged; `step_text` receives the prepared instruction at every call site.

**Entity: `format_step_error(exc)`** — unchanged (the error-text policy already landed).

#### Cell: `prettyplay/engine/groups`

**Entity: `GroupStepOutcome(sentence, instruction, step_type, tries, delay, vars: dict[str, str], outcome, url_before, url_after, identity)`** (changed)
- `location: outcome.py` — new `instruction` + `vars` fields; `render()` renders the instruction line first.

**Entity: `classify_group_failure(config, provider, group_prompt, traces, previous_steps: list[ScenarioStep], step_text, step_type, attempt_history, page) -> diagnosis`** (changed)
- `location: diagnosis.py` — gains `previous_steps`; `step_text` is the failed step's prepared instruction.

**Entity: `GroupRecovery.recover(group_prompt, traces, prepared: PreparedStep, step_type, previous_steps, identity, attempt_history, page, window, memory: StepMemory) -> step: CachedStep`** (changed)
- `location: recovery.py` — local scenario/trace views (`model_copy(update=…)`, caller lists never mutated); active failure facts updated per row failure; per row step: quiet delay → `render_step(trace.sentence, trace.step_type, memory, trace.vars)` → `refresh_healing` → `regenerate` (execute → validate → gate → publish → store) → update the occurrence's instruction by index; a re-render authoring error propagates loudly.

#### Cell: `prettyplay/engine/steering`

**Entity: `StepSteering.steer(failure, identity, prepared: PreparedStep, step_type, previous_steps, group_prompt, page, attempt_history, memory: StepMemory) -> healed: CachedStep | None`** (changed)
- `location: steering.py` — banner and every request carry the prepared instruction with INPUTS/RESULTS; each green turn: `run_step_code` → `validate_step_result` (violation = red turn, record `failed check`) → gate → `memory.publish` + cache write-back.

#### Cell: `prettyplay` (root)

**Entities: `PrettyPlay.step` / `expect`, `StepGroup.step` / `expect`** (changed)
- Keyword-only `vars: dict[str, str] | None`; string-only validation at the call via a shared `_validate_vars` beside `_validate_tries`/`_validate_delay` in `groups.py` (imported by `scenario.py`); bools never coerce; every value must be `str`, else the loud actionable `PrettyplayError` naming the parameter, the received value and the allowed form.

**Entity: `StepExecutor.execute(step_text, step_type, page, group, tries, delay, vars)`** (changed)
- `location: executor.py` — the render point and memory owner: `StepMemory` constructed once in `__init__`; render **before** identity; identity from the **original** sentence; HIT path: `settle` → `validate_step_result` → publish (gate never runs on replay); violation → the failed-check paths; `ScenarioStep(sentence, instruction, group_prompt)` and the group trace carry both texts; hook events keep the raw sentence.

### Re-exports

- `prettyplay` re-exports `->PrettyConfig`, `->BrowserConfig`, `->StepHooks` — already implemented; no work.
- Renderer facade `prettyplay/engine/renderer/__init__.py` — not a `->` re-export block, but the Python cell facade obligation: all four contract names in `__all__` and importable from the package root.

### Usages Context

- `conventions` (`.goga/usages/conventions.md`) — Python rules: pydantic v2 kw_only + empty defaults, relative imports, Google docstrings, logging levels, test structure (`tests/engine/renderer/test_*.py`), validation commands. Referenced by every changed cell's global annotations; extracted into "Mandatory Rules" below.
- `jinja` (`.goga/usages/cooks/jinja.md`) — the Jinja environment contract (`autoescape=False`, `StrictUndefined`, `from_string`), the `{% var %}` extension mechanics, the memory/vars namespaces, the missing-value policy, `raw` blocks. Connected in the renderer CODEMANIFEST as `jinja`.
- `system_prompt` (`.goga/usages/prompts/step_generation.md`) — the generation system prompt: STEP is the prepared instruction; INPUTS/RESULTS inputs; the two code forms (`-> None` / `-> dict[str, str] | None`); the RESULTS rule (read from the page, never fabricate). Frozen mirrors: `generator.SYSTEM_PROMPT`, `steering.SYSTEM_PROMPT`.
- `compliance_prompt` (engine inline, in the engine CODEMANIFEST `Usages`) — the gate prompt with INPUTS/RESULTS inputs and the RESULTS exact-key contract rule. Frozen mirror: `compliance.COMPLIANCE_PROMPT`.
- `group_diagnosis` (`.goga/usages/prompts/group_diagnosis.md`) — PREVIOUS STEPS block of prepared instructions; `earliest_step` quotes a visible instruction. Frozen mirror: `groups/diagnosis.GROUP_DIAGNOSIS_PROMPT`.
- `taxonomy` (imported from `prettyplay/failures`) — the failure kinds and the base kind (`PrettyplayError`) of authoring errors.
- `group_framing`, `classification_prompt`, `cheat_sheet` — unchanged content; consumed exactly as before.

### Imported Usages

- `rendering` from `prettyplay/engine/renderer` — root (executor render point), groups (row re-render patterns). Path: `prettyplay/engine/renderer/.usages/rendering.md`.
- `memory` from `prettyplay/engine/renderer` — root, engine, groups, steering (publication points, snapshot semantics). Path: `prettyplay/engine/renderer/.usages/memory.md`.
- `validation` from `prettyplay/engine/renderer` — root, engine, groups, steering (result acceptance, violation channel). Path: `prettyplay/engine/renderer/.usages/validation.md`.
- All three files exist and are current (verified during design; `goga lint` validates the references).

### Local Usages

None to create. The renderer `.usages/` (`rendering.md`, `memory.md`, `validation.md`) and all updated cell `.usages/` files (`addressing.md`, `steps.md`, `lifecycle.md`, `generation.md`, `healing.md`, `recovery.md`, `settle.md`, `steering.md`, `providers.md`) are already written and current per the design's `.usages/` Update section.

### External Dependencies

- `jinja2>=3.1` — already added to `[project].dependencies` in `pyproject.toml`; must be installed in the recreated virtualenv.
- pytest, pytest-cov, pytest-mock, ruff — `[project.optional-dependencies].test`.
- No other new dependencies.

### Interaction Diagram (verbatim from the design)

```
author                facade (scenario.py / groups.py)
  │ t.step(text, vars={"expected": "D"})        # keyword-only vars, str-only validated at the call
  ▼
StepExecutor.execute(step_text, step_type, page, group, tries, delay, vars)
  │ 1. on_step_started(raw sentence) → quiet delay
  │ 2. render_step(text, step_type, memory, vars) ──► renderer.render_step
  │       │ StepMemory.snapshot() + vars → Jinja (StrictUndefined, autoescape=False,
  │       │ {% var %} extension) → PreparedStep(instruction, inputs, declarations)
  │       └ authoring errors → PrettyplayError (before any browser execution)
  │    StepIdentity ← normalize_step_text(ORIGINAL step_text)   [cache cell]
  │ 3. cache.load(identity)
  │    ├─ HIT:  url pair → settle(run_step_code, …) → result
  │    │        validate_step_result(prepared, result)
  │    │          ├─ valid → memory.publish(captures)      [acceptance = validated replay]
  │    │          └─ violation (AssertionError) → step 4 failed-check paths
  │    ├─ strict + MISS → IncurableStepError
  │    └─ MISS: generator.generate(identity, prepared, step_type, previous_steps,
  │              group_prompt, page, attempt_history, window, memory)
  │ 4. HIT failure → strict classify(prepared.instruction) | group recover | healer.heal(prepared, …, memory)
  │ 6. IncurableStepError (non-strict, interactive) → steering.steer(failure, identity,
  │              prepared, step_type, previous_steps, group_prompt, page, history, memory)
  │ 7. ScenarioStep(sentence, instruction, group_prompt) append; group trace
  │    GroupStepOutcome(sentence, instruction, step_type, tries, delay, vars, outcome, urls, identity)
  ▼
engines (generator / healer / recovery / steering)
  │ every request: provider.*(instruction=prepared.instruction, inputs=prepared.inputs,
  │                          declarations=prepared.declarations, …)
  │ acceptance: validate_step_result → check_step_compliance → memory.publish → cache.save
  ▼
LLM port (openai / anthropic — full parity)
  STEP TYPE line, STEP line, [INPUTS], [RESULTS], [GROUP PROMPT], PREVIOUS STEPS
  (instruction fields, group-marked), PAGE SNAPSHOT, PAGE URL, CHEAT SHEET,
  USER INSTRUCTIONS, HISTORY, RECOMMENDATION, USER GUIDANCE
```

### Data Flows (verbatim from the design)

1. **Ordinary template step, cache miss (non-strict)** — `render_step` → `PreparedStep` → `generate` loop: request (instruction + INPUTS/RESULTS) → `settle(run_step_code)` → result → `validate_step_result` → `check_step_compliance` → `memory.publish` → cache store → `ScenarioStep` append.
2. **Cached replay of a template step** — render → identity → HIT → `settle` → result → validate → publish (the gate never runs on replay). Violation → failed-check paths (strict: classify by step type; group: recovery; ordinary: heal).
3. **Group row recovery** — executor traces the failed step (with instruction + vars) and delegates `recover(group_prompt, traces, prepared, …, memory)`; recovery copies scenario/trace views, initializes the active failure, diagnoses (`classify_group_failure` with `previous_steps`), re-renders each row step (`render_step` from the trace sentence + recorded vars + current memory), regenerates, validates, gates, publishes per step, updates the local views, returns the failed step's healed code.
4. **Steering turn** — banner shows the prepared instruction; each guidance turn requests with `prepared`; `y` runs via `run_step_code` → result → `validate_step_result` (violation = red turn, record `failed check`) → gate → `memory.publish` + cache write-back.
5. **Capture flow across steps** — step A: `{% var name %}` declares; accepted execution returns `{"name": "Book"}`; validation passes; publication; step B: `{{ name }}` reads the snapshot value "Book"; the model and the failure texts see the prepared instruction with "Book" embedded.

### Entity Dependencies (verbatim from the design)

Initialization/composition order (leaves → root), unchanged wiring plus the renderer:

```
failures → config → driver → reporting → cache → polling → renderer → llm → engine → groups → steering → executor → scenario(PrettyPlay)
```

- The renderer depends only on `prettyplay/failures` (`PrettyplayError`, `taxonomy`) and `jinja2`.
- `engine` imports `PreparedStep`, `StepMemory`, `validate_step_result` from the renderer (not `render_step` — the engine never re-renders).
- `groups` additionally imports `render_step` (row re-render).
- `steering` imports `PreparedStep`, `StepMemory`, `validate_step_result`.
- The root imports all four renderer types; the executor constructs the per-test `StepMemory` and is the only render point outside recovery.
- No import cycles (verified by `goga schema`: renderer sits under engine, all four consumers point to it, nothing points back).

## Facts

- The CODEMANIFESTs of all eight cells already reflect the target contracts (apply-architecture landed them); `.goga/usages/cooks/jinja.md` and all changed prompt practices exist.
- `pyproject.toml` already contains `jinja2>=3.1`; ruff is configured there (target `py310`, line-length 120, rule set E/W/F/I/N/UP/B/SIM/PL/PLR/C4/DTZ/PT/ARG/RUF/PTH/C90; `[tool.ruff.format]`: double quotes, space indent, LF).
- The repo `.venv` is macOS-built (`pyvenv.cfg` → `/opt/homebrew/...python@3.14`) and broken on this Linux box — `.venv/bin/python` does not resolve. It is gitignored; it must be recreated on Linux before any command runs.
- No implementation of the feature exists yet: `normalize_step_text` is the old pipeline; `settle`/`run_step_code` return `None`; `ScenarioStep` has no `instruction`; the facade methods have no `vars`; `prettyplay/engine/renderer/` contains only `CODEMANIFEST` + `.usages/` (no Python files); `GroupStepOutcome` lacks `instruction`/`vars`.
- `PageFacade.run(action) -> _T` already returns the callable's outcome (plain data) — the driver primitive carries results back; `run_step_code` merely drops it today.
- Hook payloads (`on_step_started`/`on_step_failed`/`on_step_finished`) carry the raw sentence — the reporting surface is unchanged (user decision, option A); the prepared instruction is visible inside the rendered failure text.
- No import cycles: renderer sits under engine; all four consumers (engine, groups, steering, root) point to it; nothing points back (`goga schema` verified during design).
- Tests exist for every touched module under `tests/` mirroring the source tree; the fakes pattern (fake `PageFacade` with `run(fn)` returning `fn(fake_page)`, fake `LLMProvider`, `tmp_path` cache roots) is established.

## Gap Analysis

- Missing cell implementation: `prettyplay/engine/renderer/` has no `__init__.py`, `render.py`, `memory.py`, `validation.py`.
- Missing test package: `tests/engine/renderer/` does not exist.
- `normalize_step_text` (cache/text.py): template split missing — template sentences go through casefold today.
- `settle` (polling/settle.py): returns `None`; result carriage missing in both modes (the count-mode helper has a separate return path).
- `run_step_code` (engine/execution.py): annotated `-> None`; drops the step function's return.
- LLM port: `generate_step_code`/`check_instruction_compliance` lack `instruction`/`inputs`/`declarations`; `classify_group_failure` lacks `previous_steps`; `ScenarioStep` lacks `instruction`; builders render no INPUTS/RESULTS/PREVIOUS STEPS blocks.
- Engine: `generate`/`regenerate`/`heal`/`check_step_compliance` signatures and acceptance chains lack `PreparedStep`/`StepMemory`/validation/publication; frozen prompt mirrors predate the practice updates.
- Groups: `GroupStepOutcome` lacks `instruction`/`vars`; `classify_group_failure` (engine cell wrapper) lacks `previous_steps`; `recover` does not re-render rows or keep local views.
- Steering: `steer` lacks `prepared`/`memory`; turns are not validated; nothing publishes.
- Root: no `vars` on `step`/`expect` (facade and group); no `_validate_vars`; executor is not the render point, owns no memory, does not validate/publish replays; `ScenarioStep`/trace records carry one text only.
- Reusable: all existing unit tests (update signatures first), the fakes pattern, `format_step_error`, `_validate_tries`/`_validate_delay`, the taxonomy, the settle window mechanics.
- Environment: the broken macOS `.venv` blocks every validation command — recreate first.

---

## Mandatory Rules

Extracted from the project convention (`.goga/usages/conventions.md`, the single source of the project's Python rules) and the stage requirements. These rules are **mandatory for every task**; they override personal preference and default to the strictest reading. Where a CODEMANIFEST annotation is stricter, the contract wins; where it is silent, these rules apply.

### M1. Coding Style (from the convention)

1. Python 3.10+ only. `pyproject.toml` is the single configuration source — no separate config files.
2. All code execution happens inside the project virtualenv — create it if missing (Task 1 recreates it: the committed one is macOS-built). Never run pytest/ruff/python outside the venv.
3. Imports: **relative imports for all intra-package references** (`from .models import User`, `from ..utils import helper`); absolute imports only for stdlib and third-party (`import logging`, `from pydantic import BaseModel`). Absolute imports within the package are forbidden.
4. Data models: pydantic v2, `model_config = ConfigDict(kw_only=True, ...)` (plus `frozen=True` where the contract says immutable); empty defaults for all fields (empty string, zero, empty list/dict); `None` only for fields representing explicit absence. `PreparedStep` follows this; `StepMemory` is a plain stateful class, not pydantic (contract).
5. Logging: the stdlib `logging` library, `logger = logging.getLogger(__name__)`; lowercase concise messages, stable event names, structured contextual metadata (`extra={...}`); levels per the convention (DEBUG diagnostics, INFO lifecycle, WARNING recoverable/skips, ERROR operation cannot complete, CRITICAL never used here); no secrets, tokens or personal data in any log output — step sentences (raw or rendered) included.
6. Formatting: inside function and method bodies, logical blocks are separated by **one blank line** — initialization from conditionals/loops, data preparation from processing, processing from return.
7. Docstrings: all public functions, methods and classes **must** have Google-style docstrings — first line capitalized and ending with a period; `Args` when parameters exist, `Returns` when a value returns, `Raises` for exceptions beyond built-ins; one point per comment, professional and concise.
8. Dependencies: every third-party library in `pyproject.toml` with a minimum version; test libraries under `[project.optional-dependencies].test`. (`jinja2>=3.1` is already declared — do not re-declare.)
9. Signature rules (Python cell): mandatory type hints; allowed primitives `str, int, float, bool, list[T], dict[str, T], T | None`; no `*args`/`**kwargs`, no untyped generics; PascalCase classes, snake_case functions/methods/properties.

### M2. Test Writing (from the convention)

1. Tools: pytest (runner), ruff (lints and formats test code too), pytest-cov (coverage). All tests run in the venv.
2. Structure mirrors the source directly: `prettyplay/engine/renderer/memory.py` → `tests/engine/renderer/test_memory.py`; no intermediate root package directory; root-package module tests sit directly in `tests/`.
3. Every test directory contains `__init__.py`. Local fixtures live in `tests/<package>/conftest.py`, shared fixtures in `tests/conftest.py`. Integration tests covering multiple packages sit directly in `tests/` (e.g. the existing `tests/test_integration.py`).
4. Naming: files `test_<module>.py`; functions `test_<what>_<scenario>` (e.g. `test_complexity_with_empty_input`); grouping `class Test<Component>:`.
5. Coverage: unit tests for every public function/method/class with the main scenario and typical data; edge tests for empty inputs (`None`, `""`, `[]`, `{}`), boundary values, invalid types, expected exceptions via `pytest.raises`; integration tests only for interaction between modules/packages.
6. Boundaries: for thresholds, ranges and state transitions use `@pytest.mark.parametrize` with a table of values including each boundary.
7. Mocks: pure logic — no mocks; file I/O — the `tmp_path` fixture exclusively; subprocesses — `mock.patch` the call; external dependencies — `mock.patch` at the import point. Mock only at external boundaries; business logic tests stay mock-free (the renderer tests need no mocks at all).
8. Self-documenting test names, minimal comments. Skip integration tests with unavailable external dependencies via `pytest.mark.skipif`.
9. Contract/logic/integration classification (project conventions file): contract tests (facade, API shape, signatures) are written FIRST and fail initially; logic tests (positive/negative/edge behavior) after implementation; integration tests never replace them.

### M3. Linter and Formatter Enforcement (all stages and local commits)

1. ruff is the project's linter **and** formatter; its configuration lives in `pyproject.toml` (target `py310`, line-length 120, rule set E/W/F/I/N/UP/B/SIM/PL/PLR/C4/DTZ/PT/ARG/RUF/PTH/C90, mccabe max-complexity 10; format: double quotes, space indent, LF endings). Do not add configuration anywhere else.
2. Every task's final step runs `ruff check prettyplay/` and `ruff check tests/` — all findings fixed before the task's checkboxes are marked complete. Fix the code, never the per-file ignore list (the existing per-file-ignores encode contract facts — e.g. the frozen prompt constants must not rewrap).
3. Formatting gate before completion: `ruff format --check prettyplay/ tests/` is clean; apply `ruff format` when needed — except the frozen prompt constants, which are verbatim contract texts.
4. **Local commit gate**: no local commit is made unless, in the venv, both `ruff check prettyplay/ tests/`, `ruff format --check prettyplay/ tests/` and `pytest tests/ -x` pass. A failing lint/format/test blocks the commit — fix the code, never skip the gate.
5. The lint step applies at every development stage: infrastructure tasks, coding tasks, integration test tasks alike.

### M4. REPL Cycle Rules (continuous interactive evaluation, hot reloading, migration to source)

1. **REPL after contract tests, before logic tests**: first write the failing contract tests. Then probe the current behavior interactively in the project venv (`.venv/bin/python - <<'PY' … PY` heredocs, or `python -c`). A missing new API or the old behavior is an expected initial observation; after implementation, verify importability, return shapes, and that error texts name the offending name/value before writing logic tests.
2. **Continuous evaluation / hot reloading**: after every code edit, immediately re-run the REPL probe (fresh process, or `importlib.reload` of the touched module) and observe the changed behavior — the REPL is the fast feedback loop; full test-suite runs are reserved for the task's debugging step, not for exploration.
3. **Migration to source**: once a snippet is verified in the REPL, migrate it into the target source file — apply docstrings, type hints and the M1 style at migration time. The source files are the single source of truth: nothing lives only in a REPL session, and no scratch files are committed.
4. **REPL probes are disposable**: run them in the venv, paste outcomes into the task's working notes if useful, then discard; the durable verification artifacts are the pytest files.
5. Each coding task below carries an explicit **REPL checkpoint** checkbox between contract tests and code. Start the probe there, keep it active through implementation, and mark it complete only after the post-edit probe confirms the target behavior, before writing logic tests.

---

## Tasks

> **Package ordering rule**: coding tasks for each package are completed before starting the next. Within each coding task, contract tests are written first (TDD workflow). Dependency order: `cache` → `polling` → `renderer` → `llm` → `engine` → `groups` → `steering` → root facade/executor → integration.

> **Global context for every task**: `CODEMANIFEST` files are read-only contract definitions — never modify them; if implementation does not match the contract, fix the implementation. All commands run in the project virtualenv (Task 1). The Mandatory Rules M1–M4 apply to every task.

### Task 1: Recreate the Linux virtualenv and record the baseline (infrastructure)

The repo's `.venv` was built on macOS (`pyvenv.cfg` points at `/opt/homebrew/.../python@3.14`) and its `bin/python` does not resolve on this Linux box — it is gitignored and safe to replace. Every subsequent task runs pytest/ruff through this venv; the project convention requires all execution inside it. After recreation, run the existing suite to record the pre-change baseline and confirm `jinja2` is importable (it is declared in `[project].dependencies`). The prompt practice files already contain the new contract text, while the frozen constants are updated in Tasks 11, 12, 15 and 17, so prompt-mirror tests are expected to fail until those tasks complete; record the exact baseline failures and investigate any unrelated failure before proceeding. API migrations across dependent cells also cause temporary failures until Task 19 completes.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them.**

- [ ] Recreate the venv: `rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -e ".[test]"` (installs the package plus pytest/pytest-cov/pytest-mock/ruff; pulls `jinja2>=3.1`)
- [ ] REPL probe the environment (M4): `.venv/bin/python -c "import jinja2, pydantic, prettyplay; print(jinja2.__version__)"` — must print a 3.1+ version
- [ ] Baseline: `.venv/bin/pytest tests/` — record passing and failing test counts and the exact prompt-mirror failures; investigate any unrelated failure before proceeding. Require the full suite to pass after Task 19 completes all dependent API migrations; Task 20 confirms the integrated result.
- [ ] Baseline: `.venv/bin/ruff check prettyplay/` and `.venv/bin/ruff check tests/` — clean
- [ ] Lint: `.venv/bin/ruff format --check prettyplay/ tests/` — fix nothing that predates this topic unless the check fails on files this topic will not touch; report any pre-existing failure instead of reformatting the world
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 2: Renderer package skeleton and test scaffolding (infrastructure)

Create the Python package for the new cell `prettyplay/engine/renderer/` (today it holds only `CODEMANIFEST` and `.usages/`): `__init__.py` with the package docstring and an `__all__` that grows as the entity tasks land, plus the mirrored test package `tests/engine/renderer/` with its `__init__.py` (convention M2.3). The four facade names (`PreparedStep`, `render_step`, `StepMemory`, `validate_step_result`) become importable from `prettyplay.engine.renderer` as their modules are created in Tasks 5–7; each entity task appends its own names to `__all__`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them.**

- [ ] Create `prettyplay/engine/renderer/__init__.py` — package docstring (the step-sentence preparation cell: rendering, memory, result validation), `__all__: list[str] = []` for now; relative imports only when re-exports land
- [ ] Create `tests/engine/renderer/__init__.py` (empty, per convention)
- [ ] Verify package importability: `.venv/bin/python -c "import prettyplay.engine.renderer"` — no error
- [ ] Lint: `.venv/bin/ruff check prettyplay/engine/renderer/ tests/engine/renderer/` — clean
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 3: Template-aware `normalize_step_text` in the cache cell

`prettyplay/cache/CODEMANIFEST` declares the template/ordinary split for `normalize_step_text` (`location: text.py`): a sentence containing any of the markers `{{`, `{%`, `{#` addresses verbatim (NFC + trim only — Jinja names are case-sensitive, expression whitespace is significant); an ordinary sentence keeps today's pipeline (NFC, trim, collapse internal whitespace, casefold). This is the addressing key of `StepIdentity` — runtime values never enter it. Pure function, deterministic on `text` alone. The `{#` marker is this session's defect-3 fix: a comment-only sentence must not break the "instruction equals sentence for a non-template step" invariant.

**Usages relevant to this task:**
- `conventions` (M1/M2 rules): pure function, Google docstring, `tests/cache/test_text.py` mirrors the location.
- `addressing` (`prettyplay/cache/.usages/addressing.md`, already updated): the identity-triple row and the template-sentences section describe the target behavior.

- [ ] **Contract tests**: in `tests/cache/test_text.py` — template sentences keep case and internal whitespace verbatim (`{{ name }}` ≠ `{{ Name }}` addresses); the three markers `{{`, `{%`, `{#` each trigger template mode; ordinary sentences stay byte-identical to the current pipeline (extend the existing tests, do not replace them) (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, evaluate `normalize_step_text("  Read {{ name }} into {% var out %}  ")` and `normalize_step_text("{# note #} Click Sign in")` interactively — confirm verbatim NFC+trim output before writing the logic tests
- [ ] **Code**: in `prettyplay/cache/text.py`, implement the split per the contract Algorithm — detect `any(marker in text for marker in ("{{", "{%", "{#"))`; template branch: `unicodedata.normalize("NFC", text).strip()` returned as-is; ordinary branch: the existing NFC → trim → collapse → casefold pipeline unchanged; update the docstring to the template-aware contract
- [ ] **Interface verification**: `.venv/bin/pytest tests/cache/ -v` — all pass
- [ ] **Logic tests**: transfer verbatim from the design:
  - `test_normalize_template_sentence_addresses_verbatim` — **Input**: `normalize_step_text("  Read {{ name }} into {% var out %}  ")`; **Trace**: markers detected (`{{`, `{%`) → NFC + trim only; **Assertions**: result == `"Read {{ name }} into {% var out %}"` (case and internal whitespace preserved); `normalize_step_text("read {{ Name }} …") != normalize_step_text("read {{ name }} …")`; **Sufficiency**: case-sensitive template addressing; prevents the casefold pipeline from collapsing distinct templates into one address.
  - `test_normalize_comment_marker_sentence_is_template` — **Input**: `normalize_step_text("{# note #} Click Sign in")`; **Assertions**: verbatim NFC+trim form (case preserved, no casefold); **Sufficiency**: locks the marker-set fix (defect 3).
  - Existing ordinary-pipeline tests (Russian casefold pairs, whitespace collapse) stay green unchanged.
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: signature `normalize_step_text(text: str) -> str` unchanged; pure; no new imports beyond stdlib
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/cache/ tests/cache/` and `.venv/bin/ruff format --check prettyplay/cache/ tests/cache/` — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 4: Result carriage through `settle` in the polling cell

`prettyplay/engine/polling/CODEMANIFEST` changes `settle` (`location: settle.py`) to carry the successful execution's result through untouched: the execute callable now returns `dict[str, str] | None` and `settle` returns it as-is — including the result of a successful count-mode retry. The loop never inspects, validates or alters the result (validation belongs to the calling cycle). Pollable filter, settle_retry INFO records, per-call zero counter in count mode — all unchanged. The count-mode helper `_settle_by_count` has its own return path: an implementation that preserves the first-execution result but discards the successful retry's result is the regression this task must catch.

**Usages relevant to this task:**
- `conventions` (M1/M2): type hints on the callable and return; `tests/engine/polling/test_settle.py`.
- `settle` (`prettyplay/engine/polling/.usages/settle.md`, already updated): result-carriage paragraph.

- [ ] **Contract tests**: in `tests/engine/polling/test_settle.py` — the `execute` callable signature accepts and returns `dict[str, str] | None`; `settle` returns the successful execution's result object (same identity/value) in both modes (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, evaluate `settle(lambda code, page: {"name": "Dune"}, "code", object(), SettleWindow(None, 0.0))` interactively — confirm the dictionary comes back before writing the logic tests
- [ ] **Code**: in `prettyplay/engine/polling/settle.py`, thread the result: both the time-bounded and count-bounded paths return the successful execution's return value; update the `execute` type to `Callable[[str, PageFacade], dict[str, str] | None]` and the return annotation; docstrings updated to the carriage contract
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/polling/ -v` — all pass
- [ ] **Logic tests**: transfer verbatim from the design:
  - `test_settle_carries_successful_result_through` — **Setup**: `window = SettleWindow(None, 0.0)` (polling off); `execute = lambda code, page: {"name": "Dune"}`; **Input**: `settle(execute, "code", page, window)`; **Trace**: window.start → single execution succeeds → return its result; **Assertions**: `result == {"name": "Dune"}`; **Sufficiency**: result carriage without polling; the executor's replay publication depends on it.
  - `test_settle_carries_result_of_successful_count_retry` — **Setup**: `window = SettleWindow(None, 0.0, 2)`; fake `page = object()`; `caplog` captures INFO from logger `prettyplay`; a fake `execute` increments `calls`, raises `AssertionError("page not ready")` on call 1, and returns `{"name": "Dune"}` on call 2 (`AssertionError` is pollable under the existing `is_pollable_failure` map); **Input**: `result = settle(execute, "code", page, window)`; **Trace**: count branch → pollable failure with `executed=1 < tries=2` → one `settle_retry` log and zero-delay pause → second call returns the dictionary → `_settle_by_count` and `settle` pass that same dictionary to the caller; **Assertions**: `assert result == {"name": "Dune"}`; `assert calls == 2`; `assert [r.getMessage() for r in caplog.records if r.getMessage() == "settle_retry"] == ["settle_retry"]`; **Sufficiency**: catches an implementation that discards the successful retry's result.
  - Existing failure-propagation and non-pollable tests stay green.
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: `window` mechanics untouched (start idempotence, has_remaining, count-bounded loop); no new log records on the happy path
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/polling/ tests/engine/polling/` and `ruff format --check` on the same paths — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 5: `StepMemory` in the renderer cell

`prettyplay/engine/renderer/CODEMANIFEST` declares `StepMemory()` (`location: memory.py`): the per-test-execution memory of captured observations. Constructs empty; `snapshot() -> dict[str, str]` returns a stable copy (later publishes never mutate a taken snapshot); `publish(captures: dict[str, str])` replaces the value of every present name, keeps absent names, never removes names — one call per accepted execution; a failed or rejected attempt never calls publish. Survives navigation; never crosses tests. **A plain mutable class — not pydantic** (contract). Register `StepMemory` in the facade `__all__` (Task 2 created the skeleton).

**Usages relevant to this task:**
- `conventions` (M1/M2): plain class with type hints and Google docstrings; `tests/engine/renderer/test_memory.py`.
- `memory` (`prettyplay/engine/renderer/.usages/memory.md`): lifecycle, publisher list — the consumer documentation this entity implements.

- [ ] **Contract tests**: in `tests/engine/renderer/test_memory.py` — `from prettyplay.engine.renderer import StepMemory` (facade accessibility); `snapshot()` returns `dict[str, str]`; `publish(captures: dict[str, str])` accepts a string mapping (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, evaluate interactively — construct, publish `{"name": "Book"}`, take a snapshot, publish `{"name": "Tale", "kind": "novel"}`, verify the earlier snapshot object is unchanged and the new one reflects replace-and-keep
- [ ] **Code**: create `prettyplay/engine/renderer/memory.py` per the contract Algorithm — `construct: values ← {}`; `snapshot(): RETURN dict(values)`; `publish(captures): FOR name, value IN captures: values[name] ← value`; append `"StepMemory"` to `__all__` in the renderer `__init__.py` (relative import)
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/renderer/test_memory.py -v` — all pass
- [ ] **Logic tests**: transfer verbatim from the design:
  - `test_memory_publish_replaces_present_and_keeps_absent` — **Setup**: `memory.publish({"name": "Book"})`; **Input**: `memory.publish({"name": "Tale", "kind": "novel"})`; then `memory.snapshot()`; **Trace**: publish replaces `name`, adds `kind` → snapshot `{"name": "Tale", "kind": "novel"}`; **Assertions**: earlier snapshot objects unchanged (`first == {"name": "Book"}`); new snapshot reflects the replace-and-keep semantics; **Sufficiency**: recapture-replaces + absent-keeps + snapshot stability — the memory contract in one test.
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: facade import works; no pydantic; no locks, no module-global state
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/renderer/ tests/engine/renderer/` and `ruff format --check` on the same — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 6: `PreparedStep` and `render_step` in the renderer cell

`prettyplay/engine/renderer/CODEMANIFEST` declares two entities in `location: render.py`:

`PreparedStep(instruction: str, inputs: dict[str, str], declarations: list[str])` — pydantic v2, `kw_only=True`, `frozen=True`, empty defaults; `has_declarations -> bool` is a plain property; the immutable render product.

`render_step(text, step_type, memory, vars) -> prepared: PreparedStep` — the render point. Algorithm (from the CODEMANIFEST and the design, verbatim):
1. Take the snapshot: the `StepMemory` snapshot plus `vars` (None — empty); standard Jinja scope applies, ordinary set stays local to the template
2. Compile through the Jinja environment of `jinja`: StrictUndefined, autoescape=False, the `{% var %}` extension — a **fresh Environment per call** (concurrent tests stay isolated)
3. Render: a reached capture tag records its name and renders to empty text; a duplicate name within one render fails as an authoring error; the reserved name `vars` and non-Jinja-identifier capture names fail as authoring errors
4. An unavailable name fails ordinary interpolation with the unavailable name in the message; author-written default and is defined keep standard behavior
5. `step_type` assertion with non-empty declarations — the authoring error: capture declarations are invalid in expect; an inactive branch declares nothing
6. Build and return `PreparedStep` — instruction (the rendered text), inputs (`vars`), declarations

Errors: all authoring errors raise the loud actionable `PrettyplayError` (imported from `prettyplay/failures`) naming the problem and the offending name — **before any browser execution**. Compile-time `TemplateSyntaxError` (including its `TemplateAssertionError` subclass) is translated into `PrettyplayError` retaining the syntax message and `lineno` (per the Jinja API). Constraints: no browser, LLM or page access; no mutation of `memory` — the snapshot is read-only; substituted data is never rendered again.

**Usages relevant to this task:**
- `jinja` (`.goga/usages/cooks/jinja.md`) — the authoritative environment contract: `Environment(autoescape=False, undefined=StrictUndefined, extensions=[VarExtension])`, `from_string` (no loader), `template.render(memory, vars=inputs)`; the extension subclasses `Extension`, declares the tag, parses the name token, emits an output node that renders to nothing and records the reached name; names are case-sensitive Jinja identifiers; `vars` reserved; duplicate within one render is an authoring error; only reached tags declare; captures invalid in expect; `raw` blocks emit literal text; `| default(...)`/`is defined` behave as authored.
- `taxonomy` (from Imports, `prettyplay/failures/.usages/taxonomy.md`) — the base kind `PrettyplayError` of the authoring errors, message-first constructor.
- `conventions` (M1/M2): pydantic v2 kw_only frozen for `PreparedStep`; `tests/engine/renderer/test_render.py`.
- `rendering` (`prettyplay/engine/renderer/.usages/rendering.md`) — the consumer-facing render example this implements.

- [ ] **Contract tests**: in `tests/engine/renderer/test_render.py` — facade import of `PreparedStep` and `render_step`; `render_step(text: str, step_type: str, memory: StepMemory, vars: dict[str, str] | None) -> PreparedStep` signature; `PreparedStep` fields with empty defaults and `has_declarations` property; keyword-only construction (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, evaluate interactively before writing the logic tests — a memory substitution, a `{% var %}` capture (declaration recorded, renders empty), a missing name (`PrettyplayError` naming it), a duplicate capture, and `{% raw %}{{ x }}{% endraw %}` staying literal; re-run the probe after every implementation edit (hot reload)
- [ ] **Code**: create `prettyplay/engine/renderer/render.py` — the `{% var %}` extension class (`jinja2.ext.Extension` subclass; tag `var`; parse-time validation: the token after `var` must be a single Jinja identifier, else `PrettyplayError` naming the tag; the output node records the reached name into the per-render recorder list and renders to empty text; the reserved name `vars` and a repeat of an already-recorded name raise `PrettyplayError` at record time); `PreparedStep` pydantic model (`kw_only=True, frozen=True`, empty defaults, `has_declarations` property); `render_step` implementing the six algorithm steps, catching `TemplateSyntaxError` (with `TemplateAssertionError`) and `UndefinedError` into `PrettyplayError` (original diagnostic and line number retained; the unavailable name in the message); a fresh `Environment` per call; the `jinja2` import lives in this file; append `"PreparedStep"` and `"render_step"` to the facade `__all__`
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/renderer/test_render.py -v` — all pass
- [ ] **Logic tests**: transfer verbatim from the design:
  - `test_render_substitutes_memory_value_into_instruction` — **Setup**: `memory = StepMemory()`; `memory.publish({"name": "Book"})`; **Input**: `render_step("Open the item named {{ name }}", "action", memory, None)`; **Trace**: snapshot `{"name": "Book"}` → `template.render({"name": "Book"}, vars={})` returns `"Open the item named Book"` → no assertion gate → `PreparedStep(instruction="Open the item named Book", inputs={}, declarations=[])`; **Assertions**: `prepared.instruction == "Open the item named Book"`; `prepared.inputs == {}`; `prepared.declarations == []`; `prepared.has_declarations is False`; **Sufficiency**: the core rendering contract — actual values embedded, plain text; prevents regressions where requests would carry raw Jinja.
  - `test_render_reads_vars_namespace_separately_from_memory` — **Setup**: `memory.publish({"name": "Book"})`; **Input**: `render_step("The page contains {{ name }} and {{ vars.expected }}", "assertion", memory, {"expected": "Details"})`; **Assertions**: `prepared.instruction == "The page contains Book and Details"`; `prepared.inputs == {"expected": "Details"}`; **Sufficiency**: the two-namespace contract (`{{ name }}` memory vs `{{ vars.x }}` inputs); prevents one namespace overwriting the other.
  - `test_render_capture_tag_declares_result_and_renders_empty` — **Setup**: empty memory; **Input**: `render_step("Read the first item name into {% var name %}", "action", memory, None)`; **Assertions**: `prepared.declarations == ["name"]`; `prepared.has_declarations is True`; `prepared.instruction == "Read the first item name into "`; **Sufficiency**: the capture mechanism — a declaration is a slot, not a value.
  - `test_render_inactive_branch_declares_nothing` — **Input**: `render_step("{% if false %}{% var x %}{% endif %}click Save", "action", memory, None)`; **Assertions**: `prepared.declarations == []`; `prepared.instruction == "click Save"`; **Sufficiency**: only reached tags declare.
  - `test_render_duplicate_capture_name_raises_authoring_error` — **Input**: `render_step("{% var x %}{% var x %} go", "action", memory, None)`; **Trace**: second reached tag finds `x` recorded → raise; **Assertions**: `pytest.raises(PrettyplayError)` with a message naming `x` and the duplicate problem; raised before any browser interaction (no page object involved at all); **Sufficiency**: one slot per name per render.
  - `test_render_malformed_standard_jinja_is_an_authoring_error` — **Setup**: empty `StepMemory()`; no page, provider or cache object exists; **Input**: `render_step("{% if x %}", "action", memory, None)`; **Trace**: `snapshot()` returns `{}`; fresh Jinja environment constructed; `from_string` parses the incomplete `if` and raises `TemplateSyntaxError` with line 1; `render_step` catches it and raises `PrettyplayError` retaining the syntax message and line; no render or browser execution occurs; **Assertions**: `with pytest.raises(PrettyplayError) as exc:`; `assert "if" in str(exc.value)`; `assert "line 1" in str(exc.value)`; **Sufficiency**: standard Jinja syntax errors need the same loud authoring-error boundary as malformed `{% var %}` tags; a raw library exception must not escape through the public step call.
  - `test_render_reserved_and_invalid_capture_names_raise` — **Input**: `render_step("{% var vars %}", "action", …)` and `render_step("{% var 1x %}", "action", …)`; **Assertions**: both raise `PrettyplayError` naming the offending tag; the reserved `vars` namespace stays unreachable as a capture; **Sufficiency**: namespace reservation and identifier-form enforcement.
  - `test_render_unavailable_name_raises_naming_the_name` — **Setup**: empty memory; **Input**: `render_step("Open {{ missing }}", "action", memory, None)`; **Trace**: `StrictUndefined` raises `UndefinedError('missing' …)` → caught → `PrettyplayError` naming `missing`; **Assertions**: `pytest.raises(PrettyplayError)`, `"missing" in str(exc)`; **Sufficiency**: the loud missing-value policy — no silent empty strings.
  - `test_render_capture_in_expectation_raises` — **Input**: `render_step("The page shows {% var x %}", "assertion", memory, None)`; **Assertions**: `PrettyplayError`; declarations gate applies only to assertions — the same sentence as `action` succeeds; **Sufficiency**: captures are actions-only; expectations observe.
  - `test_render_same_step_cannot_read_its_own_capture` — **Input**: `render_step("Read {{ name }} and {% var name %}", "action", StepMemory(), None)` with empty memory; **Assertions**: `PrettyplayError` naming `name` (the snapshot lacks it); **Sufficiency**: snapshot isolation — new captures publish only after acceptance.
  - `test_render_captured_value_containing_jinja_stays_literal` — **Setup**: `memory.publish({"payload": "{{ boom }}"})`; **Input**: `render_step("Type {{ payload }}", "action", memory, None)`; **Assertions**: `prepared.instruction == "Type {{ boom }}"` — data is never re-rendered; no injection through captured content; **Sufficiency**: the substituted-data-is-never-a-template rule.
  - `test_render_author_written_default_and_is_defined_keep_behavior` — **Input**: `render_step("{{ missing | default('n/a') }}", …)` and `render_step("{% if missing is defined %}x{% else %}y{% endif %}", …)`; **Assertions**: instruction `"n/a"`; instruction `"y"` — authored absence handling is honored, engines never add fallbacks; **Sufficiency**: StrictUndefined does not break authored Jinja idiom.
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: `render_step` touches no browser/LLM/page; `memory` never mutated by rendering; `vars=None` with `{{ vars.x }}` in the template raises the unavailable-name error naming `vars.x`; a memory name equal to an input name leaves both accessible (`{{ name }}` vs `{{ vars.name }}`); a capture tag inside a loop body reached twice → duplicate-name authoring error
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/renderer/ tests/engine/renderer/` and `ruff format --check` on the same — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 7: `validate_step_result` in the renderer cell

`prettyplay/engine/renderer/CODEMANIFEST` declares `validate_step_result(prepared: PreparedStep, result: object) -> captures: dict[str, str]` (`location: validation.py`): the deterministic gate between an execution's return and publication. Algorithm (verbatim from the design):
1. IF `prepared.declarations` empty: IF `result is None` → RETURN `{}`; ELSE → violation "unexpected result without declarations"
2. IF `result is None` → violation "missing result"
3. IF `not isinstance(result, dict)` → violation "result must be a dictionary"
4. IF `set(result) != set(prepared.declarations)` → violation naming the missing/unexpected names
5. FOR name, value IN result.items(): IF `not isinstance(value, str)` → violation naming name; IF `value.strip() == ""` → violation naming name (blank observation)
6. RETURN `dict(result)`

Violations raise `AssertionError` with the deterministic text (the failed-check channel; formatted by `format_step_error` downstream — never re-composed here). The non-dict check fires **before** key inspection (`set(["name"])` would match the declarations even though a list has no `.items()` — generated Python can return any type at runtime despite its annotation). Pure: no I/O, no LLM, deterministic on the inputs. Never fabricates or repairs. Register `validate_step_result` in the facade `__all__`.

**Usages relevant to this task:**
- `conventions` (M1/M2): pure function; `tests/engine/renderer/test_validation.py`.
- `validation` (`prettyplay/engine/renderer/.usages/validation.md`): the consumer-facing validation contract this implements.

- [ ] **Contract tests**: in `tests/engine/renderer/test_validation.py` — facade import; signature `validate_step_result(prepared: PreparedStep, result: object) -> dict[str, str]` (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, evaluate interactively — the exact-key accept, the blank rejection, the list return raising `AssertionError("result must be a dictionary")`, and `None` for a declaration-free prepared returning `{}`
- [ ] **Code**: create `prettyplay/engine/renderer/validation.py` implementing the six algorithm steps with deterministic violation texts; append `"validate_step_result"` to the facade `__all__`
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/renderer/test_validation.py -v` — all pass
- [ ] **Logic tests**: transfer verbatim from the design:
  - `test_validate_accepts_exact_declared_dictionary` — **Setup**: `prepared = PreparedStep(instruction="…", inputs={}, declarations=["name", "kind"])`; **Input**: `validate_step_result(prepared, {"kind": "book", "name": "Dune"})`; **Trace**: declarations non-empty; result not None; `set(result) == {"name", "kind"} == set(declarations)`; both values str, non-blank; **Assertions**: `captures == {"name": "Dune", "kind": "book"}` (order irrelevant, values verbatim); **Sufficiency**: the exact-key contract — order-free key equality, values untrimmed.
  - `test_validate_declaration_free_step_accepts_none` — **Setup**: `prepared = PreparedStep(instruction="click Sign in", inputs={}, declarations=[])`; **Input**: `validate_step_result(prepared, None)` → returns `{}`; **Assertions**: `captures == {}` — legacy cached code replays clean; **Sufficiency**: backward compatibility of the replay path for all pre-template cached steps.
  - `test_validate_missing_and_unexpected_names_violate` — **Input**: `prepared(declarations=["a", "b"])` with `{"a": "x"}` (missing `b`) and with `{"a": "x", "b": "y", "c": "z"}` (unexpected `c`); also `None` (missing result) and a non-None dict for a declaration-free prepared; **Assertions**: each raises `AssertionError`; the message names the offending name(s); **Sufficiency**: the exact-key contract's both sides plus the None matrix.
  - `test_validate_blank_value_violates` — **Input**: `prepared(declarations=["a"])` with `{"a": ""}` and `{"a": "   "}`; **Assertions**: `AssertionError` naming `a`; `{"a": "  x  "}` passes with the value verbatim; **Sufficiency**: blank = unobserved; whitespace-only is blank; non-blank values keep their form.
  - `test_validate_wrong_result_type_is_a_failed_check` — **Setup**: `prepared = PreparedStep(instruction="Read the name", inputs={}, declarations=["name"])`; no page, provider or cache is needed for this pure validator test; **Input**: call `validate_step_result(prepared, ["name"])` and `validate_step_result(prepared, 42)` separately; **Trace**: each result is non-None, then fails `isinstance(result, dict)` before key inspection; each call raises `AssertionError("result must be a dictionary")`; the list is especially important: `set(["name"])` would match the declarations even though it has no `.items()`; **Assertions**: for both inputs, `pytest.raises(AssertionError, match="result must be a dictionary")`; no captures are returned; **Sufficiency**: keeps wrong types in the deterministic failed-check channel instead of leaking `TypeError` or `AttributeError`.
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: renderer facade complete — `.venv/bin/python -c "from prettyplay.engine.renderer import PreparedStep, StepMemory, render_step, validate_step_result"`; all four in `__all__`
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/renderer/ tests/engine/renderer/` and `ruff format --check` on the same — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 8: `ScenarioStep` gains `instruction` in the llm cell

`prettyplay/llm/CODEMANIFEST` declares `ScenarioStep(sentence: str, instruction: str, group_prompt: str)` (`location: models.py`): the new `instruction` field is the prepared instruction recorded at the step's execution — equals `sentence` for a non-template step; the only field requests render; `sentence` stays the addressing and diagnostics artifact, never rendered into requests. pydantic v2, kw_only, frozen, empty defaults (M1.4). A record appended to the scenario context is never rewritten.

**Usages relevant to this task:**
- `conventions` (M1/M2): pydantic model rules; `tests/llm/test_models.py` (extend the existing tests).

- [ ] **Contract tests**: `ScenarioStep` has `instruction` with empty-string default; keyword-only construction with `instruction=`; frozen (assignment raises); facade import from `prettyplay.llm` (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, construct `ScenarioStep(sentence="Read {{ kind }}", instruction="Read novel")` and `ScenarioStep(sentence="click Save")` interactively — the latter defaults `instruction=""`
- [ ] **Code**: in `prettyplay/llm/models.py`, add `instruction: str = ""` to `ScenarioStep` with the docstring updated to the dual-text semantics; existing constructions in tests/code updated to pass `instruction=` where they represent executed steps
- [ ] **Interface verification**: `.venv/bin/pytest tests/llm/ -v` — all pass
- [ ] **Logic tests**: field default, kw_only, frozen, group_prompt unchanged; a non-template step's record carries `instruction == ""` until the executor fills it (the equality with `sentence` is the caller's responsibility)
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: no other model in `models.py` changed
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/llm/ tests/llm/` and `ruff format --check` on the same — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 9: LLM port signatures, request builders and both providers

`prettyplay/llm/CODEMANIFEST` changes the port and both implementations in lockstep (parity is absolute):

- `generate_step_code(prompt, user_instructions, instruction, step_type, previous_steps, group_prompt, inputs: dict[str, str], declarations: list[str], snapshot, page_url, screenshot, cheat_sheet, attempt_history, recommendation, guidance) -> code: str` — `step_text` → `instruction` (the prepared instruction; the raw template sentence never reaches the request), plus `inputs` and `declarations`.
- `check_instruction_compliance(prompt, user_instructions, instruction, step_type, inputs, declarations, code, attempt_history) -> verdict: list[ComplianceFinding]`.
- `classify_group_failure(prompt, user_instructions, group_prompt, group_steps, previous_steps: list[ScenarioStep], step_text, attempt_history, snapshot, screenshot) -> diagnosis: GroupFailureClassification` — gains `previous_steps`.
- `classify_step_failure` — signature unchanged; `step_text` semantics documented as the prepared instruction.

Builder changes in `_request.py`: `build_fields_text(user_instructions, instruction, step_type, previous_steps, group_prompt, inputs, declarations, snapshot, page_url, cheat_sheet, attempt_history, recommendation, guidance)` — section order as traced: STEP TYPE line, STEP line, [INPUTS: `name = value` lines], [RESULTS: declared names + the return-contract sentence], [GROUP PROMPT], PREVIOUS STEPS (instruction fields, group-marked), PAGE SNAPSHOT, [PAGE URL], CHEAT SHEET, [USER INSTRUCTIONS], [HISTORY], [RECOMMENDATION], [USER GUIDANCE]; `_previous_step_line(record)` renders `record.instruction` (+ group marking from `record.group_prompt`); `build_group_diagnosis_fields(…, previous_steps)` inserts the optional PREVIOUS STEPS block before GROUP STEPS (GROUP STEPS lines render trace instructions); `build_compliance_fields(…, inputs, declarations)` inserts optional INPUTS/RESULTS after the STEP block (order: INSTRUCTIONS, STEP TYPE + STEP, [INPUTS], [RESULTS], ATTEMPT HISTORY, CODE). Both providers compose identically; one SDK call per operation through `send_with_retries`; parsers unchanged; the new inputs take no part in step addressing.

**Usages relevant to this task:**
- `openai` / `anthropic` (`.goga/usages/cooks/`): SDK call patterns and error mapping — unchanged mechanics; the request-attempt setting names supersede the older wording (do not implement old names).
- `conventions` (M1/M2): `tests/llm/test_request.py`, `tests/llm/test_openai_provider.py`, `tests/llm/test_anthropic_provider.py` (extend existing).

- [ ] **Contract tests**: port ABC signatures match the CODEMANIFEST exactly (parameter names and order: `instruction`, `inputs`, `declarations`, `previous_steps` in group diagnosis); both provider implementations accept the new keyword arguments; existing signature tests updated first (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, call `build_fields_text(...)` interactively with canned inputs and inspect the composed string — INPUTS/RESULTS sit immediately after STEP, PAGE URL immediately after PAGE SNAPSHOT; re-run after every builder edit
- [ ] **Code**: `prettyplay/llm/provider.py` — rename/extend the three method signatures per the contract (docstrings to the prepared-instruction semantics); `prettyplay/llm/_request.py` — the four builder changes above; `prettyplay/llm/openai_provider.py` and `prettyplay/llm/anthropic_provider.py` — thread the new inputs through `build_fields_text`/`build_group_diagnosis_fields`/`build_compliance_fields` identically
- [ ] **Interface verification**: `.venv/bin/pytest tests/llm/ -v` — all pass
- [ ] **Logic tests**: transfer verbatim from the design:
  - `test_provider_renders_inputs_and_results_blocks_in_fixed_order` — **Setup**: recorded provider request capture (openai implementation with a stubbed SDK call); **Input**: `generate_step_code(prompt=…, user_instructions="", instruction="Read novel into ", step_type="action", previous_steps=[], group_prompt=None, inputs={"expected": "Details"}, declarations=["name"], snapshot="snap", page_url="https://x", screenshot=None, cheat_sheet="cs", attempt_history=[], recommendation=None, guidance=None)`; **Trace**: `build_fields_text` composes sections; the user content string is captured; **Assertions**: `text.index("STEP TYPE: action") < text.index("STEP:\nRead novel into ") < text.index("INPUTS:\nexpected = Details") < text.index("RESULTS:") < text.index("PAGE SNAPSHOT:") < text.index("PAGE URL: https://x") < text.index("CHEAT SHEET:")`; identical composition asserted for the anthropic builder (parity); **Sufficiency**: the fixed scenario-part order — INPUTS/RESULTS immediately after STEP, PAGE URL immediately after PAGE SNAPSHOT (the defect D1 regression lock).
  - Group diagnosis: a `previous_steps` list renders the PREVIOUS STEPS block before GROUP STEPS from `record.instruction` fields with group marking; empty list omits the block; GROUP STEPS lines render the trace instructions (the model never sees raw Jinja).
  - Compliance fields: optional INPUTS/RESULTS insert after the STEP block; ATTEMPT HISTORY and CODE keep their positions; empty `inputs`/`declarations` omit the blocks.
  - `_previous_step_line`: renders `record.instruction`, group-marked when `record.group_prompt` is non-empty.
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: provider parity — both implementations expose the same operations and identical block composition; addressing independence — inputs/declarations never enter the address; `send_with_retries` wiring untouched
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/llm/ tests/llm/` and `ruff format --check` on the same — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 10: `run_step_code` returns the step's result

`prettyplay/engine/CODEMANIFEST` changes `run_step_code(code: str, page: PageFacade) -> result: dict[str, str] | None` (`location: execution.py`): the step function's return passes back as-is — plain data (the dictionary of declared names to observed strings for a step with declarations, None for a declaration-free step). `PageFacade.run(action) -> _T` already returns the callable's outcome; `run_step_code` merely stops dropping it. Everything else unchanged: compile/resolve on the calling thread, the whole step inside the driver worker thread, exceptions propagate untouched.

**Usages relevant to this task:**
- `conventions` (M1/M2): `tests/engine/test_execution.py` (extend the existing fakes-based tests).

- [ ] **Contract tests**: signature `run_step_code(code: str, page: PageFacade) -> dict[str, str] | None`; a returning step function's dictionary comes back; a `None`-returning step function comes back as `None` (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, evaluate `run_step_code('def step(page):\n    return {"name": "Dune"}\n', fake_page)` with the existing fake page from the tests — the dictionary returns
- [ ] **Code**: in `prettyplay/engine/execution.py`, return the outcome of the run primitive; update annotations and docstrings
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/test_execution.py -v` — all pass
- [ ] **Logic tests**: result passes through untouched (same object/values); exceptions still propagate as-is; the worker-thread boundary unchanged (calling thread never touches Playwright)
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: no translation, no swallowing, no retry
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/ tests/engine/` and `ruff format --check` on the same — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 11: `check_step_compliance` takes the render product; compliance prompt mirror updated

`prettyplay/engine/CODEMANIFEST` changes `check_step_compliance(config, provider, prepared: PreparedStep, step_type, code, attempt_history) -> findings: list[ComplianceFinding]` (`location: compliance.py`): the verdict request renders the prepared instruction with its INPUTS and RESULTS blocks so the reviewer judges the result-returning code against the declared contract. The inline `compliance_prompt` practice (in the engine CODEMANIFEST `Usages`) already carries the new INPUTS/RESULTS inputs and the RESULTS exact-key return-contract rule — copy its post-`---` content verbatim into the frozen mirror `COMPLIANCE_PROMPT` in `compliance.py` (the mirror and the practice change together; E501 per-file-ignores protect it from rewrapping). Gate mechanics unchanged: off-switch/empty generation instructions → empty findings with zero provider calls; hard failures propagate; the gate never runs on replayed cached code.

**Usages relevant to this task:**
- `compliance_prompt` (engine CODEMANIFEST inline): the authoritative prompt text for the frozen mirror.
- `conventions` (M1/M2): `tests/engine/test_compliance.py`.

- [ ] **Contract tests**: signature `check_step_compliance(config, provider, prepared, step_type, code, attempt_history)`; the provider receives `instruction=prepared.instruction`, `inputs=prepared.inputs`, `declarations=prepared.declarations` (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, diff the frozen `COMPLIANCE_PROMPT` constant against the CODEMANIFEST practice text interactively (`python -c "..."` comparing the strings) — must be identical
- [ ] **Code**: in `prettyplay/engine/compliance.py`, change the signature to the render product; thread `prepared.instruction`/`inputs`/`declarations` into `check_instruction_compliance`; replace `COMPLIANCE_PROMPT` with the updated verbatim mirror; update docstrings
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/test_compliance.py -v` — all pass
- [ ] **Logic tests**: the frozen mirror matches the CODEMANIFEST `compliance_prompt` verbatim (extend the existing mirror test); gate-off path returns `[]` with zero provider calls; findings pass through unchanged; `user_instructions` = effective `generation_prompt`
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: no attempt budget consumed here; hard failures propagate to the caller
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/compliance.py tests/engine/test_compliance.py` and `ruff format --check` on the same — fix findings (the prompt constant keeps its per-file E501 ignore)
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 12: `StepGenerator.generate` / `regenerate` — prepared threading, in-loop validation and publication

`prettyplay/engine/CODEMANIFEST` changes both loops (`location: generator.py`):

`generate(identity, prepared: PreparedStep, step_type, previous_steps, group_prompt, page, attempt_history, window, memory: StepMemory) -> step: CachedStep` — Algorithm (from the design, verbatim):
```
per attempt:
  budget.try_generation(identity) or exhaustion table
  code ← provider.generate_step_code(…, instruction=prepared.instruction, inputs=prepared.inputs,
          declarations=prepared.declarations, previous_steps, attempt_history=[r.render() …])
  url pair; TRY result ← settle(run_step_code, code, page, window)
    CATCH AssertionError → record(failed check) → decision table (group suppress | classify |
      one funded retry with recommendation | final classification)
    CATCH Exception → record(execution failed) → next attempt
    ELSE captures ← validate_step_result(prepared, result)
      (violation → record(failed check) → decision table — identical channel)
      findings ← check_step_compliance(prepared, step_type, code, history)
      high → record(compliance blocked), standing ← finding, next attempt   # nothing publishes
      ELSE medium/low → WARNING; memory.publish(captures); store; RETURN step
the funded regeneration repeats the same acceptance inline (execute → validate → gate → publish → store)
```
`regenerate(identity, prepared, step_type, previous_steps, group_prompt, page, attempt_history, recommendation, window, memory) -> step: CachedStep` — the same loop under the healing budget (try_healing), no classification; exhaustion raises `IncurableStepError` carrying the entry verdict — nothing publishes.

Acceptance ordering is the core invariant: captures publish **exactly once**, after validation and the gate; violations are failed checks entering the existing decision table (group suppression, classification, one funded retry); the frozen `SYSTEM_PROMPT` mirror is updated verbatim from `.goga/usages/prompts/step_generation.md` (STEP is the prepared instruction; INPUTS/RESULTS inputs; the two code forms; the read-from-page RESULTS rule). Requests carry `instruction=prepared.instruction`, `inputs=prepared.inputs`, `declarations=prepared.declarations`; classification calls pass the prepared instruction; the raw template sentence never reaches a request.

**Usages relevant to this task:**
- `system_prompt` (`.goga/usages/prompts/step_generation.md`): the authoritative generation prompt for the frozen mirror in `generator.py`.
- `memory` (`prettyplay/engine/renderer/.usages/memory.md`) / `validation` (`prettyplay/engine/renderer/.usages/validation.md`) from Imports: validate the returned result, then publish its captures only after the compliance gate passes.
- `generation` (`prettyplay/engine/.usages/generation.md`, already updated): honest-inputs bullets describe the target threading.
- `conventions` (M1/M2): `tests/engine/test_generator.py`.

- [ ] **Contract tests**: signatures of `generate`/`regenerate` match the CODEMANIFEST parameter order exactly; provider calls include `instruction`/`inputs`/`declarations`; `memory` is the last parameter (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, run a minimal fake-provider generation loop interactively (fake page returning the result dictionary, gate returning `[]`) — watch the acceptance order: request → settle → validate → gate → publish → store; re-run after each edit
- [ ] **Code**: in `prettyplay/engine/generator.py`, re-thread both loops per the algorithm above; result handling (`settle` now returns the result); `validate_step_result` at step 5 with the violation joining the failed-check channel; `memory.publish` at acceptance; `check_step_compliance(prepared, …)` at the gate; replace `SYSTEM_PROMPT` with the verbatim updated mirror; docstrings to the new signatures
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/test_generator.py -v` — all pass
- [ ] **Logic tests**: transfer verbatim from the design:
  - `test_generator_publishes_captures_after_gate_pass_and_stores` — **Setup**: fake provider returns `def step(page) -> dict: return {"name": "Dune"}`; gate returns `[]`; budgets fresh; **Input**: `generator.generate(identity, prepared(declarations=["name"]), "action", [], None, page, [], window, memory)`; **Trace**: request carries `instruction/inputs/declarations` → settle returns result → validate OK → gate `[]` → `memory.publish({"name": "Dune"})` → cache.save → return step; **Assertions**: memory snapshot; cache file exists; provider call kwargs include `instruction=prepared.instruction`, `inputs={}`, `declarations=["name"]`; **Sufficiency**: the acceptance ordering — validation → gate → publication → store.
  - `test_generator_violation_is_a_failed_check_and_publishes_nothing` — **Setup**: provider returns code yielding `{"name": ""}` (blank); classification returns `incurable`; **Input**: `generate(identity, prepared(declarations=["name"]), "action", [], None, page, [], window, memory)`; **Trace**: settle succeeds → validate raises → record(`failed check`, violation text) → classify → `IncurableStepError` carrying the verdict, code and violation text; **Assertions**: memory snapshot empty; history record outcome `failed check` with the deterministic text; raised `IncurableStepError.verdict.category == "incurable"`; **Sufficiency**: the result-contract violation joins the existing failed-check channel with publication withheld.
  - The frozen `SYSTEM_PROMPT` mirror matches `.goga/usages/prompts/step_generation.md` post-`---` verbatim (extend the existing mirror test).
  - `group_prompt` non-empty: internal classification points suppressed, failure raises the unclassified `IncurableStepError`; `group_prompt` None: behavior byte-identical to the ordinary path (C13) — existing tests stay green after signature updates.
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: publication exactly once per acceptance; gate hard failures (`LLMUnavailableError`, `ComplianceVerdictError`) propagate with nothing cached/published; the funded regeneration publishes like any acceptance; budget mechanics untouched
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/generator.py tests/engine/test_generator.py` and `ruff format --check` on the same — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 13: `StepHealer.heal` threads the render product and memory

`prettyplay/engine/CODEMANIFEST` changes `heal(step, error, prepared: PreparedStep, step_type, previous_steps, page, attempt_history, window, memory: StepMemory) -> step: CachedStep` (`location: healer.py`): classification via `classify_step_failure` passes the prepared instruction (`step_text=prepared.instruction`); verdict mapping unchanged (product_defect → `ProductDefectError`; incurable → `IncurableStepError`; rot/fixable → `generator.regenerate(identity, prepared, step_type, previous_steps, None, page, attempt_history, recommendation, window, memory)` — the loop validates, gates, publishes and stores); the engine-cell wrapper `classify_step_failure` (`classification.py`) keeps its signature — its `step_text` parameter simply receives the prepared instruction at every call site (docstring note only, no code change in `classification.py`).

**Usages relevant to this task:**
- `healing` (`prettyplay/engine/.usages/healing.md`, already updated): the scenario-context bullet and example describe the target threading.
- `conventions` (M1/M2): `tests/engine/test_healer.py`.

- [ ] **Contract tests**: `heal` signature matches the CODEMANIFEST; the classification call receives `prepared.instruction` as `step_text`; `regenerate` receives `prepared` and `memory` (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, drive a fake rot-classified heal interactively — the classification request's STEP line shows the prepared instruction, never `{{`
- [ ] **Code**: in `prettyplay/engine/healer.py`, re-thread per the contract; docstrings updated
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/test_healer.py -v` — all pass
- [ ] **Logic tests**: classification sees the prepared instruction (assert on the fake provider's captured `step_text`); product_defect/incurable raise carrying verdict + underlying error; rot/fixable delegate to `regenerate` with `prepared`+`memory`; nothing publishes on a failed or gate-blocked regeneration (publication lives in the generator loop)
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: anti-masking unchanged; verdicts fully reach the raised errors; `classification.py` untouched
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/healer.py tests/engine/test_healer.py` and `ruff format --check` on the same — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 14: `GroupStepOutcome` gains `instruction` and `vars`

`prettyplay/engine/groups/CODEMANIFEST` changes `GroupStepOutcome(sentence, instruction, step_type, tries, delay, vars: dict[str, str], outcome, url_before, url_after, identity)` (`location: outcome.py`): pydantic v2, kw_only, frozen, empty defaults (`vars` defaults to an empty dict — not None; `identity` stays required). `render()` renders the instruction line first (the unit the GROUP STEPS block renders): 1. The instruction line — the prepared instruction verbatim; 2. The outcome line; 3. The URL line. `sentence` is the re-render source (never rendered into requests); `vars` is the re-render input of the row mechanics; `identity` never renders.

**Usages relevant to this task:**
- `conventions` (M1/M2): `tests/engine/groups/test_outcome.py`.

- [ ] **Contract tests**: new fields with empty defaults; `render()` starts with the instruction line (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, construct a trace record and print `render()` — instruction line, outcome line, URL line, in that order
- [ ] **Code**: in `prettyplay/engine/groups/outcome.py`, add `instruction: str = ""` and `vars: dict[str, str] = field(default_factory=dict)`-equivalent pydantic default; reorder `render()` per the contract
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/groups/ -v` — all pass
- [ ] **Logic tests**: transfer verbatim from the design:
  - `test_group_trace_records_instruction_and_vars` — **Input**: group step `g.step("Check {{ vars.code }}", vars={"code": "A1"})` with fakes (the record is constructed directly here: `GroupStepOutcome(sentence="Check {{ vars.code }}", instruction="Check A1", vars={"code": "A1"}, …)`); **Assertions**: `record.render()` starts with the instruction line; `vars` round-trips; **Sufficiency**: the trace feeds row re-render (sentence + vars) and the matcher (instruction) — both fields must be recorded.
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: immutable once appended; no truncation in `render()`
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/groups/ tests/engine/groups/` and `ruff format --check` on the same — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 15: `classify_group_failure` gains `previous_steps` (groups cell wrapper)

`prettyplay/engine/groups/CODEMANIFEST` changes the engine-cell wrapper `classify_group_failure(config, provider, group_prompt, traces, previous_steps: list[ScenarioStep], step_text, step_type, attempt_history, page) -> diagnosis` (`location: diagnosis.py`): composes the diagnosis request with the whole prior scenario visible — the provider renders the optional PREVIOUS STEPS block from `previous_steps`' instruction fields before GROUP STEPS; `step_text` is the failed step's prepared instruction (never the raw template sentence); the frozen `GROUP_DIAGNOSIS_PROMPT` mirror is updated verbatim from `.goga/usages/prompts/group_diagnosis.md` (PREVIOUS STEPS block of prepared instructions; `earliest_step` quotes a visible instruction). Degraded-verdict and unavailability handling unchanged.

**Usages relevant to this task:**
- `group_diagnosis` (`.goga/usages/prompts/group_diagnosis.md`): the authoritative prompt for the frozen mirror.
- `conventions` (M1/M2): `tests/engine/groups/test_diagnosis.py`.

- [ ] **Contract tests**: signature with `previous_steps` after `traces`; call the wrapper with a prepared instruction string as `step_text` and verify that the provider receives that same string and `previous_steps`, without raw Jinja (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, diff the frozen `GROUP_DIAGNOSIS_PROMPT` against the updated practice file interactively — identical
- [ ] **Code**: in `prettyplay/engine/groups/diagnosis.py`, add the parameter, thread it into the provider call, replace the frozen mirror verbatim, update docstrings
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/groups/test_diagnosis.py -v` — all pass
- [ ] **Logic tests**: the request carries PREVIOUS STEPS (instruction fields, group-marked) before GROUP STEPS; empty list omits the block; the mirror matches the practice verbatim; degraded/unavailable handling unchanged
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: provider unavailability propagates as `LLMUnavailableError`
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/groups/ tests/engine/groups/` and `ruff format --check` on the same — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 16: `GroupRecovery.recover` — local views, row re-render, per-step publication

`prettyplay/engine/groups/CODEMANIFEST` changes `recover(group_prompt, traces, prepared: PreparedStep, step_type, previous_steps, identity, attempt_history, page, window, memory: StepMemory) -> step: CachedStep` (`location: recovery.py`). Algorithm (from the design, verbatim):
```
1. open_group_cycle(group_prompt) or raise (cycle cap)
2. local_scenario ← copies of previous_steps; local_traces ← copies of traces
   active ← (prepared, step_type, identity, attempt_history, error ← last record's error)
3. verdict ← classify_group_failure(…, local_traces, local_scenario, active.instruction,
              step_type, active.history, page)
4. product_defect / outside-root (matched against local_scenario instructions) / incurable →
   raise carrying the mapped verdict and active.error
5. row ← local_traces[index_of(earliest_step match):]   # no match → the active failure's occurrence
   refresh_healing per row identity
6. FOR each row trace (sequential):
     sleep(trace.delay) if declared
     fresh ← render_step(trace.sentence, trace.step_type, memory, trace.vars)
     row_history ← active history for the failed step / anchored record-0 list for earlier steps
     regenerate(trace.identity, fresh, trace.step_type, local_scenario_view, group_prompt,
                row_history, verdict.recommendation, SettleWindow(…, trace.tries), memory)
       # inside: execute → validate → gate → publish → store
     update the occurrence's instruction in local_scenario + local_traces (by index)
     on_healing_started / on_healed; group_row_recovered log
   RETURN the failed step's healed CachedStep
7. row failure → active ← (fresh prepared of that occurrence, its identity/type, grown history,
   fresh error); mark the occurrence failed in local_traces (keep the fresh instruction);
   GOTO 1 while cycles remain
```
Local views are `model_copy(update=…)` copies — the caller's lists are never mutated; occurrences are located by group order (index), never by sentence equality (sentences may repeat); every row step re-renders through `render_step` (imported from the renderer) against the current memory before its regeneration; a re-render authoring error propagates loudly as that row step's failure (defensive; never swallowed, never retried silently); published captures of earlier accepted row steps are never rolled back; the failed step's captures publish with its acceptance and it is never executed again merely to recover them; on full row success the return value is the healed cached step of the **originally** failed step.

**Usages relevant to this task:**
- `rendering` (from Imports, `prettyplay/engine/renderer/.usages/rendering.md`): the row re-render patterns.
- `memory` (`prettyplay/engine/renderer/.usages/memory.md`) / `validation` (`prettyplay/engine/renderer/.usages/validation.md`) from Imports: each regenerated row step validates its returned result and publishes the captures at its own acceptance point after the compliance gate.
- `recovery` (`prettyplay/engine/groups/.usages/recovery.md`, already updated): row re-render, local views, publication.
- `conventions` (M1/M2): `tests/engine/groups/test_recovery.py`.

- [ ] **Contract tests**: `recover` signature matches the CODEMANIFEST; the diagnosis receives the local views and `active.instruction`; row regenerations receive freshly rendered `PreparedStep` objects and `memory` (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, drive a minimal fake two-step row interactively — verify the row step's provider request carries the fresh instruction (not the executor's stale one) and the caller's lists are the same objects afterward
- [ ] **Code**: in `prettyplay/engine/groups/recovery.py`, implement per the algorithm — local views, active failure facts, re-render per row step, per-step acceptance (inside `regenerate`), index-based occurrence updates, cycle re-entry on row failure
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/groups/test_recovery.py -v` — all pass
- [ ] **Logic tests**: transfer verbatim from the design:
  - `test_recovery_rerenders_row_step_against_current_memory` — **Setup**: group traces: step1 `sentence="Read {{ kind }} into {% var name %}"`, `vars={}`, `instruction="Read novel into "` (recorded at execution); memory now holds `name="Dune"` after the failed step's history; diagnosis verdict `recoverable`, `earliest_step="Read novel into "`; fake provider regenerates `def step(page): return {"name": "Dune"}`; **Input**: `recovery.recover(group_prompt, traces, prepared_failed, "action", scenario, identity, history, page, window, memory)`; **Trace**: recover → local views copied → diagnosis → row = [step1, failed] → step1: `fresh = render_step("Read {{ kind }} into {% var name %}", "action", memory, {})` → instruction "Read novel into " (same values); regenerate carries fresh → failed step: fresh render with memory containing name → its own regeneration → per step: validate → gate → publish → store; local views updated by index → returns the failed step's healed `CachedStep`; **Assertions**: provider received `instruction="Read novel into "` for step1 (fresh, not stale); `memory` holds recaptured values; caller's `traces`/`previous_steps` unchanged objects; row histories anchored per step; **Sufficiency**: row re-render against current context + local-view isolation — the two most intricate recovery mechanics.
  - `test_recovery_row_failure_updates_active_failure_for_next_diagnosis` — **Setup**: two-row recovery; the first row step's regeneration raises `IncurableStepError` once; second diagnosis verdict `product_defect`; **Input**: `recover(…)`; **Trace**: row step 1 fails → active failure updated (fresh prepared, identity, grown history, error) → occurrence marked failed with the fresh instruction preserved → new diagnosis receives that STEP/HISTORY → product_defect raises `ProductDefectError`; **Assertions**: the second `classify_group_failure` call received the row step's instruction (not the executor's original) as `step_text`; local trace view marks failure; caller views untouched; **Sufficiency**: "STEP and HISTORY always describe the failure that triggered that diagnosis".
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: no page-state rollback; no new failure kinds; the ordinary per-step healing pools of non-group steps never consumed; strict mode never invokes recovery (executor guards)
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/groups/ tests/engine/groups/` and `ruff format --check` on the same — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 17: `StepSteering.steer` — validated, gated, published green turns

`prettyplay/engine/steering/CODEMANIFEST` changes `steer(failure, identity, prepared: PreparedStep, step_type, previous_steps, group_prompt, page, attempt_history, memory: StepMemory) -> healed: CachedStep | None` (`location: steering.py`). Algorithm (from the design, verbatim): banner (prepared instruction — never `{{`) → prompt loop: local commands | guidance → request (`instruction=prepared.instruction`, `inputs`, `declarations` + guidance + history, group framing when applicable) → show code → `run? [y/N]` → `y`: `run_step_code` (no settle) → `validate_step_result` (violation → red turn, record `failed check`) → gate (high → red turn, record `compliance blocked`; hard → end dialog, return `None`) → `memory.publish` + write-back + `on_healed` → return healed; `n`/Enter/quit → record rejected, back to prompt; quit/EOF/SIGINT/unreadable stdin → return `None`. The frozen `SYSTEM_PROMPT` mirror in `steering.py` (cell-owned copy) is updated verbatim from `.goga/usages/prompts/step_generation.md` in lockstep with Task 12.

**Usages relevant to this task:**
- `system_prompt` (`.goga/usages/prompts/step_generation.md`): the frozen mirror source.
- `memory` (`prettyplay/engine/renderer/.usages/memory.md`) / `validation` (`prettyplay/engine/renderer/.usages/validation.md`) from Imports: an approved green turn validates its result, then publishes captures with cache write-back after the compliance gate.
- `steering` (`prettyplay/engine/steering/.usages/steering.md`, already updated): validation + publication semantics.
- `conventions` (M1/M2): `tests/engine/steering/test_steering.py`; stdin scripted via `monkeypatch`/`tmp_path` per the existing tests.

- [ ] **Contract tests**: `steer` signature matches the CODEMANIFEST; the guidance request carries `instruction`/`inputs`/`declarations`; the banner carries the prepared instruction (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, script stdin `b"guidance\ny\n"` through a fake provider and watch one green turn accept end-to-end (validate → gate → publish → write-back) before writing the logic tests
- [ ] **Code**: in `prettyplay/engine/steering/steering.py`, thread `prepared`+`memory`; result validation on every green turn; publication only with the write-back; the frozen mirror update; docstrings
- [ ] **Interface verification**: `.venv/bin/pytest tests/engine/steering/ -v` — all pass
- [ ] **Logic tests**: transfer verbatim from the design:
  - `test_steer_validates_green_turn_and_publishes_with_writeback` — **Setup**: stdin scripted `b"guidance\ny\n"`; provider returns `def step(page) -> dict: return {"name": "Dune"}`; gate `[]`; prepared has `declarations=["name"]`; **Input**: `steering.steer(failure, identity, prepared, "action", [], None, page, history, memory)`; **Trace**: banner carries the prepared instruction → guidance request carries instruction/inputs/declarations + USER GUIDANCE → approval → `run_step_code` → result → validate OK → gate `[]` → publish → write-back → `on_healed` → returns healed step; **Assertions**: memory snapshot `{"name": "Dune"}`; cache saved; healed returned; banner line contains the prepared instruction, never `{{`; **Sufficiency**: the steering acceptance chain — result validation and publication ride the same acceptance rule as the engines.
  - `test_steering_violation_is_a_red_turn_without_publication` — **Setup**: stdin `b"guidance\ny\nquit\n"`; provider returns blank-valued code; **Input**: `steer(...)` → executed turn validates to a violation; **Assertions**: record appended with outcome `failed check`; memory empty; nothing cached; dialog returns to the prompt and finally `None` → the original failure propagates; **Sufficiency**: interactive turns obey the same acceptance rule; nothing green is written back unvalidated.
  - The frozen `steering.SYSTEM_PROMPT` mirror matches the practice verbatim.
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: no budget consumed, settle never re-arms, no code executes without approval, every exit path heals or returns `None`
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/steering/ tests/engine/steering/` and `ruff format --check` on the same — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 18: Facade and group `vars` — `_validate_vars` and keyword-only threading

The root CODEMANIFEST (`prettyplay`) extends `PrettyPlay.step`/`expect` and `StepGroup.step`/`expect` (`locations: scenario.py`, `groups.py`) with the keyword-only `vars: dict[str, str] | None`: the call-local string inputs, validated at the call surface — a shared `_validate_vars` beside `_validate_tries`/`_validate_delay` in `groups.py`, used by the facade and the group methods; every value must be `str` (bools never coerce), otherwise the loud actionable `PrettyplayError` naming the parameter, the received value and the allowed form — uniform with tries/delay; executor/render never invoked on rejection. The methods delegate to `executor.execute(..., vars=vars)`.

**Usages relevant to this task:**
- `conventions` (M1/M2): `tests/test_scenario.py`, `tests/engine/groups/test_groups.py` or the existing facade test locations.
- `steps` (`prettyplay/.usages/steps.md`, already updated): the vars + templates + memory authoring docs.

- [ ] **Contract tests**: `vars` is keyword-only on all four methods; `PrettyPlay(cache_key=...)` facade unchanged otherwise (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, call the validator directly with `{"expected": 42}` and `{"expected": True}` — both raise naming `vars`, the received value and the allowed form; `{"expected": "D"}` passes
- [ ] **Code**: in `prettyplay/groups.py`, add `_validate_vars` (mirroring the `_validate_tries`/`_validate_delay` style: reject non-dict, reject every non-str value — `isinstance(value, str)` with bool awareness); extend the four `step`/`expect` signatures with `*, vars: dict[str, str] | None = None`; thread into the executor delegation; `prettyplay/scenario.py` imports `_validate_vars` from `.groups` beside the existing validators
- [ ] **Interface verification**: `.venv/bin/pytest tests/test_scenario.py -v` — all pass
- [ ] **Logic tests**: transfer verbatim from the design:
  - `test_facade_rejects_non_string_vars_value` — **Setup**: `t = PrettyPlay("k")` with fakes; **Input**: `t.step("open the page", vars={"expected": 42})`; **Trace**: `_validate_vars` before the executor → raise; **Assertions**: `pytest.raises(PrettyplayError)` naming `vars`, the received value `42` and the allowed form; executor/render never invoked; no page opened; **Sufficiency**: the loud call-surface validation, uniform with tries/delay.
  - Valid `vars` reach the executor delegation unchanged; `vars=None` is the default (no validation error, empty bindings downstream).
- [ ] **Debugging**: re-run the task-focused tests after adding logic tests and fix the implementation until they pass; run `.venv/bin/pytest tests/ -x` diagnostically, map each remaining expected failure to a specific pending migration task, and fix every unrelated regression (do not weaken tests)
- [ ] **Contract re-verification**: tries/delay validation untouched; the traceback folding guarantee preserved
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/ tests/` and `ruff format --check` on the same — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 19: `StepExecutor.execute` — the render point and memory owner

The root CODEMANIFEST changes `StepExecutor` (`location: executor.py`): constructs the test's own `StepMemory` once in `__init__` (one per test execution); `execute(step_text, step_type, page, group, tries, delay, vars)`. Algorithm (from the design, verbatim):
```
1. emit on_step_started(step_text, step_type); IF delay is not None: sleep(delay)
2. prepared ← render_step(step_text, step_type, self._memory, vars)
3. identity ← StepIdentity(cache_key, step_type, normalize_step_text(step_text))
   window ← SettleWindow(polling_timeout, polling_delay, tries); attempt_history ← []
   group_url_before ← read_url(page) IF group
4. cached ← cache.load(identity)
5. IF cached is not None:
     url_before ← group bracket or read_url(page)
     TRY result ← settle(run_step_code, cached.code, page, window)
         captures ← validate_step_result(prepared, result); self._memory.publish(captures)
       CATCH error:
         route failure (formatted by format_step_error, replay URL pair):
           strict → classify(prepared.instruction) → raise by kind (quiet skip on LLM down)
           group  → failed trace + record 0 + recover(…, prepared, …, memory) → steering gate
           else   → record 0 + heal(step, error, prepared, …, memory) → steering gate
   ELIF strict → raise IncurableStepError(strict miss)
   ELSE → generate(identity, prepared, step_type, scenario, group_prompt, page, history, window,
                   memory) → group routing of its IncurableStepError → steering gate
6. scenario.append(ScenarioStep(sentence=step_text, instruction=prepared.instruction, group_prompt))
   group trace append (sentence, instruction, step_type, tries, delay, vars, outcome, urls, identity)
7. emit on_step_passed; failure path: on_step_failed(step_text, str(error)) → on_step_verdict →
   raise; finally on_step_finished(step_text, step_type, outcome)
```
Key invariants: render **before** identity (authoring errors precede cache access — browser untouched, identity untouched); identity from the **original** sentence, never the instruction; the HIT path validates and publishes (the gate never runs on replay — acceptance is the validated successful execution); a validation violation routes into the existing failed-check paths with the replay URL pair; hook events carry the raw sentence (option A) while the failure text (`error` payload) carries the prepared instruction; the steering intercept wraps the engine paths exactly at a caught `IncurableStepError` on a non-strict interactive run.

**Usages relevant to this task:**
- `rendering` (`prettyplay/engine/renderer/.usages/rendering.md`) / `memory` (`prettyplay/engine/renderer/.usages/memory.md`) / `validation` (`prettyplay/engine/renderer/.usages/validation.md`) from Imports: render each step from the memory snapshot before addressing; validate a cached replay's result and publish captures only after successful validation.
- `generation` / `healing` / `recovery` (from Imports): the engine cycles the executor delegates to.
- `conventions` (M1/M2): `tests/test_executor.py`.

- [ ] **Contract tests**: `StepMemory` constructed in `__init__`; `execute(..., vars)` signature; the executor constructs the identity from the raw sentence (expected to fail at this stage)
- [ ] **REPL checkpoint** (M4): in the venv, drive a primed-cache replay interactively with the test fakes — render → identity → HIT → settle → validate → publish; watch `memory.snapshot()` grow and confirm no provider/generator/gate calls
- [ ] **Code**: in `prettyplay/executor.py`, implement per the algorithm — the memory field, the render-before-identity ordering, result carriage on the HIT path with validation and publication, violation routing, record-0 seeding before heal, group trace and `ScenarioStep` dual-text appends, hook surface unchanged
- [ ] **Interface verification**: `.venv/bin/pytest tests/test_executor.py -v` — all pass
- [ ] **Logic tests**: transfer verbatim from the design:
  - `test_executor_publishes_validated_captures_on_cached_replay` — **Setup**: fake page; cache primed with `code = 'def step(page):\n    return {"name": "Dune"}\n'` for the identity of `"Read {{ kind }} into {% var name %}"` (memory holds `kind` → "novel"); non-strict; **Input**: `executor.execute("Read {{ kind }} into {% var name %}", "action", page, vars=None)`; **Trace**: render_step → `PreparedStep(instruction="Read novel into ", declarations=["name"])` → identity ← normalize(original sentence); cache.load → HIT → settle → `{"name": "Dune"}` → validate → captures → publish → `ScenarioStep(sentence=<raw>, instruction="Read novel into ", group_prompt="")` → on_step_started/on_step_passed carry the raw sentence; **Assertions**: `memory.snapshot() == {"kind": "novel", "name": "Dune"}`; the prior `kind` value survives publication of `name`; scenario record holds both texts; no LLM calls; no gate call; **Sufficiency**: the replay acceptance rule — the gate never runs on replay; publication is the validated successful execution.
  - `test_executor_strict_template_step_validates_and_publishes_on_replay` — **Setup**: `strict=True`; cache primed under `StepIdentity(cache_key="k", step_type="action", normalized_text=normalize_step_text("Read {{ kind }} into {% var name %}"))` with `def step(page): return {"name": "Dune"}`; executor memory initially `{"kind": "novel"}`; fake page returns the step function's plain result; fake provider and generator record calls; patch the gate with a call recorder; **Input**: `executor.execute("Read {{ kind }} into {% var name %}", "action", page, vars=None)`; **Trace**: render reads `kind="novel"` and declares `name`; identity uses the raw template; cache hit; `settle` passes through `{"name": "Dune"}`; validation returns that dictionary; executor publishes `name` and retains `kind`; scenario receives raw sentence and prepared instruction; strict replay does not request a gate or LLM call; **Assertions**: `assert memory.snapshot() == {"kind": "novel", "name": "Dune"}`; `assert provider.call_count == 0`; `assert generator.call_count == 0`; `assert gate.call_count == 0`; `assert scenario[-1].instruction == "Read novel into "`; **Sufficiency**: strict replay accepts and publishes valid captures without regeneration or compliance gating.
  - `test_executor_strict_template_result_violation_stays_unpublished` — **Setup**: same strict cache and initial memory as the successful test, except cached code returns `{"name": ""}`; fake provider's classification response is `FailureClassification(category="incurable", explanation="capture is blank", recommendation="inspect the page")`; fake page supplies snapshot `"snap"`; generator and gate are call-recording fakes; **Input**: `executor.execute("Read {{ kind }} into {% var name %}", "action", page, vars=None)`; **Trace**: render and cache hit follow the successful test; `settle` returns the blank dictionary; `validate_step_result` raises `AssertionError` naming `name`; replay failure formats the assertion text without an `AssertionError` prefix; strict classification receives `step_text="Read novel into "`, failed code and the validation text; the `incurable` verdict raises `IncurableStepError`; no publication, generation or gate call occurs; **Assertions**: `pytest.raises(IncurableStepError)` with `"name" in str(exc.value)` and `exc.value.verdict.category == "incurable"`; `assert memory.snapshot() == {"kind": "novel"}`; `assert provider.classify_step_failure.call_count == 1`; `assert generator.call_count == 0`; `assert gate.call_count == 0`; **Sufficiency**: a result-contract violation on cached strict replay must remain a failed check, keep memory unchanged and terminate through classification without generation.
  - Delay ordering: a declared `delay` sleeps before rendering — an authoring error surfaces after the pause (matches the numbered contract order).
- [ ] **Debugging**: `.venv/bin/pytest tests/ -x` — fix implementation code until all tests pass
- [ ] **Contract re-verification**: one settle window per step execution; one render per step execution; `on_step_finished` exactly once; the `_delegated` group-pause mechanics unchanged; strict MISS → `IncurableStepError` with no generation request
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/ tests/` and `ruff format --check` on the same — fix findings
- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

### Task 20: Integration tests — the template flow end to end

Cross-cell scenarios spanning the facade, executor, renderer, engines and LLM port with the established fakes (fake `PageFacade` with `run(fn)` returning `fn(fake_page)`, fake `LLMProvider` returning canned code, `tmp_path` cache roots). Per convention M2.3, multi-package integration tests sit directly in `tests/` — extend `tests/test_integration.py` (and the group integration file where group-scoped).

**Usages relevant to this task:**
- `conventions` (M2): integration tests only for cross-module/package interaction; they do not replace per-entity contract/logic tests.

- [ ] Create/extend the integration test cases in `tests/test_integration.py`
- [ ] Test cross-entity interaction, transfer verbatim from the design:
  - `test_scenario_records_carry_both_texts_and_events_carry_raw_sentence` — **Setup**: template step end-to-end with fakes (miss → generate → accept); **Input**: `t.step("Open the item named {{ name }}")` after a capture step; **Assertions**: `ScenarioStep(sentence="Open the item named {{ name }}", instruction="Open the item named Book", …)`; hook events' `step_text == "Open the item named {{ name }}"`; the provider request's STEP line is the prepared instruction; **Sufficiency**: the dual-text invariant and the hook-surface decision (option A).
  - Capture flow across steps (design Data Flow 5): step A `{% var name %}` declares; accepted execution returns `{"name": "Book"}`; validation passes; publication; step B `{{ name }}` reads the snapshot value "Book"; the model and the failure texts see the prepared instruction with "Book" embedded.
  - Group template flow: `g.step("Check {{ vars.code }}", vars={"code": "A1"})` traces `GroupStepOutcome(sentence=…, instruction="Check A1", vars={"code": "A1"}, …)` and the diagnosis/group requests carry instructions only.
- [ ] Test edge case: cached replay of a template step under `strict=True` end-to-end (render → HIT → validate → publish; no LLM keys required)
- [ ] Run validation: `.venv/bin/pytest tests/ -x` — all green

- [ ] **Full lint/format gate (M3)**: `.venv/bin/ruff check prettyplay/ tests/` and `.venv/bin/ruff format --check prettyplay/ tests/` — both pass before marking this task complete

---

## Validation Commands

All commands run in the project virtualenv (Task 1 recreates it; prefix with `.venv/bin/` or activate it).

- `.venv/bin/pytest tests/ -x`: Run all tests
- `.venv/bin/pytest tests/engine/renderer/test_render.py -v`: Run a specific test file
- `.venv/bin/ruff check prettyplay/`: Lint the source
- `.venv/bin/ruff check prettyplay/ tests/`: Lint everything (commit gate, M3.4)
- `.venv/bin/ruff format --check prettyplay/ tests/`: Formatter check (commit gate, M3.4)
- `.venv/bin/python -c "from prettyplay.engine.renderer import PreparedStep, StepMemory, render_step, validate_step_result"`: Renderer facade check
- `.venv/bin/python -c "import prettyplay"`: Root package import check

---

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location`
- [ ] Every contract entity is accessible from its facade (renderer `__all__` carries all four names)
- [ ] Properties and methods match the declared API
- [ ] Descriptions are reflected in behavior (acceptance ordering, dual-text records, hook surface)
- [ ] Contract dependencies are met (renderer imports only `prettyplay/failures` + `jinja2`; no import cycles)
- [ ] Re-exports are accessible from the facade (root re-exports unchanged and green)
- [ ] Every coding task followed the TDD workflow (contract tests → initial REPL probe → code with a REPL probe after each edit → interface verification → logic tests → debugging → contract re-verification → lint)
- [ ] Contract tests and logic tests cover facade, API, and behavior within each coding task
- [ ] Integration tests exist for the cross-entity template flow (Task 20)
- [ ] No package boundary was expanded; no new cells beyond the contracted renderer
- [ ] `CODEMANIFEST` files were not modified (contract is read-only)
- [ ] All validation commands pass (tests, lint, format check, facade checks)
- [ ] The mandatory rules M1–M4 were applied in every task: conventions-based style, conventions-based tests, lint/format gates at every stage and before every local commit, REPL-cycle inner loop
- [ ] Every Usages entry is mentioned in at least one task (conventions, jinja, taxonomy, system_prompt, compliance_prompt, group_diagnosis, group_framing, classification_prompt, cheat_sheet, rendering, memory, validation)
