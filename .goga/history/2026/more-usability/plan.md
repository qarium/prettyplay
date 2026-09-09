# Plan: `more-usability`

Result of compiling the verified design document (`.goga/history/2026/more-usability/design.md`,
13/13 review fixes applied) into a ralphex-compatible execution plan.

---

## Purpose

Materialize the `more-usability` contract changes into the Python implementation of `prettyplay`:

- **Verdicts on terminal failures** — the new `FailureVerdict` value object carried by
  `ProductDefectError` (which also gains the `AssertionError` base) and `IncurableStepError`
  (whose `recommendation` becomes a derived property with a built-in fallback); rendered messages
  append the verdict render.
- **Failed-check classification stop** — a candidate check that executed and did not hold stops
  the generation retries immediately and is classified; budget exhaustion classifies the last
  candidate (generation pool only); the LLM-unavailable verdict skip is a WARNING.
- **The shared classification routine** — `classify_step_failure` in the new
  `prettyplay/engine/classification.py`, the single classification call for both engines.
- **Browser channels + headless** — `Config.headless`, the five-value browser set,
  `PRETTYPLAY_BROWSER_NAME` / `PRETTYPLAY_BROWSER_HEADLESS` env overrides, the legacy
  `PRETTYPLAY_BROWSER` answered loudly, and `DriverSession` launching with `headless`/`channel`.
- **Configuration error** — validation failures wrapped into the actionable
  `ConfigurationError` (a `PrettyplayError` mutation) with the original `ValidationError` chained.
- **Scroll abilities** — 8 scroll methods on `PageFacade` (never sleeping), the scroll rule in
  `GENERATION_PROMPT`, and the 8 scroll rows in `PAGE_API_SURFACE`.
- **Author screenshots** — `PrettyTest.get_screenshot()` / `save_screenshot(filepath)`.
- **Traceback folding + verdict reporting** — `PrettyTest.action`/`assertion` fold the traceback
  to the library boundary; `StepExecutor.execute` reports `on_step_verdict` between
  `on_step_failed` and the raise; `StepHooks` gains the `on_step_verdict` event.

The most important gaps between contract and code: every new entity above is absent; the error
constructors take a legacy `recommendation` string instead of a verdict; the generation loop
retries failed checks and never classifies; the healer classifies inline and raises verdict-less
errors; the loader leaks raw pydantic errors and reads the removed env name; the launch call
passes no `headless`/`channel`.

**Strategy**: strict TDD per contract entity, one cell completed before the next, in dependency
order **failures → config → driver → engine → reporting → root**, integration tests last.
The six changed `CODEMANIFEST` files are already applied to the tree and lint-clean — they are
**read-only** for the implementation.

---

## Context

### Contract Surface

**Entity: `FailureVerdict(category: str, explanation: str, recommendation: str)`**
- Type: `class` (Entity)
- Declared `location`: `prettyplay/failures/errors.py`
- Facade obligation: importable from `prettyplay.failures` (new `__all__` entry)
- Mutations: none (plain entity, built by the engines — the failure types never request it)
- Properties: `category -> str` (rot | product_defect | incurable), `explanation -> str`
  (what happened on the page — one short sentence), `recommendation -> str` (the recommended
  engineer action — one short sentence)
- Methods: `render() -> text: str` — one line per **non-empty** field
  (`category: …`, `explanation: …`, `recommendation: …`), joined with `"\n"`; labels are stable
  lowercase words — integrators parse them; the single render used by the exception message tail,
  the hook event payload content and the log record
- Semantic requirements: frozen immutable value object; a `@dataclass(frozen=True)` (stdlib, not
  pydantic — the failures cell is the stdlib-only leaf; `FailureClassification` already validated
  the source data; pydantic models inside exception payloads add construction cost on failure
  paths — a conscious, documented deviation from the pydantic rule that targets data models)
- Imported dependencies: none (stdlib only)
- Annotation context: header annotation — "the rendered message of a terminal failure starts with
  its primary reason; the verdict render is appended, never interleaved"

**Entity mutation: `PrettyplayError::ProductDefectError(step_text: str, message: str, verdict: FailureVerdict | None)`**
- Type: `class` (Entity, mutation of `PrettyplayError`)
- Declared `location`: `prettyplay/failures/errors.py`
- Facade obligation: already exported from `prettyplay.failures`
- Properties: `step_text -> str`, `message -> str` (what was expected vs observed — the primary
  reason), `verdict -> FailureVerdict | None` (None = explicit absence when the LLM was
  unavailable — the failure never waits for the verdict)
- Semantic requirements:
  - Derives from **both** `PrettyplayError` and `AssertionError` (catchable as any library
    failure and as an assertion failure; unittest counts it as a failure, not an error);
    bases resolve — both derive from `Exception`, no layout conflict
  - `PrettyplayError.__init__(message)` — `args` carry the primary reason only; `__init__` stores
    `.step_text`, `.message`, `.verdict` (`verdict` defaults to `None`)
  - `__str__`: `message` first, then `"\n" + verdict.render()` appended when the verdict is
    present — never interleaved
  - The runner alignment is done by the type itself, never by a runner plugin
- Imported dependencies: none new

**Entity mutation: `PrettyplayError::IncurableStepError(step_text: str, reason: str, verdict: FailureVerdict | None)`**
- Type: `class` (Entity, mutation of `PrettyplayError`)
- Declared `location`: `prettyplay/failures/errors.py`
- Facade obligation: already exported from `prettyplay.failures`
- Properties: `step_text -> str`, `reason -> str` (the specific incurability cause — the primary
  reason), `recommendation -> str` (derived `@property`: `verdict.recommendation` when present,
  otherwise the built-in path guidance `"reword the step or refresh the cache"`),
  `verdict -> FailureVerdict | None`
- Semantic requirements:
  - Derives from `PrettyplayError` **only**, never from `AssertionError` (an execution failure,
    not a failed check)
  - `__str__`: `reason` first; then `"\n" + verdict.render()` when the verdict is present,
    otherwise `"\nrecommendation: <built-in path guidance>"` — the fallback keeps the message
    actionable
  - The old positional signature `(step_text, reason, recommendation)` is replaced: these errors
    are raised by the library, not constructed by integrators — legacy call sites (engine, tests)
    are updated
- Imported dependencies: `FailureVerdict` (same file)

**Entity mutation: `PrettyplayError::ConfigurationError(message: str)`**
- Type: `class` (Entity, mutation of the imported `PrettyplayError`)
- Declared `location`: `prettyplay/config/loader.py`
- Facade obligation: importable from `prettyplay.config` (new `__all__` entry)
- Properties: `message -> str` (the rendered actionable validation text — one line per invalid
  setting)
- Semantic requirements: raised by `load_config` with the original pydantic `ValidationError`
  chained (`__cause__`); catchable with the single library except clause; **never carries a
  verdict** — a configuration failure is not a step failure
- Imported dependencies: `PrettyplayError` from `prettyplay/failures` (Types import, already in
  the manifest)

**Entity: `Config(provider, browser, model, generation_model, classification_model, base_url, cache_root, generation_attempts, healing_attempts, send_screenshots, headless)`**
- Type: `class` (Entity, pydantic model)
- Declared `location`: `prettyplay/config/models.py`
- Facade obligation: already exported from `prettyplay.config`
- Changed surface: `browser` becomes `Literal["chromium", "firefox", "webkit", "chrome", "msedge"]`
  (default `chromium`; `chrome`/`msedge` are valid settings whose launch semantics live in the
  driver); new field `headless: bool = True`
- Semantic requirements: kw_only construction; every field has an empty default; attempts are
  positive integers; unchanged fields untouched
- Imported dependencies: pydantic (external)

**Routine: `load_config(pyproject_path: str | None) -> config: Config`**
- Type: `function`
- Declared `location`: `prettyplay/config/loader.py`
- Facade obligation: already exported from `prettyplay.config`
- Algorithm (verbatim from the design):
  1. `path = explicit or _find_pyproject()` (unchanged; `FileNotFoundError` retained)
  2. `data = tomllib.load(path)` (unchanged; `tomllib` / `tomli` on 3.10)
  3. `section = data["tool"]["prettyplay"] or {}` (unchanged)
  4. **Legacy check**: if `"PRETTYPLAY_BROWSER"` is set in the environment, raise
     `ConfigurationError("PRETTYPLAY_BROWSER is no longer supported: use PRETTYPLAY_BROWSER_NAME")`
     **before** merging (user-approved D1=(a))
  5. Collect env overrides from the per-field name map — `browser → PRETTYPLAY_BROWSER_NAME`,
     `headless → PRETTYPLAY_BROWSER_HEADLESS`, every other field →
     `PRETTYPLAY_<FIELD_UPPERCASE>`; a variable that is set wins (empty string included);
     bool strings (`"false"`, `"0"`, `"true"`) are coerced by pydantic lax mode at the next step
  6. `merged = {**section, **overrides}`
  7. Empty `cache_root` → absolute `<pyproject_dir>/.prettyplay/cache` (unchanged)
  8. `TRY: RETURN Config(**merged)` / `EXCEPT ValidationError as error: RAISE
     ConfigurationError(_render_validation(error)) FROM error`
  - `_render_validation(error) -> str`: one line per entry of `error.errors()` —
    `f"{field}: received {input!r} — allowed: {ALLOWED.get(field, entry.msg)}"`; the allowed text
    from a static map (provider → `openai, anthropic`; browser → `chromium, firefox, webkit,
    chrome, msedge`; generation_attempts / healing_attempts → `a positive integer`; headless →
    `a boolean`; the string fields → `a non-empty string`; fallback → the pydantic message);
    lines joined with `"\n"`
- Semantic requirements: an env override exists for every setting; a raw
  `pydantic.ValidationError` never leaves the loader; no pydantic internals in the user-visible
  text; multiple invalid settings → multiple lines in pydantic's report order

