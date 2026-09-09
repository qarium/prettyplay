# Plan: `additional-configuration`

Result of compiling the verified design document (`.goga/history/2026/additional-configuration/design.md`,
reviewed and approved by the design-review stage) into ralphex execution tasks. This format is compatible
with ralphex execution.

---

## Purpose

Materialize the `additional-configuration` contract changes into the Python implementation of `prettyplay`:
per-test runtime lifecycle (no process-wide singleton), `PrettyConfig` layered merging over the file layer,
generation user instructions routed to generation/regeneration requests only, three universal locators on the
page facade, and the remote browser endpoint (ws/wss connect).

After implementation the package provides: a `PrettyTest` that accepts `config: PrettyConfig | None` and owns
its whole runtime; `load_config(pyproject_path=None, overrides=None)` with the explicit-values-win overlay;
`Config` with `generation_prompt` and validated `browser_endpoint` fields publicly re-exported as `PrettyConfig`;
`PageFacade.find_by_attribute/css/xpath`; a `DriverSession` that connects over ws when the endpoint is set;
`generate_step_code(..., user_instructions, ...)` with an identical USER INSTRUCTIONS block in both providers;
a `StepGenerator` carrying the instructions on every request of both pools; per-test `RunBudgets`.

The most important gaps between contract and code: the six CODEMANIFEST files are already applied and lint-clean,
the implementation still carries the per-run singleton (`get_runtime`), the 11-setting loader (13 in the contract),
the instructions-free provider port, and the locator-trio-free page facade.

Strategy: cell-by-cell bottom-up (`config → cache → llm → driver → engine → root`), each task TDD and green before
the next; wording-only per-run → per-test updates ride along with the files each task already touches.

## Context

### Contract Surface

**Entity: `Config`** — Task 1
- Type: class (pydantic model, kw_only)
- Declared `location`: `prettyplay/config/models.py`
- Facade obligation: importable from `prettyplay.config`
- Properties: 13 fields in the contract order — provider, browser, model, generation_model, classification_model,
  base_url, cache_root, **generation_prompt** (new), **browser_endpoint** (new), generation_attempts,
  healing_attempts, send_screenshots, headless — str fields default `""`, attempts `PositiveInt` 3/2,
  `send_screenshots` False, `headless` True; plus `effective_generation_model` / `effective_classification_model`
  (unchanged)
- Semantic requirements: a non-empty `browser_endpoint` is a valid ws/wss URL — otherwise a loud actionable error;
  every field has an empty default (unset means file layer); attempts are budgets **per step per test**; `headless`
  is scoped to the local launch; no secret values in fields
- Imported dependencies: none (pydantic only)
- Annotation context: global — kw_only, empty defaults, layered resolution principle, "`Config` is publicly known
  as PrettyConfig"; use `pydantic` cook for data models
- New public alias: `PrettyConfig = Config` defined in `models.py`, exported by the cell facade

**Routine: `load_config`** — Task 2
- Type: function
- Declared `location`: `prettyplay/config/loader.py`
- Facade obligation: importable from `prettyplay.config`
- Signature: `load_config(pyproject_path: str | None = None, overrides: Config | None = None) -> config: Config`
  (both parameters optional; single-argument calls keep working)
- Semantic requirements: env override exists for every setting (13 env names including
  `PRETTYPLAY_GENERATION_PROMPT` and `PRETTYPLAY_BROWSER_ENDPOINT`); a raw pydantic `ValidationError` never leaves
  the loader (`ConfigurationError` rendered per-setting, original chained); empty `cache_root` resolves to the
  absolute default; the overlay — a field participates when it was passed at construction (`model_fields_set`)
  and is non-empty for strings; untouched model defaults never overwrite file values; programmatic layer wins
  over the pyproject+env layer
- Annotation context: use `pydantic` cook for the layered merge mechanics (`model_fields_set` + `model_copy`)

**Entity: `RunBudgets`** — Task 3
- Type: class
- Declared `location`: `prettyplay/cache/budgets.py`
- Facade obligation: importable from `prettyplay.cache`
- Methods: `try_generation(identity) -> allowed: bool`, `try_healing(identity) -> allowed: bool` (unchanged)
- Semantic requirements: **the registry lives for the lifetime of one test, owned by the test's runtime** — every
  test starts with full limits, a step reused across tests gets a fresh budget in each test; identity key is
  `StepIdentity`; no persistence. Signature and mechanics unchanged — the change is ownership semantics and
  documentation wording (per-run → per-test)

**Entity: `LlmProvider` (port method `generate_step_code`) + mutations `LlmProvider::OpenAiProvider` / `LlmProvider::AnthropicProvider`** — Task 4
- Type: class (port) + two SDK implementations
- Declared `location`s: `prettyplay/llm/provider.py`, `prettyplay/llm/openai_provider.py`, `prettyplay/llm/anthropic_provider.py`; shared helper in `prettyplay/llm/_request.py`
- Facade obligation: `LlmProvider`, `OpenAiProvider`, `AnthropicProvider`, `create_provider` importable from `prettyplay.llm`
- Method signature: `generate_step_code(prompt: str, user_instructions: str, step_text: str, previous_steps: list[str], snapshot: str, screenshot: bytes | None, page_api: str, existing_code: str | None, error: str | None) -> code: str` — `user_instructions` is the **second** parameter in the port and both implementations
- Semantic requirements: a non-empty `user_instructions` renders **verbatim** as a separate `USER INSTRUCTIONS`
  block of the user content placed **after the page API block, before the regeneration-only blocks (CODE, ERROR)**,
  identically in both providers (parity requirement); empty — no block; `classify_failure` never carries the
  instructions; providers pass the value through unchanged, request/response handling untouched
- Annotation context: provider parity is absolute; the user instructions input participates in both
  implementations with identical semantics; use `openai` / `anthropic` cooks for SDK patterns

**Entity: `DriverSession`** — Task 6
- Type: class
- Declared `location`: `prettyplay/driver/session.py`
- Facade obligation: importable from `prettyplay.driver`
- Methods: `open_context() -> page: PageFacade`, `close()` (signatures unchanged)
- Semantic requirements: per-test lifecycle owner; the start mode branches on the `browser_endpoint` setting of
  `Config`: empty — local launch with headless and the channel for chrome/msedge; set — connect over the
  Playwright ws endpoint of the selected engine (headless ignored, channels do not apply, chrome/msedge map to
  the chromium engine — the browser setting selects the engine); **a failed connect fails loudly with an
  actionable message naming the endpoint** (re-raised wrapped, chained to Playwright's original — the raw connect
  error carries only the OS-level cause); a failed launch or connect stops the started driver and closes the
  thread so a retry begins from a clean state
- Annotation context: use `playwright` cook for the sync lifecycle, channels, remote connect

**Entity: `PageFacade` (three new methods)** — Task 5
- Type: class
- Declared `location`: `prettyplay/driver/page.py`
- Facade obligation: importable from `prettyplay.driver` (class itself already is)
- New methods (after `find_by_text`, in the manifest order):
  - `find_by_attribute(name: str, value: str) -> element: LocatorFacade` — locate one element by the value of the
    attribute `name` (intended for data-* attributes); auto-waits exactly like the other locating methods
  - `find_by_css(selector: str) -> element: LocatorFacade` — locate one element by a CSS selector
  - `find_by_xpath(xpath: str) -> element: LocatorFacade` — locate one element by an XPath expression
- Semantic requirements: every lookup runs through the driver-thread boundary (`_call` + `_wrap_locator`), returns
  a `LocatorFacade` inheriting auto-wait; no raw Playwright object crosses the facade
- Annotation context: the facade surface is a backward-compatibility contract — extend, never rename or remove

**Entity: `StepGenerator`** — Task 7
- Type: class
- Declared `location`: `prettyplay/engine/generator.py`
- Facade obligation: importable from `prettyplay.engine`
- Methods: `generate(...)`, `regenerate(...)` (signatures unchanged)
- Semantic requirements: every provider request of both pools passes the user instructions — the effective config
  `generation_prompt` — via the `user_instructions` parameter (the engine passes the value **unconditionally**;
  the empty check lives in the provider helper alone); the instructions take no part in the step address; the
  system prompt constant is renamed `GENERATION_PROMPT` → `SYSTEM_PROMPT` and its text gains the USER INSTRUCTIONS
  input line and the universal-locating priority line; `PAGE_API_SURFACE` gains the three locator rows mirroring
  `facade` exactly
- Annotation context: use `system_prompt` (engine Usages) verbatim; the listing mirrors `facade` from Imports —
  the listing and the practice change together; instructions reach generation/regeneration only, never
  classification, never the step address

