# [ARCHITECTURE_PLAN]

## Topic

**Prettyplay MVP — UI-тесты на человеческом языке с кэшем шагов и самолечением**

План: `.goga/history/2026/the-first-version/arch.md` (путь из `goga history path -f arch.md`).
Проект greenfield: `goga schema` → `[]`; **все 8 клеток создаются anew** (модификаций существующих нет — их не существует).

## Implementation Order

1. **prettyplay/config** — лист — внутренних Imports нет; настройки нужны всем.
2. **prettyplay/reporting** — лист — внутренних Imports нет; видимость нужна cache/engine/корню.
3. **prettyplay/failures** — лист — внутренних Imports нет; таксономия нужна llm/engine/корню.
4. **prettyplay/driver** — зависит от config (Config).
5. **prettyplay/cache** — зависит от config (Config) и reporting (StepReporter + usage hooks).
6. **prettyplay/llm** — зависит от config (Config) и failures (LlmUnavailableError).
7. **prettyplay/engine** — зависит от llm, cache, driver, reporting, failures, config.
8. **prettyplay** — корень — зависит от всех семи клеток; фасад библиотеки.

## Artifacts
### Cell: prettyplay/config — CREATED
#### CODEMANIFEST
```yaml
Usages:
  conventions: .goga/usages/conventions.md
  pydantic: .goga/usages/cooks/pydantic.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `pydantic` for data models and TOML loading.

  All data models — pydantic v2, kw_only=True, empty defaults (None only for explicit absence).
  Naming: PascalCase for classes; snake_case for functions, methods, properties.
  Type hints mandatory; no *args/**kwargs; generics parameterized.

---

"Config(provider: str, browser: str, model: str, generation_model: str, classification_model: str, base_url: str, cache_root: str, generation_attempts: int, healing_attempts: int, send_screenshots: bool)":
  location: models.py
  annotations: |
    Validated project settings — the single source of the immutable configuration part.

    `provider`: the LLM provider of the {openai, anthropic} set; default openai.
    `browser`: browser of the {chromium, firefox, webkit} matrix; default chromium.
    `model`: main LLM model name.
    `generation_model`: optional generation override; empty — fallback to `model`.
    `classification_model`: optional classification override; empty — fallback to `model`.
    `base_url`: optional custom LLM API endpoint.
    `cache_root`: cache root; empty — default <repo root>/.prettyplay/cache/ resolved by `load_config`.
    `generation_attempts`: generation attempt budget per step per run; default 3.
    `healing_attempts`: healing attempt budget per step per run; default 2.
    `send_screenshots`: optional screenshot input to the LLM; default False.

    Requirements:
    - kw_only construction; every field has an empty default
    - provider validated against {openai, anthropic}; browser against the matrix; invalid value — loud actionable error
    - attempts are positive integers

    Constraints:
    - No secret values in fields: LLM API keys are never stored in the config; keys come only from environment variables
  properties:
    "provider -> str": |
      The LLM provider setting: openai or anthropic.
    "browser -> str": |
      The browser setting of the {chromium, firefox, webkit} matrix.
    "model -> str": |
      The main LLM model name.
    "generation_model -> str": |
      The optional generation model override.
    "classification_model -> str": |
      The optional classification model override.
    "base_url -> str": |
      The optional custom LLM API endpoint.
    "cache_root -> str": |
      The cache root; empty means the default resolved at load.
    "generation_attempts -> int": |
      The generation attempt budget per step per run.
    "healing_attempts -> int": |
      The healing attempt budget per step per run.
    "send_screenshots -> bool": |
      Whether screenshots are attached to LLM requests.
    "effective_generation_model -> str": |
      generation_model when non-empty, otherwise model.
    "effective_classification_model -> str": |
      classification_model when non-empty, otherwise model.

"load_config(pyproject_path: str | None) -> config: Config":
  location: loader.py
  annotations: |
    Load project configuration from pyproject.toml with environment overrides.

    `pyproject_path`: optional explicit path to pyproject.toml; empty — the first pyproject.toml found upwards from the current directory.
    `config`: fully resolved and validated `Config`.

    Algorithm:
    1. Resolve the pyproject.toml path: given `pyproject_path` or the first match found upwards from the current directory
    2. Parse TOML: stdlib tomllib on Python 3.11+, tomli on 3.10 (see `pydantic`)
    3. Extract the tool.prettyplay section; a missing section is an empty section
    4. Apply environment overrides: each setting is overridden by PRETTYPLAY_<SETTING_UPPERCASE> when the variable is set
    5. Construct `Config`; a validation failure raises a loud actionable error naming the invalid setting

    Requirements:
    - An env override exists for every setting of `Config`
    - The empty cache_root setting is resolved to the absolute default <repo root>/.prettyplay/cache/ at load

    Constraints:
    - Never read or store LLM API keys from any file; keys come only from environment variables
    - Python 3.10 compatibility via the tomli fallback (see `pydantic`)

---

Author: Goga
CreatedAt: 07/09/26
Description: |
  Project settings of prettyplay: the validated [tool.prettyplay] schema and the loader with environment overrides.
```
#### .usages file: `prettyplay/config/.usages/configuration.md`
````md
# Project configuration

Domain: prettyplay settings. Audience: integrators configuring a test project and CI.

The immutable part of the settings lives in the [tool.prettyplay] section of pyproject.toml. Load it once per run; every run reads the same values.

```toml
[tool.prettyplay]
provider = "openai"
browser = "chromium"
model = "gpt-5"
generation_model = ""      # optional: empty -> model
classification_model = ""  # optional: empty -> model
base_url = ""
cache_root = ""            # empty -> <repo>/.prettyplay/cache/
generation_attempts = 3
healing_attempts = 2
send_screenshots = false
```

## Environment overrides

Every setting has an override for CI — env variable PRETTYPLAY_<SETTING> in upper case:

| Setting | Env override |
|---|---|
| provider | PRETTYPLAY_PROVIDER |
| browser | PRETTYPLAY_BROWSER |
| model | PRETTYPLAY_MODEL |
| generation_model | PRETTYPLAY_GENERATION_MODEL |
| classification_model | PRETTYPLAY_CLASSIFICATION_MODEL |
| base_url | PRETTYPLAY_BASE_URL |
| cache_root | PRETTYPLAY_CACHE_ROOT |
| generation_attempts | PRETTYPLAY_GENERATION_ATTEMPTS |
| healing_attempts | PRETTYPLAY_HEALING_ATTEMPTS |
| send_screenshots | PRETTYPLAY_SEND_SCREENSHOTS |

## Rules

- LLM API keys are never stored in the config file — secrets come only from environment variables: OPENAI_API_KEY for openai, ANTHROPIC_API_KEY for anthropic
- Invalid configuration fails loudly with an actionable message naming the setting
- The browser matrix: chromium, firefox, webkit
- The provider set: openai, anthropic
- The cache root default: <repo root>/.prettyplay/cache/ — resolved from the located pyproject.toml

## Loading

```python
from prettyplay.config import load_config

config = load_config(pyproject_path=None)  # locates pyproject.toml upwards from the current directory
print(config.browser, config.generation_attempts)
```
````