**Entity: `DriverSession(config: Config)`**
- Type: `class` (Entity)
- Declared `location`: `prettyplay/driver/session.py`
- Facade obligation: already exported from `prettyplay.driver`
- Changed behavior — `_launch_engine(playwright) -> Browser` (verbatim from the design):
  ```
  1. name = config.browser
  2. IF name in ("chrome", "msedge"): engine = playwright.chromium; channel = name
     ELSE: engine = ENGINES[name]; channel = None    # ENGINES = {chromium, firefox, webkit}
  3. IF channel: RETURN engine.launch(headless=config.headless, channel=channel)
     ELSE: RETURN engine.launch(headless=config.headless)
  ```
- Semantic requirements: a channel launch without the installed browser fails loudly with an
  actionable message naming the missing browser — Playwright's native `Error` already names the
  distribution and the `playwright install <name>` remedy; propagate as-is, invent no new failure
  kind in the driver cell; the failed-launch cleanup of `_launch` (stop driver, close thread)
  applies unchanged; retry after a failed launch starts from a clean state
- Imported dependencies: `Config` (config cell)

**Entity: `PageFacade(page: Page, context: BrowserContext)`**
- Type: `class` (Entity)
- Declared `location`: `prettyplay/driver/page.py`
- Facade obligation: already exported from `prettyplay.driver`
- New methods (8) — primitive mapping (verbatim from the design):
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
  ```
- Semantic requirements:
  - Every call is marshalled through `self._call(...)` into the driver thread of the owning
    session (existing pattern); strictly one at a time
  - `scroll_into_view` resolves the target via `element_handle()` (auto-waits) and passes the
    `ElementHandle` as the evaluate argument — it is a `JSHandle` subclass and serializes as a
    live handle (a raw `Locator` argument serializes as `undefined` in playwright-python and is
    not usable — verified empirically at design review)
  - No sleeps anywhere — the scrolled state is awaited by the follow-up locators and expectations
  - `pixels: int` documented positive; no validation mandated (a negative amount simply scrolls
    the other way); a target taller than the container centers as far as the scroll range allows
    (clamped by the browser, no error)
  - Playwright errors propagate as-is (element not found after auto-wait) — same as the locating
    methods
- Imported dependencies: `LocatorFacade` (same file)

**Routine: `classify_step_failure(config: Config, provider: LlmProvider, step_text: str, code: str, error: str, page: PageFacade) -> classification: FailureClassification`**
- Type: `function` (Routine)
- Declared `location`: `prettyplay/engine/classification.py` (**new file**)
- Facade obligation: importable from `prettyplay.engine` (new `__all__` entry)
- Algorithm (verbatim from the design):
  ```
  1. snapshot = page.aria_snapshot()
  2. screenshot = page.screenshot() IF config.send_screenshots ELSE None
  3. RETURN provider.classify_failure(prompt=CLASSIFICATION_PROMPT, step_text=step_text,
                                      code=code, error=error, snapshot=snapshot,
                                      screenshot=screenshot)
  ```
- Semantic requirements: `CLASSIFICATION_PROMPT` (without "cached") moves here from
  `generator.py` — its only consumer; the module placement breaks the would-be import cycle
  (`classification` ← prompt ← `generator` ← routine ← `classification`); provider
  unavailability (`LlmUnavailableError`) propagates untouched — this routine never swallows it;
  the calling path decides (quiet skip in the generator, infrastructure failure in the healer)
- Imported dependencies: `Config` (config), `LlmProvider` + `FailureClassification` (llm),
  `PageFacade` (driver)

**Entity: `StepGenerator(config, provider, cache, budgets, reporter)`**
- Type: `class` (Entity)
- Declared `location`: `prettyplay/engine/generator.py`
- Facade obligation: already exported from `prettyplay.engine`
- Changed behavior — the shared loop `_loop(identity, step_text, previous_steps, page, pool,
  existing_code, error) -> CachedStep` (verbatim from the design):
  ```
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
- Semantic requirements:
  - `generate` enters the loop with `pool="generation"`; `regenerate` with `pool="healing"`,
    `existing_code` and `error` — the same loop with **three** additions: (1) every provider
    request carries `existing_code` and `error`; (2) attempts consume `budgets.try_healing`;
    (3) a budget exhaustion raises `IncurableStepError` **without classification** — the healer
    attaches the verdict of its own classification, no extra LLM request is made; the
    failed-check classification applies on both pools (a product defect found mid-regeneration
    still fails loudly)
  - Exactly one failed check stops the retries: the attempt budget is never spent on a
    legitimately failing assertion
  - Provider unavailability of a generation request surfaces as `LlmUnavailableError`
    immediately — no retry on it
  - The quiet-skip WARNING sites use `logging.getLogger("prettyplay")` directly — never routed
    through `StepReporter.emit` (log-only, not hook events)
  - First-refusal exhaustion (budget spent by an earlier test of the run) → no classification
    inputs exist; the error names the exhausted pool only
  - A verdict requested on this path fully reaches the raised error
- Constant updates (same file, verbatim):
  - `GENERATION_PROMPT`: insert after the locating rule —
    `- Scroll abilities exist for scenario scrolling: bring an element into view, scroll by an amount, to the page end or start, inside a scrollable container`
  - `PAGE_API_SURFACE`: after the `page.url` line insert (mirroring `facade.md` order/purposes):
    ```
    page.scroll_to_element(element)            — bring an element into the viewport (works inside scrollable ancestors)
    page.scroll_down(pixels)                   — scroll the page down by an amount
    page.scroll_up(pixels)                     — scroll the page up by an amount
    page.scroll_to_bottom()                    — scroll to the end of the page
    page.scroll_to_top()                       — scroll to the start of the page
    page.scroll_into_view(element, container)  — bring an element into view inside a specific scrollable container
    page.scroll_container_down(container, pixels) — scroll a scrollable container down by an amount
    page.scroll_container_up(container, pixels)   — scroll a scrollable container up by an amount
    ```
  - `CLASSIFICATION_PROMPT` is **removed** from `generator.py` (it moves to `classification.py`;
    text: "a cached web UI test step" → "a web UI test step")
- Imported dependencies: `Config`, `PageFacade`, `FailureVerdict` + error types (failures),
  `LlmProvider` (llm), cache types, `StepReporter` (reporting), `classify_step_failure`
  (classification.py)