**Entity: `PrettyTest`** — Task 8
- Type: class
- Declared `location`: `prettyplay/scenario.py`
- Facade obligation: importable from `prettyplay`
- Signature: `PrettyTest(cache_key: str, cache_path: str | None = None, config: PrettyConfig | None = None)`
- Methods: `action`, `assertion`, `get_screenshot`, `save_screenshot`, `add_hooks`, `close` (unchanged shapes)
- Semantic requirements: resolves the effective config via `load_config` with `overrides = config`; builds its own
  `PrettyplayRuntime` — no process-wide singleton exists; construction is cheap (browser lazy, no LLM credentials);
  `close` closes the test page context **and stops the whole runtime of this test**; idempotent; the context
  manager exit does the same; no cross-test state on the instance
- Imported dependencies: `Config AS PrettyConfig`, `load_config`, `DriverSession`/`PageFacade` (via runtime),
  engine types, `RunBudgets`, `StepCache`

**Entity: `PrettyplayRuntime`** — Task 9
- Type: class
- Declared `location`: `prettyplay/runtime.py`
- Facade obligation: importable from `prettyplay`
- Signature: `PrettyplayRuntime(config: PrettyConfig)`
- Properties: `config`, `driver` (lazy), `budgets`, `provider` (lazy) — unchanged shapes
- Methods: `open_page()`, `close()` — unchanged shapes
- Semantic requirements: **one instance serves exactly one test**; **every instance registers its own close with
  `atexit`**, manual calls stay valid and idempotent; construction starts nothing expensive
- Deleted: `get_runtime()` and the module global `_runtime` — the process-wide singleton leaves the public
  contract and the code (deliberate, ADR-approved breaking change; no external consumers exist)

### Entity Interactions (from the design, verbatim)

```
integrator
   │  PrettyTest(cache_key, cache_path=None, config=PrettyConfig(...) | None)
   ▼
load_config(pyproject_path=None, overrides=config)          [prettyplay/config]
   │  pyproject.toml [tool.prettyplay] → env overrides → validated file layer
   │  + overlay of explicitly set override fields (model_fields_set, non-empty strings)
   ▼
effective Config (== PrettyConfig)
   │
   ▼
PrettyplayRuntime(effective config)                          [prettyplay/runtime]
   │  atexit.register(self.close) — one hook per instance
   ├─► RunBudgets(generation_attempts, healing_attempts)     [prettyplay/cache]  per test
   ├─► DriverSession(config)                    lazy        [prettyplay/driver]
   │     ├─ browser_endpoint == ""  → engine.launch(headless, channel for chrome/msedge)
   │     └─ browser_endpoint != ""  → engine.connect(ws_endpoint)   (headless ignored,
   │                                                                 channels do not apply)
   │     └─► open_context() → PageFacade ──► LocatorFacade
   │            find_by_role / find_by_label / find_by_text
   │            find_by_attribute / find_by_css / find_by_xpath      (new)
   └─► create_provider(config)                  lazy        [prettyplay/llm]
          ├─► OpenAiProvider(config) | AnthropicProvider(config)
          │     generate_step_code(prompt=SYSTEM_PROMPT,
          │                       user_instructions=config.generation_prompt, ...)
          │       user content: STEP | PREVIOUS STEPS | PAGE SNAPSHOT | [SCREENSHOT]
          │                    | PAGE API | [USER INSTRUCTIONS] | [CODE | ERROR]
          └─► classify_failure(prompt=CLASSIFICATION_PROMPT, ...)     (no instructions block)
   │
   ▼
PrettyTest.action/assertion → StepExecutor.execute            [prettyplay/executor]
   ├─ cache hit      → run_step_code(cached.code)             (no LLM, no instructions)
   ├─ cache miss     → StepGenerator.generate                  (instructions in every request)
   └─ cached failure → StepHealer.heal → classify → verdict branch
                          product_defect → ProductDefectError
                          incurable      → IncurableStepError
                          rot           → StepGenerator.regenerate (instructions carried)
```

Data flows (from the design, verbatim):

- **Configuration flow**: `PrettyConfig(...)` (integrator, explicit fields only) → `load_config(None, overrides)`
  → file layer (pyproject → env) → overlay → effective `Config` → `PrettyplayRuntime` → `StepCache`
  (cache_root), `DriverSession` (browser, headless, browser_endpoint), `create_provider` (provider, models,
  base_url), `RunBudgets` (generation_attempts, healing_attempts), `StepGenerator` (send_screenshots,
  generation_prompt). One resolved object feeds every consumer — no consumer re-reads pyproject or env.
- **Instructions flow**: `config.generation_prompt` → `StepGenerator._loop` →
  `provider.generate_step_code(user_instructions=...)` → `build_fields_text` → USER INSTRUCTIONS block of the
  user content → SDK request (openai `messages` / anthropic `messages`). The value never enters
  `classify_failure`, `StepIdentity`, `CachedStep` or the cache file.
- **Budget flow**: `PrettyplayRuntime.__init__` constructs one `RunBudgets` per test from the effective config
  limits; `StepGenerator._loop` spends through `try_generation`/`try_healing` keyed by
  `StepIdentity.filename`; a step reused by N tests in one process encounters N fresh registries.
- **Browser flow**: first step → `PrettyTest._ensure_page` → `runtime.open_page()` →
  `DriverSession.open_context()` → launch or connect (first call only) → new isolated context + page →
  `PageFacade` bound to the driver thread. Test close → `PageFacade.close` (context) → `PrettyplayRuntime.close`
  → browser close, Playwright stop, driver thread join.

Implementation order (bottom-up, matches the architecture plan): `config` → `cache` → `llm` → `driver` →
`engine` → root (`runtime.py`, `executor.py`, `scenario.py`, `__init__.py`). Dependents of the changed cells:
config ← {root, cache, driver, engine, llm}; cache ← {root, engine}; llm ← {root, engine}; driver ← {root,
engine}; engine ← {root}. `failures` and `reporting` are untouched.

### Re-exports

- Name: `PrettyConfig`
- Source: `Imports` entry `Config AS PrettyConfig` from `prettyplay/config` (the alias `PrettyConfig = Config` is
  defined in `prettyplay/config/models.py` and exported by the config cell facade)
- Facade obligation: must be importable from `prettyplay` (`from prettyplay import PrettyConfig`); listed in the
  root `__all__` together with `PrettyTest`, `PrettyplayRuntime`, `StepExecutor`; `get_runtime` removed from the
  module and `__all__`
- Task: 9

### Usages Context

- `conventions` — `.goga/usages/conventions.md`: mandatory Python code and test rules (relative intra-package
  imports, pydantic kw_only models with empty defaults, Google docstrings, logging, mirrored test layout
  `tests/<pkg>/test_<module>.py`, ruff/pytest commands). Used by every task.
- `pydantic` — `.goga/usages/cooks/pydantic.md`: kw_only construction, empty defaults, the `[tool.prettyplay]`
  schema with the two new fields, the layered merge mechanics (`model_fields_set` + `model_copy`, non-empty
  refinement for strings only), actionable validation wrapping, tomllib/tomli fallback. Tasks 1, 2.
- `playwright` — `.goga/usages/cooks/playwright.md`: sync API lifecycle, engine/channel matrix, remote ws connect
  (headless ignored, channels do not apply, browser selects the engine), locator auto-wait, CSS attribute
  selectors, the `xpath=` engine prefix. Tasks 5, 6.
- `openai` / `anthropic` — `.goga/usages/cooks/openai.md`, `.goga/usages/cooks/anthropic.md`: SDK call patterns
  and error mapping of the two providers. Task 4.
- `system_prompt` (engine, inline in CODEMANIFEST `Usages`): the fixed system prompt of every generation request
  — now documenting the USER INSTRUCTIONS input and the universal-locating priority. Task 7 (constant
  `SYSTEM_PROMPT` takes this text verbatim).
- `classification_prompt` (engine, inline): unchanged; verified it carries no instructions input — the negative
  test of Task 4 pins it.

### Imported Usages

- `taxonomy` from `prettyplay/failures` (imported by config, root) — the failure base `PrettyplayError`;
  `ConfigurationError` stays a mutation of the base. Path: `prettyplay/failures/.usages/taxonomy.md`. Tasks 1, 2, 9.
- `hooks` from `prettyplay/reporting` (imported by cache, root) — hook payload contracts; unchanged. Path:
  `prettyplay/reporting/.usages/hooks.md`. Context for Task 8 wiring (reporter/hooks stay as is).
- `facade` from `prettyplay/driver` (imported by engine) — the page API surface; extended with the three locators;
  drives `PAGE_API_SURFACE`. Path: `prettyplay/driver/.usages/facade.md`. Task 7.
- `classification` from `prettyplay/llm` (imported by engine) — classification verdict semantics; unchanged;
  classification requests never carry the instructions. Path: `prettyplay/llm/.usages/classification.md`. Task 4.
- `generation`, `healing` from `prettyplay/engine` (imported by root) — the engine cycles the executor delegates
  to; already reflect per-test budgets and instructions routing. Paths: `prettyplay/engine/.usages/generation.md`,
  `prettyplay/engine/.usages/healing.md`. Tasks 8, 9 context.