### Cell: prettyplay/reporting — CREATED
#### CODEMANIFEST
```yaml
Usages:
  conventions: .goga/usages/conventions.md

Annotations: |
  Use `conventions` for code writing rules and testing.

  Visibility goes through the standard logging library: the logger is named prettyplay.
  Log messages: lowercase, concise operational wording, stable event names, contextual metadata attached.
  Never log secrets, credentials, tokens or personal sensitive data.

---

"StepHooks()":
  location: hooks.py
  annotations: |
    Thin callback contract for integrators: consumer-side reactions to step, generation, healing and cache events. The library calls the hooks synchronously; the integrator overrides the events of interest. No event bus, no queuing, no delivery retries.

    The base implementation of every method is a no-op: override only the events you need.
  methods:
    "on_step_started(step_text: str, step_type: str)": |
      A step started executing; `step_type` is action or assertion.
    "on_step_passed(step_text: str, step_type: str)": |
      The step finished successfully.
    "on_step_failed(step_text: str, step_type: str, error: str)": |
      The step failed; `error` is a short human-readable failure description.
    "on_generation_started(step_text: str, attempt: int)": |
      A code generation attempt started; `attempt` is the 1-based attempt number.
    "on_healing_started(step_text: str, category: str)": |
      Healing of a failed cached step started; `category` is the classification label: rot, product_defect, incurable.
    "on_healed(step_text: str, explanation: str)": |
      The step was healed and the cache updated; `explanation` says why it was rot and what changed.
    "on_cache_saved(step_text: str, filename: str)": |
      Step code was written to the cache file `filename`.
    "on_cache_skipped(step_text: str, reason: str)": |
      The cache write was skipped; `reason` names the cause, e.g. a read-only cache.

"StepReporter(hooks: list[StepHooks])":
  location: reporter.py
  annotations: |
    The single visibility point of the library: every step, generation, healing and cache event goes through the emit method — written to the logger prettyplay and forwarded to the registered `StepHooks` implementations.

    `hooks`: callback implementations registered by the integrator; the list may be empty.
  methods:
    "emit(event: str, payload: dict[str, str])": |
      Dispatch one event.

      `event`: the event name — equals a `StepHooks` method name exactly.
      `payload`: the string payload fields of the event.

      Algorithm:
      1. Write a structured log record to the logger prettyplay: the event name as the message, the payload fields as contextual metadata
      2. For each registered hook, in registration order, call the method named `event` with the payload values as arguments
      3. A hook that raises is logged as a warning and skipped; the run continues

      Requirements:
      - Log levels: step, generation and healing lifecycle — INFO; a skipped cache write and a failed hook call — WARNING

      Constraints:
      - No secrets in log records (see `conventions`)
      - No own event bus: the emit call is a synchronous fan-out, nothing more

---

Author: Goga
CreatedAt: 07/09/26
Description: |
  Visibility of prettyplay: the logger prettyplay plus the thin StepHooks callback contract.
```
#### .usages file: `prettyplay/reporting/.usages/hooks.md`
````md
# Step and healing hooks

Domain: event callbacks of prettyplay. Audience: integrators building custom reporting, metrics or CI reactions on top of step execution.

StepHooks is a thin callback contract. The library calls the matching method synchronously while a step executes. The base implementation of every method is a no-op — override only the events you need. Hook implementations are registered on the main library object at the start of a test.

## Events

| Method | When | Payload |
|---|---|---|
| on_step_started | a step started executing | step_text, step_type (action or assertion) |
| on_step_passed | the step finished successfully | step_text, step_type |
| on_step_failed | the step failed | step_text, step_type, error (short description) |
| on_generation_started | a generation attempt started | step_text, attempt (1-based) |
| on_healing_started | healing of a failed cached step started | step_text, category (rot, product_defect, incurable) |
| on_healed | the step healed, cache updated | step_text, explanation (why rot, what changed) |
| on_cache_saved | step code written to the cache | step_text, filename |
| on_cache_skipped | cache write skipped | step_text, reason (e.g. read-only cache) |

## Example

```python
from prettyplay.reporting import StepHooks


class HealingMonitor(StepHooks):
    def on_healed(self, step_text: str, explanation: str) -> None:
        print(f"healed: {step_text} — {explanation}")

    def on_cache_skipped(self, step_text: str, reason: str) -> None:
        print(f"cache not saved: {step_text} — {reason}")
```

## Rules

- Handlers run synchronously inside step execution: keep them fast
- A raising handler is logged as a warning and skipped — the test run never fails because of a hook
- All payload values are plain strings
- Step texts land in logs and hooks: never put secrets or personal data into a step sentence
````

### Cell: prettyplay/failures — CREATED
#### CODEMANIFEST
```yaml
Usages:
  conventions: .goga/usages/conventions.md

Annotations: |
  Use `conventions` for code writing rules and testing.

  The failure taxonomy of the library: three distinct, user-distinguishable failure kinds; every failure carries an actionable message.
  All failure types derive from the single library base `PrettyplayError`.

---

"PrettyplayError(message: str)":
  location: errors.py
  annotations: |
    The common base of every library failure. Exists for one consumer need: catch any prettyplay failure with a single except clause at the test-suite boundary.

    `message`: the failure description.

"PrettyplayError::ProductDefectError(step_text: str, message: str)":
  location: errors.py
  annotations: |
    A real functional product defect: the expectation of an assertion step legitimately did not hold against the current application state. This is the signal the test suite exists for.

    `step_text`: the sentence of the failed step.
    `message`: what exactly was expected and what was observed.

    Requirements:
    - Propagates to the test runner as a failing test: no retry, no healing
    - The message names the expectation and the observed state

"PrettyplayError::IncurableStepError(step_text: str, reason: str, recommendation: str)":
  location: errors.py
  annotations: |
    An incurable step: regeneration cannot produce working code — the attempt budget is exhausted, the step text no longer matches the application reality, or the intent is ambiguous.

    `step_text`: the sentence of the failed step.
    `reason`: the specific incurability cause.
    `recommendation`: the recommended engineer action, e.g. reword the step or refresh the cache.

    Requirements:
    - Carries all three fields; the rendered message includes each of them

"PrettyplayError::LlmUnavailableError(message: str)":
  location: errors.py
  annotations: |
    LLM infrastructure failure: the provider service is unreachable, times out, rate-limits or rejects authentication. Blocks only code generation and healing; cached steps keep running.

    `message`: the failure description naming the provider.

    Requirements:
    - Raised only on generation or healing paths; never on a cached step execution path

---

Author: Goga
CreatedAt: 07/09/26
Description: |
  The failure taxonomy of prettyplay: product defect, incurable step, LLM infrastructure — mutations of one library base.
```
#### .usages file: `prettyplay/failures/.usages/taxonomy.md`
````md
# Failure taxonomy

Domain: failure kinds of prettyplay. Audience: integrators wiring library failures into runner and CI reporting.

Every library failure is one of three distinct kinds; each has its own exception type, and all derive from `PrettyplayError`.

| Exception | Meaning | When it happens | Recommended reaction |
|---|---|---|---|
| ProductDefectError | real product regression | an assertion expectation legitimately failed | treat as a bug: file it, fix the product — this failure is the value of the suite |
| IncurableStepError | the step cannot be (re)generated | attempt budget exhausted, step text no longer matches reality, ambiguity | follow `recommendation`: reword the step or refresh the cache |
| LlmUnavailableError | LLM infrastructure down | generation or healing ran while the provider was unavailable | restore provider access or keys; cached steps are unaffected |

