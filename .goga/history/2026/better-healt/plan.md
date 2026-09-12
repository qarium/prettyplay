# Plan: `better-healt`

Bounded healing, settle polling and interactive steering of prettyplay — compiled from the design
document (`.goga/history/2026/better-healt/design.md`) and the applied CODEMANIFEST contracts.

---

## Purpose

Implement the three features the applied contracts add to prettyplay:

- **Settle polling** — a per-step-execution `SettleWindow` + `settle` loop that re-executes step
  code (cached code and candidates alike, replay-strict included) to absorb transient page-state
  failures before any costly move; recognition lives in the driver's fixed pollable map
  `is_pollable_failure`.
- **Bounded healing** — a failed check inside the generate loop no longer burns the whole budget:
  classification decides, and a rot/fixable verdict grants exactly one healing-funded
  recommendation-carrying regeneration (also at exhaustion); the fourth verdict label `fixable`
  runs through every path.
- **Interactive steering** — the opt-in `StepSteering` REPL opened by the executor exactly when an
  `IncurableStepError` would propagate on a non-strict interactive run; guidance turns are
  regeneration requests executed against the live page, healing writes back to the cache.

The most important gaps between contract and code: the two new cells (`engine/polling`,
`engine/steering`) have CODEMANIFESTs and `.usages/` but no Python code; `IncurableStepError`
lacks the `code` field; `StepHooks` has nine events (the contract requires ten); `Config` and the
loader lack the three polling/interactive settings; the LLM port lacks `recommendation`/`guidance`/
`guidance_history`; the engine loops lack the window, bounded healing and the code field; the
executor lacks the steering intercept and `on_step_finished`; the facade does not compose steering.

Strategy: implement cell by cell in dependency order (leaves first — the order matches the
contract import map), one TDD task per contract entity or cohesive location, then integration
tests through the public facade. `CODEMANIFEST` files are read-only throughout.

## Context

### Contract Surface