### Local Usages

No `.usages/` files are created or updated by this plan. The design stage verified all six cell-level files
against their CODEMANIFESTs — every one is current, additions needed: none:

- `prettyplay/config/.usages/configuration.md` — 13-setting TOML table, 13-row env table, layered merge section,
  remote execution section — current
- `prettyplay/cache/.usages/budgets.md` — per-test semantics, fresh-budget-per-test rule, defaults — current
- `prettyplay/driver/.usages/facade.md` — Surface table includes the three new locators in the manifest order —
  current (`PAGE_API_SURFACE` mirrors it; Task 7 implements the engine side of that sync)
- `prettyplay/engine/.usages/generation.md`, `healing.md` — USER INSTRUCTIONS routing, per-test budgets — current
- `prettyplay/.usages/lifecycle.md` — per-test composition, per-test atexit, interactive-session guidance — current

### External Dependencies

- pydantic v2 (`BaseModel`, `ConfigDict(kw_only=True)`, `PositiveInt`, `field_validator`, `ValidationError`,
  `model_fields_set`, `model_copy(update=...)`)
- Playwright sync API (`sync_playwright`, `engine.connect(ws_endpoint)`, `page.locator(...)` with the CSS engine
  handling attribute selectors natively and the explicit `xpath=` engine prefix)
- openai SDK / anthropic SDK (request patterns unchanged)
- stdlib: `urllib.parse.urlparse` (scheme lowercased — `WS://` accepted), `tomllib` / `tomli` on 3.10
- Test tooling: pytest, pytest-mock (`mock.patch`), ruff (line-length 120; `E501` ignored for the prompt
  constants in `prettyplay/engine/generator.py`)
- No new dependencies; no changes to `pyproject.toml` dependencies

## Facts

- The six changed CODEMANIFEST files are applied to the tree and lint-clean (`goga lint` → cells: 8, errors: 0);
  the four-dimension consistency audit of the design-review found no contract defects
- ADR decisions behind the changes: ADR-1 per-test runtime (accepted N-atexit-hooks risk), ADR-2 explicitly set
  values win, ADR-3 instructions reach generation/regeneration only and never the cache address, ADR-4 universal
  locators with the accessibility-first priority kept, ADR-5 remote endpoint branch
- `get_runtime` removal is a deliberate public-surface breaking change; no external consumers exist
- The engine calls the provider port **by keyword**; the port signature inserts `user_instructions` as the second
  positional-or-keyword parameter — the engine tests use duck-typed stub providers with their own signatures, so
  the llm change alone leaves the engine suite green
- Playwright's raw connect error carries only the OS-level cause (`WebSocket error: connect ECONNREFUSED ...`),
  never the endpoint URL — verified against the installed driver bundle; that is why the connect branch wraps
- Playwright sniffs XPath implicitly only via `/^\(*\/\//` or a `..` prefix — `*[@id='main']` or `./div` would
  silently go to the CSS engine; the explicit `xpath=` prefix keeps every expression uniform
- The test suite builds fakes at the external boundaries only (SDK clients, Playwright objects, provider port) —
  no venv/network needed; `pytest tests/ -x` green is the gate
- `tests/conftest.py` exists and is empty — the loader merge tests get the shared `write_pyproject` fixture there
- Shared test helpers already present: `FakePage`/`seed_cache` (tests/test_scenario.py), SDK fakes
  (tests/llm/test_openai_provider.py, test_anthropic_provider.py), `FakePlaywrightFactory`/`FakeEngine`
  (tests/driver/test_session.py), recording fake page (tests/driver/test_page.py), `StubProvider`
  (tests/engine/test_generator.py)
- Current `_ENV_NAMES` covers 11 settings; the contract requires 13 (missing `generation_prompt`,
  `browser_endpoint`)
- Singleton-dependent test fixtures exist in THREE files: `isolated_runtime_global` resets the module singleton
  `_runtime` in tests/test_scenario.py, tests/test_runtime.py and tests/test_integration.py; `make_runtime`
  (tests/test_scenario.py) and `installed_runtime` (tests/test_integration.py, also patches `open_page`/
  `create_provider` on the installed instance) INSTALL the singleton — all of them are rebased/deleted together
  with the singleton (Tasks 8–9)

## Gap Analysis

- Missing contract entities (fields): `Config.generation_prompt`, `Config.browser_endpoint` with the ws/wss
  validator; the `PrettyConfig` public alias — Task 1
- Missing API surface: `load_config.overrides` parameter and the overlay algorithm — Task 2;
  `generate_step_code.user_instructions` (port + both providers) and the USER INSTRUCTIONS block in
  `build_fields_text` — Task 4; `PageFacade.find_by_attribute/css/xpath` — Task 5
- Missing facade exposure: `PrettyConfig` missing from `prettyplay.config.__all__` (Task 1) and from the root
  facade `__all__` (Task 9)
- Deleted surface still present: `get_runtime` and `_runtime` in `prettyplay/runtime.py`, exported by the root
  facade — Task 9
- Behavioral gaps: `DriverSession` has no connect branch and no endpoint-naming error wrapper — Task 6;
  `StepGenerator._loop` does not pass the instructions, `GENERATION_PROMPT` lacks the two lines,
  `PAGE_API_SURFACE` lacks the three rows — Task 7; `PrettyTest` composes over the singleton, has no `config`
  parameter, and its `close` stops only the page — Task 8; `PrettyplayRuntime` registers atexit via the singleton
  path only — Task 9
- Documentation drift: per-run wording in `budgets.py`, `session.py`, `page.py`, `runtime.py`, `scenario.py`,
  `generator.py`, `healer.py`, `executor.py` — updated by the tasks touching each file (Task 3 covers
  `budgets.py`; `healer.py` rides with Task 7; `executor.py` with Task 8)
- Existing code that can be reused: the whole step cycle, cache store, classification, healing, reporting,
  failures, scroll methods, launch path of `DriverSession`, SDK error mapping — unchanged mechanics everywhere
- Test coverage gaps: the 30 scenarios of the design's Test Stack Trace (19 positive, 4 negative, 7 edge) do not
  exist yet; env-override tests do not cover the two new names; port signature lists lack `user_instructions`;
  `TestGetRuntime` and the singleton fixtures become obsolete

---

## Tasks

> **Package ordering rule**: coding tasks for each package are completed before starting the next. Within each
> coding task, contract tests are written first (TDD workflow). Package order: `config` → `cache` → `llm` →
> `driver` → `engine` → root. Task ordering inside a package keeps every intermediate state green: Task 8
> (`PrettyTest` stops using the singleton) precedes Task 9 (`get_runtime` deleted).

### Task 1: `Config` — `generation_prompt` and `browser_endpoint` fields with ws/wss validation (TDD coding)

The settings model of the config cell gains two string fields in the contract order and a field validator, plus
the public alias. Entity `Config`, location `prettyplay/config/models.py`; facade `prettyplay/config/__init__.py`
exports the alias. The model stays kw_only with empty defaults; the validator makes a non-empty `browser_endpoint`
a hard requirement of ws/wss URL shape (stdlib `urllib.parse.urlparse`: scheme in {ws, wss} — lowercased by
`urlparse`, so `WS://` is accepted — and non-empty netloc; `"ws://"` with empty netloc is invalid). Direct
construction by an integrator surfaces the raw pydantic `ValidationError` at their own call site — the loader
wraps it later (Task 2); one model — one place of validation. The per-test attempt wording
(`generation_attempts`/`healing_attempts` docstrings: "per step per run" → "per step per test") updates here in
the same docstring pass.

**Usages relevant to this task:**
- `pydantic`: kw_only model with empty defaults; `field_validator` for the ws/wss check; the model-with-empty-defaults convention makes "explicitly set vs untouched" mechanical for Task 2
- `conventions`: Google docstrings, type hints, relative imports, mirrored test layout `tests/config/test_models.py`
- `taxonomy` from Imports: context only — `ConfigurationError` (loader cell member) derives from `PrettyplayError`; not touched here

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests** (tests/config/test_models.py — expected to fail at this stage): the `Config` signature
  exposes `generation_prompt` and `browser_endpoint` after `cache_root` in the contract field order, both `str`
  with default `""` (`inspect.signature(Config)` / `Config.model_fields`); `PrettyConfig` importable from
  `prettyplay.config`, `PrettyConfig is Config`, `"PrettyConfig" in prettyplay.config.__all__`
- [x] **Code**: declare the fields in the contract order — provider, browser, model, generation_model,
  classification_model, base_url, cache_root, `generation_prompt: str = ""`, `browser_endpoint: str = ""`,
  generation_attempts, healing_attempts, send_screenshots, headless
- [x] **Code**: add `field_validator("browser_endpoint")` — empty value returns as is (unset means local launch);
  otherwise `urlparse(value)` must give `scheme in {"ws", "wss"}` and non-empty `netloc`, else raise
  `ValueError("must be a valid ws/wss URL")` (surfacing as pydantic `ValidationError` with loc
  `("browser_endpoint",)`)
