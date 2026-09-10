# Design Document: `additional-configuration`

The complete architectural specification for materializing the `additional-configuration` contract
changes (per-test runtime, PrettyConfig layered merging, generation user instructions, universal
locators, remote browser endpoint) into the Python implementation of `prettyplay`.

The source of truth is the set of six changed CODEMANIFEST files (applied to the tree by the
apply-architecture stage, lint-clean: `goga lint` → cells: 8, errors: 0). This document specifies
**what** to implement and **how**; the execution order is decided by the planning stage, not here.
No implementation code is written at this stage.

---

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/config/CODEMANIFEST`: `Config` gains `generation_prompt` and `browser_endpoint`
  fields (signature + properties + ws/wss validation requirement); `load_config` gains the
  `overrides` parameter and the overlay algorithm (steps 6–8); global annotation gains the layered
  resolution principle and the PrettyConfig public name.
- `prettyplay/cache/CODEMANIFEST`: `RunBudgets` semantics flipped from per-run to per-test
  (registry owned by the test's runtime); signature unchanged.
- `prettyplay/llm/CODEMANIFEST`: `LlmProvider.generate_step_code` gains `user_instructions` as the
  second parameter; both provider mutations document the USER INSTRUCTIONS block placement in the
  request-building step; parity annotation line added.
- `prettyplay/driver/CODEMANIFEST`: `DriverSession` is per-test; `open_context` launch/connect
  branch on `browser_endpoint`; `PageFacade` gains `find_by_attribute`, `find_by_css`,
  `find_by_xpath`; remote connect rules in global annotations.
- `prettyplay/engine/CODEMANIFEST`: practice `generation_prompt` renamed to `system_prompt` (with
  the USER INSTRUCTIONS input line and the universal-locating priority line); `StepGenerator`
  passes user instructions in `generate` and `regenerate`; per-test budget wording.
- `prettyplay/CODEMANIFEST`: `Config AS PrettyConfig` import + `->PrettyConfig: {}` embedding;
  `PrettyTest` gains the `config` parameter and builds its own `PrettyplayRuntime`;
  `PrettyplayRuntime` is the per-test composition root with per-instance atexit; `get_runtime`
  deleted.

### New Entities

- None at the type level. New API surface elements:
  - `PageFacade.find_by_attribute(name, value)` — `prettyplay/driver/page.py`
  - `PageFacade.find_by_css(selector)` — `prettyplay/driver/page.py`
  - `PageFacade.find_by_xpath(xpath)` — `prettyplay/driver/page.py`
  - `->PrettyConfig: {}` embedding — the root facade re-exports the settings model under its
    public name (`prettyplay/__init__.py`).

### Changed Entities

- `Config` — two new string fields with empty defaults; `browser_endpoint` validated as ws/wss
  URL when non-empty; per-test attempt wording; headless scoped to the local launch.
- `load_config` — `overrides: Config | None = None` parameter (both parameters default to
  `None`; single-argument calls keep working); layered overlay via
  `model_fields_set` + `model_copy` after the file+env layer resolves.
- `LlmProvider.generate_step_code` (+ both provider implementations) — `user_instructions`
  parameter; USER INSTRUCTIONS block in the user content, after PAGE API, before CODE/ERROR.
- `DriverSession` — per-test lifecycle; connect-over-ws branch when `browser_endpoint` is set.
- `StepGenerator` — passes `config.generation_prompt` as user instructions on every provider
  request of both pools; system prompt constant renamed; PAGE API surface listing extended.
- `RunBudgets` — ownership semantics only (constructed per test by the runtime); behavior
  unchanged.
- `PrettyTest` — `config` parameter; owns a private `PrettyplayRuntime`; `close` stops the whole
  runtime of the test.
- `PrettyplayRuntime` — per-test root; each instance registers its own close with atexit.

### Deleted Entities

- `get_runtime()` (root cell, `runtime.py`) — the process-wide singleton is gone from the public
  contract and from the code; the module global `_runtime` is deleted with it.

### Usages and Annotations Changes

- engine `Usages`: key `generation_prompt` → `system_prompt`; content gains the
  `USER INSTRUCTIONS` input line and the attribute/CSS/XPath locating priority line.
- engine global annotations: `system_prompt` reference replaces `generation_prompt`; new routing
  rule — instructions reach generation/regeneration only, never classification, never the step
  address.
- driver global annotations: remote connect rules (headless ignored, channels do not apply,
  browser selects the engine); "one browser process per test".
- config global annotations: layered resolution principle; "`Config` is publicly known as
  PrettyConfig".
- llm global annotations: user-instructions parity line.
- Project-level cooks `playwright.md` (remote connect section, per-test lifecycle) and
  `pydantic.md` (new fields, layered merge section) — already updated at the formulation stage.

## Applied Fixes

### Fixed CODEMANIFEST Defects

- None. The four-dimension consistency audit (interface↔type, type↔mutation,
  interface↔interface, annotations↔entity) found no defects; `goga lint` reports 0 errors.

### Fixed Practice Defects

- `.goga/usages/cooks/pydantic.md` (layered merge snippet): the illustrative filter `if value`
  applied truthiness to every field, so an explicit `headless=False` (or `send_screenshots=False`)
  passed in `PrettyConfig(...)` would be silently dropped — contradicting the `load_config`
  contract ("a field participates when it was passed at construction and is non-empty for
  strings") and ADR-2 ("explicitly set values win"). Fixed to `model_fields_set`-based
  participation with the non-empty refinement for strings only. Practices do not create
  contractual obligations; the CODEMANIFEST is authoritative — the fix aligns the practice with
  the contract so the implementing agent cannot copy the wrong pattern.
- `.goga/usages/cooks/playwright.md` (remote connect snippet, fixed at the design-review stage):
  `engines[name].connect(ws_endpoint)` raised `KeyError` for the channel values chrome/msedge —
  contradicting the section's own rule ("channels do not apply to a connect; the browser setting
  selects the engine"). Fixed to the same mapping the driver design uses:
  `engines["chromium" if name in ("chrome", "msedge") else name]`.

## Entity Interaction and Data Flow

### Interaction Diagram

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

### Data Flows

- **Configuration flow**: `PrettyConfig(...)` (integrator, explicit fields only) →
  `load_config(None, overrides)` → file layer (pyproject → env) → overlay → effective `Config` →
  `PrettyplayRuntime` → `StepCache` (cache_root), `DriverSession` (browser, headless,
  browser_endpoint), `create_provider` (provider, models, base_url), `RunBudgets`
  (generation_attempts, healing_attempts), `StepGenerator` (send_screenshots,
  generation_prompt). One resolved object feeds every consumer — no consumer re-reads pyproject
  or env.
- **Instructions flow**: `config.generation_prompt` → `StepGenerator._loop` →
  `provider.generate_step_code(user_instructions=...)` → `build_fields_text` → USER INSTRUCTIONS
  block of the user content → SDK request (openai `messages` / anthropic `messages`). The value
  never enters `classify_failure`, `StepIdentity`, `CachedStep` or the cache file.
- **Budget flow**: `PrettyplayRuntime.__init__` constructs one `RunBudgets` per test from the
  effective config limits; `StepGenerator._loop` spends through `try_generation`/`try_healing`
  keyed by `StepIdentity.filename`; a step reused by N tests in one process encounters N fresh
  registries.
- **Browser flow**: first step → `PrettyTest._ensure_page` → `runtime.open_page()` →
  `DriverSession.open_context()` → launch or connect (first call only) → new isolated context +
  page → `PageFacade` bound to the driver thread. Test close → `PageFacade.close` (context) →
  `PrettyplayRuntime.close` → browser close, Playwright stop, driver thread join.

### Entity Dependencies

Implementation order (bottom-up, matches the architecture plan): `config` → `cache` → `llm` →
`driver` → `engine` → root (`runtime.py`, `executor.py`, `scenario.py`, `__init__.py`).
Dependents of the changed cells (`goga schema --depends-on`): config ← {root, cache, driver,
engine, llm}; cache ← {root, engine}; llm ← {root, engine}; driver ← {root, engine}; engine ←
{root}. `failures` and `reporting` are untouched.

## Code Stack Trace

### Trace: `Config(...)` construction with the new fields

#### Chain
1. **Input**: integrator constructs `PrettyConfig(browser="firefox", browser_endpoint="ws://ci-grid:3000/playwright/firefox", generation_prompt="prefer data-test-id")` — or the loader constructs `Config(**merged)` from file+env.
2. **Step**: pydantic kw_only model assigns fields; `generation_prompt`/`browser_endpoint` default to `""` when absent → checkpoint: empty defaults satisfy "unset means file layer" convention; `model_fields_set` records exactly the passed names ✓
3. **Step**: field validator on `browser_endpoint` runs only for non-empty values: parse with `urllib.parse.urlparse`, require scheme in {ws, wss} and a non-empty netloc → checkpoint: `"ws://ci-grid:3000/playwright/firefox"` passes; `"http://ci-grid:3000"` fails validation ✓
4. **Step**: a validation failure raises `pydantic.ValidationError` with loc `("browser_endpoint",)` — the integrator constructing `PrettyConfig` directly sees the raw pydantic error at their own call site; the loader path wraps it (see next trace) → checkpoint: "one model — one place of validation" holds — both construction paths flow through the same validators ✓
5. **Output**: a validated `Config` instance; `effective_generation_model`/`effective_classification_model` properties unchanged.

#### Checkpoint Summary
- Fields participate in merging via `model_fields_set`, not truthiness: passed.
- ws/wss validation matches the manifest requirement text: passed.
- No secret fields added (endpoint is an address, instructions are text): passed.

### Trace: `load_config(pyproject_path, overrides)`

#### Chain
1. **Input**: `pyproject_path: str | None`, `overrides: Config | None`.
2. **Step**: resolve the pyproject.toml path (explicit or first upward from cwd) → `Path` ✓
3. **Step**: parse TOML (`tomllib`, `tomli` fallback on 3.10 — see `pydantic`) ✓
4. **Step**: extract `tool.prettyplay`; missing section → empty dict ✓
5. **Step**: reject the legacy `PRETTYPLAY_BROWSER` env name (existing behavior, kept); collect env overrides — the `_ENV_NAMES` table now covers all 13 settings including `PRETTYPLAY_GENERATION_PROMPT` and `PRETTYPLAY_BROWSER_ENDPOINT` → checkpoint: manifest requirement "an env override exists for every setting" ✓
6. **Step**: resolve the empty `cache_root` to the absolute default `<pyproject_dir>/.prettyplay/cache` ✓
7. **Step**: construct `Config(**merged)`; on `ValidationError` render one line per invalid setting (name, received value, allowed text — `_ALLOWED_TEXT` gains entries for the two new fields) and raise `ConfigurationError` with the original chained → checkpoint: no raw pydantic error escapes ✓
8. **Step**: `overrides is None` → return the file-layer config as is (previous behavior, exactly) ✓
9. **Step**: overlay — `explicit = overrides.model_fields_set`; participating fields are those in `explicit` whose value is non-empty when `isinstance(value, str)`; `file_config.model_copy(update=participating)` → checkpoint: `PrettyConfig(browser="firefox")` overwrites only `browser`; `PrettyConfig(headless=False)` overwrites `headless` (bool False participates — passed at construction); `PrettyConfig(cache_root="")` does not overwrite the resolved absolute default; `PrettyConfig()` changes nothing ✓
10. **Step**: `model_copy(update=...)` performs no re-validation — safe here because both instances are validated and the validators are per-field; the result is the effective `Config` ✓
11. **Output**: the effective `Config` — file+env layer with explicit programmatic values on top.

#### Checkpoint Summary
- Programmatic layer wins over env layer (overlay happens after env merge): passed.
- One model, one validation place: passed.
- `overrides=None` path byte-identical to the current behavior: passed.

### Trace: `LlmProvider.generate_step_code` → `OpenAiProvider` / `AnthropicProvider`

#### Chain
1. **Input**: `prompt` (engine `SYSTEM_PROMPT`), `user_instructions` (engine
   `config.generation_prompt`), `step_text`, `previous_steps`, `snapshot`, `screenshot`,
   `page_api` (`PAGE_API_SURFACE`), `existing_code`, `error`.
2. **Step**: the port method signature inserts `user_instructions: str` as the second parameter; both implementations add the parameter at the same position → checkpoint: positional compatibility between port and mutations; engine calls by keyword ✓
3. **Step**: `build_fields_text(user_instructions, step_text, previous_steps, snapshot, page_api, existing_code, error)` builds the sections: STEP, PREVIOUS STEPS, PAGE SNAPSHOT, PAGE API, then — only when `user_instructions` is non-empty — `USER INSTRUCTIONS:\n{user_instructions}` verbatim, then CODE/ERROR only on regeneration → checkpoint: block placement "after the page API block, before the regeneration-only blocks (CODE, ERROR)" matches both provider annotations; the empty check lives in this one shared helper — parity by construction ✓
4. **Step**: openai — messages `[{system: prompt}, {user: openai_user_content(text, screenshot)}]` → `chat.completions.create(model=effective_generation_model)`; anthropic — `messages.create(model=..., system=prompt, content=self._user_content(text, screenshot))` → checkpoint: instructions change only the shared `text`; SDK call patterns untouched (see `openai`, `anthropic`) ✓
5. **Step**: SDK error → `LlmUnavailableError` naming the provider (unchanged mapping) ✓
6. **Step**: answer → `require_completion_text` → `extract_code_block` (first fenced block, unfenced verbatim) — unchanged ✓
7. **Output**: the step code string; `classify_failure` is not touched by this trace — its field builder `build_classification_fields` stays without any instructions input → checkpoint: "classification requests never carry them" ✓

#### Checkpoint Summary
- Identical USER INSTRUCTIONS rendering in both providers (single shared helper): passed.
- Port signature order matches the manifest: passed.
- No instructions leak into classification: passed.

### Trace: `DriverSession.open_context()` — launch vs connect

#### Chain
1. **Input**: `DriverSession(config)` with `config.browser` ∈ {chromium, firefox, webkit, chrome, msedge} and `config.browser_endpoint` ("" or a ws/wss URL).
2. **Step**: first call starts nothing-then-everything: `PlaywrightWorker` thread starts, `sync_playwright().start()` runs inside it (existing mechanics) ✓
3. **Step**: engine start branches inside `_launch_engine`:
   - `browser_endpoint` empty → the current launch path: engine = chromium for chrome/msedge (channel=name) else the named engine; `engine.launch(headless=config.headless, channel=...)` ✓
   - `browser_endpoint` set → engine = **chromium for chrome/msedge** (channels do not apply to a connect — the cook's rule; chrome/msedge are chromium channels, so the engine type is chromium) else the named engine; `engine.connect(browser_endpoint)` — `headless` is not passed (window visibility belongs to the endpoint server), no channel argument ✓
4. **Step**: a failed launch propagates as-is after cleanup: `worker.run(playwright.stop)`, `worker.close()` — a retry begins from a clean state (existing `_launch` try/except covers both branches); a failed **connect** is re-raised wrapped with the endpoint named — `Error(f"cannot connect to the browser endpoint {config.browser_endpoint}: {failure}") from failure` — because Playwright's own connect message carries only the OS-level cause (verified in the driver bundle: `WebSocket error: connect ECONNREFUSED 127.0.0.1:1`, `getaddrinfo ENOTFOUND host`, TLS failures with no address at all; the endpoint URL reaches only the progress log) → checkpoint: "a failed connect fails loudly with an actionable message naming the endpoint" — satisfied by the wrapper; the launch path keeps Playwright's own actionable text (it names the missing distribution itself) ✓
5. **Step**: success → `browser.new_context()` → `context.new_page()` inside the driver thread → `PageFacade(page, context)` bound to the worker ✓
6. **Output**: the per-test page facade. Subsequent calls of the same session create further isolated contexts of the same browser.

#### Checkpoint Summary
- Branch condition reads the `browser_endpoint` setting of `Config` exactly as the driver annotation states: passed.
- chrome/msedge → chromium engine on the connect path (channels do not apply): passed.
- Cleanup symmetry between launch and connect failures: passed (one `_launch` wrapper).
- The connect error names the endpoint (wrapper re-raise; Playwright's raw connect error does not): passed.

### Trace: `PageFacade.find_by_attribute` / `find_by_css` / `find_by_xpath`

#### Chain
1. **Input**: attribute pair `("data-test-id", "submit-button")`, or a CSS selector `"form > button.primary"`, or an XPath expression `"//button[@type='submit']"`.
2. **Step**: `find_by_attribute` builds a CSS attribute selector with the value escaped for the quoted string context: backslashes doubled first, then double quotes escaped — `['data-test-id'="submit-button"]`-style bracket selector with double-quoted value → `self._page.locator(f'[{name}="{escaped}"]')` → checkpoint: values containing `"` or `\` cannot break out of the selector; Playwright's CSS engine handles attribute selectors natively ✓
3. **Step**: `find_by_css` → `self._page.locator(selector)` — the selector passes through verbatim ✓
4. **Step**: `find_by_xpath` → `self._page.locator(f"xpath={xpath}")` — the explicit `xpath=` engine prefix (robust for expressions the implicit sniffing misses: Playwright detects XPath only via `/^\(*\/\//` or a `..` prefix, so `*[@id='main']` or `./div` would silently go to the CSS engine; a parenthesized `(//div)[2]` is in fact sniffed, but the prefix keeps every expression uniform) ✓
5. **Step**: each lookup runs through `self._call` (driver thread when a worker is bound; inline for hand-built facades in tests) and returns `self._wrap_locator(locator)` — the handle inherits the driver-thread boundary and Playwright's auto-wait ✓
6. **Output**: a `LocatorFacade` — the same element API as the existing locating methods; expectations raise assertion-style errors destined for classification.