## Example

```python
import pytest

from prettyplay.failures import IncurableStepError, PrettyplayError


def test_reports_only_library_failures():
    with pytest.raises(IncurableStepError) as info:
        ...
    assert info.value.recommendation


# any library failure at the suite boundary:
# except PrettyplayError: ...
```

## Rules

- Every failure message is actionable: what happened, on which step, what to do next
- A healed run never turns a ProductDefectError into a green test
- LlmUnavailableError never occurs on the cached path — a cached suite runs without any LLM
````

### Cell: prettyplay/driver — CREATED
#### CODEMANIFEST
```yaml
Imports:
  - Types:
      - Config
    From: prettyplay/config

Usages:
  conventions: .goga/usages/conventions.md
  playwright: .goga/usages/cooks/playwright.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `playwright` for the sync API lifecycle, locators, auto-wait and the accessibility snapshot.

  The driver is Playwright sync-only: the async API is out of scope.
  One browser process serves the whole run; every test gets its own isolated browser context — no state is shared between tests through the library.
  All waits go through locators and expectations; fixed delays (time.sleep and similar) are forbidden.
  The facade surface is a backward-compatibility contract: generated step code works only through `PageFacade` and LocatorFacade, so the existing method set must not break across library releases — extend, never rename or remove.

---

"DriverSession(config: Config)":
  location: session.py
  annotations: |
    Lifecycle owner of the Playwright sync driver and the browser process for the whole run.

    `config`: project settings; the browser setting selects the browser of the {chromium, firefox, webkit} matrix (see `playwright`).
  methods:
    "open_context() -> page: PageFacade": |
      Open a fresh isolated context with one page.

      Algorithm:
      1. Launch the browser lazily on the first call: constructing the session starts nothing
      2. Create a fresh isolated browser context (see `playwright`)
      3. Create a page inside the context
      4. Wrap the page into `PageFacade` and return it

      Requirements:
      - Each result is isolated from every other context of the run
    "close()": |
      Stop the browser and the Playwright driver; safe to call when nothing was started.

"PageFacade()":
  location: page.py
  annotations: |
    The narrow, stable facade of a single test page — the only page API the generated step code may use. Wraps one isolated browser context created by `DriverSession`.

    Requirements:
    - Locating methods never sleep: waiting is the locator's own auto-wait behavior
    - aria_snapshot and screenshot reflect the state at call time

    Constraints:
    - No method exposes raw Playwright objects: the facade is the boundary generated code works against
  properties:
    "url -> str": |
      The current page URL.
  methods:
    "open(url: str)": |
      Navigate to `url` and wait for the load state (see `playwright`).
    "find_by_role(role: str, name: str) -> element: LocatorFacade": |
      Locate one element by its aria role and accessible name; returns a `LocatorFacade`.
    "find_by_label(label: str) -> element: LocatorFacade": |
      Locate one element by its associated label; returns a `LocatorFacade`.
    "find_by_text(text: str) -> element: LocatorFacade": |
      Locate one element by its visible text; returns a `LocatorFacade`.
    "aria_snapshot() -> snapshot: str": |
      The structured accessibility-tree representation of the page — the primary machine-readable page state (see `playwright`).
    "screenshot() -> image: bytes": |
      A full-page PNG image of the current state.
    "close()": |
      Close the isolated context of this page; the browser process keeps running.

"LocatorFacade()":
  location: page.py
  annotations: |
    An auto-waiting handle of one located element — the only element API the generated step code may use.

    Requirements:
    - Every action and expectation auto-waits for actionability (see `playwright`)
    - Failed expectations raise assertion-style errors destined for failure classification

    Constraints:
    - No fixed delays; no raw Playwright objects exposed
  methods:
    "click()": |
      Click the element, waiting for actionability.
    "fill(value: str)": |
      Set the text input value of the element to `value`.
    "select_option(value: str)": |
      Select the option with `value` in a list or combo box.
    "expect_visible()": |
      Assert the element is visible.
    "expect_text(text: str)": |
      Assert the element text equals or contains `text`.
    "expect_enabled()": |
      Assert the element is enabled.

---

Author: Goga
CreatedAt: 07/09/26
Description: |
  The Playwright sync driver of prettyplay: the run-scoped session and the narrow backward-compatible page facade for generated step code.
```
#### .usages file: `prettyplay/driver/.usages/facade.md`
````md
# Driver facade

Domain: the browser facade of prettyplay. Audience: consumers of the page API — the step generation engine and engineers reading or hand-writing step code.

The facade wraps the Playwright sync API. Step code receives a `PageFacade` and works only through it and `LocatorFacade` — never through raw Playwright objects. The method set is a backward-compatibility contract: cached step code keeps working across library upgrades.

## Surface

| Call | Purpose |
|---|---|
| page.open(url) | navigate and wait for load |
| page.find_by_role(role, name) | element by aria role and accessible name |
| page.find_by_label(label) | element by associated label |
| page.find_by_text(text) | element by visible text |
| page.aria_snapshot() | accessibility-tree page state |
| page.screenshot() | full-page PNG bytes |
| page.url | current URL |
| element.click() | click with auto-wait |
| element.fill(value) | set input text |
| element.select_option(value) | choose an option |
| element.expect_visible() | assert visible |
| element.expect_text(text) | assert text |
| element.expect_enabled() | assert enabled |

## Example

```python
page.open("https://example.com/login")
page.find_by_label("Логин").fill("user")
page.find_by_label("Пароль").fill("secret")
page.find_by_role("button", name="Войти").click()
page.find_by_text("Добро пожаловать").expect_visible()

snapshot = page.aria_snapshot()
```

## Rules

- Contexts are isolated per test; the browser process is shared per run
- Auto-wait everywhere: no time.sleep, no fixed delays in step code
- Never put secrets into step actions — step texts and code land in the repository cache
````

