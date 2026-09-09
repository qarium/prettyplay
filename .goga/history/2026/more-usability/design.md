# Design Document: `more-usability`

The complete architectural specification for materializing the `more-usability` contract changes
(verdicts on terminal failures, failed-check classification stop, browser channels + headless,
scroll abilities, author screenshots, configuration error) into the Python implementation of
`prettyplay`.

The source of truth is the set of six changed CODEMANIFEST files (already applied to the tree and
lint-clean). This document specifies **what** to implement and **how**; the execution order is
decided by the planning stage, not here.

---

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/failures/CODEMANIFEST`: new `FailureVerdict` entity; `ProductDefectError` gains the
  `verdict` field, the `AssertionError` base and the folded-traceback requirement;
  `IncurableStepError` gains the `verdict` field, `recommendation` becomes a derived property with
  a built-in fallback; header annotations describe the verdict render contract.
- `prettyplay/reporting/CODEMANIFEST`: new `StepHooks.on_step_verdict` event fired after
  `on_step_failed`; header annotation fixes the INFO level of the verdict event.
- `prettyplay/config/CODEMANIFEST`: new `Imports` from `prettyplay/failures`
  (`PrettyplayError` + `taxonomy` usage); new `PrettyplayError::ConfigurationError` mutation;
  `Config` gains `headless: bool` and the five-value browser set; `load_config` renames the browser
  env override to `PRETTYPLAY_BROWSER_NAME`, adds `PRETTYPLAY_BROWSER_HEADLESS`, and wraps
  validation failures into `ConfigurationError`.
- `prettyplay/driver/CODEMANIFEST`: `DriverSession.open_context` launches with `headless` and the
  channel mechanism for `chrome`/`msedge` with a loud failure on a missing browser; `PageFacade`
  gains 8 scroll methods and the never-sleep scroll requirement.
- `prettyplay/engine/CODEMANIFEST`: new `classify_step_failure` routine (location
  `classification.py`); `generate` algorithm steps 6–9 (failed-check classification stop,
  exhaustion classification, quiet verdict skip); `heal` algorithm (classification through the
  shared routine, verdicts reaching the raised errors, exhaustion verdict reuse without an extra
  LLM request); `generation_prompt` scroll rule; `classification_prompt` without "cached"; the
  page API surface mirrors `facade` from Imports.
- `prettyplay/CODEMANIFEST`: `PrettyTest` gains `get_screenshot`/`save_screenshot`; `action` and
  `assertion` fold the traceback to the library boundary; `StepExecutor.execute` step 7 reports
  `on_step_verdict` between `on_step_failed` and the raise. Review fix: `PrettyplayError` added
  to Imports from `prettyplay/failures` (the facade catches it for folding and raises it for the
  screenshot no-page/write failures).

### New Entities

- `FailureVerdict(category, explanation, recommendation)` — the verdict of a terminal step
  failure; `prettyplay/failures/errors.py`.
- `PrettyplayError::ConfigurationError(message)` — the actionable invalid-configuration failure;
  `prettyplay/config/loader.py`.
- `classify_step_failure(config, provider, step_text, code, error, page) -> FailureClassification`
  — the single classification call for both engines; `prettyplay/engine/classification.py`
  (new file).
- `StepHooks.on_step_verdict(step_text, category, explanation, recommendation)` — the verdict hook
  event; `prettyplay/reporting/hooks.py`.
- `PageFacade.scroll_to_element`, `scroll_down`, `scroll_up`, `scroll_to_bottom`,
  `scroll_to_top`, `scroll_into_view`, `scroll_container_down`, `scroll_container_up` —
  `prettyplay/driver/page.py`.
- `PrettyTest.get_screenshot() -> bytes`, `PrettyTest.save_screenshot(filepath)` —
  `prettyplay/scenario.py`.
- `Config.headless: bool = True` — `prettyplay/config/models.py`.

### Changed Entities

- `ProductDefectError(step_text, message, verdict=None)` — third field; derives from both
  `PrettyplayError` and `AssertionError`; rendered message appends the verdict render.
- `IncurableStepError(step_text, reason, verdict=None)` — `recommendation` param replaced by the
  derived property (verdict recommendation with the built-in fallback); rendered message appends
  the verdict render or the fallback recommendation.
- `Config(provider, browser, …, headless)` — browser set extended to
  `{chromium, firefox, webkit, chrome, msedge}`.
- `load_config` — env override map with the two special names; validation failures wrapped into
  `ConfigurationError` with the original `ValidationError` chained; the legacy
  `PRETTYPLAY_BROWSER` variable is answered loudly.
- `DriverSession.open_context` — launch with `headless` from settings and `channel` for the
  chrome/msedge values.
- `StepGenerator.generate` / `regenerate` — failed-check classification stop, exhaustion
  classification (generation pool only), verdicts carried into the raised errors.
- `StepHealer.heal` — classification through `classify_step_failure`; every produced verdict fully
  reaches the raised error; regeneration exhaustion reuses the step-1 verdict.
- `StepExecutor.execute` — verdict event reporting in the failure branch.
- `PrettyTest.action` / `assertion` — traceback folding to the library boundary.

### Deleted Entities

- None.

### Usages and Annotations Changes

- `playwright` (project usage, driver): now covers browser channels, headless launch and the
  scroll primitives (already updated in `.goga/usages/cooks/playwright.md`).
- `pydantic` (project usage, config): now covers the five-value browser set, `headless`,
  `PRETTYPLAY_BROWSER_NAME`, the legacy-variable hint and the `ConfigurationError` wrapping
  (already updated in `.goga/usages/cooks/pydantic.md`).
- `generation_prompt` (engine inline usage): new scroll-abilities rule line.
- `classification_prompt` (engine inline usage): "a cached web UI test step" → "a web UI test
  step".
- Engine global annotations: the verdict contract lines, the failed-check stop line, and the
  page-API-surface-mirrors-`facade` line.
- Cell `.usages/` files (`taxonomy.md`, `hooks.md`, `configuration.md`, `facade.md`,
  `generation.md`, `healing.md`, `steps.md`, `lifecycle.md`) — already updated by the apply stage;
  verified consistent (see `.usages/` Update).

## Applied Fixes

### Fixed CODEMANIFEST Defects

- `prettyplay/engine/CODEMANIFEST` (Interface ↔ Type): engine builds `FailureVerdict` objects to
  raise verdict-carrying errors, but the type was absent from `Imports`. Before: failures import
  listed only the three error types → after: `FailureVerdict` added to `Imports` → `Types` from
  `prettyplay/failures`, referenced in the global annotation ("a `FailureVerdict` of category,
  explanation, recommendation") to satisfy `import_is_used`. User-approved (q1).
- `prettyplay/engine/CODEMANIFEST` (Interface ↔ Interface): `regenerate` claimed "the same loop
  with two additions", while `heal` step 6 requires a third difference — no exhaustion
  classification on the healing pool. Before: two additions → after: three additions, the third
  naming the no-classification exhaustion with the healer attaching its verdict and the
  failed-check classification applying on both pools. User-approved (q1).

### User-Approved Design Decisions (undefined by DSL)

- **D1 = (a)**: the legacy `PRETTYPLAY_BROWSER` variable, when set, raises `ConfigurationError`
  with a hint naming `PRETTYPLAY_BROWSER_NAME` — the loud option.
- **D2 = (a)**: `save_screenshot` write failures are wrapped into `PrettyplayError` naming the
  path, with the original `OSError` chained (`raise … from error`); the no-page failure of both
  screenshot methods is a `PrettyplayError` as well.
- **Traceback folding mechanism** (decided at design level): implemented in the facade methods
  `PrettyTest.action`/`assertion` — the boundary the root manifest assigns; the exception object
  is re-raised with a single-frame `TracebackType` built from the boundary frame (details in the
  algorithm section).

---

## Entity Interaction and Data Flow

### Interaction Diagram

```
                        ┌────────────────────────────────────────────────────────┐
                        │ PrettyTest (scenario.py)                               │
                        │  action/assertion ── fold traceback ──> runner         │
                        │  get_screenshot/save_screenshot ──> PageFacade          │
                        └───────────────┬────────────────────────────────────────┘
                                        │ execute(step_text, step_type, page)
                        ┌───────────────▼────────────────────────────────────────┐
                        │ StepExecutor (executor.py)                              │
                        │  hit: run_step_code | miss: generate | fail: heal       │
                        │  on failure: on_step_failed → [on_step_verdict] → raise │
                        └───────┬───────────────────────────────┬────────────────┘
                                │ generate/regenerate           │ heal
                ┌───────────────▼───────────────┐   ┌───────────▼────────────────┐
                │ StepGenerator (generator.py)  │   │ StepHealer (healer.py)     │
                │  candidate loop, budgets      │   │  classify → branch         │
                └───────┬───────────────┬───────┘   └───────┬────────────┬───────┘
                        │               │ classify_step_failure      │
                        │               ▼ (classification.py)       │ build
                        │        ┌──────────────────┐               ▼
                        │        │ LlmProvider port │      ┌──────────────────┐
                        │        │ classify_failure  │      │ FailureVerdict   │
                        │        └───────┬──────────┘      │ (failures cell)  │
                        │                ▼                 └────────┬─────────┘
                        │        FailureClassification               │ verdict
                        └────────────────────────────────────────────┘
                                     raised errors carry .verdict
                        ProductDefectError(PrettyplayError, AssertionError)
                        IncurableStepError(PrettyplayError)

  config cell ── Config(browser 5-set, headless) ──> DriverSession.launch(headless, channel)
                                              └────> PageFacade.scroll_* (8 methods)
  load_config ──ValidationError──> ConfigurationError(PrettyplayError)
  StepReporter.emit("on_step_verdict", {4 str fields}) ──> logger prettyplay + StepHooks
