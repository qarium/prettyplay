# Design Document: `strict-and-fullscreen-mode`

Topic directory: `.goga/history/2026/strict-and-fullscreen-mode/`.
Scope source: `task.md` (four capabilities: nested browser group with screen modes, strict replay, structured failure message, classification instructions).
Contract base: the CODEMANIFEST files materialized by the architecture stage; diffs taken against the working tree of branch `strict-and-fullscreen-mode`.

---

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/config/CODEMANIFEST`: new `BrowserConfig` entity; `Config` restructured (nested `browser: BrowserConfig`, new `strict`, new `classification_prompt`; flat `browser`/`headless`/`browser_endpoint` removed); `load_config` gains group env overrides, old-flat-key rejection, typed scalar env parsing, nested-group merge; `ConfigurationError` covers removed keys.
- `prettyplay/failures/CODEMANIFEST`: new routine `render_terminal_message`; `FailureVerdict.render` redefined (category dropped, column alignment); `ProductDefectError`/`IncurableStepError` gain the `error` field and render through the single template; `LlmUnavailableError` renamed `LLMUnavailableError`.
- `prettyplay/reporting/CODEMANIFEST`: `on_step_failed` error payload redefined as the full structured render; `on_step_verdict` documented as built from the verdict object.
- `prettyplay/driver/CODEMANIFEST`: `DriverSession.open_context` gains the screen-mode resolution algorithm (empty / WxH / fullscreen / device name); annotations describe the browser group.
- `prettyplay/llm/CODEMANIFEST`: `classify_failure` gains `user_instructions`; `LlmProvider`→`LLMProvider`, `OpenAiProvider`→`OpenAIProvider`, `LlmUnavailableError`→`LLMUnavailableError`; per-request-kind USER INSTRUCTIONS placement fixed.
- `prettyplay/engine/CODEMANIFEST`: engines carry the full underlying error in the `error` field of raised terminal failures; colon-free first lines; `classify_step_failure` passes the classification user instructions; classification system prompt lists the USER INSTRUCTIONS input.
- `prettyplay/CODEMANIFEST` (root): `BrowserConfig` re-export embedding; `StepExecutor` gains `config` and `provider` parameters and the strict replay-only path; `PrettyTest` wiring updated; initialism renames applied.

### New Entities

- `BrowserConfig` — the nested browser settings group (engine, screen mode, headless, endpoint); `prettyplay/config/models.py`.
- `render_terminal_message(reason, step_text, error, verdict)` — the single structured render of a terminal failure; `prettyplay/failures/errors.py`.

### Changed Entities

- `Config` — `browser` is now a `BrowserConfig` group; new `strict: bool = False`; new `classification_prompt: str = ""`; `browser_endpoint`/`headless` fields removed (moved into the group).
- `load_config` — flat env overrides for the group, old-flat-key rejection, typed scalar env parsing, nested merge of programmatic overrides.
- `ConfigurationError` — also covers removed flat keys.
- `FailureVerdict.render` — verdict block only (explanation/recommendation), values column-aligned after the longest label, multi-line continuations indented to the value column, category dropped.
- `ProductDefectError` / `IncurableStepError` — new `error` field; the exception message is composed through `render_terminal_message`; `IncurableStepError` keeps the fallback recommendation in the render when the verdict is absent.
- `LlmUnavailableError` → `LLMUnavailableError`; `LlmProvider` → `LLMProvider`; `OpenAiProvider` → `OpenAIProvider` (initialism naming; class aliases are not kept — a pre-1.0 hard rename).
- `DriverSession.open_context` — resolves the screen setting into context parameters per launch mode; `_launch_engine` reads the browser group and adds maximized launch arguments for chromium-family fullscreen.
- `classify_failure` (port + both providers) — new `user_instructions` parameter rendered as the final USER INSTRUCTIONS block of the user content.
- `classify_step_failure` — passes `config.classification_prompt` as the classification user instructions.
- `StepGenerator.generate`/`regenerate` (shared `_loop`) — error field carries the full formatted failure; reasons authored colon-free.
- `StepHealer.heal` — terminal raises carry the full underlying error in the `error` field.
- `StepExecutor` — signature gains `config: PrettyConfig` and `provider: LLMProvider`; strict replay-only path; `on_step_failed` carries the full render.
- `PrettyTest` — passes the runtime config and the runtime provider to `StepExecutor`.

### Deleted Entities

- None. (`first_line_short` of `prettyplay/engine/text.py` is an implementation helper absent from contracts; it becomes obsolete and is replaced — see Algorithm Design, `format_step_error`.)

### Usages and Annotations Changes

- `.goga/usages/cooks/playwright.md`: new "Screen modes" section (viewport, device emulation, fullscreen rules).
- `.goga/usages/cooks/pydantic.md`: nested `BrowserConfig` schema, flat env overrides, old-flat-key hard break, nested-group merge rules.
- Cell `.usages/` consumer docs updated by the architecture stage: `configuration.md` (group, screen modes, strict), `taxonomy.md` (structured message), `hooks.md` (full-render error payload), `facade.md` (screen modes note), `generation.md`/`healing.md` (error field, classification instructions), `classification.md`/`providers.md` (user instructions parity), `lifecycle.md` (strict mode), `steps.md` (render in output).
- Engine inline usage `classification_prompt` (system prompt text) lists `USER INSTRUCTIONS: the project's classification guidance, when configured`.

## Applied Fixes

### Fixed CODEMANIFEST Defects

- `prettyplay/CODEMANIFEST` (root): `StepExecutor.execute` step 4 requires the strict-path classification via `classify_step_failure(config, provider, …)`, but the declared signature carried no provider — Interface↔Interface inconsistency (the caller could not supply a required input of the callee). **Fix (approved, option A)**: `provider: LLMProvider` added to the `StepExecutor` signature and annotations; `PrettyTest` algorithm step 6 now constructs the executor "…with `cache_key`, the cache, the engines, the runtime budgets, the reporter, the runtime config and the runtime provider". `LLMProvider` was already imported by the root — no new Imports entry. Validated: `goga lint` → 8 cells, 0 errors.

Approved design decision (not a contract edit): fullscreen on a local headed launch maximizes through engine launch arguments only for the chromium family (`chromium`, `chrome`, `msedge` — `args=["--start-maximized"]`); `firefox`/`webkit` launch with no extra arguments and the context still opens `no_viewport=True`, so the viewport follows the default window (option A of the design question; Playwright has no maximized-start flag for those engines).

## Entity Interaction and Data Flow

### Interaction Diagram

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

### Data Flows

1. **Settings flow** — `[tool.prettyplay]` + `[tool.prettyplay.browser]` + flat env vars → `load_config` (reject old flat keys → typed env parsing → pydantic validation → nested programmatic merge) → `Config` → consumed by `DriverSession` (browser group), `StepGenerator`/`classify_step_failure` (prompts), `StepExecutor` (strict switch), providers (models/base_url).
2. **Strict step flow (replay-only)** — `PrettyTest.action/assertion` → `StepExecutor.execute` → cache load → hit: `run_step_code`; failure → `classify_step_failure` (the only LLM call) → raise `ProductDefectError`/`IncurableStepError` carrying `FailureVerdict` + full error text; miss → `IncurableStepError` (strict forbids generation). Events: `on_step_started` → `on_step_failed` (full render) → `on_step_verdict` (when the verdict exists).
3. **Non-strict step flow** — unchanged cycle; the healer and generator now receive and carry the full formatted error text; terminal failures render through the single template.
4. **Screen flow** — `browser.screen` → `DriverSession.open_context` → context parameters (`viewport` / `no_viewport` / full device descriptor) and, at first launch, maximized args for chromium-family fullscreen.
5. **Classification instructions flow** — `classification_prompt` → `classify_step_failure` → `provider.classify_failure(user_instructions=…)` → USER INSTRUCTIONS block placed last in the user content of both providers.

