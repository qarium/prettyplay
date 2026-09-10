# Plan: `strict-and-fullscreen-mode`

Compiled from the reviewed design document `.goga/history/2026/strict-and-fullscreen-mode/design.md` (all five design-review fixes included: `FailureVerdict.render` column formula, launch-args `not headless` gate, `PRETTYPLAY_BROWSER` legacy rejection step, corrected consumer instructions, `format_step_error` message-less normalization).

## Purpose

Implement four capabilities of prettyplay (pre-1.0):

1. **Nested browser group with screen modes** — `BrowserConfig` (engine, screen, headless, endpoint) inside `Config`; screen resolved at context creation (empty / WxH / fullscreen / Playwright device name).
2. **Strict replay-only mode** — `strict: bool`; cached code executes honestly, nothing is ever (re)generated; a cache miss is incurable, a failed cached step is at most classified.
3. **Structured failure message** — one render per terminal failure (`render_terminal_message`): reason line, `---` separated `step:`/`error:` block, aligned verdict block; the same text feeds the exception message, the log record and the `on_step_failed` payload; the new `error` field carries the full underlying error.
4. **Classification instructions** — `classification_prompt` setting reaching classification requests only, as the final USER INSTRUCTIONS block, identically in both providers.

The most important gaps between contract and code: flat `browser`/`headless``browser_endpoint` settings vs the contracted nested group; no strict switch; truncated error text (`first_line_short`) vs the contracted full-text `error` field; verdict render with a category line vs the contracted aligned block; `classify_failure` without user instructions; initialism names (`LlmProvider`, `OpenAiProvider`, `LlmUnavailableError`) vs the contracted `LLMProvider`, `OpenAIProvider`, `LLMUnavailableError`.

Strategy: mechanical total rename first (unblocks everything), then leaf cells to root (`failures` → `config` → `llm` → `driver` → `engine` → root), each task leaving the full suite green, integration verification last. `prettyplay/cache`, `prettyplay/reporting` source and all `CODEMANIFEST` files stay untouched.

## Context

### Contract Surface

**Cell `prettyplay/failures`** (facade `prettyplay/failures/__init__.py`)

- **Entity: `render_terminal_message`** — Type: routine; `location: errors.py`; signature `(reason: str, step_text: str, error: str, verdict: FailureVerdict | None) -> text: str`; must be exported from the cell facade. Composes the single structured render: reason verbatim; `---` + `step:`/`error:` lines when either is non-empty; `---` + verdict block when the verdict renders non-empty; fixed block order; no bare or trailing separator; never embeds step code.
- **Entity: `FailureVerdict`** — Type: class (frozen dataclass); `location: errors.py`; `render()` redefined: explanation/recommendation lines only (category dropped — it travels in structured fields), values aligned after the longest label, multi-line continuations indented to the value column, empty fields produce no line, both empty → `""`.
- **Entity: `ProductDefectError`** — Type: class; `location: errors.py`; signature gains `error: str` (before `verdict`); derives `PrettyplayError` + `AssertionError`; exception text composed through `render_terminal_message` via `Exception.__init__`; `str(exc)` is the render, `exc.message` stays the primary reason; `step_text`/`message`/`error`/`verdict` attributes.
- **Entity: `IncurableStepError`** — Type: class; `location: errors.py`; signature gains `error: str` (before `verdict`); derives `PrettyplayError` only; same render routing; keeps the render-only fallback verdict (`FailureVerdict("incurable", "", "reword the step or refresh the cache")`) when the verdict is absent — the `verdict` attribute stays `None`; `recommendation` property falls back to the built-in guidance.
- **Entity: `LLMUnavailableError`** — Type: class; `location: errors.py`; renamed from `LlmUnavailableError`, behavior unchanged; no alias kept.
- Imported dependencies: none (base cell). Usages: `conventions`.

**Cell `prettyplay/config`** (facade `prettyplay/config/__init__.py`)

- **Entity: `BrowserConfig`** — Type: class (new); `location: models.py`; kw_only pydantic model; fields `name: Literal["chromium","firefox","webkit","chrome","msedge"] = "chromium"`, `screen: str = ""`, `headless: bool = True`, `endpoint: str = ""`; validators: ws/wss endpoint, WxH-positive screen (format level only — device names pass through unresolved); must be exported from the cell facade (beside `PrettyConfig`).
- **Entity: `Config`** — Type: class; `location: models.py`; restructured: `browser: BrowserConfig = BrowserConfig()`, new `strict: bool = False`, new `classification_prompt: str = ""`; flat `browser`/`headless`/`browser_endpoint` fields removed; `PrettyConfig` alias unchanged; `effective_generation_model`/`effective_classification_model` unchanged.
- **Entity: `load_config`** — Type: routine; `location: loader.py`; algorithm steps 1–10 (see Task 3): legacy `PRETTYPLAY_BROWSER` env rejection, old-flat-key rejection (one line per key naming the new home), typed scalar env parsing (bools `true/false/1/0` case-insensitive; ints decimal; loud `ConfigurationError` naming setting/received/allowed), group env overrides `PRETTYPLAY_BROWSER_{NAME|SCREEN|HEADLESS|ENDPOINT}` merged as a nested dict over the section group, nested programmatic merge (explicitly set `BrowserConfig` fields win; untouched defaults never overwrite; explicit `strict=False` overrides).
- **Entity: `ConfigurationError`** — Type: class; `location: loader.py`; additionally covers removed flat keys and unparseable env values.
- Imported dependencies: `PrettyplayError` from `prettyplay/failures` (+ usage `taxonomy`). Usages: `conventions`, `pydantic`.

**Cell `prettyplay/llm`** (facade `prettyplay/llm/__init__.py`)

- **Entity: `LLMProvider`** — Type: class (port); `location: provider.py`; renamed from `LlmProvider`; `classify_failure` signature gains `user_instructions: str` (after `prompt`); port raises `NotImplementedError`.
- **Entity: `OpenAIProvider`** — Type: class; `location: openai_provider.py`; renamed from `OpenAiProvider`; `classify_failure` builds fields via the shared builder and sends one completion with `effective_classification_model`, `system=prompt`.
- **Entity: `AnthropicProvider`** — Type: class; `location: anthropic_provider.py`; full parity with the openai implementation.
- **Entity: `_request.build_classification_fields`** — internal helper, `location: _request.py`; signature gains `user_instructions`; renders `STEP / CODE / ERROR / PAGE SNAPSHOT` sections with `USER INSTRUCTIONS` appended **last** when non-empty.
- **Entity: `create_provider`** — Type: routine; `location: provider.py`; unchanged behavior, renamed types.
- Imported dependencies: `Config` from `prettyplay/config`, `LLMUnavailableError` from `prettyplay/failures`. Usages: `conventions`, `openai`, `anthropic`.

**Cell `prettyplay/driver`** (facade `prettyplay/driver/__init__.py`)

- **Entity: `DriverSession.open_context`** — Type: method; `location: session.py`; screen-mode resolution: `""` → no params; `"fullscreen"` → `no_viewport=True` on a local headed launch, else `viewport 1920x1080`; WxH (`^\d+x\d+$`) → parsed viewport in every launch mode; otherwise device name → full descriptor from the registry of the **running** Playwright, absent → loud `Error` with `difflib.get_close_matches` suggestions (cutoff 0.5, up to 3). `_launch_engine` reads the browser group and adds `args=["--start-maximized"]` iff `screen == "fullscreen"` and name in `{chromium, chrome, msedge}` and a local headed launch (`not headless`); firefox/webkit launch with no extra args (approved decision A).
- Constraints: `PageFacade`/`LocatorFacade` untouched; the screen resolution and the device registry access run inside the driver thread.
- Imported dependencies: `Config` from `prettyplay/config`. Usages: `conventions`, `playwright`.

**Cell `prettyplay/engine`** (facade `prettyplay/engine/__init__.py`)

- **Entity: `classify_step_failure`** — Type: routine; `location: classification.py`; passes `config.classification_prompt` as `user_instructions`; `CLASSIFICATION_PROMPT` gains the input line `- USER INSTRUCTIONS: the project's classification guidance, when configured` (after SCREENSHOT).
- **Entity: `StepGenerator`** (`generate`/`regenerate` via shared `_loop`) — Type: class; `location: generator.py`; the `error` field of terminal raises carries the full formatted failure; reasons authored colon-free (em dash); failed-check stop, budget exhaustion with pool-specific classification behavior per the design algorithm.
- **Entity: `StepHealer.heal`** — Type: method; `location: healer.py`; terminal raises carry the full underlying error in the `error` field; rot-regeneration exhaustion re-raises with the healer's verdict.
- **Entity: `format_step_error`** — implementation helper (not a contract entity); `location: text.py`; replaces `first_line_short`/`SHORT_ERROR_LENGTH` (removed — no consumer remains).
- Imported dependencies: `Config`, `StepReporter`, `ProductDefectError`/`IncurableStepError`/`LLMUnavailableError`/`FailureVerdict`, `PageFacade` (+ usage `facade`), cache types, `LLMProvider`/`FailureClassification` (+ usage `classification`). Usages: `conventions`, inline `system_prompt` and `classification_prompt`.

**Cell `prettyplay` (root)** (facade `prettyplay/__init__.py`)

- **Entity: `StepExecutor`** — Type: class; `location: executor.py`; signature gains `config: PrettyConfig` and `provider: LLMProvider`; `execute` gains the strict replay-only path and `_strict_failure` (classification only, quiet skip on LLM unavailability, raise by step type); `on_step_failed` carries `str(error)` — the render, never re-composed; `on_step_verdict` from the verdict object fields.
- **Entity: `PrettyTest`** — Type: class; `location: scenario.py`; construction step 6 passes `config=runtime.config, provider=runtime.provider` to `StepExecutor`; construction stays credential-free.
- Imported dependencies: everything above (+ usages `hooks`, `taxonomy`, `generation`, `healing`). Usages: `conventions`.