#### Checkpoint Summary
- Locator objects resolve lazily at action time — auto-wait semantics identical to the existing three locating methods: passed.
- No raw Playwright object crosses the facade: passed.

### Trace: `StepGenerator.generate` / `regenerate` (changed step)

#### Chain
1. **Input**: `identity`, `step_text`, `previous_steps`, `page`; `regenerate` adds `existing_code`, `error`.
2. **Step**: `spend = budgets.try_generation | try_healing` — the per-test registry (the runtime built it fresh for this test) → checkpoint: budget exhaustion semantics unchanged, only the registry lifetime changed ✓
3. **Step**: per attempt — `on_generation_started` report, `page.aria_snapshot()`, optional `page.screenshot()` ✓
4. **Step**: `provider.generate_step_code(prompt=SYSTEM_PROMPT, user_instructions=self._config.generation_prompt, step_text=..., previous_steps=..., snapshot=..., screenshot=..., page_api=PAGE_API_SURFACE, existing_code=..., error=...)` — one call site in `_loop` covers both pools → checkpoint: instructions carried on generation **and** regeneration; the empty value means "no block" inside the provider helper — the engine passes the value unconditionally, the single empty-check renders parity ✓
5. **Step**: candidate execution via `run_step_code`; `AssertionError` → the failed-check stop with classification (unchanged); other failures → retry with fresh error/snapshot; success → `CachedStep` + `cache.save` ✓
6. **Output**: the proven `CachedStep`. `SYSTEM_PROMPT` (renamed from `GENERATION_PROMPT`) text gains the USER INSTRUCTIONS input line and the universal-locating priority line — mirroring the `system_prompt` practice; `PAGE_API_SURFACE` gains the three locator rows — mirroring `facade.md` (see Additional Instructions).