**Entity: `StepHealer(config, provider, generator, cache, budgets, reporter)`**
- Type: `class` (Entity)
- Declared `location`: `prettyplay/engine/healer.py`
- Facade obligation: already exported from `prettyplay.engine`
- Changed behavior — `heal(step, error, previous_steps, page) -> CachedStep` (verbatim from the
  design):
  ```
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
- Semantic requirements:
  - `classify_step_failure` is called exactly once per `heal` invocation (assertable via the fake
    provider call count); the exhaustion reuse introduces no second LLM request
  - Anti-masking: a classified product defect always fails the test; the healed code replaces the
    cache only after a successful execution (the generator saves only proven candidates)
  - Every verdict produced on the paths of this method fully reaches the raised error — all four
    exit paths: product_defect, incurable, exhaustion-reuse (`raise … from incurable`), and the
    failed-check passthrough (a `ProductDefectError` from `regenerate` is a different type — the
    `except IncurableStepError` clause never takes it)
  - A fresh failed-check verdict from regeneration is never overwritten
- Imported dependencies: same set as before plus `classify_step_failure` (classification.py),
  `FailureVerdict` (failures)

**Entity: `StepHooks()`**
- Type: `class` (Entity)
- Declared `location`: `prettyplay/reporting/hooks.py`
- Facade obligation: already exported from `prettyplay.reporting`
- New method: `on_step_verdict(step_text: str, category: str, explanation: str,
  recommendation: str)` — "The terminal failure of the step carried a verdict; fires after
  on_step_failed"; a no-op base like every other event; payload values are plain strings, uniform
  with the other events; the class docstring event count 8 → 9
- Reporting contract: the event is INFO by default (not in `_WARNING_EVENTS`) — **no change to
  `reporter.py`**; the event never fires without a verdict (the executor guards
  `verdict is not None`); a raising hook is logged WARNING and skipped (existing emit behavior)

**Entity: `StepExecutor(cache_key, cache, generator, healer, budgets, reporter)`**
- Type: `class` (Entity)
- Declared `location`: `prettyplay/executor.py`
- Facade obligation: already exported from `prettyplay`
- Changed behavior — the failure branch of `execute` (verbatim from the design):
  ```
  EXCEPT Exception AS error:
  1. emit on_step_failed(step_text, step_type, first_line_short(error))
  2. IF isinstance(error, (ProductDefectError, IncurableStepError)) AND error.verdict is not None:
       emit on_step_verdict(step_text, error.verdict.category, error.verdict.explanation,
                            error.verdict.recommendation)
  3. RAISE
  ```
- Semantic requirements: only these two types carry a verdict (`LlmUnavailableError` and
  `ConfigurationError` never do); ordering after `on_step_failed` and before the raise; the
  original exception object re-raised untouched — the verdict still reaches the runner through
  the exception itself; both types are imported by the root cell already

**Entity: `PrettyTest(cache_key: str, cache_path: str | None)`**
- Type: `class` (Entity)
- Declared `location`: `prettyplay/scenario.py`
- Facade obligation: already exported from `prettyplay`
- Changed methods `action(text)` / `assertion(text)` — traceback folding (verbatim from the design):
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
  ```
  The runner then shows: test frame → the boundary frame of `PrettyTest.action/assertion`
  (scenario.py — the raise line and the executor call line, both at the boundary) → the rendered
  message with the verdict tail; internal library frames (engine, healing, provider) never
  appear. Re-raise the **same** exception object (`raise error.with_traceback(…)`) — never a
  copy — so hook consumers and `except` clauses keep identity; re-raising the same object adds
  no `__context__` nesting (verified: `__context__` stays None). Non-library exceptions
  (a hook's own bug, `KeyboardInterrupt`) pass through the `except PrettyplayError` filter
  untouched.
- New methods:
  - `get_screenshot() -> image: bytes`: `if self._page is None: raise PrettyplayError("no test
    page yet: run a step first — the page opens lazily on the first step")`; else
    `return self._page.screenshot()` (the facade full-page PNG)
  - `save_screenshot(filepath: str)`: the same no-page guard; `image = self._page.screenshot()`;
    `try: Path(filepath).write_bytes(image)` / `except OSError as error: raise
    PrettyplayError(f"cannot write the screenshot to {filepath}: {error}") from error`.
    Parent directories are **not** created — nothing is created silently
- Semantic requirements (user-approved D2=(a)): the no-page failure of both methods is a
  `PrettyplayError`; write failures are wrapped into `PrettyplayError` naming the path with the
  original `OSError` chained; no screenshot is taken automatically on step failures — the
  decision belongs to the author (no changes to the failure paths); `close()` then
  `get_screenshot()` → the no-page failure (`_page` reset to `None`)
- Imported dependencies: `PrettyplayError` from `prettyplay/failures` (root manifest import —
  already applied at review), `PageFacade`

**Unchanged entities**: `run_step_code` (execution.py), `PrettyplayError`, `LlmUnavailableError`
(failures), `StepReporter.emit` (reporting), `PrettyplayRuntime` / `get_runtime` (runtime.py),
`LocatorFacade` (driver/page.py), the whole `cache` and `llm` cells.

### Interaction Diagram (verbatim from the design)

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

### Data Flows (verbatim from the design)

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

### Re-exports

None — no `->Name: {}` blocks exist in any of the six manifests. The facade obligations of this
plan are the three new `__all__` entries: `FailureVerdict` (failures), `ConfigurationError`
(config), `classify_step_failure` (engine). `driver`, `reporting` and the root `prettyplay`
facades change nothing (no new `__all__` entities; `get_screenshot`/`save_screenshot` are methods
of the exported `PrettyTest`).

### Usages Context

- **`conventions`** (`.goga/usages/conventions.md`) — mandatory Python code/testing rules:
  relative imports, pydantic models, logging levels, Google docstrings, pytest structure
  (`tests/<pkg>/test_<module>.py` mirroring the source tree), mock policy (mocks only at external
  boundaries). Used by all six cells.
- **`pydantic`** (`.goga/usages/cooks/pydantic.md`) — model rules, the `[tool.prettyplay]` schema
  shape, the validation-wrap pattern, the TOML loading fallback; covers the five-value browser
  set, `headless`, `PRETTYPLAY_BROWSER_NAME`, the legacy-variable hint and the
  `ConfigurationError` wrapping. Used by `Config`, `load_config`, `ConfigurationError` rendering.
- **`playwright`** (`.goga/usages/cooks/playwright.md`) — sync-API lifecycle, the engine/channel
  matrix with `headless` (`channel=name if name in ("chrome", "msedge") else None`), locator
  auto-wait, the accessibility snapshot, the scroll primitives (Scrolling section), screenshot;
  no fixed delays. Used by `DriverSession._launch_engine` and `PageFacade`.
- **`generation_prompt`** (engine inline usage) — the system prompt of every generation request;
  gains the scroll-abilities rule line.
- **`classification_prompt`** (engine inline usage) — the system prompt of every classification
  request; "a cached web UI test step" → "a web UI test step"; lives in `classification.py`.

### Imported Usages

- **`taxonomy`** from `prettyplay/failures` (imported by config and root) —
  `prettyplay/failures/.usages/taxonomy.md`. The failure kinds the config error joins and the
  step methods propagate; the verdict semantics and the AssertionError catching guidance.
  Relevance: `ConfigurationError` derives from the documented base; the executor guards the
  verdict event by the two verdict-carrying kinds; the facade folds every `PrettyplayError`.
- **`facade`** from `prettyplay/driver` (imported by engine) —
  `prettyplay/driver/.usages/facade.md`. The single source of the page API surface:
  `PAGE_API_SURFACE` mirrors its 21-row table verbatim (names and order); the scroll rows are
  the model's allowed scrolling vocabulary.
- **`classification`** from `prettyplay/llm` (imported by engine) —
  `prettyplay/llm/.usages/classification.md`. The category semantics (rot / product_defect /
  incurable) and the `provider.classify_failure` call shape used verbatim by
  `classify_step_failure`.
- **`hooks`** from `prettyplay/reporting` (imported by root) —
  `prettyplay/reporting/.usages/hooks.md`. The callback contract `add_hooks` accepts; the
  verdict event ordering (`on_step_failed` → `on_step_verdict`) and the skip rule.
- **`generation`, `healing`** from `prettyplay/engine` (imported by root) —
  `prettyplay/engine/.usages/generation.md`, `prettyplay/engine/.usages/healing.md`. The engine
  cycles the executor delegates to — the failed-check stop, the exhaustion verdict reuse and the
  shared classification routine documented there match the amended manifest.

### Local Usages

None. The design's `.usages/` Update verified all eight cell-level practice files current
(`taxonomy.md`, `hooks.md`, `configuration.md`, `facade.md`, `generation.md`, `healing.md`,
`steps.md`, `lifecycle.md` — already updated by the apply stage). New files: none — every change
lives inside an existing functional domain. **The plan contains no usage-file tasks.**

### External Dependencies

- **playwright** (sync API, installed 1.62.0) — `BrowserType.launch(headless=…, channel=…)`,
  `scroll_into_view_if_needed`, `mouse.wheel`, `evaluate`, `element_handle()` (an
  `ElementHandle` is a `JSHandle` subclass and serializes as a live handle; a raw `Locator`
  argument serializes as `undefined`), `expect` raising `AssertionError`.
- **pydantic v2** — `BaseModel`, `ConfigDict(kw_only=True)`, `Literal`, `PositiveInt`, lax bool
  coercion of env strings, `ValidationError.errors()`.
- **pytest** (fixtures: `tmp_path`, `monkeypatch`, `caplog`, `pytest.raises`).
- **ruff** (0.16.6; line-length 120; the prompt constants in `generator.py` carry an E501
  per-file ignore — extend the ignore to `classification.py` in `pyproject.toml` if the moved
  `CLASSIFICATION_PROMPT` trips E501; `pyproject.toml` is not a CODEMANIFEST and may be edited
  for tooling).
- **stdlib** — `types.TracebackType(tb_next, tb_frame, tb_lasti, tb_lineno)` (the only valid
  constructor form — `filename`/`name` derive from the frame automatically),
  `traceback.extract_tb`, `tomllib` / `tomli` on 3.10, `pathlib.Path`, `logging`.
- Project venv: all commands run through `.venv/bin/python` and `.venv/bin/ruff`.

## Facts

- The six changed `CODEMANIFEST` files (failures, reporting, config, driver, engine, root) are
  **already applied to the tree and lint-clean** (`goga lint`: 8 cells, 0 errors); they are
  read-only contract definitions for this plan.
- All cell `.usages/` files and the two project cooks (`playwright.md`, `pydantic.md`) are
  already updated and verified consistent — no documentation tasks.
- Both contract-defect fixes from the design review are already in the manifests: `FailureVerdict`
  imported by engine, `PrettyplayError` imported by root; the `regenerate` "three additions"
  annotation is amended.
- The dependency graph needs no new edges: `config → failures` already exists; engine imports are
  stable down the graph (llm/cache untouched).
- The current test suite collects **308 tests** and passes; the known breakage registry of
  existing tests is listed in the Gap Analysis and each breakage is fixed inside its own task.
- The project venv is `.venv/` (Python 3.12, playwright 1.62.0, pydantic v2, ruff 0.16.6);
  plain `python` outside the venv has no playwright — always use `.venv/bin/…`.
- Some legacy tests carry Russian sample data; per the design, all **new/rewritten** test
  examples use English sample data (minimal in-place patches may keep legacy data).
- `CLASSIFICATION_PROMPT` moves from `generator.py` to `classification.py` (its only consumer) —
  this breaks the would-be import cycle; `GENERATION_PROMPT` and `PAGE_API_SURFACE` stay in
  `generator.py`.
- `errors.py`, `models.py`, `loader.py`, `session.py`, `page.py`, `generator.py`, `healer.py`,
  `hooks.py`, `executor.py`, `scenario.py` all exist with their current (pre-change)
  implementations — this plan modifies them; only `engine/classification.py` is a new source
  file.

## Gap Analysis

- **Missing contract entities**:
  - `FailureVerdict` (errors.py) — absent.
  - `ConfigurationError` (config/loader.py) — absent; loader leaks raw `ValidationError`.
  - `classify_step_failure` + `engine/classification.py` — file absent; prompt lives in
    `generator.py` with the "cached" wording.
  - `StepHooks.on_step_verdict` (reporting/hooks.py) — absent (8 events, contract says 9).
  - 8 `PageFacade` scroll methods (driver/page.py) — absent.
  - `PrettyTest.get_screenshot` / `save_screenshot` (scenario.py) — absent.
  - `Config.headless` (config/models.py) — absent; browser Literal is the old 3-value set.
- **Missing facade exposure**: `FailureVerdict`, `ConfigurationError`, `classify_step_failure`
  absent from the respective `__all__`.
- **Incorrect `location` placement**: none — `classification.py` will be created at its declared
  location.
- **API mismatches**:
  - `ProductDefectError(step_text, message)` — no `verdict` param, no `AssertionError` base,
    `__str__` prefixes "product defect on step …".
  - `IncurableStepError(step_text, reason, recommendation)` — takes a recommendation **string**,
    no `verdict`, no derived property, no fallback.
  - `load_config` — reads `PRETTYPLAY_BROWSER` (removed name) instead of
    `PRETTYPLAY_BROWSER_NAME`; no `PRETTYPLAY_BROWSER_HEADLESS`; no legacy check; no
    `ConfigurationError` wrapping.
  - `_launch_engine` — `engine.launch()` with no `headless`/`channel`; `chrome`/`msedge` raise
    `KeyError` in the engine map.
  - `_loop` — catches every candidate failure as retryable (failed checks are retried); budget
    exhaustion raises with a legacy recommendation string, no classification, no verdict, no
    quiet-skip WARNING.
  - `heal` — classifies inline (not via the shared routine), raises verdict-less errors, no
    regeneration-exhaustion verdict reuse, no `raise … from incurable`.
  - `execute` failure branch — no `on_step_verdict` event.
  - `action`/`assertion` — no traceback folding; scenario.py already imports `TracebackType`
    (used by `__exit__` annotation only).
  - `GENERATION_PROMPT` — no scroll rule; `CLASSIFICATION_PROMPT` — "cached" wording;
    `PAGE_API_SURFACE` — 13 rows, no scroll lines.
- **Behavioral mismatches**: same list — every algorithm section of the design describes target
  behavior the current code does not implement.
- **Existing code that can be reused**: `_find_pyproject` / `_collect_env_overrides` skeleton
  (rename map on top), the `_loop` skeleton (spend/attempt/emit structure), `PlaywrightWorker`
  and the `_call` marshalling, `StepReporter.emit` INFO default (no reporter change needed),
  `first_line_short`, the existing test fakes (`FakePlaywrightFactory`, `ClassificationProvider`,
  `SpyGenerator`, `RecordingHooks`-style recorders).
- **Test coverage gaps** (all scenarios are specified in the design and embedded into the tasks
  below): 20 positive + 7 negative + 6 edge-case scenarios, plus the review additions
  (`EVENT_SIGNATURES` verdict entry, `test_verdict_event_logged_at_info`,
  `test_classify_step_failure_without_screenshots`, the no-verdict `__str__` assert) and the
  integration hook-list expectations.
- **Known breakage registry of existing tests** (each fixed inside its own task):
  - `tests/failures/test_errors.py` — 2/3-arg constructors and the `recommendation` param.
  - `tests/config/test_loader.py:63` — `PRETTYPLAY_BROWSER` now raises; the
    `_ALL_ENV_FIELDS` fixture list must become `BROWSER_NAME` / `BROWSER_HEADLESS`.
  - `tests/engine/test_generator.py:238,308`, `tests/engine/test_healer.py`,
    `tests/test_executor.py:198–288` — error constructors and recommendation fallbacks.
  - `tests/engine/test_generator.py:368` — the prompt text check (prompt moved + no "cached").
  - `tests/engine/test_healer.py` and `tests/engine/test_generator.py:11–15` — the
    `CLASSIFICATION_PROMPT` import path changes to `prettyplay.engine.classification` (the
    generator test file imports it at module level — a collection-time breakage of the whole
    file).
  - `tests/test_integration.py:402,431` — both verdict-carrying failure tests
    (`test_product_defect_verdict_fails_the_test_loudly`,
    `test_incurable_verdict_fails_with_verdict_fields`) must expect `on_step_verdict` after
    `on_step_failed` in their hook-event list assertions.
- **Missing visibility in workspace or git**: none — all touched files are tracked.

---

## Tasks

> **Package ordering rule**: coding tasks for each package are completed before starting the next.
> Within each coding task, contract tests are written first (TDD workflow). Only ONE task is
> executed per ralphex iteration. After each task: REVIEW → APPROVAL → NEXT TASK.
>
> Package order: `prettyplay/failures` → `prettyplay/config` → `prettyplay/driver` →
> `prettyplay/engine` → `prettyplay/reporting` → `prettyplay` (root) → integration.

### Task 1: `FailureVerdict` and the verdict-carrying error types (failures)

Implement the verdict transport of terminal failures in `prettyplay/failures/errors.py` and
export it from the facade. Three contract entities change in one location: the new
`FailureVerdict` entity (a frozen stdlib value object — **not** a pydantic model; the failures
cell is the stdlib-only leaf, `FailureClassification` already validated the source data, and
pydantic models inside exception payloads add construction cost on failure paths — a conscious,
documented deviation), `ProductDefectError` (gains the `verdict` field, the `AssertionError`
base and the folded-traceback requirement satisfied at the facade boundary), and
`IncurableStepError` (the `recommendation` param is replaced by the derived property with the
built-in fallback). `PrettyplayError` and `LlmUnavailableError` stay unchanged.

**Usages relevant to this task:**
- `conventions`: Google docstrings, relative imports, tests at `tests/failures/test_errors.py`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/failures/test_errors.py`; expected to fail at this stage):
  facade exposes `FailureVerdict` (`from prettyplay.failures import FailureVerdict` works;
  `__all__` lists the five names); `inspect.signature(FailureVerdict.__init__)` parameters are
  `category`, `explanation`, `recommendation`; `render` is a callable method;
  `ProductDefectError.__init__` parameters are `step_text`, `message`, `verdict` (default
  `None`); `IncurableStepError.__init__` parameters are `step_text`, `reason`, `verdict`
  (default `None`); `issubclass(ProductDefectError, AssertionError)` and
  `issubclass(ProductDefectError, PrettyplayError)`
- [ ] **Code**: add `FailureVerdict` — `@dataclass(frozen=True)` with
  `category: str`, `explanation: str`, `recommendation: str` and
  `render() -> str`: build one line per non-empty field (`f"category: {self.category}"`,
  `f"explanation: {self.explanation}"`, `f"recommendation: {self.recommendation}"`; an empty
  field yields no line), join with `"\n"`
- [ ] **Code**: rework `ProductDefectError` — bases `(PrettyplayError, AssertionError)`;
  `__init__(self, step_text: str, message: str, verdict: FailureVerdict | None = None)` stores
  the three fields and calls `PrettyplayError.__init__(message)` (`args` carry the primary
  reason only); `__str__` returns `message`, then appends `"\n" + verdict.render()` when the
  verdict is present (never interleaved, no step-text prefix)
- [ ] **Code**: rework `IncurableStepError` — bases `(PrettyplayError,)` only, never
  `AssertionError`; `__init__(self, step_text: str, reason: str, verdict: FailureVerdict | None
  = None)`; `recommendation` becomes a derived `@property`
  (`self.verdict.recommendation` when the verdict is present, otherwise the built-in path
  guidance `"reword the step or refresh the cache"`); `__str__` returns `reason`, then appends
  `"\n" + verdict.render()` when present, otherwise `"\nrecommendation: " + <built-in path
  guidance>`
- [ ] **Code**: add `FailureVerdict` to `prettyplay/failures/__init__.py` imports and `__all__`
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/failures/ -q` — contract
  tests pass
- [ ] **Logic tests** (design scenarios, English sample data; update the legacy tests that
  construct the old signatures in the same file):
  - `test_render_lists_all_fields`: `FailureVerdict("rot", "the button was renamed", "refresh
    the cache").render().splitlines() == ["category: rot", "explanation: the button was
    renamed", "recommendation: refresh the cache"]`
  - `test_render_skips_empty_fields`: `FailureVerdict("rot", "", "refresh the cache").render()
    == "category: rot\nrecommendation: refresh the cache"`
  - `test_product_defect_is_assertion_and_library_error`: isinstance checks for both bases with
    and without a verdict; add
    `str(ProductDefectError("step", "expected x, observed y", None)) == "expected x, observed y"`
    (the message without the verdict tail)
  - `test_product_defect_str_appends_verdict_render`: `str(...)` starts with
    `"expected x, observed y"`, contains `"category: product_defect"` and
    `"recommendation: rec"`, and `s.index("expected x, observed y") < s.index("category:")`
  - `test_incurable_recommendation_comes_from_verdict`:
    `IncurableStepError("s", "budget exhausted", FailureVerdict("incurable", "e", "reword the
    step")).recommendation == "reword the step"`
  - `test_incurable_fallback_recommendation_without_verdict`: with verdict `None` —
    `error.recommendation == "reword the step or refresh the cache"`;
    `str(error).startswith("budget exhausted")`; the fallback recommendation line present;
    `not isinstance(error, AssertionError)`
  - fix the registered breakages in this file: 2/3-arg constructors and the `recommendation`
    param now construct `FailureVerdict` objects (English sample data in rewritten examples)
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — fix implementation code until all
  tests pass (do NOT fix test code)
- [ ] **Contract re-verification**: `.venv/bin/python -c "from prettyplay.failures import
  FailureVerdict, ProductDefectError, IncurableStepError, LlmUnavailableError, PrettyplayError"` —
  facade, API shape and behavior intact
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/failures/` — fix formatting if necessary

### Task 2: `Config` browser channels and `headless` (config)

Extend the validated settings model in `prettyplay/config/models.py`: the browser `Literal`
grows from the 3-value matrix to the five-value set `{chromium, firefox, webkit, chrome,
msedge}`, and the new `headless: bool = True` field arrives (`chrome`/`msedge` are valid
settings whose launch semantics live in the driver — this task only widens the model). One
contract entity, one location; the loader task follows.

**Usages relevant to this task:**
- `conventions`: pydantic models kw_only with empty defaults.
- `pydantic`: the `[tool.prettyplay]` schema shape — the five-value browser set and `headless`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/config/test_models.py`; expected to fail): `Config()` has
  `headless is True` and `browser == "chromium"`; constructing with each of the five browser
  names and `headless=False` type-checks via the field set (a `headless` kwarg exists)