### Entity Dependencies

Initialization order per test (unchanged shape, two new wires):
`load_config` → `PrettyplayRuntime(config)` → `StepReporter` → `StepCache` → `StepGenerator(config, provider, cache, budgets, reporter)` → `StepHealer(config, provider, generator, cache, budgets, reporter)` → `StepExecutor(cache_key, cache, generator, healer, budgets, reporter, config, provider)` — the provider is `runtime.provider` (cheap object construction; the SDK client stays lazy, no credentials needed).

## Code Stack Trace

### Trace: `load_config`

#### Chain
1. **Input**: `pyproject_path=None, overrides=None` (from `PrettyTest.__init__` or direct integrator call).
2. Resolve path (given or searched upward) → checkpoint: unchanged logic, `Path` ✓.
3. Parse TOML (`tomllib`/`tomli`); extract `tool.prettyplay` (missing → `{}`) → checkpoint: dict ✓.
4. Legacy env guard: `PRETTYPLAY_BROWSER` set → `ConfigurationError` naming `PRETTYPLAY_BROWSER_NAME` (existing behavior kept; consistent with the old-flat-key rejection) → checkpoint: loud, pre-merge ✓.
5. Old flat keys: `browser` present **as a str**, or `headless`/`browser_endpoint` present at the section level → `ConfigurationError`, one line per key naming its new home (`browser` → `[tool.prettyplay.browser] name`, `headless` → `… headless`, `browser_endpoint` → `… endpoint`) → checkpoint: matches contract algorithm step 5; a dict-valued `browser` is the valid group, not a flat key ✓.
6. Env overrides: `PRETTYPLAY_PROVIDER/MODEL/…`, `PRETTYPLAY_STRICT`, `PRETTYPLAY_CLASSIFICATION_PROMPT`, `PRETTYPLAY_GENERATION_ATTEMPTS`…, `PRETTYPLAY_SEND_SCREENSHOTS`; group: `PRETTYPLAY_BROWSER_{NAME|SCREEN|HEADLESS|ENDPOINT}`. Scalars parsed by field type — bools: `true/false/1/0` case-insensitive; ints: decimal; unparseable → `ConfigurationError` `"<setting>: received <value!r> — allowed: <form>"`; group values land in a nested `browser` dict merged over the section's group dict → checkpoint: `bool`/`int`/`str` types verified; no silent ignore ✓.
7. Empty `cache_root` → absolute `<pyproject_dir>/.prettyplay/cache` (unchanged) ✓.
8. `Config(**merged)`; `ValidationError` → `_render_validation` (loc joined with `.` — `browser.name`, `browser.endpoint`, `strict`, …; `_ALLOWED_TEXT` extended accordingly) → `ConfigurationError` chained ✓.
9. `overrides is None` → return file layer; else field-level merge (see Algorithm Design) → checkpoint: nested group merge verified against the contract step 8 ✓.
10. **Output**: validated `Config` with a `BrowserConfig` group.

#### Checkpoint Summary
- Nested loc rendering: passed (old code dropped the inner field name).
- Bool env wider acceptance by pydantic lax mode: passed — parsing happens in the loader before pydantic, so only `true/false/1/0` pass.

### Trace: `DriverSession.open_context`

#### Chain
1. **Input**: none (config held at construction).
2. First call → `_launch()`: worker thread → `sync_playwright().start()` → `_launch_engine(playwright)` reads `config.browser`: `endpoint` set → `connect(endpoint)` (engine by `name`, chrome/msedge→chromium, wrapped connect error); else local `launch(headless=browser.headless, channel=name for chrome/msedge)`, plus `args=["--start-maximized"]` **iff** `browser.screen == "fullscreen"` and chromium family and a local headed launch (`not headless`; the endpoint branch never reaches launch) → checkpoint: launch args decided from immutable config ✓; failure cleans up worker (unchanged) ✓.
3. Screen resolution (inside the driver thread, per context): `screen == ""` → no params; `"fullscreen"` → local headed (`not endpoint and not headless`) → `no_viewport=True`, else `viewport={"width": 1920, "height": 1080}`; WxH (`^\d+x\d+$`, guaranteed positive by config) → `viewport={"width": W, "height": H}`; otherwise device name → `screen in playwright.devices` → full descriptor (`dict(devices[screen])`, verified keys `viewport/user_agent/has_touch/is_mobile/device_scale_factor/default_browser_type` — all valid `new_context` parameters); absent → `difflib.get_close_matches` (cutoff 0.5, up to 3) → loud `playwright.sync_api.Error` listing close names → checkpoint: registry of the *running* Playwright (207 devices in 1.62.0), never hard-coded ✓.
4. `browser.new_context(**params)` + `new_page()` in the worker; wrap into `PageFacade` (untouched) → **Output**: facade; constraint "PageFacade/LocatorFacade stay untouched" ✓.

#### Checkpoint Summary
- Device descriptor compatibility: passed (verified against the installed Playwright signature).
- WxH regex duplication between config and driver: passed with a pinned canonical form (`^\d+x\d+$`, lowercase `x`); config guarantees positivity, driver only re-detects the shape.

### Trace: `StepExecutor.execute`

#### Chain
1. **Input**: `step_text`, `step_type` (`action`|`assertion`), `page` (from `PrettyTest.action/assertion` after lazy `_ensure_page`).
2. `on_step_started` emitted ✓.
3. `StepIdentity(cache_key, step_type, normalize_step_text(step_text))` → `cache.load(identity)` ✓ (addressing untouched by strict/prompts — instructions never invalidate the cache).
4. Hit → `run_step_code(cached.code, page)`:
   - success → scenario append + `on_step_passed` ✓.
   - failure → `error_text = format_step_error(error)` (`AssertionError` → `str(error)` without prefix; other → `f"{type(error).__name__}: {error}"`):
     - **strict** → `_strict_failure` (always raises; see Algorithm Design);
     - **non-strict** → `healer.heal(cached, error_text, scenario, page)` (healed = re-executed + stored by the engine).
5. Miss → strict: raise `IncurableStepError(step_text, "strict mode forbids generation — the step is missing from the cache", "", None)`; non-strict: `generator.generate(identity, step_text, scenario, page)` → checkpoint: no engine call, no budget consumption in strict ✓.
6. Outer `except Exception as error`: `on_step_failed {"step_text", "step_type", "error": str(error)}` — `str()` of a terminal failure **is** the render composed at construction (never re-composed); then `on_step_verdict` from `error.verdict` object fields when the failure is terminal and the verdict exists; re-raise → checkpoint: one render for exception message, log record and hook payload ✓.
7. **Output**: raise by kind (`ProductDefectError`, `IncurableStepError`, `LLMUnavailableError`) or silent success; `PrettyTest` folds the traceback at the facade boundary (unchanged).