#### Checkpoint Summary
- The instructions value takes no part in the step address — `StepIdentity` inputs untouched: passed.
- Rename frees the name `generation_prompt` for the public setting — no collision remains in the engine manifest: passed.

### Trace: `PrettyTest.__init__` (new composition)

#### Chain
1. **Input**: `cache_key: str`, `cache_path: str | None = None`, `config: PrettyConfig | None = None`.
2. **Step**: `effective = load_config(None, config)` → checkpoint: `config=None` resolves everything from pyproject+env — behavior identical to today; non-None merges explicit values over the file layer ✓
3. **Step**: `self._runtime = PrettyplayRuntime(effective)` — the module-global singleton and `get_runtime` no longer exist; every test owns its runtime → checkpoint: two `PrettyTest` in one process hold two runtimes, two registries, two browser sessions ✓
4. **Step**: per-test reporter (`StepReporter(hooks=[])`), `StepCache(runtime.config, cache_path, reporter)`, `StepGenerator`/`StepHealer` from the runtime config/provider/budgets, `StepExecutor(cache_key, cache, generator, healer, budgets, reporter)` — the existing wiring, sourced from `self._runtime` ✓
5. **Step**: nothing expensive starts — the browser launches lazily on the first step (existing `_ensure_page`), the provider constructs lazily on first access → checkpoint: "construction is cheap; no LLM credentials required" — atexit registration inside the runtime constructor is cheap and credential-free ✓
6. **Output**: the composed test object; `cache_key` property delegates to the executor as today.

#### Checkpoint Summary
- No cross-test state on the instance: passed (every collaborator is per-test).
- Failure of `load_config` (invalid merged settings) surfaces as `ConfigurationError` at construction time, before any browser/LLM involvement: passed — matches the failures table in `lifecycle.md`.

### Trace: `PrettyTest.close()` / `__exit__` and `PrettyplayRuntime.close()`

#### Chain
1. **Input**: explicit `close()` call, context-manager exit, or process exit (atexit).
2. **Step**: `close()` — if a page exists: `self._page.close()` (closes the isolated context; the browser process keeps running until the next step) then `self._page = None`; then `self._runtime.close()` unconditionally → checkpoint: idempotent — page block guarded, `runtime.close` is a no-op when nothing started; repeated `close()` safe ✓
3. **Step**: `PrettyplayRuntime.__init__` registered `atexit.register(self.close)` — one hook per instance; at process exit atexit runs hooks LIFO, each closes only its own browser/driver → checkpoint: N tests = N hooks (accepted ADR-1 risk); manual close + atexit double-close is safe by idempotency ✓
4. **Step**: `runtime.close()` → `DriverSession.close()`: browser close (a connected browser disconnects — the remote browser process belongs to the endpoint server), Playwright stop, driver thread join — the existing sequence ✓
5. **Output**: no leaked browser processes, driver threads or Playwright drivers for the closed test; other tests' runtimes are untouched.

#### Checkpoint Summary
- The context manager exit performs the same full close as the explicit method: passed.
- Interactive sessions (no process exit between cells): the integrator closes each test explicitly — `lifecycle.md` documents this: passed.

### Trace: root re-export (`->PrettyConfig: {}`)

#### Chain
1. **Input**: integrator import `from prettyplay import PrettyTest, PrettyConfig`.
2. **Step**: `prettyplay/__init__.py` imports `PrettyConfig` from `.config` (where `PrettyConfig = Config` is defined in `models.py` and exported by the cell facade) and lists it in `__all__` together with `PrettyTest`, `PrettyplayRuntime`, `StepExecutor`; `get_runtime` is removed from the module and `__all__` → checkpoint: the embedding matches the manifest; `get_runtime` absent from the public export ✓
3. **Output**: the public names `PrettyTest`, `PrettyConfig`, `PrettyplayRuntime`, `StepExecutor`; `Config` stays importable from `prettyplay.config` for the other cells.

#### Checkpoint Summary
- Breaking change (get_runtime removal) is deliberate and ADR-approved; no external consumers exist (discovery fact): passed.

## Algorithm Design

### `Config` (models.py)

**Responsibility**: the validated settings model — single source of the immutable configuration part; the public name `PrettyConfig` is an alias of it.

**Algorithm:**
```
1. Declare fields in the contract order:
   provider, browser, model, generation_model, classification_model, base_url,
   cache_root, generation_prompt, browser_endpoint, generation_attempts,
   healing_attempts, send_screenshots, headless — str fields default "",
   attempts PositiveInt 3/2, send_screenshots False, headless True.
2. field_validator("browser_endpoint"):
   IF value == "": return value                      # unset — local launch
   parsed = urlparse(value)
   IF parsed.scheme not in {"ws", "wss"} OR parsed.netloc == "":
     raise ValueError("must be a valid ws/wss URL")  # → actionable render in the loader
   return value
3. Define PrettyConfig = Config (module-level alias, exported by the cell facade).
```