### Cell: prettyplay/cache — CREATED
#### CODEMANIFEST
```yaml
Imports:
  - Types:
      - Config
    From: prettyplay/config
  - Types:
      - StepReporter
    Usages:
      - hooks
    From: prettyplay/reporting

Usages:
  conventions: .goga/usages/conventions.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `hooks` from Imports for the payload contract of the cache events.

  The cache is a repository artifact: one .py file per step, addressed deterministically; the cache is always read, writes are best-effort.
  Step identity is intentional: the same normalized sentence in the same context is one step; a different language, a different step type or a different cache key is a different step.
  RunBudgets lives in this cell because its accounting key is `StepIdentity`: run-scoped attempt accounting stays next to the addressing it is keyed by.

---

"normalize_step_text(text: str) -> normalized: str":
  location: text.py
  annotations: |
    Normalize a step sentence for identity and addressing.

    `text`: the raw step sentence as written by the engineer.
    `normalized`: the normalized sentence.

    Algorithm:
    1. Apply Unicode NFC normalization
    2. Trim leading and trailing whitespace
    3. Collapse internal whitespace runs to single spaces
    4. Apply casefold

    Requirements:
    - Pure function: no I/O, no locale dependence
    - «Нажать Войти» and «нажать  войти » normalize to the same string; a Russian sentence and its English translation stay different

"StepIdentity(cache_key: str, step_type: str, normalized_text: str)":
  location: models.py
  annotations: |
    The address of a cache step: the triple (cache_key, step_type, normalized_text) plus the deterministic file name derived from it.

    `cache_key`: the explicit context key set by the integrator on the main object.
    `step_type`: action or assertion.
    `normalized_text`: the step sentence after `normalize_step_text`.
  properties:
    "cache_key -> str": |
      The explicit context key of the step address.
    "step_type -> str": |
      The step kind: action or assertion.
    "normalized_text -> str": |
      The normalized step sentence.
    "filename -> str": |
      The deterministic cache file name.

      Algorithm:
      1. Build the identity string: cache_key, step_type and normalized_text joined with an unambiguous separator
      2. Hash the string with sha256
      3. Compose the file name from the hex digest

      Requirements:
      - The same triple always yields the same file name; any difference in the triple yields a different one
      - The digest identifies the file unambiguously inside the cache directory

"CachedStep(identity: StepIdentity, code: str, created_at: str)":
  location: models.py
  annotations: |
    One cached step in memory: the metadata and the generated code of the step, as stored in its cache file.

    `identity`: the step address.
    `code`: the generated step code of the fixed form.
    `created_at`: the creation date.

    Requirements:
    - The cache file is a valid Python module: metadata fields first, then the step code; importing the module and reading the fields reconstructs the step
    - The file carries no library version field and is never invalidated by a library upgrade
  properties:
    "identity -> StepIdentity": |
      The step address.
    "code -> str": |
      The generated step code of the fixed form.
    "created_at -> str": |
      The creation date.

"StepCache(config: Config, path: str | None, reporter: StepReporter)":
  location: store.py
  annotations: |
    The repository store of cache steps: addressing, atomic writes and the read-only mode.

    `config`: project settings; the cache_root setting is the cache root.
    `path`: the optional subdirectory inside the cache; part of the address — steps of different subdirectories never collide; empty — the shared root, so equal cache keys are reused across tests.
    `reporter`: the visibility point — cache events (saved, skipped) go through it.
  properties:
    "root -> str": |
      The effective cache root; the default is <repo root>/.prettyplay/cache/.
    "writable -> bool": |
      Whether the cache directory accepts writes.
  methods:
    "load(identity: StepIdentity) -> step: CachedStep | None": |
      Load the cached step by address.

      Algorithm:
      1. Resolve the target file by the effective root, the subdirectory and the identity file name
      2. A missing file returns None
      3. Read the module, validate the metadata fields, reconstruct `CachedStep`
    "save(step: CachedStep)": |
      Store the step atomically, best-effort.

      Algorithm:
      1. Check writability: a read-only cache skips the write and reports on_cache_skipped with the reason read-only cache
      2. Serialize the step into the module text: metadata fields, then the code
      3. Write a temporary file with a unique name in the target directory
      4. Replace the target file atomically via os.replace
      5. On Windows, when the target is busy: retry the replace shortly, then skip the write for this step and report on_cache_skipped — the run does not fail
      6. Report on_cache_saved with the file name on success

      Requirements:
      - Concurrent writers on one step never corrupt the file: last writer wins
      - A partially written file never becomes visible: the replace is atomic
      - The cache is always read, in every environment

"RunBudgets(generation_limit: int, healing_limit: int)":
  location: budgets.py
  annotations: |
    The per-run attempt registry: how many generation and healing attempts each step has left within the run.

    `generation_limit`: the generation attempt budget per step per run.
    `healing_limit`: the healing attempt budget per step per run.

    Requirements:
    - The registry lives for the whole run (process): budgets are not reset between tests, so a step reused across tests shares one budget
    - The identity key is `StepIdentity`
    - An exhausted budget returns False — the caller turns it into the incurable failure

    Constraints:
    - No persistence: budgets exist only in the memory of the running process
  methods:
    "try_generation(identity: StepIdentity) -> allowed: bool": |
      Consume one generation attempt for the step; False — the budget is exhausted, the caller reports incurability.
    "try_healing(identity: StepIdentity) -> allowed: bool": |
      Consume one healing attempt for the step; False — the budget is exhausted, the caller reports incurability.

---

Author: Goga
CreatedAt: 07/09/26
Description: |
  The step cache of prettyplay: normalization, deterministic addressing, atomic repository storage and the per-run attempt budgets.
```
#### .usages file: `prettyplay/cache/.usages/addressing.md`
````md
# Step addressing

Domain: step identity and addressing of the cache. Audience: engineers reasoning about step reuse and inspecting the repository cache.

## Identity triple

| Component | Source | Effect on identity |
|---|---|---|
| cache_key | the main object constructor argument | a different key — a different step |
| step type | action vs assertion | the same sentence as action and as assertion — two steps |
| normalized sentence | NFC, trim, whitespace collapse, casefold | «Нажать Войти» equals «нажать  войти »; a Russian sentence and its English translation are different steps |

A missing cache entry for the computed address is a cache miss — the step is generated, not an error.

## Normalize and address

```python
from prettyplay.cache import StepIdentity, normalize_step_text

normalized = normalize_step_text("  Нажать   Войти ")
identity = StepIdentity(
    cache_key="login-flow",
    step_type="action",
    normalized_text=normalized,
)
# identity.filename — the deterministic digest of the triple
```

## Layout

The cache root defaults to <repo root>/.prettyplay/cache/ and is set by cache_root. The optional subdirectory argument is part of the address: steps never leak across subdirectories; without a subdirectory, equal cache keys are reused across tests. One .py file per step.
````
#### .usages file: `prettyplay/cache/.usages/storage.md`
````md
# Cache storage

Domain: reading and writing the step cache. Audience: engineers inspecting cache files and building tooling around the store.

## Read and write

```python
from prettyplay.cache import CachedStep, StepCache
from prettyplay.config import Config
from prettyplay.reporting import StepReporter

cache = StepCache(config=Config(), path="checkout", reporter=StepReporter(hooks=[]))

step = cache.load(identity)  # None on a cache miss
if step is None:
    # a miss means: generate the step, then store it
    cache.save(CachedStep(identity=identity, code=step_code, created_at="2026-09-07"))
```

## File format

Each file carries the metadata fields (step sentence, cache key, creation date) followed by the generated step code of the fixed form. Files carry no library version and are never invalidated by a library upgrade.

## Write behavior

- save never fails the run: a read-only cache or a busy Windows target skips the write loudly
- writes are atomic: a unique temporary file in the target directory, then an atomic replace; the last writer wins, a partial file never becomes visible
- load always works, in every environment

## Team workflow

Generate locally where the LLM is reachable → commit the cache directory → CI runs the whole suite from the cache with no LLM keys at all.
````
#### .usages file: `prettyplay/cache/.usages/budgets.md`
````md
# Attempt budgets

Domain: generation and healing attempt budgets. Audience: engineers tuning budgets and reasoning about budget exhaustion.

## Consume attempts

```python
from prettyplay.cache import RunBudgets

budgets = RunBudgets(generation_limit=3, healing_limit=2)

if budgets.try_generation(identity):
    ...  # attempt allowed; False — budget exhausted, the caller reports incurability
```