**Cell `prettyplay/reporting`** — contract semantics updated (`on_step_failed` error payload is the full structured render; `on_step_verdict` built from the verdict object), realized entirely by the executor payload construction; `hooks.py` and `reporter.py` signatures are unchanged — **no source change in this cell**.

**Cell `prettyplay/cache`** — untouched (step addressing and budgets contractually unchanged; budgets are simply never consumed on the strict path).

### Re-exports

- `->PrettyConfig: {}` — root facade re-export of `Config AS PrettyConfig` from `prettyplay/config`; already satisfied; stays importable from `prettyplay`.
- `->BrowserConfig: {}` — root facade re-embed of `BrowserConfig` from `prettyplay/config`; facade obligation: `from prettyplay import BrowserConfig` must work and `"BrowserConfig"` must be in `prettyplay.__all__` (Task 7).

### Usages Context

- `conventions` (`.goga/usages/conventions.md`) — mandatory Python rules: 3.10+ compatibility, relative intra-package imports, pydantic `kw_only` models with empty defaults, `prettyplay` logging conventions, Google-style docstrings, test structure/mocking rules, parametrize for threshold/matrix tables. Validation commands: `pytest tests/ -x`, `ruff check prettyplay/`. Relevant to every task.
- `pydantic` (`.goga/usages/cooks/pydantic.md`) — nested `BrowserConfig` schema, TOML loading, flat env overrides, old-flat-key hard break, `model_fields_set`/`model_copy` nested-group merge rules. Relevant to Task 3. Already updated with the new sections by the architecture stage.
- `playwright` (`.goga/usages/cooks/playwright.md`) — sync-API lifecycle, channels, ws connects, and the new "Screen modes" section (`new_context(viewport=…)`, device emulation, fullscreen rules, `launch(args=["--start-maximized"])` + `no_viewport=True`). Relevant to Task 5. Already updated.
- `openai` / `anthropic` (`.goga/usages/cooks/{openai,anthropic}.md`) — SDK call patterns and the `LLMUnavailableError` error mapping for both providers. Relevant to Tasks 1, 4.
- Inline `system_prompt` / `classification_prompt` (engine cell header) — the verbatim system prompts; `classification_prompt` already lists the USER INSTRUCTIONS input line; `SYSTEM_PROMPT` in `generator.py` must match `system_prompt` byte-for-byte and `CLASSIFICATION_PROMPT` in `classification.py` must gain the line. Relevant to Tasks 4, 6.

### Imported Usages

- `taxonomy` from `prettyplay/failures` (`prettyplay/failures/.usages/taxonomy.md`) — structured message template with the exact sample, block-omission rules, `error` field note, one-render rule. Consumed by `prettyplay/config` and the root. Relevant to Tasks 2, 3, 7.
- `facade` from `prettyplay/driver` (`prettyplay/driver/.usages/facade.md`) — page-API surface listing mirrored verbatim by `PAGE_API_SURFACE` in `generator.py`; unchanged by this topic. Relevant to Task 6 (do not drift).
- `classification` from `prettyplay/llm` (`prettyplay/llm/.usages/classification.md`) — the `user_instructions` parameter placement. Relevant to Tasks 4, 6.
- `hooks` from `prettyplay/reporting` (`prettyplay/reporting/.usages/hooks.md`) — full-render `error` payload, verdict-fields rule. Relevant to Task 7.
- `generation` / `healing` from `prettyplay/engine` (`prettyplay/engine/.usages/{generation,healing}.md`) — error field, classification instructions, strict interplay. Relevant to Tasks 6, 7.

### Local Usages

No new `.usages/` files and no updates: every cell-level practice file (`configuration.md`, `taxonomy.md`, `hooks.md`, `facade.md`, `classification.md`, `providers.md`, `generation.md`, `healing.md`, `lifecycle.md`, `steps.md`) was updated by the architecture stage and verified current by the design review. No creation tasks needed.

### External Dependencies

- pydantic ≥ 2.7 (verified behaviors: nested dict→model coercion, `model_fields_set`, deep-copied model defaults, `model_copy(update=)`, dotted locs).
- Playwright sync ≥ 1.49, verified against 1.62.0 (207 devices in the running registry; descriptor keys are valid `new_context` params; `no_viewport` and `launch(args=…)` valid).
- openai / anthropic SDKs (one completion per attempt; error mapping).
- pytest / pytest-mock / ruff (test = extra).

## Facts

- The CODEMANIFEST files of all seven cells already state the target contracts (materialized by the architecture stage; the config manifest carries the reviewed `load_config` 10-step algorithm including the legacy `PRETTYPLAY_BROWSER` rejection).
- All `.usages/` files and both cooks (`playwright.md`, `pydantic.md`) are already current in the working tree.
- Current source still has: flat `Config.browser`/`headless`/`browser_endpoint`; `first_line_short` + `SHORT_ERROR_LENGTH` in `prettyplay/engine/text.py`; `on_step_failed` carrying `first_line_short(error)`; verdict render with a category line; `classify_failure` without `user_instructions`; old initialism names everywhere.
- `first_line_short` consumers: `prettyplay/executor.py` (import + 2 call sites), `prettyplay/engine/generator.py` (import + 3 call sites), `tests/test_executor.py` (import + 1 use). No other consumer exists.
- `ProductDefectError`/`IncurableStepError` construction sites that must gain the `error` argument: `prettyplay/engine/generator.py` (`_loop`), `prettyplay/engine/healer.py` (`heal`), and the new strict path in `prettyplay/executor.py`.
- The provider is constructed lazily by `PrettyplayRuntime.provider` — a lightweight object, no SDK client, no credentials; passing it to `StepExecutor` keeps `PrettyTest` construction credential-free.
- The reporter's reserved-key prefixing (`ctx_`-prefix) does not affect `error` — it is not a reserved log-record key; multi-line renders pass through unchanged.
- Test suite layout mirrors cells: `tests/{config,failures,llm,driver,engine,reporting}/test_*.py` plus root-level `tests/test_executor.py`, `tests/test_scenario.py`, `tests/test_integration.py`, `tests/test_runtime.py`; shared fixtures in `tests/conftest.py` (`write_pyproject`, atexit isolation).
- Validation gates (design): `pytest tests/ -x` green; `ruff check prettyplay/` clean; `python -c "from prettyplay import BrowserConfig, PrettyConfig, PrettyTest"`.

## Gap Analysis

- **Missing contract entities**: `BrowserConfig` (models.py), `render_terminal_message` (errors.py).
- **Missing facade exposure**: `BrowserConfig` from `prettyplay/config/__init__.py`; `render_terminal_message` from `prettyplay/failures/__init__.py`; `BrowserConfig` from the root facade (`__all__` update).
- **API mismatches**: `Config` flat browser fields vs nested group (+ `strict`, `classification_prompt` missing); `load_config` env map lacks `PRETTYPLAY_STRICT`, `PRETTYPLAY_CLASSIFICATION_PROMPT`, `PRETTYPLAY_BROWSER_SCREEN`, `PRETTYPLAY_BROWSER_ENDPOINT`, lacks typed scalar parsing, old-flat-key rejection and the nested merge; `LLMProvider.classify_failure`/`OpenAIProvider`/`AnthropicProvider`/`build_classification_fields` lack `user_instructions`; `ProductDefectError`/`IncurableStepError` lack `error`; `StepExecutor` lacks `config`/`provider`; initialism renames not applied.
- **Behavioral mismatches**: `FailureVerdict.render` emits a category line with no alignment; terminal exception texts are message + verdict tail, not the structured render; `on_step_failed` carries a 200-char first line; `_loop` truncates error texts and embeds them into reasons (colon form `candidate check failed: …`, `… exhausted; last failure: …`); `open_context` accepts no context parameters and `_launch_engine` never passes launch args; `CLASSIFICATION_PROMPT` lacks the USER INSTRUCTIONS input line; `classify_step_failure` passes no instructions.
- **Existing code that can be reused**: the whole driver-thread machinery (`PlaywrightWorker`, `_launch`, close paths), cache, reporter/hooks, runtime, provider request/parse helpers, `PageFacade`/`LocatorFacade`, conftest fixtures, fake-page/fake-provider test patterns.
- **Test coverage gaps**: all 26 scenarios of the design's Test Stack Trace are new; existing tests pinning old shapes (flat config, old render bytes, truncated errors, old names) must be updated inside the tasks that change those shapes.
- **Deletions**: `first_line_short`, `SHORT_ERROR_LENGTH` (`prettyplay/engine/text.py`); flat `Config` fields; old initialism names (no aliases kept).

### Entity Interaction and Data Flow (from the design, verbatim)

```
                 pyproject.toml [tool.prettyplay]            env PRETTYPLAY_*
                          │                                        │
                          └──────────────┬─────────────────────────┘
                                         ▼
                                   load_config ──► ConfigurationError (old flat keys,
                                         │          invalid values, unparseable env)
                                         ▼
                                   Config ─ browser: BrowserConfig (name, screen, headless, endpoint)
                                    │  │                     strict, classification_prompt, generation_prompt
        ┌───────────────────────────┘  └──────────────────────┐
        ▼                                                     ▼
  PrettyTest(scenario.py) ──► PrettyplayRuntime(runtime.py)      StepExecutor(executor.py)
        │                         │        │                      config, provider, cache, engines,
        │                         │        │                      budgets, reporter
        │                   DriverSession  LLMProvider ◄─────────────┘ (strict-path classification)
        │                         │            ▲
        │                         ▼            │ classify_failure(user_instructions=classification_prompt)
        │                   PageFacade ──► run_step_code ──► Exception
        │                                              │
        │                    non-strict                 ▼                strict
        │        StepGenerator.generate ◄──── cache miss ───────► IncurableStepError (no generation)
        │        StepHealer.heal          ◄── cached failure ───► classify_step_failure ─┬─ product_defect
        │                 │                                        │                    │   → ProductDefectError
        │                 │ verdict = FailureVerdict               │ rot/incurable      │   → IncurableStepError
        │                 ▼                                        └─ LLM unavailable ──┘ raise by step type
        │   ProductDefectError / IncurableStepError (error field = full underlying error text)
        │                 │
        └── on_step_failed(error=str(exc)) / on_step_verdict(fields from verdict object) ──► StepReporter
                                                                                   │
                                                                        logger "prettyplay" + StepHooks
```