- [x] **Code**: define the module-level alias `PrettyConfig = Config` in `models.py`; export it from
  `prettyplay/config/__init__.py` (`__all__` gains `"PrettyConfig"`)
- [x] **Code**: docstrings — attribute lines for the two new fields (generation_prompt: user instructions for
  generation requests, empty — no block; browser_endpoint: ws endpoint of a remote browser, empty — local
  launch, headless ignored on connect), per-test wording for the two attempt fields
- [x] **Interface verification**: `pytest tests/config -x` — all pass
- [x] **Logic tests** (tests/config/test_models.py):
  - positive `test_models_browser_endpoint_accepts_ws_and_wss` — parametrize
    `["ws://host:3000/x", "wss://grid.example/playwright/chromium", "ws://127.0.0.1:9000", "WS://host:3000"]` →
    `Config(browser_endpoint=endpoint)` keeps the value
  - negative `test_models_rejects_non_ws_browser_endpoint` — parametrize
    `["http://ci-grid:3000", "ftp://x", "ci-grid:3000", "wss://"]` → `pytest.raises(ValidationError)`;
    assert the error loc names `browser_endpoint`
- [x] **Debugging**: `pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification**: facade `prettyplay.config` exposes `Config`, `PrettyConfig`,
  `ConfigurationError`, `load_config`; the model keeps kw_only + empty defaults; no secret fields added
- [x] **Lint**: `ruff check prettyplay tests` — fix formatting if necessary

### Task 2: `load_config` — `overrides` parameter and the layered overlay (TDD coding)

The loader routine of the config cell gains the programmatic layer. Entity `load_config`, location
`prettyplay/config/loader.py`. Signature: `load_config(pyproject_path: str | None = None, overrides: Config | None = None)` —
both parameters optional (single-argument calls keep working; the existing loader tests call it with
`pyproject_path` only). `_ENV_NAMES` grows to all 13 settings (add `generation_prompt` →
`PRETTYPLAY_GENERATION_PROMPT`, `browser_endpoint` → `PRETTYPLAY_BROWSER_ENDPOINT`); `_ALLOWED_TEXT` gains
`"browser_endpoint": "a valid ws/wss URL"` and `"generation_prompt": "a non-empty string"` so the rendered
validation message stays actionable. Verified overlay algorithm (from the design trace — implement exactly):

```
1. path = Path(pyproject_path) if given else first pyproject.toml upward from cwd
2. data = tomllib.load(path)                       # tomli fallback on 3.10
3. section = data["tool"]["prettyplay"] or {}
4. IF PRETTYPLAY_BROWSER in environ: raise ConfigurationError(legacy hint)
   merged = {**section, **env_overrides()}         # 13 settings incl. the two new env names
5. IF not merged["cache_root"]: merged["cache_root"] = absolute default
6. TRY file_config = Config(**merged)
   EXCEPT ValidationError → raise ConfigurationError(render(error)) from error
7. IF overrides is None: return file_config
8. explicit = overrides.model_fields_set
   update = {name: value for name, value in overrides
             if name in explicit and (value or not isinstance(value, str))}
   return file_config.model_copy(update=update)
```

Key semantics: participation via `model_fields_set`, not truthiness (explicit `headless=False` /
`send_screenshots=False` participate — bool, not str); empty strings never erase the file layer (explicit
`cache_root=""` leaves the resolved absolute default); env var set AND explicit override set → the override wins
(the overlay runs after the env merge); `overrides=PrettyConfig()` behaves like `None` (empty `update`, one cheap
copy); `model_copy(update=...)` performs no re-validation — safe because both instances are validated and the
validators are per-field.

**Usages relevant to this task:**
- `pydantic`: the layered merge mechanics — `model_fields_set` for participation, `model_copy(update=...)` for the
  overlay, the non-empty refinement for strings only (the cook's fixed snippet follows exactly this contract)
- `conventions`: test layout `tests/config/test_loader.py`; the new shared fixture lands in `tests/conftest.py`
- `taxonomy` from Imports: `ConfigurationError` derives from `PrettyplayError` — the catch-all except clause

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (tests/config/test_loader.py — expected to fail at this stage):
  `inspect.signature(load_config)` parameters are `["pyproject_path", "overrides"]`, both defaulting to `None`;
  existing single-argument contract/behavior tests keep passing unchanged
- [ ] **Code**: add the shared fixture `write_pyproject(tmp_path, **settings)` to `tests/conftest.py` — writes a
  `[tool.prettyplay]` TOML from the given settings and returns the file path (used by the merge tests)
- [ ] **Code**: extend `_ENV_NAMES` with the two new settings and `_ALLOWED_TEXT` with the two new entries
- [ ] **Code**: change the signature to `(pyproject_path: str | None = None, overrides: Config | None = None)`
  and implement steps 6–8 of the algorithm above (the `overrides is None` early return keeps the previous
  behavior byte-identical; then the `model_fields_set`-based overlay via `model_copy`)
- [ ] **Code**: docstring — describe the layered resolution: pyproject → env → explicit programmatic values
  (explicitly set values win; empty string means unset for string fields)
- [ ] **Interface verification**: `pytest tests/config -x` — all pass
- [ ] **Logic tests** (tests/config/test_loader.py):
  - positive `test_load_config_overrides_explicit_values_win` — file layer `browser="chromium"`, `model="gpt-5"`,
    `base_url="https://file.example/v1"`; `load_config(path, Config(browser="firefox",
    browser_endpoint="ws://ci-grid:3000/playwright/firefox"))` → `browser == "firefox"`,
    `browser_endpoint == "ws://..."`, `model`/`base_url` untouched file values survive
  - positive `test_load_config_without_overrides_returns_file_layer` — file `provider="anthropic"`,
    `generation_attempts=5`; both `load_config(path, None)` and `load_config(path, PrettyConfig())` return the
    file layer (`generation_prompt == ""`, `browser_endpoint == ""`)
  - negative `test_load_config_renders_actionable_line_for_endpoint` — file `browser_endpoint="http://bad"` →
    `ConfigurationError` with `"browser_endpoint"` and `"ws/wss"` in the message;
    `excinfo.value.__cause__` is a `ValidationError`
  - edge `test_load_config_empty_string_override_does_not_win` — file `cache_root="/custom/cache"`,
    `model="gpt-5"`; `load_config(path, Config(model="", cache_root=""))` keeps both file values
  - edge `test_load_config_explicit_false_overrides_file_true` — file `headless=true`;
    `load_config(path, Config(headless=False))` → `config.headless is False`
  - edge `test_load_config_env_value_loses_to_explicit_override` — file `browser="chromium"`,
    `monkeypatch.setenv("PRETTYPLAY_BROWSER_NAME", "webkit")`; `load_config(path, Config(browser="firefox"))` →
    `"firefox"` (pyproject → env → PrettyConfig observable end-to-end)
  - extend the existing env-override tests to `PRETTYPLAY_GENERATION_PROMPT` and
    `PRETTYPLAY_BROWSER_ENDPOINT` (an env override exists for every setting)
- [ ] **Debugging**: `pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: a raw pydantic `ValidationError` never leaves the loader; the empty
  `cache_root` still resolves to the absolute default; the None path is byte-identical to the previous behavior
- [ ] **Lint**: `ruff check prettyplay tests` — fix formatting if necessary

### Task 3: `RunBudgets` — per-test ownership wording (TDD coding, documentation alignment)