## Semantics

- Budgets are per step per run (process) and shared across tests: a step reused in several tests has one budget
- Defaults: 3 generation attempts, 2 healing attempts — configurable in the project settings
- An exhausted budget is the incurable failure, never an infinite loop
- Budgets exist only in the memory of the running process — nothing is persisted
````

### Cell: prettyplay/llm — CREATED
#### CODEMANIFEST
```yaml
Imports:
  - Types:
      - Config
    From: prettyplay/config
  - Types:
      - LlmUnavailableError
    From: prettyplay/failures

Usages:
  conventions: .goga/usages/conventions.md
  openai: .goga/usages/cooks/openai.md
  anthropic: .goga/usages/cooks/anthropic.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `openai` and `anthropic` for the SDK call patterns and the error mapping of the two providers.

  Provider parity is absolute: both providers expose the same operations, accept the same inputs, return the same output shapes and map failures to the same taxonomy; the provider choice is a configuration decision, never a capability difference.
  API keys come only from environment variables; never log keys or payloads containing secrets.
  One completion request per attempt: attempt budgets are owned by the calling engine, never by a provider.
  Cached step code never depends on the provider: the provider serves generation and classification only.

---

"LlmProvider()":
  location: provider.py
  annotations: |
    The unified LLM port of the library: code generation for a step and failure classification for healing. One contract, two interchangeable implementations selected by configuration.
  methods:
    "generate_step_code(prompt: str, step_text: str, previous_steps: list[str], snapshot: str, screenshot: bytes | None, page_api: str, existing_code: str | None, error: str | None) -> code: str": |
      Generate step code of the fixed form.

      `prompt`: the system prompt text supplied by the calling engine — applied verbatim as the system message.
      `step_text`: the sentence of the step to generate.
      `previous_steps`: the sentences of the previous steps of the test, in execution order — scenario context.
      `snapshot`: the accessibility snapshot of the current page.
      `screenshot`: an optional PNG image of the page; passed only when the project enables screenshots.
      `page_api`: the exact page facade surface listing — the list of calls the model may use.
      `existing_code`: the existing step code that failed; non-empty only on regeneration requests.
      `error`: the failure description of the existing code; non-empty only on regeneration requests.
      `code`: the generated step code of the fixed form, working only through the driver facade.

      Requirements:
      - A provider service failure (connectivity, timeout, rate limit, authentication) raises `LlmUnavailableError` naming the provider
      - The generated code contains no provider-specific constructs
    "classify_failure(prompt: str, step_text: str, code: str, error: str, snapshot: str, screenshot: bytes | None) -> classification: FailureClassification": |
      Classify a failed cached step.

      `prompt`: the system prompt text supplied by the calling engine — applied verbatim as the system message.
      `code`: the existing step code that failed.
      `error`: the human-readable description of the failure.
      `classification`: the `FailureClassification` verdict.

"LlmProvider::OpenAiProvider(config: Config)":
  location: openai_provider.py
  annotations: |
    The openai SDK implementation of `LlmProvider` (see `openai`).

    `config`: project settings; the generation model is the effective_generation_model of `config`, the classification model is the effective_classification_model of `config`; the base_url setting of `config` overrides the endpoint when set.

    Algorithm (both operations):
    1. Build the request: the prompt text as the system message, the user content carrying the inputs
    2. Send one completion request via the SDK
    3. Extract the text answer
    4. An SDK error maps to `LlmUnavailableError` (see `openai`)

"LlmProvider::AnthropicProvider(config: Config)":
  location: anthropic_provider.py
  annotations: |
    The anthropic SDK implementation of `LlmProvider` (see `anthropic`); full parity with the openai implementation.

    `config`: the same settings semantics as the openai implementation.

    Algorithm (both operations):
    1. Build the request: the prompt text as the system message, the user content carrying the inputs
    2. Send one message request via the SDK
    3. Extract the text answer
    4. An SDK error maps to `LlmUnavailableError` (see `anthropic`)

"create_provider(config: Config) -> provider: LlmProvider":
  location: provider.py
  annotations: |
    Select and construct the LLM provider from configuration.

    `config`: project settings.
    `provider`: the selected provider implementation.

    Algorithm:
    1. Read the provider choice from `config`
    2. Construct the matching provider implementation with `config`
    3. Return it

    Requirements:
    - An unknown provider value fails loudly with an actionable message listing the supported providers

"FailureClassification(category: str, explanation: str, recommendation: str)":
  location: models.py
  annotations: |
    The verdict of a failure classification: what kind of failure it is and what to do about it.

    `category`: one of rot (the UI changed — regeneration is meaningful), product_defect (the expectation legitimately failed), incurable (regeneration cannot help).
    `explanation`: why the failure got this category.
    `recommendation`: the recommended engineer action.

    Requirements:
    - `category` is always one of the three labels
  properties:
    "category -> str": |
      The classification label: rot, product_defect or incurable.
    "explanation -> str": |
      Why the failure got this category.
    "recommendation -> str": |
      The recommended engineer action.

---

Author: Goga
CreatedAt: 07/09/26
Description: |
  The LLM port of prettyplay: one contract, the openai and anthropic SDK implementations in full parity, and the failure classification verdict.
```
#### .usages file: `prettyplay/llm/.usages/providers.md`
````md
# Providers

Domain: LLM provider selection and parity. Audience: integrators choosing a provider and setting models.

## Select a provider

```python
from prettyplay.config import Config
from prettyplay.llm import create_provider

config = Config(provider="anthropic", model="claude-sonnet-4-5")
provider = create_provider(config)
```

The provider is a project setting: openai or anthropic; env override PRETTYPLAY_PROVIDER. API keys come only from environment variables: OPENAI_API_KEY for openai, ANTHROPIC_API_KEY for anthropic.

## Models

| Setting | Purpose | Fallback |
|---|---|---|
| model | the main model for both operations | — |
| generation_model | code generation only | model |
| classification_model | failure classification only | model |

base_url overrides the provider endpoint when set.

## Parity

Both providers expose the same two operations — generate_step_code and classify_failure — with identical inputs, identical output shapes and the identical failure taxonomy: a provider service failure raises LlmUnavailableError; cached step code never depends on the provider. One request per attempt; attempt budgets belong to the calling engine.
````
#### .usages file: `prettyplay/llm/.usages/classification.md`
````md
# Failure classification

Domain: classifying a failed cached step before healing. Audience: engineers reasoning about healing decisions.

## Categories

| Category | Meaning | Consequence |
|---|---|---|
| rot | the UI changed: selectors, texts, structure | the step is regenerated from the current page and retried |
| product_defect | the expectation legitimately failed | the test fails loudly — never healed green |
| incurable | regeneration cannot help: budget exhausted, text no longer matches reality, ambiguity | the incurable failure carries step, reason, recommendation |

## Call

```python
classification = provider.classify_failure(
    prompt=system_prompt,  # the system prompt text comes from the calling engine
    step_text="нажать «Войти»",
    code=step_code,
    error="element not found: button «Войти»",
    snapshot=snapshot_text,
    screenshot=None,
)
print(classification.category, classification.explanation, classification.recommendation)
```
````