- [ ] **Code**: in `models.py` change `browser: Literal["chromium", "firefox", "webkit",
  "chrome", "msedge"] = "chromium"` and add `headless: bool = True` (after `send_screenshots`);
  update the class docstring Attributes for both fields (browser — the five-value set with the
  channel note; headless — runs the browser without a visible window, default True)
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/config/test_models.py -q`
- [ ] **Logic tests** (design scenarios):
  - `test_config_headless_default_and_browser_channels`: `Config().headless is True`;
    `Config().browser == "chromium"`; every name of
    `("chromium", "firefox", "webkit", "chrome", "msedge")` accepted;
    `Config(headless=False).headless is False`
  - `test_unknown_browser_rejected_at_model`:
    `pytest.raises(ValidationError, Config, browser="netscape")`
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/config/ -x` — fix implementation until
  green
- [ ] **Contract re-verification**: facade import `from prettyplay.config import Config` and the
  declared field surface (including the unchanged `effective_*` properties)
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/config/`

### Task 3: `ConfigurationError` and the loud `load_config` (config)

Implement the invalid-configuration failure and the loader changes in
`prettyplay/config/loader.py`: the `PrettyplayError::ConfigurationError` mutation (the loaded
`[tool.prettyplay]` section failed validation), the legacy `PRETTYPLAY_BROWSER` check, the two
special env names, and the per-setting validation rendering with the original `ValidationError`
chained. A raw pydantic error never leaves the loader.

**Usages relevant to this task:**
- `conventions`: relative imports (`from ..failures.errors import PrettyplayError`), test
  structure `tests/config/test_loader.py`.
- `pydantic`: the validation-wrap pattern (`raise … from error`), the TOML loading fallback,
  lax bool coercion of env strings.
- `taxonomy` (imported from `prettyplay/failures`): the failure base the configuration error
  joins — catchable with the single library except clause; never carries a verdict.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/config/test_loader.py`; expected to fail):
  `from prettyplay.config import ConfigurationError` works; `issubclass(ConfigurationError,
  PrettyplayError)`; `inspect.signature(ConfigurationError.__init__)` is the single `message`