**Errors:**
- `pydantic.ValidationError` (loc browser_endpoint) → loader wraps into `ConfigurationError`; direct construction by the integrator surfaces the pydantic error at their own call site.

**Edge Cases:**
- `browser_endpoint="ws://"` (empty netloc) → invalid. `"wss://host:port/path"` → valid. Value with uppercase scheme `WS://` — `urlparse` lowercases the scheme; accept.

### `load_config` (loader.py)

**Responsibility**: resolve the effective settings from pyproject + env + explicit programmatic values; one place of validation.

**Algorithm:**
```
0. Signature: load_config(pyproject_path: str | None = None, overrides: Config | None = None)
   — both parameters optional; single-argument calls keep working (the cell usage example
   and the existing loader tests call it with pyproject_path only)
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

**Errors:**
- `FileNotFoundError` / `TOMLDecodeError` — unchanged behaviors.
- `ConfigurationError` — merged file+env validation failure, actionable per-setting lines.

**Edge Cases:**
- `overrides=PrettyConfig()` → `update` empty → the file layer returned (equal semantics to None, one extra cheap copy).
- Explicit `headless=False` / `send_screenshots=False` participate (in `model_fields_set`, bool value is not a string).
- Env var set AND explicit override set → the override wins (overlay runs after env merge).
- Explicit `cache_root=""` → not participating → the resolved absolute default survives.

### `LlmProvider` port + `OpenAiProvider` / `AnthropicProvider`

**Responsibility**: the unified LLM port; both implementations in absolute parity, now including the user instructions input.

**Algorithm:**
```
1. Port method signature (both implementations mirror it):
   generate_step_code(prompt, user_instructions, step_text, previous_steps,
                      snapshot, screenshot, page_api, existing_code, error) -> str
2. build_fields_text(user_instructions, step_text, previous_steps, snapshot,
                     page_api, existing_code, error):
   sections = [STEP, PREVIOUS STEPS, PAGE SNAPSHOT, PAGE API]
   IF user_instructions: sections.append("USER INSTRUCTIONS:\n" + user_instructions)
   IF existing_code is not None: sections.append(CODE)
   IF error is not None: sections.append(ERROR)
   return "\n\n".join(sections)
3. Providers pass user_instructions through unchanged; request/response handling unchanged.
```

**Errors:** unchanged (`LlmUnavailableError` on SDK failures and empty completions).

**Edge Cases:**
- Whitespace-only instructions string is non-empty → the block renders verbatim (no trimming — the value is the project's text).
- Instructions containing markdown fences/headers — rendered as-is inside the block; the model-facing structure is fixed by the section label, not by sanitization.

### `DriverSession` (session.py)

**Responsibility**: lifecycle owner of the Playwright sync driver and the browser process of one test; local launch or remote connect.

**Algorithm:**
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

**Errors:**
- Connect failure → the Playwright `Error` is re-raised wrapped as an `Error` naming `config.browser_endpoint`, chained to the original (Playwright's raw connect message carries only the OS-level cause, not the endpoint); `_launch` stops the started Playwright and closes the worker — retry from a clean state.
- Channel launch without the installed browser → Playwright's actionable error, as today.

**Edge Cases:**
- `browser_endpoint` set and `browser="chrome"` → connects a chromium engine (channels do not apply).
- `close()` on a connected browser disconnects; the remote browser process is the server's concern.

### `PageFacade` locators (page.py)

**Responsibility**: universal locating for elements without accessible names, through the same facade boundary and auto-wait.

**Algorithm:**
```
find_by_attribute(name, value):
1. escaped = value.replace("\\", "\\\\").replace('"', '\\"')
2. locator = _call(lambda: page.locator(f'[{name}="{escaped}"]'))
3. return _wrap_locator(locator)

find_by_css(selector):
  locator = _call(lambda: page.locator(selector)); return _wrap_locator(locator)

find_by_xpath(xpath):
  locator = _call(lambda: page.locator(f"xpath={xpath}")); return _wrap_locator(locator)
```

**Errors:** none raised eagerly — locators resolve at action time; action failures surface through the locator API as today.

**Edge Cases:**
- Attribute value with quotes/backslashes — escaped, selector stays single-element.
- XPath not matched by the implicit sniffing (`*[@id='main']`, `./div`) — the explicit `xpath=` prefix keeps it out of the CSS engine.

### `StepGenerator` (generator.py)

**Responsibility**: the generation engine; now carries the project user instructions on every provider request of both pools.

**Algorithm:**
```
_loop(identity, step_text, previous_steps, page, pool, existing_code, error):
1. spend = budgets.try_generation (pool "generation") | budgets.try_healing (pool "healing")
2. per granted attempt:
   report on_generation_started
   snapshot = page.aria_snapshot(); screenshot = page.screenshot() if send_screenshots
   code = provider.generate_step_code(
       prompt=SYSTEM_PROMPT,
       user_instructions=self._config.generation_prompt,   # "" → no block, provider-side
       step_text=..., previous_steps=..., snapshot=..., screenshot=...,
       page_api=PAGE_API_SURFACE, existing_code=..., error=...)
   run_step_code(code, page) → success: CachedStep + cache.save + return
                              → AssertionError: failed-check stop (classification, unchanged)
                              → other: retry with fresh error/snapshot
3. exhaustion: generation pool → classify last candidate; healing pool → raise without
   classification (healer attaches its verdict) — unchanged.
```

**Errors:** unchanged taxonomy and verdict routing.

**Edge Cases:**
- `generation_prompt` changes between runs — cached steps execute as stored; only fresh generation sees the new instructions (the address has no instructions component).

### `PrettyplayRuntime` (runtime.py)

**Responsibility**: the per-test composition root.

**Algorithm:**
```
__init__(config):
1. keep config; budgets = RunBudgets(config.generation_attempts, config.healing_attempts)
2. driver = None; provider = None                       # lazy, as today
3. atexit.register(self.close)                          # one hook per instance
close(): driver.close() if started — idempotent          # browser → playwright.stop → thread join
get_runtime and the module singleton: DELETED
```

**Edge Cases:**
- A runtime constructed but never stepped: close is a no-op; its atexit hook is a no-op.
- N runtimes in one process: N atexit hooks, each idempotent, LIFO order at exit.

### `PrettyTest` (scenario.py)

**Responsibility**: the integrator object — one per test, now owning its runtime and effective config.

**Algorithm:**
```
__init__(cache_key, cache_path=None, config=None):
1. effective = load_config(None, config)
2. self._runtime = PrettyplayRuntime(effective)
3. reporter = StepReporter(hooks=[])
4. cache = StepCache(self._runtime.config, cache_path, reporter)
5. generator = StepGenerator(...runtime.config, runtime.provider, cache, runtime.budgets, reporter)
   healer   = StepHealer(...same collaborators...)