### Cell: prettyplay/engine — CREATED
#### CODEMANIFEST
```yaml
Imports:
  - Types:
      - Config
    From: prettyplay/config
  - Types:
      - StepReporter
    From: prettyplay/reporting
  - Types:
      - ProductDefectError
      - IncurableStepError
      - LlmUnavailableError
    From: prettyplay/failures
  - Types:
      - PageFacade
    Usages:
      - facade
    From: prettyplay/driver
  - Types:
      - StepCache
      - StepIdentity
      - CachedStep
      - RunBudgets
    From: prettyplay/cache
  - Types:
      - LlmProvider
      - FailureClassification
    Usages:
      - classification
    From: prettyplay/llm

Usages:
  conventions: .goga/usages/conventions.md
  generation_prompt: |
    You generate executable Python code for one step of a web UI test.

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
    - Output only the code block, no explanations
  classification_prompt: |
    You classify a failure of a cached web UI test step.

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
    Output only that single line — no code, no extra text.

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `facade` from Imports for the page API the generated code works through.
  Use `classification` from Imports for the healing decision categories.
  Use `generation_prompt` as the system prompt of every code generation request.
  Use `classification_prompt` as the system prompt of every failure classification request.
  Use `facade` from Imports as the single source of the page API surface for generation requests.

  The fixed form of step code: one function receiving exactly one argument — the `PageFacade` of the test; the function body works only through `PageFacade` and the LocatorFacade element API.
  Every attempt — generation or healing — consumes the shared per-step budget of the run; exhaustion is the incurable failure, never an infinite loop.
  Healing never masks a product defect: a classified product_defect fails the test loudly; a healed step is reported loudly and written back to the cache.

---

"run_step_code(code: str, page: PageFacade)":
  location: execution.py
  annotations: |
    Execute step code of the fixed form against the page facade of the test.

    `code`: the step code text.
    `page`: the page facade of the current test.

    Algorithm:
    1. Compile and load `code` as a module in an isolated namespace
    2. Resolve the step function of the fixed form — the single callable receiving the page facade
    3. Call it with `page`

    Requirements:
    - A failure inside the step code propagates to the caller as-is: the engine classifies it, this routine never swallows or retries
    - Executing step code loads no LLM provider and touches no network beyond the page itself

    Constraints:
    - Execute only step code produced by generation or loaded from the cache — never arbitrary file content

"StepGenerator(config: Config, provider: LlmProvider, cache: StepCache, budgets: RunBudgets, reporter: StepReporter)":
  location: generator.py
  annotations: |
    The generation engine: produce working step code for an unknown step, executing candidates against the live page.

    `config`: project settings — the screenshot flag.
    `provider`: the LLM port.
    `cache`: the step cache — a generated step is stored on success.
    `budgets`: the per-run attempt registry.
    `reporter`: the visibility point.
  methods:
    "generate(identity: StepIdentity, step_text: str, previous_steps: list[str], page: PageFacade) -> step: CachedStep": |
      Generate and store a new step.

      Algorithm:
      1. Ask the budgets registry try_generation for the step identity; a refused attempt is the incurable failure
      2. Collect the request inputs: the page accessibility snapshot, the step sentence, `previous_steps`, and the page API surface from `facade`; add the page screenshot when the project settings enable screenshots
      3. Request step code from the provider port passing `generation_prompt` as the system prompt and the page API surface listing taken from `facade`
      4. Execute the candidate with `run_step_code` against `page`
      5. On success: build `CachedStep`, save it to the cache, return it
      6. On failure: repeat from step 1 with the fresh failure description and the fresh snapshot, while attempts remain
      7. Report on_generation_started for every attempt

      Requirements:
      - Every generation request carries the exact page API surface taken from `facade` from Imports: the model always sees the precise list of calls it may use
      - Provider unavailability surfaces as `LlmUnavailableError` immediately — no retry on it
      - Budget exhaustion raises `IncurableStepError` carrying the step, the reason and a recommendation
    "regenerate(identity: StepIdentity, step_text: str, previous_steps: list[str], page: PageFacade, existing_code: str, error: str) -> step: CachedStep": |
      Regenerate a failed step for healing.

      Algorithm:
      1. The same loop as the generate method with two additions: every provider request carries `existing_code` and `error`; attempts consume the healing budget via try_healing

"StepHealer(config: Config, provider: LlmProvider, generator: StepGenerator, cache: StepCache, budgets: RunBudgets, reporter: StepReporter)":
  location: healer.py
  annotations: |
    The healing engine: classify a failed cached step, regenerate rot, never mask a defect.

    `config`: project settings — the screenshot flag.
    `provider`: the LLM port for classification.
    `generator`: the regeneration engine.
    `cache`: the step cache for the healed write-back.
    `budgets`: the per-run attempt registry.
    `reporter`: the visibility point.
  methods:
    "heal(step: CachedStep, error: str, page: PageFacade) -> step: CachedStep": |
      Classify and heal a failed cached step.

      Algorithm:
      1. Collect the classification inputs: the step sentence, the failed step code, the `error` text, the fresh page snapshot — plus the screenshot when enabled
      2. Ask the provider port classify_failure passing `classification_prompt` as the system prompt — the verdict is a `FailureClassification`
      3. Report on_healing_started with the category
      4. product_defect: raise `ProductDefectError` — the test fails, nothing is regenerated, the cache stays untouched
      5. incurable: raise `IncurableStepError` carrying the verdict explanation and recommendation
      6. rot: regenerate via the generator regenerate — its loop executes the candidate and stores the healed step on success; report on_healed with the explanation of what was rot and what changed, return the healed step
      7. A regeneration budget exhaustion inside step 6 surfaces as `IncurableStepError`

      Requirements:
      - Anti-masking: healing may only turn a rot-failed step green; a classified product defect always fails the test
      - The healed code replaces the cached code only after a successful execution

---

Author: Goga
CreatedAt: 07/09/26
Description: |
  The agent engine of prettyplay: step code generation with execution in the loop, the fixed-form execution routine, and healing with anti-masking.
```
#### .usages file: `prettyplay/engine/.usages/generation.md`
````md
# Step generation

Domain: generating executable code for an unknown step. Audience: library internals and engineers debugging a first run.

## Generate a step

```python
step = generator.generate(
    identity=identity,
    step_text="нажать «Войти»",
    previous_steps=["открыть страницу логина", "ввести логин и пароль"],
    page=page,
)
```

- The loop: request code → execute against the live page → on failure re-request with the fresh error and snapshot
- Attempts are budgeted per step per run (default 3): exhaustion raises IncurableStepError
- A success stores the step in the cache and returns it
- Provider unavailability raises LlmUnavailableError immediately — no retry on it

## The fixed form

Generated code is one function receiving exactly one argument — the page facade — and working only through the facade surface: page.find_by_role(...).click(), element.expect_visible() and alike. No provider constructs, no direct driver imports, no fixed delays.
````
#### .usages file: `prettyplay/engine/.usages/healing.md`
````md
# Step healing

Domain: healing a failed cached step. Audience: library internals and engineers reasoning about healed runs.

## Heal

```python
healed = healer.heal(step=failed_step, error="element not found: button «Войти»", page=page)
```

The classification verdict decides the path:

| Category | Path |
|---|---|
| rot | regenerate from the current page within the healing budget (default 2), execute, save back to the cache, report loudly |
| product_defect | raise ProductDefectError — the test fails, nothing is regenerated |
| incurable | raise IncurableStepError with reason and recommendation |

## Rules

- Anti-masking: healing never turns a product defect into a green test
- The healed code replaces the cached code only after a successful execution
- Healing attempts share the per-step run budget with generation
- Provider unavailability during healing raises LlmUnavailableError — an explicit infrastructure failure
````

### Cell: prettyplay — CREATED
#### CODEMANIFEST
```yaml
Imports:
  - Types:
      - Config
      - load_config
    From: prettyplay/config
  - Types:
      - StepHooks
      - StepReporter
    Usages:
      - hooks
    From: prettyplay/reporting
  - Types:
      - ProductDefectError
      - IncurableStepError
      - LlmUnavailableError
    Usages:
      - taxonomy
    From: prettyplay/failures
  - Types:
      - DriverSession
      - PageFacade
    From: prettyplay/driver
  - Types:
      - StepCache
      - StepIdentity
      - normalize_step_text
      - RunBudgets
    From: prettyplay/cache
  - Types:
      - LlmProvider
      - create_provider
    From: prettyplay/llm
  - Types:
      - StepGenerator
      - StepHealer
      - run_step_code
    Usages:
      - generation
      - healing
    From: prettyplay/engine

Usages:
  conventions: .goga/usages/conventions.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `taxonomy` from Imports for the failure kinds the step methods propagate.
  Use `hooks` from Imports for the callback contract accepted by add_hooks.
  Use `generation` and `healing` from Imports for the engine cycles the executor delegates to.

  The facade of the library: one main object per test; the engineer writes steps as plain sentences and reads the suite as a scenario.
  Framework-agnostic: no plugin machinery, no runner integration — the integrator wires the library in a few lines.
  Step sentences are visible in the test output through the standard logger prettyplay; step texts land in the cache and in LLM requests — never put secrets or personal data into a step sentence.

---

"PrettyTest(cache_key: str, cache_path: str | None)":
  location: scenario.py
  annotations: |
    The main integrator object — one instance per test. Owns the cache addressing and the isolated browser context of the test; the step cycle is delegated to `StepExecutor`.

    `cache_key`: the mandatory explicit context key — part of the step address; equal keys in the shared root reuse steps across tests.
    `cache_path`: the optional cache subdirectory — part of the address; steps never leak across subdirectories.

    Supports the context manager protocol: exit closes the test context.

    Algorithm:
    1. Resolve the shared runtime via `get_runtime`
    2. Construct the per-test reporter: `StepReporter` with an empty hooks list; add_hooks appends to it
    3. Construct the per-test `StepCache` from the runtime config, `cache_path` and the reporter
    4. Construct `StepGenerator` and `StepHealer` from the runtime config, provider and budgets, the step cache and the reporter
    5. Construct `StepExecutor` with `cache_key`, the cache, the engines, the runtime budgets and the reporter
    6. The test page opens lazily on the first step via the runtime open_page
    7. close (and the context manager exit) closes the test page context; the run-scoped runtime stays alive

    Requirements:
    - Construction is cheap: the browser context opens lazily on the first step
    - The instance holds no cross-test state: identical outcomes regardless of execution order
  properties:
    "cache_key -> str": |
      The explicit context key, exposed for diagnostics.
  methods:
    "action(text: str)": |
      Execute the action step `text`.

      Delegates to the executor execute with the step type action, the sentence and the test page; failures propagate by kind — `ProductDefectError`, `IncurableStepError`, `LlmUnavailableError` (see `taxonomy`).
    "assertion(text: str)": |
      Execute the assertion step `text` — a legitimately failed expectation surfaces as the product defect failure.

      Delegates to the executor execute with the step type assertion; failures propagate by kind — `ProductDefectError`, `IncurableStepError`, `LlmUnavailableError` (see `taxonomy`).
    "add_hooks(hooks: StepHooks)": |
      Register a callback implementation (see `hooks`); applies to the steps of this test.
    "close()": |
      Close the isolated context of the test; the run-scoped runtime stays alive.

"StepExecutor(cache_key: str, cache: StepCache, generator: StepGenerator, healer: StepHealer, budgets: RunBudgets, reporter: StepReporter)":
  location: executor.py
  annotations: |
    The owner of the step cycle: cache hit — execute; cache miss — generate and store; cached failure — heal.

    `cache_key`: the context key of the owning test object.
    `cache`: the step cache of the test.
    `generator` and `healer`: the engines (see `generation` and `healing` from Imports).
    `budgets`: the run-scoped attempt registry.
    `reporter`: the visibility point.
  methods:
    "execute(step_text: str, step_type: str, page: PageFacade)": |
      Run one step through the full cycle.

      Algorithm:
      1. Report on_step_started with the sentence and the step type
      2. Build the step identity: `normalize_step_text`, then `StepIdentity` with the test cache key and the step type
      3. Load the cached step: a hit executes its code with `run_step_code` against `page`
      4. On a hit execution failure: delegate to the healer heal with the failure description — a healed step is already re-executed and stored by the engine
      5. On a miss: the generator generate — the engine stores the step on success
      6. Append the sentence to the scenario context of the test — the previous step texts feed the next generation
      7. Report on_step_passed; on a failed step report on_step_failed with the sentence, the step type and the short error description, then raise by kind — `ProductDefectError`, `IncurableStepError`, `LlmUnavailableError` (see `taxonomy`)

      Requirements:
      - The scenario context lives per test: steps of different tests never mix
      - A cached step executes with no LLM involvement whatsoever
      - An assertion step surfaces a legitimately failed expectation as the product defect failure

"PrettyplayRuntime(config: Config)":
  location: runtime.py
  annotations: |
    The run-scoped composition root: one instance per process run, owning everything shared across tests.

    `config`: the project settings, loaded once.

    Requirements:
    - Everything expensive is created once per run and shared; nothing test-specific lives here
  properties:
    "config -> Config": |
      The project settings loaded once per run.
    "driver -> DriverSession": |
      The browser session — one browser process for the run, created lazily.
    "budgets -> RunBudgets": |
      The attempt registry — one budget per step for the whole run.
    "provider -> LlmProvider": |
      The LLM provider instance, created lazily on first access via `create_provider`.

      Requirements:
      - Constructing the runtime never requires LLM credentials: a missing key surfaces as the infrastructure failure on the first generation or classification request
  methods:
    "open_page() -> page: PageFacade": |
      Open a fresh isolated browser context and return its page facade — one per test.
    "close()": |
      Stop the browser and the driver; safe when nothing was started.

"get_runtime() -> runtime: PrettyplayRuntime":
  location: runtime.py
  annotations: |
    Return the process-wide runtime: the first call loads the configuration via `load_config` and constructs `PrettyplayRuntime`; every later call returns the same instance.

    `runtime`: the shared runtime.

    Requirements:
    - One instance per process for the whole run
    - Repeated calls are cheap

---

Author: Goga
CreatedAt: 07/09/26
Description: |
  The facade of prettyplay: the per-test scenario object, the step cycle executor and the run-scoped composition root.
```
#### .usages file: `prettyplay/.usages/steps.md`
````md
# Writing steps