- [ ] **Code**: define `ConfigurationError(PrettyplayError)` in `loader.py` (no new `__init__`
  needed — `.message` exposes the rendered actionable text via the base); import
  `PrettyplayError` from `..failures.errors` and `ValidationError` from `pydantic`
- [ ] **Code**: add the legacy check — before merging, `if "PRETTYPLAY_BROWSER" in os.environ:
  raise ConfigurationError("PRETTYPLAY_BROWSER is no longer supported: use
  PRETTYPLAY_BROWSER_NAME")` (user-approved D1=(a): loud, actionable, names both variables)
- [ ] **Code**: rework the env name map — `browser → PRETTYPLAY_BROWSER_NAME`,
  `headless → PRETTYPLAY_BROWSER_HEADLESS`, every other field →
  `"PRETTYPLAY_" + field.upper()`; a set variable wins (empty string included); add `headless`
  to the overridable fields
- [ ] **Code**: wrap the `Config(**merged)` construction — `except ValidationError as error:
  raise ConfigurationError(_render_validation(error)) from error`; `_render_validation` builds
  one line per entry of `error.errors()`:
  `f"{field}: received {input!r} — allowed: {ALLOWED.get(field, entry.msg)}"` with the static
  map (provider → `openai, anthropic`; browser → `chromium, firefox, webkit, chrome, msedge`;
  generation_attempts / healing_attempts → `a positive integer`; headless → `a boolean`; the
  string model/base_url/cache_root fields → `a non-empty string`; fallback → the pydantic
  message), lines joined with `"\n"`
- [ ] **Code**: add `ConfigurationError` to `prettyplay/config/__init__.py` imports and
  `__all__`
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/config/test_loader.py -q`
- [ ] **Logic tests** (design scenarios; `tmp_path` pyproject files, `monkeypatch.setenv` /
  `delenv`):
  - `test_load_env_browser_name_and_headless`: pyproject with `browser = "chromium"`; set
    `PRETTYPLAY_BROWSER_NAME=firefox` and `PRETTYPLAY_BROWSER_HEADLESS=false` →
    `config.browser == "firefox"`, `config.headless is False` (pydantic coerces `"false"`)
  - `test_configuration_error_wraps_validation_with_lines`: pyproject with
    `browser = "netscape"` and `generation_attempts = 0` → `ConfigurationError` raised;
    `isinstance(excinfo.value, PrettyplayError)`; the message contains `"browser"`,
    `"netscape"`, `"chromium, firefox, webkit, chrome, msedge"`, `"generation_attempts"`;
    `str(excinfo.value).count("\n") == 1` (exactly two lines, one per setting);
    `isinstance(excinfo.value.__cause__, ValidationError)`
  - `test_legacy_browser_env_raises_configuration_error`: valid pyproject;
    `monkeypatch.setenv("PRETTYPLAY_BROWSER", "firefox")` → `ConfigurationError` with
    `"PRETTYPLAY_BROWSER_NAME"` in the message
  - fix the registered breakage in this file: the test at `tests/config/test_loader.py:63` uses
    the removed `PRETTYPLAY_BROWSER` override — switch it to `PRETTYPLAY_BROWSER_NAME`; update
    the `_ALL_ENV_FIELDS` autouse fixture list (`BROWSER` → `BROWSER_NAME`, add
    `BROWSER_HEADLESS`)
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — fix implementation until green
- [ ] **Contract re-verification**: `from prettyplay.config import ConfigurationError,
  Config, load_config`; `FileNotFoundError` behavior (no pyproject found) unchanged
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/config/`

### Task 4: headless and channel launch in `DriverSession` (driver)

Launch the configured browser engine with `headless` from the settings and the channel
mechanism for the `chrome`/`msedge` values: `prettyplay/driver/session.py`, method
`_launch_engine`. The config cell is complete (Task 2), so `config.headless` and the five-value
browser set exist. A missing channel browser fails loudly through Playwright's native `Error`
(which names the distribution and the `playwright install <name>` remedy) — propagate as-is,
invent no new failure kind in the driver cell.

**Usages relevant to this task:**
- `conventions`: mocks only at the external Playwright boundary (stub engines), tests at
  `tests/driver/test_session.py`.
- `playwright`: the engine/channel matrix —
  `channel=name if name in ("chrome", "msedge") else None`, then
  `engine.launch(headless=config.headless[, channel=…])`; bundled engines launch with `headless`
  only (no `channel` kwarg).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/driver/test_session.py`; expected to fail): with
  `Config(browser="msedge", headless=False)`, `_launch_engine` selects the chromium engine and
  calls `launch(headless=False, channel="msedge")`; with `Config()`,
  `launch` receives exactly `{"headless": True}` (no channel)
- [ ] **Code**: in `_launch_engine` — `name = self._config.browser`; if
  `name in ("chrome", "msedge")`: `engine = playwright.chromium`, `channel = name`; else
  `engine = ENGINES[name]`, `channel = None`; return
  `engine.launch(headless=self._config.headless, channel=channel)` when a channel exists,
  otherwise `engine.launch(headless=self._config.headless)`
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/driver/test_session.py -q`
- [ ] **Logic tests** (design scenario):
  - `test_launch_passes_headless_and_channel`: `Config(browser="msedge", headless=False)` with
    a stub engine recording `launch(**kwargs)` patched into the engine map →
    `fake_chromium.launch.call_args.kwargs == {"headless": False, "channel": "msedge"}`; and
    for `Config()`: `fake_chromium.launch.call_args.kwargs == {"headless": True}`
  - update the existing `FakeEngine.launch()` fake to accept and record `**kwargs`; extend the
    existing launch tests where the recorded name for `chrome`/`msedge` is now `chromium` with
    a channel
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/driver/ -x` — fix implementation until
  green
- [ ] **Contract re-verification**: `from prettyplay.driver import DriverSession, PageFacade`;
  the lazy `_launch`/`open_context` flow and the failed-launch cleanup are unchanged
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/driver/`

### Task 5: the 8 scroll methods of `PageFacade` (driver)

Add the scroll abilities to `prettyplay/driver/page.py` — the explicit programmatic scrolling
surface for scenario steps: `scroll_to_element`, `scroll_down`, `scroll_up`,
`scroll_to_bottom`, `scroll_to_top`, `scroll_into_view`, `scroll_container_down`,
`scroll_container_up`. Every call is marshalled through `self._call(...)` into the driver thread
(existing pattern); no sleeps anywhere — the scrolled state is awaited by the follow-up locators
and expectations. This surface is a backward-compatibility contract (extend, never rename or
remove).

**Usages relevant to this task:**
- `conventions`: tests at `tests/driver/test_page.py`.
- `playwright`: the scroll primitives (Scrolling section) —
  `scroll_into_view_if_needed()` (nearest scrollable ancestor), `mouse.wheel(0, ±pixels)`,
  `evaluate` with `window.scrollTo`, container `scrollTop` adjustment; `element_handle()` for
  resolving a locator into a serializable live handle (an `ElementHandle` is a `JSHandle`
  subclass; a raw `Locator` passed as an evaluate argument serializes as `undefined` in
  playwright-python — verified empirically at design review).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/driver/test_page.py`; expected to fail): all 8 methods
  exist on `PageFacade` and are callable with the declared arities
  (`scroll_down(pixels)`, `scroll_into_view(element, container)`,
  `scroll_container_down(container, pixels)`, …)
- [ ] **Code**: implement the primitive mapping (each body wrapped in `self._call`):
  - `scroll_to_element(element)` → `element._locator.scroll_into_view_if_needed()`
  - `scroll_down(pixels)` / `scroll_up(pixels)` → `self._page.mouse.wheel(0, pixels)` /
    `wheel(0, -pixels)`
  - `scroll_to_bottom()` → `self._page.evaluate("window.scrollTo(0,
    document.body.scrollHeight)")`; `scroll_to_top()` → `evaluate("window.scrollTo(0, 0)")`
  - `scroll_into_view(element, container)` → `handle = element locator .element_handle()`
    (auto-waits), then one container evaluation centering the target:
    `container.evaluate("(el, target) => { const cr = el.getBoundingClientRect(); const tr =
    target.getBoundingClientRect(); el.scrollTop += tr.top - cr.top - (el.clientHeight -
    tr.height) / 2; }", handle)` — the `ElementHandle` is passed as the evaluate argument
  - `scroll_container_down(container, pixels)` / `scroll_container_up(container, pixels)` →
    `container.evaluate("(el, px) => { el.scrollTop += px; }", pixels)` /
    `el.scrollTop -= px`
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/driver/test_page.py -q`
- [ ] **Logic tests** (design scenario — `PageFacade(fake_page, fake_context)` with a recording
  fake page, inline calls, a real `LocatorFacade` over a recording fake locator):
  - `test_scroll_primitives_delegate_to_playwright`: `page.scroll_down(600)` /
    `scroll_up(300)` → `fake.mouse.wheel_calls == [(0, 600), (0, -300)]`;
    `scroll_to_bottom()` / `scroll_to_top()` →
    `fake.evaluate_calls[0].startswith("window.scrollTo(0, document.body.scrollHeight)")`;
    `scroll_to_element(el)` → `element.scroll_into_view_called is True`;
    `scroll_into_view(el, cont)` → `el_handle = fake_element.element_handle()` and
    `fake_container.evaluate(<js with target arg>, el_handle)`;
    `scroll_container_down(cont, 400)` / `scroll_container_up(cont, 200)` →
    `container.evaluate_args[-1] == 200` with `"scrollTop -="` in the js,
    `container.evaluate_args[-2] == 400` with `"scrollTop +="`;
    `"scrollTop +=" in container.evaluate_calls[-3][0]` and
    `"getBoundingClientRect" in container.evaluate_calls[-3][0]` (the centering math)
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/driver/ -x` — fix implementation until
  green