6. executor = StepExecutor(cache_key, cache, generator, healer, runtime.budgets, reporter)
7. _page = None — opens lazily on the first step
close():
1. IF _page: _page.close(); _page = None
2. self._runtime.close()
__exit__: close(); never suppress
```

**Errors:**
- `ConfigurationError` from `load_config` at construction (invalid merged settings).
- Step failures propagate by kind with folded tracebacks — unchanged (`_raise_folded`).

**Edge Cases:**
- `config=None` → pure file+env resolution, previous behavior.
- Two tests with equal `cache_key` in the shared root → steps reused across tests, budgets independent per test.

## Cross-cutting Concerns

- **Error handling**: unchanged strategy. `ConfigurationError` (actionable settings text, chained pydantic original) for configuration; Playwright `Error` propagates from launch with its actionable message (names the missing browser); a failed connect is re-raised wrapped as an `Error` naming the endpoint (chained to Playwright's original — see the DriverSession trace); `LlmUnavailableError` for provider service failures; verdict-carrying `ProductDefectError`/`IncurableStepError` for terminal step failures. Nothing new is swallowed; the overlay adds no new failure mode.
- **Logging**: the standard logger `prettyplay` — no new log points required. Existing events (step/generation/healing/cache/verdict) unchanged; the verdict-skip WARNING unchanged. Instruction text is project configuration, not a secret — but it is not logged either (no logging of request payloads exists today; keep it that way).
- **Validation**: the pydantic model is the single validation place — file values, env values and programmatic values all flow through the same validators; the loader renders failures; `browser_endpoint` gains the ws/wss check; `_ALLOWED_TEXT` gains the two new entries so the rendered message stays actionable.
- **Caching**: step addressing is untouched — instructions and endpoint never enter `StepIdentity`; cached steps run as stored regardless of either setting. The cache write/read mechanics are unchanged.
- **Concurrency**: one `PlaywrightWorker` thread per `DriverSession` per runtime per test — strictly sequential driving within each test; tests never share browser state through the library. The calling thread never adopts the Playwright event loop (interactive hosts keep working). atexit hooks: one per runtime, idempotent, LIFO at exit.

## Usages Analysis

### `conventions`
- **What it provides**: mandatory Python code and test rules (relative imports, pydantic kw_only models with empty defaults, Google docstrings, logging, test structure, ruff/pytest commands).
- **Where used**: every cell (global annotations of all six manifests).
- **Why chosen**: the project-wide baseline; no contract change touches it.
- **How exactly**: all new code follows it — kw_only model fields with empty defaults, relative intra-package imports, mirrored test layout `tests/<pkg>/test_<module>.py`.

### `pydantic`
- **What it provides**: data model rules — kw_only construction, empty defaults, the `[tool.prettyplay]` schema with the two new fields, the layered merge mechanics (`model_fields_set` + `model_copy`), actionable validation wrapping, tomllib/tomli fallback.
- **Where used**: `Config` (models.py), `load_config` (loader.py).
- **Why chosen**: settings model and merge mechanics are pydantic-native; the model-with-empty-defaults convention makes "explicitly set vs untouched" mechanical.
- **How exactly**: `model_fields_set` for participation, `model_copy(update=...)` for the overlay, `ValidationError` → `ConfigurationError` chaining, `field_validator` for the ws/wss check.

### `playwright`
- **What it provides**: sync API lifecycle, engine/channel matrix, remote ws connect, locator auto-wait, aria snapshot, scroll primitives, per-test browser process.
- **Where used**: `DriverSession`, `PageFacade`, `LocatorFacade` (driver cell).
- **Why chosen**: the driver is Playwright sync-only by architecture.
- **How exactly**: `engine.connect(ws_endpoint)` on the remote branch; `page.locator(...)` for the three new locating methods (CSS attribute selector, CSS passthrough, `xpath=` prefix); the existing launch/headless/channel rules on the local branch.

### `system_prompt` (engine, inline)
- **What it provides**: the fixed system prompt of every generation/regeneration request — now documenting the USER INSTRUCTIONS input and the universal-locating priority.
- **Where used**: `StepGenerator` (constant `SYSTEM_PROMPT`).
- **Why chosen**: renamed from `generation_prompt` to free the name for the public setting (ADR-3).
- **How exactly**: applied verbatim as the system message via the provider `prompt` parameter; the priority line keeps role → text → label as the default with attribute/CSS/XPath as fallbacks unless USER INSTRUCTIONS say otherwise.

### `classification_prompt` (engine, inline)
- **What it provides**: the fixed classification prompt; unchanged.
- **Where used**: `classify_step_failure`.
- **Why chosen**: unchanged contract; verified it carries no instructions input.

### Imported Usages
- `taxonomy` from `prettyplay/failures` (imported by config, root) — the failure base `PrettyplayError` and the terminal error kinds; `ConfigurationError` stays a mutation of the base.
  - Path: `prettyplay/failures/.usages/taxonomy.md`
- `hooks` from `prettyplay/reporting` (imported by cache, root) — hook payload contracts; unchanged.
  - Path: `prettyplay/reporting/.usages/hooks.md`
- `facade` from `prettyplay/driver` (imported by engine) — the page API surface; extended with the three locators, drives `PAGE_API_SURFACE`.
  - Path: `prettyplay/driver/.usages/facade.md`
- `classification` from `prettyplay/llm` (imported by engine) — classification verdict semantics; unchanged.
  - Path: `prettyplay/llm/.usages/classification.md`
- `generation`, `healing` from `prettyplay/engine` (imported by root) — the engine cycles the executor delegates to; updated to per-test budgets and instructions routing.
  - Path: `prettyplay/engine/.usages/generation.md`, `prettyplay/engine/.usages/healing.md`

## `.usages/` Update

All six cell-level `.usages/` files were already materialized by the apply-architecture stage from the approved plan. This stage verified each against its CODEMANIFEST:

### Cell: `prettyplay/config`
- **`configuration.md`** → current. The 13-setting TOML table, the 13-row env table, the layered merge section (PrettyConfig example), the remote execution section and the rules all match the manifest (fields, env names, ws/wss rule, PrettyConfig name). Additions needed: none.

### Cell: `prettyplay/cache`
- **`budgets.md`** → current. Per-test semantics, the fresh-budget-per-test rule with the N × attempts statement, defaults — match `RunBudgets`. Additions needed: none.

### Cell: `prettyplay/driver`
- **`facade.md`** → current. The Surface table and the example include the three new locators in the manifest order; the rules state one-browser-per-test. `PAGE_API_SURFACE` must mirror this file — the implementation adds the three rows. Additions needed: none.

### Cell: `prettyplay/engine`
- **`generation.md`** → current. USER INSTRUCTIONS routing, per-test budget wording, failed-check stop, the fixed form with the new locators — match the manifest. Additions needed: none.
- **`healing.md`** → current. Per-test registry ownership, exhaustion verdict reuse — match. Additions needed: none.

### Cell: `prettyplay` (root)
- **`lifecycle.md`** → current. Per-test composition, `ConfigurationError` in the failures table, per-test atexit, the interactive-session guidance with explicit close — match the root manifest. Additions needed: none.

### New Files
- None — every change stays inside an existing functional domain.

## Test Stack Trace

### General Setup

- Unit tests build fakes at the external boundaries only (SDK clients, Playwright objects, provider port) per `conventions`; no venv/network needed for the suite; `pytest tests/ -x` green is the gate.
- Shared helpers already present: `FakePage` (tests/test_scenario.py), provider/SDK mocks (tests/llm/*), session mocks (tests/driver/test_session.py).
- New shared fixture (tests/conftest.py): `write_pyproject(tmp_path, **settings)` writing a `[tool.prettyplay]` TOML — used by loader merge tests.

### Source File Registry

- `prettyplay/config/models.py`, `prettyplay/config/loader.py`, `prettyplay/config/__init__.py`
- `prettyplay/llm/provider.py`, `prettyplay/llm/_request.py`, `prettyplay/llm/openai_provider.py`, `prettyplay/llm/anthropic_provider.py`
- `prettyplay/driver/session.py`, `prettyplay/driver/page.py`
- `prettyplay/engine/generator.py`
- `prettyplay/cache/budgets.py`
- `prettyplay/runtime.py`, `prettyplay/scenario.py`, `prettyplay/__init__.py`

---

### Positive Tests

#### `test_load_config_overrides_explicit_values_win`

**Setup**: `tmp_path` pyproject.toml with `[tool.prettyplay]` `browser = "chromium"`, `model = "gpt-5"`, `base_url = "https://file.example/v1"`; env clean.

**Input**: `load_config(str(tmp_path / "pyproject.toml"), Config(browser="firefox", browser_endpoint="ws://ci-grid:3000/playwright/firefox"))`

**Trace**:
```
load_config(path, overrides)
  → tomllib.load                       # file layer: browser=chromium, model=gpt-5, base_url=...
  → _collect_env_overrides()           # none set
  → Config(**merged)                   # file layer validated
  → explicit = {"browser", "browser_endpoint"}
  → model_copy(update={"browser": "firefox", "browser_endpoint": "ws://..."})