Data flows (verbatim):

1. **Settings flow** — `[tool.prettyplay]` + `[tool.prettyplay.browser]` + flat env vars → `load_config` (reject old flat keys → typed env parsing → pydantic validation → nested programmatic merge) → `Config` → consumed by `DriverSession` (browser group), `StepGenerator`/`classify_step_failure` (prompts), `StepExecutor` (strict switch), providers (models/base_url).
2. **Strict step flow (replay-only)** — `PrettyTest.action/assertion` → `StepExecutor.execute` → cache load → hit: `run_step_code`; failure → `classify_step_failure` (the only LLM call) → raise `ProductDefectError`/`IncurableStepError` carrying `FailureVerdict` + full error text; miss → `IncurableStepError` (strict forbids generation). Events: `on_step_started` → `on_step_failed` (full render) → `on_step_verdict` (when the verdict exists).
3. **Non-strict step flow** — unchanged cycle; the healer and generator now receive and carry the full formatted error text; terminal failures render through the single template.
4. **Screen flow** — `browser.screen` → `DriverSession.open_context` → context parameters (`viewport` / `no_viewport` / full device descriptor) and, at first launch, maximized args for chromium-family fullscreen.
5. **Classification instructions flow** — `classification_prompt` → `classify_step_failure` → `provider.classify_failure(user_instructions=…)` → USER INSTRUCTIONS block placed last in the user content of both providers.

Initialization order per test (unchanged shape, two new wires):
`load_config` → `PrettyplayRuntime(config)` → `StepReporter` → `StepCache` → `StepGenerator(config, provider, cache, budgets, reporter)` → `StepHealer(config, provider, generator, cache, budgets, reporter)` → `StepExecutor(cache_key, cache, generator, healer, budgets, reporter, config, provider)` — the provider is `runtime.provider` (cheap object construction; the SDK client stays lazy, no credentials needed).

---

## Tasks

> **Package ordering rule**: coding tasks for each package are completed before starting the next. Within each coding task, contract tests are written first (TDD workflow). One task per ralphex iteration.

### Task 1: Initialism rename sweep — `LLMUnavailableError`, `LLMProvider`, `OpenAIProvider` (mechanical refactor, TDD)

A pre-1.0 hard rename applied totally across source and tests — no class aliases are kept. It is mechanical and unblocks every later task: the failures cell defines `LLMUnavailableError` (`prettyplay/failures/errors.py`), the llm cell defines `LLMProvider` (`prettyplay/llm/provider.py`) and `OpenAIProvider` (`prettyplay/llm/openai_provider.py`); the engine, runtime, executor and scenario modules and ten test modules reference the old spellings. The rename must land in one move — splitting it per cell would leave broken imports between tasks. Behavior is otherwise unchanged.

**Usages relevant to this task:**
- `conventions`: Google-style docstrings, relative intra-package imports; test mirrors `tests/<cell>/test_<module>.py`.
- `openai` / `anthropic`: the error mapping text stays `LLMUnavailableError` naming the provider.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Declaration**: state that Task 1 (rename sweep) is being executed
- [ ] **Contract tests**: add `test_provider_renames_are_total` to `tests/llm/test_provider.py` — assert `prettyplay.failures.LLMUnavailableError` exists while `LlmUnavailableError` raises `AttributeError`; `prettyplay.llm.{LLMProvider, OpenAIProvider, create_provider}` exist while the old spellings are gone; `create_provider(Config(provider="openai"))` returns an `OpenAIProvider` instance that `isinstance`-checks against `LLMProvider` (expected to fail at this stage)
- [ ] **Code**: rename in `prettyplay/failures/errors.py` — class `LlmUnavailableError` → `LLMUnavailableError` (class definition, docstring cross-references)
- [ ] **Code**: rename in `prettyplay/failures/__init__.py` — import list and `__all__`
- [ ] **Code**: rename in `prettyplay/llm/provider.py` — `LlmProvider` → `LLMProvider` (class, docstrings, `NotImplementedError` messages naming the port, `create_provider` return annotation and body references to `OpenAiProvider` → `OpenAIProvider`)
- [ ] **Code**: rename in `prettyplay/llm/openai_provider.py` — class `OpenAiProvider` → `OpenAIProvider` (module docstring, base class, parity cross-references)
- [ ] **Code**: rename in `prettyplay/llm/anthropic_provider.py` and `prettyplay/llm/_request.py` — `LlmUnavailableError` → `LLMUnavailableError`, `OpenAiProvider` → `OpenAIProvider` references
- [ ] **Code**: rename in `prettyplay/llm/__init__.py` — imports and `__all__`
- [ ] **Code**: update references in `prettyplay/engine/generator.py`, `prettyplay/engine/healer.py`, `prettyplay/engine/classification.py`, `prettyplay/runtime.py` — imports, type hints, `Raises:` docstring sections
- [ ] **Code**: update docstring references in `prettyplay/executor.py` and `prettyplay/scenario.py` (`Raises:` sections name `LLMUnavailableError`)
- [ ] **Code**: sweep the test suite — `tests/failures/test_errors.py`, `tests/llm/test_provider.py`, `tests/llm/test_openai_provider.py`, `tests/llm/test_anthropic_provider.py`, `tests/engine/test_classification.py`, `tests/engine/test_generator.py`, `tests/engine/test_healer.py`, `tests/test_executor.py`, `tests/test_integration.py`, `tests/test_scenario.py` (imports, fake subclasses of the port, `pytest.raises` targets)
- [ ] **Interface verification**: run `pytest tests/llm/ tests/failures/ -v` — the rename contract test passes
- [ ] **Logic tests**: none beyond the contract test — the refactor is behavior-preserving; the existing suite is the behavioral pin
- [ ] **Debugging**: run `pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code except the renamed spellings)
- [ ] **Contract re-verification**: `python -c "from prettyplay.failures import LLMUnavailableError; from prettyplay.llm import LLMProvider, OpenAIProvider, create_provider"` and no `Llm`/`OpenAi` spelling remains: `grep -rn "LlmUnavailableError\|LlmProvider\|OpenAiProvider" prettyplay/ tests/` returns nothing
- [ ] **Lint**: `ruff check prettyplay/` — fix formatting if necessary
- [ ] **Completion**: mark the checkboxes of this task as completed

### Task 2: `prettyplay/failures` — structured terminal render and the `error` field (TDD)

Implements the single structured render of a terminal failure and the new `error` field of the two terminal step errors, in `prettyplay/failures/errors.py` plus the cell facade. One render — produced at exception construction — feeds the exception message, the log record and the `on_step_failed` hook payload; consumers never re-compose. Because the constructor signatures gain `error` before `verdict`, the engine raise sites (`prettyplay/engine/generator.py`, `prettyplay/engine/healer.py`) are adapted mechanically in this task by inserting `""` as the error argument — the full error-text policy lands in Task 6; existing tests that pin old message bytes are updated to the new render in this task.

**Usages relevant to this task:**
- `conventions`: Google-style docstrings; the module docstring of `errors.py` must drop statements about the verdict-tail render.
- `taxonomy` (imported by consumers; the file `prettyplay/failures/.usages/taxonomy.md` pins the template sample byte-exactly — the render must match it):

```
<reason>
---
step: <step_text>
error: <error>
---
explanation:    <explanation>
recommendation: <recommendation>
```

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Declaration**: state that Task 2 (failures structured render) is being executed
- [ ] **Contract tests**: add to `tests/failures/test_errors.py` — facade accessibility (`from prettyplay.failures import render_terminal_message`) and API shape: `render_terminal_message(reason, step_text, error, verdict) -> str`; `ProductDefectError`/`IncurableStepError` accept the four-argument form (`step_text, message|reason, error, verdict`); `FailureVerdict.render()` takes no arguments (expected to fail at this stage)
- [ ] **Code**: implement `render_terminal_message(reason, step_text, error, verdict)` in `prettyplay/failures/errors.py`:

```
1. lines = [reason]
2. IF step_text or error:
     lines += ["---"]
     IF step_text: lines += [f"step: {step_text}"]
     IF error:    lines += [f"error: {error}"]
3. IF verdict is not None:
     block = verdict.render()
     IF block: lines += ["---", block]
4. RETURN "\n".join(lines)
```

- [ ] **Code**: redefine `FailureVerdict.render()` — verdict block only, category dropped, column-aligned:

```
1. width = 15 (len("recommendation:") — the longest label; fixed regardless of which fields are present)
2. FOR (label, value) in (("explanation", …), ("recommendation", …)):
     IF not value: continue
     line = f"{label}:".ljust(width) + " " + value.replace("\n", "\n" + " " * (width + 1))
     # value column = width + 1 = 16: "explanation:" + 4 spaces, "recommendation:" + 1 space —
     # first lines and multi-line continuations indent to the same column