The attempt registry of the cache cell flips its documented ownership semantics from per-run to per-test; the
signature and mechanics are unchanged (contract: "the registry lives for the lifetime of one test, owned by the
test's runtime: every test starts with full limits — a step reused across tests gets a fresh budget in each
test"). Entity `RunBudgets`, location `prettyplay/cache/budgets.py`. No behavioral code changes — the per-test
guarantee is realized structurally by the runtime constructing one registry per test (Task 9) and is asserted by
the runtime tests (`test_reused_step_gets_fresh_budget_per_test`, `test_scenario_builds_own_runtime_per_test`).

**Usages relevant to this task:**
- `conventions`: Google docstrings; the mirrored test layout `tests/cache/test_budgets.py` gets docstring-level
  expectation updates only — behavior unchanged

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests**: run the existing `pytest tests/cache/test_budgets.py` — signatures and behavior stay
  green (this task changes documentation wording only; no new failing tests are expected, so the TDD red phase
  does not apply)
- [ ] **Code**: update `budgets.py` docstrings — module ("Per-run attempt registry ... for the whole run" →
  per-test: one registry per test, owned by the test's runtime), class (per-run → per-test registry), attribute
  and method docstrings ("per-run generation/healing budget" → per-test)
- [ ] **Code**: update the test docstrings in `tests/cache/test_budgets.py` from per-run to per-test expectations
  (docstring-level only)
- [ ] **Logic tests**: none apply — behavior is unchanged by design; the per-test semantics are asserted
  behaviorally in Task 9 (`test_reused_step_gets_fresh_budget_per_test`) and Task 8
  (`test_scenario_builds_own_runtime_per_test`)
- [ ] **Interface verification**: `pytest tests/cache -x` — all pass
- [ ] **Contract re-verification**: `RunBudgets(generation_limit, healing_limit)` signature, `try_generation` /
  `try_healing` behavior and the `StepIdentity` keying are untouched; importable from `prettyplay.cache`
- [ ] **Lint**: `ruff check prettyplay tests` — fix formatting if necessary

### Task 4: LLM port and providers — the `user_instructions` input (TDD coding)

The unified LLM port gains the user instructions parameter and both SDK implementations render the shared block.
Entities: `LlmProvider` (location `prettyplay/llm/provider.py`), mutations `LlmProvider::OpenAiProvider`
(`prettyplay/llm/openai_provider.py`) and `LlmProvider::AnthropicProvider`
(`prettyplay/llm/anthropic_provider.py`), shared helper `build_fields_text`
(`prettyplay/llm/_request.py`). The parameter `user_instructions: str` is inserted as the **second** parameter
of `generate_step_code` in the port and both implementations (the engine calls by keyword — Task 7). The empty
check lives **only** in `build_fields_text` (single point of parity):

```
build_fields_text(user_instructions, step_text, previous_steps, snapshot, page_api, existing_code, error):
  sections = [STEP, PREVIOUS STEPS, PAGE SNAPSHOT, PAGE API]
  IF user_instructions: sections.append("USER INSTRUCTIONS:\n" + user_instructions)   # verbatim, own block
  IF existing_code is not None: sections.append(CODE)
  IF error is not None: sections.append(ERROR)
  return "\n\n".join(sections)
```

Block placement: after the page API block, before the regeneration-only blocks (CODE, ERROR). A whitespace-only
string is non-empty → the block renders verbatim (no trimming); instructions containing markdown fences/headers
render as-is inside the block. `classify_failure` and `build_classification_fields` stay instruction-free by
construction (ADR-3 boundary). Providers pass the value through unchanged; SDK call patterns, error mapping
(`LlmUnavailableError` naming the provider) and response extraction are untouched. Existing test calls of
`generate_step_code` in tests/llm update together with the signature change; the engine stub providers
(tests/engine/test_generator.py) accept the new keyword with a `""` default — recording moves to Task 7.

**Usages relevant to this task:**
- `openai` / `anthropic`: the SDK call patterns and error mapping — unchanged; only the shared request text grows the block
- `classification` (context): the classification prompt carries no instructions input — the negative test pins it
- `conventions`: parity between implementations; test layout `tests/llm/test_request.py`,
  `tests/llm/test_openai_provider.py`, `tests/llm/test_anthropic_provider.py`, `tests/llm/test_provider.py`

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (tests/llm/test_provider.py — expected to fail at this stage): `GENERATE_STEP_CODE_PARAMS`
  of tests/llm/test_provider.py — used by the `LlmProvider.generate_step_code`,
  `OpenAiProvider.generate_step_code` and `AnthropicProvider.generate_step_code` signature tests — lists
  `user_instructions` second (after `prompt`); the `NotImplementedError` base-body calls pass the new
  keyword; `classify_failure` signature unchanged
- [ ] **Code**: `build_fields_text` gains `user_instructions: str` as its first parameter and renders the block
  exactly per the algorithm above
- [ ] **Code**: the port `LlmProvider.generate_step_code` inserts `user_instructions: str` as the second
  parameter; docstring documents empty → no block, non-empty → verbatim USER INSTRUCTIONS block identical in both
  implementations
- [ ] **Code**: both providers insert the parameter at the same position and forward it to
  `build_fields_text`; update their docstrings; request/response code paths unchanged
- [ ] **Code**: update the existing `generate_step_code` calls in tests/llm/* to the new signature; give the
  engine test stub providers (tests/engine/test_generator.py `StubProvider`) a `user_instructions: str = ""`
  keyword so the untouched engine stays green (recording/assertions come with Task 7)
- [ ] **Interface verification**: `pytest tests/llm -x` — all pass
- [ ] **Logic tests**:
  - positive `test_build_fields_text_places_user_instructions_after_page_api`
    (tests/llm/test_request.py) — with all fields set:
    `text.index("PAGE API:") < text.index("USER INSTRUCTIONS:") < text.index("CODE:")` and
    `"USER INSTRUCTIONS:\nprefer data-test-id" in text`
  - edge `test_build_fields_text_omits_block_when_instructions_empty` (tests/llm/test_request.py) — empty
    instructions with regeneration fields: `"USER INSTRUCTIONS" not in text` and
    `text.index("PAGE API:") < text.index("CODE:")` (the default configuration produces byte-identical requests
    to the previous behavior)
  - positive `test_openai_generate_step_code_carries_user_instructions`
    (tests/llm/test_openai_provider.py) — SDK fake with a fenced completion; assert the captured user text
    contains `"USER INSTRUCTIONS:\nprefer data-test-id"`, the system message is `"SYS"`, the fenced block is
    unwrapped
  - positive `test_anthropic_user_instructions_parity` (tests/llm/test_anthropic_provider.py) — the same port
    call; the captured anthropic user text contains the same block at the same relative position
  - negative `test_classify_failure_never_carries_user_instructions` (tests/llm/test_openai_provider.py) —
    `Config(generation_prompt="prefer data-test-id")`; `classify_failure(...)` captured user text has no
    `"USER INSTRUCTIONS"`
- [ ] **Debugging**: `pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: port and both mutations expose identical signatures; one shared helper
  renders the block (parity by construction); no instructions leak into `classify_failure`
- [ ] **Lint**: `ruff check prettyplay tests` — fix formatting if necessary

### Task 5: `PageFacade` — universal locators `find_by_attribute` / `find_by_css` / `find_by_xpath` (TDD coding)

The page facade of the driver cell gains the three universal locating methods, in the manifest order after
`find_by_text`. Entity `PageFacade`, location `prettyplay/driver/page.py`. Verified algorithms (implement
exactly):

```
find_by_attribute(name, value):
1. escaped = value.replace("\\", "\\\\").replace('"', '\\"')     # backslashes doubled first, then quotes
2. locator = _call(lambda: page.locator(f'[{name}="{escaped}"]'))  # CSS attribute selector, double-quoted value
3. return _wrap_locator(locator)

find_by_css(selector):
  locator = _call(lambda: page.locator(selector)); return _wrap_locator(locator)   # verbatim, no escaping

find_by_xpath(xpath):
  locator = _call(lambda: page.locator(f"xpath={xpath}")); return _wrap_locator(locator)  # explicit engine prefix
```

The escaping order matters: backslashes doubled **first**, then double quotes escaped — a value containing `"` or
`\` cannot break out of the quoted selector context. `find_by_css` passes the selector through verbatim (a
"universal" escaping would break `>`/`+` combinators). The `xpath=` prefix is the robustness decision: Playwright
detects XPath implicitly only via `/^\(*\/\//` or a `..` prefix, so `*[@id='main']` or `./div` would silently go
to the CSS engine; the prefix keeps every expression uniform (a parenthesized `(//div)[2]` is in fact sniffed —
the prefix is uniformity, not a workaround for it). Each lookup runs through `self._call` (driver thread when a
worker is bound; inline for hand-built facades in tests) and returns `self._wrap_locator(locator)` — the handle
inherits the driver-thread boundary and Playwright's auto-wait. No errors raised eagerly. While touching
`page.py`, update the `close` docstring wording: the test's browser keeps running until the runtime closes it
(was "the browser of the run stays alive").

**Usages relevant to this task:**
- `playwright`: `page.locator(...)` — the CSS engine handles attribute selectors natively; locator auto-wait;
  the `xpath=` engine prefix
- `conventions`: Google docstrings with `Args`/`Returns`; test layout `tests/driver/test_page.py`

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (tests/driver/test_page.py — expected to fail at this stage): `PageFacade` exposes
  `find_by_attribute(name, value)`, `find_by_css(selector)`, `find_by_xpath(xpath)` after `find_by_text` in the
  declared order; each returns a `LocatorFacade`
- [ ] **Code**: implement the three methods per the algorithms above, with Google docstrings
  (`find_by_attribute`: intended use data-* attributes, e.g. `data-test-id`)
- [ ] **Code**: update the `PageFacade.close` docstring per-test wording while touching the file
- [ ] **Interface verification**: `pytest tests/driver/test_page.py -x` — all pass
- [ ] **Logic tests** (tests/driver/test_page.py — hand-built `PageFacade(fake_page, fake_context)` with a
  recording fake page, worker `None` → inline calls):
  - positive `test_find_by_attribute_builds_css_attribute_selector` —
    `facade.find_by_attribute("data-test-id", "submit-button")` → the fake recorded
    `'[data-test-id="submit-button"]'`; the result is a `LocatorFacade`
  - positive `test_find_by_css_passes_selector_verbatim` — `facade.find_by_css("form > button.primary")` →
    recorded selector exactly `"form > button.primary"` (no escaping)
  - positive `test_find_by_xpath_applies_xpath_engine_prefix` — `facade.find_by_xpath("*[@id='main']")` →
    recorded selector exactly `"xpath=*[@id='main']"`
  - edge `test_find_by_attribute_escapes_quotes_and_backslashes` —
    `facade.find_by_attribute("data-test-id", 'a"b\\c')` → the single recorded selector is
    `[data-test-id="a\"b\\c"]` (escaped form), no exception
- [ ] **Debugging**: `pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: no raw Playwright object crosses the facade; the existing method set is
  untouched (backward-compatibility contract — extend, never rename or remove)
- [ ] **Lint**: `ruff check prettyplay tests` — fix formatting if necessary

### Task 6: `DriverSession` — remote ws connect branch with the endpoint-naming error (TDD coding)

The session of the driver cell branches its engine start on `browser_endpoint`. Entity `DriverSession`, location
`prettyplay/driver/session.py`. The branch lives inside `_launch_engine`; the existing `_launch` failure-cleanup
wrapper (stop Playwright, close the worker, re-raise) covers both branches — do not duplicate cleanup per branch.
Verified algorithm (implement exactly):

```
_launch_engine(playwright):
1. name = config.browser; engines = {chromium, firefox, webkit}
2. IF config.browser_endpoint:
     engine = playwright.chromium if name in {"chrome", "msedge"} else engines[name]
     TRY return engine.connect(config.browser_endpoint)  # no headless, no channel
     EXCEPT Error as failure:
       raise Error(f"cannot connect to the browser endpoint "
                   f"{config.browser_endpoint}: {failure}") from failure
3. IF name in {"chrome", "msedge"}:
     return playwright.chromium.launch(headless=config.headless, channel=name)
4. return engines[name].launch(headless=config.headless)
```

Why the wrapper: Playwright's raw connect error carries only the OS-level cause (`websocket connect timeout`,
`connect ECONNREFUSED`, `getaddrinfo ENOTFOUND`) — the endpoint URL never reaches the exception — so the connect
branch re-raises wrapped as a Playwright `Error` naming `config.browser_endpoint`, chained (`from failure`) to
the original; the contract "a failed connect fails loudly with an actionable message naming the endpoint" is
satisfied by the wrapper. The launch path keeps Playwright's own actionable text (it names the missing
distribution itself). chrome/msedge map to the chromium engine on the connect path — channels do not apply to a
connect; `headless` is not passed (window visibility belongs to the endpoint server). `close()` on a connected
browser disconnects; the remote browser process is the server's concern. While touching `session.py`, update the
per-test wording: module docstring ("browser process of the run" → of one test), class docstring
("one browser process for the whole run" → per test), `open_context`/`_launch_engine` docstrings.

**Usages relevant to this task:**
- `playwright`: remote ws connect — `engine.connect(ws_endpoint)`; channels do not apply, the browser setting
  selects the engine (chromium for chrome/msedge); the existing launch/headless/channel rules on the local branch
- `conventions`: test layout `tests/driver/test_session.py`; fake-boundary testing (no real ws server — mocked
  endpoint)

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (tests/driver/test_session.py): the existing DriverSession surface tests stay green after
  the branch change (constructor `DriverSession(config)`, `open_context`, `close` shapes unchanged — the new
  behavior is a branch, not a signature change)
- [ ] **Code**: implement the connect branch in `_launch_engine` per the algorithm above (reuse the `_launch`
  cleanup wrapper as is)
- [ ] **Code**: extend the test fakes — `FakeEngine` gains a `connect(endpoint, **kwargs)` recorder
  (`connect_calls`, `connect_kwargs`) alongside `launch`; `FakePlaywrightFactory` records engine starts for the
  retry assertion
- [ ] **Code**: update the module/class/method docstrings to the per-test wording
- [ ] **Interface verification**: `pytest tests/driver -x` — all pass
- [ ] **Logic tests** (tests/driver/test_session.py, monkeypatched `prettyplay.driver.session.sync_playwright`):
  - positive `test_session_connects_over_ws_endpoint_when_set` —
    `Config(browser="firefox", browser_endpoint="ws://ci-grid:3000/playwright/firefox")` →
    `fake.firefox.connect_calls == ["ws://ci-grid:3000/playwright/firefox"]`, `fake.launches == []`,
    `"headless"` not in the connect kwargs
  - positive `test_session_connect_maps_channels_to_chromium` —
    `Config(browser="chrome", browser_endpoint="ws://ci-grid:3000/playwright/chromium")` →
    `fake.chromium.connect_calls == [endpoint]`, no `channel=` kwarg anywhere
  - negative `test_session_failed_connect_cleans_up_for_retry` — fake `firefox.connect` raises
    `Error("websocket connect timeout")` (OS-level cause without the URL, as the real driver does);
    `Config(browser="firefox", browser_endpoint="ws://dead:1")` → `pytest.raises(Error)` with `"ws://dead:1"` in
    the message; `excinfo.value.__cause__` is the original `Error`; the worker thread is joined; a second
    `open_context()` attempts a fresh start (the fake counts a second engine start)
- [ ] **Debugging**: `pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: the branch condition reads the `browser_endpoint` setting of `Config` exactly;
  cleanup symmetry between launch and connect failures (one `_launch` wrapper); a channel launch without the
  installed browser still fails with Playwright's own actionable message
- [ ] **Lint**: `ruff check prettyplay tests` — fix formatting if necessary

### Task 7: `StepGenerator` — instructions routing, `SYSTEM_PROMPT` rename, surface rows (TDD coding)

The generation engine of the engine cell carries the project user instructions on every provider request of both
pools. Entity `StepGenerator`, location `prettyplay/engine/generator.py`; per-test docstring wording also touches
`prettyplay/engine/healer.py`. Four coordinated changes in this one location:

1. **Constant rename** `GENERATION_PROMPT` → `SYSTEM_PROMPT`; the text takes the engine `system_prompt` practice
   **verbatim** — two added lines relative to the current text: the input bullet
   `- USER INSTRUCTIONS: the project's code style guidance, when configured` (after the PAGE API input bullet),
   and the locating-priority bullet
   `- Attribute, CSS and XPath locating exist for elements without accessible names — the accessibility-first priority stands unless USER INSTRUCTIONS say otherwise`
   (after the role/text/label priority line). Full target text:

```
You generate executable Python code for one step of a web UI test.

Input you receive:
- STEP: the step sentence in a natural language
- PREVIOUS STEPS: the sentences of the previous steps of the test, in order
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- SCREENSHOT: an image of the page, when attached
- PAGE API: the exact surface listing of the page facade — call nothing outside it
- USER INSTRUCTIONS: the project's code style guidance, when configured
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
- Attribute, CSS and XPath locating exist for elements without accessible names — the accessibility-first priority stands unless USER INSTRUCTIONS say otherwise
- Scroll abilities exist for scenario scrolling: bring an element into view, scroll by an amount, to the page end or start, inside a scrollable container
- No fixed delays, no sleeps, no explicit waits — the facade waits itself
- The step must complete exactly what STEP says — nothing more, nothing less
- Output only the code block, no explanations
```

2. **Surface rows**: `PAGE_API_SURFACE` gains exactly three rows after `page.find_by_text(text)`, mirroring
   `prettyplay/driver/.usages/facade.md`: `page.find_by_attribute(name, value) — element by attribute value —
   data-* attributes`, `page.find_by_css(selector) — element by CSS selector`,
   `page.find_by_xpath(xpath) — element by XPath expression` (keep the column-padding style of the constant; keep
   the comment tying the constant to `facade.md`).
3. **Instructions routing**: the single `generate_step_code` call site in `_loop` passes
   `user_instructions=self._config.generation_prompt` — **unconditionally**, on generation and regeneration alike
   (the empty value means "no block" inside the provider helper; the single empty-check renders parity — Task 4).
   The instructions value takes no part in the step address: `StepIdentity` inputs stay untouched; cached steps
   execute as stored even when `generation_prompt` changes between runs.
4. **Wording**: per-run → per-test in the docstrings of `generator.py` (class/constructor "the per-run attempt
   registry" → per-test) and `healer.py`; while touching `healer.py` keep its unused `cache`/`budgets` constructor
   parameters with their existing `# noqa: ARG002` comments — the signature is fixed by the engine contract
   (contract symmetry), do not remove them.

Existing engine tests update here: rename the `GENERATION_PROMPT` import references to `SYSTEM_PROMPT`; the stub
providers now **record** `user_instructions` (Task 4 gave them the parameter with a default).

**Usages relevant to this task:**
- `system_prompt`: the constant's text, applied verbatim as the system message via the provider `prompt` parameter
- `facade` from Imports: the single source of the page API surface — the listing and the practice change together;
  the three rows mirror the Surface table of `prettyplay/driver/.usages/facade.md`
- `generation` / `healing` (engine local usages, context): the cycles the executor delegates to — per-test budget
  wording matches them
- `conventions`: test layout `tests/engine/test_generator.py`; the `E501` per-file ignore for the prompt constants
  stays valid

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (tests/engine/test_generator.py — expected to fail at this stage):
  `generator_module.SYSTEM_PROMPT` exists (`GENERATION_PROMPT` gone); `StepGenerator` constructor/generate/
  regenerate signatures unchanged
- [ ] **Code**: rename the constant and update its text verbatim per the target text above
- [ ] **Code**: extend `PAGE_API_SURFACE` with the three rows after `page.find_by_text(text)` in the constant's
  padding style, comment tying it to `facade.md` preserved
- [ ] **Code**: pass `user_instructions=self._config.generation_prompt` at the `generate_step_code` call site in
  `_loop` (one call site covering both pools)
- [ ] **Code**: update the engine stub providers to record `user_instructions`; update the per-run → per-test
  docstrings in `generator.py` and `healer.py`
- [ ] **Interface verification**: `pytest tests/engine -x` — all pass
- [ ] **Logic tests** (tests/engine/test_generator.py — fake provider recording `generate_step_code` kwargs,
  fake page, stub cache, budgets):
  - positive `test_generator_passes_generation_prompt_to_provider` —
    `Config(generation_prompt="prefer data-test-id")`; `generator.generate(identity, "click Sign in", [],
    fake_page)` with the fake returning working code → captured `user_instructions ==
    "prefer data-test-id"`, captured `prompt == SYSTEM_PROMPT`,
    `"page.find_by_attribute" in captured["page_api"]`
  - positive `test_regenerate_carries_user_instructions_with_code_and_error` — same config,
    `RunBudgets(1, 1)`; `generator.regenerate(identity, "click Sign in", [], fake_page,
    existing_code="def step(page)...", error="TimeoutError")` → captured `user_instructions`,
    `existing_code`, `error`, `prompt == SYSTEM_PROMPT` (instructions travel together with the
    regeneration-only fields through the one shared call site)
  - positive `test_page_api_surface_mirrors_facade_practice` — static constant check:
    `"page.find_by_attribute(name, value)" in PAGE_API_SURFACE`,
    `"page.find_by_css(selector)" in PAGE_API_SURFACE`,
    `"page.find_by_xpath(xpath)" in PAGE_API_SURFACE` (the listing and `facade.md` must change together)
- [ ] **Debugging**: `pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: instructions reach generation and regeneration only — never classification,
  never the step address; every generation request carries the exact page API surface from `facade`; the budget
  semantics of `_loop` unchanged
- [ ] **Lint**: `ruff check prettyplay tests` — fix formatting if necessary

### Task 8: `PrettyTest` — per-test composition with the `config` parameter (TDD coding)

The integrator object of the root cell owns its runtime and effective config. Entity `PrettyTest`, location
`prettyplay/scenario.py`; wording-only change in `prettyplay/executor.py`. Verified composition algorithm
(implement exactly):

```
__init__(cache_key, cache_path=None, config=None):
1. effective = load_config(None, config)         # None resolves everything from pyproject+env, as before
2. self._runtime = PrettyplayRuntime(effective)  # no process-wide singleton usage from here on
3. reporter = StepReporter(hooks=[])
4. cache = StepCache(self._runtime.config, cache_path, reporter)
5. generator = StepGenerator(...runtime.config, runtime.provider, cache, runtime.budgets, reporter)
   healer   = StepHealer(...same collaborators...)
6. executor = StepExecutor(cache_key, cache, generator, healer, runtime.budgets, reporter)
7. _page = None — opens lazily on the first step

close():
1. IF _page: _page.close(); _page = None          # closes the isolated context
2. self._runtime.close()                          # browser close, Playwright stop, driver thread join — unconditionally
__exit__: close(); never suppress
```

`close` semantics change from "page only, runtime stays" to "the whole runtime of the test" — idempotent (page
block guarded; `runtime.close` is a no-op when nothing started; repeated `close()` safe; the atexit double-close
of Task 9 is protected by this idempotency). A `load_config` failure (invalid merged settings) surfaces as
`ConfigurationError` at construction time, before any browser/LLM involvement. `get_runtime` and the singleton
still exist at this stage — this task only stops using them (the scenario import of `get_runtime` is removed);
Task 9 deletes them. Two `PrettyTest` in one process hold two runtimes, two registries, two browser sessions.
Existing test updates: drop the `isolated_runtime_global` fixture and the `make_runtime` singleton installer from
tests/test_scenario.py (rebase every logic test that builds `PrettyTest` through them); construction tests mock
`prettyplay.scenario.load_config` and assert the `load_config(None, config)` call and the private runtime; the
same rebase hits tests/test_integration.py — its own `isolated_runtime_global` autouse fixture and the
`installed_runtime` singleton installer stop working the moment `PrettyTest` stops reading the singleton (the
Flow A/B/C integration tests would resolve the real repo pyproject instead of the tmp cache root).

**Usages relevant to this task:**
- `taxonomy` from Imports: `ConfigurationError` in the failures table at construction; step failures propagate by
  kind (`_raise_folded` unchanged)
- `hooks` from Imports: the per-test reporter and `add_hooks` wiring — unchanged shapes
- `generation` / `healing` from Imports: the engine cycles the executor delegates to — sourced from
  `self._runtime` now
- `conventions`: test layout `tests/test_scenario.py`

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (tests/test_scenario.py — expected to fail at this stage):
  `inspect.signature(PrettyTest.__init__)` parameters are `["cache_key", "cache_path", "config"]` with
  `cache_path`/`config` defaulting to `None`; `close` remains on the surface; the context manager protocol
  unchanged
- [ ] **Code**: implement the composition algorithm above — `config: PrettyConfig | None = None` parameter,
  `load_config(None, config)`, private `PrettyplayRuntime`, collaborators sourced from `self._runtime`, remove the
  `get_runtime` import
- [ ] **Code**: implement the new `close` (page + unconditional `runtime.close()`) and align `__exit__`
- [ ] **Code**: docstrings — per-test composition, the `config` argument (explicitly set values win, unset/empty
  fields resolve from pyproject+env), the close semantics; update `executor.py` wording ("the run-scoped attempt
  registry" → per-test) while in the cell, keeping its unused `budgets` constructor parameter with the existing
  `# noqa: ARG002` comment — the signature is fixed by the root cell contract (contract symmetry), do not remove it
- [ ] **Code**: update tests/test_scenario.py — remove the `isolated_runtime_global` fixture and the singleton
  `make_runtime`; rebase every test that built `PrettyTest` through them on the new pattern:
  `mock.patch("prettyplay.scenario.load_config", return_value=Config(cache_root=str(tmp_path)))` (or pass
  `config=Config(cache_root=str(tmp_path))` with the same patch), then patch `open_page`/`close` on the
  constructed test's own `self._runtime` (e.g. `mock.patch.object(test._runtime, "open_page", ...)`)
- [ ] **Code**: update tests/test_integration.py — delete the `isolated_runtime_global` autouse fixture;
  replace the `installed_runtime` singleton installer with per-test construction: build the test as
  `PrettyTest(cache_key, config=Config(cache_root=str(cache_root)))` under
  `mock.patch("prettyplay.scenario.load_config", return_value=Config(cache_root=str(cache_root)))`, inject the
  stub provider via `mock.patch("prettyplay.runtime.create_provider", return_value=provider)` and the fake page
  via `mock.patch.object(test._runtime, "open_page", return_value=page)`; rebase the Flow A/B/C tests
  (cache-hit, context-feeding, rot-healing) on this pattern — without the rebase they resolve the real repo
  pyproject (no `[tool.prettyplay]` → cache root `/workspace/.prettyplay/cache`, not `tmp_path`) and never see
  the patched boundaries
- [ ] **Interface verification**: `pytest tests/test_scenario.py -x` — all pass
- [ ] **Logic tests** (tests/test_scenario.py):
  - positive `test_scenario_builds_own_runtime_per_test` —
    `mock.patch("prettyplay.scenario.load_config", return_value=Config(model="gpt-5"))`; `t1 = PrettyTest("k1")`,
    `t2 = PrettyTest("k2")` → `t1._runtime is not t2._runtime`, `t1._runtime.budgets is not t2._runtime.budgets`,
    `load_config_mock.call_args_list == [call(None, None), call(None, None)]` (the ADR-1 core acceptance)
  - positive `test_scenario_close_stops_page_and_runtime` — `mock.patch` on `runtime.open_page` returning a fake
    page whose `close` counts; run one step (page opens), `test.close()`, then `test.close()` again → fake page
    `close_count == 1`, the driver close recorded once, no exception on the second call
  - edge `test_scenario_close_before_first_step_is_safe` — `PrettyTest("k")` with mocked `load_config`, nothing
    started; `test.close()` → no exception; a subsequent step still opens a page lazily
- [ ] **Debugging**: `pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: construction is cheap (no browser launch, no LLM credentials); no cross-test
  state on the instance; `ConfigurationError` surfaces at construction; `cache_key` property delegates as today
- [ ] **Lint**: `ruff check prettyplay tests` — fix formatting if necessary

### Task 9: `PrettyplayRuntime` per-test root and the `->PrettyConfig` facade embedding (TDD coding)

The composition root becomes strictly per-test and the root facade re-exports the settings model under its
public name while the singleton leaves the code. Entities: `PrettyplayRuntime` (location
`prettyplay/runtime.py`), the root facade (`prettyplay/__init__.py`) with the `->PrettyConfig: {}` embedding, and
the deleted routine `get_runtime`. Verified algorithm (implement exactly):

```
__init__(config):
1. keep config; budgets = RunBudgets(config.generation_attempts, config.healing_attempts)
2. driver = None; provider = None                       # lazy, as today
3. atexit.register(self.close)                          # one hook per instance

close(): driver.close() if started — idempotent          # browser → playwright.stop → thread join
get_runtime and the module singleton _runtime: DELETED
```

Facade: `prettyplay/__init__.py` imports `PrettyConfig` from `.config` and lists it in `__all__` together with
`PrettyTest`, `PrettyplayRuntime`, `StepExecutor`; `get_runtime` is removed from the module and `__all__` —
the embedding trace: `from prettyplay import PrettyTest, PrettyConfig` works; `Config` stays importable from
`prettyplay.config` for the other cells; `not hasattr(prettyplay, "get_runtime")`. Edge cases: a runtime
constructed but never stepped — close is a no-op, its atexit hook a no-op; N runtimes in one process — N atexit
hooks, each idempotent, LIFO order at exit (accepted ADR-1 risk); manual close + atexit double-close safe by
idempotency. Existing test updates: tests/test_runtime.py — delete the `TestGetRuntime` class and the
`isolated_runtime_global` fixture, drop the `get_runtime` import assertions, keep the constructor/surface
contract tests; tests/test_integration.py — the public-surface test.

**Usages relevant to this task:**
- `taxonomy` from Imports: unchanged failure kinds crossing the root
- `generation` / `healing` from Imports: the runtime composes the engines' collaborators (budgets per test)
- `conventions`: test layouts `tests/test_runtime.py`, `tests/test_integration.py`

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (tests/test_runtime.py + tests/test_integration.py — expected to fail at this stage):
  `PrettyplayRuntime.__init__` parameters `["config"]`; properties `config`/`budgets`/`driver`/`provider`,
  methods `open_page`/`close` on the surface; `prettyplay.__all__ == ["PrettyTest", "PrettyConfig",
  "PrettyplayRuntime", "StepExecutor"]`, `prettyplay.PrettyConfig is prettyplay.config.Config`,
  `not hasattr(prettyplay, "get_runtime")`
- [ ] **Code**: delete `get_runtime` and the module global `_runtime`; register `atexit.register(self.close)`
  inside `__init__`; keep the lazy driver/provider properties and the idempotent close as they are
- [ ] **Code**: docstrings — "Run-scoped composition root ... per process" → the per-test composition root; the
  atexit requirement documented on `close`
- [ ] **Code**: root facade `prettyplay/__init__.py` — `from .config import PrettyConfig` re-export, drop the
  `get_runtime` import/export, `__all__ = ["PrettyTest", "PrettyConfig", "PrettyplayRuntime", "StepExecutor"]`
- [ ] **Code**: tests/test_runtime.py — delete `TestGetRuntime` and the `isolated_runtime_global` fixture, drop
  the `get_runtime` import assertions, keep the constructor/surface contract tests
- [ ] **Interface verification**: `pytest tests/test_runtime.py tests/test_integration.py -x` — all pass
- [ ] **Logic tests**:
  - positive `test_runtime_registers_own_atexit_close` (tests/test_runtime.py) —
    `mock.patch("prettyplay.runtime.atexit.register")`; `r1 = PrettyplayRuntime(cfg)`,
    `r2 = PrettyplayRuntime(cfg)` → `register.call_count == 2`; `r1.close` and `r2.close` each appear in the
    registered callables (per-instance atexit replaces the deleted singleton hook)
  - positive `test_reused_step_gets_fresh_budget_per_test` (tests/test_runtime.py) — two independent
    `RunBudgets(1, 1)` registries as two runtimes build them; one `StepIdentity`;
    `a.try_generation(identity) → True`, `a.try_generation(identity) → False`, `b.try_generation(identity)` →
    `True` (a step reused across tests gets N × attempts — the flipped invariant)
  - positive `test_pretty_config_exported_and_get_runtime_removed` (tests/test_integration.py) —
    `prettyplay.PrettyConfig is Config`, `"PrettyConfig" in prettyplay.__all__`,
    `not hasattr(prettyplay, "get_runtime")` (the embedding contract and the deliberate breaking change)
- [ ] **Debugging**: `pytest tests/ -x` — fix implementation code until all tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: every instance registers its own atexit close; construction never requires
  LLM credentials; `Config` remains importable from `prettyplay.config` for the other cells; no reference to
  `get_runtime` remains anywhere in the tree
- [ ] **Lint**: `ruff check prettyplay tests` — fix formatting if necessary

### Task 10: Integration tests — the cache address is instruction-independent (integration tests)

Cross-entity acceptance of ADR-3 spanning config → engine → executor → cache → scenario: a cached step executes
with zero provider involvement even when the instructions setting differs from whatever generated the cached
code. The instructions never enter `StepIdentity`, so a cached step never regenerates because the instructions
changed. Uses the existing `seed_cache` helper of tests/test_scenario.py to preload the cache file for the step
identity in a tmp cache root.

**Usages relevant to this task:**
- `taxonomy` from Imports: the step passes — no failure kinds cross the boundary
- `conventions`: unit tests build fakes at the external boundaries only; no network

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] Create/extend the integration scenario in `tests/test_scenario.py`: `PrettyTest` built over a tmp cache
  root via `Config(cache_root=..., generation_prompt="new instructions")` passed as the `config` parameter (mock
  `load_config` or a written pyproject per the existing test style), the cache preloaded for the step identity
  (`seed_cache`), and a fake provider recording `generate_step_code` calls injected through the runtime
- [ ] Test the cross-entity interaction `test_cached_step_runs_without_provider_when_instructions_differ`:
  `test.action("the cached sentence")` → the executor loads the cache hit and runs `run_step_code(cached.code)`
  with **no** generation request — `provider.generate_step_code.call_count == 0` and the step passed (the
  cache-non-invalidation acceptance)
- [ ] Test edge case: two tests with equal `cache_key` in the shared root reuse the cached step across tests while
  their budget registries stay independent (composes Task 8's per-test runtime with the shared-root addressing of
  `StepCache`)
- [ ] Run validation: `pytest tests/test_scenario.py -x`, then the full gate `pytest tests/ -x`

---

## Validation Commands

- `pytest tests/ -x`: Run all tests (the gate; Python 3.10+, no venv/network needed — fakes only)
- `ruff check prettyplay tests`: Lint check (line-length 120; fix formatting and decompose if necessary)
- `python -c "from prettyplay import PrettyTest, PrettyConfig, PrettyplayRuntime, StepExecutor; import prettyplay; from prettyplay.config import Config; assert prettyplay.PrettyConfig is Config; assert not hasattr(prettyplay, 'get_runtime')"`: Facade accessibility — the embedding re-export and the deliberate `get_runtime` removal
- Per-cell gates used inside tasks: `pytest tests/config -x`, `pytest tests/cache -x`, `pytest tests/llm -x`, `pytest tests/driver -x`, `pytest tests/engine -x`, `pytest tests/test_scenario.py -x`, `pytest tests/test_runtime.py tests/test_integration.py -x`

---

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location`
- [ ] Every contract entity is accessible from the facade
- [ ] Properties and methods match the declared API
- [ ] Descriptions are reflected in behavior
- [ ] Contract dependencies are met
- [ ] Re-exports are accessible from the facade (`PrettyConfig` from `prettyplay`)
- [ ] Every coding task followed the TDD workflow (contract tests → code → verification → logic tests → debugging → re-verification → lint)
- [ ] Contract tests and logic tests cover facade, API, and behavior within each coding task
- [ ] Integration tests exist where cross-entity scenarios require them (Task 10)
- [ ] No package boundary was expanded
- [ ] `CODEMANIFEST` files were not modified (contract is read-only)
- [ ] All validation commands pass
- [ ] Every Usages entry is mentioned in at least one task