Domain: authoring UI tests as plain sentences. Audience: engineers writing tests and integrators wiring the library into a test framework.

## A test as a scenario

```python
from prettyplay import PrettyTest


def test_login():
    t = PrettyTest("login-flow")
    t.action("открыть страницу логина")
    t.action("ввести логин и пароль")
    t.action("нажать «Войти»")
    t.assertion("появилась надпись «Добро пожаловать»")
    t.close()
```

Or with the context manager:

```python
with PrettyTest("login-flow") as t:
    t.action("открыть страницу логина")
```

## Step kinds

- action(text) — performs what the sentence says
- assertion(text) — verifies what the sentence says; a legitimately failed expectation fails the test as a product defect

## Addressing

The constructor arguments form the cache address: cache_key (mandatory) and cache_path (optional subdirectory). Equal cache keys in the shared root reuse one cached step across tests; a different language, step type or key is a different step.

## What you see

Step sentences go to the logger prettyplay at info level — the suite output reads as a plain-language scenario. Healing, cache writes and skipped writes are reported loudly through the same logger.

## Limitations

Step sentences land in the repository cache, the logs and the LLM requests: never put secrets or personal data into a step.
````
#### .usages file: `prettyplay/.usages/lifecycle.md`
````md
# Run lifecycle

Domain: how a run is composed — runtime, contexts, hooks, failures. Audience: integrators wiring the library into a runner and CI.

## Composition

One process-wide runtime per run: the configuration, the browser process, the LLM provider and the attempt budgets are created once and shared by every test. Each PrettyTest opens its own isolated browser context and closes it on close(). Tests normally never touch the runtime directly — constructing PrettyTest is enough.

## Wiring into a framework

The library is framework-agnostic: no plugins, no base classes. Construct the object in your test, call the step methods, let failures propagate — the runner counts them as ordinary test failures. A few lines of glue are enough; the suite runs by the standard runner command.

## Hooks

Implement the StepHooks callback contract and register the implementation with add_hooks before the first step — step, generation, healing and cache events reach the handler synchronously.

## Failures

Three kinds reach the runner:

| Kind | Meaning | Reaction |
|---|---|---|
| ProductDefectError | a real regression | treat as a bug — this failure is the value of the suite |
| IncurableStepError | the step cannot be generated or healed | follow the carried recommendation |
| LlmUnavailableError | the LLM is down | only generation and healing are blocked; cached steps keep running |

## Team workflow

Generate locally where the LLM is reachable, commit the cache directory, run CI fully from the cache with no LLM keys.
````

## Dependency Map

```
                         ЛИСТЬЯ (0 зависимостей)
         ┌───────────────┬────────────────┬───────────────────┐
     prettyplay/config  prettyplay/reporting  prettyplay/failures
         │                   │                    │
         │ (Config)          │ (StepReporter)     │ (LlmUnavailableError)
         ▼                   ▼                    ▼
  ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
  │ driver        │   │ cache         │   │ llm           │
  │ (Config)      │   │ (Config,      │   │ (Config,      │
  │               │   │  StepReporter)│   │  LlmUnavailableError)
  └───────┬───────┘   └───────┬───────┘   └───────┬───────┘
          │                   │                   │
          └─────────┬─────────┴─────────┬─────────┘
                    ▼                   ▼
              ┌─────────────────────────────┐
              │ engine                      │
              │ (LlmProvider,               │
              │  FailureClassification;     │
              │  StepCache, StepIdentity,   │
              │  CachedStep, RunBudgets;    │
              │  PageFacade; StepReporter;  │
              │  таксономия; Config)        │
              └──────────────┬──────────────┘
                             ▼
                    ┌─────────────────┐
                    │ prettyplay      │  КОРЕНЬ (фасад)
                    │ (все 7 клеток + │
                    │  usages: hooks, │
                    │  taxonomy,      │
                    │  generation,    │
                    │  healing)       │
                    └─────────────────┘
```

Циклов нет; порядок реализации: config, reporting, failures → driver, cache, llm → engine → prettyplay.

### Artifact List

| Artifact | Path |
|---|---|
| CODEMANIFEST | prettyplay/CODEMANIFEST |
| CODEMANIFEST | prettyplay/config/CODEMANIFEST |
| CODEMANIFEST | prettyplay/reporting/CODEMANIFEST |
| CODEMANIFEST | prettyplay/failures/CODEMANIFEST |
| CODEMANIFEST | prettyplay/driver/CODEMANIFEST |
| CODEMANIFEST | prettyplay/cache/CODEMANIFEST |
| CODEMANIFEST | prettyplay/llm/CODEMANIFEST |
| CODEMANIFEST | prettyplay/engine/CODEMANIFEST |
| Usage-файл | prettyplay/.usages/steps.md |
| Usage-файл | prettyplay/.usages/lifecycle.md |
| Usage-файл | prettyplay/config/.usages/configuration.md |
| Usage-файл | prettyplay/reporting/.usages/hooks.md |
| Usage-файл | prettyplay/failures/.usages/taxonomy.md |
| Usage-файл | prettyplay/driver/.usages/facade.md |
| Usage-файл | prettyplay/cache/.usages/addressing.md |
| Usage-файл | prettyplay/cache/.usages/storage.md |
| Usage-файл | prettyplay/cache/.usages/budgets.md |
| Usage-файл | prettyplay/llm/.usages/providers.md |
| Usage-файл | prettyplay/llm/.usages/classification.md |
| Usage-файл | prettyplay/engine/.usages/generation.md |
| Usage-файл | prettyplay/engine/.usages/healing.md |

Итого: 8 CODEMANIFEST + 13 usage-файлов.

## Verification Checklist

После реализации каждого артефакта:

- [ ] `goga lint` — синтаксис CODEMANIFEST валиден (по всем 8 клеткам)
- [ ] `python -c "from prettyplay import PrettyTest"` — facade check корня
- [ ] По каждой клетке: все Imports разрешаются (типы существуют в клетках-провайдерах), все usages-ключи из аннотаций объявлены в Usages/Imports
- [ ] config: env-оверрайд для каждого поля; невалидные значения падают громко; tomli на Python 3.10
- [ ] reporting: события хуков = имена методов StepHooks; хук с исключением не роняет прогон
- [ ] failures: три ошибки — мутации PrettyplayError (::); LlmUnavailableError не возникает на кэш-пути
- [ ] driver: один браузер на прогон, изолированный контекст на тест; фасад не exposes сырые объекты Playwright; auto-wait без fixed delays
- [ ] cache: «Нажать Войти» ≡ «нажать  войти »; одинаковый тройной ключ → один файл; os.replace атомарен; Windows retry→skip громко; read-only прогон корректен
- [ ] llm: паритет операций openai/anthropic; prompt передаётся движком verbatim; ошибки SDK → LlmUnavailableError
- [ ] engine: бюджеты 3/2 общие на шаг на прогон (не сбрасываются между тестами); анти-маскировка (product_defect → падение); сгенерированный код только через фасад
- [ ] prettyplay: get_runtime — процессный синглтон, ленивый provider (без ключей рантайм стартует); изоляция контекстов; порядок тестов не влияет на исходы
- [ ] Тесты зеркалят структуру (conventions); ruff line 120 / complexity 10; зависимости с минимальными версиями в pyproject.toml