- [ ] **Contract re-verification**: `from prettyplay.driver import PageFacade, LocatorFacade`;
  the existing locating/snapshot/screenshot/close surface untouched
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/driver/`

### Task 6: the shared `classify_step_failure` routine (engine)

Create `prettyplay/engine/classification.py` — the single classification call for both engines —
and move `CLASSIFICATION_PROMPT` there from `generator.py` (its only consumer; the placement
breaks the would-be import cycle `classification` ← prompt ← `generator` ← routine ←
`classification`). The prompt text drops "cached": "a cached web UI test step" → "a web UI test
step". Export the routine from the engine facade.

**Usages relevant to this task:**
- `conventions`: tests at the new `tests/engine/test_classification.py` mirroring the source
  tree.
- `classification` (imported from `prettyplay/llm`,
  `prettyplay/llm/.usages/classification.md`): the category semantics (rot / product_defect /
  incurable) and the exact `provider.classify_failure` call shape used verbatim by the routine.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (new file `tests/engine/test_classification.py`; expected to fail):
  `from prettyplay.engine import classify_step_failure` works (facade); the routine is callable
  with the six declared parameters `(config, provider, step_text, code, error, page)`
- [ ] **Code**: create `prettyplay/engine/classification.py` with `CLASSIFICATION_PROMPT` (the
  moved text, "a web UI test step" wording) and
  `classify_step_failure(config, provider, step_text, code, error, page) ->
  FailureClassification`: `snapshot = page.aria_snapshot()`; `screenshot = page.screenshot() if
  config.send_screenshots else None`; `return provider.classify_failure(
  prompt=CLASSIFICATION_PROMPT, step_text=step_text, code=code, error=error,
  snapshot=snapshot, screenshot=screenshot)`; `LlmUnavailableError` propagates untouched — this
  routine never swallows it
- [ ] **Code**: remove `CLASSIFICATION_PROMPT` from `generator.py`; keep `GENERATION_PROMPT`
  and `PAGE_API_SURFACE` there; update `healer.py` to import it from `.classification` (the
  healer body still calls the provider inline until Task 8 — only the import path moves now);
  add `classify_step_failure` to `prettyplay/engine/__init__.py` imports and `__all__`
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/engine/ -q`
- [ ] **Logic tests** (design scenarios; `FakePage` with snapshot `"body: main"` and `b"png"`,
  a fake provider returning `FailureClassification`, `Config(send_screenshots=True)`):
  - `test_classify_step_failure_collects_and_calls_port`: `result.category == "rot"`;
    `kwargs = provider.classify_failure_calls[0]`; `kwargs["step_text"] == "click Sign in"`;
    `kwargs["error"] == "TimeoutError"`; `kwargs["snapshot"] == "body: main"`;
    `kwargs["screenshot"] == b"png"`;
    `kwargs["prompt"].startswith("You classify a failure of a web UI test step.")`;
    `"cached" not in kwargs["prompt"]`
  - `test_classify_step_failure_without_screenshots` (review addition):
    `Config(send_screenshots=False)` → the `screenshot` kwarg is `None` and
    `page.screenshot_calls == 0`
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — fix implementation until green
  (including the `CLASSIFICATION_PROMPT` import-path breakages in `tests/engine/test_healer.py`
  and `tests/engine/test_generator.py`: drop `CLASSIFICATION_PROMPT` from the
  `prettyplay.engine.generator` import block of both files — the frozen-prompt test of Task 7
  imports it from `prettyplay.engine.classification`)
- [ ] **Contract re-verification**: `from prettyplay.engine import classify_step_failure,
  StepGenerator, StepHealer, run_step_code`; the port keyword signature matches the call kwargs
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/` — if the moved prompt trips E501,
  extend the `pyproject.toml` per-file-ignores with `prettyplay/engine/classification.py`
  (`pyproject.toml` is tooling, not a CODEMANIFEST)

### Task 7: the failed-check stop and exhaustion classification in `StepGenerator` (engine)

Rework the shared loop of `prettyplay/engine/generator.py` per the design algorithm: the
failed-check classification stop (a candidate `AssertionError` stops the retries immediately
and is classified — the attempt budget is never spent on a legitimately failing assertion), the
budget-exhaustion classification of the last candidate (generation pool only; the healing pool
exhaustion raises without classification — the healer attaches its verdict, no extra LLM
request), the quiet verdict skip on unavailable classification (WARNING on the logger
`prettyplay`), the `_verdict` helper, and the two prompt/surface constant updates. `generate`
and `regenerate` keep their signatures.

**Usages relevant to this task:**
- `conventions`: tests at `tests/engine/test_generator.py`; `caplog` for the WARNING check.
- `generation_prompt` (engine inline usage): gains the scroll-abilities rule line (verbatim
  below).
- `facade` (imported from `prettyplay/driver`): the single source of `PAGE_API_SURFACE` — the
  8 scroll rows mirror `prettyplay/driver/.usages/facade.md` names and order; the listing and
  the practice change together (a test makes this mechanical).
- `classification` (imported from `prettyplay/llm`): the categories the verdict branches on.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/engine/test_generator.py`; expected to fail): `generate`
  and `regenerate` signatures unchanged (identity, step_text, previous_steps, page[, 
  existing_code, error]); the module exposes `GENERATION_PROMPT` and `PAGE_API_SURFACE` and no
  longer exposes `CLASSIFICATION_PROMPT`
- [ ] **Code**: rework `_loop` to the design algorithm — spend refused branch: `reason =
  f"{pool} attempt budget exhausted"` (+ `f"; last failure: {error}"` when a candidate failure
  is recorded); `pool == "healing"` → `raise IncurableStepError(step_text, reason, None)` (the
  healer attaches its verdict); `error is None` → `raise IncurableStepError(step_text, reason,
  None)` (nothing to classify); otherwise try `verdict = _verdict(classify_step_failure(…,
  last_code, error, page))`, on `LlmUnavailableError` log
  `logging.getLogger("prettyplay").warning("verdict skipped: llm unavailable")` and raise
  `IncurableStepError(step_text, reason, None)`, else raise `IncurableStepError(step_text,
  reason, verdict)` — the exhaustion classification runs on the generation pool only
- [ ] **Code**: add the failed-check branch before the retryable branch — `except
  AssertionError as check_failure:` (do not spend another attempt): `reason = f"candidate
  check failed: {first_line_short(check_failure)}"`; try the classification; on
  `LlmUnavailableError` the same quiet-skip WARNING and `IncurableStepError(step_text, reason,
  None)`; `verdict.category == "product_defect"` → `raise ProductDefectError(step_text,
  first_line_short(check_failure), verdict)`; any other verdict → `raise
  IncurableStepError(step_text, reason, verdict)`. The retryable branch (`except Exception`)
  and the success exit stay as they are
- [ ] **Code**: add `_verdict(classification) -> FailureVerdict` returning
  `FailureVerdict(classification.category, classification.explanation,
  classification.recommendation)` — the helper lives here in the engine, not in the failures
  cell ("built by the engines; the failure types never request it themselves"); import
  `FailureVerdict` and `classify_step_failure`
