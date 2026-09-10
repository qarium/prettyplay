# Design Document: `the-first-version`

The complete architectural specification of the Prettyplay implementation — UI tests in human
language with a repository step cache, LLM code generation and self-healing. The document is
derived from the CODEMANIFEST contracts of the eight cells materialized by the apply-architecture
stage, and has passed the contract-validation, tracing and algorithmization phases of the
goga-design-by-changes skill. No implementation code is written at this stage — it fixes "what"
and "how" to implement.

---

## Contract Changes

### Changed CODEMANIFEST Files

Greenfield project: before the code stage not a single cell existed (only an empty
`prettyplay/__init__.py`). All 8 manifests are new; git status `??` (untracked), the diff against
`master` is empty, so the change list is assembled from the fact of creation:

- `prettyplay/CODEMANIFEST` — library facade: `PrettyTest`, `StepExecutor`, `PrettyplayRuntime`, `get_runtime` (NEW)
- `prettyplay/config/CODEMANIFEST` — settings: `Config`, `load_config` (NEW)
- `prettyplay/reporting/CODEMANIFEST` — visibility: `StepHooks`, `StepReporter` (NEW)
- `prettyplay/failures/CODEMANIFEST` — failure taxonomy: `PrettyplayError` + 3 mutations (NEW)
- `prettyplay/driver/CODEMANIFEST` — Playwright driver: `DriverSession`, `PageFacade`, `LocatorFacade` (NEW)
- `prettyplay/cache/CODEMANIFEST` — step cache: `normalize_step_text`, `StepIdentity`, `CachedStep`, `StepCache`, `RunBudgets` (NEW)
- `prettyplay/llm/CODEMANIFEST` — LLM port: `LlmProvider` + 2 mutations, `create_provider`, `FailureClassification` (NEW)
- `prettyplay/engine/CODEMANIFEST` — engine: `run_step_code`, `StepGenerator`, `StepHealer` (NEW)

### New Entities

| Entity | Cell | location | Kind |
|---|---|---|---|
| `Config` | config | models.py | Entity (12 properties: 10 fields + 2 computed) |
| `load_config` | config | loader.py | Routine |
| `StepHooks` | reporting | hooks.py | Entity (8 no-op methods) |
| `StepReporter` | reporting | reporter.py | Entity (emit) |
| `PrettyplayError` | failures | errors.py | Entity (base) |
| `ProductDefectError` / `IncurableStepError` / `LlmUnavailableError` | failures | errors.py | `PrettyplayError::` mutations |
| `DriverSession` | driver | session.py | Entity (open_context, close) |
| `PageFacade` | driver | page.py | Entity (7 methods + url) |
| `LocatorFacade` | driver | page.py | Entity (6 methods) |
| `normalize_step_text` | cache | text.py | Routine (pure function) |
| `StepIdentity` | cache | models.py | Entity (4 properties, incl. filename) |
| `CachedStep` | cache | models.py | Entity (3 properties) |
| `StepCache` | cache | store.py | Entity (load, save + root, writable) |
| `RunBudgets` | cache | budgets.py | Entity (try_generation, try_healing) |
| `LlmProvider` | llm | provider.py | Entity (generate_step_code, classify_failure) |
| `OpenAiProvider` / `AnthropicProvider` | llm | *_provider.py | `LlmProvider::` mutations |
| `create_provider` | llm | provider.py | Routine |
| `FailureClassification` | llm | models.py | Entity (3 properties) |
| `run_step_code` | engine | execution.py | Routine |
| `StepGenerator` | engine | generator.py | Entity (generate, regenerate) |
| `StepHealer` | engine | healer.py | Entity (heal) |
| `PrettyTest` | root | scenario.py | Entity (action, assertion, add_hooks, close + cache_key) |
| `StepExecutor` | root | executor.py | Entity (execute) |
| `PrettyplayRuntime` | root | runtime.py | Entity (open_page, close + 4 properties) |
| `get_runtime` | root | runtime.py | Routine (process-wide singleton) |

### Changed Entities

None — all entities are new.

### Deleted Entities

None.

### Usages and Annotations Changes

- Three contract fixes approved and applied (see Applied Fixes): the `heal` signature, the `emit`
  payload type, the taxonomy error properties.
- Two cell usage files updated (see the `.usages/` Update section): `healing.md`, `hooks.md`.

---

## Applied Fixes

### Fixed CODEMANIFEST Defects

All three defects were found by the consistency audit (Phase 3), approved by the user (option A)
and applied; a repeated `goga lint` — 8 cells, 0 errors.

1. **`prettyplay/engine/CODEMANIFEST` → `StepHealer.heal`**:
   `heal(step: CachedStep, error: str, page: PageFacade)` →
   `heal(step: CachedStep, error: str, previous_steps: list[str], page: PageFacade)`
   (reason: Interface↔Interface — the contract had nowhere to obtain `previous_steps`, required by
   `StepGenerator.regenerate`; the scenario context is owned by `StepExecutor`).
   An accompanying edit in `prettyplay/CODEMANIFEST` → `StepExecutor.execute`, algorithm step 4:
   "delegate to the healer heal with the failure description **and the scenario context**".
2. **`prettyplay/reporting/CODEMANIFEST` → `StepReporter.emit`**:
   `payload: dict[str, str]` → `payload: dict[str, str | int]`
   (reason: Interface↔Type — `on_generation_started(step_text: str, attempt: int)` requires an
   int value; a string payload is incompatible with the hook contract).
3. **`prettyplay/failures/CODEMANIFEST` → error properties**
   (reason: Annotations↔Entity — the annotations require "carries all three fields", the
   taxonomy.md usage reads `info.value.recommendation`, but the fields were only constructor
   parameters):
   - `ProductDefectError`: + `step_text -> str`, `message -> str`
   - `IncurableStepError`: + `step_text -> str`, `reason -> str`, `recommendation -> str`
   - `LlmUnavailableError`: + `message -> str`

---

## Entity Interaction and Data Flow

### Interaction Diagram

```
                    integrator (test)
                          │  PrettyTest(cache_key[, cache_path]) / action / assertion
                          ▼
┌───────────────────────────── prettyplay (root) ──────────────────────────────────────┐
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
│              │                                    success │             failure │      │
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

### Data Flows

**Flow A — a step on a cache miss (the first run).**
`PrettyTest.action(text)` → lazily `PrettyplayRuntime.open_page()` → `DriverSession.open_context()`
(lazy browser launch) → `PageFacade` → `StepExecutor.execute(text, "action", page)` →
`emit("on_step_started")` → `normalize_step_text(text)` → `StepIdentity` → `StepCache.load` →
`None` → `StepGenerator.generate(identity, text, previous_steps, page)`: `RunBudgets.try_generation`
→ `emit("on_generation_started", attempt)` → `page.aria_snapshot()` (+ `screenshot()` with
`send_screenshots`) → `LlmProvider.generate_step_code(generation_prompt, …, page_api, None, None)`
→ `run_step_code(code, page)` → success → `CachedStep(identity, code, created_at)` →
`StepCache.save` (tmp + `os.replace`, `emit("on_cache_saved")`) → the executor appends the
scenario context → `emit("on_step_passed")`.

**Flow B — a step on a hit (a cached run, no LLM).**
`execute` → `load` → `CachedStep` → `run_step_code(cached.code, page)` → success → context →
`on_step_passed`. No provider is created, the network is untouched (except the page itself), no
keys are needed.

**Flow C — a cached step is broken (rot) → self-healing.**
`run_step_code` raised an exception → a short error description → `StepHealer.heal(step, error,
previous_steps, page)` → assembling the classification inputs → `LlmProvider.classify_failure(
classification_prompt, …)` → `FailureClassification` → `emit("on_healing_started", category)` →
on `rot`: `StepGenerator.regenerate(identity, text, previous_steps, page, existing_code, error)`
— a loop with the `try_healing` budget, the candidate is executed, success → `cache.save`
(overwriting the same file, atomically) → `emit("on_healed")` → executor: context +
`on_step_passed`.

**Flow D — configuration.**
`get_runtime()` (first call) → `load_config(None)`: search for pyproject.toml upward from cwd →
tomllib/tomli → the `[tool.prettyplay]` section → env overrides `PRETTYPLAY_*` → `Config`
validation → `PrettyplayRuntime(config)`.

### Entity Dependencies

Initialization order (bottom-up, an acyclic DAG; confirmed by `goga schema`):

```
config, reporting, failures          — leaves
driver        ← config
cache         ← config, reporting
llm           ← config, failures
engine        ← config, reporting, failures, driver, cache, llm
prettyplay    ← all seven
```

Runtime object-creation order: `load_config` → `PrettyplayRuntime` (config eagerly;
`RunBudgets` eagerly; `DriverSession` and `LlmProvider` lazily) → per test: `StepReporter` →
`StepCache` → `StepGenerator` → `StepHealer` → `StepExecutor` → lazily `PageFacade` (the first
step).

---

## Code Stack Trace

The trace covers all contract entry points, with type and logic checkpoints after each step.
Summarized per cell; all checkpoints passed (no defects remain after fixes D1–D3).

### Trace: `load_config`

#### Chain
1. **Input**: `pyproject_path: str | None` (None — auto-search) → checkpoint: the type admits
   both modes ✓
2. Path resolution: an explicit argument, otherwise walk upward from cwd to the first
   `pyproject.toml` (`pathlib.Path.cwd().parents`) → checkpoint: the found path is a `Path`,
   exists ✓
3. TOML parsing: `sys.version_info >= (3, 11)` → `tomllib`, otherwise `tomli` (see `pydantic`)
   → checkpoint: `dict` ✓
4. Extraction of `data.get("tool", {}).get("prettyplay", {})` — a missing section = empty
   → checkpoint: a missing section is not an error ✓ (contract: "a missing section is an empty
   section")
5. Env overrides: for each of the 10 fields — `PRETTYPLAY_<UPPER>` is applied if the variable is
   set (`os.environ.get(name) is not None`, including an empty value — per the contract "when
   the variable is set")
   → checkpoint: a str from env is coerced by pydantic v2 (lax) into `int`/`bool` — "3"→3,
   "false"→False ✓; an empty string in a str field is legal (an empty setting value), an empty
   string in an int/bool field — a loud ValidationError naming the setting ✓
6. `Config(**merged)` → checkpoint: an invalid value → a pydantic error naming the field, loud,
   actionable ✓
7. `cache_root == ""` → the absolute `<pyproject_dir>/.prettyplay/cache/` → checkpoint: the
   field is always an absolute path after load ✓
8. **Output**: `Config` — the single source of immutable settings ✓

#### Checkpoint Summary
- Input/output types: passed
- Env → int/bool coercion: passed (pydantic lax mode)
- cache_root resolution: passed

### Trace: `Config`

1. **Input**: kwargs (`kw_only=True`, all fields with empty defaults: provider="openai",
   browser="chromium", model="", attempts 3/2, send_screenshots=False) ✓
2. Validators: `provider ∈ {openai, anthropic}`, `browser ∈ {chromium, firefox, webkit}`,
   `generation_attempts > 0`, `healing_attempts > 0` (field_validator / Literal + GT)
   → checkpoint: invalid — ValidationError, the field name in the message ✓
3. Computed: `effective_generation_model` = `generation_model or model`; classification
   likewise → checkpoint: an empty string falls back to `model` ✓
4. **Output**: an immutable pydantic model (model_config frozen is not required; the contract
   only requires "single source of the immutable configuration part" — one load per run) ✓

### Trace: `StepReporter.emit`

1. **Input**: `event: str`, `payload: dict[str, str | int]` → checkpoint: event names match the
   `StepHooks` methods one-to-one ✓
2. `logger = logging.getLogger("prettyplay")`; `extra` is built by sanitizing the payload (see
   Algorithm Design — keys colliding with LogRecord get the `ctx_` prefix); `logger.log(level,
   event, extra=extra)`
   → checkpoint: the `filename` key of the on_cache_saved event collides with the reserved
   LogRecord attribute — `Logger.makeRecord` raises `KeyError: "Attempt to overwrite 'filename'
   in LogRecord"` (empirically confirmed on Python 3.12 at an enabled level) — the collision is
   eliminated by sanitization: in the log record the key is `ctx_filename`, the hooks receive
   the original kwargs `**payload` ✓; the remaining payload keys (step_text, step_type, error,
   attempt, category, explanation, recommendation, reason) are not reserved ✓; levels: lifecycle
   — INFO, cache-write skip and hook failure — WARNING ✓