3. RETURN "\n".join(lines)      # "" when both empty
```

- [ ] **Code**: rework `ProductDefectError.__init__(step_text, message, error="", verdict=None)` — store `step_text/message/error/verdict`; set the exception text via `Exception.__init__(self, render_terminal_message(message, step_text, error, verdict))` — do NOT route through `PrettyplayError.__init__` (it would overwrite the public `message` attribute with the full render); keep deriving `PrettyplayError` + `AssertionError`; drop the old `__str__` override
- [ ] **Code**: rework `IncurableStepError.__init__(step_text, reason, error="", verdict=None)` — same routing with `render_verdict = verdict if verdict is not None else FailureVerdict("incurable", "", "reword the step or refresh the cache")`; the `verdict` attribute stays `None` for the fallback (render-only — `on_step_verdict` never fires for it); keep the `recommendation` property (verdict recommendation when present, else the built-in guidance); keep deriving `PrettyplayError` only
- [ ] **Code**: export `render_terminal_message` from `prettyplay/failures/__init__.py` (beside `LLMUnavailableError`)
- [ ] **Code**: adapt the engine raise sites mechanically — `prettyplay/engine/generator.py` (`_loop`: the three budget-exhaustion raises and the two failed-check raises — five terminal constructions) and `prettyplay/engine/healer.py` (`heal`: the product_defect, incurable and exhaustion-re-raise sites) insert `""` as the `error` argument, keeping current behavior
- [ ] **Code**: update the module docstring of `prettyplay/failures/errors.py` to the one-render rule
- [ ] **Interface verification**: run `pytest tests/failures/ -v` — the contract tests pass
- [ ] **Logic tests**: add to `tests/failures/test_errors.py` (scenarios from the design, verbatim):
  - `test_render_terminal_message_full_template` — `render_terminal_message("кнопка осталась невидимой", "Проверить кнопку", "Locator expected to be visible", FailureVerdict("product_defect", "на странице нет элемента", "проверить селектор"))` equals exactly `"кнопка осталась невидимой\n---\nstep: Проверить кнопку\nerror: Locator expected to be visible\n---\nexplanation:    на странице нет элемента\nrecommendation: проверить селектор"`; `"explanation:"` followed by exactly 4 spaces (value column = `len("recommendation:") + 1`); the first line has no `":"` of its own
  - `test_verdict_render_alignment_and_multiline` — `FailureVerdict("rot", "line one\nline two", "fix it").render()` equals `"explanation:    line one\n                line two\nrecommendation: fix it"` (continuation indented to the value column, 16 spaces; no `category` line anywhere); `FailureVerdict("rot", "", "").render() == ""`; `FailureVerdict("rot", "only", "").render() == "explanation:    only"` (padded to the fixed column)
  - `test_terminal_errors_carry_render_error_field_and_types` — `str(pde) == render_terminal_message(...)` identical text; `pde.error == "Locator expected to be visible"`; `pde.verdict is verdict`; `pde.message == "the button stayed invisible"`; `isinstance(pde, AssertionError)` and `isinstance(pde, PrettyplayError)`; `IncurableStepError("step", "strict mode forbids generation — the step is missing from the cache")`: `ise.reason` set, `ise.error == ""`, `ise.verdict is None`, `"recommendation: reword the step or refresh the cache" in str(ise)`, `ise.recommendation == "reword the step or refresh the cache"`, `not isinstance(ise, AssertionError)`; `LLMUnavailableError("llm unavailable: openai")`: `str == message`, `issubclass PrettyplayError`
  - `test_render_terminal_message_block_omission` — `render_terminal_message("reason", "", "", None)` → `"reason"` alone, no `"---"` at all; `("reason", "step", "", None)` → `"reason\n---\nstep: step"`; `("reason", "", "err", None)` → `"reason\n---\nerror: err"`; `FailureVerdict("rot", "", "rec")` block renders `recommendation` only; the text never ends with `"---"`
- [ ] **Code**: update the existing render/message assertions across the suite to the new template (engine, healer, executor, integration tests that pin old `str(exc)` bytes — with the mechanical `error=""` the renders carry no error line)
- [ ] **Debugging**: run `pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code beyond updating the pinned render bytes)
- [ ] **Contract re-verification**: facade exports `render_terminal_message`, `LLMUnavailableError`; one-render invariant — `str(exc)` is composed only at construction
- [ ] **Lint**: `ruff check prettyplay/` — fix formatting, apply decomposition if necessary
- [ ] **Completion**: mark the checkboxes of this task as completed

### Task 3: `prettyplay/config` — nested browser group, strict switch and the layered loader (TDD)

Implements the `BrowserConfig` group and the restructured `Config` in `prettyplay/config/models.py`, the layered `load_config` in `prettyplay/config/loader.py` (group env overrides, old-flat-key rejection, typed scalar env parsing, nested programmatic merge, dotted validation rendering), and exports `BrowserConfig` from `prettyplay/config/__init__.py`. Because the flat `browser`/`headless`/`browser_endpoint` fields disappear, `prettyplay/driver/session.py` gets the minimal mechanical adaptation in this task — `_launch_engine` reads `config.browser.name` / `config.browser.headless` / `config.browser.endpoint` with unchanged semantics (endpoint connect, channel launch, headless flag); the full screen-mode algorithm lands in Task 5. Tests constructing `Config` with flat fields (`tests/config/`, `tests/driver/test_session.py`, `tests/test_scenario.py`) are updated to the group shape here.

**Usages relevant to this task:**
- `pydantic`: nested `BrowserConfig` schema, TOML loading, flat env overrides, old-flat-key hard break, `model_fields_set`-driven `model_copy` merging, loud validation wrapping; `tomllib`/`tomli` by Python version.
- `taxonomy` from Imports: the `ConfigurationError` derivation base.
- `conventions`: pydantic v2, `kw_only=True`, empty defaults, Google docstrings; the module docstrings of `models.py` and `loader.py` must drop statements about the old flat keys.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Declaration**: state that Task 3 (config cell) is being executed
- [ ] **Contract tests**: add to `tests/config/test_models.py` and `tests/config/test_loader.py` — facade accessibility (`from prettyplay.config import BrowserConfig, PrettyConfig, Config, ConfigurationError, load_config`); `BrowserConfig` kw_only construction with the four fields; `Config` carries `browser: BrowserConfig`, `strict: bool = False`, `classification_prompt: str = ""` and no flat browser fields; `load_config(pyproject_path, overrides)` signature unchanged (expected to fail at this stage)
- [ ] **Code**: implement `BrowserConfig` in `prettyplay/config/models.py`:

```
1. pydantic BaseModel, kw_only=True
2. FIELDS:
   - name: Literal["chromium","firefox","webkit","chrome","msedge"] = "chromium"
   - screen: str = ""                       # format-level validation only
   - headless: bool = True
   - endpoint: str = ""                     # ws/wss URL when non-empty
3. VALIDATORS:
   - endpoint: empty → keep; urlparse scheme in {"ws","wss"} and netloc → keep; else ValueError("must be a valid ws/wss URL")
   - screen: empty → keep; match ^(\d+)x(\d+)$ → width>0 and height>0 else
     ValueError("must be positive integers in WxH form"); no match → keep verbatim (fullscreen, device names)
```

- [ ] **Code**: restructure `Config` in `prettyplay/config/models.py`:

```
1. FIELDS (kw_only, empty defaults):
   provider: Literal["openai","anthropic"] = "openai"
   browser: BrowserConfig = BrowserConfig()          # pydantic deep-copies model defaults per instance
   model/generation_model/classification_model/base_url/cache_root: str = ""
   generation_prompt: str = ""
   classification_prompt: str = ""
   strict: bool = False
   generation_attempts: PositiveInt = 3
   healing_attempts: PositiveInt = 2
   send_screenshots: bool = False
2. PROPERTIES: effective_generation_model, effective_classification_model (unchanged)
3. PrettyConfig = Config alias (unchanged)
```

- [ ] **Code**: implement the layered `load_config` in `prettyplay/config/loader.py`:

```
1. resolve pyproject path (given / searched upward)
2. parse TOML; section = data["tool"]["prettyplay"] or {}
3. IF env PRETTYPLAY_BROWSER set:
     raise ConfigurationError("PRETTYPLAY_BROWSER is no longer supported: use PRETTYPLAY_BROWSER_NAME")
4. flat_old = [k for k in ("browser","headless","browser_endpoint")
               if k in section and not (k == "browser" and isinstance(section[k], dict))]
   IF flat_old:
     raise ConfigurationError(one line per key: "<key>: removed — its new home is [tool.prettyplay.browser] <sub>")
     # browser → name, headless → headless, browser_endpoint → endpoint
5. env = {}
   FOR each (setting, env_name) in _ENV_NAMES:                # dotted settings: browser.name, …
     raw = os.environ.get(env_name)
     IF raw is None: continue
     value = _parse_env_scalar(setting, raw)                  # bool/int/str; loud ConfigurationError on failure
     env[setting] = value
6. merged = {**section, **{k: v for k, v in env.items() if "." not in k}}
   group_env = {k.split(".", 1)[1]: v for k, v in env.items() if "." in k}
   IF group_env:
     merged["browser"] = {**(merged.get("browser") or {}), **group_env}
7. IF not merged.get("cache_root"): merged["cache_root"] = str(path.parent / ".prettyplay" / "cache")
8. TRY Config(**merged) EXCEPT ValidationError → raise ConfigurationError(_render_validation(err)) from err
   # _render_validation: field = ".".join(loc); _ALLOWED_TEXT adds browser.name, browser.endpoint,
   # browser.screen, strict, classification_prompt
9. IF overrides is None: return file_config
10. update = {}
    FOR (name, value) in overrides (fields only):
      IF name not in overrides.model_fields_set: continue
      IF isinstance(value, str) and not value: continue        # empty string means unset
      IF isinstance(value, BrowserConfig):
        group_update = {n: v for n, v in value
                        if n in value.model_fields_set and (v or not isinstance(v, str))}
        IF group_update:
          update["browser"] = file_config.browser.model_copy(update=group_update)
        # no explicitly set group fields → the file group survives untouched
      ELSE:
        update[name] = value                                    # bools participate even when False (strict)
11. RETURN file_config.model_copy(update=update)
```