```

**Assertions**:
```
config.browser == "firefox"                       # explicit wins
config.browser_endpoint == "ws://ci-grid:3000/playwright/firefox"
config.model == "gpt-5"                           # untouched file value survives
config.base_url == "https://file.example/v1"      # untouched file value survives
```

**Sufficiency**: the core ADR-2 acceptance — explicit programmatic values win while untouched file fields keep working.

#### `test_load_config_without_overrides_returns_file_layer`

**Setup**: `tmp_path` pyproject.toml with `provider = "anthropic"`, `generation_attempts = 5`.

**Input**: `load_config(str(tmp_path / "pyproject.toml"), None)`; then `load_config(str(tmp_path / "pyproject.toml"), PrettyConfig())`

**Trace**:
```
load_config(path, None)
  → file layer validated → overrides is None → return as is
load_config(path, PrettyConfig())
  → model_fields_set empty → update empty → model_copy(update={}) → the file layer
```

**Assertions**: `config.provider == "anthropic" and config.generation_attempts == 5 and config.generation_prompt == "" and config.browser_endpoint == ""` for both calls.

**Sufficiency**: the None path keeps the previous behavior — the default integrator experience is unchanged; the empty overlay is semantically equal to None (an explicitly empty PrettyConfig never erases the file layer).

#### `test_models_browser_endpoint_accepts_ws_and_wss`

**Setup**: none (pure model test).

**Input**: `pytest.mark.parametrize("endpoint", ["ws://host:3000/x", "wss://grid.example/playwright/chromium", "ws://127.0.0.1:9000", "WS://host:3000"])` → `Config(browser_endpoint=endpoint)`

**Trace**:
```
Config(browser_endpoint=endpoint)
  → field_validator: urlparse(endpoint).scheme in {"ws","wss"} and netloc non-empty → pass
```

**Assertions**: `config.browser_endpoint == endpoint` for every parametrize case.

**Sufficiency**: the accepted remote address forms — prevents over-restrictive validation breaking real grids.

#### `test_build_fields_text_places_user_instructions_after_page_api`

**Setup**: none (pure helper test, tests/llm/test_request.py).

**Input**: `build_fields_text(user_instructions="prefer data-test-id", step_text="click Sign in", previous_steps=["open the page"], snapshot="- button \"Sign in\"", page_api="page.open(url)", existing_code="def step(page)...", error="TimeoutError")`

**Trace**:
```
build_fields_text(...)
  → sections = [STEP, PREVIOUS STEPS, PAGE SNAPSHOT, PAGE API]
  → user_instructions non-empty → append "USER INSTRUCTIONS:\nprefer data-test-id"
  → existing_code/error not None → append CODE, ERROR
  → "\n\n".join(sections)
```

**Assertions**:
```
text.index("PAGE API:") < text.index("USER INSTRUCTIONS:") < text.index("CODE:")
"USER INSTRUCTIONS:\nprefer data-test-id" in text          # verbatim, own block
```

**Sufficiency**: the exact block placement is a parity contract of both providers — one helper, one order.

#### `test_openai_generate_step_code_carries_user_instructions`

**Setup**: `Config(model="gpt-5", generation_prompt="prefer data-test-id")`; `mock.patch.object(OpenAI, "chat")` style SDK boundary fake returning a fenced `def step(page)...` completion (existing test helpers in tests/llm/test_openai_provider.py).

**Input**: `provider.generate_step_code(prompt="SYS", user_instructions="prefer data-test-id", step_text="click Sign in", previous_steps=[], snapshot="- button", screenshot=None, page_api="page.open(url)", existing_code=None, error=None)`

**Trace**:
```
generate_step_code(...)
  → build_fields_text → USER INSTRUCTIONS block present
  → client.chat.completions.create(model="gpt-5", messages=[{system:"SYS"}, {user: <text>}])
  → extract_code_block(fenced answer)
```

**Assertions**:
```
"USER INSTRUCTIONS:\nprefer data-test-id" in captured_user_text
captured_system == "SYS"
result == "def step(page) -> None:\n    ..."
```

**Sufficiency**: proves the instructions reach the openai request content end-to-end from the public port signature.

#### `test_anthropic_user_instructions_parity`

**Setup**: same as the openai test against `AnthropicProvider` (tests/llm/test_anthropic_provider.py SDK fake).

**Input**: the same port call with the same values.

**Trace**: symmetric — `build_fields_text` (same helper) → `messages.create(system="SYS", content=<same text>)`.

**Assertions**: the captured anthropic user text contains the same `"USER INSTRUCTIONS:\nprefer data-test-id"` block at the same relative position as in the openai test.

**Sufficiency**: the parity requirement — identical rendering in both providers is asserted, not assumed.

#### `test_find_by_attribute_builds_css_attribute_selector`

**Setup**: `FakePage`-style page object recording `locator` calls; `PageFacade(fake_page, fake_context)` hand-built (worker None → inline calls).

**Input**: `facade.find_by_attribute("data-test-id", "submit-button")`

**Trace**:
```
find_by_attribute("data-test-id", "submit-button")
  → escaped = "submit-button" (no quotes/backslashes)
  → page.locator('[data-test-id="submit-button"]')   # recorded by the fake
  → LocatorFacade wrapping the recorded locator
```

**Assertions**: `fake_page.locator_calls == ['[data-test-id="submit-button"]']` and `isinstance(result, LocatorFacade)`.

**Sufficiency**: the data-attribute locator is the ADR-4 headline — the exact selector form is the contract with generated code.

#### `test_find_by_xpath_applies_xpath_engine_prefix`

**Setup**: the same hand-built facade.

**Input**: `facade.find_by_xpath("*[@id='main']")`

**Trace**: `page.locator("xpath=*[@id='main']")` recorded.

**Assertions**: the recorded selector equals `"xpath=*[@id='main']"`.

**Sufficiency**: an expression the implicit sniffing misses (`*[@id='main']` goes to the CSS engine without the prefix) must stay a valid XPath — the explicit engine prefix is the robustness decision.

#### `test_find_by_css_passes_selector_verbatim`

**Setup**: the same hand-built facade with a recording fake page.

**Input**: `facade.find_by_css("form > button.primary")`

**Trace**:
```
find_by_css("form > button.primary")
  → page.locator("form > button.primary")   # recorded verbatim, no escaping
  → LocatorFacade wrapping the recorded locator
```

**Assertions**: `fake_page.locator_calls == ["form > button.primary"]` and `isinstance(result, LocatorFacade)`.

**Sufficiency**: the passthrough contract — the selector must reach Playwright unmodified (unlike the attribute branch, which builds one); guards against a "universal" escaping that would break `>`/`+` combinators.

#### `test_session_connects_over_ws_endpoint_when_set`

**Setup**: `Config(browser="firefox", browser_endpoint="ws://ci-grid:3000/playwright/firefox")`; monkeypatched `prettyplay.driver.session.sync_playwright` returning a fake with `firefox.connect` / `chromium.connect` / launch recorders (existing session test fakes).

**Input**: `session.open_context()`

**Trace**:
```
open_context()
  → _launch(): worker starts, playwright.start() (faked)
  → _launch_engine: browser_endpoint non-empty
    → playwright.firefox.connect("ws://ci-grid:3000/playwright/firefox")
  → browser.new_context() → new_page() → PageFacade