3. For each hook in registration order: `getattr(hook, event)(**payload)` in try/except
   → checkpoint: a hook exception → `logger.warning` + skip, the run continues ✓
4. **Output**: side effects (log + hook calls), returns nothing ✓

### Trace: `StepHooks`

A base with 8 no-op methods; overridden by the integrator. The contract is synchronous, without
queues or retries ✓. Payload types match emit: `attempt: int`, the rest str ✓ (after D2).

### Trace: `PrettyplayError` (+ mutations)

1. **Input**: message / (step_text, message) / (step_text, reason, recommendation) ✓
2. Fields are kept as attributes (properties declared after D3) ✓
3. `IncurableStepError.__str__` renders all three fields ✓ (the "rendered message includes each
   of them" requirement)
4. **Output**: three distinguishable kinds, all caught by a single `except PrettyplayError` ✓

### Trace: `DriverSession.open_context` / `close`

1. **Input**: no arguments (state is config) ✓
2. Lazy start: the constructor launches nothing; the first call is `sync_playwright().start()`
   (the session lives for the whole run, hence an explicit start, not a `with` block), then
   `browsers[config.browser].launch()` — a `{chromium, firefox, webkit}` dictionary per the cook
   → checkpoint: the browser is launched exactly once per run ✓
3. `browser.new_context()` → `context.new_page()` → the `PageFacade(page, context)` wrapper
   → checkpoint: each page gets its own isolated context ✓
4. `close()`: if the browser is running — `browser.close()` + `playwright.stop()`; otherwise a
   no-op → checkpoint: safe when never launched ✓
5. **Output**: `PageFacade` ✓

### Trace: `PageFacade` / `LocatorFacade`

- `open(url)` → `page.goto(url)` (waits for "load" itself) ✓
- `find_by_role(role, name)` → `page.get_by_role(role, name=name)` → `LocatorFacade` ✓
- `find_by_label(label)` → `page.get_by_label(label)` ✓
- `find_by_text(text)` → `page.get_by_text(text)` ✓
- `aria_snapshot()` → `page.locator("body").aria_snapshot()` (per the cook — the primary LLM
  input) ✓
- `screenshot()` → `page.screenshot(full_page=True)` → `bytes` ✓
- `url` → `page.url` ✓; `close()` → `context.close()` (the browser stays alive) ✓
- `LocatorFacade`: `click`→`locator.click`; `fill`→`locator.fill(value)`;
  `select_option`→`locator.select_option(value)`; `expect_visible`→`expect(loc).to_be_visible()`;
  `expect_text`→`expect(loc).to_contain_text(text)` (the disjunction "equals or contains" =
  contains, a superset of equals); `expect_enabled`→`expect(loc).to_be_enabled()`
  → checkpoint: all waits go through `playwright.sync_api.expect`, auto-waits, no fixed delays
  ✓; a failed wait raises AssertionError → "destined for failure classification" ✓
  → checkpoint: no raw Playwright object escapes outward (return types are str/bytes/
  LocatorFacade) ✓

### Trace: `normalize_step_text`

1. **Input**: `text: str` ✓
2. `unicodedata.normalize("NFC", text)` → `.strip()` → `re.sub(r"\s+", " ", …)` → `.casefold()`
   → checkpoint: a pure function, no I/O and no locale ✓; "Нажать Войти" ≡ "нажать  войти " ✓
3. **Output**: `normalized: str` ✓

### Trace: `StepIdentity`

1. **Input**: the triple (cache_key, step_type, normalized_text), kw_only ✓
2. `filename`: `identity_string = "\x1f".join((cache_key, step_type, normalized_text))`
   (Unit Separator — not typed on a keyboard, never occurs in sentences) →
   `hashlib.sha256(identity_string.encode("utf-8")).hexdigest()` → `f"{digest}.py"`
   → checkpoint: the file name need not be a python identifier (a hex digest may start with a
   digit) — load parses the file text, no import by name is performed ✓;
   determinism and discrimination of triples ✓ (sha256)
3. **Output**: a model with the computed `filename` ✓

### Trace: `StepCache.load`

1. **Input**: `identity: StepIdentity` ✓
2. Target file: `root / (path or "") / identity.filename` → missing → `None`
   → checkpoint: a miss is not an error ✓
3. Module text reading: parse the header metadata (module constants `STEP_TEXT`, `CACHE_KEY`,
   `STEP_TYPE`, `CREATED_AT`), the tail from the first `def step(` is the code
   → checkpoint: the format is fixed, the file is a valid python module (a CachedStep
   requirement); a check that `CACHE_KEY`/`STEP_TYPE`/`STEP_TEXT` match the requested identity —
   on a mismatch (a manual file edit) → `None` (a protective miss) ✓; a structurally damaged
   file (an invalid header/literal, missing fields or a `def step(` tail, an unreadable file) →
   `None` (a protective miss, the run does not crash — the contract "The cache is always read")
   ✓
4. **Output**: `CachedStep | None` ✓

### Trace: `StepCache.save`

1. **Input**: `step: CachedStep` ✓
2. Directory: `os.makedirs(target_dir, exist_ok=True)`; a writability check (see Algorithm
   Design) → read-only → `emit("on_cache_skipped", reason="read-only cache")` and return
   → checkpoint: the run does not crash ✓
3. Serialization: header constants via `repr()` of the values + an empty line + the step code
   → checkpoint: the generated file is importable ✓
4. A temporary file in the target directory (`tempfile.mkstemp(dir=target_dir, prefix=".tmp-",
   suffix=".py")`) → `os.replace(tmp, target)` → checkpoint: atomic, a partial file is never
   visible ✓
5. Windows, target busy: a short replace retry loop (3 attempts, a 0.1 s pause — a library-level
   backoff, not a page wait) → no luck → `on_cache_skipped` → checkpoint: the run does not
   crash, last-write-wins under concurrent writers ✓
6. Success → `emit("on_cache_saved", {"step_text": identity.normalized_text, "filename": …})` ✓
7. **Output**: side effect — a file in the repository ✓

### Trace: `RunBudgets.try_generation` / `try_healing`

1. **Input**: `identity: StepIdentity` ✓
2. The registry key is `identity.filename: str` (deterministic, collision-free; pydantic models
   are unhashable by default — a string key is simpler and more robust)
3. `counters_gen[key] < generation_limit` → increment, `True`; otherwise `False`. Healing
   likewise, in a separate dict → checkpoint: separate limits, one registry per process ✓
4. **Output**: `allowed: bool`; `False` → the caller turns it into IncurableStepError ✓

### Trace: `create_provider`

1. `config.provider == "openai"` → `OpenAiProvider(config)`; `"anthropic"` →
   `AnthropicProvider(config)`
2. An unknown value → a loud actionable error listing the supported ones
   → checkpoint: double protection (Config already validates the Literal — belt and suspenders)
   ✓
3. **Output**: `LlmProvider` ✓

### Trace: `OpenAiProvider` / `AnthropicProvider` (parity)

1. **Input**: `config: Config` ✓
2. Lazy client: the constructor does NOT read env (the runtime requirement: "Constructing the
   runtime never requires LLM credentials") ✓; on the first request —
   `os.environ["OPENAI_API_KEY"]` / `["ANTHROPIC_API_KEY"]`; missing/empty →
   `LlmUnavailableError` naming the provider and the variable ✓; a non-empty `config.base_url`
   → passed to the client constructor ✓
3. `generate_step_code(prompt, step_text, previous_steps, snapshot, screenshot, page_api,
   existing_code, error)`:
   - openai: `client.chat.completions.create(model=config.effective_generation_model,
     messages=[{"role":"system","content":prompt}, {"role":"user","content": user_content}])`,
     where user_content is a text block with the STEP / PREVIOUS STEPS / PAGE SNAPSHOT / PAGE
     API / CODE / ERROR fields; with `screenshot is not None` — a list of blocks
     `[{"type":"text","text":…}, {"type":"image_url","image_url":{"url":"data:image/png;base64,…"}}]`
   - anthropic: `client.messages.create(model=config.effective_generation_model, system=prompt,
     max_tokens=1024, messages=[{"role":"user","content": …}])`; the screenshot is a block
     `{"type":"image","source":{"type":"base64","media_type":"image/png","data":…}}`
   → checkpoint: one request per attempt; budgets live outside the provider ✓; the system prompt
   is passed verbatim ✓
4. Text extraction: openai `response.choices[0].message.content`; anthropic
   `message.content[0].text` → checkpoint: both return `str` ✓
5. An SDK error (`openai.OpenAIError` / `anthropic.AnthropicError`) → `LlmUnavailableError`
   … from error, naming the provider → checkpoint: the taxonomy is uniform for both ✓
6. **Output**: `code: str` — without provider-specific constructs (imposed by the prompt) ✓

### Trace: `classify_failure`

1. **Input**: prompt=classification_prompt, step_text, code, error, snapshot, screenshot? ✓
2. One request (the `effective_classification_model` model), the answer is a single line
   `category | explanation | recommendation` ✓
3. Parsing: strip → the first non-empty line → split `"|"` into 3 parts → strip each
   → checkpoint: category ∈ {rot, product_defect, incurable} ✓
4. An unparsable/unknown verdict → a protective mapping to `incurable` ("classification
   unparsable…") → checkpoint: a safe default — fails loudly, never masks a defect ✓
5. **Output**: `FailureClassification(category, explanation, recommendation)` ✓

### Trace: `run_step_code`

1. **Input**: `code: str`, `page: PageFacade` ✓
2. `namespace: dict = {}`; `exec(compile(code, "<prettyplay-step>", "exec"), namespace)`
   → checkpoint: an isolated namespace, no write into `sys.modules` ✓
3. `fn = namespace["step"]` — the single callable of the fixed form
   → checkpoint: the name is fixed by the generation prompt ✓
4. `fn(page)` — an exception from the step code propagates as is
   → checkpoint: no swallow, no retry, no LLM, no network ✓
5. **Output**: None; side effect — actions on the page ✓

### Trace: `StepGenerator.generate` / `regenerate`

1. **Input**: identity, step_text, previous_steps, page (+ existing_code, error for regenerate)
   ✓
2. The attempt loop (numbering from 1):
   - budget: generate → `try_generation(identity)`; regenerate → `try_healing(identity)`;
     refusal → `IncurableStepError(step_text, reason="generation|healing attempt budget
     exhausted", recommendation="…")` → checkpoint: exhaustion = incurability, not an infinite
     loop ✓
   - `emit("on_generation_started", {"step_text": step_text, "attempt": n})` ✓
   - request assembly: snapshot=`page.aria_snapshot()`; screenshot when
     `config.send_screenshots`; `page_api` = the frozen facade-surface string (see Algorithm
     Design) ✓
   - request: the first attempt — `existing_code=None, error=None`; every subsequent one is a
     regeneration request: the failed candidate and its fresh error are passed
     → checkpoint: the interpretation matches the provider contract ("non-empty only on
     regeneration requests") — an attempt retried with a failed candidate is precisely a
     regeneration request ✓
   - `run_step_code(candidate, page)`: success → `CachedStep(identity, candidate,
     created_at=date.today().isoformat())` → `cache.save` → return; failure → a short error
     description → the next iteration ✓
   - `LlmUnavailableError` from the provider → an immediate raise-through, no retry
     → checkpoint: the provider is outside the retry loop ✓
3. **Output**: `CachedStep` (saved) or a raised taxonomy error ✓

### Trace: `StepHealer.heal`

1. **Input**: step, error, previous_steps, page (after D1) ✓
2. Assembly: `step_text = step.identity.normalized_text`, `code = step.code`, a fresh snapshot
   (+screenshot under the flag) ✓
3. `provider.classify_failure(classification_prompt, …)` → `FailureClassification` ✓
4. `emit("on_healing_started", {"step_text": …, "category": …})` ✓
5. Branching by category:
   - `product_defect` → `ProductDefectError(step_text, message=explanation)`; the cache
     untouched → checkpoint: anti-masking ✓
   - `incurable` → `IncurableStepError(step_text, reason=explanation, recommendation)` ✓
   - `rot` → `generator.regenerate(identity=step.identity, step_text, previous_steps, page,
     existing_code=step.code, error=error)` → success → `emit("on_healed", {"step_text": …,
     "explanation": …})` → return healed; budget exhaustion inside → IncurableStepError
     propagates ✓
6. **Output**: `CachedStep` (healed, overwritten in the cache only after successful execution)
   ✓

### Trace: `get_runtime` / `PrettyplayRuntime`

1. The module global `_runtime`; the first call: `load_config(None)` →
   `PrettyplayRuntime(config)`; afterwards — the same object ✓ (repeated calls are cheap)
2. Properties: `config` (eager), `budgets = RunBudgets(config.generation_attempts,
   config.healing_attempts)` (eager), `driver = DriverSession(config)` (lazily, on the first
   `open_page`), `provider = create_provider(config)` (lazily, on first access — but provider
   construction requires no keys, the client is created on the first request)
   → checkpoint: runtime construction without credentials ✓
3. `open_page()` → `self.driver.open_context()` ✓; `close()` → `driver.close()` (safe when
   never launched) ✓

### Trace: `PrettyTest` (constructor / action / assertion / add_hooks / close)

1. **Input**: cache_key (required), cache_path (optional) ✓
2. `runtime = get_runtime()`; `reporter = StepReporter(hooks=[])`; `cache = StepCache(
   runtime.config, cache_path, reporter)`; `generator = StepGenerator(runtime.config,
   runtime.provider, cache, runtime.budgets, reporter)`; `healer = StepHealer(runtime.config,
   runtime.provider, generator, cache, runtime.budgets, reporter)`; `executor = StepExecutor(
   cache_key, cache, generator, healer, runtime.budgets, reporter)`
   → checkpoint: all signatures line up ✓; accessing `runtime.provider` here is safe — the
   client is lazy ✓
3. The page is lazy: the first `action`/`assertion` → `runtime.open_page()` ✓
4. `action(text)` → `execute(text, "action", page)`; `assertion(text)` → `execute(text,
   "assertion", page)` ✓
5. `add_hooks(hooks)` → append to the reporter's list (before the first step — lifecycle.md) ✓
6. `close()` / `__exit__` → `page.close()` if open; the runtime stays alive ✓; test order has
   no effect (no per-test globals, contexts are isolated) ✓

### Trace: `StepExecutor.execute`

1. `emit("on_step_started", …)` ✓
2. `identity = StepIdentity(cache_key=self.cache_key, step_type=step_type,
   normalized_text=normalize_step_text(step_text))` ✓
3. `cached = cache.load(identity)`:
   - hit → `run_step_code(cached.code, page)` → success → step 6; failure → `healer.heal(cached,
     error=short(exc), previous_steps=self._scenario, page)` → healed → step 6
     → checkpoint: the cache path without LLM ✓ (load + run_step_code never touch the provider)
   - miss → `generator.generate(identity, step_text, previous_steps=self._scenario, page)`
     → checkpoint: previous_steps are passed both to generation and to healing (D1) ✓
4. Step 6: `self._scenario.append(step_text)` — the original sentence as written by the engineer
   (context readability for the next generation) ✓
5. `emit("on_step_passed", …)` ✓
6. A raise (any kind) → `emit("on_step_failed", {"step_text", "step_type", "error": short})`
   → the same kind propagates ✓

**A documented interpretation (not a defect).** The executor requirement "An assertion step
surfaces a legitimately failed expectation as the product defect failure" is fulfilled by the
mechanism of algorithm step 4 — classification on the cache path (the steady-state mode of
running from cache). The exact applicability boundary: **a step falls under classification (and
therefore under ProductDefectError) only after the first successful generation and saving into
the cache**. A step that has never been generated — in every run, not only the first — yields
`IncurableStepError` and never `ProductDefectError`: on the miss path it is impossible to
distinguish a "broken candidate" from a "legitimately failed expectation" without
classification, the generator contract explicitly requires `IncurableStepError` on budget
exhaustion, and only successes enter the cache (the next run gets a fresh budget and misses
again). MVP stance: tests are written against working functionality — a defective regression is
caught by classification in the steady-state mode; a congenitally broken expectation is
expressed as incurability (loudly, without masking). The contract texts do not contradict each
other under this reading: the "legitimacy" of an expectation is determined solely by
classification, which by contract exists exclusively for failed cached steps.

---

## Algorithm Design

### `Config` (config/models.py)

**Responsibility**: validated project settings — the single source of the immutable part.

**Algorithm:**
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

**Errors:** `pydantic.ValidationError` — at load time; the consumer sees the invalid setting's
name.

**Edge Cases:** empty strings are legal (fallbacks/defaults); `None` is not used (explicit
absence is expressed by an empty string, per conventions).

### `load_config` (config/loader.py)

**Responsibility**: loading `[tool.prettyplay]` from pyproject.toml with env overrides.

**Algorithm:**
```
1. path = Path(pyproject_path) if given, else the first existing
   pyproject.toml among [Path.cwd(), *Path.cwd().parents]
2. IF Python >= 3.11: import tomllib ELSE: import tomli as tomllib
3. data = tomllib.load(path.open("rb")); section = data.get("tool", {}).get("prettyplay", {})
4. FOR each of the 10 fields: env PRETTYPLAY_<FIELD_UPPER> set (including an empty value) → override
5. merged = {**section, **env_overrides}
6. cache_root empty in merged → merged["cache_root"] = str(path.parent / ".prettyplay" / "cache")
7. RETURN Config(**merged)
```

**Errors:** no pyproject.toml on auto-search → a loud "pyproject.toml not found" error;
ValidationError propagates with path context.

**Edge Cases:** no section → all defaults; env strings are coerced by pydantic ("3"→int,
"false"→bool); an empty env variable of a str field is legal, an empty env variable of an
int/bool field — a loud ValidationError naming the setting;
the obligation "never read LLM API keys from any file" — the function reads nothing besides
the specified TOML.

### `StepHooks` (reporting/hooks.py)

**Responsibility**: a thin callback contract; a base with no-op implementations of all 8 events.

**Algorithm:** a class with the methods `on_step_started(step_text, step_type)`,
`on_step_passed(step_text, step_type)`, `on_step_failed(step_text, step_type, error)`,
`on_generation_started(step_text, attempt)`, `on_healing_started(step_text, category)`,
`on_healed(step_text, explanation)`, `on_cache_saved(step_text, filename)`,
`on_cache_skipped(step_text, reason)` — bodies are `pass`.

**Errors:** none (base).

**Edge Cases:** none.

### `StepReporter` (reporting/reporter.py)

**Responsibility**: the single visibility point — the `prettyplay` logger + synchronous fan-out
to hooks.

**Algorithm:**
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
      processName, stack_info, asctime, taskName; sanitization concerns only the log record —
      otherwise Logger.makeRecord raises KeyError "Attempt to overwrite … in LogRecord";
      the `filename` key of the on_cache_saved event is logged as ctx_filename)
   c. FOR hook in self.hooks (registration order):
        try: getattr(hook, event)(**payload)
        except Exception: logger.warning("hook call failed", extra={"event": event,
              "hook": type(hook).__name__})
```

**Errors:** a hook exception — WARNING + skip; a test does not fail because of a hook.

**Edge Cases:** an empty hook list — logging only; `emit` is synchronous, without queues.

### `PrettyplayError` + mutations (failures/errors.py)

**Responsibility**: a taxonomy of three distinguishable kinds with a common base.

**Algorithm:**
```
1. PrettyplayError(Exception): __init__(message) → self.message = message
2. ProductDefectError(PrettyplayError): __init__(step_text, message) → both attributes;
   str = f"product defect on step {step_text!r}: {message}"
3. IncurableStepError(PrettyplayError): __init__(step_text, reason, recommendation) →
   three attributes; str includes all three fields
4. LlmUnavailableError(PrettyplayError): __init__(message) → the message attribute
```

**Errors:** they are themselves the terminal kinds; never retried by the library.

**Edge Cases:** every field in the message — an IncurableStepError render requirement.

### `DriverSession` (driver/session.py)

**Responsibility**: the owner of the Playwright sync driver and browser lifecycle per run.

**Algorithm:**
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
   null both fields (idempotent, safe when never launched)
```

**Errors:** Playwright errors propagate as is (launch infrastructure is outside the LLM
taxonomy; browser unavailability is visible directly).

**Edge Cases:** headless by default (`launch()`); a repeated `close()` is a no-op.

### `PageFacade` / `LocatorFacade` (driver/page.py)

**Responsibility**: a narrow stable page and element facade — the only page API of the
generated code; a backward-compatibility contract (extend, never rename).

**Algorithm:**
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

**Errors:** a failed expectation → `AssertionError` from `expect(...)` (goes to classification);
action timeouts → `playwright.Error` (also a failure description for classification).

**Edge Cases:** no `time.sleep` whatsoever; the facade never returns raw Playwright objects
(returns are str / bytes / LocatorFacade).

### `normalize_step_text` (cache/text.py)

**Responsibility**: normalization of the step sentence for addressing.

**Algorithm:**
```
1. s = unicodedata.normalize("NFC", text)
2. s = s.strip()
3. s = re.sub(r"\s+", " ", s)
4. RETURN s.casefold()
```

**Errors:** none (a pure function).

**Edge Cases:** an empty string stays empty; multibyte languages — NFC+casefold stable;
different languages remain different steps.

### `StepIdentity` / `CachedStep` (cache/models.py)

**Responsibility**: the step address (+deterministic file name) and the in-memory cache unit.

**Algorithm:**
```
StepIdentity (BaseModel, kw_only): cache_key: str, step_type: str, normalized_text: str
  filename (cached_property):
    identity_string = "\x1f".join((cache_key, step_type, normalized_text))
    RETURN hashlib.sha256(identity_string.encode("utf-8")).hexdigest() + ".py"

CachedStep (BaseModel, kw_only): identity: StepIdentity, code: str, created_at: str
```

**Errors:** none.

**Edge Cases:** the `\x1f` separator (Unit Separator) makes the concatenation unambiguous —
components cannot "collapse" into the same string under different splittings.

### `StepCache` (cache/store.py)

**Responsibility**: the step repository: addressing, atomic writes, read-only mode.

**Algorithm:**
```
1. __init__(config, path, reporter):
   self._root = Path(config.cache_root)  # already absolute after load_config
   self._subdir = Path(path) if path else None   # part of the address
   self._reporter = reporter; self._writable = None (lazy)
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
   TRY (a protective parse block — any structural error = a miss, not a run crash):
     text = target.read_text(encoding="utf-8")
     parse header: STEP_TEXT / CACHE_KEY / STEP_TYPE / CREATED_AT = <literal> (ast.literal_eval)
     code = text from the first "\ndef step(" (inclusive)
     IF (CACHE_KEY, STEP_TYPE) != (identity.cache_key, identity.step_type)
        or STEP_TEXT != identity.normalized_text: RETURN None   # protective miss
     RETURN CachedStep(identity=identity, code=code, created_at=CREATED_AT)
   EXCEPT (ValueError, SyntaxError, KeyError, IndexError, OSError): RETURN None
   # an invalid header/literal, a missing metadata field or def step( tail, an unreadable
   # file — cache corruption never cripples the run
   # (contract: "The cache is always read, in every environment")
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

**Errors:** no write error crashes the run (best-effort); reading always works.

**Edge Cases:** concurrent writers of the same step — last write wins, the file is never
crippled (atomic replace); a manual file edit with mismatched metadata → a protective miss
(regeneration); a damaged/truncated/unreadable file (any structural parse error) → a protective
miss — the cache is always read, a single file's failure does not crash the run.

### `RunBudgets` (cache/budgets.py)

**Responsibility**: the per-run registry of generation/healing attempts per step.

**Algorithm:**
```
1. __init__(generation_limit, healing_limit): two dict[str, int] (key = identity.filename)
2. try_generation(identity):
   used = self._gen.get(key, 0)
   IF used >= self._generation_limit: RETURN False
   self._gen[key] = used + 1; RETURN True
3. try_healing — symmetric with self._heal / self._healing_limit
```

**Errors:** none.

**Edge Cases:** budgets are not reset between tests (one process — one registry); xdist workers
= separate processes = separate registries (documented behavior); nothing is persisted.

### `LlmProvider` / `OpenAiProvider` / `AnthropicProvider` (llm/*)

**Responsibility**: the single LLM port: step code generation and failure classification; two
interchangeable SDK implementations in full parity.

**Algorithm (the common skeleton of both providers):**
```
1. __init__(config): self._config; self._client = None
2. _get_client() (lazy):
   key = os.environ.get("OPENAI_API_KEY" | "ANTHROPIC_API_KEY")
   IF not key: raise LlmUnavailableError("llm unavailable: <provider>: <ENV_VAR> is not set")
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
5. Request wrapper: except <SDK base error> as e:
   raise LlmUnavailableError(f"llm unavailable: <provider> request failed") from e
```

`build_user_content` — a field format unified across both providers (STEP, PREVIOUS STEPS,
PAGE SNAPSHOT, PAGE API, CODE, ERROR — the last two only on regeneration requests); the
multimodal difference is only in each SDK's content-block wrapper (see Code Stack Trace).

**Errors:** `LlmUnavailableError` — the provider's only failure kind (connectivity, timeout,
rate limit, auth, a missing key); names the provider.

**Edge Cases:** an empty model answer → treated as unparsable (classification) / as a useless
candidate (generation — the code compiles/executes and fails → a budget retry).

### `create_provider` (llm/provider.py)

**Algorithm:**
```
IF config.provider == "openai":    RETURN OpenAiProvider(config)
ELIF config.provider == "anthropic": RETURN AnthropicProvider(config)
ELSE: raise ValueError("unsupported provider {config.provider!r}: expected one of openai, anthropic")
```

### `run_step_code` (engine/execution.py)

**Responsibility**: execution of fixed-form step code against the page facade.

**Algorithm:**
```
1. namespace: dict[str, object] = {}
2. exec(compile(code, "<prettyplay-step>", "exec"), namespace)
3. fn = namespace["step"]        # the fixed name from generation_prompt
4. fn(page)                      # exceptions — outward as is
```

**Errors:** any step-body exception propagates without swallowing or retries.

**Edge Cases:** only generation/cache code is executed (the engine is the sole caller); the
module is not registered in `sys.modules`; no networks besides the page itself.

### `StepGenerator` (engine/generator.py)

**Responsibility**: generation of working step code by executing candidates against the live
page.

**Algorithm:**
```
PAGE_API_SURFACE — a frozen string constant: the listing of PageFacade and LocatorFacade calls
verbatim from the facade surface (the driver is a backward-compatibility contract, the constant
is stable; surface changes = a deliberate extension with constant synchronization).

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
  the same loop; differences: budgets.try_healing; the starting existing_code/error from the
  arguments
```

**Errors:** `LlmUnavailableError` — a pass-through immediate raise (not caught in the loop);
exhaustion — `IncurableStepError`; a candidate failure — a retry with the code and the error.

**Edge Cases:** at most `generation_attempts` (regeneration — `healing_attempts`) requests per
step per run; every retry = a regeneration request (carries the existing code and the error).

### `StepHealer` (engine/healer.py)

**Responsibility**: classification of a cached step failure, rot regeneration, defect
anti-masking.

**Algorithm:**
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

**Errors:** as in the branching; regeneration budget exhaustion surfaces from the generator as
`IncurableStepError`.

**Edge Cases:** healed code replaces the cached one only after successful execution (a
generator guarantee); provider unavailable → `LlmUnavailableError` from the classification
stage.

### `PrettyTest` (scenario.py)

**Responsibility**: the integrator's main object — one per test; owns the cache addressing and
the test's isolated browser context; the step loop is delegated to the executor.

**Algorithm:**
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
cache_key (property) → the self._executor key (for diagnostics)
_page(): IF self._page is None: self._page = self._runtime.open_page(); RETURN self._page
action(text)    → self._executor.execute(text, "action",    self._page())
assertion(text) → self._executor.execute(text, "assertion", self._page())
add_hooks(hooks)→ self._reporter.hooks.append(hooks)
close()         → IF self._page: self._page.close(); self._page = None
__enter__ → self;  __exit__ → close(); return None (does not swallow exceptions)
```

**Errors:** step failures propagate by kind (taxonomy).

**Edge Cases:** construction is cheap (browser and page are lazy); there is no cross-test
state.

### `StepExecutor` (executor.py)

**Responsibility**: the owner of the step loop: hit → execute; miss → generate; cache failure →
heal.

**Algorithm:**
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
  an except wrapper over the whole body: reporter.emit("on_step_failed", {"step_text": step_text,
    "step_type": step_type, "error": short(exc)}); raise
short(exc) → the first line of str(exc), truncated to 200 characters
```

**Errors:** taxonomy kinds propagate preceded by `on_step_failed`.

**Edge Cases:** the scenario context is per-test (lives in the executor); the cache path
without LLM.

### `PrettyplayRuntime` / `get_runtime` (runtime.py)

**Responsibility**: the run-scale composition root — everything shared by the tests, nothing
per-test.

**Algorithm:**
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

**Errors:** none of its own; everything is lazy.

**Edge Cases:** missing LLM keys do not prevent startup and cached runs (the client is created
on the first request); the root `__init__.py` re-exports the public facade:
`from .scenario import PrettyTest; from .executor import StepExecutor; from .runtime import
PrettyplayRuntime, get_runtime` (+ `__all__`), enabling `python -c "from prettyplay import
PrettyTest"`.

---

## Cross-cutting Concerns

- **Error handling**: three failure kinds (`ProductDefectError`, `IncurableStepError`,
  `LlmUnavailableError`) with the common base `PrettyplayError`; hook and cache-write failures
  never crash the run (WARNING + continuation); step-code exceptions propagate as is;
  `LlmUnavailableError` — no retries. Every message is actionable: step, reason, recommendation.
- **Logging**: a single logger `logging.getLogger("prettyplay")`; events are stable names (=
  hook names), lowercase, context via `extra`; levels: lifecycle — INFO, `on_cache_skipped` and
  hook failure — WARNING; secrets are never logged (including the provider payload and keys).
- **Validation**: configuration — at load (Literal/PositiveInt, loud, with the field name);
  cache files — at read (metadata match against identity, a protective miss); the
  classification verdict — at parse (unknown → the safe incurable); step code — by compilation
  and execution in the generation loop.
- **Caching**: the step repository — one `.py` file per step, address = sha256(triple), atomic
  writes (tmp + `os.replace`), best-effort writing, always-available reading; attempt budgets —
  in-memory per process; provider/driver/pages — lazy singletons of their scope.
- **Concurrency**: the library is single-threaded (sync Playwright); no locks; concurrent
  writers of one step file are safe via atomic replace (last write wins); `RunBudgets` and
  `_runtime` without locks — within a process this is correct; pytest-xdist is isolated by
  processes (separate runtimes and budgets — documented behavior).

---

## Usages Analysis

### `conventions`
- **What it provides**: mandatory python-code and test rules (3.10+, relative imports inside
  the package, pydantic kw_only+empty defaults, logging with context, Google docstrings, ruff,
  the tests/ structure, mocks only at external boundaries).
- **Where used**: all 8 cells (global annotations).
- **Why chosen**: the project standard; the facade check `from prettyplay import PrettyTest`.
- **How exactly**: `logging.getLogger` with `extra`; `tmp_path` for file tests; tests mirror
  the structure: `prettyplay/cache/store.py` → `tests/cache/test_store.py`.

### `pydantic`
- **What it provides**: v2 model patterns (`ConfigDict(kw_only=True)`, empty defaults) and
  TOML loading with the tomli fallback for 3.10.
- **Where used**: config (`Config`, `load_config`); the model cells (StepIdentity, CachedStep,
  FailureClassification).
- **Why chosen**: the conventions requirements for data models + the standard TOML path.
- **How exactly**: `model_config = ConfigDict(kw_only=True)`; `tomllib`/`tomli` by
  `sys.version_info`; the section `data.get("tool", {}).get("prettyplay", {})`.

### `playwright`
- **What it provides**: the sync-API lifecycle, the browser matrix, locators with auto-wait,
  the a11y snapshot, screenshots.
- **Where used**: driver (the whole cell); engine — semantics via `facade`.
- **Why chosen**: the single MVP driver (sync-only).
- **How exactly**: `sync_playwright().start()` for a long-lived session; the engine dict
  `{chromium, firefox, webkit}`; `page.locator("body").aria_snapshot()`; `expect(...)` for
  waits; no `time.sleep` in steps.

### `openai` / `anthropic`
- **What it provides**: SDK call patterns, keys from env, the SDK error →
  `LlmUnavailableError` mapping, operation parity.
- **Where used**: llm (`OpenAiProvider`, `AnthropicProvider`).
- **Why chosen**: the two MVP-supported providers.
- **How exactly**: `OpenAI(api_key=os.environ[...])` / `anthropic.Anthropic(...)`;
  `chat.completions.create` / `messages.create(system=..., max_tokens=1024)`; one request per
  attempt; `OpenAIError`/`AnthropicError` → `LlmUnavailableError ... from error`.

### `generation_prompt` (inline, engine)
- **What it provides**: the generation system prompt — fixes the answer form (a single block,
  `def step(page) -> None`), the inputs (STEP/PREVIOUS STEPS/PAGE SNAPSHOT/SCREENSHOT/PAGE
  API/CODE/ERROR) and the rules (facade surface only, no imports, no delays).
- **Where used**: `StepGenerator.generate/regenerate` → `provider.generate_step_code(prompt=…)`.
- **Why chosen**: inline — specific to the engine cell, meaningless outside it.
- **How exactly**: passed verbatim as the system message of every generation request.

### `classification_prompt` (inline, engine)
- **What it provides**: the classification system prompt — a single-line answer
  `category | explanation | recommendation`, the categories rot/product_defect/incurable.
- **Where used**: `StepHealer.heal` → `provider.classify_failure(prompt=…)`.
- **Why chosen**: inline, cell-specific.
- **How exactly**: verbatim as the system message; parsing the first non-empty line on `|`.

### Imported Usages
- `hooks` from `prettyplay/reporting` — the event contract for cache (cache-write events) and
  the root (add_hooks); path `prettyplay/reporting/.usages/hooks.md`.
- `taxonomy` from `prettyplay/failures` — the failure kinds raised by the root's step methods;
  path `prettyplay/failures/.usages/taxonomy.md`.
- `generation`, `healing` from `prettyplay/engine` — the engine loops that `StepExecutor`
  delegates to; paths `prettyplay/engine/.usages/{generation,healing}.md`.
- `facade` from `prettyplay/driver` — the single source of the PAGE API surface for generation
  requests; path `prettyplay/driver/.usages/facade.md`.
- `classification` from `prettyplay/llm` — the healing-decision categories; path
  `prettyplay/llm/.usages/classification.md`.

---

## `.usages/` Update

### Cell: `prettyplay/engine`

#### Existing Files — Consistency
- **`healing.md`** → `prettyplay/engine/.usages/healing.md`
  - Status: updated at this stage (user-approved)
  - Updates applied: the `heal(...)` example now passes `previous_steps=[…]` (a consequence of
    D1); the budget rule is reworded — "Generation and healing attempts live in one run-scoped
    registry with separate per-step limits (default 3 and 2)" instead of the ambiguous "share
    the per-step run budget".
- **`generation.md`** → up to date (the `generate` signature, the loop, budgets, the fixed
  form).

### Cell: `prettyplay/reporting`

#### Existing Files — Consistency
- **`hooks.md`** → `prettyplay/reporting/.usages/hooks.md`
  - Status: updated at this stage (user-approved)
  - Updates applied: "Payload values are plain strings; the attempt counter of
    on_generation_started is an int" (a consequence of D2).

### The remaining cells

- `prettyplay/.usages/steps.md`, `lifecycle.md` — up to date (the `PrettyTest` API,
  composition, failure kinds match the contracts).
- `prettyplay/config/.usages/configuration.md` — up to date (the schema, 10 env overrides,
  defaults).
- `prettyplay/failures/.usages/taxonomy.md` — up to date (after D3 the
  `info.value.recommendation` access is now in the contract).
- `prettyplay/driver/.usages/facade.md` — up to date (the surface = PageFacade/LocatorFacade).
- `prettyplay/cache/.usages/addressing.md`, `storage.md`, `budgets.md` — up to date.
- `prettyplay/llm/.usages/providers.md`, `classification.md` — up to date.

#### New Files (if any)
Not required: the existing domain split covers all entities; the edits stay within domains.

---

## Test Stack Trace

### General Setup

- The structure is mirrored: `tests/<cell>/test_<module>.py`; every directory with an
  `__init__.py`; local fixtures in `tests/<cell>/conftest.py`. Root-module tests live directly
  in `tests/`.
- Mocks only at external boundaries: the SDK (`openai`/`anthropic` clients), Playwright (the
  driver); time is absent (cache events are deterministic). File tests use only `tmp_path`.
- The provider in engine/root tests is replaced by a stub object with the `LlmProvider`
  signatures (`generate_step_code`, `classify_failure`), the page by a fake object with the
  facade methods.

### Source File Registry

| Cell | Files under test |
|---|---|
| config | models.py, loader.py |
| reporting | hooks.py, reporter.py |
| failures | errors.py |
| driver | session.py, page.py |
| cache | text.py, models.py, store.py, budgets.py |
| llm | provider.py, openai_provider.py, anthropic_provider.py, models.py |
| engine | execution.py, generator.py, healer.py |
| prettyplay | scenario.py, executor.py, runtime.py |

---

### Positive Tests

#### `test_config_defaults_valid`

**Setup**: nothing (a pure model).

**Input**: `Config()`.

**Trace**:
```
Config()
  → pydantic validates the defaults   # provider/browser Literal, attempts PositiveInt
  → fields set
  → effective_generation_model        # generation_model="" → fallback
    returns: Config.model
```

**Assertions**:
```
config.provider == "openai"
config.browser == "chromium"
config.generation_attempts == 3 and config.healing_attempts == 2
config.send_screenshots is False
config.effective_generation_model == config.model == ""
```

**Sufficiency**: fixes the defaults and model-fallback contract — a regression guard against
changing the MVP defaults.

---

#### `test_load_config_reads_section_and_env_overrides`

**Setup**: `tmp_path/pyproject.toml`:
```toml
[tool.prettyplay]
provider = "openai"
browser = "chromium"
model = "gpt-5"
```
`monkeypatch.setenv("PRETTYPLAY_BROWSER", "firefox")`; `monkeypatch.setenv("PRETTYPLAY_GENERATION_ATTEMPTS", "5")`.

**Input**: `load_config(pyproject_path=str(tmp_path / "pyproject.toml"))`.

**Trace**:
```
load_config(path)
  → tomllib.load                      # section read
  → env override browser="firefox", generation_attempts="5"
  → Config(**merged)                  # coercion "5"→5
  → cache_root empty → tmp_path/.prettyplay/cache/
```

**Assertions**:
```
config.model == "gpt-5"
config.browser == "firefox"            # env overrides TOML
config.generation_attempts == 5        # str→int coercion
config.cache_root == str(tmp_path / ".prettyplay" / "cache")
```

**Sufficiency**: the loader core — TOML + env + default cache-root resolution.

---

#### `test_emit_dispatches_event_to_hooks_in_order`

**Setup**: two recorder hooks `RecordingHook(StepHooks)` with a shared `calls` list; reporter =
`StepReporter(hooks=[h1, h2])`.

**Input**: `reporter.emit("on_step_started", {"step_text": "открыть страницу", "step_type": "action"})`.

**Trace**:
```
emit(...)
  → logger.info("on_step_started", extra={...})
  → h1.on_step_started(step_text=..., step_type=...)   # kwargs
  → h2.on_step_started(...)
```

**Assertions**:
```
calls == [("h1", "on_step_started", "открыть страницу", "action"),
          ("h2", "on_step_started", "открыть страницу", "action")]
caplog: one INFO record, logger == "prettyplay", msg == "on_step_started",
        record.step_text == "открыть страницу"
```

**Sufficiency**: the emit mechanics — fan-out order, event names = method names, context in
the log.

---

#### `test_open_context_lazy_launch_single_browser`

**Setup**: `mock.patch("prettyplay.driver.session.sync_playwright")` → fake pw: `pw().start()`
returns an object with `chromium/firefox/webkit`, each `.launch()` appends to `launches`;
`new_context()` → a context with `new_page()`.

**Input**: `session = DriverSession(Config(browser="chromium"))`; `session.open_context()` ×2.

**Trace**:
```
DriverSession(config)           # nothing launched
  → open_context() #1           # lazy: start + chromium.launch() (once) + new_context + new_page
  → open_context() #2           # browser already exists: only new_context + new_page
```

**Assertions**:
```
after the constructor: pw.start was not called
launches == 1
the two results are distinct PageFacade objects; 2 contexts created
```

**Sufficiency**: "one browser per run, an isolated context per test" and lazy launch.

---

#### `test_normalize_step_text_equivalence`

**Setup**: none.

**Input**: `normalize_step_text("  Нажать   Войти ")`, `normalize_step_text("нажать войти")`.

**Trace**:
```
"  Нажать   Войти " → NFC → strip → collapse → casefold → "нажать войти"
"нажать войти"      → the same pipeline → "нажать войти"
```

**Assertions**:
```
normalize_step_text("  Нажать   Войти ") == normalize_step_text("нажать войти") == "нажать войти"
normalize_step_text("Нажать Войти") != normalize_step_text("Click Login")
```

**Sufficiency**: step identity from the addressing ADR semantics — "equal sentences = one
step".

---

#### `test_identity_filename_deterministic_and_discriminating`

**Setup**: none.

**Input**: two identical and two differing triples.

**Trace**:
```
StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти").filename
StepIdentity(cache_key="k", step_type="action", normalized_text="нажать войти").filename   # the same digest
StepIdentity(cache_key="k", step_type="assertion", normalized_text="нажать войти").filename # a different digest
StepIdentity(cache_key="k2", step_type="action", normalized_text="нажать войти").filename   # a different digest
```

**Assertions**:
```
f1 == f2; f1 != f3; f1 != f4
f1.endswith(".py") and len(digest part) == 64
```

**Sufficiency**: addressing — the same triple → one file, any difference → another.

---

#### `test_save_load_roundtrip_via_file`

**Setup**: `tmp_path`; `Config(cache_root=str(tmp_path))`; a reporter with a recorder;
`cache = StepCache(config, "checkout", reporter)`; `identity = StepIdentity(cache_key="login-flow",
step_type="action", normalized_text="открыть страницу логина")`.

**Input**: `cache.save(CachedStep(identity=identity, code="def step(page) -> None:\n    page.open('https://x')\n", created_at="2026-09-07"))`; then `cache.load(identity)`.

**Trace**:
```
save(step)
  → tmp in tmp_path/checkout/.tmp-*.py → os.replace → checkout/<digest>.py
  → emit on_cache_saved(filename=<digest>.py)
load(identity)
  → read the file → the STEP_TEXT/CACHE_KEY/STEP_TYPE/CREATED_AT header → the def step(...) tail
  → identity match ✓
```

**Assertions**:
```
loaded is not None
loaded.identity == identity
loaded.code.startswith("def step(")
loaded.created_at == "2026-09-07"
file: text.startswith("STEP_TEXT =") and "def step(" in text
recorded: ("on_cache_saved", {"filename": identity.filename})
caplog: an INFO record "on_cache_saved" from the "prettyplay" logger; record.ctx_filename == identity.filename
importing the file via importlib.util.spec_from_file_location("cached_step", path)
  + module_from_spec + exec_module succeeds (a valid module; the digest file name
  need not be an identifier — load works from text, not by module name)
```

**Sufficiency**: the full storage cycle — the file format, call atomicity, step restoration.

---

#### `test_budgets_separate_pools_shared_per_identity`

**Setup**: `budgets = RunBudgets(generation_limit=1, healing_limit=1)`; `identity` and `identity2`.

**Input**: `try_generation(identity)` ×2; `try_healing(identity)`; `try_generation(identity2)`.

**Trace**:
```
try_generation(id)  → True (0→1)
try_generation(id)  → False (limit 1)
try_healing(id)     → True (a separate pool)
try_generation(id2) → True (another step — its own budget)
```

**Assertions**:
```
results: [True, False, True, True]
```

**Sufficiency**: separate limits; a per-step (not per-test) budget — shared by all tests of
the run.

---

#### `test_create_provider_selects_by_config`

**Setup**: `Config(provider="anthropic", model="claude-sonnet-4-5")` (no env keys — not
needed).

**Input**: `create_provider(config)`.

**Trace**:
```
create_provider → "anthropic" → AnthropicProvider(config)
```

**Assertions**:
```
isinstance(provider, AnthropicProvider)
isinstance(provider, LlmProvider)   # the port contract
```

**Sufficiency**: provider selection is a configuration decision; construction without keys.

---

#### `test_openai_provider_error_maps_to_llm_unavailable`

**Setup**: `mock.patch` of the SDK client: `chat.completions.create` raises
`OpenAIError("timeout")`; env `OPENAI_API_KEY=test`.

**Input**: `OpenAiProvider(Config(model="gpt-5")).generate_step_code(prompt="p", step_text="s",
previous_steps=[], snapshot="- snap", screenshot=None, page_api="page.open(...)", existing_code=None, error=None)`.

**Trace**:
```
generate_step_code → lazy client → create(...) → OpenAIError
  → raise LlmUnavailableError("llm unavailable: openai request failed") from error
```

**Assertions**:
```
pytest.raises(LlmUnavailableError); "openai" in str(excinfo.value)
isinstance(excinfo.value, PrettyplayError)
```

**Sufficiency**: the mapping of an SDK infrastructure failure into the taxonomy — no retries
at the provider level.

---

#### `test_missing_api_key_surfaces_on_first_request`

**Setup**: `monkeypatch.delenv("OPENAI_API_KEY", raising=False)`.

**Input**: `provider = OpenAiProvider(Config())` (does not fail); then a
`classify_failure(...)` call.

**Trace**:
```
OpenAiProvider(Config())   # the constructor does not read env
classify_failure(...)      # first request → _get_client → no key
  → LlmUnavailableError("llm unavailable: openai: OPENAI_API_KEY is not set")
```

**Assertions**:
```
construction succeeds (no exception)
pytest.raises(LlmUnavailableError) on the first request; "OPENAI_API_KEY" in str(...)
```

**Sufficiency**: the runtime requirement — start without credentials, fail only on
generation/classification.

---

#### `test_run_step_code_executes_fixed_form`

**Setup**: a fake page recording calls.

**Input**: `run_step_code("def step(page) -> None:\n    page.open('https://example.com')\n", page)`.

**Trace**:
```
compile(code) → namespace {} → namespace["step"] → step(page)
  → page.open("https://example.com")
```

**Assertions**:
```
page.calls == [("open", "https://example.com")]
```

**Sufficiency**: the fixed-form execution mechanism — compile, isolate, call.

---

#### `test_generate_success_stores_and_reports_attempt`

**Setup**: a stub provider: `generate_step_code` returns working code for the fake page; the
cache on `tmp_path`; an event recorder; `budgets = RunBudgets(3, 2)`;
generator = StepGenerator(...).

**Input**: `generator.generate(identity, "открыть страницу", [], page)`.

**Trace**:
```
generate → try_generation ✓ → on_generation_started(attempt=1) → aria_snapshot
  → provider.generate_step_code(existing_code=None, error=None)
  → run_step_code ✓ → CachedStep → cache.save → on_cache_saved
```

**Assertions**:
```
step.code == the stub's code; step.identity == identity
provider.calls == 1; the first attempt without existing_code/error
recorded on_generation_started: attempt == 1 (int)
recorded on_cache_saved with filename == identity.filename
```

**Sufficiency**: the generation happy path — storage, the event with an int attempt, a clean
first request.

---

#### `test_generate_retries_with_existing_code_then_succeeds`

**Setup**: a stub provider: the first answer is code that fails on the fake page
(`page.find_by_role(...)` raises AssertionError), the second works; a recorder.

**Input**: `generator.generate(identity, "нажать Войти", [], page)`.

**Trace**:
```
attempt 1: code A → run_step_code → AssertionError → error=short
attempt 2: a request with existing_code=A, error="..." → code B → run_step_code ✓
  → cache.save → return
```

**Assertions**:
```
provider.calls == 2
the second call: existing_code == A and error contains the failure text
recorded on_generation_started ×2 (attempt 1, attempt 2)
```

**Sufficiency**: the retry loop — the fresh error and the failed candidate go back to the
provider (the documented regeneration-request interpretation).

---

#### `test_heal_rot_regenerates_and_reports_healed`

**Setup**: the classification provider → `FailureClassification("rot", "кнопка переименована",
"проверить шаг")`; regeneration via a stub generator object (recorder: regenerate(...) →
returns the healed CachedStep); healer = StepHealer(config, provider, generator, cache,
budgets, reporter).

**Input**: `healer.heal(step=failed_step, error="element not found", previous_steps=["открыть"], page=page)`.

**Trace**:
```
heal → classify_failure(classification_prompt, code=failed_step.code, error=...)
  → verdict rot → on_healing_started(category="rot")
  → generator.regenerate(identity, step_text, previous_steps, page,
        existing_code=failed_step.code, error="element not found")
  → on_healed(explanation="кнопка переименована") → return healed
```

**Assertions**:
```
the healed step is returned
regenerate called exactly once with existing_code=failed_step.code and previous_steps=["открыть"]
recorded: on_healing_started(category="rot"), on_healed(explanation="кнопка переименована")
cache.save not called by the healer directly (the generator writes it after successful
execution)
```

**Sufficiency**: the rot branch — classification, regeneration delegation with full context,
the loud healing event.

---

#### `test_get_runtime_is_process_singleton`

**Setup**: global isolation (resetting the private global before/after); `mock.patch`
load_config → a fixed Config.

**Input**: `get_runtime()` ×2.

**Trace**:
```
get_runtime() #1 → load_config(None) → PrettyplayRuntime → remembered
get_runtime() #2 → the same object
```

**Assertions**:
```
runtime1 is runtime2
load_config called exactly once
```

**Sufficiency**: one runtime per process — configuration and budgets are not recreated.

---

#### `test_action_cached_step_runs_without_llm`

**Setup**: a `tmp_path` cache with a pre-written step file (a valid module for "открыть
страницу логина"); the runtime global reset; env without keys; a stub provider raising
`AssertionError("provider must not be called")` on any call (a violation detector); the page
replaced by a fake (mock runtime.open_page).

**Input**: `t = PrettyTest("login-flow"); t.action("открыть страницу логина"); t.close()`.

**Trace**:
```
PrettyTest → get_runtime → executor
action → identity → cache.load → hit → run_step_code(code, fake page) ✓
  → on_step_started / on_step_passed; the provider's methods were not called, no SDK
  client was created
```

**Assertions**:
```
the step finished without exceptions
recorded: on_step_started, on_step_passed (step_type="action")
the stub provider was not called (the cache path without LLM)
```

**Sufficiency**: the product's central promise — a cached run requires no LLM at all.

---

#### `test_scenario_context_feeds_next_generation`

**Setup**: the cache is empty; a stub provider returns working code; a recorder of previous
steps in requests; a fake page.

**Input**: `t = PrettyTest("k"); t.action("шаг один"); t.action("шаг два"); t.close()`.

**Trace**:
```
шаг один: miss → generate(previous_steps=[]) ✓
шаг два:  miss → generate(previous_steps=["шаг один"]) ✓
```

**Assertions**:
```
the provider's second request received previous_steps == ["шаг один"]
the first — []
```

**Sufficiency**: the test's scenario context feeds the next generation (and, after D1,
healing).

---

### Negative Tests

#### `test_config_invalid_provider_fails_loudly`

**Setup**: none.

**Input**: `Config(provider="yandex")` (inside `pytest.raises(ValidationError)`).

**Trace**:
```
Config(provider="yandex") → Literal validation → ValidationError
```

**Assertions**:
```
"provider" in the error text; the allowed values are listed
```

**Sufficiency**: invalid configuration fails loudly and actionably at load.

---

#### `test_raising_hook_is_skipped_and_logged`

**Setup**: h1 — a hook raising RuntimeError on on_step_passed; h2 — a recorder;
reporter = `StepReporter(hooks=[h1, h2])`; `caplog`.

**Input**: `reporter.emit("on_step_passed", {"step_text": "s", "step_type": "action"})`.

**Trace**:
```
emit → h1.on_step_passed → RuntimeError → logger.warning("hook call failed") → h2 called
```

**Assertions**:
```
the exception did not escape
h2 received the event
caplog has a WARNING from the "prettyplay" logger
```

**Sufficiency**: a hook failure never crashes the run — but is visible in the logs.

---

#### `test_generate_budget_exhaustion_raises_incurable`

**Setup**: the provider always returns code that fails on the fake page; `RunBudgets(3, 2)`;
a tmp cache.

**Input**: `generator.generate(identity, "невозможный шаг", [], page)`.

**Trace**:
```
attempts 1..3: try_generation ✓ → the candidate fails → retry
iteration 4: try_generation → False → IncurableStepError
```

**Assertions**:
```
pytest.raises(IncurableStepError)
excinfo.value.reason mentions the budget; excinfo.value.recommendation is non-empty
provider.calls == 3
cache.save not called (failures are not cached)
```

**Sufficiency**: budget exhaustion = incurability, not an infinite loop; the provider is not
called beyond the limit.

---

#### `test_generate_provider_unavailable_propagates_immediately`

**Setup**: a stub provider raises `LlmUnavailableError` on every call; a call counter.

**Input**: `generator.generate(identity, "шаг", [], page)`.

**Trace**:
```
attempt 1: try_generation ✓ → on_generation_started → provider → LlmUnavailableError → raise-through
```

**Assertions**:
```
pytest.raises(LlmUnavailableError)
provider.calls == 1        # no retries on an infrastructure failure
budgets: 1 generation attempt spent
```

**Sufficiency**: "no retry on it" — only generation/healing is blocked, the cache keeps
living.

---

#### `test_heal_provider_unavailable_propagates`

**Setup**: a stub provider, `classify_failure` raises `LlmUnavailableError`; a generator spy
(a call recorder); a cache spy (save must not be called).

**Input**: `healer.heal(failed_step, "err", [], page)`.

**Trace**:
```
heal → input assembly → provider.classify_failure → LlmUnavailableError → an immediate
  raise-through (no regeneration, no retries, the cache untouched)
```

**Assertions**:
```
pytest.raises(LlmUnavailableError)
generator.regenerate not called; cache.save not called
```

**Sufficiency**: "Blocks only code generation and healing; cached steps keep running" — an
infrastructure failure at the classification stage is neither masked nor retried; the cache is
not overwritten.

---

#### `test_heal_product_defect_raises_and_keeps_cache`

**Setup**: the classification provider → `("product_defect", "ожидание не оправдалось",
"чинить продукт")`; a cache spy (save must not be called); a generator spy.

**Input**: `healer.heal(failed_step, "text mismatch", ["шаг"], page)`.

**Trace**:
```
classify → product_defect → on_healing_started(category="product_defect")
  → ProductDefectError(step_text, "ожидание не оправдалось")
```

**Assertions**:
```
pytest.raises(ProductDefectError); issubclass(ProductDefectError, PrettyplayError)
generator.regenerate not called; cache.save not called
```

**Sufficiency**: anti-masking — a legitimate product defect fails loudly, nothing is
regenerated or overwritten.

---

#### `test_heal_incurable_carries_verdict_fields`

**Setup**: the classification provider → `("incurable", "текст шага не соответствует
реальности", "переформулируйте шаг")`.

**Input**: `healer.heal(failed_step, "err", [], page)`.

**Trace**:
```
classify → incurable → on_healing_started → IncurableStepError(step_text, reason, recommendation)
```

**Assertions**:
```
pytest.raises(IncurableStepError)
excinfo.value.reason == "текст шага не соответствует реальности"
excinfo.value.recommendation == "переформулируйте шаг"
str(excinfo.value) contains all three fields
```

**Sufficiency**: incurability carries the verdict to the engineer — an actionable message.

---

#### `test_create_provider_unknown_fails_loudly`

**Input**:
```python
config = Config.model_construct(provider="groq")  # validation bypassed intentionally:
                                                  # otherwise Literal will not let the value
                                                  # through
create_provider(config)
```

**Trace**:
```
Config.model_construct(provider="groq")   # the field set without validation
create_provider → no elif branch matched → ValueError with the supported list
```

**Assertions**:
```
pytest.raises(ValueError); "openai" and "anthropic" in the text
```

**Sufficiency**: protection for configuration that slipped past Config validation.

---

#### `test_save_readonly_cache_skips_loudly`

**Setup**: a `tmp_path` directory, `chmod 0o500` (skipif when running as root — root ignores
modes); `os.access` will return False; an event recorder.

**Input**: `cache.save(step)`.

**Trace**:
```
save → writable False → emit on_cache_skipped(reason="read-only cache") → return without
  writing
```

**Assertions**:
```
no exceptions; no file created
recorded: ("on_cache_skipped", reason="read-only cache")
```

**Sufficiency**: a read-only run is correct — the cache is always read, the write is skipped
quietly for the run and loudly in the log.

---

#### `test_load_missing_file_returns_none`

**Input**: `cache.load(StepIdentity(cache_key="k", step_type="action", normalized_text="нет такого шага"))`.

**Trace**:
```
load → the file does not exist → None
```

**Assertions**:
```
result is None
```

**Sufficiency**: a cache miss is a normal situation, not an error.

---

#### `test_load_config_no_pyproject_fails_loudly`

**Setup**: an isolated working directory with no pyproject.toml up the tree
(`monkeypatch.chdir(tmp_path)`; under a non-deterministic environment — `mock.patch` of the
upward-from-cwd search).

**Input**: `load_config(pyproject_path=None)`.

**Trace**:
```
load_config → auto-search: cwd and all parents → pyproject.toml not found
  → a loud "pyproject.toml not found" error
```

**Assertions**:
```
pytest.raises with the text "pyproject.toml not found"
```

**Sufficiency**: the auto-search contract — a missing configuration file is not silent: the
engineer sees an actionable error, not mysterious defaults from someone else's pyproject.toml.

---

### Edge Case Tests

#### `test_load_config_missing_section_yields_defaults`

**Setup**: `tmp_path/pyproject.toml` without `[tool.prettyplay]` (for example, only
`[project]`).

**Input**: `load_config(pyproject_path=...)`.

**Trace**:
```
toml → data.get("tool", {}).get("prettyplay", {}) = {} → Config() → defaults
```

**Assertions**:
```
config.provider == "openai"; config.generation_attempts == 3
```

**Sufficiency**: "a missing section is an empty section" — an empty TOML does not break
startup.

---

#### `test_normalize_empty_and_whitespace_only`

**Input**: `normalize_step_text("")`, `normalize_step_text("   ")`, `normalize_step_text("\n\t")`.

**Assertions**:
```
all three → ""
```

**Sufficiency**: boundary inputs of the pure function — empty/whitespace-only sentences yield
an empty normalized text (the address is still unique via the triple).

---

#### `test_load_metadata_mismatch_treated_as_miss`

**Setup**: in the `tmp_path` cache, a file with the identity's digest but a manually altered
`STEP_TEXT`.

**Input**: `cache.load(identity)`.

**Trace**:
```
load → the file exists → metadata ≠ identity → protective miss → None
```

**Assertions**:
```
result is None (the step will be regenerated, the run does not crash)
```

**Sufficiency**: a manual edit/corruption of a cache file does not cripple the run.

---

#### `test_load_corrupt_file_treated_as_miss`

**Setup**: in the `tmp_path` cache, a file named `identity.filename`, its content a fragment
without a header and without `def step(`: `"garbage not a module"`.

**Input**: `cache.load(identity)`.

**Trace**:
```
load → the file exists → read → header parsing failed (no constant fields),
  the "\ndef step(" tail not found → the protective block → None
```

**Assertions**:
```
result is None (no exceptions; the step will be regenerated, the run does not crash)
```

**Sufficiency**: the contract's "The cache is always read, in every environment" — a
structurally damaged file yields a miss, not a run crash; a regression guard against load
raising.

---

#### `test_budgets_default_limits_from_config`

**Input**: `RunBudgets(config.generation_attempts, config.healing_attempts)` with `Config()`.

**Trace**:
```
RunBudgets(3, 2): 3× try_generation → True,True,True,False; independently 2× try_healing
```

**Assertions**:
```
[try_generation(id) for _ in range(4)] == [True, True, True, False]
[try_healing(id) for _ in range(3)] == [True, True, False]
```

**Sufficiency**: the standard MVP budgets 3/2 — a default-setting invariant.

---

#### `test_classification_unparsable_defaults_to_incurable`

**Setup**: a stub provider returns garbage ("sorry cannot answer" without `|`).

**Input**: `provider.classify_failure(...)` (provider level).

**Trace**:
```
parsing failed → protective mapping → FailureClassification("incurable", "classification
verdict unparsable", …)
```

**Assertions**:
```
classification.category == "incurable"
```

**Sufficiency**: a malformed LLM answer cannot mask a defect — the safe default.

---

#### `test_prettytest_context_manager_closes_page`

**Setup**: the runtime global isolated; `mock` runtime.open_page → a fake page with a close()
record.

**Input**:
```python
with PrettyTest("k") as t:
    t.action("шаг")
```

**Trace**:
```
__enter__ → self; action → open_page (once) → execute ✓
__exit__ → close() → page.close()
```

**Assertions**:
```
page.closed is True; runtime.close not called (the runtime stays alive)
a second with: a new page, the same runtime
```

**Sufficiency**: the context manager closes the per-test context without touching the shared
runtime.

---

#### `test_runtime_constructs_without_llm_credentials`

**Setup**: `monkeypatch.delenv` of both keys; the runtime global isolated.

**Input**: `runtime = PrettyplayRuntime(Config(model="gpt-5"))`; reading `runtime.config`,
`runtime.budgets`.

**Trace**:
```
__init__ → Config, RunBudgets — no provider client is created
the provider was not accessed
```

**Assertions**:
```
construction without exceptions
runtime.provider has not been created yet (lazy) — accessing it is not required within the
test
```

**Sufficiency**: a run without keys starts and works on the cache — a team-workflow CI
without secrets.

---

#### `test_incurable_error_message_renders_all_fields`

**Input**: `str(IncurableStepError("шаг", "причина", "рекомендация"))`.

**Assertions**:
```
"шаг" in s and "причина" in s and "рекомендация" in s
the error is a PrettyplayError instance (a single except at the suite boundary)
```

**Sufficiency**: the "the rendered message includes each of them" requirement + the taxonomy's
common base.

---

## Additional Instructions for the Implementation Agent

- Implement the cells strictly bottom-up: config → reporting → failures → driver → cache →
  llm → engine → root; after each cell — `goga lint` and the import facade check.
- `prettyplay/__init__.py` — re-export of the root facade (`PrettyTest`, `StepExecutor`,
  `PrettyplayRuntime`, `get_runtime`, `__all__`); the facade check:
  `python -c "from prettyplay import PrettyTest"`.
- Each cell's `__init__.py` re-exports the cell's public entities (per its CODEMANIFEST) from
  the modules named in `location:` (relative imports + `__all__`) — the import examples in the
  cell `.usages/` import from the cell packages, this surface must work:
  - `prettyplay/config/__init__.py`: `Config` (models), `load_config` (loader)
  - `prettyplay/reporting/__init__.py`: `StepHooks` (hooks), `StepReporter` (reporter)
  - `prettyplay/failures/__init__.py`: `PrettyplayError`, `ProductDefectError`,
    `IncurableStepError`, `LlmUnavailableError` (errors)
  - `prettyplay/driver/__init__.py`: `DriverSession` (session), `PageFacade`,
    `LocatorFacade` (page)
  - `prettyplay/cache/__init__.py`: `normalize_step_text` (text), `StepIdentity`,
    `CachedStep` (models), `StepCache` (store), `RunBudgets` (budgets)
  - `prettyplay/llm/__init__.py`: `LlmProvider`, `create_provider` (provider),
    `OpenAiProvider` (openai_provider), `AnthropicProvider` (anthropic_provider),
    `FailureClassification` (models)
  - `prettyplay/engine/__init__.py`: `run_step_code` (execution), `StepGenerator`
    (generator), `StepHealer` (healer)
- The facade check after each cell: `python -c "from prettyplay.<cell> import <entity>"`
  (for example `from prettyplay.cache import StepCache` — verbatim from `storage.md`).
- Imports inside the package — relative only (`from ..cache.store import StepCache`);
  absolute — stdlib and third-party.
- All models — pydantic v2, `kw_only=True`, empty defaults, `None` only for explicit absence
  (`screenshot`, `pyproject_path`, `cache_path`).
- The driver facade surface — a backward-compatibility contract: extend, never rename/delete;
  when the surface changes, synchronize `PAGE_API_SURFACE` in generator.py and
  `prettyplay/driver/.usages/facade.md`.
- LLM keys — env only (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`), never from files and never in
  logs; create the provider client lazily on the first request.
- One provider request per attempt; retries and budgets — the engine's exclusive prerogative
  (`RunBudgets`), not the provider's.
- No fixed delays in step code or the facade (locator auto-wait); the library-level
  `os.replace` backoff on Windows is the only permitted sleep (up to 3×0.1 s).
- One logger: `logging.getLogger("prettyplay")`; events = hook names; context via `extra`;
  `on_cache_skipped` and hook failure — WARNING, the rest of the lifecycle — INFO.
- ruff: line-length 120, complexity 10; dependencies in `pyproject.toml` with minimal versions
  (playwright, openai, anthropic, pydantic; `tomli>=2.0; python_version < "3.11"`; the test
  ones — in `[project.optional-dependencies].test`).
- The step cache file: a `STEP_TEXT` / `CACHE_KEY` / `STEP_TYPE` / `CREATED_AT` header (repr
  literals), then fixed-form code `def step(page) -> None:`; the file carries no
  library-version field.
- Generated step code is executed only through `run_step_code` (compile → namespace →
  step(page)); do not register in `sys.modules`; do not execute arbitrary files.