```

### Data Flows

**Flow 1 — failed check during generation (the new stop path)**:
`PrettyTest.assertion(text)` → `StepExecutor.execute` (cache miss) → `StepGenerator.generate` →
candidate executes via `run_step_code` → raises `AssertionError` → `classify_step_failure`
collects snapshot (+ screenshot) and calls `provider.classify_failure` → `FailureClassification`
→ engine builds `FailureVerdict(category, explanation, recommendation)` →
`product_defect` → `ProductDefectError(step_text, message, verdict)` / otherwise →
`IncurableStepError(step_text, reason, verdict)` → propagates to `execute` → `on_step_failed` →
`on_step_verdict(step_text, category, explanation, recommendation)` → raise → `PrettyTest`
folds the traceback → the runner sees a failure whose message ends with the verdict render.

**Flow 2 — healing of a failed cached step**:
cache hit → `run_step_code` fails → `StepHealer.heal` → `classify_step_failure` → verdict →
`on_healing_started` → `product_defect`: `ProductDefectError` with verdict |
`incurable`: `IncurableStepError` with verdict | `rot`: `StepGenerator.regenerate` →
success: `on_healed` + return | regeneration exhaustion (no classification inside):
`IncurableStepError` caught with `verdict is None` → re-raised carrying the step-1 verdict →
executor reporting as in Flow 1.

**Flow 3 — configuration load**:
`get_runtime()` → `load_config(None)` → find `pyproject.toml` → parse TOML → extract section →
legacy `PRETTYPLAY_BROWSER` set? → `ConfigurationError` (hint) : collect env overrides
(`PRETTYPLAY_BROWSER_NAME`, `PRETTYPLAY_BROWSER_HEADLESS`, `PRETTYPLAY_<FIELD>`) → construct
`Config` → `ValidationError` → render one line per invalid setting → `ConfigurationError`
(chained) | success → resolved `Config` (empty `cache_root` → default).

**Flow 4 — author screenshots**:
`PrettyTest.get_screenshot()` / `save_screenshot(filepath)` → no page yet →
`PrettyplayError("run a step first…")` | page exists → `PageFacade.screenshot()` → bytes
(`save`: `Path.write_bytes`; `OSError` → `PrettyplayError` chained).

**Flow 5 — browser launch with channel/headless**:
first step of the run → `PrettyplayRuntime.open_page` → `DriverSession.open_context` →
lazy `_launch` → `_launch_engine`: engine map + `channel` for chrome/msedge →
`engine.launch(headless=config.headless[, channel=…])` → missing channel browser → Playwright
`Error` naming the distribution (loud, actionable) → `PageFacade` returned.

### Entity Dependencies

Unchanged dependency graph (verified via `goga schema`); the only new edge —
`config → failures` — was added by the apply stage. Within the implementation:

- `failures` remains stdlib-only (leaf); `FailureVerdict` adds no third-party dependency.
- `config/loader.py` imports `PrettyplayError` from `..failures.errors` (mutation base) and
  `ValidationError` from pydantic.
- `engine/classification.py` imports `Config`, `PageFacade`, `LlmProvider`,
  `FailureClassification` (type hints) — same set the engine cell already imports.
- `generator.py` imports `classify_step_failure` from `.classification`; `healer.py` imports it
  too. `CLASSIFICATION_PROMPT` moves from `generator.py` to `classification.py` (owned by its
  only consumer) — this breaks what would otherwise be an import cycle
  (`classification` ← prompt ← `generator` ← routine ← `classification`).
- Initialization order is unchanged: runtime → config → (driver | provider | budgets) → per-test
  objects.

---

## Code Stack Trace

All traces verified against the current implementation files and the actual Playwright / pydantic
APIs given in the usages. Checkpoint notation: **[OK]** type/logic verified, **[DEFECT→FIXED]**
contract defect found and fixed with user approval.

### Trace: `FailureVerdict.render()`

#### Chain
1. **Input**: an instance built by an engine from a `FailureClassification`
   (`category="product_defect"`, `explanation="…"` — one short sentence,
   `recommendation="…"` — one short sentence). **[OK]** fields are plain `str`, constructor is
   the three-field entity signature.
2. **Step**: build one line per non-empty field — `f"category: {self.category}"`,
   `f"explanation: {self.explanation}"`, `f"recommendation: {self.recommendation}"`; an empty
   field yields no line. **[OK]** labels are stable lowercase words — integrators parse them
   (requirement).
3. **Step**: join the lines with `"\n"` → `text: str`. **[OK]** str return matches
   `-> text: str`.
4. **Output**: the rendered verdict consumed by (a) the exception message tail via `__str__`,
   (b) the log/hook payload content. **[OK]** single render, three consumers — the message-tail
   use is literal; the hook/log carry the same three fields as separate strings (identical
   content, uniform payloads per the reporting contract).

#### Checkpoint Summary
- Field types `str × 3` ↔ `FailureClassification` fields `str × 3`: passed (1:1 mapping).
- "one line per **non-empty** field" ↔ engines may receive empty strings from the LLM line
  format: passed (render degrades gracefully).

### Trace: `ProductDefectError.__init__` / `__str__`

#### Chain
1. **Input**: raised by `StepHealer.heal` (step 3) or `StepGenerator.generate` (step 6) —
   `ProductDefectError(step_text: str, message: str, verdict: FailureVerdict | None)`.
   **[OK]** the engines import both types (`FailureVerdict` import fixed — **[DEFECT→FIXED]**).
2. **Step**: MRO — `class ProductDefectError(PrettyplayError, AssertionError)`; bases resolve
   (both derive from `Exception`, no layout conflict). **[OK]** catchable as
   `except PrettyplayError` and as `except AssertionError`; unittest counts it as a failure, not
   an error (requirement).
3. **Step**: `PrettyplayError.__init__(message)` stores `.message` and `args=(message,)`;
   `__init__` stores `.step_text`, `.verdict`. `verdict` defaults to `None` — the explicit
   absence when the LLM was unavailable. **[OK]** `message` stays the primary reason in `args`.
4. **Step**: `__str__` renders `message` first, then appends `"\n" + verdict.render()` when
   `verdict` is present. **[OK]** "starts with `message`; the `verdict` render is appended, never
   interleaved" (header annotation).
5. **Output**: the string a runner prints; the traceback seen by the runner is folded at
   `PrettyTest.action/assertion` (trace below) — the folding requirement on this type is
   satisfied through the facade boundary. **[OK]** the type itself performs the runner alignment
   (AssertionError base), no runner plugin involved (constraint).

#### Checkpoint Summary
- Base-class diamond `PrettyplayError` + `AssertionError`: passed.
- `verdict: FailureVerdict | None` ↔ constructor call sites (heal step 3, generate step 6/8
  alternatives): passed.

### Trace: `IncurableStepError.__init__` / `recommendation` / `__str__`

#### Chain
1. **Input**: raised by `generate` steps 6/8 (generation pool), by the shared loop on the healing
   pool (without verdict), and by `heal` steps 4/6 (with verdict) —
   `IncurableStepError(step_text: str, reason: str, verdict: FailureVerdict | None = None)`.
   **[OK]**.
2. **Step**: `class IncurableStepError(PrettyplayError)` — derives from `PrettyplayError` only,
   never from `AssertionError` (requirement: an execution failure, not a failed check). **[OK]**.
3. **Step**: `recommendation` is a derived `@property`: `self.verdict.recommendation` when the
   verdict is present, otherwise the built-in path guidance
   `"reword the step or refresh the cache"` (matches the taxonomy reaction column). **[OK]** the
   recommendation is carried by `verdict`; the fallback keeps the message actionable without one.
4. **Step**: `__str__` renders `reason`, then `"\n" + verdict.render()` when present, otherwise
   `"\nrecommendation: <fallback>"`. **[OK]** "starts with `reason`, then appends the verdict
   render; the fallback recommendation keeps the message actionable".
5. **Output**: same consumers as `ProductDefectError`. **[OK]**.

#### Checkpoint Summary
- Old positional signature `(step_text, reason, recommendation)` → new `(step_text, reason,
  verdict)`: a legacy third positional argument would now land in `verdict` and fail at render
  time — acceptable: these errors are raised by the library, not constructed by integrators
  (documented in Additional Instructions).

### Trace: `load_config`

#### Chain
1. **Input**: `get_runtime()` calls `load_config(None)`; integrators may pass an explicit path.
   **[OK]** signature unchanged.
2. **Step**: resolve the pyproject path (given or first match upward) — existing
   `_find_pyproject`. **[OK]** `FileNotFoundError` behavior retained (out of the new contract,
   unchanged).
3. **Step**: parse TOML (`tomllib` / `tomli` on 3.10 — pydantic usage) → extract
   `tool.prettyplay` (missing → `{}`). **[OK]**.
4. **Step**: legacy check — if `"PRETTYPLAY_BROWSER"` is set in the environment, raise
   `ConfigurationError("PRETTYPLAY_BROWSER is no longer supported: use PRETTYPLAY_BROWSER_NAME")`
   **before** merging (D1=(a), user-approved). **[OK]** loud, actionable, names both variables.
5. **Step**: collect env overrides from the per-field name map — `browser →
   PRETTYPLAY_BROWSER_NAME`, `headless → PRETTYPLAY_BROWSER_HEADLESS`, every other field →
   `PRETTYPLAY_<FIELD_UPPERCASE>`; a variable that is set wins (empty string included).
   **[OK]** "an env override exists for every setting"; bool strings (`"false"`, `"0"`, `"true"`)
   are coerced by pydantic lax mode at the next step.
6. **Step**: construct `Config(**merged)`. On `ValidationError` — render one line per invalid
   setting from `error.errors()`: `f"{field}: received {input!r} — allowed: {allowed}"`, the
   allowed text from a static map (provider → `openai, anthropic`; browser → `chromium, firefox,
   webkit, chrome, msedge`; attempts → `a positive integer`; headless → `a boolean`; fallback →
   the pydantic message), join with `"\n"`, raise `ConfigurationError(rendered)` chained
   `from error`. **[OK]** "a raw pydantic.ValidationError never leaves the loader"; one line per
   invalid setting; no pydantic internals in the user-visible text (pydantic usage).
7. **Step**: empty `cache_root` → absolute `<pyproject_dir>/.prettyplay/cache`. **[OK]**
   unchanged.
8. **Output**: fully resolved `Config` or `ConfigurationError` (derives from `PrettyplayError` —
   one library except clause; never carries a verdict — it is not a step failure). **[OK]**.

#### Checkpoint Summary
- `ConfigurationError` base `PrettyplayError` ↔ failures import in config manifest: passed.
- Env-name map ↔ manifest step 4 (two special names): passed.
- `Config(**merged)` field set ↔ new `headless` field and the five-value browser `Literal`:
  passed (pydantic validates both the enum and the bool coercion).

### Trace: `DriverSession.open_context` (launch part)

#### Chain
1. **Input**: first step of the run → `PrettyplayRuntime.open_page()` → `open_context()`; the
   session holds the validated `Config`. **[OK]** lazy launch unchanged.
2. **Step**: `_launch()` — start the worker thread, start Playwright inside it, launch the
   engine inside it; on failure stop and close everything so a retry starts clean (existing).
   **[OK]**.
3. **Step**: `_launch_engine(playwright)` — engine map
   `{"chromium": p.chromium, "firefox": p.firefox, "webkit": p.webkit}`; for
   `browser in ("chrome", "msedge")` the engine is `p.chromium` and `channel=browser` is passed;
   `launch(headless=self._config.headless, channel=…)` — exactly the pattern of the playwright
   usage. **[OK]** type flow: `config.headless: bool` → `launch(headless: bool)`; channel value
   is one of the two literals.
4. **Step**: a channel launch without the installed browser — Playwright raises
   `playwright.sync_api.Error` naming the distribution and the remedy
   (`playwright install chrome`). Design decision: propagate as-is; the native message already
   names the missing browser and the action. **[OK]** "fails loudly with an actionable message
   naming the missing browser"; no new failure kind invented in the driver cell.
5. **Step**: fresh isolated `browser.new_context()` + `context.new_page()` in the worker thread →
   wrapped into `PageFacade`. **[OK]** unchanged isolation.

#### Checkpoint Summary
- `headless`/`channel` kwargs ↔ Playwright `BrowserType.launch` signature: passed.
- Bundled engines launch with `headless` only (no `channel` kwarg): passed — matches the
  usage example (`channel=name if name in ("chrome", "msedge") else None`).

### Trace: `PageFacade` scroll methods (8)

#### Chain
1. **Input**: called from generated step code (`page.scroll_down(600)`), from hand-written step
   code, or from `scroll_into_view` with two `LocatorFacade` handles. **[OK]** params use
   `LocatorFacade` — declared in the same cell; no raw Playwright object crosses the boundary.
2. **Step**: every method marshals its Playwright work through `self._call(...)` into the driver
   thread of the owning session (existing pattern). **[OK]** "every Playwright call runs in the
   driver thread, strictly one at a time".
3. **Step**: primitive mapping (from the playwright usage "Scrolling" section):
   - `scroll_to_element(element)` → `element._locator.scroll_into_view_if_needed()` — brings
     the element into view inside its **nearest scrollable ancestor** (native behavior).
   - `scroll_down(pixels)` / `scroll_up(pixels)` → `self._page.mouse.wheel(0, pixels)` /
     `wheel(0, -pixels)`.
   - `scroll_to_bottom()` → `self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")`;
     `scroll_to_top()` → `evaluate("window.scrollTo(0, 0)")`.
   - `scroll_into_view(element, container)` → resolve the target first:
     `handle = element locator .element_handle()` (auto-waits for the element), then one
     `container` evaluation computing the target offset inside the specific container and
     adjusting `scrollTop` (centers the target):
     `container.evaluate("(el, target) => { const cr = el.getBoundingClientRect(); const tr =
     target.getBoundingClientRect(); el.scrollTop += tr.top - cr.top - (el.clientHeight -
     tr.height) / 2; }", handle)` — the `ElementHandle` is passed as the evaluate argument; it
     is a `JSHandle` subclass and serializes as a live handle (a raw `Locator` argument
     serializes as `undefined` in playwright-python and is not usable).
   - `scroll_container_down/up(container, pixels)` →
     `container.evaluate("(el, px) => { el.scrollTop += px; }", pixels)` /
     `el.scrollTop -= px`.
   **[OK]** each primitive is the documented Playwright API; `ElementHandle`-as-argument
   (a `JSHandle` subclass) is the serializable form — the target locator is resolved via
   `element_handle()` with auto-wait.