#### Checkpoint Summary
- Strict classification input supply: passed after the approved contract fix (`provider` parameter).
- Quiet-skip parity: passed — the executor WARNING wording matches the engines (`"verdict skipped: llm unavailable"`).

### Trace: `classify_failure` (both providers)

#### Chain
1. **Input**: `prompt=CLASSIFICATION_PROMPT`, `user_instructions=config.classification_prompt`, step/code/error/snapshot/screenshot (from `classify_step_failure`).
2. `_request.build_classification_fields(user_instructions, step_text, code, error, snapshot)` → sections `STEP / CODE / ERROR / PAGE SNAPSHOT`, then `USER INSTRUCTIONS` appended **last** when non-empty → checkpoint: identical in both providers (shared helper) ✓.
3. SDK request (openai `chat.completions.create` / anthropic `messages.create`) with `effective_classification_model`, `system=prompt` ✓.
4. Answer parse → `FailureClassification`; unparsable → protective incurable default (unchanged); SDK error → `LLMUnavailableError` naming the provider ✓.
5. **Output**: classification ✓.

#### Checkpoint Summary
- Parity: passed — both providers call the same field builder with the same placement rule.

### Trace: `StepGenerator._loop` / `StepHealer.heal`

#### Chain
1. **Input**: identity/step/scenario/page (+ pool, existing code/error for regeneration).
2. Attempt: budget check (`try_generation`/`try_healing`) → `on_generation_started` → snapshot (+screenshot) → `provider.generate_step_code(prompt=SYSTEM_PROMPT, user_instructions=config.generation_prompt, …)`.
3. Candidate execution via `run_step_code`:
   - `AssertionError` (failed check) → `reason = f"candidate check failed — {first line of str(check_failure)}"`; `error_field = str(check_failure)` (full, no prefix); classify quietly (`LlmUnavailableError` → WARNING, verdict None): `product_defect` → `ProductDefectError(step_text, classification.explanation, error_field, verdict)`; otherwise → `IncurableStepError(step_text, reason, error_field, verdict)` → checkpoint: colon-free authored template (em dash); embedded texts taken verbatim per the "authored without colons" discipline ✓.
   - other failure → `existing_code = code; error = format_step_error(candidate_error)` (full, typed) → next attempt ✓.
   - success → `CachedStep` + `cache.save` ✓.
4. Budget exhaustion → `reason = f"{pool} attempt budget exhausted"`; `error_field = error or ""`; generation pool classifies the last candidate (quiet skip on unavailability), healing pool raises without classification (the healer attaches its verdict) ✓.
5. `StepHealer.heal`: classification → `on_healing_started` → `product_defect`: `ProductDefectError(step_text, classification.explanation, error, verdict)`; `incurable`: `IncurableStepError(step_text, classification.explanation, error, verdict)`; `rot`: `regenerate`, exhaustion re-raises `IncurableStepError(step_text, inner.reason, inner.error, verdict_of_this_classification)`; provider unavailability of the classification itself → `LLMUnavailableError` ✓.

#### Checkpoint Summary
- Error-field propagation end to end: passed — every terminal raise on these paths carries the full formatted text.
- Type flow: `FailureClassification` → `FailureVerdict` mapping unchanged and shared.

### Trace: `render_terminal_message` / terminal failures

#### Chain
1. **Input**: reason, step_text, error, verdict (from the raising site — engines, healer, executor).
2. Lines: `[reason]`; if `step_text or error` → `---` + `step: …`? + `error: …`?; verdict render non-empty → `---` + verdict block; join with `\n` → checkpoint: fixed order, no bare separator, no trailing separator ✓.
3. `ProductDefectError.__init__` stores `step_text/message/error/verdict` and sets the exception text to the render via `Exception.__init__` (bypassing `PrettyplayError.__init__`, which would overwrite `message` with the render) → `str(exc)` == the render, `exc.message` == the primary reason ✓.
4. `IncurableStepError.__init__` same, with `verdict or _fallback_verdict()` where the fallback is `FailureVerdict(category="incurable", explanation="", recommendation="reword the step or refresh the cache")` — render-only: the `verdict` attribute stays `None`, so `on_step_verdict` never fires for the fallback → checkpoint: "the fallback recommendation keeps the message actionable without a verdict" ✓.
5. `FailureVerdict.render`: labels `explanation:`/`recommendation:` padded to the longest label (`recommendation:` = 15 chars) + one space → value; multi-line values indent continuation lines to the value column (`width+1` spaces); empty fields produce no line; both empty → `""` → block omitted ✓.

#### Checkpoint Summary
- Category dropped from the render, kept in structured fields: passed.
- Fallback verdict does not leak into structured events: passed.

## Algorithm Design

### `BrowserConfig` (prettyplay/config/models.py)

**Responsibility**: the nested browser group of the settings; owns engine, screen mode, window visibility, remote endpoint.

**Algorithm:**
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

**Errors:**
- `pydantic.ValidationError` (loc `("browser", "<field>")`) → wrapped by `load_config` into `ConfigurationError` (rendered as `browser.<field>: received … — allowed: …`).

**Edge Cases:**
- `"1280X720"` (capital X) — not WxH-shaped → passes as a device name → loud unknown-device error in the driver (canonical form is lowercase `x`).
- `"0x720"` / `"-5x100"` — shape `0x720` matches, width 0 → validation error; `-5x100` does not match the digits-only shape → passes as a device name → unknown-device error in the driver.

### `Config` (prettyplay/config/models.py)

**Responsibility**: validated project settings; the single immutable configuration source.

**Algorithm:**
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

**Errors:** nested validation failures surface with dotted locs.

**Edge Cases:** passing `browser` as a dict (TOML/env merge) validates into `BrowserConfig` automatically; the class-default instance is validated once at import (defaults are valid).

### `load_config` (prettyplay/config/loader.py)

**Responsibility**: layered settings resolution — pyproject → env → explicit programmatic values.

**Algorithm:**
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

**Errors:** `ConfigurationError` (removed keys, unparseable env, validation) with the original `ValidationError` chained where applicable.

**Edge Cases:** env group override over a TOML group (env wins per field); programmatic `BrowserConfig()` with nothing set → file group fully survives; explicit `strict=False` overrides the file value.

### `render_terminal_message` (prettyplay/failures/errors.py)

**Responsibility:** the one structured render shared by the exception message, the log record and the `on_step_failed` payload.

**Algorithm:**
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

**Edge Cases:** both empty middle inputs → no `---` and no bare separator; empty verdict render (both fields empty) → no verdict block; never embeds step code.

### `FailureVerdict.render`

**Algorithm:**
```
1. width = 15 (len("recommendation:") — the longest label; fixed regardless of which fields are present)
2. FOR (label, value) in (("explanation", …), ("recommendation", …)):
     IF not value: continue
     line = f"{label}:".ljust(width) + " " + value.replace("\n", "\n" + " " * (width + 1))
     # value column = width + 1 = 16: "explanation:" + 4 spaces, "recommendation:" + 1 space —
     # first lines and multi-line continuations indent to the same column
3. RETURN "\n".join(lines)      # "" when both empty
```

### `ProductDefectError` / `IncurableStepError`