- [ ] **Code**: update the constants — `GENERATION_PROMPT` gains the line after the locating
  rule: `- Scroll abilities exist for scenario scrolling: bring an element into view, scroll by
  an amount, to the page end or start, inside a scrollable container`;
  `PAGE_API_SURFACE` gains the 8 scroll rows after the `page.url` line (mirroring `facade.md`
  order/purposes: `page.scroll_to_element(element)` — bring an element into the viewport (works
  inside scrollable ancestors); `page.scroll_down(pixels)` — scroll the page down by an amount;
  `page.scroll_up(pixels)` — scroll the page up by an amount; `page.scroll_to_bottom()` —
  scroll to the end of the page; `page.scroll_to_top()` — scroll to the start of the page;
  `page.scroll_into_view(element, container)` — bring an element into view inside a specific
  scrollable container; `page.scroll_container_down(container, pixels)` — scroll a scrollable
  container down by an amount; `page.scroll_container_up(container, pixels)` — scroll a
  scrollable container up by an amount)
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/engine/test_generator.py -q`
- [ ] **Logic tests** (design scenarios; fakes at the provider/page boundaries, English sample
  data):
  - `test_generate_failed_check_product_defect_stops_and_carries_verdict`: first candidate is
    `def step(page):\n    page.find_by_text('Welcome back').expect_visible()` (raises
    `AssertionError('banner missing')` when executed — the `FakePage`'s find_by_text handle is
    programmed so the expectation fails with that message); classification returns
    `product_defect`; `RunBudgets(3, 2)` → `ProductDefectError` raised;
    `excinfo.value.verdict.category == "product_defect"`; `"banner missing" in
    str(excinfo.value)`; `provider.generate_step_code_call_count == 1` (retries stopped at
    once); `provider.classify_failure_call_count == 1`
  - `test_generate_failed_check_non_defect_verdict_raises_incurable` (review addition): the
    same failed-check setup, classification returns
    `FailureClassification("incurable", "the step is ambiguous", "reword the step")` →
    `IncurableStepError`; `excinfo.value.reason.startswith("candidate check failed")`;
    `excinfo.value.verdict.category == "incurable"`; both provider call counts == 1
  - `test_generate_exhaustion_classifies_last_candidate`: `RunBudgets(1, 2)`; candidates always
    raise `TimeoutError` (non-assertion); classification returns `incurable` →
    `excinfo.value.reason.startswith("generation attempt budget exhausted")`;
    `"last failure:" in excinfo.value.reason`; `excinfo.value.verdict.category == "incurable"`
  - `test_generate_quiet_verdict_skip_on_unavailable_classification`: candidate raises
    `AssertionError`; `FakeProvider.classify_failure` raises `LlmUnavailableError("openai
    down")`; `caplog` at WARNING on the `prettyplay` logger → `IncurableStepError` with
    `verdict is None`; `reason.startswith("candidate check failed")`;
    `any("verdict skipped" in r.message for r in caplog.records if r.levelno ==
    logging.WARNING)`
  - `test_generate_provider_request_unavailable_no_retry`:
    `FakeProvider.generate_step_code` raises `LlmUnavailableError("openai down")`;
    `RunBudgets(3, 2)` → propagates; `provider.generate_step_code_call_count == 1`
  - `test_generate_first_refusal_without_candidate` (edge): `RunBudgets(1, 2)`; spend the
    generation budget beforehand via a prior successful generate-equivalent call on the same
    identity; second `generate` → `excinfo.value.reason == "generation attempt budget
    exhausted"`; `excinfo.value.verdict is None`;
    `provider.classify_failure_call_count == 0`
  - `test_page_api_surface_mirrors_facade_practice` (edge): parse
    `prettyplay/driver/.usages/facade.md` table's `page.*` calls and compare with the
    constant's `page.*` lines (names and order) —
    `surface_calls == ["page.open(url)", "page.find_by_role(role, name)",
    "page.find_by_label(label)", "page.find_by_text(text)", "page.aria_snapshot()",
    "page.screenshot()", "page.url", "page.scroll_to_element(element)",
    "page.scroll_down(pixels)", "page.scroll_up(pixels)", "page.scroll_to_bottom()",
    "page.scroll_to_top()", "page.scroll_into_view(element, container)",
    "page.scroll_container_down(container, pixels)",
    "page.scroll_container_up(container, pixels)"]`
  - fix the registered breakages in this file: the error-constructor tests at
    `tests/engine/test_generator.py:238,308` (recommendation fallbacks → verdict form) and the
    prompt text check at `:368` (the moved/updated prompts)
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — fix implementation until green
- [ ] **Contract re-verification**: `generate`/`regenerate` signatures, the three-additions
  semantics of `regenerate` (existing_code+error on every request; `try_healing` pool;
  no-classification exhaustion), verdicts fully reaching the raised errors
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/`

### Task 8: verdicts and the exhaustion reuse in `StepHealer` (engine)

Rework `heal` in `prettyplay/engine/healer.py`: classify through the shared routine (Task 6),
build the verdict, raise verdict-carrying errors on the product_defect and incurable branches,
reuse the step-1 verdict on regeneration exhaustion without a second LLM request, and let a
fresh failed-check verdict from regeneration win. Anti-masking holds: a classified product
defect always fails the test.

**Usages relevant to this task:**
- `conventions`: tests at `tests/engine/test_healer.py`; call counters on the fake provider.
- `classification` (imported from `prettyplay/llm`): the categories driving the branches.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/engine/test_healer.py`; expected to fail): `heal` signature
  unchanged `(step, error, previous_steps, page)`; the healer constructs `FailureVerdict`
  objects (no string third arguments anywhere in the file)
- [ ] **Code**: replace the inline classification with `classification =
  classify_step_failure(config, provider, step_text, step.code, error, page)`
  (`LlmUnavailableError` propagates — an explicit infrastructure failure) and `verdict =
  FailureVerdict(classification.category, classification.explanation,
  classification.recommendation)`; `emit("on_healing_started", {step_text, category})`
- [ ] **Code**: `product_defect` → `raise ProductDefectError(step_text,
  classification.explanation, verdict)`; `incurable` → `raise IncurableStepError(step_text,
  classification.explanation, verdict)`
- [ ] **Code**: `rot` → `healed = generator.regenerate(...)` inside
  `try: … except IncurableStepError as incurable:` — if `incurable.verdict is None`
  (regeneration exhaustion): `raise IncurableStepError(step_text, incurable.reason, verdict)
  from incurable` (the step-1 verdict; the reason already names the exhausted pool); else
  re-raise as-is (a fresh failed-check verdict is never overwritten). On success:
  `emit("on_healed", {step_text, explanation})`, return `healed`
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/engine/test_healer.py -q`
- [ ] **Logic tests** (design scenarios; English sample data, fake provider with scripted
  sequences and call counters):
  - `test_heal_product_defect_carries_full_verdict`: classification
    `FailureClassification("product_defect", "expected the total 100, observed 90", "file a
    bug")` → `excinfo.value.verdict.recommendation == "file a bug"`;
    `str(excinfo.value).startswith("expected the total 100, observed 90")`;
    `str(excinfo.value).count("expected the total 100, observed 90") == 2` (message + the
    verdict render explanation); `"recommendation: file a bug" in str(excinfo.value)`;
    hooks contain `("on_healing_started", {"category": "product_defect"})`
  - `test_heal_incurable_carries_verdict_and_skips_regeneration` (review addition):
    classification `FailureClassification("incurable", "the step text no longer matches
    reality", "reword the step")` → `excinfo.value.reason == "the step text no longer matches
    reality"`; `excinfo.value.verdict.category == "incurable"`;
    `excinfo.value.recommendation == "reword the step"`;
    `str(excinfo.value).endswith("recommendation: reword the step")`;
    `provider.generate_step_code_call_count == 0` (no regeneration request)
  - `test_heal_rot_exhaustion_reuses_verdict_without_second_request`: classification returns
    rot; `RunBudgets(1, 1)`; regeneration candidates always fail with `TimeoutError` →
    `excinfo.value.verdict.category == "rot"`;
    `excinfo.value.reason.startswith("healing attempt budget exhausted")`;
    `provider.classify_failure_call_count == 1` (no extra LLM request)
  - `test_heal_classification_unavailable_is_infrastructure_failure` (negative):
    `FakeProvider.classify_failure` raises `LlmUnavailableError("anthropic down")` → propagates
    untouched; `"anthropic" in str(excinfo.value)`
  - `test_heal_preserves_fresh_verdict_from_regenerate_failed_check` (edge): classification
    returns rot; during regeneration the candidate raises `AssertionError` and the inner
    failed-check classification returns `product_defect` (scripted sequences) →
    `ProductDefectError` propagates (the `except IncurableStepError` clause never takes it);
    `excinfo.value.verdict.category == "product_defect"` (the fresh verdict, not the rot one)
  - fix the registered breakages in this file: error constructors and recommendation fallbacks
    → verdict form
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — fix implementation until green
- [ ] **Contract re-verification**: `heal` called exactly once per classification
  (`classify_failure_call_count == 1` in every scenario); all four exit paths carry their
  verdicts; the cache write happens only via the generator
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/engine/`

### Task 9: the `on_step_verdict` hook event (reporting)

Add the verdict event to the callback contract in `prettyplay/reporting/hooks.py`:
`on_step_verdict(step_text, category, explanation, recommendation)` — a no-op base method like
every other event, firing after `on_step_failed`. **No change to `reporter.py`**: the event is
INFO by default (not in `_WARNING_EVENTS`), and the emit mechanism (log record with contextual
`extra`, hook fan-out in registration order, a raising hook logged WARNING and skipped) already
handles it.

**Usages relevant to this task:**
- `conventions`: tests at `tests/reporting/test_hooks.py`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/reporting/test_hooks.py`; expected to fail): add to
  `EVENT_SIGNATURES`: `"on_step_verdict": [("step_text", str), ("category", str),
  ("explanation", str), ("recommendation", str)]` — the existing contract tests then cover the
  9-method surface automatically (update the "all eight" test name/docstring to nine)
- [ ] **Code**: add the `on_step_verdict` no-op method with the docstring "The terminal failure
  of the step carried a verdict; fires after on_step_failed."; update the class docstring event
  count 8 → 9
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/reporting/ -q`
- [ ] **Logic tests**: `StepHooks().on_step_verdict("s", "incurable", "e", "rec")` returns
  `None` (no-op base); a `RecordingHooks(StepHooks)` subclass overriding the method receives
  the four payload fields as separate strings
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/reporting/ -x` — fix implementation
  until green
- [ ] **Contract re-verification**: `from prettyplay.reporting import StepHooks, StepReporter`;
  `reporter.py` untouched; the other eight events untouched
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/reporting/`

### Task 10: the verdict event in `StepExecutor.execute` (root)

Complete the failure reporting of the step cycle in `prettyplay/executor.py`: after
`on_step_failed` and before the raise, when the terminal failure carries a verdict, report
`on_step_verdict` with the sentence and the three verdict fields. Only `ProductDefectError` and
`IncurableStepError` carry one (`LlmUnavailableError` and `ConfigurationError` never do); the
original exception object is re-raised untouched.

**Usages relevant to this task:**
- `conventions`: tests at `tests/test_executor.py`; `caplog` on the `prettyplay` logger.
- `taxonomy` (imported from `prettyplay/failures`): the two verdict-carrying kinds guard the
  event.
- `hooks` (imported from `prettyplay/reporting`): the event ordering (`on_step_failed` →
  `on_step_verdict`) and the skip rule (never fired without a verdict).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/test_executor.py`; expected to fail): the failure branch
  emits `on_step_verdict` for a verdict-carrying `IncurableStepError`/`ProductDefectError` and
  emits nothing of the kind for `LlmUnavailableError`
- [ ] **Code**: in the `except` branch of `execute`, after the `on_step_failed` emit and before
  `raise`: `if isinstance(error, (ProductDefectError, IncurableStepError)) and error.verdict is
  not None: self._reporter.emit("on_step_verdict", {"step_text": step_text, "category":
  error.verdict.category, "explanation": error.verdict.explanation, "recommendation":
  error.verdict.recommendation})`; import the two error types (already imported transitively —
  make the names available)
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/test_executor.py -q`
- [ ] **Logic tests** (design scenarios; executor wired with a healer/generator stub,
  `RecordingHooks`, `FakePage`):
  - `test_executor_reports_verdict_after_failed`: a healer stub raising
    `IncurableStepError("s", "r", FailureVerdict("incurable", "e", "rec"))` on a cached step →
    `names.index("on_step_failed") < names.index("on_step_verdict")`; the verdict event payload
    is `{"step_text": "s", "category": "incurable", "explanation": "e", "recommendation":
    "rec"}`
  - `test_verdict_event_absent_without_verdict` (edge): a healer stub raising
    `LlmUnavailableError("down")` → `"on_step_verdict" not in [e for e, _ in hooks.events]`
    while `"on_step_failed"` is
  - `test_verdict_event_logged_at_info` (review addition): `caplog` on the `prettyplay`
    logger — the `on_step_verdict` record has `levelno == logging.INFO` (the reporting header
    contract)
  - fix the registered breakages in this file: the error-constructor tests at
    `tests/test_executor.py:198–288` (recommendation fallbacks → verdict form)
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — fix implementation until green
- [ ] **Contract re-verification**: the success path and the scenario-context behavior are
  unchanged; the exception object identity is preserved through the raise
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/executor.py`