4. **Step**: no sleeps anywhere — the scrolled state is awaited by the follow-up locators and
   expectations of the step code. **[OK]** "scroll methods never sleep" requirement; the
   generated prompt carries the same rule.
5. **Output**: page/container scroll state changed; nothing returned. **[OK]**.

#### Checkpoint Summary
- 8 signatures ↔ facade.md surface rows (21 rows total): passed — names and arities identical.
- `pixels: int` documented positive; no validation mandated by the contract (a negative amount
  simply scrolls the other way): passed, documented as a non-constraint.

### Trace: `classify_step_failure`

#### Chain
1. **Input**: called by `StepGenerator` (steps 6/8) and `StepHealer` (step 1) —
   `(config, provider, step_text, code, error, page)`. **[OK]** all types imported by the engine
   cell (`Config`, `LlmProvider`, `PageFacade`, and `FailureClassification` for the return).
2. **Step**: collect inputs — `snapshot = page.aria_snapshot()`;
   `screenshot = page.screenshot() if config.send_screenshots else None`. **[OK]** the same
   collection the healer performs inline today; the screenshot flag is the only config input.
3. **Step**: `classification = provider.classify_failure(prompt=CLASSIFICATION_PROMPT,
   step_text=…, code=…, error=…, snapshot=…, screenshot=…)`. **[OK]** keyword signature matches
   the `LlmProvider.classify_failure` port exactly (verified in `llm/provider.py`);
   `CLASSIFICATION_PROMPT` (without "cached") is the system prompt — manifest inline usage.
4. **Step**: return `classification`. **[OK]** `-> classification: FailureClassification`.
5. **Output**: the verdict model to the caller. Provider unavailability (`LlmUnavailableError`)
   propagates untouched — the constraint "this routine never swallows it" — the calling path
   decides (quiet skip in the generator, infrastructure failure in the healer). **[OK]**.

#### Checkpoint Summary
- Module placement `classification.py` + prompt relocation from `generator.py`: passed — breaks
  the would-be import cycle (see Entity Dependencies).
- Port signature ↔ call kwargs: passed.

### Trace: `StepGenerator.generate` (loop steps 1–9)

#### Chain
1. **Input**: `execute` on a cache miss — `(identity, step_text, previous_steps, page)`.
   **[OK]**.
2. **Step**: `budgets.try_generation(identity)` — refused → exhaustion branch (step 8 of the
   manifest): with **no** recorded candidate failure (the run already spent this step's budget in
   an earlier test) raise `IncurableStepError(step_text, f"generation attempt budget exhausted")`
   with `verdict=None` — there is no candidate to classify; with a recorded last failure →
   classify via `classify_step_failure` (see step 4 below for the LLM-unavailable sub-case) and
   raise `IncurableStepError` with
   `reason=f"generation attempt budget exhausted; last failure: {error}"` carrying the verdict.
   **[OK]** reason names the exhausted pool and the last candidate failure.
3. **Step**: per attempt — `emit("on_generation_started", {step_text, attempt})`; snapshot;
   screenshot when enabled; `code = provider.generate_step_code(prompt=GENERATION_PROMPT, …,
   page_api=PAGE_API_SURFACE, existing_code, error)`; execute via `run_step_code(code, page)`.
   **[OK]** `LlmUnavailableError` from the provider propagates immediately (requirement — no
   retry on it); `PAGE_API_SURFACE` now includes the 8 scroll lines in facade.md order.
4. **Step**: candidate failure classification (manifest step 6) —
   `except AssertionError as check_failure:` stop the retries **immediately** (the attempt budget
   is never spent on a legitimately failing assertion); `reason = f"candidate check failed:
   {first_line_short(check_failure)}"`; try `classify_step_failure(config, provider, step_text,
   code, reason, page)`:
   - verdict `product_defect` → `raise ProductDefectError(step_text,
     first_line_short(check_failure), verdict)` — the message states what was expected against
     what was observed (the check text is that statement);
   - any other verdict → `raise IncurableStepError(step_text, reason, verdict)`;
   - `LlmUnavailableError` from the classification → `logging.getLogger("prettyplay").warning(
     "verdict skipped: llm unavailable", extra={…})` → `raise IncurableStepError(step_text,
     reason, verdict=None)` — the failed check is the primary signal, the verdict is enrichment.
   **[OK]** every sub-branch of manifest step 6; the WARNING satisfies the reporting header
   (quiet skip logged).
   **[DEFECT→FIXED]** the branch requires constructing `FailureVerdict` — the missing import was
   fixed (Applied Fixes).
5. **Step**: any other candidate failure (element not found, timeout) → `existing_code = code`;
   `error = first_line_short(candidate_error)`; repeat from step 2 while attempts remain
   (manifest step 7). **[OK]**.
6. **Step**: success → `CachedStep(identity, code, created_at)` → `cache.save(step)` → return.
   **[OK]** unchanged.
7. **Output**: a proven `CachedStep`, or one of the three terminal errors (two of them
   verdict-carrying). **[OK]** "a verdict requested on this path fully reaches the raised error"
   — the verdict object flows into the exception constructor unchanged.

#### Checkpoint Summary
- `AssertionError` detection ↔ `LocatorFacade.expect_*` raising assertion-style errors through
  Playwright `expect` (driver requirement): passed — the failed check is detectable by type.
- Quiet-skip WARNING ↔ logger name `prettyplay` (reporting contract): passed.
- First-refusal-without-candidate edge: passed (documented; no classification inputs exist).

### Trace: `StepGenerator.regenerate` (three additions)

#### Chain
1. **Input**: `StepHealer.heal` rot branch — `(identity, step_text, previous_steps, page,
   existing_code, error)`. **[OK]**.
2. **Step**: the same loop with **three** additions (amended annotation, user-approved):
   (1) every provider request carries `existing_code` and `error`; (2) attempts consume
   `budgets.try_healing`; (3) a budget exhaustion raises `IncurableStepError` **without
   classification** — `reason=f"healing attempt budget exhausted; last failure: {error}"`,
   `verdict=None` — the healer attaches the verdict of its own classification; no extra LLM
   request is made. The failed-check classification (manifest step 6) applies on both pools: a
   candidate check that executed and did not hold during regeneration classifies and raises
   `ProductDefectError`/`IncurableStepError` carrying the fresh verdict. **[OK]** consistent with
   `heal` steps 5–6 and the anti-masking requirement (a product defect found mid-regeneration
   still fails loudly).
3. **Output**: a healed `CachedStep` (saved by the loop), or an error as above.
   **[OK]**.

#### Checkpoint Summary
- Pool-dependent exhaustion ↔ heal step 6: passed after the annotation fix (**[DEFECT→FIXED]**).

### Trace: `StepHealer.heal`

#### Chain
1. **Input**: `execute` on a failed cache hit — `(step, error, previous_steps, page)`;
   `step_text = step.identity.normalized_text`. **[OK]**.
2. **Step**: `classification = classify_step_failure(config, provider, step_text, step.code,
   error, page)`; wrap into `verdict = FailureVerdict(classification.category,
   classification.explanation, classification.recommendation)`. `LlmUnavailableError` from the
   classification propagates — manifest step 7: an explicit infrastructure failure. **[OK]**.
3. **Step**: `emit("on_healing_started", {step_text, category})`. **[OK]** unchanged.
4. **Step**: `product_defect` → `raise ProductDefectError(step_text, classification.explanation,
   verdict)` — the message states what was expected against what was observed (the classifier
   saw the page at the failure moment); the recommendation reaches the error through the
   verdict. `incurable` → `raise IncurableStepError(step_text, classification.explanation,
   verdict)` — the reason names the classification explanation of incurability. **[OK]** steps
   3–4.
5. **Step**: `rot` → `healed = generator.regenerate(…)` inside
   `try: … except IncurableStepError as incurable:` — if `incurable.verdict is None`
   (regeneration exhaustion): `raise IncurableStepError(step_text, incurable.reason, verdict)
   from incurable` (the step-1 verdict, reason already names the exhausted pool); else re-raise
   as-is (a fresh failed-check verdict is never overwritten). On success:
   `emit("on_healed", {step_text, explanation})`, return `healed`. **[OK]** steps 5–6; "every
   verdict produced on the paths of this method fully reaches the raised error" holds on all
   four exit paths (product_defect, incurable, exhaustion-reuse, failed-check passthrough).
6. **Output**: the healed step or a verdict-carrying terminal error. **[OK]**.

#### Checkpoint Summary
- Verdict reuse without an extra LLM request: passed — `classify_step_failure` is called exactly
  once per `heal` invocation (assertable in tests via the fake provider call count).
- `raise … from incurable` chaining: the folded traceback hides it at the facade; debugging
  retains it. Passed.

### Trace: `StepReporter.emit("on_step_verdict", payload)` → `StepHooks.on_step_verdict`

#### Chain
1. **Input**: `execute` failure branch passes
   `{"step_text": str, "category": str, "explanation": str, "recommendation": str}`.
   **[OK]** payload values are plain strings — uniform with the other events.
2. **Step**: level — the event is not in `_WARNING_EVENTS` → INFO. **[OK]** header annotation:
   step lifecycle events including the verdict event are INFO.
3. **Step**: log record — event name as the message, payload fields as contextual `extra`
   (reserved-name keys prefixed `ctx_`). **[OK]** existing mechanism, no change needed.
4. **Step**: hook fan-out — `getattr(hook, "on_step_verdict")(**payload)` per hook in
   registration order; a raising hook is logged WARNING and skipped. **[OK]** base
   `StepHooks.on_step_verdict` is a no-op docstring method — override only what you need.
5. **Output**: log line + synchronous hook reactions. **[OK]** "not fired when the verdict was
   skipped" — the event is emitted by the executor only when `verdict is not None`.

#### Checkpoint Summary
- Event name ↔ hook method name equality (emit contract): passed.

### Trace: `StepExecutor.execute` (failure branch, manifest step 7)

#### Chain
1. **Input**: an exception escaping the try body (cached execution failure propagated through
   `heal`, generation failure from `generate`, or an unexpected error). **[OK]**.
2. **Step**: `emit("on_step_failed", {step_text, step_type, error: first_line_short(error)})`.
   **[OK]** unchanged.
3. **Step**: `if isinstance(error, (ProductDefectError, IncurableStepError)) and error.verdict
   is not None:` → `emit("on_step_verdict", {step_text, verdict.category, verdict.explanation,
   verdict.recommendation})`. **[OK]** "when the terminal failure carries a verdict" — only
   these two types carry one (`LlmUnavailableError` and `ConfigurationError` never do); both
   types are imported by the root cell; ordering after `on_step_failed` and before the raise
   matches the reporting contract.
4. **Step**: `raise` — the original exception object re-raised untouched. **[OK]** the verdict
   still reaches the runner through the exception itself.
5. **Output**: the terminal failure propagates to `PrettyTest.action/assertion`. **[OK]**.

#### Checkpoint Summary
- Type flow `verdict.category/explanation/recommendation: str` ↔ hook payload `str`: passed.

### Trace: `PrettyTest.action` / `PrettyTest.assertion` (traceback folding)

#### Chain
1. **Input**: the engineer's step sentence; `self._ensure_page()` opens the test page lazily.
   **[OK]** unchanged.
2. **Step**: call `self._executor.execute(text, "action"|"assertion", page)` inside
   `try: … except PrettyplayError as error:` — all three terminal kinds are caught (the verdict
   carries, the infrastructure failure and any other library failure fold identically).
   **[OK]**.