**Algorithm:**
```
ProductDefectError(step_text, message, error="", verdict=None):
  self.step_text/message/error/verdict stored
  Exception.__init__(self, render_terminal_message(message, step_text, error, verdict))
  # str(exc) is the render; exc.message stays the primary reason
  # derives PrettyplayError + AssertionError (unchanged)

IncurableStepError(step_text, reason, error="", verdict=None):
  self.step_text/reason/error/verdict stored
  render_verdict = verdict if verdict is not None
                   else FailureVerdict("incurable", "", "reword the step or refresh the cache")
  Exception.__init__(self, render_terminal_message(reason, step_text, error, render_verdict))
  # recommendation property: verdict.recommendation when present, else the built-in guidance
  # derives PrettyplayError only (unchanged)
```

**Errors:** none raised internally; the types are the errors.

**Edge Cases:** the fallback verdict is render-only — the `verdict` attribute stays `None`, `on_step_verdict` does not fire, `isinstance` checks unaffected.

### `LLMUnavailableError` (rename)

Unchanged behavior: `PrettyplayError.__init__(message)`; `message` property. Class name and all references updated (module docstring, `failures/__init__.py`, llm cell, engine, executor, tests).

### `DriverSession` (prettyplay/driver/session.py)

**Responsibility:** lifecycle owner of the Playwright sync driver and the browser process of one test, now including the screen modes.

**Algorithm (`open_context`):**
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

**Errors:** playwright `Error` for connect/channel/device failures — loud and actionable; propagates through the step call (existing behavior for driver-domain failures).

**Edge Cases:** `no_viewport` with headless is invalid in Playwright — the branch order guarantees `no_viewport=True` only on local headed launches; a device descriptor containing `default_browser_type` is accepted by `new_context` (verified) and does not switch the already-started engine.

### `classify_failure` (port + providers + `_request.build_classification_fields`)

**Algorithm:**
```
build_classification_fields(user_instructions, step_text, code, error, snapshot):
  sections = [STEP, CODE, ERROR, PAGE SNAPSHOT]
  IF user_instructions: sections += [USER INSTRUCTIONS]        # last
  RETURN "\n\n".join(sections)

port LLMProvider.classify_failure(prompt, user_instructions, step_text, code, error, snapshot, screenshot)
  → NotImplementedError (port, unchanged pattern)

OpenAIProvider / AnthropicProvider.classify_failure:
  text = build_classification_fields(user_instructions, …)
  request with effective_classification_model, system=prompt
  parse the one-line verdict; unparsable → protective incurable (unchanged)
  SDK error → LLMUnavailableError naming the provider
```

**Edge Cases:** empty `user_instructions` → no block (byte-identical requests to the old form); generation requests never receive classification instructions and vice versa.

### `classify_step_failure` (prettyplay/engine/classification.py)

**Algorithm:**
```
1. CLASSIFICATION_PROMPT gains the input line "- USER INSTRUCTIONS: the project's classification guidance, when configured"
   (after SCREENSHOT — matching the engine cell inline usage text)
2. snapshot = page.aria_snapshot(); screenshot when config.send_screenshots
3. RETURN provider.classify_failure(prompt=CLASSIFICATION_PROMPT,
                                    user_instructions=config.classification_prompt,
                                    step_text, code, error, snapshot, screenshot)
   # provider unavailability propagates (unchanged)
```

### `format_step_error` (prettyplay/engine/text.py — implementation helper, not a contract entity)

**Responsibility:** the single error-text policy for the `error` field of terminal failures and for healing/classification inputs.

**Algorithm:**
```
format_step_error(exc: Exception) -> str:
  text = str(exc)
  IF isinstance(exc, AssertionError): RETURN text                  # no prefix — the type carries it;
                                                                   # "" for a bare assert -> the render omits the error line
  RETURN f"{type(exc).__name__}: {text}" IF text ELSE type(exc).__name__
                                                                   # action steps carry the type; a message-less
                                                                   # error yields the bare type name (no dangling ": ")
```
`first_line_short` and `SHORT_ERROR_LENGTH` are removed — no consumer remains (reasons no longer embed truncated errors; the render and the error field carry full texts). The first-line-only variant used for authored reasons is `format_step_error(exc).partition("\n")[0]` at the single call site that embeds it.

### `StepGenerator` (prettyplay/engine/generator.py)

**Algorithm (`_loop`):**
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

(`_classify` unchanged apart from the `LLMUnavailableError` rename and passing the full error text to the classification.)

### `StepHealer` (prettyplay/engine/healer.py)

**Algorithm (`heal`)** — unchanged structure; the raises carry the error field:
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

### `StepExecutor` (prettyplay/executor.py)

**Responsibility**: the owner of the step cycle; in strict mode the replay-only referee.

**Algorithm (`execute`):**
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

**`_strict_failure(step_text, step_type, step, error_text, page)`** (always raises):
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

**Errors:** see taxonomy; no new kinds.

**Edge Cases:** strict + LLM unavailable on an *assertion* step raises `ProductDefectError` (by step type) — the check semantics stand without a verdict; the WARNING precedes the raise; every strict failure still reaches `on_step_failed` with the render.

### `PrettyTest` (prettyplay/scenario.py) and the facade (`prettyplay/__init__.py`)

**Algorithm (construction):** steps 1–5 unchanged; step 6 now `StepExecutor(cache_key, cache, generator, healer, budgets, reporter, config=runtime.config, provider=runtime.provider)` — accessing `runtime.provider` constructs only the lightweight provider object (the SDK client stays lazy; no credentials needed).

**Facade:** `from .config import BrowserConfig, PrettyConfig`; `__all__ = ["PrettyTest", "PrettyConfig", "BrowserConfig", "PrettyplayRuntime", "StepExecutor"]`.

## Cross-cutting Concerns