`_parse_env_scalar(setting, raw)`:

```
bool settings (strict, send_screenshots, browser.headless):
  "true"/"1" (case-insensitive) → True; "false"/"0" → False
  else → ConfigurationError("<setting>: received <raw!r> — allowed: a boolean (true/false/1/0)")
int settings (generation_attempts, healing_attempts):
  int(raw) → value; ValueError → ConfigurationError("<setting>: received <raw!r> — allowed: a decimal integer")
str settings: verbatim
```

The env name map: `PRETTYPLAY_<SETTING_UPPER>` for scalars; `PRETTYPLAY_STRICT`; `PRETTYPLAY_CLASSIFICATION_PROMPT`; group `PRETTYPLAY_BROWSER_{NAME|SCREEN|HEADLESS|ENDPOINT}`.

- [ ] **Code**: export `BrowserConfig` from `prettyplay/config/__init__.py` (beside `PrettyConfig`)
- [ ] **Code**: minimal driver adaptation in `prettyplay/driver/session.py` — `_launch_engine` reads `self._config.browser.name`, `self._config.browser.headless`, `self._config.browser.endpoint` (semantics unchanged; no screen logic yet); update the constructor/attribute docstrings accordingly
- [ ] **Interface verification**: run `pytest tests/config/ tests/driver/ -v` — the contract tests pass
- [ ] **Logic tests** (scenarios from the design, verbatim; every test touching `load_config` pins/clears the six greedily-read env vars — `PRETTYPLAY_BROWSER_{NAME,SCREEN,HEADLESS,ENDPOINT}`, `PRETTYPLAY_STRICT`, `PRETTYPLAY_CLASSIFICATION_PROMPT`):
  - `test_browser_config_defaults_and_kw_only` (positive) — `BrowserConfig()` defaults `name="chromium"`, `screen=""`, `headless is True`, `endpoint=""`; `pytest.raises(TypeError)` on `BrowserConfig("chromium")` (positional rejected — kw_only)
  - `test_config_uses_nested_browser_group_and_new_switches` (positive) — `Config(browser={"name": "firefox", "screen": "1280x720"}, strict=True, classification_prompt="answer in Russian")`: the dict validates into `BrowserConfig` (nested validators run); `config.browser.name == "firefox"`; `config.browser.screen == "1280x720"`; `config.browser.headless is True`; `config.browser.endpoint == ""`; `config.strict is True`; `config.classification_prompt == "answer in Russian"`; `Config().strict is False`; `Config().classification_prompt == ""`
  - `test_load_config_reads_browser_group_and_rejects_flat_keys` (positive) — pyproject with `[tool.prettyplay] provider = "openai"` and `[tool.prettyplay.browser] name = "firefox"`, `screen = "fullscreen"`, `headless = false`, `endpoint = ""` → `config.browser.name == "firefox"`, `config.browser.screen == "fullscreen"`, `config.browser.headless is False`, `config.provider == "openai"`
  - `test_load_config_env_overrides_reach_the_group_and_new_settings` (positive) — pyproject with the group (`name="chromium"`, `screen=""`); `monkeypatch.setenv` `PRETTYPLAY_BROWSER_NAME=webkit`, `PRETTYPLAY_BROWSER_SCREEN=1280x720`, `PRETTYPLAY_STRICT=true`, `PRETTYPLAY_CLASSIFICATION_PROMPT=be terse`, `PRETTYPLAY_BROWSER_HEADLESS=0` → `config.browser.name == "webkit"`, `config.browser.screen == "1280x720"`, `config.browser.headless is False`, `config.strict is True`, `config.classification_prompt == "be terse"` (bools parsed: `"true"`→True, `"0"`→False; env wins per field over the TOML group)
  - `test_load_config_rejects_each_old_flat_key` (negative) — three pyproject files, each with one old flat key (`browser = "chromium"`, `headless = true`, `browser_endpoint = "ws://x"`): `pytest.raises(ConfigurationError)`; the key name and `"[tool.prettyplay.browser]"` appear in the message; one line per present key; a `browser` key holding a TABLE (`[tool.prettyplay.browser]`) does NOT raise
  - `test_load_config_env_scalar_parse_failures` (negative) — `PRETTYPLAY_STRICT=maybe`, `PRETTYPLAY_BROWSER_HEADLESS=yes`, `PRETTYPLAY_GENERATION_ATTEMPTS=three` (separate cases): `pytest.raises(ConfigurationError)`; the message names the setting, the received value and the accepted form, e.g. `"strict: received 'maybe' — allowed: a boolean (true/false/1/0)"`; a yes-variant for a browser bool is rejected (pydantic's wider lax set is bypassed)
  - `test_browser_config_validation_failures` (negative) — `BrowserConfig(name="opera")`; `BrowserConfig(endpoint="http://x")`; `Config(browser={"screen": "0x720"})`: `ValidationError` locs `("browser", "name")` / `("browser", "endpoint")` / `("browser", "screen")`; through `load_config` the rendered line starts `"browser.name: received 'opera' — allowed: chromium, firefox, webkit, chrome, msedge"`; `"0x720"` rejected ("must be positive"); `"fullscreen"` and `"iPhone 13"` accepted verbatim
  - `test_load_config_nested_group_merge_matrix` (edge) — file group `{"name": "firefox", "headless": false}`; cases: (a) `overrides=PrettyConfig(browser=BrowserConfig(screen="fullscreen"))` → browser stays firefox, `screen == "fullscreen"`, `headless is False` (file values survive, set fields win); (b) `overrides=PrettyConfig(browser=BrowserConfig())` → the file group unchanged (untouched defaults never overwrite); (c) `overrides=PrettyConfig(strict=False)` over file `strict=true` → `strict is False` (explicit False overrides too); (d) `overrides=PrettyConfig(browser=BrowserConfig(name=""))` → `name` stays `"firefox"` (empty string means unset inside the group too)
- [ ] **Code**: update existing tests constructing `Config` with flat fields (`tests/config/test_models.py`, `tests/config/test_loader.py`, `tests/driver/test_session.py`, `tests/test_scenario.py`) to the group shape and the new env hygiene
- [ ] **Debugging**: run `pytest tests/ -x` — fix implementation code until all tests pass
- [ ] **Contract re-verification**: nested loc rendering (`browser.name`, `browser.endpoint`, `strict`, …) via `_ALLOWED_TEXT`; `ConfigurationError` still derives from `PrettyplayError`; no raw `ValidationError` escapes
- [ ] **Lint**: `ruff check prettyplay/` — fix formatting, apply decomposition if necessary
- [ ] **Completion**: mark the checkboxes of this task as completed

### Task 4: `prettyplay/llm` — classification user instructions with provider parity (TDD)

Implements the `user_instructions` parameter of `classify_failure` across the port (`prettyplay/llm/provider.py`), both implementations (`prettyplay/llm/openai_provider.py`, `prettyplay/llm/anthropic_provider.py`) and the shared field builder (`prettyplay/llm/_request.py`). Placement parity is absolute: the USER INSTRUCTIONS block is appended **last** in the user content of classification requests in both providers, and only when non-empty — empty instructions produce byte-identical requests to the old form. The engine call site (`prettyplay/engine/classification.py`) is adapted mechanically in this task to pass `user_instructions=config.classification_prompt`; the system-prompt input line and its tests land in Task 6.

**Usages relevant to this task:**
- `openai` / `anthropic`: SDK call patterns, `LLMUnavailableError` mapping (unchanged).
- `classification` (imported by the engine; `prettyplay/llm/.usages/classification.md` documents the parameter placement): USER INSTRUCTIONS last, parity section.
- `conventions`: port signature style — explicit parameters, no defaults drift.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Declaration**: state that Task 4 (llm cell) is being executed
- [ ] **Contract tests**: add to `tests/llm/test_provider.py` — `LLMProvider.classify_failure` signature carries `user_instructions: str` after `prompt` (inspect the port and both implementations); update the port-subclassing fakes to the new signature (expected to fail at this stage)
- [ ] **Code**: extend `build_classification_fields` in `prettyplay/llm/_request.py`:

```
build_classification_fields(user_instructions, step_text, code, error, snapshot):
  sections = [STEP, CODE, ERROR, PAGE SNAPSHOT]
  IF user_instructions: sections += [USER INSTRUCTIONS]        # last
  RETURN "\n\n".join(sections)
```

- [ ] **Code**: add `user_instructions: str` to `LLMProvider.classify_failure` (port, `NotImplementedError` unchanged) and to both provider implementations — `text = build_classification_fields(user_instructions, …)`; the request keeps `effective_classification_model` and `system=prompt`; parse and error mapping unchanged
- [ ] **Code**: update the engine call site in `prettyplay/engine/classification.py` — pass `user_instructions=config.classification_prompt` (mechanical; the prompt-text line and tests land in Task 6)
- [ ] **Interface verification**: run `pytest tests/llm/ -v` — the contract tests pass
- [ ] **Logic tests** (scenario from the design, verbatim):
  - `test_provider_classification_instructions_placement_parity` — fakes for the openai/anthropic SDK clients capturing messages (existing provider test style); `provider.classify_failure(prompt="sys", user_instructions="be terse", step_text="s", code="c", error="e", snapshot="snap", screenshot=None)` on both providers: the user content of both providers ends with `"USER INSTRUCTIONS:\nbe terse"`; no `"USER INSTRUCTIONS"` block when `user_instructions=""`; the generation request (`generate_step_code`) placement is unchanged — after PAGE API, before CODE/ERROR
- [ ] **Code**: update the existing classification field tests (`tests/llm/test_request.py`, `tests/llm/test_openai_provider.py`, `tests/llm/test_anthropic_provider.py`, `tests/llm/test_provider.py`) to the new builder signature and placement
- [ ] **Debugging**: run `pytest tests/ -x` — fix implementation code until all tests pass
- [ ] **Contract re-verification**: parity — both providers call the same field builder with the same placement rule; generation requests never receive classification instructions and vice versa
- [ ] **Lint**: `ruff check prettyplay/` — fix formatting, apply decomposition if necessary
- [ ] **Completion**: mark the checkboxes of this task as completed

### Task 5: `prettyplay/driver` — screen modes at context creation (TDD)

Implements the screen-mode resolution of `DriverSession.open_context` (`prettyplay/driver/session.py`): the empty value keeps the Playwright default; WxH applies a fixed viewport in every launch mode; fullscreen follows the window on a local headed launch (`no_viewport=True`, plus `--start-maximized` launch arguments for the chromium family) and pins to 1920x1080 where no window exists; any other value is a device name resolved against the registry of the **running** Playwright with loud close-name suggestions. `PageFacade`/`LocatorFacade` stay untouched. The canonical WxH form is `^\d+x\d+$` (lowercase `x`, digits only); positivity is enforced only in the config validator — the driver merely re-detects the shape. The device resolution and the unknown-device error run inside the driver thread (`worker.run`) — `playwright.devices` belongs to the started session.

**Usages relevant to this task:**
- `playwright` (`.goga/usages/cooks/playwright.md`, "Screen modes" section): `new_context(viewport=…)`, device descriptors, `launch(args=["--start-maximized"])` + `no_viewport=True`; verified against the installed Playwright — device descriptors are `new_context`-compatible dicts (`viewport/user_agent/has_touch/is_mobile/device_scale_factor/default_browser_type`), `no_viewport` and `args` are valid parameters, `Playwright.devices` exposes the running registry.
- `facade` (cell practice): the mode changes only how the context opens — the facade surface is untouched.
- `conventions`: stub the Playwright objects at the import boundary (`mock.patch` of `sync_playwright` / injected fakes), consistent with the existing `tests/driver/test_session.py` style; the module docstring of `session.py` must drop statements about the flat endpoint field.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Declaration**: state that Task 5 (driver screen modes) is being executed
- [ ] **Contract tests**: add to `tests/driver/test_session.py` — `open_context()` signature unchanged; every resolution path ends in `browser.new_context(...)` called inside the worker with the resolved parameters and returns a `PageFacade` (expected to fail at this stage — current `open_context` passes no parameters)
- [ ] **Code**: implement the screen resolution in `prettyplay/driver/session.py` (`open_context`):

```
1. IF browser is None: _launch()
   _launch_engine:
     group = config.browser
     IF group.endpoint:
       engine = chromium for chrome/msedge else engines[group.name]
       connect(group.endpoint) — wrap a connect Error with the endpoint (unchanged)
     ELSE:
       args = ["--start-maximized"] IF group.screen == "fullscreen"
              and group.name in {"chromium","chrome","msedge"}
              and not group.headless ELSE None
              # a window exists only on a local headed launch; the endpoint
              # branch never reaches here (connect path above)
       launch(headless=group.headless, channel=<name for chrome/msedge>, args=args)
     # firefox/webkit fullscreen: no extra args (approved decision A)
2. inside the worker thread: params = _screen_context_params()
     screen = config.browser.screen
     IF screen == "":            → {}
     ELIF screen == "fullscreen":
       local headed (endpoint empty and headless false) → {"no_viewport": True}
       ELSE                                       → {"viewport": {"width": 1920, "height": 1080}}
     ELIF match ^(\d+)x(\d+)$:   → {"viewport": {"width": int(w), "height": int(h)}}
     ELSE (device name):
       devices = self._playwright.devices        # the running registry, in the driver thread
       IF screen in devices: → dict(devices[screen])
       ELSE: close = difflib.get_close_matches(screen, devices, n=3, cutoff=0.5)
             raise Error("unknown screen device <screen!r>: not in the playwright device registry"
                         + (f" — closest names: {', '.join(close)}" if close else ""))
3. context = browser.new_context(**params); page = context.new_page()   # in the worker
4. RETURN PageFacade(page, context) bound to the worker  # facade untouched
```

- [ ] **Interface verification**: run `pytest tests/driver/ -v` — the contract tests pass
- [ ] **Logic tests** (scenarios from the design, verbatim):
  - `test_open_context_screen_modes` (parametrized matrix) — fake Playwright objects: `playwright.devices = {"iPhone 13": {"viewport": {"width": 390, "height": 664}, "user_agent": "ua", "has_touch": True, "is_mobile": True, "device_scale_factor": 3, "default_browser_type": "webkit"}}`; recording `browser.new_context`; recording `engine.launch`; `DriverSession(Config(browser=BrowserConfig(screen=s, headless=h, endpoint=e))).open_context()`:
    - `""` (any mode) → `new_context()` called with no kwargs
    - `"1280x720"` (any mode) → `new_context(viewport={"width": 1280, "height": 720})`
    - `"iPhone 13"` (any mode) → `new_context(**devices["iPhone 13"])`
    - `"fullscreen"` + headless=False + endpoint="" + chromium → `launch(args=["--start-maximized"])` and `new_context(no_viewport=True)`
    - `"fullscreen"` + headless=False + endpoint="" + chrome (channel) → `launch(channel="chrome", args=["--start-maximized"])` and `new_context(no_viewport=True)`
    - `"fullscreen"` + headless=True (or endpoint set) → `new_context(viewport={"width": 1920, "height": 1080})`, no launch args
    - `"fullscreen"` + firefox headed → `launch` without args; `new_context(no_viewport=True)`
    - `"fullscreen"` + remote connect → connect path; viewport pinned 1920x1080
  - `test_open_context_unknown_device_fails_loudly` (negative) — fake registry `{"iPhone 13": …, "Pixel 7": …}`; `BrowserConfig(screen="iPhon 13")`; `session.open_context()` → `pytest.raises(playwright Error)`; `"iPhon"` and `"iPhone 13"` both in `str(exc)` (close-name suggestion)
- [ ] **Debugging**: run `pytest tests/ -x` — fix implementation code until all tests pass
- [ ] **Contract re-verification**: WxH and device descriptors apply in every launch mode; `no_viewport=True` only ever on local headed launches; the device list is never hard-coded (registry of the running Playwright)
- [ ] **Lint**: `ruff check prettyplay/` — fix formatting, apply decomposition if necessary
- [ ] **Completion**: mark the checkboxes of this task as completed

### Task 6: `prettyplay/engine` — full error-text policy and classification instructions (TDD)

Implements the engine-cell concern: the `error` field of terminal failures carries the full formatted underlying error, authored reasons are colon-free, and the classification user instructions reach the port. Files: `prettyplay/engine/text.py` (introduce `format_step_error`, remove `first_line_short`/`SHORT_ERROR_LENGTH`), `prettyplay/engine/classification.py` (`CLASSIFICATION_PROMPT` input line), `prettyplay/engine/generator.py` (`_loop` rewrite), `prettyplay/engine/healer.py` (`heal` raises). `prettyplay/executor.py` is adapted mechanically in this task because `first_line_short` disappears: the heal input switches to `format_step_error(error)` and the `on_step_failed` payload switches to `str(error)` — the render, per the design's executor algorithm (the strict path itself lands in Task 7).

**Usages relevant to this task:**
- `conventions`: the module docstrings of `text.py` and `classification.py` must drop statements about `first_line_short`; Google-style docstrings for `format_step_error` (private-by-convention module function — docstring still provided).
- `system_prompt` / `classification_prompt` (inline, engine cell header): `CLASSIFICATION_PROMPT` gains the input line exactly as the inline usage states; `SYSTEM_PROMPT` already lists it — both constants keep matching the inline texts byte-for-byte (`E501` is ignored for the verbatim prompt constants).
- `facade` from Imports: `PAGE_API_SURFACE` keeps mirroring `prettyplay/driver/.usages/facade.md` verbatim — do not drift it in this task.
- `classification` from Imports: the healing decision categories and the user-instructions placement.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Declaration**: state that Task 6 (engine cell) is being executed
- [ ] **Contract tests**: add to `tests/engine/test_classification.py` and a new test module for the text policy — `classify_step_failure(config, provider, step_text, code, error, page)` signature unchanged and now forwards `user_instructions=config.classification_prompt`; `format_step_error(exc: Exception) -> str` importable from `prettyplay.engine.text`; `first_line_short` and `SHORT_ERROR_LENGTH` gone (expected to fail at this stage)
- [ ] **Code**: implement `format_step_error` in `prettyplay/engine/text.py` and remove `first_line_short`/`SHORT_ERROR_LENGTH`:

```
format_step_error(exc: Exception) -> str:
  text = str(exc)
  IF isinstance(exc, AssertionError): RETURN text                  # no prefix — the type carries it;
                                                                   # "" for a bare assert -> the render omits the error line
  RETURN f"{type(exc).__name__}: {text}" IF text ELSE type(exc).__name__
                                                                   # action steps carry the type; a message-less
                                                                   # error yields the bare type name (no dangling ": ")
```

- [ ] **Code**: `CLASSIFICATION_PROMPT` in `prettyplay/engine/classification.py` gains the input line `- USER INSTRUCTIONS: the project's classification guidance, when configured` (after SCREENSHOT — matching the engine cell inline usage text)
- [ ] **Code**: rewrite the shared `_loop` of `StepGenerator` (`prettyplay/engine/generator.py`):

```
1. attempt = 0; code = None; error = <regeneration param or None>
2. WHILE True:
   a. IF not spend(identity):
        reason = f"{pool} attempt budget exhausted"                     # colon-free
        pool == "healing" → raise IncurableStepError(step_text, reason, error or "", None)
                            # healer attaches its verdict — no second LLM request
        error is None     → raise IncurableStepError(step_text, reason, "", None)
        verdict = self._classify(step_text, code, error, page)         # quiet skip → None
        → raise IncurableStepError(step_text, reason, error, verdict)
   b. attempt += 1; emit on_generation_started
   c. snapshot (+ screenshot when enabled)
   d. code = provider.generate_step_code(prompt=SYSTEM_PROMPT,
          user_instructions=config.generation_prompt, …, existing_code, error)
      # unavailability → LLMUnavailableError immediately (unchanged)
   e. TRY run_step_code(code, page):
        EXCEPT AssertionError as check_failure:                        # failed check — stop retries
          error_field = str(check_failure)                             # full, no prefix
          reason = f"candidate check failed — {error_field.partition(chr(10))[0]}"
          verdict = self._classify(step_text, code, reason_for_request=error_field, page)
          verdict is product_defect → raise ProductDefectError(step_text, verdict.explanation, error_field, verdict)
          ELSE                        → raise IncurableStepError(step_text, reason, error_field, verdict)
        EXCEPT Exception as candidate_error:
          existing_code = code; error = format_step_error(candidate_error)   # full, typed
        ELSE: break
3. CachedStep(identity, code, date.today().isoformat()); cache.save; RETURN step
```

(`_classify` unchanged apart from passing the full error text to the classification.)

- [ ] **Code**: update `StepHealer.heal` (`prettyplay/engine/healer.py`) — the raises carry the error field:

```
1. classification = classify_step_failure(config, provider, step_text, step.code, error, page)
2. emit on_healing_started(category)
3. product_defect → raise ProductDefectError(step_text, classification.explanation, error, verdict)
4. incurable      → raise IncurableStepError(step_text, classification.explanation, error, verdict)
5. rot            → healed = generator.regenerate(…, existing_code=step.code, error=error)
                    EXCEPT IncurableStepError as inner:
                      inner.verdict is None → raise IncurableStepError(step_text, inner.reason, inner.error, verdict) from inner
                      ELSE → raise                                          # fresh verdict never overwritten
6. emit on_healed; RETURN healed
7. classification unavailability → LLMUnavailableError (explicit infrastructure failure)
```

- [ ] **Code**: adapt `prettyplay/executor.py` mechanically — import and use `format_step_error`: the heal input becomes `format_step_error(error)`; the `on_step_failed` payload becomes `{"step_text", "step_type", "error": str(error)}` (the render, verbatim — never re-composed)
- [ ] **Interface verification**: run `pytest tests/engine/ tests/test_executor.py -v` — the contract tests pass
- [ ] **Logic tests** (scenarios from the design, verbatim):
  - `test_format_step_error_message_less_exceptions` (edge) — `format_step_error(AssertionError()) == ""`; `format_step_error(AssertionError("expected visible")) == "expected visible"`; `format_step_error(TimeoutError()) == "TimeoutError"`; `format_step_error(TimeoutError("click timeout")) == "TimeoutError: click timeout"`
  - `test_classify_step_failure_passes_classification_instructions` (positive) — `RecordingProvider` (records kwargs) stub; fake page returning snapshot "snap"; `classify_step_failure(Config(classification_prompt="answer in Russian"), provider, "step", "code", "err", page)`: `recorded["user_instructions"] == "answer in Russian"`; `"- USER INSTRUCTIONS: the project's classification guidance, when configured" in recorded["prompt"]`; `Config(classification_prompt="")` → `recorded["user_instructions"] == ""`
  - `test_generator_carries_full_error_text_in_terminal_failures` (edge) — generator with a provider returning code that raises `AssertionError("expected visible")` on the first candidate; classification stub: `ProductDefectError.error == "expected visible"` (full, no prefix, no truncation at 200 chars — use a >200-char message); `IncurableStepError` on budget exhaustion: `exc.error` == the last candidate full text; `exc.reason == "generation attempt budget exhausted"` (no colon, no embedded error)
  - `test_healer_and_strict_error_fields_end_to_end` (edge) — non-strict healer with a cached step failing `TimeoutError("click timeout")`; classification product_defect: `ProductDefectError.error == "TimeoutError: click timeout"`; `str(exc)` contains `"error: TimeoutError: click timeout"`; regeneration-exhaustion path: the outer `IncurableStepError.verdict` is the rot classification verdict and `.error` is the inner last-candidate text
- [ ] **Code**: update the existing engine/executor tests that pin truncated errors, the colon-form reasons (`"candidate check failed: …"`, `"… exhausted; last failure: …"`) and the `first_line_short` import (`tests/engine/test_generator.py`, `tests/engine/test_healer.py`, `tests/engine/test_classification.py`, `tests/test_executor.py`)
- [ ] **Debugging**: run `pytest tests/ -x` — fix implementation code until all tests pass
- [ ] **Contract re-verification**: every terminal raise on the engine paths carries the full formatted text; reasons are colon-free (static templates by construction; embedded assertion/LLM texts are data and pass verbatim — `render_terminal_message` never rewrites the reason); the instructions take no part in the step address
- [ ] **Lint**: `ruff check prettyplay/` — fix formatting, apply decomposition if necessary
- [ ] **Completion**: mark the checkboxes of this task as completed

### Task 7: root cell — strict replay-only executor, wiring and the `BrowserConfig` facade re-export (TDD)

Implements the root-cell contract: `StepExecutor` (`prettyplay/executor.py`) gains `config: PrettyConfig` and `provider: LLMProvider` and the strict replay-only path (`_strict_failure`); `PrettyTest` (`prettyplay/scenario.py`) passes the runtime config and the runtime provider to the executor (cheap object construction — the SDK client stays lazy, no credentials needed); the root facade (`prettyplay/__init__.py`) re-exports `BrowserConfig` beside `PrettyConfig`. The reporting contract (full-render `error` payload, verdict fields from the verdict object) is realized by the payload construction here — `hooks.py`/`reporter.py` stay untouched.

**Usages relevant to this task:**
- `taxonomy` from Imports: the failure kinds the step methods propagate.
- `hooks` from Imports (`prettyplay/reporting/.usages/hooks.md`): the full-render `error` payload section, the verdict-fields rule, the strict note.
- `generation` / `healing` from Imports (`prettyplay/engine/.usages/{generation,healing}.md`): the engine cycles the executor delegates to; strict never invokes them.
- `conventions`: the module docstrings of `executor.py` and `scenario.py` updated to the strict cycle; Google-style docstrings.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Declaration**: state that Task 7 (root cell) is being executed
- [ ] **Contract tests**: add to `tests/test_executor.py`, `tests/test_scenario.py` — `StepExecutor(cache_key, cache, generator, healer, budgets, reporter, config, provider)` eight-parameter signature; `prettyplay.__all__` contains `"BrowserConfig"`; `from prettyplay import BrowserConfig` resolves to `prettyplay.config.models.BrowserConfig` (expected to fail at this stage)
- [ ] **Code**: implement the strict-aware `execute` in `prettyplay/executor.py`:

```
TRY:
  1. emit on_step_started
  2. identity = StepIdentity(cache_key, step_type, normalize_step_text(step_text))
  3. cached = cache.load(identity)
     IF cached is not None:
       TRY run_step_code(cached.code, page):
         EXCEPT Exception as error:
           error_text = format_step_error(error)
           IF config.strict: self._strict_failure(step_text, step_type, cached, error_text, page)  # raises
           ELSE: healer.heal(cached, error_text, scenario, page)
     ELIF config.strict:
       raise IncurableStepError(step_text,
             "strict mode forbids generation — the step is missing from the cache", "", None)
     ELSE:
       generator.generate(identity, step_text, scenario, page)
  4. scenario.append(step_text); emit on_step_passed
EXCEPT Exception as error:
  emit on_step_failed {step_text, step_type, error: str(error)}          # the render, verbatim
  IF isinstance(error, (ProductDefectError, IncurableStepError)) and error.verdict is not None:
    emit on_step_verdict {step_text, category/explanation/recommendation from error.verdict}
  RAISE
```

`_strict_failure(step_text, step_type, step, error_text, page)` (always raises):

```
TRY:
  classification = classify_step_failure(config, provider, step_text, step.code, error_text, page)
EXCEPT LLMUnavailableError:
  logger.warning("verdict skipped: llm unavailable")
  reason = "the step failed in strict mode without an llm verdict"       # colon-free
  step_type == "assertion" → raise ProductDefectError(step_text, reason, error_text, None)
  ELSE                      → raise IncurableStepError(step_text, reason, error_text, None)
verdict = FailureVerdict(classification.category, classification.explanation, classification.recommendation)
classification.category == "product_defect"
  → raise ProductDefectError(step_text, classification.explanation, error_text, verdict)
ELSE → raise IncurableStepError(step_text, classification.explanation, error_text, verdict)
# healer never invoked, healing budget untouched, on_healing_started never fires,
# generator never invoked, generation budget untouched
```

- [ ] **Code**: wire `PrettyTest` (`prettyplay/scenario.py`) — construction step 6 becomes `StepExecutor(cache_key, cache, generator, healer, budgets, reporter, config=runtime.config, provider=runtime.provider)`; steps 1–5 unchanged
- [ ] **Code**: update the root facade (`prettyplay/__init__.py`) — `from .config import BrowserConfig, PrettyConfig`; `__all__ = ["PrettyTest", "PrettyConfig", "BrowserConfig", "PrettyplayRuntime", "StepExecutor"]`
- [ ] **Interface verification**: run `pytest tests/test_executor.py tests/test_scenario.py -v` — the contract tests pass
- [ ] **Logic tests** (scenarios from the design, verbatim):
  - `test_executor_strict_cache_miss_raises_without_generation` (positive) — executor wired with a cache whose `load` returns `None`; recording generator/healer; `Config(strict=True)`; fake provider; `executor.execute("Нажать «Войти»", "action", page)`: `pytest.raises(IncurableStepError)`; `exc.reason == "strict mode forbids generation — the step is missing from the cache"`; `exc.error == ""` and `exc.verdict is None`; `generator.generate` not called; `healer.heal` not called; `budgets.try_generation` never called; `"step: Нажать «Войти»" in str(exc)`; `"recommendation:" in str(exc)` (fallback verdict); the `on_step_failed` payload `["error"] == str(exc)` (one render); no `on_generation_started` / `on_healing_started` events
  - `test_executor_strict_failed_cached_step_classifies_only` (positive) — cache returns a `CachedStep` whose code raises a `TimeoutError` (action) / assertion text (assertion); fake provider returning `FailureClassification("product_defect" | "rot" | "incurable", …)`, then a second run with a provider raising `LLMUnavailableError`: product_defect + assertion → `pytest.raises(ProductDefectError)`, `exc.verdict.category == "product_defect"`, `exc.error == "TimeoutError: locator.click: Timeout 30000ms exceeded"` (typed prefix for action errors); an assertion-failure error field carries no `"AssertionError"` prefix; rot → `pytest.raises(IncurableStepError)`, `healer.heal` not called, no `on_healing_started`, `budgets.try_healing` never called; LLM unavailable + assertion step → `ProductDefectError`, `verdict is None`, `"the step failed in strict mode without an llm verdict" == exc.message`; LLM unavailable + action step → `IncurableStepError`, same reason wording, `exc.error` carries the full text; `caplog` has one WARNING `"verdict skipped: llm unavailable"`; `provider.generate_step_code` never called on any strict run
  - `test_executor_events_carry_full_render_and_verdict_fields` (positive) — non-strict executor; healer stub raising `ProductDefectError("step", "msg", "err-text", FailureVerdict("product_defect", "expl", "rec"))`; recording hooks; a cached step failing at `run_step_code`: the `on_step_failed` hook payload `["error"] == str(raised)` == the full render (contains `"---"` and `"recommendation:"`); the `on_step_verdict` payload == `{"step_text": "step", "category": "product_defect", "explanation": "expl", "recommendation": "rec"}`; the payload fields come from the verdict object (never parsed from the render)
  - `test_incurable_fallback_verdict_never_fires_the_event` (edge) — strict executor, cache miss; recording hooks: `"recommendation: reword the step or refresh the cache"` in the `on_step_failed` error payload; `on_step_verdict` never called; `raised.verdict is None`
  - `test_pretty_test_wires_config_and_provider_into_executor` (edge) — `PrettyTest(cache_key="k", config=PrettyConfig(strict=True, browser=BrowserConfig(screen="fullscreen", headless=False)))`; inspect the wired executor: `executor._config.strict is True`; `executor._config.browser.screen == "fullscreen"`; the executor provider is the runtime provider instance
  - `test_facade_reexports_browser_config` (positive) — in `tests/test_scenario.py`: `BrowserConfig is prettyplay.config.models.BrowserConfig`; `"BrowserConfig" in prettyplay.__all__`
- [ ] **Code**: update the existing executor/scenario/integration tests to the eight-parameter constructor and the strict-aware payload expectations
- [ ] **Debugging**: run `pytest tests/ -x` — fix implementation code until all tests pass
- [ ] **Contract re-verification**: strict mode — the only LLM calls are classifications; the generation and healing budgets are never consumed; the engines are never invoked; the executor WARNING wording matches the engines (`"verdict skipped: llm unavailable"`); construction stays credential-free
- [ ] **Lint**: `ruff check prettyplay/` — fix formatting, apply decomposition if necessary
- [ ] **Completion**: mark the checkboxes of this task as completed

### Task 8: Integration tests — strict run and structured render through the public facade

Cross-entity verification through the `PrettyTest` facade (the existing `tests/test_integration.py` fake-page/fake-provider patterns): the strict replay-only cycle end to end, the one-render rule across the exception/log/hook surfaces, and the settings flow from config to driver/executor. Also the final sweep: module docstrings, validation gates, untouched cells.

**Usages relevant to this task:**
- `hooks` from `prettyplay/reporting` (`prettyplay/reporting/.usages/hooks.md`): the `FailureMonitor` example and the full-render display rule.
- `taxonomy` from `prettyplay/failures` (`prettyplay/failures/.usages/taxonomy.md`): the structured message template consumers parse.
- `conventions`: integration tests use the fake boundaries (no real browsers, no real LLM keys — `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` unset unless faked); env hygiene for every `load_config` touch.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] Create/extend the scenarios in `tests/test_integration.py` (fake page + fake provider + recording hooks, `PrettyTest` with a `tmp_path` pyproject):
  - strict + cache miss: `PrettyTest(..., config=PrettyConfig(strict=True))` → `action(...)` raises `IncurableStepError`; `str(exc)` follows the structured template (`step:` line, fallback `recommendation:`); the `on_step_failed` hook payload `["error"] == str(exc)`; `on_step_verdict` never fires; no generation/healing events
  - strict + failed cached step with a product_defect fake classification on an assertion step: raises `ProductDefectError` carrying the verdict; `on_step_verdict` fires with the three verdict fields; the log record of `on_step_failed` carries the same multi-line render (`error` extra field, no `ctx_` prefixing)
  - non-strict rot flow: the healer regenerates through the fake provider; the healed step re-executes and the cache is rewritten; the `on_step_failed` of an intermediate terminal case (unhealable) carries the full render with the `error:` line (full text, no truncation)
  - classification instructions through the runtime: `PrettyConfig(classification_prompt=...)` reaches the fake provider's `classify_failure(user_instructions=...)` on the strict path; `generation_prompt` never reaches a classification call and vice versa
  - settings flow: a pyproject with `[tool.prettyplay.browser]` reaches the wired executor config (`browser.screen`, `strict`) without launching a browser
