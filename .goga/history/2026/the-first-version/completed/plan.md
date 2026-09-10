# Plan: `the-first-version`

Result of compiling the verified design document
(`.goga/history/2026/the-first-version/design.md`, 2110 lines, passed design-review
with no open remarks) into a ralphex execution plan. Greenfield implementation of the
Prettyplay library against the CODEMANIFEST contracts of eight cells.

---

## Purpose

Implement the **prettyplay** library from scratch — UI tests in human language with a repository
step cache, LLM-driven code generation, and self-healing:

- after implementation the package provides the facade `from prettyplay import PrettyTest` — the
  integrator's main object (`action`/`assertion` with sentences), the generation/healing engine,
  the repository step cache, the failure taxonomy, and visibility (the `prettyplay` logger + hooks);
- the main gaps between contract and code: **no code exists at all** — 24 contract entities across
  8 cells are unimplemented, no `tests/`, no dependencies in `pyproject.toml`, no venv;
- strategy: strictly bottom-up over the cell DAG (config → reporting → failures → driver →
  cache → llm → engine → root), each entity a TDD task (contract tests → implementation →
  logic tests), after each cell — `goga lint` + a facade import check; the finale — integration
  tests of the full step cycle.

## Context

### Contract Surface

Cell order — bottom-up (confirmed by `goga schema`): `config, reporting, failures` —
leaves; `driver ← config`; `cache ← config, reporting`; `llm ← config, failures`;
`engine ← config, reporting, failures, driver, cache, llm`; `prettyplay ← all seven`.

#### Cell: `prettyplay/config`

**Entity: `Config`**
- Type: class (pydantic v2 BaseModel)
- Declared `location`: `prettyplay/config/models.py`
- Facade obligation: importable from `prettyplay.config`
- Signature: `Config(provider, browser, model, generation_model, classification_model, base_url, cache_root, generation_attempts, healing_attempts, send_screenshots)` — kw_only, all fields with empty defaults (`None` only for explicit absence — not used here)
- Properties (12): `provider -> str` (openai|anthropic, default openai), `browser -> str` (chromium|firefox|webkit, default chromium), `model -> str` (""), `generation_model -> str` (""), `classification_model -> str` (""), `base_url -> str` (""), `cache_root -> str` (""), `generation_attempts -> int` (3), `healing_attempts -> int` (2), `send_screenshots -> bool` (False), computed `effective_generation_model -> str` (generation_model or model), `effective_classification_model -> str`
- Semantic requirements: provider/browser — Literal validation, an invalid value is a loud actionable error naming the field; attempts — positive integers; secrets never in fields
- Imported dependencies: none (leaf)
- Annotation context: global `conventions`, `pydantic`

**Routine: `load_config`**
- Type: function
- Declared `location`: `prettyplay/config/loader.py`
- Facade obligation: importable from `prettyplay.config`
- Signature: `load_config(pyproject_path: str | None) -> config: Config`
- Semantic requirements: auto-search for pyproject.toml upward from cwd when `None`; tomllib (3.11+) / tomli (3.10); the `[tool.prettyplay]` section — missing = empty; env overrides `PRETTYPLAY_<SETTING_UPPER>` are applied **when the variable is set** (including an empty value); an empty `cache_root` → absolute `<pyproject_dir>/.prettyplay/cache/`; a pyproject.toml missing on auto-search — a loud error; LLM keys are never read from files

#### Cell: `prettyplay/reporting`

**Entity: `StepHooks`**
- Type: class (base of the callback contract)
- Declared `location`: `prettyplay/reporting/hooks.py`
- Facade obligation: importable from `prettyplay.reporting`
- Signature: `StepHooks()`
- Methods (8, all no-op `pass`): `on_step_started(step_text: str, step_type: str)`, `on_step_passed(step_text: str, step_type: str)`, `on_step_failed(step_text: str, step_type: str, error: str)`, `on_generation_started(step_text: str, attempt: int)`, `on_healing_started(step_text: str, category: str)`, `on_healed(step_text: str, explanation: str)`, `on_cache_saved(step_text: str, filename: str)`, `on_cache_skipped(step_text: str, reason: str)`
- Semantic requirements: synchronous invocation, no queues/retries; the integrator overrides the events it needs

**Entity: `StepReporter`**
- Type: class
- Declared `location`: `prettyplay/reporting/reporter.py`
- Facade obligation: importable from `prettyplay.reporting`
- Signature: `StepReporter(hooks: list[StepHooks])` — public attribute `self.hooks` (the list by reference, `add_hooks` appends to it)
- Methods: `emit(event: str, payload: dict[str, str | int])`
- Semantic requirements: the logger `logging.getLogger("prettyplay")`, event = message name, payload as `extra` context; levels: lifecycle INFO, `on_cache_skipped` and hook failure WARNING; fan-out to hooks in registration order `getattr(hook, event)(**payload)`; a hook exception → WARNING + skip, the run continues; sanitization of `extra` keys (reserved LogRecord attributes get the `ctx_` prefix — otherwise a `KeyError` from `Logger.makeRecord`; hooks receive the original kwargs); secrets are never logged

#### Cell: `prettyplay/failures`

**Entity: `PrettyplayError`** — base of the taxonomy
- Type: class (Exception)
- Declared `location`: `prettyplay/failures/errors.py`
- Facade obligation: importable from `prettyplay.failures`
- Signature: `PrettyplayError(message: str)`

**Mutation: `PrettyplayError::ProductDefectError(step_text: str, message: str)`**
- Properties: `step_text -> str`, `message -> str`
- Semantics: a real functional product defect; no retry/healing; the message names the expectation and the observed state

**Mutation: `PrettyplayError::IncurableStepError(step_text: str, reason: str, recommendation: str)`**
- Properties: `step_text -> str`, `reason -> str`, `recommendation -> str`
- Semantics: `str()` renders all three fields

**Mutation: `PrettyplayError::LlmUnavailableError(message: str)`**
- Properties: `message -> str` (names the provider)
- Semantics: blocks only generation/healing; cached steps keep executing; no retries

All four names are on the `prettyplay.failures` facade.

#### Cell: `prettyplay/driver`

**Entity: `DriverSession`**
- Type: class
- Declared `location`: `prettyplay/driver/session.py`
- Facade obligation: importable from `prettyplay.driver`
- Signature: `DriverSession(config: Config)`; Imports: `Config` from `prettyplay/config`
- Methods: `open_context() -> page: PageFacade` (lazy browser start exactly once per run: `sync_playwright().start()`, an engines dict `{chromium, firefox, webkit}`; every page gets its own isolated context), `close()` (browser + driver; safe when never started, idempotent)
- Errors: Playwright errors propagate as is

**Entity: `PageFacade`**
- Type: class
- Declared `location`: `prettyplay/driver/page.py`
- Facade obligation: importable from `prettyplay.driver`
- Signature: `PageFacade(page, context)` (a wrapper; the constructor is outside the generation contract)
- Properties: `url -> str`
- Methods: `open(url: str)` → `page.goto`; `find_by_role(role: str, name: str) -> element: LocatorFacade` → `get_by_role(role, name=name)`; `find_by_label(label: str) -> element: LocatorFacade`; `find_by_text(text: str) -> element: LocatorFacade`; `aria_snapshot() -> snapshot: str` → `page.locator("body").aria_snapshot()`; `screenshot() -> image: bytes` → `page.screenshot(full_page=True)`; `close()` → `context.close()` (the browser stays alive)

**Entity: `LocatorFacade`**
- Type: class
- Declared `location`: `prettyplay/driver/page.py` (the same file as PageFacade)
- Facade obligation: importable from `prettyplay.driver`
- Methods: `click()`; `fill(value: str)`; `select_option(value: str)`; `expect_visible()` → `expect(loc).to_be_visible()`; `expect_text(text: str)` → `expect(loc).to_contain_text(text)` (the equals|contains disjunction = contains); `expect_enabled()` → `expect(loc).to_be_enabled()`
- Constraints: no fixed delays; no raw Playwright object is handed out (returns — str / bytes / LocatorFacade); the facade is a backward-compatibility contract (extend, never rename/remove)

#### Cell: `prettyplay/cache`

**Routine: `normalize_step_text`**
- Declared `location`: `prettyplay/cache/text.py`
- Facade obligation: importable from `prettyplay.cache`
- Signature: `normalize_step_text(text: str) -> normalized: str`
- Algorithm: NFC → strip → collapse `\s+`→" " → casefold; a pure function (no I/O, no locale)

**Entity: `StepIdentity`**
- Declared `location`: `prettyplay/cache/models.py`
- Facade obligation: importable from `prettyplay.cache`
- Signature: `StepIdentity(cache_key: str, step_type: str, normalized_text: str)` — pydantic kw_only
- Properties: `cache_key -> str`, `step_type -> str`, `normalized_text -> str`, `filename -> str` (computed: `"\x1f".join((cache_key, step_type, normalized_text))` → sha256 hexdigest → `f"{digest}.py"`)

**Entity: `CachedStep`**
- Declared `location`: `prettyplay/cache/models.py`
- Facade obligation: importable from `prettyplay.cache`
- Signature: `CachedStep(identity: StepIdentity, code: str, created_at: str)` — pydantic kw_only
- Requirement: the cache file is a valid Python module (metadata, then code); no library version field