3. **Step**: fold — the traceback chain head at this point is the facade method's own frame;
   deeper links are the internal library frames (executor → engine → provider / step code).
   Build a single-frame
   `types.TracebackType(tb_next=None, tb_frame=tb.tb_frame, tb_lasti=tb.tb_lasti,
   tb_lineno=tb.tb_lineno)` from the head link (the only four parameters the constructor
   accepts; `filename`/`name` derive from the frame automatically) and
   `raise error.with_traceback(folded)`. As the exception propagates out of the facade call, the
   interpreter prepends the raise-line entry of the facade method and then the test frame — the
   runner shows: test frame → the boundary frame of `PrettyTest.action/assertion` (scenario.py —
   the raise line and the executor call line, both at the boundary) → the rendered message with
   the verdict tail; internal library frames never appear.
   **[OK]** "internal library frames — engine, healing, provider — do not appear in what the
   runner shows"; the mechanism uses the writable-`tb`-free path (a fresh `TracebackType`
   instance — no mutation of shared traceback objects); re-raising the **same** exception object
   adds no `__context__` nesting (verified: `__context__` stays None).
4. **Output**: the terminal failure with the folded traceback. **[OK]** works identically for
   `ProductDefectError` (an `AssertionError` in any runner), `IncurableStepError` and
   `LlmUnavailableError`.