- [ ] Test edge case: strict mode never writes the cache — after a strict failure, no new cache file appears (generation path never runs)
- [ ] Run validation: `pytest tests/test_integration.py -v`, then the full gates — `pytest tests/ -x` green; `ruff check prettyplay/` clean; `python -c "from prettyplay import BrowserConfig, PrettyConfig, PrettyTest"` succeeds
- [ ] Final sweep: module docstrings of `errors.py`, `models.py`, `loader.py`, `session.py`, `executor.py`, `text.py`, `classification.py` carry no statements about the old flat keys, the verdict-tail render or `first_line_short`; `prettyplay/cache`, `prettyplay/reporting` sources and every `CODEMANIFEST` are untouched (`git diff --stat` check)

---

## Validation Commands

- `pytest tests/ -x`: Run all tests (the per-task gate and the final gate)
- `pytest tests/<cell>/ -v`: Run the tests of one cell during its task
- `ruff check prettyplay/`: Lint check
- `python -c "from prettyplay import BrowserConfig, PrettyConfig, PrettyTest"`: Facade accessibility of the re-exported settings models
- `grep -rn "LlmUnavailableError\|LlmProvider\|OpenAiProvider\|first_line_short" prettyplay/ tests/`: Total-rename and total-removal check (must return nothing after Tasks 1 and 6)