### Task 11: traceback folding and author screenshots in `PrettyTest` (root)

Two facade abilities in `prettyplay/scenario.py`: (1) the traceback folding of
`action`/`assertion` — a `PrettyplayError` leaving these methods carries its traceback folded
to the library boundary, so internal library frames (engine, healing, provider) never appear in
what the runner shows; (2) the author screenshots `get_screenshot()` / `save_screenshot(filepath)`
over the facade screenshot, with the loud no-page guard and the wrapped write failure
(user-approved D2=(a)). Import `PrettyplayError` (root manifest already lists it) and `Path`.

**Usages relevant to this task:**
- `conventions`: tests at `tests/test_scenario.py`; monkeypatched runtime/executor chains.
- `taxonomy` (imported from `prettyplay/failures`): the failure kinds the step methods
  propagate; the fold applies to every `PrettyplayError` (`ProductDefectError`,
  `IncurableStepError`, `LlmUnavailableError` fold identically).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/test_scenario.py`; expected to fail): `PrettyTest` has
  callable `get_screenshot` and `save_screenshot`; `action`/`assertion` remain callable with a
  single `text` parameter
- [ ] **Code**: wrap the executor call of both `action` and `assertion` in
  `try: … except PrettyplayError as error: _raise_folded(error)`; implement the module-level
  (or private static) `_raise_folded(error) -> NoReturn`: `tb = error.__traceback__` (the head
  link is the facade method's own frame); `folded = types.TracebackType(tb_next=None,
  tb_frame=tb.tb_frame, tb_lasti=tb.tb_lasti, tb_lineno=tb.tb_lineno)` — the only four
  parameters the constructor accepts (`filename`/`name` derive from the frame automatically);
  `raise error.with_traceback(folded)` — the **same** exception object, never a copy (identity
  for hook consumers and `except` clauses; re-raising the same object adds no `__context__`
  nesting). Non-library exceptions pass through the `except PrettyplayError` filter untouched
- [ ] **Code**: implement `get_screenshot() -> bytes`: `if self._page is None: raise
  PrettyplayError("no test page yet: run a step first — the page opens lazily on the first
  step")`; `return self._page.screenshot()`
- [ ] **Code**: implement `save_screenshot(filepath: str) -> None`: the same no-page guard;
  `image = self._page.screenshot()`; `try: Path(filepath).write_bytes(image)` /
  `except OSError as error: raise PrettyplayError(f"cannot write the screenshot to {filepath}:
  {error}") from error` — parent directories are **not** created; nothing is created silently
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/test_scenario.py -q`
- [ ] **Logic tests** (design scenarios; monkeypatched `get_runtime`/executor chains, stub
  runtime whose `open_page` returns a `FakePage` with `screenshot() -> b"png-bytes"`,
  English sample data):
  - `test_action_folds_traceback_to_boundary`: a generator stub raising
    `IncurableStepError("s", "r", FailureVerdict("incurable", "e", "rec"))` through two nested
    helper frames (simulating engine depth); `PrettyTest("k").assertion("s")` →
    `frames = [e.filename for e in traceback.extract_tb(excinfo.value.__traceback__)]`
    (stdlib `traceback`, not pytest entries); `frames[-1].endswith("scenario.py")` (innermost =
    the boundary); `not any(f.endswith(("generator.py", "healer.py", "executor.py")) for f in
    frames)`
  - `test_get_and_save_screenshot`: one action step executed first (one-shot fake candidate);
    `t.get_screenshot() == b"png-bytes"`;
    `(tmp_path / "artifacts" / "home.png").read_bytes() == b"png-bytes"` (directory
    pre-created)
  - `test_screenshot_before_first_step_raises_library_failure` (negative): no page ever opened
    → `pytest.raises(PrettyplayError, t.get_screenshot)` with `"run a step first" in
    str(excinfo.value)`; `pytest.raises(PrettyplayError, t.save_screenshot, "x.png")`
  - `test_save_screenshot_write_failure_wraps_oserror` (negative): page opened;
    `filepath = tmp_path / "missing-dir" / "x.png"` (directory not created) →
    `isinstance(excinfo.value.__cause__, OSError)`;
    `str(excinfo.value).startswith("cannot write the screenshot to")`;
    `not filepath.exists()` (nothing created silently)
  - `test_scenario_close_then_screenshot_raises` (edge): one step run, then `t.close()` →
    `pytest.raises(PrettyplayError, t.get_screenshot)`
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — fix implementation until green
- [ ] **Contract re-verification**: `from prettyplay import PrettyTest`; `close()`, the context
  manager protocol, `add_hooks` and `cache_key` untouched; the folding works identically for
  `ProductDefectError` (an `AssertionError` in any runner), `IncurableStepError` and
  `LlmUnavailableError`
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/scenario.py`

### Task 12: Integration tests for the verdict reporting cycles

Wire-level verification of the verdict flow across cells in `tests/test_integration.py`: the
verdict event fires after `on_step_failed` in the hook-event lists of both verdict-carrying
failure tests, and the whole suite passes end-to-end. These tests do not replace the contract
and logic tests of Tasks 1–11 — they verify the cross-entity interaction.

**Usages relevant to this task:**
- `conventions`: integration tests exercise real wiring with fakes only at the external
  boundaries (fake provider, fake page).
- `generation`, `healing` (imported from `prettyplay/engine`): the engine cycles the executor
  delegates to — the failed-check stop and the exhaustion verdict reuse behave as documented
  there when wired end-to-end.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] Fix the registered breakages at `tests/test_integration.py:402,431`: both
  verdict-carrying failure tests (`test_product_defect_verdict_fails_the_test_loudly`,
  `test_incurable_verdict_fails_with_verdict_fields`) must expect `on_step_verdict` after
  `on_step_failed` in their hook-event list assertions (payload: step_text + the three verdict
  fields)
- [ ] Verify the full failure flow once more through the wired objects: terminal error →
  `on_step_failed` → `on_step_verdict` (when the verdict is present) → raise → the folded
  traceback at the facade → the rendered message ends with the verdict render
- [ ] Run validation: `.venv/bin/python -m pytest tests/test_integration.py -q` — all pass
- [ ] Run the full suite: `.venv/bin/python -m pytest tests/ -x` — all pass

---

## Validation Commands

- `.venv/bin/python -m pytest tests/ -x`: Run all tests (the design's verify command; the
  project venv is `.venv/` — plain `python` has no playwright)
- `.venv/bin/ruff check prettyplay/`: Lint check
- `.venv/bin/python -c "from prettyplay import PrettyTest; from prettyplay.failures import FailureVerdict; from prettyplay.config import ConfigurationError; from prettyplay.engine import classify_step_failure"`:
  Facade accessibility — every new facade entity is importable
- `.venv/bin/python -m pytest tests/failures/ tests/config/ tests/driver/ tests/engine/ tests/reporting/ tests/test_executor.py tests/test_scenario.py tests/test_integration.py -q`:
  Per-package suites (used inside tasks 1–12)

---

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location` (`FailureVerdict` and the
      two reworked errors in `errors.py`; `ConfigurationError` in `loader.py`; `headless` and
      the five-value browser set in `models.py`; the launch changes in `session.py`; the 8
      scroll methods in `page.py`; `classify_step_failure` in the new `classification.py`; the
      loop changes in `generator.py`; the heal changes in `healer.py`; `on_step_verdict` in
      `hooks.py`; the verdict event in `executor.py`; folding + screenshots in `scenario.py`)
- [ ] Every contract entity is accessible from the facade (`FailureVerdict` from
      `prettyplay.failures`, `ConfigurationError` from `prettyplay.config`,
      `classify_step_failure` from `prettyplay.engine`)
- [ ] Properties and methods match the declared API (constructor signatures incl. the `verdict`
      parameters, the derived `recommendation` property, the 8 scroll arities,
      `get_screenshot`/`save_screenshot`)
- [ ] Descriptions are reflected in behavior (verdict render contract, failed-check stop,
      exhaustion classification, quiet skip, anti-masking, verdict reuse without a second LLM
      request, INFO-level verdict event, folded tracebacks, headless/channel launch, env-name
      map, `ConfigurationError` rendering)
- [ ] Contract dependencies are met (config → failures for `PrettyplayError`; engine →
      failures for `FailureVerdict`; root → failures for `PrettyplayError` — all already in the
      manifests)
- [ ] No re-export blocks exist, and the three new facade exports are in place
- [ ] Every coding task followed the TDD workflow (contract tests → code → verification →
      logic tests → debugging → re-verification → lint)
- [ ] Contract tests and logic tests cover facade, API, and behavior within each coding task
- [ ] Integration tests exist for the cross-entity verdict-reporting scenarios
- [ ] No package boundary was expanded (no new cells; `classification.py` is an internal module
      of the engine cell at its declared location)
- [ ] `CODEMANIFEST` files were not modified (contract is read-only)
- [ ] All validation commands pass
- [ ] Every Usages entry is mentioned in at least one task (`conventions` — all tasks;
      `pydantic` — Tasks 2–3; `playwright` — Tasks 4–5; `generation_prompt` /
      `classification_prompt` — Tasks 6–7; imported `taxonomy` — Tasks 3, 10, 11; `facade` —
      Task 7; `classification` — Tasks 6–8; `hooks` — Task 10; `generation`/`healing` — Task 12
      context via the executor delegation)