- **Error handling**: taxonomy unchanged (three step kinds + base + config error). New invariants: one render per terminal failure (exception message == log record == hook payload, `str(exc)` is the source); the `error` field carries the full underlying text (no `AssertionError` prefix for failed checks, type-prefixed for action steps); authored first lines are colon-free (static templates by construction; embedded assertion/LLM texts are data and pass verbatim — `render_terminal_message` never rewrites the reason). Strict mode adds no failure kinds — it reuses the taxonomy with strict-specific reasons.
- **Logging**: `prettyplay` logger. INFO: step lifecycle, generation attempts, healing, cache writes. WARNING: verdict skips (`"verdict skipped: llm unavailable"` — engines and the strict executor share the wording), skipped cache writes, failed hook calls. The `on_step_failed` log record carries the multi-line render in its `error` extra field (the reporter's reserved-key prefixing is unaffected — `error` is not reserved).
- **Validation**: settings validated once in the config cell (screen at format level only — device resolution belongs to the running Playwright); typed env parsing rejects anything outside `true/false/1/0` / decimal integers loudly; old flat keys rejected with migration pointers; device names resolved loudly at context creation with close-name suggestions.
- **Caching**: step addressing untouched — `strict`, `classification_prompt`, `generation_prompt` and the browser group take no part in the step identity; cached steps never regenerate because instructions or screen settings changed. Strict mode never writes the cache (no generation path runs).
- **Concurrency**: unchanged single-driver-thread model; the new screen resolution and device-registry access run inside the driver thread via `worker.run`; executor/engine code stays on the caller thread.

## Usages Analysis

### `conventions`
- **What it provides**: mandatory Python rules — 3.10+ compatibility, relative intra-package imports, pydantic `kw_only` models with empty defaults, logging conventions, Google-style docstrings, code-formatting blocks, test structure/mocking rules.
- **Where used**: every cell (global annotations reference it).
- **Why chosen**: project-wide engineering standard.
- **How exactly**: pydantic v2 models for `BrowserConfig`/`Config`; `kw_only=True`; docstrings on all new/changed public entities (`render_terminal_message`, `format_step_error` is private-by-convention module function — Google docstring still provided); tests mirror `tests/<cell>/test_<module>.py`; unit tests mock only the Playwright/SDK boundaries.

### `pydantic` (cook)
- **What it provides**: settings-model patterns — nested groups, TOML loading, env layering, `model_copy` merging, loud validation wrapping.
- **Where used**: `prettyplay/config` (models, loader).
- **Why chosen**: the config cell is pydantic-based by design.
- **How exactly**: nested `BrowserConfig` group; `tomllib`/`tomli` by Python version; `model_fields_set`-driven merges; `ValidationError` never escaping raw.

### `playwright` (cook)
- **What it provides**: sync-API lifecycle, channels, ws connects, and the new screen-mode patterns (`new_context(viewport=…)`, device descriptors, `launch(args=["--start-maximized"])` + `no_viewport=True`).
- **Where used**: `prettyplay/driver`.
- **Why chosen**: the driver is Playwright sync-only.
- **How exactly**: verified against the installed Playwright 1.62.0 — device descriptors are `new_context`-compatible dicts (`viewport/user_agent/has_touch/is_mobile/device_scale_factor/default_browser_type`), `no_viewport` and `args` are valid parameters, `Playwright.devices` exposes the running registry.

### `openai` / `anthropic` (cooks)
- **What it provides**: SDK call patterns and the `LLMUnavailableError` error mapping for both providers.
- **Where used**: `prettyplay/llm` providers.
- **Why chosen**: provider parity is a hard contract.
- **How exactly**: one completion per attempt; classification user instructions rendered by the shared `_request` builder — placement parity by construction.

### Inline usages (`system_prompt`, `classification_prompt`) — engine cell
- **What it provides**: the verbatim system prompts of generation and classification requests.
- **Where used**: `StepGenerator` (`SYSTEM_PROMPT`), `classify_step_failure` (`CLASSIFICATION_PROMPT`).
- **Why chosen**: prompt text is engine-specific context, inline per the cookbook's inline-form criteria.
- **How exactly**: `CLASSIFICATION_PROMPT` gains the `USER INSTRUCTIONS` input line exactly as the inline usage states; `SYSTEM_PROMPT` already lists it.

### Imported Usages
- `taxonomy` from `prettyplay/failures` — path `prettyplay/failures/.usages/taxonomy.md` — consumed by `prettyplay/config` and the root for the failure-base context (`ConfigurationError` derivation, propagated kinds). Updated by the architecture stage to document the structured render; verified current.
- `facade` from `prettyplay/driver` — path `prettyplay/driver/.usages/facade.md` — consumed by `prettyplay/engine`; the page-API surface listing (`PAGE_API_SURFACE` in `generator.py`) mirrors it verbatim; unchanged by this topic (screen modes never touch the facade surface) — the file gained only a consumer note; verified current.
- `classification` from `prettyplay/llm` — path `prettyplay/llm/.usages/classification.md` — consumed by `prettyplay/engine`; documents the `user_instructions` parameter placement; verified current.
- `hooks` from `prettyplay/reporting` — path `prettyplay/reporting/.usages/hooks.md` — consumed by the root and `prettyplay/cache`; documents the full-render `error` payload; verified current.
- `generation` / `healing` from `prettyplay/engine` — paths `prettyplay/engine/.usages/{generation,healing}.md` — consumed by the root; document the error field and strict interplay; verified current.

## `.usages/` Update

### Cell: `prettyplay/config`
- **`configuration.md`** → current (nested group TOML, flat env table incl. `PRETTYPLAY_STRICT`/`PRETTYPLAY_CLASSIFICATION_PROMPT`/four `PRETTYPLAY_BROWSER_*`, hard-break section, nested merge, screen-mode table, strict section, remote endpoint rename). No additions needed.

### Cell: `prettyplay/failures`
- **`taxonomy.md`** → current (structured message template with the exact sample, block-omission rules, `error` field note, one-render rule). No additions needed.

### Cell: `prettyplay/reporting`
- **`hooks.md`** → current (full-render `error` payload section, `FailureMonitor` example, verdict-fields rule, strict note). No additions needed.

### Cell: `prettyplay/driver`
- **`facade.md`** → current (screen-mode note: the mode changes only how the context opens). No additions needed.

### Cell: `prettyplay/llm`
- **`classification.md`**, **`providers.md`** → current (`user_instructions` parameter and placement, parity section). No additions needed.

### Cell: `prettyplay/engine`
- **`generation.md`**, **`healing.md`** → current (classification instructions, error-field carrying, strict note). No additions needed.

### Cell: `prettyplay` (root)
- **`lifecycle.md`**, **`steps.md`** → current (strict mode section with team workflow, `BrowserConfig` import example, render note, addressing note). No additions needed.

No new `.usages/` files: every change falls inside existing functional domains.

## Test Stack Trace

### General Setup

- Existing conftest patterns: fake providers subclassing `LLMProvider` (renamed), fake pages/facades for engine tests, `tmp_path` for config files, `monkeypatch.setenv`/`delenv` for env overrides (every test must clear the four `PRETTYPLAY_BROWSER_*`, `PRETTYPLAY_STRICT`, `PRETTYPLAY_CLASSIFICATION_PROMPT` variables it does not set — the loader reads them greedily).
- Driver tests: stub the Playwright objects at the import boundary (`mock.patch` of `sync_playwright` / injected fakes), consistent with the existing `tests/driver/test_session.py` style.
- No real browsers, no real LLM keys in unit tests (`OPENAI_API_KEY`/`ANTHROPIC_API_KEY` unset unless the test sets a fake).

### Source File Registry

- `prettyplay/config/models.py`, `prettyplay/config/loader.py`
- `prettyplay/failures/errors.py`
- `prettyplay/driver/session.py`
- `prettyplay/llm/provider.py`, `prettyplay/llm/openai_provider.py`, `prettyplay/llm/anthropic_provider.py`, `prettyplay/llm/_request.py`
- `prettyplay/engine/text.py`, `prettyplay/engine/classification.py`, `prettyplay/engine/generator.py`, `prettyplay/engine/healer.py`
- `prettyplay/executor.py`, `prettyplay/scenario.py`, `prettyplay/__init__.py`

---

### Positive Tests

#### `test_browser_config_defaults_and_kw_only`

**Setup**: none (pure model).
**Input**: `BrowserConfig()`.
**Trace**:
```
BrowserConfig()
  → pydantic kw_only construction
    defaults applied: name="chromium", screen="", headless=True, endpoint=""
  → assert fields
```
**Assertions**:
```
config.name == "chromium"; config.screen == ""; config.headless is True; config.endpoint == ""
pytest.raises(TypeError) on BrowserConfig("chromium")   # positional rejected — kw_only
```
**Sufficiency**: pins the group schema and the kw_only requirement the merge relies on (`model_fields_set` semantics).

#### `test_config_uses_nested_browser_group_and_new_switches`

**Setup**: none.
**Input**: `Config(browser={"name": "firefox", "screen": "1280x720"}, strict=True, classification_prompt="answer in Russian")`.
**Trace**:
```
Config(**kwargs)
  → browser dict validated into BrowserConfig (nested validators run)
  → strict/classification_prompt stored
  → effective model properties unchanged
```
**Assertions**:
```
config.browser.name == "firefox"; config.browser.screen == "1280x720"
config.browser.headless is True; config.browser.endpoint == ""
config.strict is True; config.classification_prompt == "answer in Russian"
Config().strict is False; Config().classification_prompt == ""
```
**Sufficiency**: the nested group and the two new settings are load-bearing for driver/llm/executor behavior.

#### `test_load_config_reads_browser_group_and_rejects_flat_keys`

**Setup**: `tmp_path` pyproject:
```toml
[tool.prettyplay]
provider = "openai"
[tool.prettyplay.browser]
name = "firefox"
screen = "fullscreen"
headless = false
endpoint = ""
```
**Input**: `load_config(pyproject_path=str(p), overrides=None)`.
**Trace**:
```
load_config → parse → section carries browser dict → no old flat keys → Config(**merged)
```
**Assertions**:
```
config.browser.name == "firefox"; config.browser.screen == "fullscreen"
config.browser.headless is False; config.provider == "openai"
```
**Sufficiency**: the TOML group mapping is the primary integration surface.

#### `test_load_config_env_overrides_reach_the_group_and_new_settings`

**Setup**: pyproject with the group (`name="chromium"`, `screen=""`); `monkeypatch.setenv` `PRETTYPLAY_BROWSER_NAME=webkit`, `PRETTYPLAY_BROWSER_SCREEN=1280x720`, `PRETTYPLAY_STRICT=true`, `PRETTYPLAY_CLASSIFICATION_PROMPT=be terse`, `PRETTYPLAY_BROWSER_HEADLESS=0`.
**Input**: `load_config(pyproject_path=str(p))`.
**Trace**:
```
env collected → bools parsed ("true"→True, "0"→False) → group dict merged over the file group → Config
```
**Assertions**:
```
config.browser.name == "webkit"; config.browser.screen == "1280x720"
config.browser.headless is False; config.strict is True
config.classification_prompt == "be terse"
```
**Sufficiency**: flat env names for the nested group and typed scalar parsing are new contract requirements.

#### `test_render_terminal_message_full_template`

**Setup**: `verdict = FailureVerdict("product_defect", "на странице нет элемента", "проверить селектор")`.
**Input**: `render_terminal_message("кнопка осталась невидимой", "Проверить кнопку", "Locator expected to be visible", verdict)`.
**Trace**:
```
render_terminal_message
  → lines = [reason]; middle block (--- step: error:); verdict block (--- aligned lines)
  → "\n".join
```
**Assertions**:
```
text == "кнопка осталась невидимой\n---\nstep: Проверить кнопку\nerror: Locator expected to be visible\n---\nexplanation:    на странице нет элемента\nrecommendation: проверить селектор"
"explanation:" followed by exactly 4 spaces (value column = len("recommendation:") + 1)
first line has no ":" of its own
```
**Sufficiency**: the template is a parsing surface for integrators — exact bytes matter.

#### `test_verdict_render_alignment_and_multiline`

**Setup**: `FailureVerdict("rot", "line one\nline two", "fix it")`.
**Input**: `verdict.render()`.
**Assertions**:
```
render() == "explanation:    line one\n                line two\nrecommendation: fix it"
# continuation indented to the value column (16 spaces); no "category" line anywhere
FailureVerdict("rot", "", "").render() == ""
FailureVerdict("rot", "only", "").render() == "explanation:    only"   # padded to the fixed column
```
**Sufficiency**: column alignment and continuation rules are explicit contract requirements; empty-render drives block omission.

#### `test_terminal_errors_carry_render_error_field_and_types`

**Setup**: verdict as above.
**Input**: `ProductDefectError("step", "the button stayed invisible", "Locator expected to be visible", verdict)`; `IncurableStepError("step", "strict mode forbids generation — the step is missing from the cache")`.
**Trace**:
```
__init__ → render_terminal_message → Exception.__init__(render)
IncurableStepError without verdict → fallback verdict (recommendation only) in the render
```
**Assertions**:
```
str(pde) == render_terminal_message(...)  # identical text
pde.error == "Locator expected to be visible"; pde.verdict is verdict; pde.message == "the button stayed invisible"
isinstance(pde, AssertionError) and isinstance(pde, PrettyplayError)
ise.reason == "…"; ise.error == ""; ise.verdict is None
"recommendation: reword the step or refresh the cache" in str(ise)
ise.recommendation == "reword the step or refresh the cache"
not isinstance(ise, AssertionError)
LLMUnavailableError("llm unavailable: openai") — str == message; issubclass PrettyplayError
```
**Sufficiency**: one-render rule, the new error field, the fallback recommendation, the rename, and the assertion-semantics split.

#### `test_open_context_screen_modes`

**Setup**: fake Playwright module objects: `playwright.devices = {"iPhone 13": {"viewport": {"width": 390, "height": 664}, "user_agent": "ua", "has_touch": True, "is_mobile": True, "device_scale_factor": 3, "default_browser_type": "webkit"}}`; recording `browser.new_context`; recording `engine.launch`.
**Input** (parametrized): `BrowserConfig(screen=s)` for `s in {"", "1280x720", "iPhone 13", "fullscreen"}` × headless/endpoint combinations.
**Trace**:
```
DriverSession(Config(browser=BrowserConfig(screen=s, headless=h, endpoint=e))).open_context()
  → _launch (launch/connect with args per fullscreen+family) → _screen_context_params → new_context(**params)
```
**Assertions**:
```
"" (any mode)              → new_context() called with no kwargs
"1280x720" (any mode)      → new_context(viewport={"width": 1280, "height": 720})
"iPhone 13" (any mode)     → new_context(**devices["iPhone 13"])
"fullscreen" + headless=False + endpoint="" + chromium
                           → launch(args=["--start-maximized"]) and new_context(no_viewport=True)
"fullscreen" + headless=False + endpoint="" + chrome (channel)
                           → launch(channel="chrome", args=["--start-maximized"]) and new_context(no_viewport=True)
"fullscreen" + headless=True (or endpoint set) → new_context(viewport={"width": 1920, "height": 1080}), no launch args
"fullscreen" + firefox headed → launch without args; new_context(no_viewport=True)
"fullscreen" + remote connect → connect path; viewport pinned 1920x1080
```
**Sufficiency**: every row of the screen precedence matrix; pins the approved firefox/webkit decision.

#### `test_classify_step_failure_passes_classification_instructions`

**Setup**: `RecordingProvider` (records kwargs) stub; fake page returning snapshot "snap".
**Input**: `classify_step_failure(Config(classification_prompt="answer in Russian"), provider, "step", "code", "err", page)`.
**Trace**:
```
classify_step_failure → provider.classify_failure(prompt=CLASSIFICATION_PROMPT, user_instructions="answer in Russian", …)
```
**Assertions**:
```
recorded["user_instructions"] == "answer in Russian"
"- USER INSTRUCTIONS: the project's classification guidance, when configured" in recorded["prompt"]
Config(classification_prompt="") → recorded["user_instructions"] == ""
```
**Sufficiency**: the classification instructions reach the port; the system prompt lists the new input.

#### `test_provider_classification_instructions_placement_parity`

**Setup**: fakes for the openai/anthropic SDK clients capturing messages (existing provider test style).
**Input**: `provider.classify_failure(prompt="sys", user_instructions="be terse", step_text="s", code="c", error="e", snapshot="snap", screenshot=None)` on both providers.
**Trace**:
```
build_classification_fields → "STEP:…\n\nCODE:…\n\nERROR:…\n\nPAGE SNAPSHOT:…\n\nUSER INSTRUCTIONS:\nbe terse"
→ SDK call with system="sys"
```
**Assertions**:
```
user content of both providers ends with "USER INSTRUCTIONS:\nbe terse"
no "USER INSTRUCTIONS" block when user_instructions=""
generation request (generate_step_code) placement unchanged: after PAGE API, before CODE/ERROR
```
**Sufficiency**: placement parity is an absolute contract across both SDKs.

#### `test_executor_strict_cache_miss_raises_without_generation`

**Setup**: executor wired with a cache whose `load` returns `None`; recording generator/healer; `Config(strict=True)`; fake provider.
**Input**: `executor.execute("Нажать «Войти»", "action", page)`.
**Trace**:
```
execute → on_step_started → cache.load → None → strict branch → IncurableStepError raised
→ outer except: on_step_failed(error=str(exc)); no verdict event; raise
```
**Assertions**:
```
pytest.raises(IncurableStepError); exc.reason == "strict mode forbids generation — the step is missing from the cache"
exc.error == "" and exc.verdict is None
generator.generate not called; healer.heal not called; budgets.try_generation never called
"step: Нажать «Войти»" in str(exc); "recommendation:" in str(exc)      # fallback verdict
on_step_failed payload["error"] == str(exc)                            # one render
no on_generation_started / on_healing_started events
```
**Sufficiency**: the headline strict guarantee — nothing is ever generated.

#### `test_executor_strict_failed_cached_step_classifies_only`

**Setup**: cache returns a `CachedStep` whose code raises a `TimeoutError` (action) / assertion text (assertion); fake provider returning `FailureClassification("product_defect" | "rot" | "incurable", …)`, then a second run with a provider raising `LLMUnavailableError`.
**Input**: `executor.execute(step_text, step_type, page)` under `Config(strict=True)`.
**Trace**:
```
run_step_code raises → format_step_error → strict → classify_step_failure
  product_defect → ProductDefectError(explanation, error_text, verdict)
  rot/incurable  → IncurableStepError(explanation, error_text, verdict)
  LLM unavailable → WARNING + raise by step type without verdict
```
**Assertions**:
```
product_defect + assertion: pytest.raises(ProductDefectError); exc.verdict.category == "product_defect"
  exc.error == "TimeoutError: locator.click: Timeout 30000ms exceeded"  (typed prefix for action errors)
  assertion-failure error field carries no "AssertionError" prefix
rot: pytest.raises(IncurableStepError); healer.heal not called; no on_healing_started; budgets.try_healing never called
LLM unavailable + assertion step → ProductDefectError, verdict is None,
  "the step failed in strict mode without an llm verdict" == exc.message
LLM unavailable + action step → IncurableStepError, same reason wording, exc.error carries the full text
caplog has one WARNING "verdict skipped: llm unavailable"
provider.generate_step_code never called on any strict run
```
**Sufficiency**: the full strict failure matrix — classification-only, no regeneration, quiet skip, by-step-type fallback.

#### `test_executor_events_carry_full_render_and_verdict_fields`

**Setup**: non-strict executor; healer stub raising `ProductDefectError("step", "msg", "err-text", FailureVerdict("product_defect", "expl", "rec"))`; recording hooks.
**Input**: `executor.execute("step", "assertion", page)` with a cached step failing at `run_step_code`.
**Assertions**:
```
hook on_step_failed payload["error"] == str(raised) == full render (contains "---" and "recommendation:")
hook on_step_verdict payload == {"step_text": "step", "category": "product_defect", "explanation": "expl", "recommendation": "rec"}
payload fields come from the verdict object (never parsed from the render)
```
**Sufficiency**: the one-render rule and structured verdict event are the reporting contract.

#### `test_facade_reexports_browser_config`

**Setup/Input**: `from prettyplay import BrowserConfig, PrettyConfig, PrettyTest`.
**Assertions**:
```
BrowserConfig is prettyplay.config.models.BrowserConfig; "BrowserConfig" in prettyplay.__all__
```
**Sufficiency**: explicit acceptance criterion of the task.

---

### Negative Tests

#### `test_load_config_rejects_each_old_flat_key`

**Setup**: three pyproject files, each with one old flat key (`browser = "chromium"`, `headless = true`, `browser_endpoint = "ws://x"`).
**Input**: `load_config(pyproject_path=…)` for each.
**Assertions**:
```
pytest.raises(ConfigurationError); "browser_endpoint" in str(excinfo.value)
"[tool.prettyplay.browser]" in str(excinfo.value); one line per present key
a browser key holding a TABLE ([tool.prettyplay.browser]) does NOT raise
```
**Sufficiency**: the hard pre-1.0 break must be loud and point at the new home.

#### `test_load_config_env_scalar_parse_failures`

**Setup**: `monkeypatch.setenv` `PRETTYPLAY_STRICT=maybe`, `PRETTYPLAY_BROWSER_HEADLESS=yes`, `PRETTYPLAY_GENERATION_ATTEMPTS=three` (separate cases).
**Input**: `load_config(pyproject_path=…)`.
**Assertions**:
```
pytest.raises(ConfigurationError); str names the setting, the received value and the accepted form
e.g. "strict: received 'maybe' — allowed: a boolean (true/false/1/0)"
PRETTYPLAY_BROWSER=yes-variant rejected (only true/false/1/0) — pydantic's wider lax set is bypassed
```
**Sufficiency**: "never a silent ignore" — the new typed env parsing contract.

#### `test_browser_config_validation_failures`

**Setup/Input**: `BrowserConfig(name="opera")`; `BrowserConfig(endpoint="http://x")`; `Config(browser={"screen": "0x720"})`.
**Assertions**:
```
ValidationError loc for name/endpoint inside the group: ("browser", "name") / ("browser", "endpoint") / ("browser", "screen")
through load_config: rendered line starts "browser.name: received 'opera' — allowed: chromium, firefox, webkit, chrome, msedge"
"0x720" rejected ("must be positive"); "fullscreen" and "iPhone 13" accepted verbatim
```
**Sufficiency**: format-level screen validation and nested error rendering.

#### `test_open_context_unknown_device_fails_loudly`

**Setup**: fake registry `{"iPhone 13": …, "Pixel 7": …}`; `BrowserConfig(screen="iPhon 13")`.
**Input**: `session.open_context()`.
**Assertions**:
```
pytest.raises(playwright Error); "iPhon" in str(exc); "iPhone 13" in str(exc)   # close-name suggestion
```
**Sufficiency**: the unknown-device path must suggest, not just fail.

#### `test_provider_renames_are_total`

**Setup/Input**: import surfaces.
**Assertions**:
```
prettyplay.failures.LLMUnavailableError exists; the old spelling LlmUnavailableError raises AttributeError
prettyplay.llm.{LLMProvider, OpenAIProvider, create_provider} exist; old spellings gone
create_provider(Config(provider="openai")) returns OpenAIProvider instance (isinstance LLMProvider)
```
**Sufficiency**: the initialism rename is total — no dual names.

---

### Edge Case Tests

#### `test_render_terminal_message_block_omission`

**Input**: `render_terminal_message("reason", "", "", None)`; `render_terminal_message("reason", "step", "", None)`; `render_terminal_message("reason", "", "err", None)`; verdict with both fields empty.
**Assertions**:
```
"reason" alone — no "---" at all
"reason\n---\nstep: step" — no error line, no verdict block
"reason\n---\nerror: err" — no step line
FailureVerdict("rot", "", "rec") → block "recommendation: rec" only
text never ends with "---"
```
**Sufficiency**: the omission rules are explicit contract requirements.

#### `test_load_config_nested_group_merge_matrix`

**Setup**: file group `{"name": "firefox", "headless": false}`; cases:
(a) `overrides=PrettyConfig(browser=BrowserConfig(screen="fullscreen"))`;
(b) `overrides=PrettyConfig(browser=BrowserConfig())`;
(c) `overrides=PrettyConfig(strict=False)` over file `strict=true`;
(d) `overrides=PrettyConfig(browser=BrowserConfig(name=""))` (explicit empty string inside the group).
**Assertions**:
```
(a) browser == firefox, screen == "fullscreen", headless is False    # file values survive, set fields win
(b) browser == file group unchanged                                   # untouched defaults never overwrite
(c) strict is False                                                   # explicit False overrides too
(d) name stays "firefox"                                              # empty string means unset inside the group too
```
**Sufficiency**: the nested merge is the subtlest new loader behavior.

#### `test_incurable_fallback_verdict_never_fires_the_event`

**Setup**: strict executor, cache miss; recording hooks.
**Assertions**:
```
"recommendation: reword the step or refresh the cache" in the on_step_failed error payload
on_step_verdict never called; raised.verdict is None
```
**Sufficiency**: the fallback is render-only — structured consumers must not see a phantom verdict.

#### `test_generator_carries_full_error_text_in_terminal_failures`

**Setup**: generator with a provider returning code that raises `AssertionError("expected visible")` on the first candidate; classification stub.
**Assertions**:
```
ProductDefectError.error == "expected visible" (full, no prefix, no truncation at 200 chars — use a >200-char message)
IncurableStepError on budget exhaustion: exc.error == last candidate full text; exc.reason == "generation attempt budget exhausted" (no colon, no embedded error)
```
**Sufficiency**: the error field replaces the old truncation policy; reasons are colon-free.

#### `test_format_step_error_message_less_exceptions`

**Setup**: none (pure function; `prettyplay.engine.text.format_step_error`).
**Input**: `AssertionError()`, `AssertionError("expected visible")`, `TimeoutError()`, `TimeoutError("click timeout")`.
**Trace**:
```
format_step_error → text = str(exc)
  AssertionError, empty text      → "" (the render then omits the error line — block-omission rule)
  AssertionError, text           → text verbatim (no prefix)
  other error, empty text        → the bare type name (no dangling ": ")
  other error, text              → f"{type name}: {text}"
```
**Assertions**:
```
format_step_error(AssertionError()) == ""
format_step_error(AssertionError("expected visible")) == "expected visible"
format_step_error(TimeoutError()) == "TimeoutError"
format_step_error(TimeoutError("click timeout")) == "TimeoutError: click timeout"
```
**Sufficiency**: pins the boundary the old `first_line_short` helper documented — a message-less exception never crashes reporting and healing inputs, and the byte-exact render never grows a dangling `": "`.

#### `test_healer_and_strict_error_fields_end_to_end`

**Setup**: non-strict healer with a cached step failing `TimeoutError("click timeout")`; classification product_defect.
**Assertions**:
```
ProductDefectError.error == "TimeoutError: click timeout"; str(exc) contains "error: TimeoutError: click timeout"
regeneration-exhaustion path: outer IncurableStepError.verdict is the rot classification verdict; .error is the inner last-candidate text
```
**Sufficiency**: error-field cascade through healer and exhaustion re-raise.

#### `test_pretty_test_wires_config_and_provider_into_executor`

**Setup/Input**: `PrettyTest(cache_key="k", config=PrettyConfig(strict=True, browser=BrowserConfig(screen="fullscreen", headless=False)))`; inspect the wired executor.
**Assertions**:
```
executor._config.strict is True; executor._config.browser.screen == "fullscreen"
executor provider is the runtime provider instance
```
**Sufficiency**: the two new constructor wires actually carry the strict switch and the classification port.

## Additional Instructions for the Implementation Agent

- Apply the rename sweep first (`LLMUnavailableError`, `LLMProvider`, `OpenAIProvider`) across source and tests — it is mechanical and unblocks everything else.
- Remove `first_line_short`/`SHORT_ERROR_LENGTH` and introduce `format_step_error` in `prettyplay/engine/text.py`; update every consumer: `prettyplay/executor.py`, `prettyplay/engine/generator.py` (the `_loop` call sites — see Algorithm Design) and `tests/test_executor.py`. No other consumer exists.
- Export `BrowserConfig` from `prettyplay/config/__init__.py` (beside `PrettyConfig`) — the facade re-export and the test `test_facade_reexports_browser_config` resolve through it. `render_terminal_message` must be exported from `prettyplay/failures/__init__.py` (contract routine), alongside the renamed `LLMUnavailableError`.
- Terminal failures set their exception text via `Exception.__init__` with the render — do not route through `PrettyplayError.__init__` (it would overwrite the public `message`/`reason` attributes with the full render).
- Keep `PrettyTest` construction credential-free: `runtime.provider` builds only the lightweight provider object.
- The canonical WxH form is `^\d+x\d+$` (lowercase `x`, digits only); positivity is enforced only in the config validator — the driver merely re-detects the shape.
- The unknown-device error and all screen resolution run inside the driver thread (`worker.run`) — `playwright.devices` belongs to the started session.
- Every test touching `load_config` must pin/clear the relevant `PRETTYPLAY_*` env vars — the loader greedily reads six browser/strict/instruction variables (`PRETTYPLAY_BROWSER_{NAME,SCREEN,HEADLESS,ENDPOINT}`, `PRETTYPLAY_STRICT`, `PRETTYPLAY_CLASSIFICATION_PROMPT`); three of them are new.
- Validation gates: `pytest tests/ -x` green; `ruff check prettyplay/` clean; `python -c "from prettyplay import BrowserConfig, PrettyConfig, PrettyTest"`.
- Do not touch `prettyplay/cache` — the addressing and budgets are contractually unchanged (budgets are simply never consumed on the strict path).
- Docstrings for all new/changed public entities follow the Google style of the surrounding code; module docstrings of `errors.py`, `models.py`, `loader.py`, `session.py`, `executor.py`, `text.py`, `classification.py` must drop statements about the old flat keys, the verdict-tail render and `first_line_short`.