---

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location` (`BrowserConfig`, `Config`, `load_config`, `render_terminal_message`, `FailureVerdict.render`, `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError`, `LLMProvider`, `OpenAIProvider`/`AnthropicProvider` `classify_failure`, `DriverSession.open_context`, `classify_step_failure`, `StepGenerator`, `StepHealer`, `StepExecutor`, `PrettyTest`)
- [ ] Every contract entity is accessible from its facade (`render_terminal_message` from `prettyplay.failures`; `BrowserConfig` from `prettyplay.config` and from `prettyplay`)
- [ ] Properties and methods match the declared API (eight-parameter `StepExecutor`; `user_instructions` in `classify_failure`; `error` before `verdict` in the terminal errors)
- [ ] Descriptions are reflected in behavior (screen precedence matrix, strict replay-only guarantees, one-render rule, full-text error field, USER INSTRUCTIONS placement parity, colon-free authored reasons)
- [ ] Contract dependencies are met (imports resolve; no cross-import cycles introduced)
- [ ] Re-exports are accessible from the facade (`->PrettyConfig`, `->BrowserConfig`)
- [ ] Every coding task followed the TDD workflow (contract tests → code → verification → logic tests → debugging → re-verification → lint)
- [ ] Contract tests and logic tests cover facade, API, and behavior within each coding task (26 design scenarios + updates of the pinned old shapes)
- [ ] Integration tests exist for the cross-entity scenarios (strict run, one-render across exception/log/hook, settings flow)
- [ ] No package boundary was expanded (`prettyplay/cache` and `prettyplay/reporting` sources untouched; no new cells)
- [ ] `CODEMANIFEST` files were not modified (contract is read-only)
- [ ] All validation commands pass (`pytest tests/ -x`, `ruff check prettyplay/`, facade import)
- [ ] Every Usages entry is mentioned in at least one task (`conventions`, `pydantic`, `playwright`, `openai`, `anthropic`, `system_prompt`/`classification_prompt` inline, imported `taxonomy`/`facade`/`classification`/`hooks`/`generation`/`healing`)