```

**Assertions**:
```
fake.firefox.connect_calls == ["ws://ci-grid:3000/playwright/firefox"]
fake.launch_calls == []                     # no local launch on the connect path
"headless" not in fake.connect_kwargs       # headless ignored
```

**Sufficiency**: the ADR-5 branch — endpoint set means connect, not launch.

#### `test_session_connect_maps_channels_to_chromium`

**Setup**: `Config(browser="chrome", browser_endpoint="ws://ci-grid:3000/playwright/chromium")`, same fakes.

**Input**: `session.open_context()`

**Trace**: `_launch_engine` → `playwright.chromium.connect(endpoint)` (chrome is a chromium channel; channels do not apply to a connect).

**Assertions**: `fake.chromium.connect_calls == [endpoint]` and no `channel=` kwarg anywhere.

**Sufficiency**: pins the engine mapping decision for channel names on the connect path.

#### `test_scenario_builds_own_runtime_per_test`

**Setup**: `mock.patch("prettyplay.scenario.load_config", return_value=Config(model="gpt-5"))` — construction must not read the real pyproject.

**Input**: `t1 = PrettyTest("k1"); t2 = PrettyTest("k2")`

**Trace**:
```
PrettyTest("k1") → load_config(None, None) → PrettyplayRuntime(cfg)   # instance A
PrettyTest("k2") → load_config(None, None) → PrettyplayRuntime(cfg)   # instance B
```

**Assertions**:
```
t1._runtime is not t2._runtime
t1._runtime.budgets is not t2._runtime.budgets
load_config_mock.call_args_list == [call(None, None), call(None, None)]
```

**Sufficiency**: the ADR-1 core acceptance — one runtime (and one budget registry) per test, order-independent outcomes.

#### `test_scenario_close_stops_page_and_runtime`

**Setup**: `PrettyTest` with `mock.patch` on `runtime.open_page` returning a fake page whose `close` counts.

**Input**: run one step (page opens), then `test.close()`; then `test.close()` again.

**Trace**:
```
close() → _page.close() (count 1) → _runtime.close() (driver close recorded)
close() → _page is None → runtime.close() again — no-op (idempotent)
```

**Assertions**: fake page `close_count == 1`; driver close recorded once; no exception on the second call.

**Sufficiency**: close semantics changed from "page only, runtime stays" to "the whole runtime of the test" — and idempotency protects the atexit double-close.

#### `test_runtime_registers_own_atexit_close`

**Setup**: `mock.patch("prettyplay.runtime.atexit.register")`.

**Input**: `r1 = PrettyplayRuntime(cfg); r2 = PrettyplayRuntime(cfg)`

**Trace**: each `__init__` registers `self.close`.

**Assertions**:
```
register.call_count == 2
r1.close in [c.args[0] for c in register.call_args_list]
r2.close in [c.args[0] for c in register.call_args_list]
```

**Sufficiency**: per-instance atexit replaces the deleted singleton hook — every browser stops at process exit.

#### `test_pretty_config_exported_and_get_runtime_removed`

**Setup**: none (import surface test, tests/test_integration.py).

**Input**: `import prettyplay`

**Trace**: module `__all__` and attribute lookup.

**Assertions**:
```
prettyplay.PrettyConfig is Config                       # same model object
"PrettyConfig" in prettyplay.__all__
not hasattr(prettyplay, "get_runtime")
```

**Sufficiency**: the embedding contract and the deliberate public-surface breaking change.

#### `test_generator_passes_generation_prompt_to_provider`

**Setup**: fake provider recording `generate_step_code` kwargs; `Config(generation_prompt="prefer data-test-id")`; fake page; `StepGenerator` with a stub cache and budgets.

**Input**: `generator.generate(identity, "click Sign in", [], fake_page)` with the fake provider returning working code.

**Trace**:
```
generate → _loop → provider.generate_step_code(
    prompt=SYSTEM_PROMPT, user_instructions="prefer data-test-id", ..., page_api=PAGE_API_SURFACE)
```

**Assertions**:
```
captured["user_instructions"] == "prefer data-test-id"
captured["prompt"] == SYSTEM_PROMPT
"page.find_by_attribute" in captured["page_api"]        # surface mirror check inline
```

**Sufficiency**: the engine is the only caller that must route the setting into the port — asserted together with the surface listing growth.

#### `test_regenerate_carries_user_instructions_with_code_and_error`

**Setup**: fake provider recording `generate_step_code` kwargs and returning working code; `Config(generation_prompt="prefer data-test-id")`; fake page; `StepGenerator` with a stub cache and `RunBudgets(1, 1)`.

**Input**: `generator.regenerate(identity, "click Sign in", [], fake_page, existing_code="def step(page)...", error="TimeoutError")`

**Trace**:
```
regenerate → _loop(pool="healing") → the first candidate succeeds
  → provider.generate_step_code(prompt=SYSTEM_PROMPT,
      user_instructions="prefer data-test-id",
      existing_code="def step(page)...", error="TimeoutError", ...)
  → CachedStep + cache.save
```

**Assertions**:
```
captured["user_instructions"] == "prefer data-test-id"
captured["existing_code"] == "def step(page)..."
captured["error"] == "TimeoutError"
captured["prompt"] == SYSTEM_PROMPT
```

**Sufficiency**: covers the second half of ADR-3 (regeneration) and pins the instructions traveling together with the regeneration-only fields through the one shared call site.

#### `test_reused_step_gets_fresh_budget_per_test`

**Setup**: two `RunBudgets(generation_limit=1, healing_limit=1)` registries (as two runtimes build them); one `StepIdentity`.

**Input**: `a.try_generation(identity) → True; a.try_generation(identity) → False; b.try_generation(identity) → ?`

**Trace**: registry A exhausts its step budget; registry B is a fresh mapping.

**Assertions**: the third call on `b` returns `True` (fresh registry, same identity).

**Sufficiency**: the flipped invariant — a step reused across tests gets N × attempts; prevents reintroducing the shared-budget regression.

#### `test_page_api_surface_mirrors_facade_practice`

**Setup**: none (constant check, tests/engine/test_generator.py).

**Input**: `PAGE_API_SURFACE`, compared against the three new locator rows.

**Trace**: static text comparison of the frozen constant.

**Assertions**:
```
"page.find_by_attribute(name, value)" in PAGE_API_SURFACE
"page.find_by_css(selector)" in PAGE_API_SURFACE
"page.find_by_xpath(xpath)" in PAGE_API_SURFACE
```

**Sufficiency**: the model only sees calls present in the listing — the listing and `facade.md` must change together; this pins the engine side of that sync.

---

### Negative Tests

#### `test_models_rejects_non_ws_browser_endpoint`

**Setup**: none.

**Input**: `Config(browser_endpoint="http://ci-grid:3000")` (and parametrize: `"ftp://x"`, `"ci-grid:3000"`, `"wss://"`).

**Trace**:
```
Config(browser_endpoint="http://ci-grid:3000")
  → field_validator: scheme "http" not in {"ws","wss"} → ValueError
  → pydantic.ValidationError (loc browser_endpoint)
```

**Assertions**: `pytest.raises(ValidationError)`; via the loader — `pytest.raises(ConfigurationError)` with `"browser_endpoint"` and `"ws/wss"` in the rendered message.

**Sufficiency**: the manifest validation rule — an invalid endpoint must never reach the driver.

#### `test_load_config_renders_actionable_line_for_endpoint`

**Setup**: `tmp_path` pyproject.toml with `browser_endpoint = "http://bad"`.

**Input**: `load_config(str(tmp_path / "pyproject.toml"), None)`

**Trace**:
```
merged contains browser_endpoint="http://bad"
  → Config(**merged) raises ValidationError
  → _render_validation: "browser_endpoint: received 'http://bad' — allowed: a valid ws/wss URL"
  → ConfigurationError chained
```

**Assertions**: `"browser_endpoint" in str(excinfo.value)` and `"ws/wss" in str(excinfo.value)` and `excinfo.value.__cause__` is a `ValidationError`.

**Sufficiency**: the actionable-error contract extends to the new setting — `_ALLOWED_TEXT` must carry the entry.

#### `test_session_failed_connect_cleans_up_for_retry`

**Setup**: fake playwright whose `firefox.connect` raises `Error("websocket connect timeout")` (an OS-level cause without the URL, as the real driver does); `Config(browser="firefox", browser_endpoint="ws://dead:1")`.

**Input**: `session.open_context()`

**Trace**:
```
_launch() → worker started, playwright started
  → _launch_engine → connect raises Error("websocket connect timeout")
  → wrapper re-raise: Error("cannot connect to the browser endpoint ws://dead:1: websocket connect timeout")
  → _launch except: worker.run(playwright.stop); worker.close(); re-raise