**Entity: `IncurableStepError`** (changed)
- Type: class — mutation `PrettyplayError::IncurableStepError`
- Declared `location`: `prettyplay/failures/errors.py`
- Facade obligation: importable from `prettyplay.failures`
- Signature: `(step_text: str, reason: str, error: str, code: str, verdict: FailureVerdict | None)`
  — `code: str = ""` inserted between `error` and `verdict` (empty default; None is reserved for
  explicit absence, code's absence is the empty string)
- New property: `code -> str` — the step code that terminally failed; filled by the raiser (cached
  step code on healing/strict paths, last candidate on the generation path); empty — unknown
  (the strict cache miss carries none)
- Semantic requirements: `code` is programmatic-only — never rendered, never carried by hook or
  log payloads; the render path (`render_terminal_message`) is untouched
- Imported dependencies: `FailureVerdict` (same cell)

**Entity: `StepHooks`** (changed)
- Type: class
- Declared `location`: `prettyplay/reporting/hooks.py`
- Facade obligation: importable from `prettyplay.reporting`; re-exported by `prettyplay`
- New method: `on_step_finished(step_text: str, step_type: str, outcome: str)` — the closing event
  of every step, fired exactly once regardless of outcome; `outcome` is `passed` or `failed`;
  placed between `on_step_verdict` and `on_generation_started`; base implementation is a no-op;
  the class docstring grows to ten prettyplay events
- Semantic requirements: fired after `on_step_passed`, or after `on_step_failed` — and after
  `on_step_verdict` whenever the verdict exists; covers every terminal kind
- Log level: step lifecycle INFO (the reporter's `_WARNING_EVENTS` stays `{"on_cache_skipped"}`)

**Entity: `Config`** (changed)
- Type: class (pydantic v2, kw_only, empty defaults)
- Declared `location`: `prettyplay/config/models.py`
- Facade obligation: importable from `prettyplay.config` (publicly `PrettyConfig`)
- New fields: `polling_timeout: float | None = None` (None or a finite `>= 0` — `math.isfinite`;
  negative or non-finite fails loudly), `polling_delay: float = 0.5` (`>= 0`, finite, 0 allowed),
  `interactive: bool = False`
- `_ALLOWED_TEXT` grows: `polling_timeout: "None or a non-negative number (finite)"`,
  `polling_delay: "a non-negative number"`, `interactive: "a boolean"`

**Routine: `load_config`** (changed)
- Declared `location`: `prettyplay/config/loader.py`
- Signature unchanged: `(pyproject_path: str | None, overrides: Config | None) -> config: Config`
- Changes: `_ENV_NAMES` grows `polling_timeout`/`polling_delay`/`interactive`
  (`PRETTYPLAY_POLLING_TIMEOUT`, `PRETTYPLAY_POLLING_DELAY`, `PRETTYPLAY_INTERACTIVE`);
  `_parse_env_scalar` gains `_FLOAT_ENV_SETTINGS = {"polling_timeout", "polling_delay"}` —
  `float(raw)` with a loud `ConfigurationError` naming setting, received value and "a decimal
  float"; `interactive` joins `_BOOL_ENV_SETTINGS`; `_apply_overrides` gains the
  `if value is None: continue` clause **before** the string-emptiness check

**Routine: `is_pollable_failure`** (new)
- Declared `location`: `prettyplay/driver/errors.py`
- Facade obligation: importable from `prettyplay.driver` (added to `__all__`)
- Signature: `(exc: Exception) -> pollable: bool`
- Pure function: no state, no I/O, deterministic on the exception alone; the map is fixed in code

**Entity: `LLMProvider` (port) + `OpenAIProvider` + `AnthropicProvider`** (changed)
- Locations: `prettyplay/llm/provider.py`, `openai_provider.py`, `anthropic_provider.py`
- `generate_step_code` grows `recommendation: str | None`, `guidance: str | None`,
  `guidance_history: list[str]` — no defaults (callers pass explicitly, uniform with
  `existing_code`/`error`); both implementations forward them verbatim to the shared
  `build_fields_text`
- `prettyplay/llm/_request.py` `build_fields_text` renders the sections in the fixed order:
  STEP, PREVIOUS STEPS, PAGE SNAPSHOT, PAGE API, USER INSTRUCTIONS (non-empty), CODE
  (`existing_code is not None`), ERROR (`error is not None`), RECOMMENDATION (non-empty),
  USER GUIDANCE (non-empty), HISTORY (non-empty — entries joined with newlines)
- `prettyplay/llm/_request.py`: `CATEGORIES` grows `fixable`; `parse_classification_line` accepts
  it; an unrecognized label still returns None → `unparsable_classification()` → `incurable`
- Parity: absolute — one shared builder guarantees identical block order in both providers

**Entity: `SettleWindow`** (new)
- Declared `location`: `prettyplay/engine/polling/window.py`
- Facade obligation: importable from `prettyplay.engine.polling`
- Signature: `(timeout: float | None, delay: float)`; properties `timeout`, `delay`,
  `enabled -> bool`; methods `start()` (idempotent — only the first call wins) and
  `has_remaining() -> remaining: bool` (False when disabled, not started or expired; strict `<`)

**Routine: `settle`** (new)
- Declared `location`: `prettyplay/engine/polling/settle.py`
- Facade obligation: importable from `prettyplay.engine.polling`
- Signature: `(execute: Callable[[str, PageFacade], None], code: str, page: PageFacade, window: SettleWindow)`
- Re-executes the same code on pollable failures while the window remains; propagates everything
  else as-is (the identical exception object); each repetition logs `settle_retry` at INFO with
  the attempt counter and the failure text; no hook events, no LLM budget

**Entity: `StepGenerator`** (changed)
- Declared `location`: `prettyplay/engine/generator.py`
- `generate` gains `window: SettleWindow`; `regenerate` gains `recommendation: str` and
  `window: SettleWindow`; `SYSTEM_PROMPT` is replaced with the content of
  `.goga/usages/prompts/generation.md`; bounded healing on failed checks and at exhaustion;
  the raised `IncurableStepError` carries the failed step code

**Routine: `classify_step_failure` + `StepHealer`** (changed)
- Locations: `prettyplay/engine/classification.py` (`CLASSIFICATION_PROMPT` gains the `fixable`
  line — mirror the manifest's inline `classification_prompt` practice text), `prettyplay/engine/healer.py`
- `heal` gains `window: SettleWindow`; the decision table grows the `fixable` branch; the
  exhaustion rewrite carries the entry verdict and `step.code`

**Entity: `StepSteering`** (new)
- Declared `location`: `prettyplay/engine/steering/steering.py`
- Facade obligation: importable from `prettyplay.engine.steering`
- Signature: `(config: Config, provider: LLMProvider, cache: StepCache, reporter: StepReporter | None)`
  — `reporter=None` substitutes the hook-less default `StepReporter([])`
- Method: `steer(failure: IncurableStepError, identity: StepIdentity, previous_steps: list[str], page: PageFacade) -> healed: CachedStep | None`
- Owns frozen copies of `SYSTEM_PROMPT` (from `.goga/usages/prompts/generation.md`) and
  `PAGE_API_SURFACE` (from `prettyplay/driver/.usages/facade.md`)

**Entity: `StepExecutor`** (changed)
- Declared `location`: `prettyplay/executor.py`
- Constructor gains `steering: StepSteering` (between `healer` and `budgets` — the contract order)
- `execute` algorithm gains: the window (step 2), settle execution of cached code (step 3), the
  steering intercept (step 6) and `on_step_finished` (step 9); `_strict_failure` carries code

**Entity: `PrettyPlay`** (changed)
- Declared `location`: `prettyplay/scenario.py`
- `__init__` composes `StepSteering` from the runtime config, provider, cache and reporter, and
  threads it into `StepExecutor` (contract steps 5–6)

### Re-exports

- `->PrettyConfig`, `->BrowserConfig`, `->StepHooks` (facade `prettyplay/CODEMANIFEST`) —
  unchanged embeddings; already importable from `prettyplay`; no work beyond not breaking them.
- `prettyplay/driver/__init__.py` — `is_pollable_failure` joins `__all__` (the driver contract
  declares it; the polling cell imports it from `prettyplay.driver`).
- `prettyplay/engine/polling/__init__.py` (new) — exports `SettleWindow`, `settle` via `__all__`.
- `prettyplay/engine/steering/__init__.py` (new) — exports `StepSteering` via `__all__`.
- `prettyplay/__init__.py` — needs **no** change (the facade contract re-exports nothing new).

### Usages Context

- `conventions` (`.goga/usages/conventions.md`) — the project-wide mandatory standard: relative
  intra-package imports, pydantic kw_only models with empty defaults, Google docstrings, logging
  discipline, test structure mirroring the source tree. Applied in every task.
- `system_prompt` (`.goga/usages/prompts/generation.md`, project level) — the single source of
  the generation/regeneration system prompt, now with the RECOMMENDATION / USER GUIDANCE /
  HISTORY input lines and the guidance-following rule. Both referencing cells (engine, steering)
  materialize it as a frozen module constant mirroring the file verbatim (the established
  `PAGE_API_SURFACE` pattern); a runtime file read is rejected (`.goga/` is absent from an
  installed wheel), an engine-contract export of the constant is rejected (non-contractual detail).
- `playwright` (`.goga/usages/cooks/playwright.md`) — the sync-API lifecycle and — for this plan —
  the "Error kinds — the driver error surface" section: `is_pollable_failure` bases its fixed map
  on that kind table one-to-one.
- `pydantic` (`.goga/usages/cooks/pydantic.md`) — data models and TOML loading for the config task.

### Imported Usages

- `facade` (from `prettyplay/driver/.usages/facade.md`) — the page/element/dialog/frame surface
  listing. Engine (`generator.py`) mirrors it as `PAGE_API_SURFACE` already; steering gains its
  own verbatim copy. Both constants change only together with the file.
- `taxonomy` (from `prettyplay/failures/.usages/taxonomy.md`) — failure kinds, four verdict
  categories, structured render, the `code` field contract (`info.value.code` consumed
  programmatically; the render never parsed). Used by the facade and the failures task.
- `hooks` (from `prettyplay/reporting/.usages/hooks.md`) — the ten-event callback contract,
  attempt semantics ("per step or per LLM attempt — never per execution retry"), the verbatim
  error payload rule. Used by reporting, steering (`on_healed`), executor, integration tests.
- `generation`, `healing` (from `prettyplay/engine/.usages/`) — the generate/heal call shapes
  with `window`, the decision table, the bounded-healing rules, budget semantics. Used by the
  engine and executor tasks.
- `classification` (from `prettyplay/llm/.usages/classification.md`) — the four categories + the
  unrecognized→incurable fallback. Used by the llm and healer tasks.
- `configuration` (from `prettyplay/config/.usages/configuration.md`) — the env table incl. the
  three new variables; consumed by the driver cell, relevant context for the config tasks.

### Local Usages

No new files — every new functional domain already has its practice (verified current by the
design stage): `prettyplay/engine/polling/.usages/settle.md`,
`prettyplay/engine/steering/.usages/steering.md`, `prettyplay/driver/.usages/error_kinds.md`
(consumer documentation only, the accepted `budgets.md` pattern). One editorial fix is applied
during implementation:

- File path: `prettyplay/engine/steering/.usages/steering.md`
- Functional category: steering consumer doc
- Status: extends existing (editorial)
- Description: "the settle window does not re-arms inside the dialog" → "does not re-arm"
- Creation task reference: Task 12

### External Dependencies

- `playwright.sync_api.Error` (imported as `PlaywrightError`) — the driver exception type of the
  pollable map; the messages were verified against the installed Playwright driver bundle.
- `pydantic` v2 — `Config` fields, validators, `model_fields_set`, `model_copy` (unchanged usage).
- `openai` / `anthropic` SDKs — unchanged call patterns; only the request text grows blocks.
- stdlib: `time` (`monotonic`, `sleep`), `math` (`isfinite`), `tempfile`, `datetime.date`.

## Facts

- The architecture stage already created `prettyplay/engine/polling/CODEMANIFEST`,
  `prettyplay/engine/steering/CODEMANIFEST` and all three new `.usages/` files; no Python code
  exists for the two new cells yet.
- `.goga/usages/prompts/generation.md` exists and already carries the RECOMMENDATION / USER
  GUIDANCE / HISTORY input lines and the guidance-following rule; the current `SYSTEM_PROMPT`
  constant in `generator.py` predates them.
- `goga lint` passes with 10 cells, 0 errors; the design review found no contract defects — no
  CODEMANIFEST changes are needed anywhere in this plan.
- Exception identity crosses the driver-thread boundary intact (`PlaywrightWorker.run` re-raises
  `task.error` verbatim) — `is_pollable_failure` may rely on types.
- No import cycles: `engine` imports `engine.polling` only; `engine.steering` imports `engine`
  (module path `..execution`, not the package `__init__`); nothing imports `engine.steering`
  except the facade (`scenario.py`, `executor.py`).
- Tests mirror the source tree; `tests/conftest.py` provides the `_no_runtime_atexit` autouse
  fixture and the `write_pyproject` helper; the suite's fake pattern is
  `SimpleNamespace`/`mock.Mock` — no real browser, no real LLM.
- `example/conftest.py` exists for the example suite; the main gate is `pytest tests/ -x`.

## Gap Analysis

- Missing contract entities: `SettleWindow` + `settle` (no `prettyplay/engine/polling/` package),
  `StepSteering` (no `prettyplay/engine/steering/` package), `is_pollable_failure`
  (no `prettyplay/driver/errors.py`).
- Missing facade exposure: the two new packages have no `__init__.py`;
  `prettyplay/driver/__init__.py` does not export `is_pollable_failure`.
- API mismatches: `IncurableStepError.__init__` lacks `code` (4-arg today); `StepHooks` has nine
  events; `Config` lacks the three settings; the loader lacks the env names, float parsing and
  the None-skip merge clause; the LLM port/builders/`CATEGORIES` lack the three inputs and the
  `fixable` label; `generate`/`regenerate`/`heal` lack `window` (and `regenerate` —
  `recommendation`); `StepExecutor` lacks `steering`, settle wiring, the intercept and
  `on_step_finished`; `PrettyPlay` does not compose steering; `SYSTEM_PROMPT`/`CLASSIFICATION_PROMPT`
  predate the new inputs and label.
- Behavioral mismatches: the generate loop retries on AssertionError today instead of the
  bounded-healing decision table; cached-hit execution has no settle; no hook closes a step.
- Existing code that can be reused: the engine `_loop` skeleton, `_classify` (quiet
  LLM-unavailable skip), `_verdict`, the executor cycle and `_strict_failure`, the reporter emit
  fan-out, `PAGE_API_SURFACE` and its mirroring comment style, the test fakes pattern.
- Test coverage gaps: 36 planned scenarios across ~10 files, three of them new
  (`tests/driver/test_errors.py`, `tests/engine/polling/`, `tests/engine/steering/`).
- Missing visibility in workspace: the new test packages need `__init__.py`
  (`tests/engine/polling/`, `tests/engine/steering/`).

### Entity interaction (verbatim from the design)

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

Initialization order (leaves first): `failures`, `reporting` → `config`, `driver`, `llm` →
`engine/polling` → `engine` → `engine/steering` → `prettyplay` facade. Tasks follow this order.

---

## Tasks

> **Package ordering rule**: coding tasks for each package are completed before starting the next. Within each coding task, contract tests are written first (TDD workflow).

### Task 1: `IncurableStepError` gains the `code` field (failures)

The failures cell contract (`prettyplay/failures/CODEMANIFEST`) widens the mutation
`PrettyplayError::IncurableStepError(step_text, reason, error, code, verdict)`: a new `code: str`
field inserted **between** `error` and `verdict`, defaulting to `""` (conventions: empty default —
None is reserved for explicit absence, and code's absence is the empty string). The new public
property `code -> str` exposes it. The render path is untouched: `code` never enters
`render_terminal_message`, the exception message, the log record or the hook payload — it is for
programmatic consumers only (`info.value.code`, see `taxonomy` from Imports). Because `code`
defaults to `""`, every existing 4-arg raiser keeps working at this point; the raisers in other
cells start passing the code in their own tasks. `render_terminal_message`, `FailureVerdict`,
`ProductDefectError` (gains nothing) and `LLMUnavailableError` are untouched.

**Usages relevant to this task:**
- `conventions`: pydantic-unrelated class follows the existing errors.py style — Google
  docstrings, blank-line block separation; keep the existing `Exception.__init__` pattern.
- `taxonomy` (from `prettyplay/failures/.usages/taxonomy.md`): the `code` field contract —
  programmatic consumers read `info.value.code`; the render is never parsed.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/failures/test_errors.py` add — `IncurableStepError` accepts
  `code` as the 4th positional/keyword argument between `error` and `verdict`
  (`IncurableStepError("s", "r", "e", "c", None)` constructs; 4-arg legacy construction still
  works and yields `code == ""`); the `code` property exists and returns the stored value
  (expected to fail at this stage)
- [x] **Code**: in `prettyplay/failures/errors.py` — insert `code: str = ""` into
  `IncurableStepError.__init__` between `error` and `verdict`, store it as `self.code`, extend
  the class docstring Args with `code` (the step code that terminally failed; empty — unknown)
- [x] **Code**: verify the render path is untouched — `render_terminal_message` is not called
  with and does not accept `code`; `str(exc)` and `exc.message` stay exactly as before
- [x] **Interface verification**: `pytest tests/failures/test_errors.py -x` — all pass
- [x] **Logic tests**: in `tests/failures/test_errors.py` add — a code-bearing error:
  `exc.code == "def step(page): boom()"`, the code string absent from `str(exc)` and from the
  structured render; a no-code error: `exc.code == ""` and the render identical to the pre-change
  form (reason / step / error / verdict blocks unchanged); a verdict-bearing error with code:
  the verdict block renders, the code still absent
- [x] **Debugging**: `pytest tests/failures/ -x` — fix implementation code until all tests pass
- [x] **Contract re-verification**: facade accessibility `python -c "from prettyplay.failures import IncurableStepError"`;
  property set matches the contract (`step_text`, `reason`, `error`, `code`, `recommendation`, `verdict`)
- [x] **Lint**: `ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 2: `StepHooks` grows `on_step_finished` (reporting)

The reporting cell contract (`prettyplay/reporting/CODEMANIFEST`) grows the tenth event:
`on_step_finished(step_text: str, step_type: str, outcome: str)` — the closing event of every
step, fired exactly once regardless of outcome, after `on_step_passed` or after `on_step_failed`
(and after `on_step_verdict` whenever the verdict exists); `outcome` is the string `passed` or
`failed`. The base implementation is a no-op (the class is a thin callback contract — override
only the events of interest). The method is placed between `on_step_verdict` and
`on_generation_started` in the class body (the contract order); the class docstring grows to
"ten prettyplay events". Hook lifecycle events log at INFO through the reporter —
`_WARNING_EVENTS` stays `{"on_cache_skipped"}` (do not add the new event to it). The emission
itself is the executor's business (Task 13); this task only adds the callback slot and keeps the
reporter fan-out working for the new event name.

**Usages relevant to this task:**
- `hooks` (from `prettyplay/reporting/.usages/hooks.md`): the ten-event table, the closing-event
  semantics ("a step ends exactly once"), attempt semantics for `on_generation_started`.
- `conventions`: match the existing hooks.py docstring style (one-line no-op methods).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/reporting/test_hooks.py` add — `StepHooks` has an
  `on_step_finished` attribute callable with `(step_text, step_type, outcome)` returning None
  (no-op default); the method sits in the contract order (source order check:
  `on_step_verdict` before `on_step_finished` before `on_generation_started`)
- [x] **Code**: in `prettyplay/reporting/hooks.py` — add the no-op `on_step_finished` method with
  a one-line docstring ("The step ended — the closing event of every step, fired exactly once
  regardless of outcome.") and update the class docstring to ten events
- [x] **Interface verification**: `pytest tests/reporting/test_hooks.py -x` — all pass
- [x] **Logic tests**: in `tests/reporting/test_hooks.py` add — a recording `StepHooks` subclass
  receives `("on_step_finished", {...})` through `StepReporter.emit("on_step_finished",
  {"step_text": "s", "step_type": "action", "outcome": "passed"})`; the emit writes an INFO log
  record (caplog: `reclevelno == INFO`, name `prettyplay`, message `on_step_finished`)
- [x] **Debugging**: `pytest tests/reporting/ -x` — fix implementation code until all tests pass
- [x] **Contract re-verification**: facade accessibility
  `python -c "from prettyplay.reporting import StepHooks; from prettyplay import StepHooks"` (the re-export);
  the class exposes exactly the ten contract events
- [x] **Lint**: `ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 3: `Config` gains the polling and interactive settings (config models)

The config cell contract adds three validated fields to `Config`
(`prettyplay/config/models.py`, pydantic v2, kw_only, empty/neutral defaults):

```
polling_timeout: float | None = None      # validator: None or a finite >= 0 (math.isfinite) — a
                                          # negative or non-finite value (inf/nan, e.g. env "inf")
                                          # fails loudly; else "must be None or a non-negative number"
polling_delay: float = 0.5                # validator: >= 0 (finite), else "must be a non-negative number"
interactive: bool = False
```

`_ALLOWED_TEXT` (the actionable render table in the loader) grows:
`polling_timeout: "None or a non-negative number (finite)"`, `polling_delay: "a non-negative
number"`, `interactive: "a boolean"`. `polling_timeout=0` is legal — an explicit disable
equivalent to None; only negative or non-finite values fail. The defaults mean polling off,
0.5 s pause, steering off — an accidentally enabled REPL must never hang CI.

**Usages relevant to this task:**
- `pydantic` (`.goga/usages/cooks/pydantic.md`): field validators, kw_only models, empty defaults.
- `conventions`: pydantic kw_only=True models with empty defaults — the three fields follow it.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/config/test_models.py` add — `Config()` defaults:
  `polling_timeout is None`, `polling_delay == 0.5`, `interactive is False`; the three properties
  readable with the contract types (`float | None`, `float`, `bool`)
- [x] **Code**: in `prettyplay/config/models.py` — add the three fields with the validators
  (`math.isfinite` for both floats; negative → loud pydantic validation error) in the contract's
  field order (after `strict`, before `generation_attempts`); extend the class docstring Args —
  the `polling_timeout` Args line carries the sizing guidance: the window must exceed the
  facade's longest internal wait the engineer wants to absorb (Playwright expect default 5 s) —
  6.0 covers one exhausted expectation plus one re-execution; a 30 s action wait consumes any
  sane window alone, polling targets expectation/element-state races
- [x] **Code**: in `prettyplay/config/loader.py` — extend `_ALLOWED_TEXT` with the three entries
  (the validation render names setting, value, allowed form)
- [x] **Interface verification**: `pytest tests/config/test_models.py -x` — all pass
- [x] **Logic tests**: in `tests/config/test_models.py` add
  `test_config_rejects_negative_polling_values` (parametrized): `pytest.raises(ValidationError)`
  for `Config(polling_timeout=-1.0)` and `Config(polling_delay=-0.5)` — the field name appears in
  the error; boundary row: `Config(polling_timeout=0.0, polling_delay=0)` is valid (explicit
  disable and zero pause stay legal); non-finite row: `Config(polling_timeout=float("inf"))`
  raises (an infinite settle window is never constructible)
- [x] **Debugging**: `pytest tests/config/ -x` — fix implementation code until all tests pass
- [x] **Contract re-verification**: facade accessibility
  `python -c "from prettyplay.config import Config"`; the layered-merge participants unchanged
- [x] **Lint**: `ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 4: `load_config` parses the three settings — env floats/bools and the None-skip merge (config loader)

The loader contract (`prettyplay/config/loader.py`, signature unchanged) grows: `_ENV_NAMES`
adds `polling_timeout → PRETTYPLAY_POLLING_TIMEOUT`, `polling_delay → PRETTYPLAY_POLLING_DELAY`,
`interactive → PRETTYPLAY_INTERACTIVE`; `_parse_env_scalar` gains
`_FLOAT_ENV_SETTINGS = {"polling_timeout", "polling_delay"}` — `float(raw)` with the loud
`ConfigurationError(f"{setting}: received {raw!r} — allowed: a decimal float")` on `ValueError`;
`interactive` joins `_BOOL_ENV_SETTINGS` (true/false/1/0 case-insensitive). The programmatic
merge (`_apply_overrides`) gains one clause — `if value is None: continue` — placed **before**
the string-emptiness check: `PrettyConfig(polling_timeout=None)` is skipped (indistinguishable
from unset), while `PrettyConfig(polling_timeout=0.0)` and `PrettyConfig(interactive=False)`
participate (explicit disable/off wins over the file layer — bools have no "empty" form).

**Usages relevant to this task:**
- `configuration` (`prettyplay/config/.usages/configuration.md`): the env table incl. the three
  new variables and the merge rules — keep the documented table true.
- `conventions`: loud actionable errors naming setting, received value, accepted form.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests**: in `tests/config/test_loader.py` add — the loader accepts env
  `PRETTYPLAY_POLLING_TIMEOUT` / `PRETTYPLAY_POLLING_DELAY` / `PRETTYPLAY_INTERACTIVE` (expected
  to fail at this stage)
- [x] **Code**: `_ENV_NAMES` += the three settings; `_FLOAT_ENV_SETTINGS = {"polling_timeout",
  "polling_delay"}` with `float(raw)` parsing and the loud failure; `interactive` added to
  `_BOOL_ENV_SETTINGS`
- [x] **Code**: `_apply_overrides` — insert `if value is None: continue` before the
  string-emptiness check (binding decision 6 of the design; keep the emptiness clause after it)
- [x] **Interface verification**: `pytest tests/config/test_loader.py -x` — all pass
- [x] **Logic tests**: in `tests/config/test_loader.py` add:
  - `test_load_config_env_parses_polling_and_interactive`: `write_pyproject()` empty section;
    env `PRETTYPLAY_POLLING_TIMEOUT=8`, `PRETTYPLAY_POLLING_DELAY=0.25`,
    `PRETTYPLAY_INTERACTIVE=true` → `config.polling_timeout == 8.0`,
    `config.polling_delay == 0.25`, `config.interactive is True`; boundary row (second case):
    env `PRETTYPLAY_POLLING_TIMEOUT=0` → `config.polling_timeout == 0.0` — the explicit disable
    parses to the float zero, not None
  - `test_load_config_env_rejects_unparseable_float` (parametrized `soon` | `inf`): `soon` →
    `ConfigurationError` with `polling_timeout`, `received 'soon'`, `a decimal float`; `inf` →
    parses to `float("inf")` then the field validator rejects it — loud failure naming
    `polling_timeout` and the received value (no infinite settle window is ever constructible)
  - `test_explicit_zero_and_false_override_the_file_layer`:
    `write_pyproject(polling_timeout=8.0, interactive=True)` +
    `overrides=PrettyConfig(polling_timeout=0.0, interactive=False)` →
    `config.polling_timeout == 0.0`, `config.interactive is False`
  - `test_explicit_none_polling_timeout_is_indistinguishable_from_unset`:
    `write_pyproject(polling_timeout=8.0)` + `overrides=PrettyConfig(polling_timeout=None)` →
    `config.polling_timeout == 8.0` (the None is skipped by the merge)
- [x] **Debugging**: `pytest tests/config/ -x` — fix implementation code until all tests pass
- [x] **Contract re-verification**: an env override exists for every setting (spot-check
  `PRETTYPLAY_STRICT` still works); a raw pydantic ValidationError still never leaves the loader
- [x] **Lint**: `ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 5: `is_pollable_failure` — the fixed pollable map (driver)

The driver cell contract declares a new Routine at `prettyplay/driver/errors.py`
(`is_pollable_failure(exc: Exception) -> pollable: bool`) — the single recognition point deciding
which failed step-code exceptions a settle window may absorb. Pure function: no state, no I/O, no
settings, no LLM; deterministic on the exception alone; the map is fixed in code. Exception
identity/type survives the driver-thread boundary intact (`PlaywrightWorker.run` re-raises
`task.error` verbatim), so playwright `Error` instances and facade `AssertionError`s arrive with
their types intact. Algorithm (verbatim from the design; binding decision 7/9):

```
1. text = str(exc)
2. IF "strict mode violation" in text: RETURN False        # locator ambiguity — deterministic
   (checked before the AssertionError rule so an ambiguity-styled AssertionError is also refused)
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

The detach family is exactly the verified set above — the draft's `element has been detached`
matches no real Playwright message and is **not** implemented. `prettyplay/driver/__init__.py`
exports the function via `__all__` (the polling cell imports it from this facade).

**Usages relevant to this task:**
- `playwright` (`.goga/usages/cooks/playwright.md`, "Error kinds — the driver error surface"
  section): the map mirrors the documented kind table one-to-one — timeout, element state,
  navigation/context pollable; ambiguity, Python-level and unrecognized not.
- `error_kinds` (`prettyplay/driver/.usages/error_kinds.md`): the consumer-facing table of the
  same map (already current — keep the code and the table consistent).
- `conventions`: `from playwright.sync_api import Error as PlaywrightError`; module docstring;
  Google docstring on the function.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests**: create `tests/driver/test_errors.py` — `is_pollable_failure` is
  importable from `prettyplay.driver` (the facade export) and callable with one exception
  argument returning a bool (expected to fail at this stage)
- [ ] **Code**: create `prettyplay/driver/errors.py` implementing the algorithm above
  (ambiguity substring first, AssertionError second, `PlaywrightError` type + lowercased pattern
  set third, conservative False)
- [ ] **Code**: extend `prettyplay/driver/__init__.py` — import `is_pollable_failure` and add it
  to `__all__`
- [ ] **Interface verification**: `pytest tests/driver/test_errors.py -x` — all pass
- [ ] **Logic tests**: in `tests/driver/test_errors.py` add `test_is_pollable_failure_map`
  (parametrized table — the exact messages):
  `PlaywrightError("Locator.click: Timeout 10000ms exceeded.")` → True;
  `PlaywrightError("element is not visible")` → True;
  `PlaywrightError("element is not enabled")` → True;
  `PlaywrightError("Execution context was destroyed, most likely…")` → True;
  `PlaywrightError("Target closed")` → True;
  `PlaywrightError("Frame has been detached.")` → True;
  `PlaywrightError("… was interrupted by another navigation to …")` → True;
  `AssertionError("Locator expected to be visible")` → True;
  `PlaywrightError("strict mode violation: locator resolved to 2 elements")` → False;
  `AssertionError("strict mode violation: locator resolved to 2 elements")` → False;
  `NameError("name 'paeg' is not defined")` → False;
  `PlaywrightError("something never seen before")` → False
- [ ] **Debugging**: `pytest tests/driver/ -x` — fix implementation code until all tests pass
- [ ] **Contract re-verification**: facade accessibility
  `python -c "from prettyplay.driver import is_pollable_failure"`; a non-playwright exception
  with a timeout-looking message stays False (type + pattern, never pattern alone)
- [ ] **Lint**: `ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 6: the LLM port grows `recommendation`/`guidance`/`guidance_history` and the `fixable` label (llm)

The llm cell contract widens the port and the label set. `LLMProvider.generate_step_code`
(`prettyplay/llm/provider.py`) gains `recommendation: str | None`, `guidance: str | None`,
`guidance_history: list[str]` — no defaults; callers pass explicitly, uniform with
`existing_code`/`error`. Both SDK implementations (`openai_provider.py`, `anthropic_provider.py`)
forward the three verbatim to the shared `_request.build_fields_text` — parity is structural (one
shared builder; nothing provider-specific sees them). `build_fields_text`
(`prettyplay/llm/_request.py`) renders, in the fixed order: STEP, PREVIOUS STEPS, PAGE SNAPSHOT,
PAGE API, USER INSTRUCTIONS (non-empty), CODE (`existing_code is not None`), ERROR
(`error is not None`), RECOMMENDATION (non-empty), USER GUIDANCE (non-empty), HISTORY (non-empty
— entries joined with newlines). `CATEGORIES` (`prettyplay/llm/_request.py`) grows `fixable`;
`parse_classification_line` accepts it; an unrecognized label still returns None →
`unparsable_classification()` → category `incurable` — an unknown verdict never grants a
regeneration. The new inputs take no part in step addressing (they never reach the cache key —
addressing lives in `StepIdentity`/`StepCache` from the step triple only).

**Usages relevant to this task:**
- `classification` (`prettyplay/llm/.usages/classification.md`): the four categories and the
  unrecognized→incurable fallback.
- `conventions`: keep the `# noqa: PLR0913, PLR0917` pattern on the widened signatures — the
  parameters mirror the fixed port signature.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests**: in `tests/llm/test_provider.py` (or the existing per-provider test
  files) add — the protocol signature accepts the three new keyword arguments on both
  `OpenAIProvider` and `AnthropicProvider` (inspect signatures or call with a mocked SDK);
  `CATEGORIES`-facing models importable (expected to fail at this stage)
- [ ] **Code**: `prettyplay/llm/_request.py` — `build_fields_text` gains the three parameters
  and appends the three optional blocks after ERROR in the fixed order (RECOMMENDATION, USER
  GUIDANCE, HISTORY — history entries joined with newlines; a non-empty input renders its named
  block, empty/None renders nothing)
- [ ] **Code**: `prettyplay/llm/provider.py` — widen the port protocol signature; docstrings for
  the three parameters (RECOMMENDATION — the diagnosis that preceded the regeneration, rendered
  after CODE and ERROR; USER GUIDANCE — the steering message; HISTORY — the accumulated turns)
- [ ] **Code**: `prettyplay/llm/openai_provider.py` and `prettyplay/llm/anthropic_provider.py` —
  accept the three parameters and forward verbatim to the shared builder (both call sites stay
  byte-identical in structure)
- [ ] **Code**: `prettyplay/llm/_request.py` — `CATEGORIES` grows `fixable`
  (`{"rot", "product_defect", "fixable", "incurable"}`); `parse_classification_line` accepts the
  label (no other change — the unrecognized fallback stays)
- [ ] **Code**: `prettyplay/llm/models.py` — update the `FailureClassification` class docstring:
  the category Attributes line grows the four-label set (rot, product_defect, fixable, incurable —
  the fixable gloss mirrors the contract annotation: the step code is at fault while the intent
  stays satisfiable)
- [ ] **Interface verification**: `pytest tests/llm/ -x` — all pass (existing tests updated to
  the new explicit-kwargs call shape where they call the port directly)
- [ ] **Logic tests**: add
  - `test_build_fields_renders_new_blocks_in_fixed_order` (in `tests/llm/test_request.py`):
    direct call with all blocks non-empty — `user_instructions="style"`, `existing_code="old"`,
    `error="err"`, `recommendation="rec"`, `guidance="do this"`,
    `guidance_history=["h1", "h2"]` → assert
    `text.index("PAGE API:") < text.index("USER INSTRUCTIONS:") < text.index("CODE:") <
    text.index("ERROR:") < text.index("RECOMMENDATION:") < text.index("USER GUIDANCE:") <
    text.index("HISTORY:")` and `"HISTORY:\nh1\nh2" in text`
  - `test_parse_classification_accepts_fixable_label` (in `tests/llm/test_request.py`):
    `parse_classification_line("fixable | ambiguous locator | use role locator")` returns
    `("fixable", "ambiguous locator", "use role locator")`; an unrecognized label still returns
    None and `unparsable_classification()["category"] == "incurable"`
  - parity: both providers forward the three inputs to the same builder output — one test
    calling each provider's request-building path with identical inputs yields identical user
    text (mocked SDK clients)
- [ ] **Debugging**: `pytest tests/llm/ -x` — fix implementation code until all tests pass
- [ ] **Contract re-verification**: both providers expose the identical widened signature
  (parity); the fence unwrapping and error mapping are untouched
- [ ] **Lint**: `ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 7: the `engine/polling` cell skeleton and facade (infrastructure)

The polling cell is new Python-side: its CODEMANIFEST and `.usages/settle.md` already exist. The
cell imports `PageFacade` and `is_pollable_failure` from `prettyplay/driver` (available after
Task 5). This task creates the package skeleton so the two entities of Tasks 8–9 have their
structure and facade in place: `prettyplay/engine/polling/__init__.py` (the facade exposing
`SettleWindow` and `settle` through `__all__`), plus module skeletons `window.py` and `settle.py`
with correct imports, docstrings and signature-level stubs (raising `NotImplementedError` in the
bodies) — the implementations land in the next two tasks. Relative imports per conventions
(`from ...driver import PageFacade, is_pollable_failure`; `from .window import SettleWindow`).

**Usages relevant to this task:**
- `conventions`: a cell is a Python package; the facade `__init__.py` exposes the contract API
  through `__all__`; relative intra-package imports; module docstrings.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] Create `prettyplay/engine/polling/window.py` — module docstring + the `SettleWindow` class
  skeleton: `__init__(self, timeout: float | None, delay: float)` storing the two public
  attributes; property/method stubs (`enabled`, `start`, `has_remaining`) raising
  `NotImplementedError`
- [ ] Create `prettyplay/engine/polling/settle.py` — module docstring + the `settle` function
  skeleton with the full contract signature
  (`execute: Callable[[str, PageFacade], None], code: str, page: PageFacade, window: SettleWindow`)
  raising `NotImplementedError`; the needed imports (`is_pollable_failure`, `PageFacade`,
  logger `prettyplay`)
- [ ] Create `prettyplay/engine/polling/__init__.py` — docstring ("Facade of the
  prettyplay.engine.polling cell…"), imports and `__all__ = ["SettleWindow", "settle"]`
- [ ] Verify facade accessibility: `python -c "from prettyplay.engine.polling import SettleWindow, settle"`
- [ ] Lint: `ruff check prettyplay/` — fix formatting if necessary

### Task 8: `SettleWindow` — the settle horizon (engine/polling)

The settle horizon of one step execution: when re-executing the same step code may still help
and how long to pause between re-executions. Contract: `SettleWindow(timeout: float | None,
delay: float)` at `prettyplay/engine/polling/window.py`; public attributes/properties `timeout`,
`delay`, `enabled -> bool`; methods `start()` and `has_remaining()`. Algorithm (verbatim from the
design — pure time bookkeeping on `time.monotonic()`, no I/O, no logging):

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

Semantics: `timeout=0` is an explicit disable, uniform with None; expiry is checked before each
repetition only — the window never kills a running attempt ("the first execution may consume the
whole window"); strict `<` at the boundary. Edge cases: `delay=0` → `time.sleep(0)` later —
repetition without a pause (the window does not care). The `Config` validators (Task 3) already
guarantee finite non-negative inputs — the window trusts the validated config.

**Usages relevant to this task:**
- `conventions`: type hints mandatory; Google docstrings; monkeypatch
  `prettyplay.engine.polling.window.time` in tests (a monotonic counter) — no real sleeps.
- `settle` (`prettyplay/engine/polling/.usages/settle.md`): the consumer doc of the window —
  the code example matches these final signatures.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests**: create `tests/engine/polling/` package (`__init__.py` + test module) —
  `SettleWindow` importable from `prettyplay.engine.polling`; constructs with
  `(timeout, delay)`; exposes `timeout`/`delay`/`enabled` and the two methods (expected to fail
  at this stage)
- [ ] **Code**: implement `SettleWindow` in `prettyplay/engine/polling/window.py` per the
  algorithm above (monotonic clock; idempotent start; strict `<`)
- [ ] **Interface verification**: `pytest tests/engine/polling/ -x` — all pass
- [ ] **Logic tests**: add (monkeypatched monotonic clock)
  - `test_window_state_table` (parametrized): `SettleWindow(None, 0.5)` — `enabled` False,
    `has_remaining` False before and after `start`; `SettleWindow(0, 0.5)` — `enabled` False
    (explicit disable); `SettleWindow(5.0, 0.5)` — not started → `has_remaining` False; started,
    monotonic+2 → True; monotonic+5 → False (the exact boundary — strict `<`); monotonic+6 →
    False (expired)
  - `test_window_start_is_idempotent`: monkeypatched monotonic returning 1.0 then 9.0;
    `start(); start()` → `_started_at == 1.0` — the second call never shifts the window start
- [ ] **Debugging**: `pytest tests/engine/polling/ -x` — fix implementation code until all tests pass
- [ ] **Contract re-verification**: facade accessibility
  `python -c "from prettyplay.engine.polling import SettleWindow"`; property/method set matches
  the contract
- [ ] **Lint**: `ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 9: `settle` — the re-execution loop (engine/polling)

Execute step code under the settle window: absorb transient page-state failures by re-executing
the same code, propagate everything else as-is. Contract: `settle(execute, code, page, window)`
at `prettyplay/engine/polling/settle.py` — `execute` is `run_step_code` passed by the caller
(`Callable[[str, PageFacade], None]`). Algorithm (verbatim from the design):

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

Requirements: each repetition writes a `settle_retry` INFO record to the logger `prettyplay`
with the attempt counter (binding decision 5: the 1-based ordinal of the failed execution that
triggers the repetition) and the failure text; **no hook events** — polling imports no reporting
type (its schema dependency is driver only); no LLM budget (no budgets object exists in this
cell). Constraints: never swallow, translate or retry a non-pollable failure — the identical
exception object propagates; `BaseException` (KeyboardInterrupt, SIGINT) is never caught
(`except Exception` only). Edge cases: disabled window (`timeout` None or 0) → exactly one
execution, the failure propagates immediately; pollable failure at window end → propagates; the
window never kills a running attempt (`has_remaining` checked only before a repetition).

**Usages relevant to this task:**
- `conventions`: logger `prettyplay`, lowercase event names, contextual metadata via `extra`;
  tests use `SettleWindow(timeout=…, delay=0)` and monkeypatched time — no real sleeps beyond
  `sleep(0)`.
- `playwright`/`error_kinds` (from the driver): `is_pollable_failure` is the recognition point —
  settle never re-implements matching.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests**: in the `tests/engine/polling/` package — `settle` importable and
  callable with the four contract parameters (expected to fail at this stage)
- [ ] **Code**: implement `settle` in `prettyplay/engine/polling/settle.py` per the algorithm
  above — `window.start()` first, the loop catching `Exception` only, the three-part gate
  (enabled + pollable + has_remaining), the `settle_retry` INFO record, `time.sleep(window.delay)`,
  `raise` of the original object otherwise
- [ ] **Interface verification**: `pytest tests/engine/polling/ -x` — all pass
- [ ] **Logic tests**: add (fakes: `FakePage = SimpleNamespace(aria_snapshot=…, screenshot=…)`,
  `PlaywrightError("Timeout 10000ms exceeded")` as the pollable failure)
  - `test_settle_retries_pollable_failure_until_success`: `window = SettleWindow(5.0, 0)`; a fake
    `execute` raising the timeout on the first two calls, succeeding on the third → no exception;
    `execute.call_count == 3`; caplog has two INFO records named `settle_retry` with attempt 1
    and 2
  - `test_settle_passes_code_and_page_to_execute`: `window = SettleWindow(None, 0.5)`;
    `execute = mock.Mock()` → `settle(execute, "CODE", fake_page, window)` →
    `execute.assert_called_once_with("CODE", fake_page)`
  - `test_settle_propagates_non_pollable_failure_immediately` (negative):
    `window = SettleWindow(5.0, 0)`; `execute` raises
    `PlaywrightError("strict mode violation: locator resolved to 2 elements")` → the **same
    exception object** propagates (`info.value is original`); `execute.call_count == 1`; no
    `settle_retry` records
  - `test_settle_disabled_window_single_execution` (edge): `SettleWindow(None, 0)`; `execute`
    raises a pollable timeout forever → `execute.call_count == 1`; the exception propagates; no
    `settle_retry` records
- [ ] **Debugging**: `pytest tests/engine/polling/ -x` — fix implementation code until all tests pass
- [ ] **Contract re-verification**: facade accessibility
  `python -c "from prettyplay.engine.polling import settle"`; a `KeyboardInterrupt` raised by
  `execute` escapes uncaught (BaseException is never intercepted)
- [ ] **Lint**: `ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 10: `StepGenerator` — window threading, bounded healing and the code field (engine)

The generation engine (`prettyplay/engine/generator.py`) takes the largest behavioral change.
Contract: `generate` gains `window: SettleWindow`; `regenerate` gains `recommendation: str` and
`window: SettleWindow`; every candidate execution runs under `settle` with the window; the
failed-check path becomes the bounded-healing decision table; every generation-path
`IncurableStepError` carries the failed step code (the last candidate); `SYSTEM_PROMPT` is
replaced with the content of `.goga/usages/prompts/generation.md`.

The generate loop (verbatim from the design):

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
       # kind-authored reason (binding decision 13): an AssertionError repeat —
       #   "candidate check failed — <first line>"; any other failure —
       #   "candidate failed — <first line>"; the quiet-skip path (final is None,
       #   LLM unavailable) keeps "candidate check failed — <first line>" — contract wording
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

`_funded_regeneration(...)` (binding decision 3): ONE attempt — `attempt += 1`, emit
`on_generation_started` (it is an LLM attempt), one provider request carrying
`existing_code`/`error`/`recommendation`, one `settle` execution under the same window; success →
`CachedStep` + `cache.save` + return; failure of the **execution** — never of the provider
request, whose `LLMUnavailableError` propagates immediately (no retry, no final classification) —
returns None together with the failed code and the `format_step_error` text for the caller's
terminal handling. The funded regenerations are single inline requests, NOT calls to
`regenerate` (whose loop retries).

The regenerate loop (healing pool): the same loop with `spend = try_healing`, every request
carrying `existing_code`/`error`/`recommendation`; **every** failed attempt — a failed check
included — takes the retry branch with the fresh error and snapshot while attempts remain (no
per-attempt classification inside the loop; the entry classification already guards
anti-masking); exhaustion raises `IncurableStepError(step_text, "healing attempt budget
exhausted", error, code=last candidate, verdict=None)` — no classification; the calling healer
attaches the entry verdict (binding decision 1; Task 11 wires the rewrite). `regenerate` output:
stored `CachedStep` | `IncurableStepError(verdict=None)` | `LLMUnavailableError`.

`SYSTEM_PROMPT`: replace the constant body with the prompt text of
`.goga/usages/prompts/generation.md` (the section after the `---` separator) — it adds the
RECOMMENDATION / USER GUIDANCE / HISTORY input lines and the rule "RECOMMENDATION and USER
GUIDANCE carry the diagnosis and the engineer's intent — follow them when they conflict with your
first instinct"; keep the frozen-constant comment style (mirrors the file verbatim; changes only
together with it — the `PAGE_API_SURFACE` pattern). Binding decision 2: no runtime read of
`.goga/`. Plain generation requests pass `recommendation=None, guidance=None,
guidance_history=[]` (no RECOMMENDATION/GUIDANCE/HISTORY blocks). `attempt` counts LLM requests
of the pool run: loop attempts + the funded regeneration(s). The settle window is shared: the
funded regeneration runs under the same `window` (the same step execution).

**Usages relevant to this task:**
- `generation` (`prettyplay/engine/.usages/generation.md`): the generate call shape with
  `window`, the decision table, the bounded-healing rules, budget semantics.
- `system_prompt` (`.goga/usages/prompts/generation.md`): the single source mirrored into the
  frozen constant.
- `facade` (from `prettyplay/driver/.usages/facade.md`): `PAGE_API_SURFACE` stays the verbatim
  mirror — unchanged in this task.
- `hooks` (from `prettyplay/reporting/.usages/hooks.md`): `on_generation_started` fires once per
  LLM attempt regardless of settle re-executions inside it.
- `conventions`: recording fakes pattern for tests; `# noqa` on the widened fixed signatures.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests**: in `tests/engine/test_generator.py` add — `generate` and `regenerate`
  accept `window` (`regenerate` also `recommendation`, positioned per the contract) — signature
  shape via direct calls with fakes (expected to fail at this stage)
- [ ] **Code**: `SYSTEM_PROMPT` — replace the constant with the generation.md prompt text
  (frozen mirror, comment updated)
- [ ] **Code**: widen `generate`/`regenerate` signatures and thread `window` into `_loop`; every
  candidate execution goes through `settle(run_step_code, code, page, window)`; plain-generation
  requests pass `recommendation=None, guidance=None, guidance_history=[]`
- [ ] **Code**: implement the failed-check decision table (classify → product_defect /
  incurable / bounded healing) with the code field on every raise; `verdict is None` (quiet
  skip) → `IncurableStepError(reason="candidate check failed — <first line>", verdict=None)`
- [ ] **Code**: implement `_funded_regeneration` (one request funded by an explicit
  `try_healing` check; `on_generation_started` fires; provider `LLMUnavailableError` propagates
  immediately; execution failure returns the failed code + formatted error to the caller) and
  wire it into the failed-check and exhaustion rot/fixable branches
- [ ] **Code**: implement the exhaustion path per the algorithm (incl. the no-error first
  candidate case `code=""`); the kind-authored repeat-failure reason (AssertionError repeat —
  "candidate check failed — <first line>"; other failure — "candidate failed — <first line>";
  quiet skip — the contract wording)
- [ ] **Code**: regenerate loop — healing pool spend, every failed attempt retries (failed
  checks included), exhaustion raises `IncurableStepError(..., code=last candidate,
  verdict=None)` with no classification
- [ ] **Interface verification**: `pytest tests/engine/test_generator.py -x` — all pass
- [ ] **Logic tests**: in `tests/engine/test_generator.py` add (recording provider fake;
  `RunBudgets`; `FakePage`; `SettleWindow(None, 0.5)` unless stated)
  - `test_generate_failed_check_rot_grants_one_funded_regeneration`: budgets
    `RunBudgets(generation_limit=3, healing_limit=2)`; first candidate raises
    `AssertionError("button is hidden")`; classification scripted `rot` with recommendation
    "retry with an id locator"; the funded regeneration returns working code → the step is
    returned; assertions: `provider.generate_step_code.call_count == 2`; second call
    `kwargs["recommendation"] == "retry with an id locator"`, `kwargs["existing_code"]` is the
    failed candidate, `kwargs["error"] == "button is hidden"`; `on_generation_started` emitted
    twice (attempts 1 and 2); `cache.save` called once with the healed code;
    `on_healing_started` never emitted
  - `test_exhaustion_rot_verdict_grants_extra_regeneration_and_repeat_failure_is_terminal`:
    generation budget 1; candidate always fails with `TypeError("bad code")`; classification
    scripted `rot`; the funded regeneration also fails → `pytest.raises(IncurableStepError)`
    with `.verdict.category == "rot"`, `.reason` naming the exhausted generation pool,
    `.code` == the funded candidate; `provider.generate_step_code.call_count == 2` (1 loop +
    1 funded; no third — no reclassification)
  - `test_generate_failed_check_refused_funding_is_terminal` (negative):
    `RunBudgets(generation_limit=3, healing_limit=0)`; failed check; classification `rot` →
    `IncurableStepError` with `.reason == "healing attempt budget exhausted"`,
    `.verdict.category == "rot"`; `provider.generate_step_code.call_count == 1` (no unfunded
    request)
  - `test_on_generation_started_fires_once_despite_settle_retries` (edge): candidate fails
    twice with a pollable `PlaywrightError("Timeout 10000ms exceeded")` then succeeds;
    `window = SettleWindow(10.0, 0)` → `on_generation_started` emitted exactly once; two
    `settle_retry` log records; budgets spent exactly one generation attempt
- [ ] **Debugging**: `pytest tests/engine/ -x` — fix implementation code until all tests pass
  (do NOT fix test code)
- [ ] **Contract re-verification**: anti-masking preserved (`product_defect` never regenerates);
  budget invariant (a failing assertion costs at most one classification + one funded
  regeneration + one final classification); `code` on every generation-path terminal error =
  the last candidate; provider request failures surface as `LLMUnavailableError` immediately
- [ ] **Lint**: `ruff check prettyplay/ tests/` — fix formatting, apply decomposition if necessary

### Task 11: `StepHealer` — the window, the `fixable` branch and the code rewrite (engine)

The healing engine (`prettyplay/engine/healer.py`) and the classification prompt
(`prettyplay/engine/classification.py`). Contract: `heal(step, error, previous_steps, page,
window)`; the uniform decision table on the entry classification — `product_defect` raises
`ProductDefectError`; `incurable` raises `IncurableStepError(code=step.code)`; **rot and
fixable** regenerate via `generator.regenerate(..., existing_code=step.code, error,
recommendation=classification.recommendation, window)`. Algorithm (verbatim):

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

Binding decision 1: `regenerate` raises budget-exhaustion with `verdict=None` and the healer
rewrites the error carrying **its own entry verdict** and `step.code` — never add a verdict
parameter to `regenerate`. In `classification.py`, `CLASSIFICATION_PROMPT` gains the `fixable`
line in the category list (mirror the manifest's inline `classification_prompt` practice text —
the four labels with the fixable gloss: "the step code is at fault (an ambiguous or wrong locator
or strategy) while the intent stays satisfiable; regeneration for the same intent can help").
Edge case: a failed check inside the regeneration loop now retries instead of classifying — the
entry classification already guards the anti-masking.

**Usages relevant to this task:**
- `healing` (`prettyplay/engine/.usages/healing.md`): the heal call shape with `window`, the
  decision table, the exhaustion rewrite rule.
- `classification` (from `prettyplay/llm/.usages/classification.md`): the four categories —
  `on_healing_started` payload and the prompt both carry `fixable`.
- `taxonomy` (from `prettyplay/failures/.usages/taxonomy.md`): the code field on the rewrite.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests**: in `tests/engine/test_healer.py` add — `heal` accepts the `window`
  parameter (expected to fail at this stage); `CLASSIFICATION_PROMPT` names all four labels
- [ ] **Code**: `prettyplay/engine/classification.py` — add the `fixable` line to
  `CLASSIFICATION_PROMPT`'s category list
- [ ] **Code**: `prettyplay/engine/healer.py` — widen `heal` with `window: SettleWindow`; the
  decision table with the fixable branch folded into rot; thread `recommendation` and `window`
  into `generator.regenerate`; the exhaustion rewrite per the algorithm (`from inner`,
  `code=step.code`, the entry verdict); `code=step.code` on the incurable raise
- [ ] **Interface verification**: `pytest tests/engine/test_healer.py tests/engine/test_classification.py -x` — all pass
- [ ] **Logic tests**: in `tests/engine/test_healer.py` add
  `test_heal_fixable_category_regenerates_with_recommendation`: classification scripted
  `fixable` (recommendation "use an unambiguous role locator"); `CachedStep` with `code="old"`;
  `healer.heal(step, error="strict mode violation: locator resolved to 2 elements", [],
  fake_page, SettleWindow(None, 0.5))` → `regenerate` called with
  `existing_code="old"`, `error=…`, `recommendation="use an unambiguous role locator"`,
  `window=window`; `on_healing_started` payload `category == "fixable"`; `on_healed` emitted;
  the returned step is the regenerated one. Plus the exhaustion-rewrite case: `regenerate`
  scripted to raise `IncurableStepError(reason="healing attempt budget exhausted", verdict=None)`
  → the raised error carries the **entry** verdict, `code == "old"`, the inner reason, and
  `__cause__` is the inner error
- [ ] **Debugging**: `pytest tests/engine/ -x` — fix implementation code until all tests pass
- [ ] **Contract re-verification**: anti-masking (a classified product defect always raises);
  the healed code replaces the cache only after a successful execution (the engine stores);
  every verdict produced on these paths fully reaches the raised error
- [ ] **Lint**: `ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 12: `StepSteering` — the interactive steering REPL (engine/steering)

The steering cell is new Python-side (CODEMANIFEST and `.usages/steering.md` exist). One entity:
`StepSteering(config, provider, cache, reporter)` at `prettyplay/engine/steering/steering.py`
with the single method `steer(failure, identity, previous_steps, page) -> healed: CachedStep |
None`. Construction: keep config, provider, cache; `reporter is None` → substitute the hook-less
default reporter `StepReporter([])` (binding decision 12). The cell holds its own frozen copies
of `SYSTEM_PROMPT` (mirroring `.goga/usages/prompts/generation.md` verbatim) and
`PAGE_API_SURFACE` (mirroring `prettyplay/driver/.usages/facade.md` verbatim) — the same frozen
constant pattern as the engine, duplicated because the steering cell imports neither constant
from the engine contract (binding decision 2). Imports: `run_step_code` from `..execution` (the
module path, not the engine package `__init__`); types from the neighboring cells via relative
paths (`from ...cache import CachedStep`, etc. — no import cycle: nothing imports
`engine.steering` except the facade).

Algorithm (verbatim from the design):

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

Binding decisions baked in: steering requests pass `recommendation=None` (decision 4 — the
verdict diagnosis is banner-only; the live guidance replaces it); a blank/whitespace-only line is
a re-prompt (decision 10 — no log record, no LLM request, no history entry); the executions are
bare `run_step_code` (no settle — "the window never re-arms inside the dialog"); no
`RunBudgets` object exists in this class — budgets are structurally unspendable. Presentation
constants (resolved ADR items): the snapshot fragment is the first 20 lines of
`page.aria_snapshot()`; screenshots (banner and command) write a full PNG to the `tempfile`
system directory as `prettyplay-steering-*.png` and print the path; a history line is
`f"{guidance} => {first line of str(outcome)}"`. SIGINT policy: `KeyboardInterrupt` is
`BaseException` — it escapes `steer` directly (never swallowed into a loop or a heal); the
executor's `finally` still closes the step. Every exit path heals or returns None — no
`Exception` ever escapes `steer`.

Also apply the editorial fix to the cell's practice file: `prettyplay/engine/steering/.usages/steering.md`
— "the settle window does not re-arms inside the dialog" → "does not re-arm" (grammar defect
introduced by the architecture stage; the design instructs applying it during implementation).

**Usages relevant to this task:**
- `system_prompt` (`.goga/usages/prompts/generation.md`): the frozen constant mirror.
- `facade` (from `prettyplay/driver/.usages/facade.md`): the `PAGE_API_SURFACE` mirror.
- `hooks` (from `prettyplay/reporting/.usages/hooks.md`): `on_healed` — "an interactively healed
  step reports here too".
- `steering` (`prettyplay/engine/steering/.usages/steering.md`): the consumer doc of the REPL —
  current with the contract; this task applies the one editorial fix.
- `conventions`: tests monkeypatch `builtins.input` (a scripted answer queue); temp files via
  `tmp_path`; the recording fakes pattern.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests**: create `tests/engine/steering/` package (`__init__.py` + test module) —
  `StepSteering` importable from `prettyplay.engine.steering`; constructs with the four contract
  parameters (`reporter=None` accepted); `steer` callable with the four parameters (expected to
  fail at this stage)
- [ ] **Code**: create `prettyplay/engine/steering/steering.py` — the frozen `SYSTEM_PROMPT` and
  `PAGE_API_SURFACE` copies (mirroring comments), the constructor with the `reporter=None` →
  `StepReporter([])` substitution, and `steer` per the algorithm (banner, guarded page
  interactions, the input loop, blank re-prompt, local commands, the guidance request, the bare
  execution, the write-back + `on_healed`, the red-turn history, the exit paths)
- [ ] **Code**: create `prettyplay/engine/steering/__init__.py` — docstring, import,
  `__all__ = ["StepSteering"]`
- [ ] **Editorial**: in `prettyplay/engine/steering/.usages/steering.md` fix "does not re-arms"
  → "does not re-arm"
- [ ] **Interface verification**: `pytest tests/engine/steering/ -x` — all pass
- [ ] **Logic tests**: in the steering test module add (steering tests monkeypatch
  `builtins.input` with a scripted answer queue; `FakePage`; recording provider/cache/reporter
  fakes; failure = `IncurableStepError("click Pay", "budget exhausted", "Timeout…", code="old",
  verdict=None)` unless stated)
  - `test_steer_green_turn_writes_back_and_reports_healed`: `input` scripted
    `["dismiss the modal first"]`; provider returns working code; `run_step_code` monkeypatched
    to succeed → the returned step's code is the generated code; `cache.save` called once with
    the identity; `on_healed` payload explanation mentions the interactive healing; provider
    `kwargs["guidance"] == "dismiss the modal first"`, `kwargs["recommendation"] is None`,
    `kwargs["existing_code"] == "old"`, `kwargs["error"] == "Timeout…"`
  - `test_steer_red_turn_appends_history_and_next_request_carries_it`: `input` scripted
    `["try hovering first", "then click"]`; provider returns failing code on the first guidance
    turn, working code on the second → second provider call
    `kwargs["guidance_history"] == ["try hovering first => <outcome first line>"]`;
    `provider.generate_step_code.call_count == 2`
  - `test_steer_quit_eof_sigint_return_none` (negative, parametrized quit / EOF / SIGINT):
    `input` fake returning `"quit"` / raising `EOFError` / raising `KeyboardInterrupt` →
    `steer(...) is None`; `provider.generate_step_code` not called; nothing hangs
  - `test_steer_provider_unavailable_ends_dialog` (negative): provider fake
    `side_effect=LLMUnavailableError("llm unavailable: openai")`; `input` returns a guidance
    line → `steer(...) is None`
  - `test_steer_local_commands_served_without_llm` (edge): `input` scripted
    `["code", "error", "snapshot", "screenshot", "quit"]` → `provider.generate_step_code` not
    called; `steer` returns None; the captured stdout contains the failed code, the error text,
    the snapshot, and a printed temp PNG path that exists on disk
  - `test_steer_survives_dead_page_banner_and_commands` (edge): `FakePage` whose
    `aria_snapshot`/`screenshot` raise `PlaywrightError("Target closed")`; `input` scripted
    `["snapshot", "quit"]` → `steer(...) is None` — nothing raised out of the dialog; the
    captured stdout contains "snapshot unavailable: Target closed"; the `steering_declined` log
    record present; no `on_healed` emitted
  - `test_steer_blank_guidance_line_reprompts_without_llm` (edge): `input` scripted
    `["", "   ", "quit"]` → `steer(...) is None`; `provider.generate_step_code` not called;
    caplog carries no `steering_guidance` record
  - `test_steer_no_candidate_failure_empty_code` (edge): failure with `code=""`;
    `input` scripted `["code", "<a guidance line>"]`; provider returns working code;
    `run_step_code` monkeypatched to succeed → provider `kwargs["existing_code"] == ""`; the
    captured stdout contains the empty code block of the banner and the `code` command; the
    returned step's code is the generated code; `cache.save` called once
- [ ] **Debugging**: `pytest tests/engine/steering/ -x` — fix implementation code until all tests pass
- [ ] **Contract re-verification**: facade accessibility
  `python -c "from prettyplay.engine.steering import StepSteering"`; every exit path heals or
  returns None; the guidance never enters the cache file; no budgets touched
- [ ] **Lint**: `ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 13: `StepExecutor` — the window, settle, the steering intercept and `on_step_finished` (facade)

The step cycle owner (`prettyplay/executor.py`). The constructor gains `steering: StepSteering`
(per the facade contract order: after `healer`, before `budgets`). `execute` algorithm (verbatim
from the design):

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

Key semantics: the gate catches exactly `IncurableStepError` — `ProductDefectError` and
`LLMUnavailableError` are not `IncurableStepError`, so the "never on product_defect / never when
the LLM is unavailable / never in replay-strict / never when off" gate holds structurally;
`on_step_finished` is emitted in `finally` — exactly once, after every other event, on pass, on
failure and on the strict miss; the outcome flag flips to "passed" only on the success path; a
steering-healed step is a pass (the intercept heals before any failure event fires);
`KeyboardInterrupt` (BaseException) is not caught by `except Exception` — it skips
`on_step_failed` but the `finally` still fires `on_step_finished(outcome="failed")` and the
interrupt propagates; `on_step_failed` payload is `str(error)` — the render, never re-composed;
replay-strict settle included ("re-executing cached code is execution, not generation").

**Usages relevant to this task:**
- `generation`, `healing` (from `prettyplay/engine/.usages/`): the engine cycles the executor
  delegates to — now with `window`.
- `hooks` (from `prettyplay/reporting/.usages/hooks.md`): the event sequence and the
  exactly-once closing event.
- `taxonomy` (from `prettyplay/failures/.usages/taxonomy.md`): the raised kinds and the code
  field of the strict paths.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests**: in `tests/test_executor.py` add — `StepExecutor` accepts the `steering`
  parameter (contract position); `execute(step_text, step_type, page)` unchanged shape (expected
  to fail at this stage)
- [ ] **Code**: wire the constructor (`steering` param stored) and implement `execute` per the
  algorithm — the window from `config.polling_timeout`/`config.polling_delay`, `settle` on the
  cached hit, `_steer_or_raise` with the gate `config.interactive and not config.strict`,
  `on_step_finished` in `finally` with the outcome flag, the `code` fields on the strict paths
  (miss `""`, failure `step.code`)
- [ ] **Code**: thread `window` into `healer.heal(...)` and `generator.generate(...)` calls
- [ ] **Interface verification**: `pytest tests/test_executor.py -x` — all pass
- [ ] **Logic tests**: in `tests/test_executor.py` add (executor with fakes; recording hooks;
  `Config(strict=False, interactive=True, polling_timeout=None)` unless stated)
  - `test_execute_steering_intercept_healed_continues_as_success`: cache hit whose code always
    fails; healer fake raises `IncurableStepError`; steering fake returns a healed `CachedStep` →
    `steering.steer` called once with the `IncurableStepError` instance; hooks sequence ends
    `["on_step_started", "on_step_passed", "on_step_finished"]` with `outcome == "passed"`; no
    raise
  - `test_execute_reports_on_step_finished_last_on_failure_with_verdict`: generator fake raises
    `IncurableStepError(..., verdict=verdict)`; `interactive=False` → events ==
    `["on_step_started", "on_step_failed", "on_step_verdict", "on_step_finished"]`; last payload
    `{"step_text": "open the docs", "step_type": "action", "outcome": "failed"}`
  - `test_execute_steering_intercept_never_on_product_defect_llm_strict_or_off` (negative,
    parametrized four cases): heal raises `ProductDefectError`; generate raises
    `LLMUnavailableError`; strict config with a failing cached step; `interactive=False` with an
    `IncurableStepError` — steering fake would heal → `steering.steer.assert_not_called()`; the
    original error kind propagates
  - `test_strict_failure_carries_cached_code_and_miss_carries_empty` (edge, parametrized):
    strict executor; a cached failing step (classification scripted `rot`) →
    `IncurableStepError.code == cached.code`; a cache miss → `IncurableStepError.code == ""`
  - `test_execute_step_finished_fires_on_keyboard_interrupt` (edge): cache miss; generator fake
    raises `IncurableStepError`; steering fake's `steer` raises `KeyboardInterrupt` →
    `pytest.raises(KeyboardInterrupt)`; the hooks sequence ends with
    `("on_step_finished", {"step_text": "click Pay", "step_type": "action", "outcome": "failed"})`;
    no `on_step_failed` event (the interrupt is not a step failure)
  - `test_strict_replay_settle_absorbs_transient_cached_failure` (edge):
    `Config(strict=True, polling_timeout=10.0, polling_delay=0)`; cache hit; `run_step_code`
    monkeypatched to raise `PlaywrightError("Timeout 10000ms exceeded")` on the first call and
    pass on the second; a provider fake that would record any call → no exception; hooks
    sequence `["on_step_started", "on_step_passed", "on_step_finished"]`; caplog carries exactly
    one `settle_retry` record; `provider.generate_step_code.assert_not_called()` and
    `provider.classify_failure.assert_not_called()`
  - `test_incurable_code_field_absent_from_render_and_hook_payload` (edge):
    `IncurableStepError("click Pay", "budget exhausted", "Timeout …",
    code="def step(page): boom()", verdict=None)` through an executor failure →
    `"def step(page): boom()" not in str(exc)`; not in the `on_step_failed` hook payload;
    `exc.code == "def step(page): boom()"`
- [ ] **Debugging**: `pytest tests/test_executor.py -x` — fix implementation code until all tests pass
- [ ] **Contract re-verification**: one render per terminal failure (message, `on_step_failed`
  payload, log record carry the same text); a cached step executes with no LLM involvement
  (settle absorbed); strict mode consumes no budgets; `on_step_finished` exactly once per step
- [ ] **Lint**: `ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 14: `PrettyPlay` composes `StepSteering` (facade)

The composition root (`prettyplay/scenario.py`) threads the steering into the per-test object.
Contract algorithm steps 5–6: "Construct `StepGenerator`, `StepHealer` and `StepSteering` from
the runtime config, provider, budgets, the step cache and the reporter" and "Construct
`StepExecutor` with `cache_key`, the cache, the engines, **the steering**, the runtime budgets,
the reporter, the runtime config and the runtime provider". The steering shares the same
provider, cache and reporter objects as the healer — one visibility point, one write-back store
per test. `prettyplay/__init__.py` needs no change (the facade contract re-exports nothing new);
the import comes from `prettyplay.engine.steering` into `scenario.py`.

**Usages relevant to this task:**
- `steering` (`prettyplay/engine/steering/.usages/steering.md`): the consumer doc of the REPL —
  the composition it assumes.
- `lifecycle` (`prettyplay/.usages/lifecycle.md`): the per-test composition order.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests**: in `tests/test_scenario.py` add — `PrettyPlay(cache_key="k",
  config=PrettyConfig(interactive=True))` with monkeypatched engine/driver boundaries constructs;
  `isinstance(executor._steering, StepSteering)` (expected to fail at this stage)
- [ ] **Code**: in `prettyplay/scenario.py` — import `StepSteering` from
  `prettyplay.engine.steering`; construct it from the runtime config, provider, step cache and
  reporter (after the healer, before the executor); pass it into the `StepExecutor` constructor
- [ ] **Interface verification**: `pytest tests/test_scenario.py -x` — all pass
- [ ] **Logic tests**: in `tests/test_scenario.py` add
  `test_prettyplay_composes_steering_and_threads_it_into_the_executor`:
  `PrettyPlay(cache_key="k", config=PrettyConfig(interactive=True))` with monkeypatched
  engine/driver boundaries (no browser, no LLM) → `isinstance(executor._steering, StepSteering)`;
  the same instance is passed to the `StepExecutor` constructor; steering holds the same cache
  and reporter objects as the healer
- [ ] **Debugging**: `pytest tests/test_scenario.py -x` — fix implementation code until all tests pass
- [ ] **Contract re-verification**: `python -c "import prettyplay"` — the public facade
  (`PrettyPlay`, `PrettyConfig`, `BrowserConfig`, `StepHooks`) unchanged and importable
- [ ] **Lint**: `ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 15: Integration tests — the full cycle with the window and the closing event

Cross-cell scenarios through the public facade: the window flow (`Config.polling_timeout` →
`SettleWindow` per step execution → settle on every execution), the hook flow ending with
`on_step_finished`, and the end-to-end wiring of both features. Extend
`tests/test_integration.py` (the existing scripted-provider-over-fake-page pattern — no real
browser, no real LLM).

**Usages relevant to this task:**
- `hooks` (from `prettyplay/reporting/.usages/hooks.md`): the full event sequence per step.
- `lifecycle` (`prettyplay/.usages/lifecycle.md`): the per-test object lifecycle.
- `conventions`: integration tests do not replace the per-entity contract/logic tests — they
  verify the wiring.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] Create/extend the integration scenario in `tests/test_integration.py`
- [ ] Test `test_scenario_and_full_integration_green_path_with_window`: a scripted provider over
  a fake page; `PrettyConfig(polling_timeout=6.0)`; `test.step("open the page")` and
  `test.expect("the heading is visible")` → both steps pass; per step the hook sequence is
  `[on_step_started, on_generation_started, (on_cache_saved when stored), on_step_passed,
  on_step_finished]` with `outcome == "passed"` — one window per step execution, cache writes,
  the closing event last
- [ ] Test the failure-shape scenario end-to-end: a scripted provider whose candidate always
  fails the check with a scripted `incurable` verdict, `interactive=False` → the raised
  `IncurableStepError` reaches the integrator with `.code` == the last candidate; the hook
  sequence per step ends `[..., on_step_failed, on_step_verdict, on_step_finished]`
- [ ] Run validation: `pytest tests/ -x` — the full suite green
- [ ] Final gates: `ruff check prettyplay/` and `goga lint` (0 errors — no CODEMANIFEST was
  modified)

---

## Validation Commands

- `pytest tests/ -x`: Run all tests (the design's validation gate)
- `ruff check prettyplay/`: Lint check (the design's validation gate; tasks use the superset
  `ruff check prettyplay/ tests/`)
- `python -c "from prettyplay.driver import is_pollable_failure; from prettyplay.engine.polling import SettleWindow, settle; from prettyplay.engine.steering import StepSteering; from prettyplay import PrettyPlay, PrettyConfig, StepHooks"`:
  Facade accessibility of every new and re-exported surface
- `goga lint`: contract lint — must stay at 0 errors (10 cells); proves no CODEMANIFEST was modified

---

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location`
- [ ] Every contract entity is accessible from the facade
- [ ] Properties and methods match the declared API
- [ ] Descriptions are reflected in behavior
- [ ] Contract dependencies are met
- [ ] Re-exports are accessible from the facade
- [ ] Every coding task followed the TDD workflow (contract tests → code → verification → logic tests → debugging → re-verification → lint)
- [ ] Contract tests and logic tests cover facade, API, and behavior within each coding task
- [ ] Integration tests exist where cross-entity scenarios require them
- [ ] No package boundary was expanded
- [ ] `CODEMANIFEST` files were not modified (contract is read-only)
- [ ] All validation commands pass
- [ ] Every Usages entry is mentioned in at least one task