**Entity: `StepCache`**
- Declared `location`: `prettyplay/cache/store.py`
- Facade obligation: importable from `prettyplay.cache`
- Signature: `StepCache(config: Config, path: str | None, reporter: StepReporter)`; Imports: `Config` from `prettyplay/config`, `StepReporter` + usages `hooks` from `prettyplay/reporting`
- Properties: `root -> str`, `writable -> bool` (a lazy check: mkdir parents exist_ok + `os.access(W_OK)`; OSError → False)
- Methods: `load(identity) -> step: CachedStep | None` (a missing file → None; the protective parse block: header constants `STEP_TEXT`/`CACHE_KEY`/`STEP_TYPE`/`CREATED_AT` via `ast.literal_eval`, the tail from the first occurrence of `def step(` without the leading newline; any structural error or metadata mismatch with the identity → None — a protective miss, the run does not fail); `save(step: CachedStep)` (read-only → `emit("on_cache_skipped", reason="read-only cache")` and return; serialization: the header's repr literals + code; `tempfile.mkstemp(dir=target_dir, prefix=".tmp-", suffix=".py")` + fsync + `os.replace`; a Windows retry 3×0.1 s on PermissionError, then skip + `on_cache_skipped(reason="cache target busy")`; success → `emit("on_cache_saved", {"step_text", "filename"})`)

**Entity: `RunBudgets`**
- Declared `location`: `prettyplay/cache/budgets.py`
- Facade obligation: importable from `prettyplay.cache`
- Signature: `RunBudgets(generation_limit: int, healing_limit: int)`
- Methods: `try_generation(identity: StepIdentity) -> allowed: bool`, `try_healing(identity: StepIdentity) -> allowed: bool`
- Semantics: a per-run registry (one process), the key — `identity.filename`; separate gen/heal pools; budgets are not reset between tests; no persistence

#### Cell: `prettyplay/llm`

**Entity: `LlmProvider`** (port)
- Declared `location`: `prettyplay/llm/provider.py`
- Facade obligation: importable from `prettyplay.llm`
- Methods: `generate_step_code(prompt, step_text, previous_steps, snapshot, screenshot, page_api, existing_code, error) -> code: str`; `classify_failure(prompt, step_text, code, error, snapshot, screenshot) -> classification: FailureClassification`
- Semantics: the prompt is passed verbatim as the system message; one request per attempt (budgets live outside the provider); a service failure → `LlmUnavailableError` naming the provider; the generated code contains no provider constructs

**Mutation: `LlmProvider::OpenAiProvider(config: Config)`**
- Declared `location`: `prettyplay/llm/openai_provider.py`
- Facade obligation: importable from `prettyplay.llm`
- Parity with AnthropicProvider: a lazy client (`OPENAI_API_KEY` on the first request; missing/empty → `LlmUnavailableError("llm unavailable: openai: OPENAI_API_KEY is not set")`); `client.chat.completions.create(model=effective_generation_model, messages=[system, user])`; the screenshot — the block `{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}`; extraction of `response.choices[0].message.content`; `openai.OpenAIError` → `LlmUnavailableError ... from e`

**Mutation: `LlmProvider::AnthropicProvider(config: Config)`**
- Declared `location`: `prettyplay/llm/anthropic_provider.py`
- Facade obligation: importable from `prettyplay.llm`
- Full parity: `ANTHROPIC_API_KEY`; `client.messages.create(model=..., system=prompt, max_tokens=1024, messages=[user])`; the screenshot — the block `{"type":"image","source":{"type":"base64","media_type":"image/png","data":...}}`; extraction of `message.content[0].text`; `anthropic.AnthropicError` → `LlmUnavailableError ... from e`

**Routine: `create_provider`**
- Declared `location`: `prettyplay/llm/provider.py`
- Facade obligation: importable from `prettyplay.llm`
- Signature: `create_provider(config: Config) -> provider: LlmProvider`
- Semantics: `"openai"` → OpenAiProvider, `"anthropic"` → AnthropicProvider, anything else — `ValueError` listing the supported ones (belt and suspenders over the Literal)

**Entity: `FailureClassification`**
- Declared `location`: `prettyplay/llm/models.py`
- Facade obligation: importable from `prettyplay.llm`
- Signature: `FailureClassification(category: str, explanation: str, recommendation: str)` — pydantic kw_only
- Properties: `category -> str` (rot | product_defect | incurable), `explanation -> str`, `recommendation -> str`

#### Cell: `prettyplay/engine`

**Routine: `run_step_code`**
- Declared `location`: `prettyplay/engine/execution.py`
- Facade obligation: importable from `prettyplay.engine`
- Signature: `run_step_code(code: str, page: PageFacade)`
- Algorithm: `namespace = {}`; `exec(compile(code, "<prettyplay-step>", "exec"), namespace)`; `fn = namespace["step"]`; `fn(page)` — exceptions propagate as is (no swallow, no retry, no LLM, no network); the module is not registered in `sys.modules`

**Entity: `StepGenerator`**
- Declared `location`: `prettyplay/engine/generator.py`
- Facade obligation: importable from `prettyplay.engine`
- Signature: `StepGenerator(config: Config, provider: LlmProvider, cache: StepCache, budgets: RunBudgets, reporter: StepReporter)`
- Methods: `generate(identity, step_text, previous_steps, page) -> step: CachedStep`; `regenerate(identity, step_text, previous_steps, page, existing_code, error) -> step: CachedStep`
- Semantics: PAGE_API_SURFACE — a frozen string constant of the facade surface; the attempt loop with `try_generation`/`try_healing`, `emit("on_generation_started", {"step_text", "attempt": n})`, snapshot (+screenshot under the flag), the first attempt `existing_code=None, error=None`, every retry — a regeneration request carrying the failed candidate and the fresh error; success → `CachedStep(..., created_at=date.today().isoformat())` → `cache.save`; `LlmUnavailableError` — immediate propagation; exhaustion → `IncurableStepError`
- Inline Usages: `generation_prompt`, `classification_prompt` (texts — in the respective task, verbatim)

**Entity: `StepHealer`**
- Declared `location`: `prettyplay/engine/healer.py`
- Facade obligation: importable from `prettyplay.engine`
- Signature: `StepHealer(config: Config, provider: LlmProvider, generator: StepGenerator, cache: StepCache, budgets: RunBudgets, reporter: StepReporter)`
- Methods: `heal(step: CachedStep, error: str, previous_steps: list[str], page: PageFacade) -> step: CachedStep`
- Semantics: assemble the classification inputs → `classify_failure` (classification_prompt) → `emit("on_healing_started", {"step_text", "category"})` → product_defect → `ProductDefectError` (the cache untouched); incurable → `IncurableStepError(step_text, reason, recommendation)`; rot → `generator.regenerate(...)` → `emit("on_healed", {"step_text", "explanation"})` → return healed; anti-masking

#### Cell: `prettyplay` (root)

**Entity: `PrettyTest`**
- Declared `location`: `prettyplay/scenario.py`
- Facade obligation: importable from `prettyplay`
- Signature: `PrettyTest(cache_key: str, cache_path: str | None)`
- Properties: `cache_key -> str`
- Methods: `action(text: str)`, `assertion(text: str)`, `add_hooks(hooks: StepHooks)`, `close()`; the context-manager protocol (`__enter__`/`__exit__` → close, does not swallow exceptions)
- Semantics: composition of per-test objects over `get_runtime()`; the page lazily on the first step; construction is cheap; no cross-test state

**Entity: `StepExecutor`**
- Declared `location`: `prettyplay/executor.py`
- Facade obligation: importable from `prettyplay`
- Signature: `StepExecutor(cache_key: str, cache: StepCache, generator: StepGenerator, healer: StepHealer, budgets: RunBudgets, reporter: StepReporter)`
- Methods: `execute(step_text: str, step_type: str, page: PageFacade)`
- Semantics: on_step_started → identity → load → hit: run_step_code (failure → heal with context) | miss: generate → append the scenario context → on_step_passed; any failure → on_step_failed + propagation by kind; documented interpretation: classification (and ProductDefectError) — only after the step's first successful generation and caching; a step that never generated yields IncurableStepError

**Entity: `PrettyplayRuntime`**
- Declared `location`: `prettyplay/runtime.py`
- Facade obligation: importable from `prettyplay`
- Signature: `PrettyplayRuntime(config: Config)`
- Properties: `config -> Config` (eager), `budgets -> RunBudgets` (eager), `driver -> DriverSession` (lazily), `provider -> LlmProvider` (lazily, via `create_provider`)
- Methods: `open_page() -> page: PageFacade`, `close()`
- Semantics: construction without LLM credentials

**Routine: `get_runtime`**
- Declared `location`: `prettyplay/runtime.py`
- Facade obligation: importable from `prettyplay`
- Signature: `get_runtime() -> runtime: PrettyplayRuntime` — a process-wide singleton (the module global `_runtime`)

### Interaction Diagram (verbatim from the design)

```
                    integrator (test)
                          │  PrettyTest(cache_key[, cache_path]) / action / assertion
                          ▼
┌───────────────────────────── prettyplay (root) ───────────────────────────────────────┐
│                                                                                      │
│  PrettyTest ──get_runtime()──► PrettyplayRuntime (process-wide singleton)            │
│     │                            │         │         │                               │
│     │ StepReporter(hooks=[])  Config   DriverSession RunBudgets    LlmProvider        │
│     │      ▲                (load_config)   │         │         (create_provider)    │
│     │      │ emit(...)                     ▼         │        ┌─ OpenAiProvider      │
│     │      ├──────────────► logger "prettyplay" + StepHooks     └─ AnthropicProvider  │
│     │                                                                                 │
│     └─► StepExecutor.execute(step_text, step_type, page)                             │
│              │ 1. identity = StepIdentity(cache_key, step_type,                       │
│              │      normalize_step_text(text))                                        │
│              │ 2. cache.load(identity) ──────────── hit ──► run_step_code(code, page) │
│              │                                          │                    │        │
│              │                                     success │          failure │        │
│              │                                          ▼                    ▼        │
│              │                                   append scenario   StepHealer.heal    │
│              │ ─────────── miss ──► StepGenerator.generate    (step, error,   prev,  │
│              │                         │  ▲   retry            page)                │
│              │                         │  └─────────────┘        │ classify_failure  │
│              │                    cache.save(CachedStep)         ▼                   │
│              │                                              verdict ─┬─ rot ──►        │
│              │  DriverSession.open_context() ──► PageFacade        │   regenerate    │
│              │  (lazily, on the test's first step)               ├─ product_defect   │
│              │                                                  ▶ ProductDefectError│
│              │                                                  └─ incurable        │
│              │                                                     ▶ IncurableStepError
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Runtime object creation order: `load_config` → `PrettyplayRuntime` (config eagerly;
`RunBudgets` eagerly; `DriverSession` and `LlmProvider` — lazily) → per test: `StepReporter` →
`StepCache` → `StepGenerator` → `StepHealer` → `StepExecutor` → lazily `PageFacade` (the
first step).

### Re-exports

There are no `->Name: {}` DSL blocks in the manifests. Facade obligations arise from the
Python language rules (`__init__.py` + `__all__`) and the design's Additional Instructions —
the full list:

| Package | Re-export (`__all__`) |
|---|---|
| `prettyplay` | `PrettyTest` (scenario), `StepExecutor` (executor), `PrettyplayRuntime`, `get_runtime` (runtime) |
| `prettyplay.config` | `Config` (models), `load_config` (loader) |
| `prettyplay.reporting` | `StepHooks` (hooks), `StepReporter` (reporter) |
| `prettyplay.failures` | `PrettyplayError`, `ProductDefectError`, `IncurableStepError`, `LlmUnavailableError` (errors) |
| `prettyplay.driver` | `DriverSession` (session), `PageFacade`, `LocatorFacade` (page) |
| `prettyplay.cache` | `normalize_step_text` (text), `StepIdentity`, `CachedStep` (models), `StepCache` (store), `RunBudgets` (budgets) |
| `prettyplay.llm` | `LlmProvider`, `create_provider` (provider), `OpenAiProvider` (openai_provider), `AnthropicProvider` (anthropic_provider), `FailureClassification` (models) |
| `prettyplay.engine` | `run_step_code` (execution), `StepGenerator` (generator), `StepHealer` (healer) |

Imports inside the package are relative only; the facade check after each cell:
`.venv/bin/python -c "from prettyplay.<cell> import <entity>"`.

### Usages Context

- **`conventions`** (`.goga/usages/conventions.md`) — mandatory code and test rules:
  Python 3.10+, relative imports inside the package, pydantic v2 `kw_only=True` + empty
  defaults (`None` only for explicit absence), logging with context (`extra`),
  Google docstrings, ruff, a mirrored tests/ structure (`prettyplay/cache/store.py` →
  `tests/cache/test_store.py`, root modules — directly in `tests/`), mocks only at
  external boundaries, file-based tests — `tmp_path` only. Validation: `pytest tests/ -x`,
  `ruff check <src>/`, the facade `python -c "from package import Entity"`. All third-party
  libraries — in `pyproject.toml` with a minimal version. Relevant to **every** task.
- **`pydantic`** (`.goga/usages/cooks/pydantic.md`) — v2 model patterns
  (`model_config = ConfigDict(kw_only=True)`, empty defaults) and TOML loading with
  the tomli fallback for 3.10 (`sys.version_info >= (3, 11)` → `tomllib`, otherwise `tomli`).
  Relevant to: `Config`, `load_config`, `StepIdentity`, `CachedStep`, `FailureClassification`.
- **`playwright`** (`.goga/usages/cooks/playwright.md`) — sync-API lifecycle
  (`sync_playwright()`), the browser matrix `{chromium, firefox, webkit}` via a dict,
  locators with auto-wait, `expect(...)` for waits, `page.locator("body").aria_snapshot()`,
  an isolated context per test, no `time.sleep` at all. Relevant to: `DriverSession`,
  `PageFacade`, `LocatorFacade`.
- **`openai`** (`.goga/usages/cooks/openai.md`) — SDK patterns: keys only from env,
  `client.chat.completions.create(model=..., messages=[system, user])`, extraction of
  `choices[0].message.content`, mapping `OpenAIError` → `LlmUnavailableError`. Relevant to:
  `OpenAiProvider`.
- **`anthropic`** (`.goga/usages/cooks/anthropic.md`) — SDK patterns: keys only from env,
  `client.messages.create(model=..., max_tokens=1024, system=..., messages=[user])`,
  extraction of `content[0].text`, mapping `AnthropicError` → `LlmUnavailableError`.
  Relevant to: `AnthropicProvider`.
- **`generation_prompt`** (inline, engine) — the generation system prompt; fixes the
  response form (`def step(page) -> None:`), the inputs (STEP/PREVIOUS STEPS/PAGE SNAPSHOT/
  SCREENSHOT/PAGE API/CODE/ERROR), and the rules (facade surface only, no imports, no
  delays). The text is given verbatim in Task 17. Relevant to: `StepGenerator`.
- **`classification_prompt`** (inline, engine) — the classification system prompt; the
  answer is a single line `category | explanation | recommendation`, categories
  rot/product_defect/incurable. The text is given verbatim in Task 17. Relevant to:
  `StepHealer`.

### Imported Usages

- **`hooks`** from `prettyplay/reporting` (`prettyplay/reporting/.usages/hooks.md`) — the
  event contract: method names = event names; payload values — strings, the
  `on_generation_started` attempt counter — int. Consumers: cache (cache-write events),
  the root (`add_hooks`).
- **`taxonomy`** from `prettyplay/failures` (`prettyplay/failures/.usages/taxonomy.md`) —
  the three failure kinds and their fields (including `info.value.recommendation` on
  IncurableStepError); consumers: llm (LlmUnavailableError), engine
  (ProductDefectError/IncurableStepError), the root (propagation by kind).
- **`generation`, `healing`** from `prettyplay/engine`
  (`prettyplay/engine/.usages/{generation,healing}.md`) — the engine loops that
  `StepExecutor` delegates to; budgets — one run-scoped registry with separate per-step
  limits (3 and 2 by default); `heal` accepts `previous_steps`.
- **`facade`** from `prettyplay/driver` (`prettyplay/driver/.usages/facade.md`) — the
  single source of the PAGE API surface for generation requests (PAGE_API_SURFACE in
  generator.py is synchronized with this surface).
- **`classification`** from `prettyplay/llm` (`prettyplay/llm/.usages/classification.md`) —
  the healing-decision categories (rot / product_defect / incurable) and the protective
  incurable default.

### Local Usages

The design requires no new `.usages/` files ("the existing domain split covers all
entities; edits stay within domains"). The existing 13 files are current after the design
stage:

| File | Domain | Status |
|---|---|---|
| `prettyplay/.usages/steps.md` | the `PrettyTest` API (action/assertion) | current |
| `prettyplay/.usages/lifecycle.md` | composition, add_hooks before the first step, failure kinds | current |
| `prettyplay/config/.usages/configuration.md` | schema, 10 env overrides, defaults | current |
| `prettyplay/reporting/.usages/hooks.md` | the hook contract | updated by the design stage (int attempt) |
| `prettyplay/failures/.usages/taxonomy.md` | taxonomy | current (after D3) |
| `prettyplay/driver/.usages/facade.md` | the facade surface | current |
| `prettyplay/cache/.usages/addressing.md` | step addressing | current |
| `prettyplay/cache/.usages/storage.md` | file format, atomicity | current |
| `prettyplay/cache/.usages/budgets.md` | the attempt registry | current |
| `prettyplay/llm/.usages/providers.md` | provider parity | current |
| `prettyplay/llm/.usages/classification.md` | the classification verdict | current |
| `prettyplay/engine/.usages/generation.md` | the generation loop | current |
| `prettyplay/engine/.usages/healing.md` | the healing loop | updated by the design stage (previous_steps, separate limits) |

The plan has no tasks to create/update usage files. Implementation constraint: when the
driver facade surface changes, synchronize `PAGE_API_SURFACE` (generator.py) and
`prettyplay/driver/.usages/facade.md` — but the facade itself does not change in this
plan.

### External Dependencies

- **pydantic ≥2.7** — all data models (`Config`, `StepIdentity`, `CachedStep`, `FailureClassification`)
- **playwright ≥1.44** — the browser driver (sync API)
- **openai ≥1.30** — the OpenAI provider SDK
- **anthropic ≥0.28** — the Anthropic provider SDK
- **tomli ≥2.0** (the marker `python_version < "3.11"`) — TOML for Python 3.10
- Test (already declared in `pyproject.toml` → `[project.optional-dependencies].test`):
  pytest ≥8.0, pytest-cov ≥5.0, pytest-mock ≥3.10, ruff ≥0.15.0
- Process tooling: venv (`python3 -m venv .venv`), `goga lint` (cell verification)

## Facts

- Greenfield: `prettyplay/` contains only an empty `__init__.py`; cells contain only
  `CODEMANIFEST` + `.usages/`; no `tests/` directory; no venv.
- `pyproject.toml` exists: `[project]` name=prettyplay, `requires-python >=3.10`,
  `dependencies = []` (empty — dependencies must be added), test-extras declared,
  `[tool.ruff]` line-length=120, mccabe max-complexity=10, `[tool.pytest.ini_options]`
  testpaths=["tests"], addopts="-v --tb=short".
- The local interpreter is Python 3.12.14; pytest/ruff/pydantic are not installed
  globally (a venv is needed, `.venv` is already in `.gitignore`).
- `goga lint` — 8 cells, 0 errors (contracts valid and read-only).
- `goga config language` — python (rules: PascalCase classes, snake_case functions/methods,
  the facade via `__all__`, type hints mandatory, `self` excluded from contract signatures).
- Step cache file: the header `STEP_TEXT` / `CACHE_KEY` / `STEP_TYPE` / `CREATED_AT`
  (repr literals), then code of the fixed form `def step(page) -> None:`; no version field.
- Design runtime invariants: runtime and PrettyTest construction requires no LLM
  credentials; the cache path does not touch the provider; one provider request per
  attempt; `LlmUnavailableError` without retries; keys only from env, never in logs.

## Gap Analysis

- **Missing contract entities**: all 24 (see Contract Surface) — implemented from scratch.
- **Missing facade exposure**: all 8 cell `__init__.py` files (the 7 sub-cells do not
  exist, the root is empty) + `__all__`.
- **Incorrect `location` placement**: none — no files yet; `location` values from
  CODEMANIFEST are mandatory literally (a file at the cell directory level, with the
  extension).
- **API mismatches / Behavioral mismatches**: no existing code.
- **Existing code that can be reused**: `pyproject.toml` (build, ruff, pytest config,
  test-extras), `.gitignore` (needs `.prettyplay/` added), the empty
  `prettyplay/__init__.py`.
- **Test coverage gaps**: 100% — no tests; the design fixes 38 test scenarios
  (18 positive, 11 negative, 9 edge) + additional ones per conventions (facade
  delegation, anthropic parity, executor unit).
- **Missing visibility in workspace or git**: dependencies not in `pyproject.toml`
  (`dependencies = []`); no venv created.

---

## Tasks

> **Package ordering rule**: tasks execute strictly in numeric order; cells complete
> bottom-up (config → reporting → failures → driver → cache → llm → engine → root).
> Inside each coding task, contract tests are written first (TDD workflow).
> One ralphex cycle = one task. CODEMANIFEST files are read-only.

### Task 1: Project infrastructure — dependencies, venv, test skeleton (infrastructure)

Context: prepare the environment for all subsequent tasks. The project is greenfield: in
`pyproject.toml` `dependencies = []`, no venv, no `tests/` directory. Per conventions, all
third-party libraries must be in `pyproject.toml` with a minimal version; all code runs in
a venv; tests mirror the package structure (`tests/<cell>/test_<module>.py`, root modules —
directly in `tests/`, every directory with an `__init__.py`). The default cache root
`<repo root>/.prettyplay/cache/` must be in `.gitignore`.

**Usages relevant to this task:**
- `conventions`: the Development sections (venv, pyproject), Dependencies (minimal
  versions), Test Structure (mirroring, `__init__.py` in every test directory).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] Add runtime dependencies to `pyproject.toml` → `[project].dependencies`:
      `"pydantic>=2.7"`, `"playwright>=1.44"`, `"openai>=1.30"`, `"anthropic>=0.28"`,
      `"tomli>=2.0; python_version < '3.11'"` (marker quotes — single inside the
      double-quoted TOML string)
- [x] Make sure `[project.optional-dependencies].test` already contains pytest,
      pytest-cov, pytest-mock, ruff (add nothing if already present)
- [x] Extend `.gitignore` with the line `.prettyplay/` (the repository step cache is not
      committed)
- [x] Create a venv and install the package with test dependencies:
      `python3 -m venv .venv && .venv/bin/pip install -e ".[test]"`
- [x] Create the test skeleton (empty packages): `tests/__init__.py`,
      `tests/conftest.py` (empty), and for each cell
      `tests/{config,reporting,failures,driver,cache,llm,engine}/__init__.py`
- [x] Verify: `.venv/bin/pytest --collect-only tests/` completes without collection
      errors (0 tests is normal at this stage)
- [x] Verify: `.venv/bin/ruff check prettyplay/ tests/` — 0 errors
- [x] Lint: `.venv/bin/ruff check prettyplay/ tests/` — fix formatting if necessary

### Task 2: `Config` — validated settings (prettyplay/config/models.py)

Context: the contract entity `Config` of cell `prettyplay/config`, `location: models.py`,
facade obligation `from prettyplay.config import Config` (create
`prettyplay/config/__init__.py` with the re-export and `__all__`). pydantic v2 BaseModel,
`model_config = ConfigDict(kw_only=True)`, all fields with empty defaults. Validation:
`provider` — `Literal["openai", "anthropic"]` (default "openai"); `browser` —
`Literal["chromium", "firefox", "webkit"]` (default "chromium"); `generation_attempts=3`,
`healing_attempts=2` — PositiveInt; the remaining string fields ""; `send_screenshots=False`.
Computed properties: `effective_generation_model = generation_model or model`,
`effective_classification_model = classification_model or model`. `None` is not used.
Secrets never in fields.

**Usages relevant to this task:**
- `pydantic`: kw_only models, empty defaults.
- `conventions`: Google docstrings, type hints, ruff.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
1. pydantic v2 BaseModel, model_config = ConfigDict(kw_only=True)
   → all fields with empty defaults: provider="openai", browser="chromium", model="",
     generation_model="", classification_model="", base_url="", cache_root="",
     generation_attempts=3, healing_attempts=2, send_screenshots=False
2. Validation: provider — Literal["openai","anthropic"]; browser — Literal["chromium","firefox","webkit"];
   attempts — PositiveInt (pydantic), the message includes the field name
   → an invalid value = a loud actionable error
3. Computed properties (cached_property or plain):
   effective_generation_model = generation_model if generation_model else model
   effective_classification_model = classification_model if classification_model else model
```

- [x] **STEP 0 (Declaration)**: declare that Task 2 — `Config` — is being executed
- [x] **Contract tests** (`tests/config/test_models.py`): `from prettyplay.config import Config`
      works; `Config` is a pydantic BaseModel; construction ONLY with keyword arguments
      (positional `Config("openai")` → TypeError); the instance exposes all 12 properties
      (`provider`, `browser`, `model`, `generation_model`, `classification_model`, `base_url`,
      `cache_root`, `generation_attempts`, `healing_attempts`, `send_screenshots`,
      `effective_generation_model`, `effective_classification_model`). Expected failure at
      this stage
- [x] **Code**: create `prettyplay/config/models.py` with `Config` per the algorithm above
      (a Google docstring on the class; type hints mandatory)
- [x] **Code**: create `prettyplay/config/__init__.py` — `from .models import Config`,
      `__all__ = ["Config"]`
- [x] **Interface verification**: `.venv/bin/pytest tests/config/test_models.py -v` — all
      contract tests pass; the facade: `.venv/bin/python -c "from prettyplay.config import Config"`
- [x] **Logic tests** (`tests/config/test_models.py`):
      - `test_config_defaults_valid` — Setup: nothing (a pure model). Input: `Config()`.
        Assertions (verbatim from the design):
        ```
        config.provider == "openai"
        config.browser == "chromium"
        config.generation_attempts == 3 and config.healing_attempts == 2
        config.send_screenshots is False
        config.effective_generation_model == config.model == ""
        ```
      - `test_config_invalid_provider_fails_loudly` — Input: `Config(provider="yandex")`.
        Assertions: `pytest.raises(pydantic.ValidationError)`; `"provider"` in the error
        text; the allowed values listed ("openai", "anthropic")
      - an additional edge (per conventions): `Config(generation_attempts=0)` →
        ValidationError naming the field; `Config(browser="ie")` → ValidationError
- [x] **Debugging**: `.venv/bin/pytest tests/config/ -x` — fix the implementation (not the
      tests) until everything passes
- [x] **Contract re-verification**: the `prettyplay.config` facade imports `Config` through
      `__all__`; kw_only; the 12 properties in place; behavior matches the contract
- [x] **Lint**: `.venv/bin/ruff check prettyplay/config/ tests/config/` — fix formatting

### Task 3: `load_config` — pyproject.toml loading with env overrides (prettyplay/config/loader.py)

Context: the Routine of cell `prettyplay/config`, `location: loader.py`, the facade
`from prettyplay.config import load_config` (add to the cell's existing `__init__.py`).
Signature: `load_config(pyproject_path: str | None) -> Config`. Uses `Config` from
`prettyplay/config/models.py` (the relative import `from .models import Config`).
The config cell completes with this task.

**Usages relevant to this task:**
- `pydantic`: TOML loading — `sys.version_info >= (3, 11)` → `import tomllib`, otherwise
  `import tomli as tomllib`; `tomllib.load(path.open("rb"))`.
- `conventions`: file-based tests — `tmp_path` only; env — `monkeypatch`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
1. path = Path(pyproject_path) if given, otherwise the first existing
   pyproject.toml among [Path.cwd(), *Path.cwd().parents]
2. IF Python >= 3.11: import tomllib ELSE: import tomli as tomllib
3. data = tomllib.load(path.open("rb")); section = data.get("tool", {}).get("prettyplay", {})
4. FOR each of the 10 fields: env PRETTYPLAY_<FIELD_UPPER> set (including an empty value) → override
5. merged = {**section, **env_overrides}
6. cache_root empty in merged → merged["cache_root"] = str(path.parent / ".prettyplay" / "cache")
7. RETURN Config(**merged)
```

Design trace checkpoints (walk the implementation): an env override applies when
`os.environ.get(name) is not None` (the "when the variable is set" contract — including an
empty value; an empty string in a str field is legal, an empty one in an int/bool field —
a loud ValidationError naming the setting — pydantic lax mode does the coercion: "3"→3,
"false"→False); a missing section is not an error; a pyproject.toml missing on auto-search —
the loud error "pyproject.toml not found"; a ValidationError propagates.

- [x] **STEP 0 (Declaration)**: declare that Task 3 — `load_config` — is being executed
- [x] **Contract tests** (`tests/config/test_loader.py`):
      `from prettyplay.config import load_config` is available; the signature admits
      `load_config(None)` and `load_config(str(path))`; returns `Config`. Expected failure
      at this stage
- [x] **Code**: create `prettyplay/config/loader.py` per the algorithm above; env overrides
      for all 10 fields (`PRETTYPLAY_PROVIDER`, `PRETTYPLAY_BROWSER`, `PRETTYPLAY_MODEL`,
      `PRETTYPLAY_GENERATION_MODEL`, `PRETTYPLAY_CLASSIFICATION_MODEL`, `PRETTYPLAY_BASE_URL`,
      `PRETTYPLAY_CACHE_ROOT`, `PRETTYPLAY_GENERATION_ATTEMPTS`, `PRETTYPLAY_HEALING_ATTEMPTS`,
      `PRETTYPLAY_SEND_SCREENSHOTS`)
- [x] **Code**: `prettyplay/config/__init__.py` — add `from .loader import load_config`,
      `__all__ = ["Config", "load_config"]`
- [x] **Interface verification**: `.venv/bin/pytest tests/config/test_loader.py -v`;
      the facade: `.venv/bin/python -c "from prettyplay.config import load_config"`
- [x] **Logic tests** (`tests/config/test_loader.py`):
      - `test_load_config_reads_section_and_env_overrides` — Setup:
        `tmp_path/pyproject.toml`
        ```toml
        [tool.prettyplay]
        provider = "openai"
        browser = "chromium"
        model = "gpt-5"
        ```
        `monkeypatch.setenv("PRETTYPLAY_BROWSER", "firefox")`;
        `monkeypatch.setenv("PRETTYPLAY_GENERATION_ATTEMPTS", "5")`.
        Input: `load_config(pyproject_path=str(tmp_path / "pyproject.toml"))`.
        Assertions (verbatim):
        ```
        config.model == "gpt-5"
        config.browser == "firefox"            # env overrides TOML
        config.generation_attempts == 5        # str→int coercion
        config.cache_root == str(tmp_path / ".prettyplay" / "cache")
        ```
      - `test_load_config_no_pyproject_fails_loudly` — Setup: an isolated working
        directory without a pyproject.toml up the tree (`monkeypatch.chdir(tmp_path)`;
        if the environment is non-deterministic — `mock.patch` the upward search from
        cwd).
        Input: `load_config(pyproject_path=None)`.
        Assertions: `pytest.raises` with the text `"pyproject.toml not found"`
      - `test_load_config_missing_section_yields_defaults` — Setup:
        `tmp_path/pyproject.toml` without `[tool.prettyplay]` (e.g. only `[project]`).
        Assertions: `config.provider == "openai"; config.generation_attempts == 3`
- [x] **Debugging**: `.venv/bin/pytest tests/config/ -x` — fix the implementation until
      green
- [x] **Contract re-verification**: the config cell facade is complete (`Config`,
      `load_config`); "never read LLM API keys from any file" — the function reads
      nothing but TOML
- [x] **Lint**: `.venv/bin/ruff check prettyplay/config/ tests/config/`
- [x] The config cell is complete: `goga lint` — 0 errors; the facade check:
      `.venv/bin/python -c "from prettyplay.config import Config, load_config"`

### Task 4: `StepHooks` + `StepReporter` — visibility (prettyplay/reporting/{hooks,reporter}.py)

Context: two entities of cell `prettyplay/reporting`. `StepHooks` (`location: hooks.py`) —
the base of the callback contract with 8 no-op methods. `StepReporter`
(`location: reporter.py`) — the single point of visibility: `__init__(hooks:
list[StepHooks])` stores the list by reference in the public attribute `self.hooks`; the
method `emit(event, payload)` writes to the logger `logging.getLogger("prettyplay")`
and does a synchronous fan-out to the hooks. Facade: `from prettyplay.reporting import
StepHooks, StepReporter` (create `__init__.py`). The reporting cell completes with this
task. No link to `hooks.md` from Imports is needed — those are consumer cells.

**Usages relevant to this task:**
- `conventions`: logging — `logging.getLogger("prettyplay")`, context via `extra`,
  lowercase messages, INFO/WARNING levels; Google docstrings.
- `hooks` (imported usage, to understand the payload contract): values — strings, the
  attempt counter — int.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm `StepReporter` (verbatim from the design):
```
1. __init__(hooks: list[StepHooks]) — stores the list by reference in the public attribute
   self.hooks (PrettyTest's add_hooks appends to the same list)
2. emit(event, payload):
   a. level = WARNING if event in {"on_cache_skipped"} else INFO
      (a hook failure is logged separately as WARNING)
   b. extra = {("ctx_" + key) if key in _LOG_RECORD_RESERVED else key: value
      for key, value in payload.items()}; logger.log(level, event, extra=extra)
      (_LOG_RECORD_RESERVED — a frozen set of reserved LogRecord attributes:
      name, msg, message, args, levelname, levelno, pathname, filename, module, exc_info,
      funcName, lineno, created, msecs, relativeCreated, thread, threadName, process,
      processName, stack_info, asctime, taskName; the sanitization concerns only the log
      record — otherwise Logger.makeRecord throws the KeyError "Attempt to overwrite … in
      LogRecord"; the `filename` key of the on_cache_saved event is logged as ctx_filename)
   c. FOR hook in self.hooks (registration order):
        try: getattr(hook, event)(**payload)
        except Exception: logger.warning("hook call failed", extra={"event": event,
              "hook": type(hook).__name__})
```

The `StepHooks` methods (8, bodies `pass`): `on_step_started(step_text, step_type)`,
`on_step_passed(step_text, step_type)`, `on_step_failed(step_text, step_type, error)`,
`on_generation_started(step_text, attempt)`, `on_healing_started(step_text, category)`,
`on_healed(step_text, explanation)`, `on_cache_saved(step_text, filename)`,
`on_cache_skipped(step_text, reason)`.

- [x] **STEP 0 (Declaration)**: declare that Task 4 — StepHooks + StepReporter — is being
      executed
- [x] **Contract tests** (`tests/reporting/test_hooks.py`,
      `tests/reporting/test_reporter.py`): `from prettyplay.reporting import StepHooks,
      StepReporter`; `StepHooks` has all 8 methods with exact signatures (checked via
      `inspect.signature`); calling each no-op method of the base class does not fail;
      `StepReporter(hooks=[])` constructs; `reporter.hooks` — a public list. Expected
      failure
- [x] **Code**: create `prettyplay/reporting/hooks.py` (class `StepHooks`, 8 no-op
      methods)
- [x] **Code**: create `prettyplay/reporting/reporter.py` (class `StepReporter`,
      `_LOG_RECORD_RESERVED: frozenset[str]`, method `emit`) per the algorithm above
- [x] **Code**: create `prettyplay/reporting/__init__.py` —
      `from .hooks import StepHooks`, `from .reporter import StepReporter`,
      `__all__ = ["StepHooks", "StepReporter"]`
- [x] **Interface verification**: `.venv/bin/pytest tests/reporting/ -v`; the facade:
      `.venv/bin/python -c "from prettyplay.reporting import StepHooks, StepReporter"`
- [x] **Logic tests**:
      - `test_emit_dispatches_event_to_hooks_in_order`
        (`tests/reporting/test_reporter.py`) — Setup: two recorder hooks
        `RecordingHook(StepHooks)` sharing the list `calls`;
        reporter = `StepReporter(hooks=[h1, h2])`.
        Input: `reporter.emit("on_step_started", {"step_text": "открыть страницу", "step_type": "action"})`.
        Assertions (verbatim):
        ```
        calls == [("h1", "on_step_started", "открыть страницу", "action"),
                  ("h2", "on_step_started", "открыть страницу", "action")]
        caplog: one INFO record, logger == "prettyplay", msg == "on_step_started",
                record.step_text == "открыть страницу"
        ```
      - `test_raising_hook_is_skipped_and_logged` — Setup: h1 — a hook raising
        RuntimeError on on_step_passed; h2 — a recorder; `caplog`.
        Input: `reporter.emit("on_step_passed", {"step_text": "s", "step_type": "action"})`.
        Assertions (verbatim):
        ```
        the exception did not propagate out
        h2 received the event
        caplog has a WARNING from the "prettyplay" logger
        ```
      - an additional edge (sanitization, from design R1): `emit("on_cache_saved",
        {"step_text": "s", "filename": "abc.py"})` does not throw KeyError; the caplog
        record has the attribute `ctx_filename == "abc.py"`; the hook received the
        original kwarg `filename`
      - an additional edge: an empty hook list — logging only; `on_cache_skipped` is
        logged at WARNING level
- [x] **Debugging**: `.venv/bin/pytest tests/reporting/ -x`
- [x] **Contract re-verification**: 8 methods = 8 events one-to-one; INFO/WARNING
      levels; hooks receive the original kwargs; synchronous fan-out
- [x] **Lint**: `.venv/bin/ruff check prettyplay/reporting/ tests/reporting/`
- [x] The reporting cell is complete: `goga lint` — 0 errors; the facade import check

### Task 5: Failure taxonomy (prettyplay/failures/errors.py)

Context: four contract entities of cell `prettyplay/failures` in one `location: errors.py`
(grouped by location): the base `PrettyplayError(message)` and three `PrettyplayError::`
mutations — `ProductDefectError(step_text, message)`, `IncurableStepError(step_text, reason,
recommendation)`, `LlmUnavailableError(message)`. All are caught by the single
`except PrettyplayError`. Fields are stored as attributes (the properties from CODEMANIFEST).
`IncurableStepError.__str__` renders all three fields. Facade: `from prettyplay.failures
import PrettyplayError, ProductDefectError, IncurableStepError, LlmUnavailableError`.
The failures cell completes with this task.

**Usages relevant to this task:**
- `conventions`: docstrings, type hints.
- `taxonomy` (imported usage, consumer cells): the `recommendation` field is read by
  consumers as `info.value.recommendation` — the attribute is mandatory.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
1. PrettyplayError(Exception): __init__(message) → self.message = message
2. ProductDefectError(PrettyplayError): __init__(step_text, message) → both attributes;
   str = f"product defect on step {step_text!r}: {message}"
3. IncurableStepError(PrettyplayError): __init__(step_text, reason, recommendation) →
   three attributes; str includes all three fields
4. LlmUnavailableError(PrettyplayError): __init__(message) → the message attribute
```

- [x] **STEP 0 (Declaration)**: declare that Task 5 — the failure taxonomy — is being
      executed
- [x] **Contract tests** (`tests/failures/test_errors.py`): all four names import from
      `prettyplay.failures`; every mutation is a subclass of `PrettyplayError`;
      `ProductDefectError` has the properties `step_text`/`message`; `IncurableStepError` —
      `step_text`/`reason`/`recommendation`; `LlmUnavailableError` — `message`.
      Expected failure
- [x] **Code**: create `prettyplay/failures/errors.py` per the algorithm above
- [x] **Code**: create `prettyplay/failures/__init__.py` re-exporting all four names
      and `__all__`
- [x] **Interface verification**: `.venv/bin/pytest tests/failures/test_errors.py -v`; the
      facade:
      `.venv/bin/python -c "from prettyplay.failures import PrettyplayError, ProductDefectError, IncurableStepError, LlmUnavailableError"`
- [x] **Logic tests**:
      - `test_incurable_error_message_renders_all_fields` —
        Input: `str(IncurableStepError("шаг", "причина", "рекомендация"))`.
        Assertions (verbatim):
        ```
        "шаг" in s and "причина" in s and "рекомендация" in s
        the error is a PrettyplayError instance (a single except at the suite boundary)
        ```
      - an additional positive: `ProductDefectError("шаг", "ожидание не оправдалось")`
        — `str()` contains the step and the message; `LlmUnavailableError("llm
        unavailable: openai: ...")` — `message` is available; each is
        `issubclass(..., PrettyplayError)`
- [x] **Debugging**: `.venv/bin/pytest tests/failures/ -x`
- [x] **Contract re-verification**: three distinguishable kinds, one base except; the
      attribute fields match the contract's properties
- [x] **Lint**: `.venv/bin/ruff check prettyplay/failures/ tests/failures/`
- [x] The failures cell is complete: `goga lint` — 0 errors; the facade import check

### Task 6: `DriverSession` — browser lifecycle (prettyplay/driver/session.py)

Context: the entity of cell `prettyplay/driver`, `location: session.py`. The owner of the
Playwright sync driver and the browser for a run. Imports: `Config` from
`prettyplay/config` — the canonical facade relative import `from ..config import Config`.
The constructor starts nothing; `open_context()` lazily starts `sync_playwright().start()`
(the session lives for the whole run — an explicit start, not a with-block), launches the
browser through the engines dict `{chromium, firefox, webkit}` exactly once, then
`browser.new_context()` → `context.new_page()` → `PageFacade(page, context)`. `close()` —
`browser.close()` + `playwright.stop()` + nulling the fields; safe when never started
(no-op). Playwright errors propagate as is. Facade: DriverSession.

**Usages relevant to this task:**
- `playwright`: sync lifecycle — `sync_playwright().start()` for a long-lived session;
  the dict `{"chromium": p.chromium, "firefox": p.firefox, "webkit": p.webkit}` →
  `.launch()`; headless by default.
- `conventions`: mocks of external dependencies — `mock.patch` on
  `prettyplay.driver.session.sync_playwright`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
1. __init__(config): self._config, self._playwright=None, self._browser=None
2. open_context():
   IF self._browser is None:
     self._playwright = sync_playwright().start()
     engines = {"chromium": self._playwright.chromium, "firefox": self._playwright.firefox,
                "webkit": self._playwright.webkit}
     self._browser = engines[self._config.browser].launch()
   context = self._browser.new_context(); page = context.new_page()
   RETURN PageFacade(page, context)
3. close(): IF self._browser: self._browser.close(); self._playwright.stop();
   null both fields (idempotent, safe when never started)
```

Note: `PageFacade` is not implemented yet (Task 7). For task independence: in this task
`open_context` returns `PageFacade(...)` imported from `.page`; to keep the task
executable, create in `prettyplay/driver/page.py` a minimal `PageFacade.__init__(page,
context)` skeleton (no methods — the full implementation in Task 7), or implement Tasks 6
and 7 in one session, preserving the checkbox order. Task 6 contract tests mock
`sync_playwright`.

- [x] **STEP 0 (Declaration)**: declare that Task 6 — DriverSession — is being executed
- [x] **Contract tests** (`tests/driver/test_session.py`): `from prettyplay.driver import
      DriverSession`; `DriverSession(config)` constructs without starting anything;
      `open_context() -> PageFacade`; `close()` without a start does not fail. Expected
      failure
- [x] **Code**: create `prettyplay/driver/session.py` per the algorithm above (the
      `page.py` skeleton if needed — see the note)
- [x] **Code**: create/extend `prettyplay/driver/__init__.py` — re-export `DriverSession`
- [x] **Interface verification**: `.venv/bin/pytest tests/driver/test_session.py -v`
- [x] **Logic tests**:
      - `test_open_context_lazy_launch_single_browser` — Setup: `mock.patch(
        "prettyplay.driver.session.sync_playwright")` → fake pw: `pw().start()` returns
        an object with `chromium/firefox/webkit`, each `.launch()` appends to `launches`;
        `new_context()` → a context with `new_page()`.
        Input: `session = DriverSession(Config(browser="chromium"))`;
        `session.open_context()` ×2.
        Assertions (verbatim):
        ```
        after the constructor: pw.start was not called
        launches == 1
        the two results are distinct PageFacade; 2 contexts created
        ```
      - an additional edge: a repeated `close()` — no-op; `close()` before a start —
        no-op
- [x] **Debugging**: `.venv/bin/pytest tests/driver/test_session.py -x`
- [x] **Contract re-verification**: one browser per run; an isolated context per call;
      constructor laziness
- [x] **Lint**: `.venv/bin/ruff check prettyplay/driver/ tests/driver/`

### Task 7: `PageFacade` + `LocatorFacade` — the page facade (prettyplay/driver/page.py)

Context: two entities of one `location: page.py` of the driver cell. A narrow stable
facade — the only page API of generated code; a backward-compatibility contract (extend,
never rename/remove). No `time.sleep` whatsoever; waits — only through
`playwright.sync_api.expect`; no raw Playwright object is handed out (returns —
str / bytes / LocatorFacade). The driver cell completes with this task. This facade's
surface is the source of `PAGE_API_SURFACE` for Task 16 (the generator).

**Usages relevant to this task:**
- `playwright`: locators `get_by_role(role, name=name)` / `get_by_label` / `get_by_text`;
  `page.locator("body").aria_snapshot()`; `page.screenshot(full_page=True)`;
  `expect(locator).to_be_visible()/to_contain_text()/to_be_enabled()`; auto-wait.
- `facade` (imported usage): `.usages/facade.md` describes the surface for consumers —
  the implementation must match it.
- `conventions`: mock Playwright at the external boundary.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
PageFacade.__init__(page, context) — private fields
  open(url)            → self._page.goto(url)
  find_by_role(r, name)→ LocatorFacade(self._page.get_by_role(r, name=name))
  find_by_label(l)     → LocatorFacade(self._page.get_by_label(l))
  find_by_text(t)      → LocatorFacade(self._page.get_by_text(t))
  aria_snapshot()      → self._page.locator("body").aria_snapshot()
  screenshot()         → self._page.screenshot(full_page=True)  # bytes
  url (property)       → self._page.url
  close()              → self._context.close()

LocatorFacade.__init__(locator)
  click()              → self._locator.click()
  fill(value)          → self._locator.fill(value)
  select_option(value) → self._locator.select_option(value)
  expect_visible()     → expect(self._locator).to_be_visible()
  expect_text(text)    → expect(self._locator).to_contain_text(text)
  expect_enabled()     → expect(self._locator).to_be_enabled()
```

- [x] **STEP 0 (Declaration)**: declare that Task 7 — PageFacade + LocatorFacade — is
      being executed
- [x] **Contract tests** (`tests/driver/test_page.py`): `from prettyplay.driver import
      PageFacade, LocatorFacade`; the full set of methods/properties per the contract
      (7 methods + url on PageFacade; 6 methods on LocatorFacade); signatures
      (`find_by_role(role: str, name: str)`, `fill(value: str)` etc.). Expected failure
- [x] **Code**: complete `prettyplay/driver/page.py` with the full implementation of both
      facades
- [x] **Code**: `prettyplay/driver/__init__.py` — the full cell re-export:
      `DriverSession`, `PageFacade`, `LocatorFacade` + `__all__`
- [x] **Interface verification**: `.venv/bin/pytest tests/driver/ -v`
- [x] **Logic tests** (`tests/driver/test_page.py`, fake-playwright objects recording
      calls — mocks only at the boundary):
      - delegation of every PageFacade method (`open` → `page.goto(url)`; locators →
        the corresponding calls returning `LocatorFacade`; `aria_snapshot` →
        `page.locator("body").aria_snapshot()`; `screenshot` →
        `page.screenshot(full_page=True)` returns bytes; `url` → `page.url`; `close` →
        `context.close()`)
      - delegation of every LocatorFacade method (`click`, `fill`, `select_option`,
        `expect_visible`/`expect_text`/`expect_enabled` → `expect(locator).to_*` — mock
        `playwright.sync_api.expect` or inject it)
      - edge: a failed expectation raises AssertionError (it goes to classification);
        no method returns a raw Playwright object
- [x] **Debugging**: `.venv/bin/pytest tests/driver/ -x`
- [x] **Contract re-verification**: the surface equals the contract (extension without
      renaming); no fixed delays in the code
- [x] **Lint**: `.venv/bin/ruff check prettyplay/driver/ tests/driver/`
- [x] The driver cell is complete: `goga lint` — 0 errors; the facade check:
      `.venv/bin/python -c "from prettyplay.driver import DriverSession, PageFacade, LocatorFacade"`

### Task 8: `normalize_step_text` — sentence normalization (prettyplay/cache/text.py)

Context: the Routine of cell `prettyplay/cache`, `location: text.py`. A pure addressing
function: NFC → strip → collapse → casefold. No I/O, no locale. The first task of the
cache cell.

**Usages relevant to this task:**
- `conventions`: pure logic — tests without mocks; docstring.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
1. s = unicodedata.normalize("NFC", text)
2. s = s.strip()
3. s = re.sub(r"\s+", " ", s)
4. RETURN s.casefold()
```

- [x] **STEP 0 (Declaration)**: declare that Task 8 — normalize_step_text — is being
      executed
- [x] **Contract tests** (`tests/cache/test_text.py`): `from prettyplay.cache import
      normalize_step_text`; the signature `(text: str) -> str`. Expected failure
- [x] **Code**: create `prettyplay/cache/text.py`; create `prettyplay/cache/__init__.py`
      re-exporting `normalize_step_text`
- [x] **Interface verification**: `.venv/bin/pytest tests/cache/test_text.py -v`; the
      facade: `.venv/bin/python -c "from prettyplay.cache import normalize_step_text"`
- [x] **Logic tests**:
      - `test_normalize_step_text_equivalence` — Input:
        `normalize_step_text("  Нажать   Войти ")`, `normalize_step_text("нажать войти")`.
        Assertions (verbatim):
        ```
        normalize_step_text("  Нажать   Войти ") == normalize_step_text("нажать войти") == "нажать войти"
        normalize_step_text("Нажать Войти") != normalize_step_text("Click Login")
        ```
      - `test_normalize_empty_and_whitespace_only` — Input: `normalize_step_text("")`,
        `normalize_step_text("   ")`, `normalize_step_text("\n\t")`.
        Assertions: all three → `""`
- [x] **Debugging**: `.venv/bin/pytest tests/cache/test_text.py -x`
- [x] **Contract re-verification**: a pure function; the NFC→strip→collapse→casefold
      pipeline
- [x] **Lint**: `.venv/bin/ruff check prettyplay/cache/ tests/cache/`

### Task 9: `StepIdentity` + `CachedStep` — cache models (prettyplay/cache/models.py)

Context: two entities of one `location: models.py` of the cache cell. `StepIdentity` —
the step address: the triple (cache_key, step_type, normalized_text) + the computed
`filename`. `CachedStep` — the in-memory cache unit. Both models — pydantic v2 kw_only;
the triple/cache fields are semantically mandatory, without defaults (kw_only
construction is mandatory); `filename` — a `cached_property` (or a plain property) over
the triple. The `\x1f` (Unit Separator) delimiter makes the concatenation unambiguous.

**Usages relevant to this task:**
- `pydantic`: kw_only models.
- `conventions`: pydantic models; `None` only for explicit absence.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
StepIdentity (BaseModel, kw_only): cache_key: str, step_type: str, normalized_text: str
  filename (cached_property):
    identity_string = "\x1f".join((cache_key, step_type, normalized_text))
    RETURN hashlib.sha256(identity_string.encode("utf-8")).hexdigest() + ".py"

CachedStep (BaseModel, kw_only): identity: StepIdentity, code: str, created_at: str
```

Trace checkpoint: the file name need not be a Python identifier (a hex digest may start
with a digit) — load parses the file text, no import by name happens; determinism and
distinctness of triples (sha256).

- [x] **STEP 0 (Declaration)**: declare that Task 9 — StepIdentity + CachedStep — is
      being executed
- [x] **Contract tests** (`tests/cache/test_models.py`): both names from
      `prettyplay.cache`; kw_only construction (positional → TypeError); the properties
      `cache_key`/`step_type`/`normalized_text`/`filename` on StepIdentity;
      `identity`/`code`/`created_at` on CachedStep. Expected failure
- [x] **Code**: create `prettyplay/cache/models.py` per the algorithm above
- [x] **Code**: `prettyplay/cache/__init__.py` — add `StepIdentity`, `CachedStep`
- [x] **Interface verification**: `.venv/bin/pytest tests/cache/test_models.py -v`
- [x] **Logic tests**:
      - `test_identity_filename_deterministic_and_discriminating` — Input: two
        identical and two differing triples.
        Trace (verbatim):
        ```
        StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти").filename
        StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти").filename   # same digest
        StepIdentity(cache_key="k", step_type="assertion", normalized_text="нажать войти").filename # different digest
        StepIdentity(cache_key="k2", step_type="action", normalized_text="нажать войти").filename   # different digest
        ```
        Assertions (verbatim):
        ```
        f1 == f2; f1 != f3; f1 != f4
        f1.endswith(".py") and len(digest part) == 64
        ```
- [x] **Debugging**: `.venv/bin/pytest tests/cache/ -x`
- [x] **Contract re-verification**: filename — a deterministic function of the triple
- [x] **Lint**: `.venv/bin/ruff check prettyplay/cache/ tests/cache/`

### Task 10: `StepCache` — the step repository (prettyplay/cache/store.py)

Context: the entity of the cache cell, `location: store.py`. Imports: `Config` from
`prettyplay/config`; `StepReporter` + usages `hooks` from `prettyplay/reporting`
(cache-write events). The properties `root` (str) and `writable` (a lazy check). `load` —
always reads; any structural error = a protective miss None. `save` — an atomic
best-effort write (tmp + os.replace), read-only → a silent-but-loud skip with a WARNING
event. Uses `StepIdentity`/`CachedStep` from `.models`, `StepReporter` for emit.

**Usages relevant to this task:**
- `hooks` (from `prettyplay/reporting`): the `on_cache_saved(step_text, filename)` /
  `on_cache_skipped(step_text, reason)` event payloads — strings.
- `conventions`: file-based tests — `tmp_path` only; caplog to check the logger.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
1. __init__(config, path, reporter):
   self._root = Path(config.cache_root)  # already absolute after load_config
   self._subdir = Path(path) if path else None   # part of the address
   self._reporter = reporter; self._writable = None (lazily)
2. root (property) → str(self._root)
3. writable (property):
   IF self._writable is None:
     try: self._target_dir().mkdir(parents=True, exist_ok=True)
          self._writable = os.access(self._target_dir(), os.W_OK)
     except OSError: self._writable = False
   RETURN self._writable
4. load(identity):
   target = self._target_dir() / identity.filename
   IF not target.exists(): RETURN None
   TRY (protective parse block — any structural error = a miss, not a run failure):
     text = target.read_text(encoding="utf-8")
     parse header: STEP_TEXT / CACHE_KEY / STEP_TYPE / CREATED_AT = <literal> (ast.literal_eval)
     code = text from the first occurrence of "def step(" (search by "\ndef step(", but the
     leading newline is NOT part of the code — loaded.code.startswith("def step(") holds
     deterministically; a missing "def step(" — a structural error → a protective miss)
     IF (CACHE_KEY, STEP_TYPE) != (identity.cache_key, identity.step_type)
        or STEP_TEXT != identity.normalized_text: RETURN None   # protective miss
     RETURN CachedStep(identity=identity, code=code, created_at=CREATED_AT)
   EXCEPT (ValueError, SyntaxError, KeyError, IndexError, OSError): RETURN None
   # an invalid header/literal, a missing metadata field or def step( tail,
   # an unreadable file — cache corruption never cripples a run
   # (contract: "The cache is always read")
5. save(step):
   IF not self.writable:
     emit on_cache_skipped(step_text=normalized, reason="read-only cache"); RETURN
   body = header constants (repr values) + "\n\n" + step.code + "\n"
   tmp = tempfile.mkstemp(dir=self._target_dir(), prefix=".tmp-", suffix=".py")
   write body; fsync; close
   FOR attempt in 1..3: try os.replace(tmp, target); BREAK
     except PermissionError: time.sleep(0.1)   # Windows: target busy
   ELSE: delete tmp; emit on_cache_skipped(reason="cache target busy"); RETURN
   emit on_cache_saved(step_text=normalized, filename=identity.filename)
```

Note: `time.sleep(0.1)` in the replace loop is the only library-permitted backoff
(Windows), not a page wait.

- [x] **STEP 0 (Declaration)**: declare that Task 10 — StepCache — is being executed
- [x] **Contract tests** (`tests/cache/test_store.py`): `from prettyplay.cache import
      StepCache`; the signature `StepCache(config, path, reporter)` (path optional); the
      properties `root -> str`, `writable -> bool`; the methods `load(identity)` /
      `save(step)`. Expected failure
- [x] **Code**: create `prettyplay/cache/store.py` per the algorithm above
- [x] **Code**: `prettyplay/cache/__init__.py` — add `StepCache`
- [x] **Interface verification**: `.venv/bin/pytest tests/cache/test_store.py -v`
- [x] **Logic tests**:
      - `test_save_load_roundtrip_via_file` — Setup: `tmp_path`;
        `Config(cache_root=str(tmp_path))`; a reporter with a recorder;
        `cache = StepCache(config, "checkout", reporter)`;
        `identity = StepIdentity(cache_key="login-flow", step_type="action",
        normalized_text="открыть страницу логина")`.
        Input: `cache.save(CachedStep(identity=identity, code="def step(page) -> None:\n    page.open('https://x')\n", created_at="2026-09-07"))`;
        then `cache.load(identity)`.
        Assertions (verbatim):
        ```
        loaded is not None
        loaded.identity == identity
        loaded.code.startswith("def step(")
        loaded.created_at == "2026-09-07"
        file: text.startswith("STEP_TEXT =") and "def step(" in text
        recorded: ("on_cache_saved", {"filename": identity.filename})
        caplog: an INFO record "on_cache_saved" from the "prettyplay" logger; record.ctx_filename == identity.filename
        importing the file via importlib.util.spec_from_file_location("cached_step", path)
          + module_from_spec + exec_module succeeds (a valid module; the digest file
          name need not be an identifier — load goes by text, not by module name)
        ```
      - `test_save_readonly_cache_skips_loudly` — Setup: a `tmp_path` directory,
        `chmod 0o500` (skipif when run as root — root ignores modes); an event recorder.
        Assertions (verbatim):
        ```
        no exceptions; no file created
        recorded: ("on_cache_skipped", reason="read-only cache")
        ```
      - `test_load_missing_file_returns_none` — Input:
        `cache.load(StepIdentity(cache_key="k", step_type="action",
        normalized_text="нет такого шага"))`. Assertions: `result is None`
      - `test_load_metadata_mismatch_treated_as_miss` — Setup: in the `tmp_path` cache,
        a file with the identity's digest but a manually altered `STEP_TEXT`.
        Assertions: `result is None` (the step will be regenerated, the run does not
        fail)
      - `test_load_corrupt_file_treated_as_miss` — Setup: in the `tmp_path` cache, a
        file named `identity.filename` whose content is a fragment without a header and
        without `def step(`: `"garbage not a module"`. Assertions: `result is None`
        (no exceptions)
- [x] **Debugging**: `.venv/bin/pytest tests/cache/ -x`
- [x] **Contract re-verification**: reading always works; no write error fails a run;
      concurrent writers — the last one wins (atomic replace)
- [x] **Lint**: `.venv/bin/ruff check prettyplay/cache/ tests/cache/`

### Task 11: `RunBudgets` — the attempt registry (prettyplay/cache/budgets.py)

Context: the entity of the cache cell, `location: budgets.py`. A per-run registry: how
many generation/healing attempts a step has left within the run. The key —
`identity.filename: str` (deterministic, collision-free; pydantic models are unhashable
by default — a string key is simpler and more robust). Separate gen/heal dicts. Nothing
persists; budgets are not reset between tests. The cache cell completes with this task.

**Usages relevant to this task:**
- `conventions`: pure logic — no mocks.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
1. __init__(generation_limit, healing_limit): two dict[str, int] (key = identity.filename)
2. try_generation(identity):
   used = self._gen.get(key, 0)
   IF used >= self._generation_limit: RETURN False
   self._gen[key] = used + 1; RETURN True
3. try_healing — symmetric with self._heal / self._healing_limit
```

- [x] **STEP 0 (Declaration)**: declare that Task 11 — RunBudgets — is being executed
- [x] **Contract tests** (`tests/cache/test_budgets.py`): `from prettyplay.cache import
      RunBudgets`; the signature `RunBudgets(generation_limit, healing_limit)`; the
      methods `try_generation(identity) -> bool`, `try_healing(identity) -> bool`.
      Expected failure
- [x] **Code**: create `prettyplay/cache/budgets.py` per the algorithm above
- [x] **Code**: `prettyplay/cache/__init__.py` — the full cell facade:
      `normalize_step_text`, `StepIdentity`, `CachedStep`, `StepCache`, `RunBudgets` +
      `__all__`
- [x] **Interface verification**: `.venv/bin/pytest tests/cache/ -v`
- [x] **Logic tests**:
      - `test_budgets_separate_pools_shared_per_identity` — Setup:
        `budgets = RunBudgets(generation_limit=1, healing_limit=1)`; `identity` and
        `identity2`.
        Input: `try_generation(identity)` ×2; `try_healing(identity)`;
        `try_generation(identity2)`.
        Assertions (verbatim): `results: [True, False, True, True]`
      - `test_budgets_default_limits_from_config` — Input:
        `RunBudgets(config.generation_attempts, config.healing_attempts)` with
        `Config()`.
        Assertions (verbatim):
        ```
        [try_generation(id) for _ in range(4)] == [True, True, True, False]
        [try_healing(id) for _ in range(3)] == [True, True, False]
        ```
- [x] **Debugging**: `.venv/bin/pytest tests/cache/ -x`
- [x] **Contract re-verification**: one registry per process; separate limits; False on
      exhaustion
- [x] **Lint**: `.venv/bin/ruff check prettyplay/cache/ tests/cache/`
- [x] The cache cell is complete: `goga lint` — 0 errors; the facade check:
      `.venv/bin/python -c "from prettyplay.cache import StepCache"`

### Task 12: `FailureClassification` — the classification verdict (prettyplay/llm/models.py)

Context: the entity of cell `prettyplay/llm`, `location: models.py`. The verdict model:
category (one of rot / product_defect / incurable), explanation, recommendation. pydantic
v2 kw_only. The first task of the llm cell.

**Usages relevant to this task:**
- `pydantic`: kw_only models.
- `classification` (imported usage, for the consumer — the healer): the healing-decision
  categories.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **STEP 0 (Declaration)**: declare that Task 12 — FailureClassification — is being
      executed
- [x] **Contract tests** (`tests/llm/test_models.py`): `from prettyplay.llm import
      FailureClassification`; kw_only; the properties
      `category`/`explanation`/`recommendation` (str). Expected failure
- [x] **Code**: create `prettyplay/llm/models.py` (the model) and
      `prettyplay/llm/__init__.py` re-exporting `FailureClassification`
- [x] **Interface verification**: `.venv/bin/pytest tests/llm/test_models.py -v`
- [x] **Logic tests**: positive — `FailureClassification(category="rot",
      explanation="e", recommendation="r")` stores all three; edge — categories of all
      three allowed values construct
- [x] **Debugging**: `.venv/bin/pytest tests/llm/test_models.py -x`
- [x] **Contract re-verification**: the three properties; the category — a label string
- [x] **Lint**: `.venv/bin/ruff check prettyplay/llm/ tests/llm/`

### Task 13: `LlmProvider` (port) + `create_provider` (prettyplay/llm/provider.py)

Context: two entities of one `location: provider.py` of the llm cell. `LlmProvider` —
the single LLM port: the methods `generate_step_code(prompt, step_text, previous_steps,
snapshot, screenshot, page_api, existing_code, error) -> str` and
`classify_failure(prompt, step_text, code, error, snapshot, screenshot) ->
FailureClassification`. The implementations — mutations in separate files (Tasks 14–15);
the port itself — a base class with these signatures (bodies — raising
NotImplementedError; the port is never instantiated at runtime). `create_provider(config)`
— a factory by `config.provider`. Imports: `Config` from `prettyplay/config`,
`LlmUnavailableError` from `prettyplay/failures`, `FailureClassification` from `.models`.

**Usages relevant to this task:**
- `conventions`: type hints mandatory; docstrings.
- `taxonomy`: `LlmUnavailableError` — the provider's only failure kind.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm `create_provider` (verbatim from the design):
```
IF config.provider == "openai":    RETURN OpenAiProvider(config)
ELIF config.provider == "anthropic": RETURN AnthropicProvider(config)
ELSE: raise ValueError("unsupported provider {config.provider!r}: expected one of openai, anthropic")
```

- [x] **STEP 0 (Declaration)**: declare that Task 13 — LlmProvider + create_provider —
      is being executed
- [x] **Contract tests** (`tests/llm/test_provider.py`): `from prettyplay.llm import
      LlmProvider, create_provider`; the port has the methods `generate_step_code` and
      `classify_failure` with exact signatures (inspect); `create_provider` — callable
      with Config. Expected failure
- [x] **Code**: create `prettyplay/llm/provider.py`: the class `LlmProvider` (the port)
      and the function `create_provider` with both branches ("openai" → OpenAiProvider,
      "anthropic" → AnthropicProvider, anything else — ValueError per the algorithm).
      To keep the task executable in one session (the Task 6 pattern): create minimal
      skeletons of `OpenAiProvider(LlmProvider)` and `AnthropicProvider(LlmProvider)` in
      `prettyplay/llm/openai_provider.py` and `prettyplay/llm/anthropic_provider.py`
      (skeleton: the constructor `__init__(config)` stores config in a private field;
      the port methods are inherited from `LlmProvider`; the full implementation —
      Tasks 14–15), so that `create_provider` returns real instances and all Task 13
      tests pass
- [x] **Code**: `prettyplay/llm/__init__.py` — add `LlmProvider`, `create_provider`
- [x] **Interface verification**: `.venv/bin/pytest tests/llm/test_provider.py -v`
- [x] **Logic tests**:
      - `test_create_provider_selects_by_config` — Setup: `Config(provider="anthropic",
        model="claude-sonnet-4-5")` (no env keys — not needed).
        Input: `create_provider(config)`.
        Assertions (verbatim):
        ```
        isinstance(provider, AnthropicProvider)
        isinstance(provider, LlmProvider)   # the port contract
        ```
        (plus the symmetric case `provider="openai"` → OpenAiProvider)
      - `test_create_provider_unknown_fails_loudly` — Input:
        ```python
        config = Config.model_construct(provider="groq")  # validation bypassed intentionally:
                                                          # Literal would otherwise reject the value
        create_provider(config)
        ```
        Assertions (verbatim): `pytest.raises(ValueError)`; `"openai"` and `"anthropic"`
        in the text
- [x] **Debugging**: `.venv/bin/pytest tests/llm/ -x`
- [x] **Contract re-verification**: double protection (the Literal in Config +
      ValueError in the factory); one request per attempt — the port has no retries of
      its own
- [x] **Lint**: `.venv/bin/ruff check prettyplay/llm/ tests/llm/`

### Task 14: `OpenAiProvider` (prettyplay/llm/openai_provider.py)

Context: the mutation `LlmProvider::OpenAiProvider(config)`, `location:
openai_provider.py`. A lazy client: the constructor does NOT read env (starts without
credentials); on the first request `os.environ.get("OPENAI_API_KEY")` — missing/empty →
`LlmUnavailableError` naming the provider and the variable; a non-empty `config.base_url`
→ passed to the client constructor. `generate_step_code`:
`client.chat.completions.create(model=config.effective_generation_model,
messages=[{"role":"system","content":prompt}, {"role":"user","content":user_content}])`;
user_content — a text block with the fields STEP / PREVIOUS STEPS / PAGE SNAPSHOT / PAGE
API / CODE / ERROR (the last two — regeneration requests only); when
`screenshot is not None` — a list of blocks `[{"type":"text","text":...},
{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}]`.
`classify_failure`: one request (the model `effective_classification_model`), the answer —
a single line `category | explanation | recommendation`; parsing: strip → the first
non-empty line → split `"|"` into 3 parts → strip each; category ∈ {rot,
product_defect, incurable}; an unparsable/unknown verdict → the protective mapping to
incurable. SDK errors (`openai.OpenAIError`) → `LlmUnavailableError("llm unavailable:
openai request failed") from error`. The prompt is passed verbatim.

**Usages relevant to this task:**
- `openai`: `OpenAI(api_key=os.environ["OPENAI_API_KEY"])`;
  `chat.completions.create`; `response.choices[0].message.content`; `OpenAIError` —
  the SDK error base.
- `conventions`: mock the SDK at the external boundary (`mock.patch` of the client).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Skeleton (shared by both providers, verbatim from the design):
```
1. __init__(config): self._config; self._client = None
2. _get_client() (lazily):
   key = os.environ.get("OPENAI_API_KEY")
   IF not key: raise LlmUnavailableError("llm unavailable: openai: OPENAI_API_KEY is not set")
   construct SDK client (api_key=key; base_url=config.base_url or None)
3. generate_step_code(...):
   model = config.effective_generation_model
   messages: system=prompt (verbatim), user=build_user_content(...)
   send ONE request; extract text; RETURN code
4. classify_failure(...):
   model = config.effective_classification_model
   send ONE request; parse "category | explanation | recommendation"
   IF parsing failed or the category is unknown:
     RETURN FailureClassification("incurable", "classification verdict unparsable",
                                  "re-run the step or check the provider answer")
   RETURN FailureClassification(category, explanation, recommendation)
5. Request wrapper: except openai.OpenAIError as e:
   raise LlmUnavailableError("llm unavailable: openai request failed") from e
```

`build_user_content` — a field format unified across both providers; the multimodal
difference is only in each SDK's content-block wrapper. It is reasonable to factor the
shared field-building helper into an internal cell module (e.g. `_request.py`) — an
admissible internal decomposition.

- [x] **STEP 0 (Declaration)**: declare that Task 14 — OpenAiProvider — is being
      executed
- [x] **Contract tests** (`tests/llm/test_openai_provider.py`):
      `from prettyplay.llm import OpenAiProvider`;
      `isinstance(OpenAiProvider(Config()), LlmProvider)`; both port methods overridden
      with the same signatures; the constructor does not read env. Expected failure
- [x] **Code**: complete the `prettyplay/llm/openai_provider.py` skeleton from Task 13
      with the full implementation per the skeleton above (+ the shared field helper
      under the chosen decomposition); the `"openai"` branch in `create_provider` is
      already wired by the Task 13 skeletons
- [x] **Code**: `prettyplay/llm/__init__.py` — add `OpenAiProvider`
- [x] **Interface verification**: `.venv/bin/pytest tests/llm/test_openai_provider.py -v`
- [x] **Logic tests**:
      - `test_openai_provider_error_maps_to_llm_unavailable` — Setup: `mock.patch` the
        SDK client: `chat.completions.create` raises `OpenAIError("timeout")`; env
        `OPENAI_API_KEY=test`.
        Input: `OpenAiProvider(Config(model="gpt-5")).generate_step_code(prompt="p",
        step_text="s", previous_steps=[], snapshot="- snap", screenshot=None,
        page_api="page.open(...)", existing_code=None, error=None)`.
        Assertions (verbatim):
        ```
        pytest.raises(LlmUnavailableError); "openai" in str(excinfo.value)
        isinstance(excinfo.value, PrettyplayError)
        ```
      - `test_missing_api_key_surfaces_on_first_request` — Setup:
        `monkeypatch.delenv("OPENAI_API_KEY", raising=False)`.
        Input: `provider = OpenAiProvider(Config())` (does not fail); then call
        `classify_failure(...)`.
        Assertions (verbatim):
        ```
        construction succeeds (no exception)
        pytest.raises(LlmUnavailableError) on the first request; "OPENAI_API_KEY" in str(...)
        ```
      - `test_classification_unparsable_defaults_to_incurable` — Setup: a provider stub
        of the SDK response returns garbage ("sorry cannot answer" without `|`).
        Assertions (verbatim): `classification.category == "incurable"`
      - an additional positive: `generate_step_code` with a mocked SDK returns str;
        the system message == the prompt verbatim; the model ==
        effective_generation_model; an existing base_url passed to the client
        constructor
- [x] **Debugging**: `.venv/bin/pytest tests/llm/ -x`
- [x] **Contract re-verification**: one request per attempt; operation parity; keys
      only from env; no secrets in logs
- [x] **Lint**: `.venv/bin/ruff check prettyplay/llm/ tests/llm/`

### Task 15: `AnthropicProvider` — full parity (prettyplay/llm/anthropic_provider.py)

Context: the mutation `LlmProvider::AnthropicProvider(config)`, `location:
anthropic_provider.py`. Absolute parity with OpenAiProvider (the same operations, the
same inputs, the same outputs, the same failure taxonomy): a lazy client
(`ANTHROPIC_API_KEY`); `client.messages.create(model=..., system=prompt,
max_tokens=1024, messages=[{"role":"user","content":...}])`; the screenshot — the block
`{"type":"image","source":{"type":"base64","media_type":"image/png","data":...}}`;
extraction of `message.content[0].text`; `anthropic.AnthropicError` →
`LlmUnavailableError("llm unavailable: anthropic request failed") from e`. The llm cell
completes with this task.

**Usages relevant to this task:**
- `anthropic`: `anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])`;
  `messages.create(system=..., max_tokens=1024)`; `message.content[0].text`;
  `AnthropicError` — the SDK error base.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **STEP 0 (Declaration)**: declare that Task 15 — AnthropicProvider — is being
      executed
- [x] **Contract tests** (`tests/llm/test_anthropic_provider.py`):
      `from prettyplay.llm import AnthropicProvider`; inherits `LlmProvider`; the
      operation signatures are identical to OpenAiProvider; the constructor does not
      read env. Expected failure
- [x] **Code**: complete the `prettyplay/llm/anthropic_provider.py` skeleton from Task
      13 with the full implementation (reuse the Task 14 shared field helper); the
      `"anthropic"` branch in `create_provider` is already wired by the Task 13
      skeletons
- [x] **Code**: `prettyplay/llm/__init__.py` — the full cell facade: `LlmProvider`,
      `create_provider`, `OpenAiProvider`, `AnthropicProvider`,
      `FailureClassification` + `__all__`
- [x] **Interface verification**: `.venv/bin/pytest tests/llm/ -v`
- [x] **Logic tests** (mirror the key openai scenarios — parity):
      - `test_anthropic_provider_error_maps_to_llm_unavailable` — `mock.patch` the
        client: `messages.create` raises `AnthropicError("timeout")`; env
        `ANTHROPIC_API_KEY=test`;
        Assertions: `pytest.raises(LlmUnavailableError)`; `"anthropic" in str(...)`;
        `isinstance(..., PrettyplayError)`
      - `test_anthropic_missing_api_key_surfaces_on_first_request` —
        `monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)`; construction
        succeeds; the first request → `LlmUnavailableError` with `"ANTHROPIC_API_KEY"`
        in the message
      - edge: an unparsable classification verdict → `category == "incurable"`;
        positive: generate with a mocked SDK: system=prompt verbatim, max_tokens=1024,
        extraction of `content[0].text`
- [x] **Debugging**: `.venv/bin/pytest tests/llm/ -x`
- [x] **Contract re-verification**: parity is absolute — identical
      inputs/outputs/errors; provider choice — configuration only
- [x] **Lint**: `.venv/bin/ruff check prettyplay/llm/ tests/llm/`
- [x] The llm cell is complete: `goga lint` — 0 errors; the facade check:
      `.venv/bin/python -c "from prettyplay.llm import create_provider, FailureClassification"`

### Task 16: `run_step_code` + prompts — fixed-form execution (prettyplay/engine/execution.py)

Context: the Routine of cell `prettyplay/engine`, `location: execution.py`. Execution of
step code against the page facade: compile → an isolated namespace → `namespace["step"]`
→ `fn(page)`. Exceptions propagate as is; the module is not registered in `sys.modules`;
there are no networks beyond the page itself. The first task of the engine cell. The
prompts (the engine cell's inline Usages) and `PAGE_API_SURFACE` are implemented as
constants in `generator.py` — by Task 17; the verbatim prompt texts are given in Task
17's Code step (their only place of use).

**Usages relevant to this task:**
- `conventions`: docstrings, pure mechanics.
- `facade` (from `prettyplay/driver`): the source of the PAGE API surface (for the
  constant in Task 17).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
1. namespace: dict[str, object] = {}
2. exec(compile(code, "<prettyplay-step>", "exec"), namespace)
3. fn = namespace["step"]        # the fixed name from generation_prompt
4. fn(page)                      # exceptions — out, as is
```

- [x] **STEP 0 (Declaration)**: declare that Task 16 — run_step_code — is being executed
- [x] **Contract tests** (`tests/engine/test_execution.py`):
      `from prettyplay.engine import run_step_code`; the signature
      `(code: str, page: PageFacade)`. Expected failure
- [x] **Code**: create `prettyplay/engine/execution.py` per the algorithm above; create
      `prettyplay/engine/__init__.py` re-exporting `run_step_code`
- [x] **Interface verification**: `.venv/bin/pytest tests/engine/test_execution.py -v`
- [x] **Logic tests**:
      - `test_run_step_code_executes_fixed_form` — Setup: a fake page recording calls.
        Input:
        `run_step_code("def step(page) -> None:\n    page.open('https://example.com')\n", page)`.
        Assertions (verbatim): `page.calls == [("open", "https://example.com")]`
      - an additional negative: step code raising AssertionError (`def step(page):
        raise AssertionError("x")`) — the exception propagates as is (no swallow);
        edge: code without `def step(` → a KeyError/exception out (a gross form
        violation — not a normal situation, no protection required)
- [x] **Debugging**: `.venv/bin/pytest tests/engine/ -x`
- [x] **Contract re-verification**: an isolated namespace; no sys.modules; no
      LLM/network
- [x] **Lint**: `.venv/bin/ruff check prettyplay/engine/ tests/engine/`

### Task 17: `StepGenerator` — generation with in-loop execution (prettyplay/engine/generator.py)

Context: the entity of the engine cell, `location: generator.py`. Generation of working
step code with in-loop execution of candidates on the live page. Constructor:
`StepGenerator(config, provider, cache, budgets, reporter)` — config (the screenshot
flag), provider (the LLM port), cache (persisting success), budgets (the attempt
registry), reporter (visibility). The methods `generate(identity, step_text,
previous_steps, page)` and `regenerate(identity, step_text, previous_steps, page,
existing_code, error)`. The file defines the constants `GENERATION_PROMPT`,
`CLASSIFICATION_PROMPT` (texts — in Task 16, verbatim) and `PAGE_API_SURFACE` — a frozen
string constant listing the PageFacade and LocatorFacade calls verbatim from the facade
surface (the driver — a backward-compatibility contract; surface changes = a deliberate
extension with constant synchronization).

**Usages relevant to this task:**
- `generation_prompt`: the system message of every generation request (verbatim).
- `facade` (from `prettyplay/driver`): the single source of the PAGE API surface for
  requests.
- `generation` (imported usage, cell .usages): the loop, budgets, the fixed form.
- `conventions`: stub objects instead of the SDK; tmp_path for the cache.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
PAGE_API_SURFACE — a frozen string constant: a listing of the PageFacade and LocatorFacade
calls verbatim from the facade surface (the driver — a backward-compatibility contract,
the constant is stable; surface changes = a deliberate extension with constant
synchronization).

generate(identity, step_text, previous_steps, page):
  attempt = 0; existing_code = None; last_error = None
  LOOP:
    IF not budgets.try_generation(identity):
      raise IncurableStepError(step_text, "generation attempt budget exhausted",
                               "reword the step or raise generation_attempts")
    attempt += 1
    reporter.emit("on_generation_started", {"step_text": step_text, "attempt": attempt})
    snapshot = page.aria_snapshot()
    screenshot = page.screenshot() if config.send_screenshots else None
    code = provider.generate_step_code(prompt=GENERATION_PROMPT, step_text=step_text,
             previous_steps=previous_steps, snapshot=snapshot, screenshot=screenshot,
             page_api=PAGE_API_SURFACE, existing_code=existing_code, error=last_error)
    try: run_step_code(code, page); BREAK
    except Exception as e: existing_code = code; last_error = short(e)
  step = CachedStep(identity=identity, code=code, created_at=date.today().isoformat())
  cache.save(step); RETURN step

regenerate(identity, step_text, previous_steps, page, existing_code, error):
  the same loop; differences: budgets.try_healing; the starting existing_code/error
  from the arguments
```

Trace checkpoints: the retry interpretation is agreed with the provider contract
("non-empty only on regeneration requests") — a retry with the failed candidate is
exactly a regeneration request; `LlmUnavailableError` from the provider → immediate
propagation, no retry (outside the candidate try-loop); exhaustion = IncurableStepError,
not an infinite loop; at most `generation_attempts` (regeneration — `healing_attempts`)
requests per step per run.

- [x] **STEP 0 (Declaration)**: declare that Task 17 — StepGenerator — is being executed
- [x] **Contract tests** (`tests/engine/test_generator.py`):
      `from prettyplay.engine import StepGenerator`; the constructor signature (config,
      provider, cache, budgets, reporter); the methods `generate`/`regenerate` with
      exact signatures. Expected failure
- [x] **Code**: create `prettyplay/engine/generator.py`: the constants
      `GENERATION_PROMPT`, `CLASSIFICATION_PROMPT` (texts below, verbatim),
      `PAGE_API_SURFACE` (the PageFacade surface:
      open/find_by_role/find_by_label/find_by_text/aria_snapshot/screenshot/url;
      LocatorFacade: click/fill/select_option/expect_visible/expect_text/expect_enabled —
      13 calls verbatim per the Surface table in
      `prettyplay/driver/.usages/facade.md`, the single source of the surface under the
      engine contract; the facade's `close()` is not in the listing — it stays a runtime
      method for PrettyTest.close, not for generated code),
      the class `StepGenerator` per the algorithm above (the classification prompt is
      used by StepHealer — Task 18 imports it from generator or symmetrically defines
      the reference; canonically: both constants in generator.py, the healer imports
      CLASSIFICATION_PROMPT)

Prompt texts (verbatim from the engine cell's CODEMANIFEST; copied into the constants):

```python
GENERATION_PROMPT = """You generate executable Python code for one step of a web UI test.

Input you receive:
- STEP: the step sentence in a natural language
- PREVIOUS STEPS: the sentences of the previous steps of the test, in order
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- SCREENSHOT: an image of the page, when attached
- PAGE API: the exact surface listing of the page facade — call nothing outside it
- CODE: the existing step code that failed (regeneration requests only)
- ERROR: the failure description of the existing code (regeneration requests only)

Output exactly one Python code block with one function of the fixed form:

def step(page) -> None:
    ...

Rules:
- The function receives exactly one argument: the page facade. Never import anything, never use other libraries
- Work only through the page API: the request carries the exact surface listing of the page facade — call nothing outside it
- For an assertion sentence end with an expectation call; for an action sentence perform the actions
- Locating by role and accessible name is preferred; by visible text next; by label for form fields
- No fixed delays, no sleeps, no explicit waits — the facade waits itself
- The step must complete exactly what STEP says — nothing more, nothing less
- Output only the code block, no explanations"""

CLASSIFICATION_PROMPT = """You classify a failure of a cached web UI test step.

Input you receive:
- STEP: the step sentence
- CODE: the step code that failed
- ERROR: the failure description
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- SCREENSHOT: an image of the page, when attached

Answer with exactly one line of the form:
category | explanation | recommendation

where category is one of:
- rot — the UI changed (selectors, texts, structure) and the step can be regenerated for the same intent
- product_defect — the step works as written but the expected behavior of the application is genuinely broken
- incurable — the step sentence no longer matches reality, the intent is ambiguous, or regeneration cannot help

explanation: one short sentence why. recommendation: one short sentence what the engineer should do.
Output only that single line — no code, no extra text."""
```
- [x] **Code**: `prettyplay/engine/__init__.py` — add `StepGenerator`
- [x] **Interface verification**: `.venv/bin/pytest tests/engine/test_generator.py -v`
- [x] **Logic tests** (a stub provider with the LlmProvider signatures; a fake page with
      the facade methods; the cache on tmp_path; an event recorder):
      - `test_generate_success_stores_and_reports_attempt` — Setup: a stub provider:
        `generate_step_code` returns working code for the fake page;
        `budgets = RunBudgets(3, 2)`.
        Input: `generator.generate(identity, "открыть страницу", [], page)`.
        Assertions (verbatim):
        ```
        step.code == the stub's code; step.identity == identity
        provider.calls == 1; the first attempt without existing_code/error
        recorded on_generation_started: attempt == 1 (int)
        recorded on_cache_saved with filename == identity.filename
        ```
      - `test_generate_retries_with_existing_code_then_succeeds` — Setup: a stub
        provider: the first answer — code that fails on the fake page
        (`page.find_by_role(...)` raises AssertionError), the second — working; a
        recorder.
        Input: `generator.generate(identity, "нажать Войти", [], page)`.
        Assertions (verbatim):
        ```
        provider.calls == 2
        the second call: existing_code == A and error contains the failure text
        recorded on_generation_started ×2 (attempt 1, attempt 2)
        ```
      - `test_generate_budget_exhaustion_raises_incurable` — Setup: the provider
        always returns code failing on the fake page; `RunBudgets(3, 2)`; a tmp cache.
        Input: `generator.generate(identity, "невозможный шаг", [], page)`.
        Assertions (verbatim):
        ```
        pytest.raises(IncurableStepError)
        excinfo.value.reason mentions the budget; excinfo.value.recommendation is non-empty
        provider.calls == 3
        cache.save not called (failures are not cached)
        ```
      - `test_generate_provider_unavailable_propagates_immediately` — Setup: a stub
        provider raising `LlmUnavailableError` on every call; a call counter.
        Input: `generator.generate(identity, "шаг", [], page)`.
        Assertions (verbatim):
        ```
        pytest.raises(LlmUnavailableError)
        provider.calls == 1        # no retries on an infrastructure failure
        budgets: 1 generation attempt consumed
        ```
      - an additional edge: `regenerate` starts from the passed existing_code/error
        and spends the healing budget (`try_healing`), not generation
- [x] **Debugging**: `.venv/bin/pytest tests/engine/ -x`
- [x] **Contract re-verification**: every request carries the exact PAGE_API_SURFACE;
      the prompt verbatim; only successes are cached
- [x] **Lint**: `.venv/bin/ruff check prettyplay/engine/ tests/engine/`

### Task 18: `StepHealer` — classification and healing (prettyplay/engine/healer.py)

Context: the entity of the engine cell, `location: healer.py`. Constructor:
`StepHealer(config, provider, generator, cache, budgets, reporter)`. The method
`heal(step: CachedStep, error: str, previous_steps: list[str], page: PageFacade) ->
CachedStep` (the post-D1 signature — with `previous_steps`). Classification via
`provider.classify_failure` with `CLASSIFICATION_PROMPT` (from Task 17's generator.py);
branching: product_defect → ProductDefectError (the cache untouched); incurable →
IncurableStepError with the verdict fields; rot → `generator.regenerate(...)` →
`on_healed` → return healed. The engine cell completes with this task.

**Usages relevant to this task:**
- `classification_prompt`: the system message of the classification request (verbatim).
- `classification` (from `prettyplay/llm`): the healing-decision categories.
- `healing` (imported usage, cell .usages): heal accepts previous_steps; separate
  limits.
- `taxonomy`: the failure kinds and their fields.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
heal(step, error, previous_steps, page):
  step_text = step.identity.normalized_text
  snapshot = page.aria_snapshot()
  screenshot = page.screenshot() if config.send_screenshots else None
  verdict = provider.classify_failure(prompt=CLASSIFICATION_PROMPT, step_text=step_text,
              code=step.code, error=error, snapshot=snapshot, screenshot=screenshot)
  reporter.emit("on_healing_started", {"step_text": step_text, "category": verdict.category})
  IF verdict.category == "product_defect":
    raise ProductDefectError(step_text, verdict.explanation)      # cache untouched
  IF verdict.category == "incurable":
    raise IncurableStepError(step_text, verdict.explanation, verdict.recommendation)
  # rot:
  healed = generator.regenerate(identity=step.identity, step_text=step_text,
             previous_steps=previous_steps, page=page,
             existing_code=step.code, error=error)
  reporter.emit("on_healed", {"step_text": step_text, "explanation": verdict.explanation})
  RETURN healed
```

- [x] **STEP 0 (Declaration)**: declare that Task 18 — StepHealer — is being executed
- [x] **Contract tests** (`tests/engine/test_healer.py`):
      `from prettyplay.engine import StepHealer`; the constructor signature; the method
      `heal(step, error, previous_steps, page)`. Expected failure
- [x] **Code**: create `prettyplay/engine/healer.py` per the algorithm above
- [x] **Code**: `prettyplay/engine/__init__.py` — the full cell facade:
      `run_step_code`, `StepGenerator`, `StepHealer` + `__all__`
- [x] **Interface verification**: `.venv/bin/pytest tests/engine/test_healer.py -v`
- [x] **Logic tests**:
      - `test_heal_rot_regenerates_and_reports_healed` — Setup: the classification
        provider → `FailureClassification("rot", "кнопка переименована", "проверить
        шаг")`; regeneration via a stub generator object (recorder: regenerate(...) →
        returns the healed CachedStep); healer = StepHealer(config, provider,
        generator, cache, budgets, reporter).
        Input: `healer.heal(step=failed_step, error="element not found",
        previous_steps=["открыть"], page=page)`.
        Assertions (verbatim):
        ```
        the healed step is returned
        regenerate called exactly once with existing_code=failed_step.code and previous_steps=["открыть"]
        recorded: on_healing_started(category="rot"), on_healed(explanation="кнопка переименована")
        cache.save not called directly by the healer (the generator writes it after successful execution)
        ```
      - `test_heal_provider_unavailable_propagates` — Setup: a stub provider whose
        `classify_failure` raises `LlmUnavailableError`; a generator spy (a call
        recorder); a cache spy (save must not be called).
        Input: `healer.heal(failed_step, "err", [], page)`.
        Assertions (verbatim):
        ```
        pytest.raises(LlmUnavailableError)
        generator.regenerate not called; cache.save not called
        ```
      - `test_heal_product_defect_raises_and_keeps_cache` — Setup: the classification
        provider → `("product_defect", "ожидание не оправдалось", "чинить продукт")`;
        a cache spy (save must not be called); a generator spy.
        Input: `healer.heal(failed_step, "text mismatch", ["шаг"], page)`.
        Assertions (verbatim):
        ```
        pytest.raises(ProductDefectError); issubclass(ProductDefectError, PrettyplayError)
        generator.regenerate not called; cache.save not called
        ```
      - `test_heal_incurable_carries_verdict_fields` — Setup: the classification
        provider → `("incurable", "текст шага не соответствует реальности",
        "переформулируйте шаг")`.
        Input: `healer.heal(failed_step, "err", [], page)`.
        Assertions (verbatim):
        ```
        pytest.raises(IncurableStepError)
        excinfo.value.reason == "текст шага не соответствует реальности"
        excinfo.value.recommendation == "переформулируйте шаг"
        str(excinfo.value) contains all three fields
        ```
- [x] **Debugging**: `.venv/bin/pytest tests/engine/ -x`
- [x] **Contract re-verification**: anti-masking (product_defect always fails loudly);
      the healed code replaces the cache only after successful execution
- [x] **Lint**: `.venv/bin/ruff check prettyplay/engine/ tests/engine/`
- [x] The engine cell is complete: `goga lint` — 0 errors; the facade check:
      `.venv/bin/python -c "from prettyplay.engine import StepGenerator, StepHealer, run_step_code"`

### Task 19: `PrettyplayRuntime` + `get_runtime` — composition root (prettyplay/runtime.py)

Context: two entities of one `location: runtime.py` of the root cell. A run-scoped
composition root: everything shared by tests, nothing per-test. `get_runtime()` — a
process-wide singleton (the module global `_runtime`). Properties: `config` (eager),
`budgets = RunBudgets(config.generation_attempts, config.healing_attempts)` (eager),
`driver = DriverSession(config)` (lazily), `provider = create_provider(config)` (lazily
— provider construction requires no keys, the client is created on the first request).
`open_page() → driver.open_context()`; `close() → driver.close()` (safe when never
started). The root `prettyplay/__init__.py` (currently empty) starts accumulating the
facade: `PrettyplayRuntime`, `get_runtime`.

**Usages relevant to this task:**
- `conventions`: isolate the global in tests (reset before/after), `mock.patch`
  load_config.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
_runtime: PrettyplayRuntime | None = None (module global)

get_runtime():
  global _runtime
  IF _runtime is None: _runtime = PrettyplayRuntime(load_config(None))
  RETURN _runtime

PrettyplayRuntime.__init__(config):
  self._config = config
  self._budgets = RunBudgets(config.generation_attempts, config.healing_attempts)
  self._driver = None; self._provider = None
config (property) → self._config
budgets (property) → self._budgets
driver (property): lazily self._driver = DriverSession(self._config)
provider (property): lazily self._provider = create_provider(self._config)
open_page() → self.driver.open_context()
close() → IF self._driver: self._driver.close()
```

- [x] **STEP 0 (Declaration)**: declare that Task 19 — PrettyplayRuntime + get_runtime —
      is being executed
- [x] **Contract tests** (`tests/test_runtime.py`): `from prettyplay import
      PrettyplayRuntime, get_runtime`; the properties
      `config`/`budgets`/`driver`/`provider`; the methods `open_page`/`close`;
      `get_runtime()` callable without arguments. Expected failure
- [x] **Code**: create `prettyplay/runtime.py` per the algorithm above; fill in
      `prettyplay/__init__.py`: `from .runtime import PrettyplayRuntime, get_runtime` +
      the start of `__all__`
- [x] **Interface verification**: `.venv/bin/pytest tests/test_runtime.py -v`; the
      facade: `.venv/bin/python -c "from prettyplay import PrettyplayRuntime, get_runtime"`
- [x] **Logic tests**:
      - `test_get_runtime_is_process_singleton` — Setup: isolate the global (reset the
        private global before/after); `mock.patch` load_config → a fixed Config.
        Input: `get_runtime()` ×2.
        Assertions (verbatim):
        ```
        runtime1 is runtime2
        load_config called exactly once
        ```
      - `test_runtime_constructs_without_llm_credentials` — Setup:
        `monkeypatch.delenv` both keys; the runtime global isolated.
        Input: `runtime = PrettyplayRuntime(Config(model="gpt-5"))`; read
        `runtime.config`, `runtime.budgets`.
        Assertions (verbatim):
        ```
        construction without exceptions
        runtime.provider has not been created yet (lazy) — touching it is not required in the test
        ```
      - an additional edge: `close()` before any `open_page()` — no-op; `budgets` — a
        RunBudgets with the limits from config
- [x] **Debugging**: `.venv/bin/pytest tests/test_runtime.py -x`
- [x] **Contract re-verification**: runtime construction without credentials; one
      runtime per process; repeated calls are cheap
- [x] **Lint**: `.venv/bin/ruff check prettyplay/runtime.py prettyplay/__init__.py tests/test_runtime.py`

### Task 20: `StepExecutor` — the step cycle (prettyplay/executor.py)

Context: the entity of the root, `location: executor.py`. Constructor:
`StepExecutor(cache_key, cache, generator, healer, budgets, reporter)` + the per-test
state `self._scenario: list[str]` (the test's scenario context).
`execute(step_text, step_type, page)`: the full cycle — hit → execute; miss → generate;
a cache failure → heal. The internal helper `short(exc)` — the first line of `str(exc)`,
truncated to 200 characters.

**Usages relevant to this task:**
- `generation`, `healing` (from `prettyplay/engine`): the loops the executor delegates
  to.
- `taxonomy` (from `prettyplay/failures`): the failure kinds propagated with
  on_step_failed.
- `conventions`: stub provider/page objects.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
__init__(cache_key, cache, generator, healer, budgets, reporter):
  state + self._scenario: list[str] = []   # the test's scenario context
execute(step_text, step_type, page):
  reporter.emit("on_step_started", {"step_text": step_text, "step_type": step_type})
  identity = StepIdentity(cache_key=self.cache_key, step_type=step_type,
                          normalized_text=normalize_step_text(step_text))
  cached = cache.load(identity)
  IF cached is not None:
    try:
      run_step_code(cached.code, page)
    except Exception as e:
      self._healer.heal(cached, short(e), self._scenario, page)   # healed = re-executed
  ELSE:
    self._generator.generate(identity, step_text, self._scenario, page)
  self._scenario.append(step_text)
  reporter.emit("on_step_passed", {"step_text": step_text, "step_type": step_type})
  # ANY raise from the branches above:
  an except-wrapper around the whole body: reporter.emit("on_step_failed", {"step_text": step_text,
    "step_type": step_type, "error": short(exc)}); raise
short(exc) → the first line of str(exc), truncated to 200 characters
```

Documented interpretation (verbatim from the design, mandatory for the implementation):
a step falls under classification (and therefore under ProductDefectError) only after its
first successful generation and caching; a step that has never generated yields
`IncurableStepError` and never `ProductDefectError`.

- [x] **STEP 0 (Declaration)**: declare that Task 20 — StepExecutor — is being executed
- [x] **Contract tests** (`tests/test_executor.py`): `from prettyplay import
      StepExecutor`; the constructor signature; the method
      `execute(step_text, step_type, page)`. Expected failure
- [x] **Code**: create `prettyplay/executor.py` per the algorithm above (delegation to
      the engine, on_step_failed + propagation in the except-wrapper around the whole
      body)
- [x] **Code**: `prettyplay/__init__.py` — add `from .executor import StepExecutor` to
      the re-exports and `__all__`
- [x] **Interface verification**: `.venv/bin/pytest tests/test_executor.py -v`
- [x] **Logic tests** (a fake page; the cache on tmp_path; stub generator/healer
      recorders):
      - the hit path: a step pre-written to the cache → `run_step_code` executes,
        generator/healer not called, `on_step_started`/`on_step_passed` recorded
        (step_type passed correctly)
      - the miss path: an empty cache → `generator.generate` called with the identity
        and `previous_steps`; after success — `on_step_passed`; the scenario context
        grows (`_scenario` is appended the original sentences — observed through the
        second step's behavior)
      - the failure branch: the generator raises IncurableStepError → `on_step_failed`
        recorded with the short error; the exception re-raised as the same kind
      - edge: `short()` — a multi-line error → the first line up to 200 characters in
        `on_step_failed`
- [x] **Debugging**: `.venv/bin/pytest tests/test_executor.py -x`
- [x] **Contract re-verification**: the cache path without LLM; the scenario context
      per-test; propagation by kind with on_step_failed
- [x] **Lint**: `.venv/bin/ruff check prettyplay/executor.py tests/test_executor.py`

### Task 21: `PrettyTest` — the integrator's main object (prettyplay/scenario.py)

Context: the entity of the root, `location: scenario.py`. One instance per test; owns
the cache addressing and the test's isolated browser context; the step cycle is
delegated to the executor. Constructor `PrettyTest(cache_key, cache_path=None)`:
`runtime = get_runtime()`; `reporter = StepReporter(hooks=[])`;
`cache = StepCache(runtime.config, cache_path, reporter)`;
`generator = StepGenerator(runtime.config, runtime.provider, cache,
runtime.budgets, reporter)`; `healer = StepHealer(runtime.config,
runtime.provider, generator, cache, runtime.budgets, reporter)`; `executor =
StepExecutor(cache_key, cache, generator, healer, runtime.budgets, reporter)`; the page
lazily. Context manager: `__enter__` → self, `__exit__` → close() (does not swallow
exceptions). The root facade completes with this task.

**Usages relevant to this task:**
- `hooks` (from `prettyplay/reporting`): add_hooks registers StepHooks before the first
  step.
- `taxonomy`: step failures propagate by kind.
- `steps`, `lifecycle` (cell .usages — the main object's API): action/assertion/close.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

Algorithm (verbatim from the design):
```
__init__(cache_key, cache_path=None):
  self._runtime = get_runtime()
  self._reporter = StepReporter(hooks=[])
  self._cache = StepCache(self._runtime.config, cache_path, self._reporter)
  self._generator = StepGenerator(self._runtime.config, self._runtime.provider,
                                  self._cache, self._runtime.budgets, self._reporter)
  self._healer = StepHealer(self._runtime.config, self._runtime.provider, self._generator,
                            self._cache, self._runtime.budgets, self._reporter)
  self._executor = StepExecutor(cache_key, self._cache, self._generator, self._healer,
                                self._runtime.budgets, self._reporter)
  self._page = None
cache_key (property) → the executor's key (for diagnostics)
_page(): IF self._page is None: self._page = self._runtime.open_page(); RETURN self._page
action(text)    → self._executor.execute(text, "action",    self._page())
assertion(text) → self._executor.execute(text, "assertion", self._page())
add_hooks(hooks)→ self._reporter.hooks.append(hooks)
close()         → IF self._page: self._page.close(); self._page = None
__enter__ → self;  __exit__ → close(); return None (does not swallow exceptions)
```

Checkpoint: accessing `runtime.provider` in the constructor is safe — the client is
lazy (construction without credentials).

- [x] **STEP 0 (Declaration)**: declare that Task 21 — PrettyTest — is being executed
- [x] **Contract tests** (`tests/test_scenario.py`): `from prettyplay import
      PrettyTest`; the property `cache_key`; the methods `action(text)`/
      `assertion(text)`/`add_hooks(hooks)`/`close()`; the context manager. Expected
      failure
- [x] **Code**: create `prettyplay/scenario.py` per the algorithm above
- [x] **Code**: `prettyplay/__init__.py` — the full root facade:
      `from .scenario import PrettyTest`, `from .executor import StepExecutor`,
      `from .runtime import PrettyplayRuntime, get_runtime`;
      `__all__ = ["PrettyTest", "StepExecutor", "PrettyplayRuntime", "get_runtime"]`
- [x] **Interface verification**: `.venv/bin/pytest tests/test_scenario.py -v`; the
      facade: `.venv/bin/python -c "from prettyplay import PrettyTest"`
- [x] **Logic tests** (the runtime global isolated; mock `runtime.open_page` → a fake
      page):
      - `test_prettytest_context_manager_closes_page` — Setup: the runtime global
        isolated; `mock` runtime.open_page → a fake page recording close().
        Input:
        ```python
        with PrettyTest("k") as t:
            t.action("шаг")
        ```
        Assertions (verbatim):
        ```
        page.closed is True; runtime.close not called (the runtime lives on)
        a second with: a new page, the same runtime
        ```
      - an additional positive: `add_hooks(hooks)` appends to reporter.hooks (visible
        in the next step's fan-out); the `cache_key` property returns the passed key;
        construction opens no browser (open_page not called before the first step);
        edge: `close()` twice — no-op; `__exit__` does not swallow an exception (it
        propagates)
- [x] **Debugging**: `.venv/bin/pytest tests/test_scenario.py -x`
- [x] **Contract re-verification**: construction is cheap (the browser and the page
      are lazy); no cross-test state
- [x] **Lint**: `.venv/bin/ruff check prettyplay/ tests/`
- [x] The root cell is complete: `goga lint` — 0 errors; the full-root facade check

### Task 22: Integration tests of the full step cycle (tests/test_integration.py)

Context: cross-entity scenarios through the public `PrettyTest` facade — the product's
central promises: a cached run requires no LLM at all (Flow B), the scenario context
feeds the next generation (Flow A), a broken cached step → self-healing (Flow C). The
provider — a stub with the `LlmProvider` signatures raising AssertionError on a
"cache path without LLM" violation (violation detection); the page — a fake object with
the facade methods; the runtime global isolated and reset; env without keys; the file
cache — `tmp_path` only. Per conventions, integration tests live directly in `tests/`.

**Usages relevant to this task:**
- `hooks`: an event recorder to check on_step_started/on_step_passed.
- `taxonomy`: the failure kinds at the boundary.
- `conventions`: integration tests of multi-package scenarios — directly in `tests/`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] Create test file `tests/test_integration.py` (shared fixtures: an isolated
      runtime with a tmp cache, a stub provider, a fake page, a hook recorder)
- [x] `test_action_cached_step_runs_without_llm` — Setup: a `tmp_path` cache with a
      pre-written step file (a valid module for "открыть страницу логина"); the runtime
      global reset; env without keys; a stub provider raising
      `AssertionError("provider must not be called")` on any call (violation
      detection); the page replaced with a fake (mock runtime.open_page).
      Input: `t = PrettyTest("login-flow"); t.action("открыть страницу логина");
      t.close()`.
      Assertions (verbatim):
      ```
      the step completed without exceptions
      recorded: on_step_started, on_step_passed (step_type="action")
      the stub provider was not called (cache path without LLM)
      ```
- [x] `test_scenario_context_feeds_next_generation` — Setup: an empty cache; a stub
      provider returning working code; a recorder of previous steps in requests; a fake
      page.
      Input: `t = PrettyTest("k"); t.action("шаг один"); t.action("шаг два"); t.close()`.
      Assertions (verbatim):
      ```
      the provider's second request received previous_steps == ["шаг один"]
      the first — []
      ```
- [x] An additional integration scenario (Flow C from the design): a cached step
      failing on the fake page; the classification provider → rot; regeneration returns
      working code → the step passes, the cache file rewritten,
      on_healing_started(category="rot") and on_healed recorded, then on_step_passed
- [x] Test edge case: `PrettyTest` with `cache_path` — steps of different subdirectories
      do not collide (the address includes the subdirectory)
- [x] Run validation: `.venv/bin/pytest tests/ -x` — the whole suite green;
      `.venv/bin/ruff check prettyplay/ tests/` — 0 errors;
      `.venv/bin/python -c "from prettyplay import PrettyTest"` — the root facade

---

## Validation Commands

- `.venv/bin/pytest tests/ -x`: Run all tests (the full suite; the plan's final check)
- `.venv/bin/pytest tests/<cell>/test_<module>.py -v`: Run a specific test (in every task)
- `.venv/bin/ruff check prettyplay/ tests/`: Lint check (line-length 120, complexity 10)
- `.venv/bin/python -c "from prettyplay import PrettyTest"`: Verify root facade importable
- `.venv/bin/python -c "from prettyplay.config import Config, load_config"`: config facade
- `.venv/bin/python -c "from prettyplay.reporting import StepHooks, StepReporter"`: reporting facade
- `.venv/bin/python -c "from prettyplay.failures import PrettyplayError, ProductDefectError, IncurableStepError, LlmUnavailableError"`: failures facade
- `.venv/bin/python -c "from prettyplay.driver import DriverSession, PageFacade, LocatorFacade"`: driver facade
- `.venv/bin/python -c "from prettyplay.cache import StepCache"`: cache facade (verbatim from storage.md)
- `.venv/bin/python -c "from prettyplay.llm import create_provider, FailureClassification"`: llm facade
- `.venv/bin/python -c "from prettyplay.engine import StepGenerator, StepHealer, run_step_code"`: engine facade
- `goga lint`: Verify cells (8 cells, 0 errors; after every completed cell)

---

## Completion Criteria

- [x] Every contract entity is implemented in the correct `location`
- [x] Every contract entity is accessible from the facade (8 `__init__.py` + `__all__`)
- [x] Properties and methods match the declared API (signatures verbatim from
      CODEMANIFEST)
- [x] Descriptions are reflected in behavior (the design's algorithms implemented as
      specified)
- [x] Contract dependencies are met (Imports resolved with relative imports between
      cells)
- [x] Re-exports are accessible from the facade
- [x] Every coding task followed the TDD workflow (contract tests → code →
      verification → logic tests → debugging → re-verification → lint)
- [x] Contract tests and logic tests cover facade, API, and behavior within each coding
      task
- [x] Integration tests exist where cross-entity scenarios require them (Task 22)
- [x] No package boundary was expanded (no new cells; imports inside the package are
      relative)
- [x] `CODEMANIFEST` files were not modified (contract is read-only)
- [x] All validation commands pass
- [x] Every Usages entry is mentioned in at least one task (Phase 2 calibration):
      `conventions` — all tasks; `pydantic` — 2/3/9/12; `playwright` — 6/7;
      `openai` — 14; `anthropic` — 15; `generation_prompt` — 17;
      `classification_prompt` — 17/18; imported `hooks` — 4/10/21; `taxonomy` —
      5/13/18/20; `generation`/`healing` — 17/18/20; `facade` — 7/16/17;
      `classification` — 12/18