#### Checkpoint Summary
- Fold scope ↔ failures manifest requirement ("the traceback a runner sees starts at the library
  boundary"): passed — the boundary is the facade method.
- Non-library exceptions (e.g. a hook's own bug outside the library, or `KeyboardInterrupt`)
  pass through the `except PrettyplayError` filter untouched: passed.

### Trace: `PrettyTest.get_screenshot` / `save_screenshot`

#### Chain
1. **Input**: author call after (or, negatively, before) the first step;
   `save_screenshot(filepath)`. **[OK]** no default directory imposed.
2. **Step**: `if self._page is None:` → `raise PrettyplayError("no test page yet: run a step
   first — the page opens lazily on the first step")` — loud, actionable, catchable with the
   single library except clause (D2=(a), user-approved). **[OK]**.
3. **Step**: `image = self._page.screenshot()` — the facade full-page PNG (`bytes`);
   `get_screenshot` returns it. **[OK]** "uniform with the facade screenshot"; root cell
   imports `PageFacade`.
4. **Step**: `save_screenshot` — `try: Path(filepath).write_bytes(image)` `except OSError as
   error: raise PrettyplayError(f"cannot write the screenshot to {filepath}: {error}") from
   error`. Parent directories are **not** created — nothing is created silently; a missing
   directory surfaces loudly naming the path with the original `OSError` chained. **[OK]** D2=(a).
5. **Output**: PNG bytes / a written file. **[OK]** no screenshot is taken automatically on step
   failures — the decision belongs to the author (no changes to the failure paths).

#### Checkpoint Summary
- `PageFacade.screenshot() -> bytes` ↔ both methods: passed.
- `PrettyplayError` availability at root: passed — added to the root manifest Imports from
  `prettyplay/failures` during review (the facade catches it in `action/assertion` folding and
  raises it for the no-page and write-failure cases); referenced in the action/assertion and
  screenshot annotations; `goga lint` clean.

---

## Algorithm Design

### `FailureVerdict`

**Responsibility**: the LLM-agnostic transport of a terminal-failure verdict inside exceptions;
built by the engines, never requested by the failure types themselves.

**Algorithm:**
```
construct(category: str, explanation: str, recommendation: str):
1. store the three fields — immutable value object (@dataclass(frozen=True))
render():
1. lines = []
2. IF category is non-empty: lines += ["category: " + category]
3. IF explanation is non-empty: lines += ["explanation: " + explanation]
4. IF recommendation is non-empty: lines += ["recommendation: " + recommendation]
5. RETURN lines joined with "\n"
```

**Errors**: none — a pure value object.

**Edge Cases**:
- An empty field → no line (the LLM single-line format may yield empty segments).
- **Design decision**: a frozen stdlib dataclass, not a pydantic model. Rationale: the failures
  cell is the leaf every other cell imports and is stdlib-only today; the verdict is an
  exception-transport value object (no schema validation semantics — the port model
  `FailureClassification` already validated the source data); pydantic models inside exception
  payloads add construction cost on failure paths. The conventions' pydantic rule targets data
  models / request-response schemas; this is a conscious, documented deviation.

### `ProductDefectError`

**Responsibility**: a legitimately failed expectation — the signal the suite exists for.

**Algorithm:**
```
construct(step_text: str, message: str, verdict: FailureVerdict | None = None):
1. bases: (PrettyplayError, AssertionError)
2. PrettyplayError.__init__(message) — args carry the primary reason only
3. store step_text, message, verdict
__str__():
1. text = message
2. IF verdict is not None: text += "\n" + verdict.render()
3. RETURN text
```

**Errors**: is itself an error; no internal handling.

**Edge Cases**:
- `verdict=None` (LLM unavailable) → the message stays the expectation-vs-observation statement.
- Caught by `except AssertionError` in runners → reported as a failure, not an error.

### `IncurableStepError`

**Responsibility**: regeneration cannot produce working code.

**Algorithm:**
```
construct(step_text: str, reason: str, verdict: FailureVerdict | None = None):
1. bases: (PrettyplayError,) — never AssertionError
2. PrettyplayError.__init__(reason)
3. store step_text, reason, verdict
recommendation (property):
1. IF verdict is not None: RETURN verdict.recommendation
2. RETURN "reword the step or refresh the cache"   # the built-in path guidance
__str__():
1. text = reason
2. IF verdict is not None: text += "\n" + verdict.render()
   ELSE: text += "\nrecommendation: " + <built-in path guidance>
3. RETURN text
```

**Errors**: is itself an error; no internal handling.

**Edge Cases**:
- The fallback keeps the message actionable when the verdict was skipped.

### `ConfigurationError`

**Responsibility**: the loaded `[tool.prettyplay]` section failed validation.

**Algorithm:**
```
construct(message: str):
1. bases: (PrettyplayError,) — defined in loader.py, mutating the imported base
2. PrettyplayError.__init__(message)
3. .message exposes the rendered actionable text (inherited)
```

**Errors**: raised by `load_config` with the original `ValidationError` chained (`__cause__`).

**Edge Cases**: never carries a verdict — a configuration failure is not a step failure.

### `load_config`

**Responsibility**: file + env → validated `Config`, loud on invalid input.

**Algorithm:**
```
load_config(pyproject_path: str | None) -> Config:
1. path = explicit or _find_pyproject()                       # unchanged
2. data = tomllib.load(path)                                  # unchanged
3. section = data["tool"]["prettyplay"] or {}                 # unchanged
4. IF "PRETTYPLAY_BROWSER" in os.environ:
     RAISE ConfigurationError("PRETTYPLAY_BROWSER is no longer supported: "
                              "use PRETTYPLAY_BROWSER_NAME")  # D1=(a)
5. overrides = {field: env[f"{ENV_NAME[field]}"] for each set variable}
     ENV_NAME: browser -> PRETTYPLAY_BROWSER_NAME
               headless -> PRETTYPLAY_BROWSER_HEADLESS
               otherwise -> "PRETTYPLAY_" + field.upper()
6. merged = {**section, **overrides}
7. IF not merged["cache_root"]: merged["cache_root"] = <pyproject_dir>/.prettyplay/cache
8. TRY: RETURN Config(**merged)
   EXCEPT ValidationError as error:
     RAISE ConfigurationError(_render_validation(error)) FROM error

_render_validation(error) -> str:
1. FOR each entry in error.errors():
     line = f"{field}: received {input!r} — allowed: {ALLOWED.get(field, entry.msg)}"
   ALLOWED: provider -> "openai, anthropic"; browser -> "chromium, firefox, webkit, chrome,
   msedge"; generation_attempts / healing_attempts -> "a positive integer";
   headless -> "a boolean"; model/generation_model/… -> "a non-empty string" (fallback: msg)
2. RETURN lines joined with "\n"        # one line per invalid setting
```

**Errors**: `FileNotFoundError` (no pyproject found — unchanged), `ConfigurationError`
(invalid settings; legacy variable). `ValidationError` never escapes.

**Edge Cases**:
- Env `PRETTYPLAY_BROWSER_HEADLESS=false|0|true|1` — pydantic lax bool coercion; any other
  string fails validation and lands in the rendered lines ("headless: received 'maybe' —
  allowed: a boolean").
- Multiple invalid settings → multiple lines, one per setting, in pydantic's report order.

### `Config`

**Responsibility**: the validated settings model.

**Algorithm:**
```
fields: browser: Literal["chromium", "firefox", "webkit", "chrome", "msedge"] = "chromium"
        headless: bool = True
        (all other fields unchanged; kw_only, empty defaults, PositiveInt attempts)
```

**Errors**: `ValidationError` on construction (wrapped by the loader).

**Edge Cases**: `chrome`/`msedge` are valid settings whose launch semantics live in the driver.

### `DriverSession._launch_engine`

**Responsibility**: launch the configured browser engine inside the worker thread.

**Algorithm:**
```
_launch_engine(playwright) -> Browser:
1. name = config.browser
2. IF name in ("chrome", "msedge"): engine = playwright.chromium; channel = name
   ELSE: engine = ENGINES[name]; channel = None        # ENGINES = {chromium, firefox, webkit}
3. IF channel: RETURN engine.launch(headless=config.headless, channel=channel)
   ELSE: RETURN engine.launch(headless=config.headless)
```

**Errors**: Playwright `Error` propagates (a missing channel browser's native message names the
distribution and the `playwright install <name>` remedy) — loud and actionable by itself; the
failed-launch cleanup of `_launch` (stop driver, close thread) applies unchanged.

**Edge Cases**: retry after a failed launch starts from a clean state (existing behavior).

### `PageFacade` scroll methods

**Responsibility**: explicit programmatic scrolling for scenario steps.

**Algorithm:**
```
scroll_to_element(element):        element locator .scroll_into_view_if_needed()
scroll_down(pixels):               page.mouse.wheel(0, pixels)
scroll_up(pixels):                 page.mouse.wheel(0, -pixels)
scroll_to_bottom():                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
scroll_to_top():                   page.evaluate("window.scrollTo(0, 0)")
scroll_into_view(element, container):
                                   handle = element locator .element_handle()   # auto-wait
                                   container.evaluate("(el, target) => {
                                       const cr = el.getBoundingClientRect();
                                       const tr = target.getBoundingClientRect();
                                       el.scrollTop += tr.top - cr.top
                                                     - (el.clientHeight - tr.height) / 2;
                                   }", handle)
scroll_container_down(container, pixels):
                                   container.evaluate("(el, px) => { el.scrollTop += px; }", pixels)
scroll_container_up(container, pixels):
                                   container.evaluate("(el, px) => { el.scrollTop -= px; }", pixels)
— every call marshalled through self._call (driver thread); no sleeps anywhere
```

**Errors**: Playwright errors propagate as-is (element not found after auto-wait, etc.) — the
same behavior as the locating methods.

**Edge Cases**: a target taller than the container centers as far as the scroll range allows
(clamped by the browser); no error.

### `classify_step_failure`

**Responsibility**: the single classification call for both engines.

**Algorithm:**
```
classify_step_failure(config, provider, step_text, code, error, page) -> FailureClassification:
1. snapshot = page.aria_snapshot()
2. screenshot = page.screenshot() IF config.send_screenshots ELSE None
3. RETURN provider.classify_failure(prompt=CLASSIFICATION_PROMPT, step_text=step_text,
                                    code=code, error=error, snapshot=snapshot,
                                    screenshot=screenshot)
```

**Errors**: `LlmUnavailableError` propagates — the caller decides (quiet skip or infrastructure
failure).

**Edge Cases**: none — input collection mirrors the healer's current inline code exactly.

### `StepGenerator._loop` (generate / regenerate)

**Responsibility**: produce working step code, executing candidates against the live page.

**Algorithm:**
```
_loop(identity, step_text, previous_steps, page, pool, existing_code, error) -> CachedStep:
1. spend = try_generation IF pool == "generation" ELSE try_healing
2. LOOP:
   a. IF NOT spend(identity):                                   # budget exhausted
        reason = f"{pool} attempt budget exhausted"
        IF error: reason += f"; last failure: {error}"
        IF pool == "healing": RAISE IncurableStepError(step_text, reason, None)
                              # the healer attaches its verdict — no extra LLM request
        IF error is None: RAISE IncurableStepError(step_text, reason, None)
                              # nothing to classify — the run already spent this step's budget
        TRY:   verdict = _verdict(classify_step_failure(config, provider, step_text,
                                                         last_code, error, page))
        EXCEPT LlmUnavailableError:
               LOG warning "verdict skipped: llm unavailable" (logger prettyplay)
               RAISE IncurableStepError(step_text, reason, None)
        RAISE IncurableStepError(step_text, reason, verdict)
   b. attempt += 1; emit on_generation_started(step_text, attempt)
   c. snapshot = page.aria_snapshot(); screenshot IF enabled
   d. code = provider.generate_step_code(prompt=GENERATION_PROMPT, step_text,
        previous_steps, snapshot, screenshot, page_api=PAGE_API_SURFACE,
        existing_code, error)                                   # LlmUnavailable propagates
   e. TRY run_step_code(code, page)
      EXCEPT AssertionError AS check_failure:                   # failed check — stop retries
        reason = f"candidate check failed: {first_line_short(check_failure)}"
        TRY:   verdict = _verdict(classify_step_failure(config, provider, step_text,
                                                        code, reason, page))
        EXCEPT LlmUnavailableError:
               LOG warning "verdict skipped: llm unavailable"
               RAISE IncurableStepError(step_text, reason, None)
        IF verdict.category == "product_defect":
               RAISE ProductDefectError(step_text, first_line_short(check_failure), verdict)
        RAISE IncurableStepError(step_text, reason, verdict)
      EXCEPT Exception AS candidate_error:                      # retryable
        existing_code = code; error = first_line_short(candidate_error); CONTINUE
      ELSE: BREAK
3. step = CachedStep(identity, code, date.today().isoformat()); cache.save(step); RETURN step

_verdict(classification) -> FailureVerdict:
    RETURN FailureVerdict(classification.category, classification.explanation,
                          classification.recommendation)
```

**Errors**: `LlmUnavailableError` (generation request — immediate; classification request —
converted per the quiet-skip branches), `ProductDefectError` / `IncurableStepError` (terminal,
verdict-carrying where a verdict exists).

**Edge Cases**:
- First-refusal exhaustion (budget spent by an earlier test of the run) → no classification
  inputs exist; the error names the exhausted pool only.
- One failed check consumes exactly one attempt and stops the loop — the budget is never spent
  on a legitimately failing assertion.

### `StepHealer.heal`

**Responsibility**: classify a failed cached step, regenerate rot, never mask a defect.

**Algorithm:**
```
heal(step, error, previous_steps, page) -> CachedStep:
1. step_text = step.identity.normalized_text
2. classification = classify_step_failure(config, provider, step_text, step.code, error, page)
   # LlmUnavailableError propagates — explicit infrastructure failure (step 7)
3. verdict = FailureVerdict(classification.category, classification.explanation,
                            classification.recommendation)
4. emit on_healing_started(step_text, classification.category)
5. IF category == "product_defect":
     RAISE ProductDefectError(step_text, classification.explanation, verdict)
   IF category == "incurable":
     RAISE IncurableStepError(step_text, classification.explanation, verdict)
6. TRY:   healed = generator.regenerate(identity, step_text, previous_steps, page,
                                        step.code, error)
   EXCEPT IncurableStepError AS incurable:
     IF incurable.verdict is None:                              # regeneration exhaustion
        RAISE IncurableStepError(step_text, incurable.reason, verdict) FROM incurable
     RAISE                                                      # fresh failed-check verdict wins
7. emit on_healed(step_text, classification.explanation); RETURN healed
```

**Errors**: three terminal kinds, all verdict-carrying where produced; anti-masking holds (a
classified product defect always fails the test; the healed code replaces the cache only after a
successful execution — the generator saves only proven candidates).

**Edge Cases**:
- `classify_step_failure` is called exactly once per `heal` — the exhaustion reuse introduces no
  second LLM request.

### `StepHooks.on_step_verdict` / reporter

**Responsibility**: the verdict event of the callback contract.

**Algorithm:**
```
class StepHooks:
    def on_step_verdict(self, step_text, category, explanation, recommendation) -> None:
        """The terminal failure carried a verdict; fires after on_step_failed."""
        # no-op base — class docstring count 8 -> 9 events
# reporter: no code change — the event is INFO by default (not in _WARNING_EVENTS)
```

**Errors**: a raising hook is logged WARNING and skipped (existing emit behavior).

**Edge Cases**: the event never fires without a verdict (executor guards `verdict is not None`).

### `StepExecutor.execute` (failure branch)

**Responsibility**: complete the step cycle's failure reporting.

**Algorithm:**
```
EXCEPT Exception AS error:
1. emit on_step_failed(step_text, step_type, first_line_short(error))
2. IF isinstance(error, (ProductDefectError, IncurableStepError)) AND error.verdict is not None:
     emit on_step_verdict(step_text, error.verdict.category, error.verdict.explanation,
                          error.verdict.recommendation)
3. RAISE
```

**Errors**: the original exception re-raised untouched.

**Edge Cases**: `LlmUnavailableError` and hook-independent failures produce no verdict event.

### `PrettyTest.action` / `assertion` (folding) and screenshot methods

**Responsibility**: the integrator boundary.

**Algorithm:**
```
action(text) / assertion(text):
1. TRY: self._executor.execute(text, "action"|"assertion", self._ensure_page())
   EXCEPT PrettyplayError AS error: _raise_folded(error)

_raise_folded(error) -> NoReturn:
1. tb = error.__traceback__                 # head link = this facade method's frame
2. folded = types.TracebackType(tb_next=None, tb_frame=tb.tb_frame,
                                tb_lasti=tb.tb_lasti, tb_lineno=tb.tb_lineno)
                                           # the only constructor form; filename/name derive
                                           # from the frame automatically
3. RAISE error.with_traceback(folded)       # the raise-line entry of the facade method and
                                           # the test frame are prepended on propagation

get_screenshot() -> bytes:
1. IF self._page is None: RAISE PrettyplayError("no test page yet: run a step first — "
                                                "the page opens lazily on the first step")
2. RETURN self._page.screenshot()

save_screenshot(filepath) -> None:
1. IF self._page is None: RAISE PrettyplayError(<the same actionable text>)
2. image = self._page.screenshot()
3. TRY:   Path(filepath).write_bytes(image)
   EXCEPT OSError AS error:
        RAISE PrettyplayError(f"cannot write the screenshot to {filepath}: {error}") FROM error
```

**Errors**: `PrettyplayError` for the no-page and write-failure cases (D2=(a)); terminal step
failures re-raised folded.

**Edge Cases**: `close()` then `get_screenshot()` → the no-page failure (`_page` reset to
`None`); no parent-directory creation in `save_screenshot`.

### Constant and prompt updates (`generator.py`)

```
GENERATION_PROMPT:   insert after the locating rule —
  "- Scroll abilities exist for scenario scrolling: bring an element into view, scroll by an
     amount, to the page end or start, inside a scrollable container"
CLASSIFICATION_PROMPT: "a cached web UI test step" -> "a web UI test step";
                       constant moves to classification.py
PAGE_API_SURFACE:    after the "page.url" line insert (mirroring facade.md order/purposes):
  page.scroll_to_element(element)            — bring an element into the viewport (works inside
                                               scrollable ancestors)
  page.scroll_down(pixels)                   — scroll the page down by an amount
  page.scroll_up(pixels)                     — scroll the page up by an amount
  page.scroll_to_bottom()                    — scroll to the end of the page
  page.scroll_to_top()                       — scroll to the start of the page
  page.scroll_into_view(element, container)  — bring an element into view inside a specific
                                               scrollable container
  page.scroll_container_down(container, pixels) — scroll a scrollable container down by an amount
  page.scroll_container_up(container, pixels)   — scroll a scrollable container up by an amount
```

### Package facades (`__init__.py`)

- `prettyplay/failures/__init__.py`: add `FailureVerdict` to imports and `__all__`.
- `prettyplay/config/__init__.py`: add `ConfigurationError` (from `.loader`).
- `prettyplay/engine/__init__.py`: add `classify_step_failure` (from `.classification`).
- `prettyplay/driver`, `prettyplay/reporting`, root `prettyplay`: no facade changes (no new
  `__all__` entities; `get_screenshot`/`save_screenshot` are methods of the exported
  `PrettyTest`).

---

## Cross-cutting Concerns

- **Error handling**: the four-kind taxonomy (`ProductDefectError` + `AssertionError`,
  `IncurableStepError`, `LlmUnavailableError`, `ConfigurationError`) under one
  `PrettyplayError` base. Verdict policy: verdicts enrich already-decided failures and are
  skipped quietly (WARNING) when the LLM is unavailable; the classification driving a healing
  decision surfaces as `LlmUnavailableError`. Raw pydantic errors never leave the loader;
  screenshot failures are library failures; channel-launch failures are Playwright's loud
  native errors. Tracebacks fold at the facade.
- **Logging**: logger `prettyplay`. INFO — step lifecycle events including the verdict event,
  generation/healing lifecycle, cache writes. WARNING — skipped cache write, failed hook call
  (existing), quiet verdict skips (new engine sites: the two `LOG warning "verdict skipped:
  llm unavailable"` branches of the shared loop — the failed-check classification and the
  generation-pool exhaustion classification). Contextual metadata via `extra`; no secrets.
- **Validation**: config — pydantic Literal/PositiveInt/bool + the rendered
  `ConfigurationError` wrapper; the legacy env variable check. Runtime — page-required guard in
  the screenshot methods. Scroll amounts are documented positive, not validated (no contract
  requirement). Assertion semantics — a failed check is an `AssertionError` by type.
- **Caching**: unchanged (step cache, per-run budgets). One behavioral addition: a failed check
  consumes exactly one generation attempt and stops the loop — budgets are never spent on
  legitimately failing assertions.
- **Concurrency**: unchanged — every Playwright call (including all 8 scroll methods and
  screenshots) is marshalled into the single driver thread through the facade `_call` boundary;
  strictly one call at a time; the calling thread never adopts the Playwright event loop.

---

## Usages Analysis

### `conventions`
- **What it provides**: mandatory Python code/testing rules (relative imports, pydantic models,
  logging levels, Google docstrings, pytest structure, mock policy).
- **Where used**: all six cells (global annotations).
- **Why chosen**: the project-wide canon.
- **How exactly**: kw_only pydantic models in config; Google docstrings everywhere; tests mirror
  the source tree (`tests/<pkg>/test_<module>.py`); mocks only at external boundaries (fake
  provider, fake page — see Test Stack Trace).

### `pydantic` (config)
- **What it provides**: model rules, the `[tool.prettyplay]` schema shape, the validation-wrap
  pattern, the TOML loading fallback.
- **Where used**: `Config`, `load_config`, `ConfigurationError` rendering.
- **Why chosen**: the settings cell's data layer.
- **How exactly**: `ConfigDict(kw_only=True)`, empty defaults, `Literal` browser set,
  `PositiveInt` attempts, `headless: bool = True`; the `wrap_validation_error` pattern becomes
  `ConfigurationError(_render(error)) from error`; `tomllib`/`tomli` conditional import.

### `playwright` (driver)
- **What it provides**: sync-API lifecycle, the engine/channel matrix with `headless`, locator
  auto-wait, the accessibility snapshot, the scroll primitives, screenshot.
- **Where used**: `DriverSession._launch_engine`, `PageFacade` (locating, snapshot, screenshot,
  8 scroll methods).
- **Why chosen**: the only browser API of the library.
- **How exactly**: `engine.launch(headless=…, channel=…)` per the matrix code block;
  `scroll_into_view_if_needed` / `mouse.wheel` / `evaluate` scroll primitives — no fixed delays.

### Imported Usages
- `taxonomy` from `prettyplay/failures` (imported by config and root)
  - Path: `prettyplay/failures/.usages/taxonomy.md`
  - Why: the failure kinds the config error joins and the step methods propagate; the verdict
    semantics and the AssertionError catching guidance. Traceable dependency: the config cell's
    `ConfigurationError` derives from the base the taxonomy documents; the root executor guards
    the verdict event by the two verdict-carrying kinds.
- `facade` from `prettyplay/driver` (imported by engine)
  - Path: `prettyplay/driver/.usages/facade.md`
  - Why: the single source of the page API surface — `PAGE_API_SURFACE` mirrors its 21-row
    table verbatim (the manifest annotation binds them to change together); the scroll rows are
    the model's allowed scrolling vocabulary.
- `classification` from `prettyplay/llm` (imported by engine)
  - Path: `prettyplay/llm/.usages/classification.md`
  - Why: the category semantics (rot / product_defect / incurable) and the
    `provider.classify_failure` call shape used verbatim by `classify_step_failure`.
- `hooks` from `prettyplay/reporting` (imported by root)
  - Path: `prettyplay/reporting/.usages/hooks.md`
  - Why: the callback contract `add_hooks` accepts; the verdict event ordering
    (`on_step_failed` → `on_step_verdict`) and the skip rule.
- `generation`, `healing` from `prettyplay/engine` (imported by root)
  - Paths: `prettyplay/engine/.usages/generation.md`, `prettyplay/engine/.usages/healing.md`
  - Why: the engine cycles the executor delegates to — the failed-check stop, the exhaustion
    verdict reuse and the shared classification routine documented there match the amended
    manifest.

---

## `.usages/` Update

### Cell: `prettyplay/failures`
- **`taxonomy.md`** → current — the four-kind table (incl. `ConfigurationError`), the verdicts
  section and the assertion semantics match the manifest. Additions/updates: none.

### Cell: `prettyplay/reporting`
- **`hooks.md`** → current — the `on_step_verdict` row, example and skip rule match. None.

### Cell: `prettyplay/config`
- **`configuration.md`** → current — `headless` in TOML and the env table
  (`PRETTYPLAY_BROWSER_NAME`, `PRETTYPLAY_BROWSER_HEADLESS`), the Browsers section,
  `ConfigurationError` rules. None.

### Cell: `prettyplay/driver`
- **`facade.md`** → current — 21-row surface with the 8 scroll calls; scroll examples in
  English; the never-sleep rule. None.

### Cell: `prettyplay/engine`
- **`generation.md`** → current — the failed-check stop, the exhaustion classification with the
  quiet skip, the shared `classify_step_failure` call. None.
- **`healing.md`** → current — the verdict table, the regeneration-exhaustion verdict reuse
  ("no extra LLM request"), the LlmUnavailable rule, the Verdicts section. None.

### Cell: `prettyplay`
- **`steps.md`** → current — the Screenshots section (both methods, the page-required rule, the
  no-automatic-capture rule). None.
- **`lifecycle.md`** → current — the four failure kinds with the verdict paragraph, the
  `on_step_verdict` hook line. None.

New files: none — every change lives inside an existing functional domain (cookbook decision
rule: changes within an existing domain supplement the existing file).

---

## Test Stack Trace

### General Setup

- Fakes at the external boundaries only (conventions mock policy):
  - `FakeProvider(LlmProvider)` — scripted `generate_step_code` / `classify_failure` sequences;
    raisable on demand (`LlmUnavailableError`).
  - `FakePage` — records calls (`aria_snapshot`, `screenshot`, `scroll_*`), returns canned
    snapshot `"body: ..."` and `b"png-bytes"`; no Playwright.
  - `RecordingHooks(StepHooks)` — appends `(event, payload)` tuples.
  - `RunBudgets(generation_attempts, healing_attempts)` — real object, cheap.
- `tmp_path` for cache roots, written screenshots and ad-hoc pyproject.toml files
  (`monkeypatch.setenv` / `delenv` for overrides; `PRETTYPLAY_*` cleaned between tests).
- Step texts and verdict fields in English sample data.

### Source File Registry

`prettyplay/failures/errors.py`, `prettyplay/config/models.py`, `prettyplay/config/loader.py`,
`prettyplay/driver/session.py`, `prettyplay/driver/page.py`,
`prettyplay/engine/classification.py`, `prettyplay/engine/generator.py`,
`prettyplay/engine/healer.py`, `prettyplay/reporting/hooks.py`,
`prettyplay/reporting/reporter.py`, `prettyplay/executor.py`, `prettyplay/scenario.py`, and the
four touched `__init__.py` facades. Test files mirror them:
`tests/failures/test_errors.py`, `tests/config/test_models.py`, `tests/config/test_loader.py`,
`tests/driver/test_session.py`, `tests/driver/test_page.py`,
`tests/engine/test_classification.py` (new), `tests/engine/test_generator.py`,
`tests/engine/test_healer.py`, `tests/reporting/test_hooks.py`, `tests/test_executor.py`,
`tests/test_scenario.py`.

Existing tests touching the old signatures are updated by the same implementation (registry of
known breakages: `tests/failures/test_errors.py` — 2/3-arg constructors, `recommendation`
param; `tests/config/test_loader.py:63` — `PRETTYPLAY_BROWSER` now raises; `tests/engine/
test_generator.py:238,308`, `test_healer.py`, `tests/test_executor.py:198–288` — error
constructors and recommendation fallbacks; `tests/engine/test_generator.py:368` — the prompt
text check; `tests/test_integration.py:402,431` — the verdict hook event: both verdict-carrying
failure tests (`test_product_defect_verdict_fails_the_test_loudly`,
`test_incurable_verdict_fails_with_verdict_fields`) must expect `on_step_verdict` after
`on_step_failed` in their hook-event list assertions).

Test additions from the review (registry):

- `tests/reporting/test_hooks.py` — add to `EVENT_SIGNATURES`:
  `"on_step_verdict": [("step_text", str), ("category", str), ("explanation", str),
  ("recommendation", str)]` — the existing contract tests then cover the 9-method surface
  automatically.
- `test_verdict_event_logged_at_info` (executor wiring, `caplog` on the `prettyplay` logger):
  the `on_step_verdict` record has `levelno == logging.INFO` (the reporting header contract).
- `test_classify_step_failure_without_screenshots`: `Config(send_screenshots=False)` →
  `provider.classify_failure` kwargs `screenshot` is `None`; `page.screenshot_calls == 0`.
- in `test_product_defect_is_assertion_and_library_error` add:
  `str(ProductDefectError("step", "expected x, observed y", None)) == "expected x, observed y"`
  (the message without the verdict tail).

---

### Positive Tests

#### `test_render_lists_all_fields`

**Setup**: none (pure value).

**Input**: `FailureVerdict(category="rot", explanation="the button was renamed",
recommendation="refresh the cache")`

**Trace**:
```
FailureVerdict("rot", "the button was renamed", "refresh the cache")
  → render()
    builds ["category: rot", "explanation: the button was renamed",
            "recommendation: refresh the cache"]
    returns: "category: rot\nexplanation: the button was renamed\nrecommendation: refresh the cache"
```

**Assertions**:
```
lines = verdict.render().splitlines()
lines == ["category: rot", "explanation: the button was renamed",
          "recommendation: refresh the cache"]
```

**Sufficiency**: fixes the stable-label contract integrators parse; prevents label drift
(casing, separators) across releases.

---

#### `test_product_defect_is_assertion_and_library_error`

**Setup**: none.

**Input**: `ProductDefectError("the banner appears", "expected visible, observed hidden",
FailureVerdict("product_defect", "e", "r"))`

**Trace**:
```
ProductDefectError(...) → class (PrettyplayError, AssertionError)
  → isinstance checks in the test
```

**Assertions**:
```
isinstance(error, PrettyplayError) and isinstance(error, AssertionError)
isinstance(ProductDefectError("s", "m", None), AssertionError)
```

**Sufficiency**: the runner-alignment requirement — unittest counts the defect as a failure,
not an error; one except clause catches it as either base.

---

#### `test_product_defect_str_appends_verdict_render`

**Setup**: none.

**Input**: `str(ProductDefectError("step", "expected x, observed y",
FailureVerdict("product_defect", "expl", "rec")))`

**Trace**:
```
__str__() → text = "expected x, observed y"; verdict present → += "\n" + render()
```

**Assertions**:
```
s.startswith("expected x, observed y")
"category: product_defect" in s and "recommendation: rec" in s
s.index("expected x, observed y") < s.index("category:")
```

**Sufficiency**: "starts with the primary reason, the verdict render appended, never
interleaved".

---

#### `test_incurable_recommendation_comes_from_verdict`

**Setup**: none.

**Input**: `IncurableStepError("s", "budget exhausted",
FailureVerdict("incurable", "e", "reword the step"))`

**Trace**:
```
recommendation (property) → verdict is not None → verdict.recommendation
```

**Assertions**:
```
error.recommendation == "reword the step"
```

**Sufficiency**: the recommendation is carried by the verdict, not a constructor field.

---

#### `test_incurable_fallback_recommendation_without_verdict`

**Setup**: none.

**Input**: `IncurableStepError("s", "budget exhausted", None)`; `str(error)`

**Trace**:
```
recommendation → verdict None → "reword the step or refresh the cache"
__str__ → reason + "\nrecommendation: reword the step or refresh the cache"
```

**Assertions**:
```
error.recommendation == "reword the step or refresh the cache"
str(error).startswith("budget exhausted")
"recommendation: reword the step or refresh the cache" in str(error)
not isinstance(error, AssertionError)
```

**Sufficiency**: the quiet-skip path stays actionable; the execution-failure kind never
masquerades as a failed check.

---

#### `test_config_headless_default_and_browser_channels`

**Setup**: none (model defaults).

**Input**: `Config()`; `Config(browser="msedge", headless=False)`

**Trace**:
```
Config() → pydantic defaults → headless True, browser "chromium"
Config(browser="msedge", headless=False) → Literal accepts "msedge"; bool False
```

**Assertions**:
```
Config().headless is True and Config().browser == "chromium"
for name in ("chromium", "firefox", "webkit", "chrome", "msedge"):
    Config(browser=name).browser == name
Config(headless=False).headless is False
```

**Sufficiency**: the five-value set and the headless default are contract surface.

---

#### `test_load_env_browser_name_and_headless`

**Setup**: `tmp_path` pyproject with `[tool.prettyplay] browser="chromium"`;
`monkeypatch.setenv("PRETTYPLAY_BROWSER_NAME", "firefox")`,
`setenv("PRETTYPLAY_BROWSER_HEADLESS", "false")`.

**Input**: `load_config(str(pyproject))`

**Trace**:
```
load_config → parse → section {browser: chromium}
  → legacy check: PRETTYPLAY_BROWSER unset → pass
  → overrides {browser: "firefox", headless: "false"}
  → Config(**merged) → pydantic coerces "false" → False
```

**Assertions**:
```
config.browser == "firefox" and config.headless is False
```

**Sufficiency**: the two renamed/special env overrides (the plan removed the old
`PRETTYPLAY_BROWSER` name).

---

#### `test_configuration_error_wraps_validation_with_lines`

**Setup**: pyproject with `browser = "netscape"` and `generation_attempts = 0`;
`monkeypatch.delenv("PRETTYPLAY_BROWSER", raising=False)`.

**Input**: `load_config(str(pyproject))`

**Trace**:
```
Config(**merged) → ValidationError (browser literal, attempts positive)
  → _render_validation: one line per invalid setting
  → raise ConfigurationError(rendered) from ValidationError
```

**Assertions**:
```
excinfo = pytest.raises(ConfigurationError, load_config, str(pyproject))
isinstance(excinfo.value, PrettyplayError)
"browser" in str(excinfo.value) and "netscape" in str(excinfo.value)
"chromium, firefox, webkit, chrome, msedge" in str(excinfo.value)
"generation_attempts" in str(excinfo.value)
str(excinfo.value).count("\n") == 1          # exactly two lines, one per setting
isinstance(excinfo.value.__cause__, ValidationError)
```

**Sufficiency**: actionable per-setting rendering, the chained original error, and the
raw-never-leaves rule.

---

#### `test_launch_passes_headless_and_channel`

**Setup**: `Config(browser="msedge", headless=False)`; a stub engine object recording
`launch(**kwargs)`; patched into the engine map (mock at the Playwright boundary).

**Input**: `DriverSession(config)._launch_engine(fake_playwright)`

**Trace**:
```
_launch_engine → name "msedge" in channels → engine = playwright.chromium
  → engine.launch(headless=False, channel="msedge")
```

**Assertions**:
```
fake_chromium.launch.call_args.kwargs == {"headless": False, "channel": "msedge"}
# and for Config(): fake_chromium.launch.call_args.kwargs == {"headless": True}
```

**Sufficiency**: the channel/headless launch contract; bundled engines pass no channel.

---

#### `test_scroll_primitives_delegate_to_playwright`

**Setup**: `PageFacade(fake_page, fake_context)` with a recording fake page (no worker — inline
calls); a real `LocatorFacade` over a recording fake locator.

**Input**: `page.scroll_down(600)`; `page.scroll_up(300)`; `page.scroll_to_bottom()`;
`page.scroll_to_top()`; `page.scroll_to_element(element)`; `page.scroll_into_view(element,
container)`; `page.scroll_container_down(container, 400)`; `page.scroll_container_up(container,
200)`

**Trace**:
```
scroll_down(600)  → fake_page.mouse.wheel(0, 600)          recorded
scroll_up(300)    → fake_page.mouse.wheel(0, -300)         recorded
scroll_to_bottom()→ fake_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
scroll_to_top()   → fake_page.evaluate("window.scrollTo(0, 0)")
scroll_to_element(el) → fake_locator.scroll_into_view_if_needed()
scroll_into_view(el, cont) → el_handle = fake_element.element_handle()
                             fake_container.evaluate(<js with target arg>, el_handle)
scroll_container_down(cont, 400) → fake_container.evaluate(<js>, 400)
scroll_container_up(cont, 200)  → fake_container.evaluate(<js>, 200)
```

**Assertions**:
```
fake.mouse.wheel_calls == [(0, 600), (0, -300)]
fake.evaluate_calls[0].startswith("window.scrollTo(0, document.body.scrollHeight)")
container.evaluate_args[-1] == 200 and "scrollTop -=" in container.evaluate_calls[-1][0]
container.evaluate_args[-2] == 400 and "scrollTop +=" in container.evaluate_calls[-2][0]
element.scroll_into_view_called is True
"scrollTop +=" in container.evaluate_calls[-3][0]     # scroll_into_view centering math
"getBoundingClientRect" in container.evaluate_calls[-3][0]
```

**Sufficiency**: the facade maps to the documented Playwright primitives with exact signs and
amounts — the surface cached step code depends on.

---

#### `test_classify_step_failure_collects_and_calls_port`

**Setup**: `FakePage` (snapshot `"body: main"`, `b"png"`); `FakeProvider` returning
`FailureClassification(category="rot", explanation="e", recommendation="r")`;
`Config(send_screenshots=True)`.

**Input**: `classify_step_failure(config, provider, "click Sign in", "def step(page): …",
"TimeoutError", page)`

**Trace**:
```
classify_step_failure → page.aria_snapshot() → "body: main"
  → page.screenshot() → b"png"               (send_screenshots True)
  → provider.classify_failure(prompt=CLASSIFICATION_PROMPT, step_text="click Sign in",
      code=…, error="TimeoutError", snapshot="body: main", screenshot=b"png")
  → returns the classification
```

**Assertions**:
```
result.category == "rot"
kwargs = provider.classify_failure_calls[0]
kwargs["step_text"] == "click Sign in" and kwargs["error"] == "TimeoutError"
kwargs["prompt"].startswith("You classify a failure of a web UI test step.")
"cached" not in kwargs["prompt"]
```

**Sufficiency**: the single shared classification call; the prompt text contract.

---

#### `test_generate_failed_check_product_defect_stops_and_carries_verdict`

**Setup**: generator over `FakeProvider` whose first candidate is
`"def step(page):\n    page.find_by_text('Welcome back').expect_visible()"`
(raises `AssertionError('banner missing')` when executed — the `FakePage`'s find_by_text handle
is programmed so the expectation fails with that message) and whose
classification returns `product_defect`; budgets `RunBudgets(3, 2)`; recording reporter.

**Input**: `generator.generate(identity, "the banner appears", [], page)`

**Trace**:
```
generate → try_generation ok → on_generation_started(1)
  → candidate code → run_step_code → AssertionError("banner missing")
  → classify_step_failure(..., error="candidate check failed: banner missing", ...)
  → verdict category product_defect
  → raise ProductDefectError("the banner appears", "banner missing", verdict)
```

**Assertions**:
```
excinfo = pytest.raises(ProductDefectError, ...)
excinfo.value.verdict.category == "product_defect"
"banner missing" in str(excinfo.value)
provider.generate_step_code_call_count == 1        # retries stopped at once
provider.classify_failure_call_count == 1
```

**Sufficiency**: the failed-check stop — the budget is never spent on a legitimately failing
assertion; the verdict reaches the error.

---

#### `test_generate_failed_check_non_defect_verdict_raises_incurable`

**Setup**: generator over `FakeProvider`: the first candidate is code with an expectation call
that raises `AssertionError("banner missing")` when executed (a `FakePage` programmed so the
expectation fails); the classification returns
`FailureClassification("incurable", "the step is ambiguous", "reword the step")`; budgets
`RunBudgets(3, 2)`.

**Input**: `generate(identity, "the banner appears", [], page)`

**Trace**:
```
generate → try_generation ok → on_generation_started(1)
  → candidate → run_step_code → AssertionError("banner missing")
  → classify_step_failure(..., error="candidate check failed: banner missing", ...)
  → verdict category incurable (not product_defect)
  → raise IncurableStepError(reason="candidate check failed: banner missing", verdict)
```

**Assertions**:
```
excinfo = pytest.raises(IncurableStepError, ...)
excinfo.value.reason.startswith("candidate check failed")
excinfo.value.verdict.category == "incurable"
provider.generate_step_code_call_count == 1        # retries stopped at once
provider.classify_failure_call_count == 1
```

**Sufficiency**: the second branch of manifest step 6 — the stop is the same but the error
kind and reason differ; prevents a regression where a non-defect failed check silently retries.

---

#### `test_generate_exhaustion_classifies_last_candidate`

**Setup**: `RunBudgets(1, 2)`; candidates always raise `TimeoutError` (non-assertion);
classification returns `incurable`.

**Input**: `generate(identity, "open the menu", [], page)`

**Trace**:
```
attempt 1 → candidate fails (TimeoutError) → error recorded
  → spend refused on iteration 2 → pool "generation", error present
  → classify_step_failure → verdict incurable
  → raise IncurableStepError(reason="generation attempt budget exhausted; last failure: …",
                             verdict)
```

**Assertions**:
```
excinfo.value.reason.startswith("generation attempt budget exhausted")
"last failure:" in excinfo.value.reason
excinfo.value.verdict.category == "incurable"
```

**Sufficiency**: exhaustion classification with the verdict — the reason names the pool and the
last candidate failure.

---

#### `test_heal_product_defect_carries_full_verdict`

**Setup**: healer over `FakeProvider` classification
`FailureClassification("product_defect", "expected the total 100, observed 90", "file a bug")`;
a cached step; `FakePage`.

**Input**: `healer.heal(step, "assertion text mismatch", [], page)`

**Trace**:
```
heal → classify_step_failure → classification
  → verdict = FailureVerdict("product_defect", "expected the total 100, observed 90", "file a bug")
  → on_healing_started(category="product_defect")
  → raise ProductDefectError(step_text, "expected the total 100, observed 90", verdict)
```

**Assertions**:
```
excinfo.value.verdict.recommendation == "file a bug"
str(excinfo.value).startswith("expected the total 100, observed 90")   # message first
str(excinfo.value).count("expected the total 100, observed 90") == 2
  # message + the verdict render explanation — the heal path passes classification.explanation
  # as the message AND the verdict carries it
"recommendation: file a bug" in str(excinfo.value)
hooks events contain ("on_healing_started", {"category": "product_defect"})
```

**Sufficiency**: anti-masking path with the verdict fully reaching the error.

---

#### `test_heal_incurable_carries_verdict_and_skips_regeneration`

**Setup**: healer over `FakeProvider` classification `FailureClassification("incurable", "the
step text no longer matches reality", "reword the step")`; a cached step; `FakePage`; call
counter on the fake provider.

**Input**: `healer.heal(step, "element not found", [], page)`

**Trace**:
```
heal → classify_step_failure (call 1) → incurable verdict
  → on_healing_started(category="incurable")
  → raise IncurableStepError(step_text, "the step text no longer matches reality", verdict)
  # regenerate is never reached
```

**Assertions**:
```
excinfo = pytest.raises(IncurableStepError, ...)
excinfo.value.reason == "the step text no longer matches reality"
excinfo.value.verdict.category == "incurable"
excinfo.value.recommendation == "reword the step"          # property derives from the verdict
str(excinfo.value).endswith("recommendation: reword the step")
provider.generate_step_code_call_count == 0                 # no regeneration request
hooks events contain ("on_healing_started", {"category": "incurable"})
```

**Sufficiency**: the third verdict branch of heal gets its own regression test — the reason
comes from the classification, the verdict fully reaches the error, and incurability never
triggers regeneration (anti-masking).

---

#### `test_heal_rot_exhaustion_reuses_verdict_without_second_request`

**Setup**: classification returns rot; `RunBudgets(1, 1)`; regeneration candidates always fail
with `TimeoutError`; call counter on the fake provider.

**Input**: `healer.heal(step, "element not found", [], page)`

**Trace**:
```
heal → classify_step_failure (call 1) → rot verdict
  → on_healing_started → regenerate → try_healing spent on attempt 1 → candidate fails
  → spend refused → pool "healing" → raise IncurableStepError(reason, None)   # no classification
  → healer catches verdict None → raise IncurableStepError(reason, rot verdict) from it
```

**Assertions**:
```
excinfo.value.verdict.category == "rot"
excinfo.value.reason.startswith("healing attempt budget exhausted")
provider.classify_failure_call_count == 1          # no extra LLM request
```

**Sufficiency**: the amended third difference — exhaustion on the healing pool reuses the
step-1 verdict.

---

#### `test_executor_reports_verdict_after_failed`

**Setup**: executor wired with a healer stub raising
`IncurableStepError("s", "r", FailureVerdict("incurable", "e", "rec"))`; `RecordingHooks`;
`FakePage`; a cached step present.

**Input**: `executor.execute("s", "assertion", page)`

**Trace**:
```
execute → on_step_started → cache hit → run_step_code raises → heal raises IncurableStepError
  → except: on_step_failed(error=first line of reason)
  → isinstance check + verdict not None → on_step_verdict("s", "incurable", "e", "rec")
  → raise
```

**Assertions**:
```
names = [e for e, _ in hooks.events]
names.index("on_step_failed") < names.index("on_step_verdict")
payload = dict-verdict event → {"step_text": "s", "category": "incurable",
                                "explanation": "e", "recommendation": "rec"}
```

**Sufficiency**: the manifest execute step 7 — the verdict event fires between
`on_step_failed` and the raise, with the three verdict fields.

---

#### `test_action_folds_traceback_to_boundary`

**Setup**: monkeypatched `get_runtime`/executor chain returning a generator stub whose
`generate` raises `IncurableStepError("s", "r", FailureVerdict("incurable", "e", "rec"))`
through two nested helper frames (simulating engine depth).

**Input**: `PrettyTest("k").assertion("s")`

**Trace**:
```
assertion → _ensure_page → executor.execute → …engine frames… → raise
  → except PrettyplayError → _raise_folded
  → fresh single-frame types.TracebackType(tb_frame=assertion boundary, tb_lasti, lineno)
  → raise …with_traceback → propagates out to the test frame
```

**Assertions**:
```
import traceback
excinfo = pytest.raises(IncurableStepError, t.assertion, "s")
frames = [e.filename for e in traceback.extract_tb(excinfo.value.__traceback__)]
assert frames[-1].endswith("scenario.py")                       # innermost = the boundary
assert not any(f.endswith(("generator.py", "healer.py", "executor.py")) for f in frames)
```

**Sufficiency**: the runner sees no engine/healing/provider frames; the boundary frame is the
facade method.

---

#### `test_get_and_save_screenshot`

**Setup**: `PrettyTest` with a monkeypatched runtime whose `open_page` returns `FakePage`
(screenshot → `b"png-bytes"`); one action step executed first (`FakeProvider` one-shot
candidate).

**Input**: `t.get_screenshot()`; `t.save_screenshot(str(tmp_path / "artifacts" / "home.png"))`
(with the directory pre-created).

**Trace**:
```
get_screenshot → _page not None → FakePage.screenshot() → b"png-bytes"
save_screenshot → write_bytes(b"png-bytes") → file exists
```

**Assertions**:
```
t.get_screenshot() == b"png-bytes"
(tmp_path / "artifacts" / "home.png").read_bytes() == b"png-bytes"
```

**Sufficiency**: the author screenshot abilities over the facade screenshot.

---

### Negative Tests

#### `test_screenshot_before_first_step_raises_library_failure`

**Setup**: `PrettyTest("k")` with a runtime stub (no page ever opened).

**Input**: `t.get_screenshot()`; then `t.save_screenshot("x.png")`

**Trace**:
```
get_screenshot → _page is None → raise PrettyplayError("no test page yet: run a step first …")
```

**Assertions**:
```
excinfo = pytest.raises(PrettyplayError, t.get_screenshot)
"run a step first" in str(excinfo.value)
pytest.raises(PrettyplayError, t.save_screenshot, "x.png")
```

**Sufficiency**: the page-required guard is loud, actionable and library-typed (D2).

---

#### `test_save_screenshot_write_failure_wraps_oserror`

**Setup**: page opened (stub); `filepath = tmp_path / "missing-dir" / "x.png"` (directory not
created).

**Input**: `t.save_screenshot(str(filepath))`

**Trace**:
```
save_screenshot → screenshot() ok → Path.write_bytes → OSError (missing parent)
  → raise PrettyplayError("cannot write the screenshot to …: …") from OSError
```

**Assertions**:
```
excinfo = pytest.raises(PrettyplayError, ...)
"isinstance(excinfo.value.__cause__, OSError)"
str(excinfo.value).startswith("cannot write the screenshot to")
not filepath.exists()                              # nothing created silently
```

**Sufficiency**: the write-failure contract (D2=(a)) with the chained original error.

---

#### `test_legacy_browser_env_raises_configuration_error`

**Setup**: valid pyproject; `monkeypatch.setenv("PRETTYPLAY_BROWSER", "firefox")`;
`delenv("PRETTYPLAY_BROWSER_NAME", raising=False)`.

**Input**: `load_config(str(pyproject))`

**Trace**:
```
load_config → legacy check → PRETTYPLAY_BROWSER set
  → raise ConfigurationError(hint naming PRETTYPLAY_BROWSER_NAME)
```

**Assertions**:
```
excinfo = pytest.raises(ConfigurationError, ...)
"PRETTYPLAY_BROWSER_NAME" in str(excinfo.value)
```

**Sufficiency**: D1=(a) — the legacy variable is answered loudly, never silently ignored.

---

#### `test_generate_quiet_verdict_skip_on_unavailable_classification`

**Setup**: candidate raises `AssertionError`; `FakeProvider.classify_failure` raises
`LlmUnavailableError("openai down")`; `caplog` at WARNING on the `prettyplay` logger.

**Input**: `generate(identity, "the total is 100", [], page)`

**Trace**:
```
candidate fails as a check → classify_step_failure → provider raises LlmUnavailableError
  → engine catches → logger.warning("verdict skipped: llm unavailable")
  → raise IncurableStepError(reason="candidate check failed: …", verdict=None)
```

**Assertions**:
```
excinfo = pytest.raises(IncurableStepError, ...)
excinfo.value.verdict is None
excinfo.value.reason.startswith("candidate check failed")
any("verdict skipped" in r.message for r in caplog.records if r.levelno == logging.WARNING)
```

**Sufficiency**: the quiet-skip rule — the failure is never delayed or distorted, the verdict
enrichment is skipped with a WARNING.

---

#### `test_heal_classification_unavailable_is_infrastructure_failure`

**Setup**: `FakeProvider.classify_failure` raises `LlmUnavailableError("anthropic down")`.

**Input**: `healer.heal(step, "error", [], page)`

**Trace**:
```
heal → classify_step_failure → provider raises → propagates untouched (no swallow)
```

**Assertions**:
```
excinfo = pytest.raises(LlmUnavailableError, ...)
"anthropic" in str(excinfo.value)
```

**Sufficiency**: the classification driving the healing decision surfaces as the infrastructure
failure — the opposite regime of the quiet skip.

---

#### `test_generate_provider_request_unavailable_no_retry`

**Setup**: `FakeProvider.generate_step_code` raises `LlmUnavailableError("openai down")`;
budgets `RunBudgets(3, 2)`.

**Input**: `generate(identity, "s", [], page)`

**Trace**:
```
attempt 1 → provider raises → propagates immediately (no classification, no retry)
```

**Assertions**:
```
pytest.raises(LlmUnavailableError, ...)
provider.generate_step_code_call_count == 1
```

**Sufficiency**: unchanged hard requirement re-pinned against the new loop shape.

---

#### `test_unknown_browser_rejected_at_model`

**Setup**: none.

**Input**: `Config(browser="netscape")`

**Trace**:
```
Config(**{...}) → Literal validation → ValidationError
```

**Assertions**:
```
pytest.raises(ValidationError, Config, browser="netscape")
```

**Sufficiency**: the five-value set enforced at the model (the loader wraps it into
`ConfigurationError` — covered above).

---

### Edge Case Tests

#### `test_render_skips_empty_fields`

**Setup**: none.

**Input**: `FailureVerdict(category="rot", explanation="", recommendation="refresh the cache")`

**Trace**:
```
render → explanation empty → no line
```

**Assertions**:
```
verdict.render() == "category: rot\nrecommendation: refresh the cache"
```

**Sufficiency**: the LLM single-line format may yield empty segments; the render degrades
without empty lines.

---

#### `test_generate_first_refusal_without_candidate`

**Setup**: `RunBudgets(1, 2)`; spend the generation budget beforehand via a prior
`generate`-equivalent call on the same identity (candidates succeed there).

**Input**: second `generate(identity, "s", [], page)` in the same run

**Trace**:
```
spend refused → error is None → no classification inputs
  → raise IncurableStepError(reason="generation attempt budget exhausted", verdict=None)
```

**Assertions**:
```
excinfo.value.reason == "generation attempt budget exhausted"
excinfo.value.verdict is None
provider.classify_failure_call_count == 0
```

**Sufficiency**: the budget-shared-per-run edge — no candidate exists to classify.

---

#### `test_verdict_event_absent_without_verdict`

**Setup**: executor wired with a healer stub raising `LlmUnavailableError("down")`;
`RecordingHooks`.

**Input**: `execute("s", "action", page)`

**Trace**:
```
except branch → on_step_failed → isinstance guard: not a verdict-carrying kind → no
  on_step_verdict → raise
```

**Assertions**:
```
"on_step_verdict" not in [e for e, _ in hooks.events]
"on_step_failed" in [e for e, _ in hooks.events]
```

**Sufficiency**: "not fired when the verdict was skipped" — LlmUnavailable logs a WARNING and
raises no event.

---

#### `test_heal_preserves_fresh_verdict_from_regenerate_failed_check`

**Setup**: classification returns rot; during regeneration the candidate raises
`AssertionError` and the inner failed-check classification returns `product_defect`
(`FakeProvider` with scripted sequences).

**Input**: `healer.heal(step, "error", [], page)`

**Trace**:
```
heal → rot verdict → regenerate → candidate check fails → inner classification product_defect
  → ProductDefectError(fresh verdict) → healer except IncurableStepError: not taken
    (different type) → propagates
```

**Assertions**:
```
excinfo = pytest.raises(ProductDefectError, ...)
excinfo.value.verdict.category == "product_defect"      # the fresh verdict, not the rot one
```

**Sufficiency**: "every verdict produced on the paths of this method fully reaches the raised
error" — the reuse never overwrites a fresher verdict.

---

#### `test_page_api_surface_mirrors_facade_practice`

**Setup**: none (constant vs practice file).

**Input**: `PAGE_API_SURFACE` vs `prettyplay/driver/.usages/facade.md`

**Trace**:
```
parse the practice table's page.* calls → compare with the constant's page.* lines (names and
order)
```

**Assertions**:
```
surface_calls = [l.split("—")[0].strip() for l in PAGE_API_SURFACE.splitlines()
                 if l.startswith("page.")]
assert surface_calls == [
    "page.open(url)", "page.find_by_role(role, name)", "page.find_by_label(label)",
    "page.find_by_text(text)", "page.aria_snapshot()", "page.screenshot()", "page.url",
    "page.scroll_to_element(element)", "page.scroll_down(pixels)", "page.scroll_up(pixels)",
    "page.scroll_to_bottom()", "page.scroll_to_top()", "page.scroll_into_view(element, container)",
    "page.scroll_container_down(container, pixels)", "page.scroll_container_up(container, pixels)",
]
```

**Sufficiency**: the manifest annotation "the listing and the practice change together" made
mechanical — a forgotten surface update fails a test, not a generation.

---

#### `test_scenario_close_then_screenshot_raises`

**Setup**: `PrettyTest` with stub runtime; one step run; then `t.close()`.

**Input**: `t.get_screenshot()` after `close()`

**Trace**:
```
close → _page.close() → _page = None → get_screenshot → no-page PrettyplayError
```

**Assertions**:
```
pytest.raises(PrettyplayError, t.get_screenshot)
```

**Sufficiency**: the page state after close is the same explicit absence as before the first
step.

---

## Additional Instructions for the Implementation Agent

- Implement in dependency order: failures → config → driver → engine → reporting → root
  (matches the cell order; reporting's hook is independent but its consumer lands in root).
- `prettyplay/engine/classification.py` is a **new** file; move `CLASSIFICATION_PROMPT` there
  from `generator.py` (its only consumer); keep `GENERATION_PROMPT` and `PAGE_API_SURFACE` in
  `generator.py`.
- Update the three facades (`failures`, `config`, `engine` `__init__.py`) with the new exports
  (`FailureVerdict`, `ConfigurationError`, `classify_step_failure`) — `__all__` is the facade.
- The verdict build from a classification is one helper (`FailureVerdict(c.category,
  c.explanation, c.recommendation)`) — keep it in the engine (`generator.py`), not in the
  failures cell ("built by the engines; the failure types never request it themselves").
- The quiet-skip WARNING sites use `logging.getLogger("prettyplay")` — do not route them through
  `StepReporter.emit` (they are log-only, not hook events).
- Do not construct `ProductDefectError`/`IncurableStepError` with a string third argument — the
  parameter is `verdict: FailureVerdict | None`; update every legacy call site (engine, tests).
- The traceback folding must re-raise the **same** exception object (`raise error
  .with_traceback(…)`) — never a copy — so hook consumers and `except` clauses keep identity.
- No sleeps, no new waits anywhere near scrolls; no parent-directory creation in
  `save_screenshot`; no changes to the cache cell, the llm cell or `run_step_code`.
- Tests: new file `tests/engine/test_classification.py`; update the registered breakages
  (see Source File Registry); English sample data in all new/rewritten examples.
- Verify with `pytest tests/ -x`, `ruff check prettyplay/`, and the facade check
  `python -c "from prettyplay import PrettyTest; from prettyplay.failures import
  FailureVerdict; from prettyplay.config import ConfigurationError; from
  prettyplay.engine import classify_step_failure"`.