```

**Assertions**:
```
pytest.raises(Error) with "ws://dead:1" in str(excinfo.value)   # the wrapper names the endpoint
excinfo.value.__cause__ is the original Error                    # chained for debugging
fake.worker_alive is False                                       # thread joined
session.open_context() again → fresh start attempt (fake counts a second start)
```

**Sufficiency**: the clean-retry requirement covers the connect branch, and the failure names the endpoint.

#### `test_classify_failure_never_carries_user_instructions`

**Setup**: openai SDK fake; `Config(generation_prompt="prefer data-test-id")`.

**Input**: `provider.classify_failure(prompt="CLS", step_text="s", code="c", error="e", snapshot="- button", screenshot=None)`

**Trace**: `build_classification_fields` (no instructions parameter) → request captured.

**Assertions**: `"USER INSTRUCTIONS" not in captured_user_text`.

**Sufficiency**: ADR-3 boundary — classification is instruction-free by construction, asserted against the real request content.

---

### Edge Case Tests

#### `test_load_config_empty_string_override_does_not_win`

**Setup**: pyproject with `cache_root = "/custom/cache"` and `model = "gpt-5"`.

**Input**: `load_config(path, Config(model="", cache_root=""))`

**Trace**: both overrides in `model_fields_set` but empty strings → excluded from `update`.

**Assertions**: `config.model == "gpt-5" and config.cache_root == "/custom/cache"`.

**Sufficiency**: the "empty string means unset for string fields" convention — an empty programmatic value must not erase the file layer.

#### `test_load_config_explicit_false_overrides_file_true`

**Setup**: pyproject with `headless = true`.

**Input**: `load_config(path, Config(headless=False))`

**Trace**: `headless` in `model_fields_set`, bool value participates.

**Assertions**: `config.headless is False`.

**Sufficiency**: pins the fields_set semantics against the truthiness pitfall (the fixed pydantic cook snippet).

#### `test_load_config_env_value_loses_to_explicit_override`

**Setup**: pyproject with `browser = "chromium"`; `monkeypatch.setenv("PRETTYPLAY_BROWSER_NAME", "webkit")`.

**Input**: `load_config(path, Config(browser="firefox"))`

**Trace**: env overrides the file layer (chromium → webkit), then the overlay wins (firefox).

**Assertions**: `config.browser == "firefox"`.

**Sufficiency**: the layer order pyproject → env → PrettyConfig is observable end-to-end.

#### `test_build_fields_text_omits_block_when_instructions_empty`

**Setup**: none.

**Input**: `build_fields_text(user_instructions="", ...)` with regeneration fields.

**Trace**: the empty check skips the append; sections go PAGE API → CODE.

**Assertions**: `"USER INSTRUCTIONS" not in text` and `text.index("PAGE API:") < text.index("CODE:")`.

**Sufficiency**: the default configuration (empty instructions) produces byte-identical requests to the previous library behavior.

#### `test_find_by_attribute_escapes_quotes_and_backslashes`

**Setup**: hand-built facade with recording fake page.

**Input**: `facade.find_by_attribute("data-test-id", 'a"b\\c')`

**Trace**: `escaped = 'a\\"b\\\\c'` → selector `[data-test-id="a\"b\\c"]`.

**Assertions**: the recorded selector equals `[data-test-id="a\"b\\c"]` (single recorded argument, no exception).

**Sufficiency**: attribute values are page data — hostile characters must not corrupt the selector.

#### `test_scenario_close_before_first_step_is_safe`

**Setup**: `PrettyTest("k")` with mocked `load_config`; nothing started.

**Input**: `test.close()`

**Trace**: `_page` None → skip; `runtime.close()` → driver None → no-op.

**Assertions**: no exception; a subsequent step still opens a page lazily.

**Sufficiency**: the idempotent/safe-when-unstarted close contract (context manager on a skipped test).

#### `test_cached_step_runs_without_provider_when_instructions_differ`

**Setup**: `PrettyTest` with a preloaded cache file for the step identity (tmp cache root); fake provider recording calls; `Config(generation_prompt="new instructions")` passed to the test.

**Input**: `test.action("the cached sentence")`

**Trace**: executor load → cache hit → `run_step_code(cached.code)` — no generation request.

**Assertions**: `provider.generate_step_code.call_count == 0`; the step passed.

**Sufficiency**: the cache-non-invalidation acceptance — instructions never enter the address; a cached step never regenerates because the instructions changed.

---

### Existing Test Updates Required

- `tests/test_runtime.py`: delete the `TestGetRuntime` class and the `isolated_runtime_global` fixture (the singleton is gone); keep the constructor/surface contract tests; add the per-instance atexit test; drop the `get_runtime` import assertions.
- `tests/test_scenario.py`: drop the `runtime_module._runtime` reset fixture; construction tests assert the `load_config(None, config)` call and the private runtime; close tests assert page + runtime close.
- `tests/config/test_models.py`, `tests/config/test_loader.py`: new-field and merge suites above; existing env-override tests extend to the two new names.
- `tests/llm/test_request.py`: no existing test calls `build_fields_text` directly — add the placement/omission tests above; the two provider call sites update together with the signature change.
- `tests/llm/test_openai_provider.py`, `test_anthropic_provider.py`: port signature gains the second parameter — update existing calls; add the instructions-carry and parity tests.
- `tests/driver/test_session.py`: launch tests stay; add connect-branch tests (mocked endpoint; no real ws server — `pytest.mark.skipif` guard if any test ever wants a live endpoint).
- `tests/driver/test_page.py`: the three locator tests.
- `tests/engine/test_generator.py`: rename `GENERATION_PROMPT` → `SYSTEM_PROMPT` references; provider fakes accept/record `user_instructions`; surface mirror test.
- `tests/cache/test_budgets.py`: behavior unchanged — docstring-level expectations only; the fresh-registry-per-test semantics live in the runtime/scenario tests.
- `tests/test_integration.py`: public-surface test (PrettyConfig in, get_runtime out).

## Additional Instructions for the Implementation Agent

- Follow the implementation order: config → cache → llm → driver → engine → root; each cell's `ruff check` and its test module stay green before moving on. Final gate: `ruff check` and `pytest tests/ -x`, Python 3.10+.
- Rename the engine constant `GENERATION_PROMPT` → `SYSTEM_PROMPT` and update its text to the `system_prompt` practice **verbatim** (the two added lines: the USER INSTRUCTIONS input bullet after PAGE API, the locating-priority bullet after the role/text/label line).
- Extend `PAGE_API_SURFACE` with exactly three rows after `page.find_by_text(text)`, mirroring `driver/.usages/facade.md`: `page.find_by_attribute(name, value) — element by attribute value — data-* attributes`, `page.find_by_css(selector) — element by CSS selector`, `page.find_by_xpath(xpath) — element by XPath expression` (keep the column padding style of the constant; keep the comment tying it to `facade.md`).
- Update every per-run wording to per-test in docstrings and comments while touching the files: `budgets.py` (module and class docstrings), `session.py` ("for the whole run" → "of one test"), `page.py` (`close` docstring: "the browser of the run stays alive" → the test's browser keeps running until the runtime closes), `runtime.py`, `scenario.py`, `generator.py`, `healer.py`, `executor.py` ("the run-scoped attempt registry" → per-test). Search for "run-scoped", "per-run", "for the whole run", "the run does not fail" (the last one in `store.py` step 5 means "the test run does not fail" — a cache-save skip; leave it).
- `prettyplay/config/__init__.py` exports `PrettyConfig` alongside `Config` (`PrettyConfig = Config` defined in `models.py`); the root `__init__.py` imports and re-exports `PrettyConfig` and drops `get_runtime`.
- The empty-instructions check lives only in `build_fields_text` (single point of parity); the engine passes `self._config.generation_prompt` unconditionally.
- The connect branch reuses the `_launch` failure-cleanup wrapper — do not duplicate cleanup code per branch. The connect `Error` itself is re-raised wrapped with the endpoint named (`from failure` chaining): Playwright's raw connect message does not carry the endpoint URL.
- Keep `StepExecutor`'s and `StepHealer`'s unused `budgets`/`cache` constructor parameters with their existing `noqa` comments (contract symmetry, root/engine manifests unchanged here).
- No new dependencies; no changes to `pyproject.toml` dependencies (the ws/wss check uses stdlib `urllib.parse`).
- Docstrings follow Google style per `conventions`; every new public method gets `Args`/`Returns`/`Raises` as applicable.
