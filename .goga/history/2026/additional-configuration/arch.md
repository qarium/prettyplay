# Architecture Plan — additional-configuration

**Topic:** `additional-configuration` — расширение конфигурации prettyplay (per-test рантайм, PrettyConfig со слиянием, инструкции генерации, универсальные локаторы, remote-браузер)
**Plan path:** `.goga/history/2026/additional-configuration/arch.md`
**Base:** 5 ADR `.goga/history/2026/additional-configuration/adr.md` (принят 09.09.2026)

Все клетки — **модификация существующих** (modified). Новых клеток нет. Клетки `prettyplay/failures` и `prettyplay/reporting` не затрагиваются.

---

## Implementation Order

| # | Cell | Обоснование порядка |
|---|---|---|
| 1 | `prettyplay/config` | Лист среди модифицируемых: зависит только от failures (не меняется); поставляет `Config`/`PrettyConfig`/`load_config` всем остальным |
| 2 | `prettyplay/cache` | Зависит от config (готов) и reporting (не меняется); независимо от driver/llm |
| 3 | `prettyplay/llm` | Зависит от config (готов) и failures (не меняется); независимо от cache/driver |
| 4 | `prettyplay/driver` | Зависит от config (готов); независимо от cache/llm |
| 5 | `prettyplay/engine` | Зависит от config, driver, cache, llm (все готовы) + failures/reporting |
| 6 | `prettyplay` (корень) | Зависит от всех клеток выше; публикует `PrettyConfig`, собирает per-test рантайм |

---

## Artifacts

### Cell 1: `prettyplay/config` — MODIFIED

**Дельта:** `Config` — сигнатура +2 поля (`generation_prompt`, `browser_endpoint`), +2 properties, валидация ws/wss, «per run»→«per test» в описаниях попыток; `load_config` — +параметр `overrides`, +шаги слияния 6–8; глобальная аннотация +строка layered resolution; Description футера дополнен.

**CODEMANIFEST** (`prettyplay/config/CODEMANIFEST`), полное содержимое:

```yaml
Imports:
  - Types:
      - PrettyplayError
    Usages:
      - taxonomy
    From: prettyplay/failures

Usages:
  conventions: .goga/usages/conventions.md
  pydantic: .goga/usages/cooks/pydantic.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `pydantic` for data models and TOML loading.
  Use `taxonomy` from Imports for the failure base the configuration error joins.

  All data models — pydantic v2, kw_only=True, empty defaults (None only for explicit absence).
  Naming: PascalCase for classes; snake_case for functions, methods, properties.
  Type hints mandatory; no *args/**kwargs; generics parameterized.
  A validation failure never surfaces as a raw pydantic error: the loader wraps it into the loud actionable `ConfigurationError`.
  Layered resolution: a value passed programmatically wins over the pyproject+env layer only when explicitly set; empty string means unset for string fields. One model — one place of validation — file and programmatic values validate identically. `Config` is publicly known as PrettyConfig.

---

"PrettyplayError::ConfigurationError(message: str)":
  location: loader.py
  annotations: |
    An invalid prettyplay configuration: the loaded [tool.prettyplay] section failed validation.

    `message`: the rendered actionable text — one line per invalid setting: the setting name, the received value, the allowed values or range.

    Requirements:
    - Raised by `load_config` with the original pydantic ValidationError chained
    - Catchable with the single library except clause: derives from `PrettyplayError` (see `taxonomy` from Imports)
    - Never carries a verdict: a configuration failure is not a step failure
  properties:
    "message -> str": |
      The rendered actionable validation text.

"Config(provider: str, browser: str, model: str, generation_model: str, classification_model: str, base_url: str, cache_root: str, generation_prompt: str, browser_endpoint: str, generation_attempts: int, healing_attempts: int, send_screenshots: bool, headless: bool)":
  location: models.py
  annotations: |
    Validated project settings — the single source of the immutable configuration part.

    `provider`: the LLM provider of the {openai, anthropic} set; default openai.
    `browser`: browser of the {chromium, firefox, webkit, chrome, msedge} set; chrome and msedge launch the locally installed browser through the driver channel mechanism; default chromium.
    `model`: main LLM model name.
    `generation_model`: optional generation override; empty — fallback to `model`.
    `classification_model`: optional classification override; empty — fallback to `model`.
    `base_url`: optional custom LLM API endpoint.
    `cache_root`: cache root; empty — default <repo root>/.prettyplay/cache/ resolved by `load_config`.
    `generation_prompt`: user instructions for generation requests; non-empty — a separate USER INSTRUCTIONS block in generation and regeneration requests; empty — no block; default empty.
    `browser_endpoint`: ws endpoint of a remote browser; empty — local launch; default empty.
    `generation_attempts`: generation attempt budget per step per test; default 3.
    `healing_attempts`: healing attempt budget per step per test; default 2.
    `send_screenshots`: optional screenshot input to the LLM; default False.
    `headless`: run the browser without a visible window of a local launch; default True.

    Requirements:
    - kw_only construction; every field has an empty default
    - provider validated against {openai, anthropic}; browser against the five-value set; invalid value — loud actionable error
    - attempts are positive integers
    - a non-empty browser_endpoint is a valid ws/wss URL — otherwise a loud actionable error

    Constraints:
    - No secret values in fields: LLM API keys are never stored in the config; keys come only from environment variables
  properties:
    "provider -> str": |
      The LLM provider setting: openai or anthropic.
    "browser -> str": |
      The browser setting of the {chromium, firefox, webkit, chrome, msedge} set.
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
    "generation_prompt -> str": |
      The user instructions for generation requests; empty means no instructions block.
    "browser_endpoint -> str": |
      The ws endpoint of a remote browser; empty means the local launch.
    "generation_attempts -> int": |
      The generation attempt budget per step per test.
    "healing_attempts -> int": |
      The healing attempt budget per step per test.
    "send_screenshots -> bool": |
      Whether screenshots are attached to LLM requests.
    "headless -> bool": |
      Whether the browser runs without a visible window of a local launch; ignored on a remote connect.
    "effective_generation_model -> str": |
      generation_model when non-empty, otherwise model.
    "effective_classification_model -> str": |
      classification_model when non-empty, otherwise model.

"load_config(pyproject_path: str | None, overrides: Config | None) -> config: Config":
  location: loader.py
  annotations: |
    Load project configuration from pyproject.toml with environment overrides and explicit per-test values.

    `pyproject_path`: optional explicit path to pyproject.toml; empty — the first pyproject.toml found upwards from the current directory.
    `overrides`: the programmatically passed values — the same full model; None — no programmatic layer, the file layer resolves everything.
    `config`: fully resolved and validated `Config`.

    Algorithm:
    1. Resolve the pyproject.toml path: given `pyproject_path` or the first match found upwards from the current directory
    2. Parse TOML: stdlib tomllib on Python 3.11+, tomli on 3.10 (see `pydantic`)
    3. Extract the tool.prettyplay section; a missing section is an empty section
    4. Apply environment overrides: each setting is overridden by PRETTYPLAY_<SETTING_UPPERCASE> when the variable is set; the browser override is PRETTYPLAY_BROWSER_NAME, the headless override is PRETTYPLAY_BROWSER_HEADLESS
    5. Construct `Config`; on a validation failure render the actionable text — one line per invalid setting: the setting name, the received value, the allowed values — and raise `ConfigurationError` with the original ValidationError chained
    6. `overrides` is None — return the file layer as is
    7. Overlay the explicitly set fields of `overrides` onto the file layer (the model with empty defaults, model_copy — see `pydantic`): a field participates when it was passed at construction and is non-empty for strings; untouched model defaults never overwrite file values
    8. Return the effective `Config`

    Requirements:
    - An env override exists for every setting of `Config` (including PRETTYPLAY_GENERATION_PROMPT and PRETTYPLAY_BROWSER_ENDPOINT)
    - A raw pydantic.ValidationError never leaves the loader
    - The empty cache_root setting is resolved to the absolute default <repo root>/.prettyplay/cache/ at load

    Constraints:
    - Never read or store LLM API keys from any file; keys come only from environment variables
    - Python 3.10 compatibility via the tomli fallback (see `pydantic`)

---

Author: Goga
CreatedAt: 07/09/26
Description: |
  Project settings of prettyplay: the validated [tool.prettyplay] schema with the browser channels, the headless mode, the generation instructions and the remote browser endpoint, and the loader with environment overrides, explicit per-test merging and the actionable configuration error.
```

**.usages** — `prettyplay/config/.usages/configuration.md`, полное содержимое:

```md
# Project configuration

Domain: prettyplay settings. Audience: integrators configuring a test project and CI.

The immutable part of the settings lives in the [tool.prettyplay] section of pyproject.toml. Load it once per test; a test can additionally override specific values programmatically through PrettyConfig.

```toml
[tool.prettyplay]
provider = "openai"
browser = "chromium"
headless = true             # false — run with a visible window
model = "gpt-5"
generation_model = ""      # optional: empty -> model
classification_model = ""  # optional: empty -> model
base_url = ""
cache_root = ""            # empty -> <repo>/.prettyplay/cache/
generation_attempts = 3
healing_attempts = 2
send_screenshots = false
generation_prompt = ""     # user instructions for generation requests; empty -> no instructions block
browser_endpoint = ""      # ws endpoint of a remote browser; empty -> local launch
```

## Environment overrides

Every setting has an override for CI — env variable PRETTYPLAY_<SETTING> in upper case:

| Setting | Env override |
|---|---|
| provider | PRETTYPLAY_PROVIDER |
| browser | PRETTYPLAY_BROWSER_NAME |
| headless | PRETTYPLAY_BROWSER_HEADLESS |
| model | PRETTYPLAY_MODEL |
| generation_model | PRETTYPLAY_GENERATION_MODEL |
| classification_model | PRETTYPLAY_CLASSIFICATION_MODEL |
| base_url | PRETTYPLAY_BASE_URL |
| cache_root | PRETTYPLAY_CACHE_ROOT |
| generation_attempts | PRETTYPLAY_GENERATION_ATTEMPTS |
| healing_attempts | PRETTYPLAY_HEALING_ATTEMPTS |
| send_screenshots | PRETTYPLAY_SEND_SCREENSHOTS |
| generation_prompt | PRETTYPLAY_GENERATION_PROMPT |
| browser_endpoint | PRETTYPLAY_BROWSER_ENDPOINT |

## Per-test overrides — layered merge

PrettyConfig is the public name of the full settings model. A config passed to the test object carries only the explicitly set values; everything else resolves from pyproject+env:

```python
from prettyplay import PrettyTest, PrettyConfig

test = PrettyTest(
    cache_key="login-flow",
    config=PrettyConfig(
        browser="firefox",
        browser_endpoint="ws://ci-grid:3000/playwright/firefox",
    ),
)
```

- An explicitly set field wins over pyproject+env; a field left at its default (an empty string) falls back to the file layer
- File values you did not touch survive: base_url and model set only in pyproject.toml keep working when a config is passed
- One model — one place of validation: file and programmatic values validate identically

## Browsers

The browser matrix: chromium, firefox, webkit (Playwright-bundled engines) plus chrome and msedge — channels that launch the locally installed browser through the chromium engine. A channel requires the real browser installed on the machine; a missing browser fails loudly with an actionable message.

## Remote execution

A non-empty browser_endpoint switches the test to connecting over the Playwright ws endpoint — a Playwright Server or a hosted browser grid. The endpoint is an address, not a secret: it is valid in the config file; CI rotation goes through the env override. An empty endpoint keeps the local launch; headless does not apply to a connect — window visibility is controlled by the endpoint server.

## Rules

- LLM API keys are never stored in the config file — secrets come only from environment variables: OPENAI_API_KEY for openai, ANTHROPIC_API_KEY for anthropic
- Invalid configuration fails loudly: ConfigurationError names the setting, the received value and the allowed values; the raw pydantic error stays chained for debugging
- The provider set: openai, anthropic
- A non-empty browser_endpoint must be a valid ws/wss URL
- The cache root default: <repo root>/.prettyplay/cache/ — resolved from the located pyproject.toml

## Loading

```python
from prettyplay.config import load_config

config = load_config(pyproject_path=None)  # locates pyproject.toml upwards from the current directory
print(config.browser, config.headless, config.generation_attempts)
```
```

---

### Cell 2: `prettyplay/cache` — MODIFIED

**Дельта:** глобальная аннотация — «run-scoped»→«per-test» (одна строка); `RunBudgets` — описание/Requirements на per-test семантику (сигнатура и методы не меняются); Description футера «per-run»→«per-test». Остальные типы — дословно.

**CODEMANIFEST** (`prettyplay/cache/CODEMANIFEST`), полное содержимое:

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
  RunBudgets lives in this cell because its accounting key is `StepIdentity`: per-test attempt accounting stays next to the addressing it is keyed by.

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

"StepCache(config: Config, path: str | None, reporter: StepReporter | None)":
  location: store.py
  annotations: |
    The repository store of cache steps: addressing, atomic writes and the read-only mode.

    `config`: project settings; the cache_root setting is the cache root.
    `path`: the optional subdirectory inside the cache; part of the address — steps of different subdirectories never collide; empty — the shared root, so equal cache keys are reused across tests.
    `reporter`: the visibility point — cache events (saved, skipped) go through it; omitted — the hook-less default reporter, so a missing visibility point never fails a save.
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
    The per-test attempt registry: how many generation and healing attempts each step has left within the test.

    `generation_limit`: the generation attempt budget per step per test.
    `healing_limit`: the healing attempt budget per step per test.

    Requirements:
    - The registry lives for the lifetime of one test, owned by the test's runtime: every test starts with full limits — a step reused across tests gets a fresh budget in each test
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
  The step cache of prettyplay: normalization, deterministic addressing, atomic repository storage and the per-test attempt budgets.
```

**.usages** — `prettyplay/cache/.usages/budgets.md`, полное содержимое:

```md
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

- Budgets are per step per test: every test owns its registry and starts with full limits — a step reused across tests gets a fresh budget in each test (N tests running one step in a process spend N × attempts in total)
- Defaults: 3 generation attempts, 2 healing attempts — configurable in the project settings
- An exhausted budget is the incurable failure, never an infinite loop
- Budgets exist only in the memory of the running process — nothing is persisted
```

---

### Cell 3: `prettyplay/llm` — MODIFIED

**Дельта:** глобальная аннотация +строка паритета инструкций; `LlmProvider.generate_step_code` — +параметр `user_instructions` (вторым) с аннотацией; оба провайдера — Algorithm шаг 1 расширен блоком USER INSTRUCTIONS. `classify_failure`, `create_provider`, `FailureClassification` — дословно.

**CODEMANIFEST** (`prettyplay/llm/CODEMANIFEST`), полное содержимое:

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
  The user instructions input participates in both provider implementations with identical semantics — a parity requirement, not a capability difference.
  API keys come only from environment variables; never log keys or payloads containing secrets.
  One completion request per attempt: attempt budgets are owned by the calling engine, never by a provider.
  Cached step code never depends on the provider: the provider serves generation and classification only.

---

"LlmProvider()":
  location: provider.py
  annotations: |
    The unified LLM port of the library: code generation for a step and failure classification for healing. One contract, two interchangeable implementations selected by configuration.
  methods:
    "generate_step_code(prompt: str, user_instructions: str, step_text: str, previous_steps: list[str], snapshot: str, screenshot: bytes | None, page_api: str, existing_code: str | None, error: str | None) -> code: str": |
      Generate step code of the fixed form.

      `prompt`: the system prompt text supplied by the calling engine — applied verbatim as the system message.
      `user_instructions`: the project's code style instructions supplied by the calling engine from the generation_prompt setting; empty — the request carries no instructions block; non-empty — rendered by the provider implementations verbatim as a separate USER INSTRUCTIONS block of the user content, identically in both.
      `step_text`: the sentence of the step to generate.
      `previous_steps`: the sentences of the previous steps of the test, in execution order — scenario context.
      `snapshot`: the accessibility snapshot of the current page.
      `screenshot`: an optional PNG image of the page; passed only when the project enables screenshots.
      `page_api`: the exact page facade surface listing — the list of calls the model may use.
      `existing_code`: the existing step code that failed; non-empty only on regeneration requests.
      `error`: the failure description of the existing code; non-empty only on regeneration requests.
      `code`: the generated step code of the fixed form, working only through the driver facade; the first markdown-fenced block of the answer is unwrapped — an answer with no closed fence returns verbatim.

      Requirements:
      - A provider service failure (connectivity, timeout, rate limit, authentication) raises `LlmUnavailableError` naming the provider
      - The generated code contains no provider-specific constructs
    "classify_failure(prompt: str, step_text: str, code: str, error: str, snapshot: str, screenshot: bytes | None) -> classification: FailureClassification": |
      Classify a failed cached step.

      `prompt`: the system prompt text supplied by the calling engine — applied verbatim as the system message.
      `step_text`: the sentence of the failed step.
      `code`: the existing step code that failed.
      `error`: the human-readable description of the failure.
      `snapshot`: the accessibility snapshot of the current page.
      `screenshot`: an optional PNG image of the page; passed only when the project enables screenshots.
      `classification`: the `FailureClassification` verdict.

"LlmProvider::OpenAiProvider(config: Config)":
  location: openai_provider.py
  annotations: |
    The openai SDK implementation of `LlmProvider` (see `openai`).

    `config`: project settings; the generation model is the effective_generation_model of `config`, the classification model is the effective_classification_model of `config`; the base_url setting of `config` overrides the endpoint when set.

    Algorithm (both operations):
    1. Build the request: the prompt text as the system message, the user content carrying the inputs — a non-empty user_instructions renders as a separate USER INSTRUCTIONS block placed after the page API block, before the regeneration-only blocks (CODE, ERROR)
    2. Send one completion request via the SDK
    3. Extract the text answer; a generation answer unwraps its first markdown-fenced block — an unfenced answer passes through verbatim
    4. An SDK error maps to `LlmUnavailableError` (see `openai`)

"LlmProvider::AnthropicProvider(config: Config)":
  location: anthropic_provider.py
  annotations: |
    The anthropic SDK implementation of `LlmProvider` (see `anthropic`); full parity with the openai implementation.

    `config`: the same settings semantics as the openai implementation.

    Algorithm (both operations):
    1. Build the request: the prompt text as the system message, the user content carrying the inputs — a non-empty user_instructions renders as a separate USER INSTRUCTIONS block placed after the page API block, before the regeneration-only blocks (CODE, ERROR)
    2. Send one message request via the SDK
    3. Extract the text answer; a generation answer unwraps its first markdown-fenced block — an unfenced answer passes through verbatim
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

Формат блока в пользовательском контенте (общий провайдерам):

```
USER INSTRUCTIONS:
<текст инструкций дословно>
```

Блок добавляется только при непустых инструкциях; порядок блоков контента: STEP → PREVIOUS STEPS → PAGE SNAPSHOT → SCREENSHOT → PAGE API → USER INSTRUCTIONS → CODE → ERROR.

**.usages** — без изменений (`providers.md`, `classification.md` остаются как есть).

---

### Cell 4: `prettyplay/driver` — MODIFIED

**Дельта:** глобальная аннотация — инвариант per-test браузер + строка ветвления запуска; `DriverSession` — описание и Algorithm `open_context` с ветвлением launch/connect (+requirement о connect-ошибке); `PageFacade` — +3 метода локации; Description футера обновлён. `LocatorFacade` — дословно.

**CODEMANIFEST** (`prettyplay/driver/CODEMANIFEST`), полное содержимое:

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
  Use `playwright` for the sync API lifecycle, locators, auto-wait, the accessibility snapshot, browser channels, remote connects and the scroll primitives.

  The driver is Playwright sync-only: the async API is out of scope.
  The whole Playwright session — start, browser, contexts, pages — lives in one dedicated driver thread owned by the library: the sync API parks its private event loop on its starting thread, so the thread executing the steps never holds a running asyncio loop (interactive hosts such as IPython and Jupyter keep working between steps).
  Driver-thread calls are strictly sequential: one facade call runs at a time; concurrent driving is out of scope.
  One browser process per test: the session is owned by the test's runtime — no state is shared between tests through the library.
  The start mode branches on the browser_endpoint setting of `Config`: empty — local launch with headless and the channel for chrome/msedge; set — connect over the Playwright ws endpoint: headless is ignored, channels do not apply, the browser setting selects the engine (see `playwright`).
  All waits go through locators and expectations; fixed delays (time.sleep and similar) are forbidden.
  The facade surface is a backward-compatibility contract: generated step code works only through `PageFacade` and LocatorFacade, so the existing method set must not break across library releases — extend, never rename or remove.

---

"DriverSession(config: Config)":
  location: session.py
  annotations: |
    Lifecycle owner of the Playwright sync driver and the browser process of one test.

    `config`: project settings; the browser setting selects the browser of the {chromium, firefox, webkit, chrome, msedge} set — chrome and msedge launch the locally installed browser through the channel mechanism; headless controls the window visibility of a local launch; browser_endpoint switches the start to a remote connect (see `playwright`).

    Requirements:
    - The Playwright session lives in a dedicated driver thread owned by the session: every Playwright-touching operation of this type runs there, and the calling thread never holds a running asyncio loop after any call
  methods:
    "open_context() -> page: PageFacade": |
      Open a fresh isolated context with one page of this test's browser.

      Algorithm:
      1. Start lazily on the first call: constructing the session starts nothing — start the dedicated driver thread, then start Playwright inside it; an empty browser_endpoint — launch the selected engine locally with headless from the project settings and the channel for the chrome/msedge values; a set browser_endpoint — connect over the Playwright ws endpoint of the selected engine: headless is ignored and channels do not apply; a failed launch or connect stops the started driver and closes the thread, so a retry begins from a clean state
      2. Create a fresh isolated browser context and its page inside the driver thread (see `playwright`)
      3. Wrap the page into `PageFacade` bound to the driver thread and return it

      Requirements:
      - Each result is isolated from every other context
      - A channel launch without the installed browser fails loudly with an actionable message naming the missing browser
      - A failed connect fails loudly with an actionable message naming the endpoint
    "close()": |
      Stop the browser, the Playwright driver and the driver thread; safe to call when nothing was started.

"PageFacade(page: Page, context: BrowserContext)":
  location: page.py
  annotations: |
    The narrow, stable facade of a single test page — the only page API the generated step code may use.
    Wraps one isolated browser context created by `DriverSession`.

    `page`: the wrapped Playwright page object; never exposed through the facade.
    `context`: the isolated browser context owning the page; the boundary the close method closes.

    Requirements:
    - Every Playwright call runs in the driver thread of the owning session: the call blocks until it finishes, strictly one at a time, and the calling thread never adopts the Playwright event loop
    - Locating methods never sleep: waiting is the locator's own auto-wait behavior
    - Scroll methods never sleep: the scrolled state is awaited through locators and expectations
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
    "find_by_attribute(name: str, value: str) -> element: LocatorFacade": |
      Locate one element by the value of the attribute `name` — the intended use is data-* attributes (data-test-id, data-qa and any other data attribute). Auto-waits exactly like the other locating methods.

      `name`: the full attribute name, e.g. data-test-id.
      `value`: the attribute value to match.
    "find_by_css(selector: str) -> element: LocatorFacade": |
      Locate one element by a CSS selector.

      `selector`: a valid CSS selector expression, e.g. form > button.primary.
    "find_by_xpath(xpath: str) -> element: LocatorFacade": |
      Locate one element by an XPath expression.

      `xpath`: a valid XPath expression, e.g. //button[@type='submit'].
    "aria_snapshot() -> snapshot: str": |
      The structured accessibility-tree representation of the page — the primary machine-readable page state (see `playwright`).
    "screenshot() -> image: bytes": |
      A full-page PNG image of the current state.
    "scroll_to_element(element: LocatorFacade)": |
      Scroll the page so `element` enters the viewport — inside its nearest scrollable ancestor when the element lives in a scrollable container (see `playwright`).

      `element`: the located element to bring into view.
    "scroll_down(pixels: int)": |
      Scroll the page down by `pixels`.

      `pixels`: a positive scroll amount in CSS pixels.
    "scroll_up(pixels: int)": |
      Scroll the page up by `pixels`.

      `pixels`: a positive scroll amount in CSS pixels.
    "scroll_to_bottom()": |
      Scroll the page to its end.
    "scroll_to_top()": |
      Scroll the page to its start.
    "scroll_into_view(element: LocatorFacade, container: LocatorFacade)": |
      Bring `element` into the visible area of the specific scrollable `container` — for nested scrollables where the nearest-ancestor behavior of scroll_to_element is not enough (see `playwright`).

      `element`: the located element to bring into view.
      `container`: the located scrollable container, e.g. a carousel.
    "scroll_container_down(container: LocatorFacade, pixels: int)": |
      Scroll the scrollable `container` down by `pixels`.

      `container`: the located scrollable container.
      `pixels`: a positive scroll amount in CSS pixels.
    "scroll_container_up(container: LocatorFacade, pixels: int)": |
      Scroll the scrollable `container` up by `pixels`.

      `container`: the located scrollable container.
      `pixels`: a positive scroll amount in CSS pixels.
    "close()": |
      Close the isolated context of this page; the browser process keeps running.

"LocatorFacade(locator: Locator)":
  location: page.py
  annotations: |
    An auto-waiting handle of one located element — the only element API the generated step code may use.

    `locator`: the wrapped Playwright locator object; never exposed through the facade.

    Requirements:
    - Every action and expectation runs in the driver thread inherited from the page facade that created the handle
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
  The Playwright sync driver of prettyplay: the per-test session with local launches and remote ws connects, and the narrow backward-compatible page facade with universal locators and scroll abilities for generated step code.
```

**.usages** — `prettyplay/driver/.usages/facade.md`, полное содержимое:

```md
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
| page.find_by_attribute(name, value) | element by attribute value — data-* attributes |
| page.find_by_css(selector) | element by CSS selector |
| page.find_by_xpath(xpath) | element by XPath expression |
| page.aria_snapshot() | accessibility-tree page state |
| page.screenshot() | full-page PNG bytes |
| page.url | current URL |
| page.scroll_to_element(element) | bring an element into the viewport (works inside scrollable ancestors) |
| page.scroll_down(pixels) | scroll the page down by an amount |
| page.scroll_up(pixels) | scroll the page up by an amount |
| page.scroll_to_bottom() | scroll to the end of the page |
| page.scroll_to_top() | scroll to the start of the page |
| page.scroll_into_view(element, container) | bring an element into view inside a specific scrollable container |
| page.scroll_container_down(container, pixels) | scroll a scrollable container down by an amount |
| page.scroll_container_up(container, pixels) | scroll a scrollable container up by an amount |
| element.click() | click with auto-wait |
| element.fill(value) | set input text |
| element.select_option(value) | choose an option |
| element.expect_visible() | assert visible |
| element.expect_text(text) | assert text |
| element.expect_enabled() | assert enabled |

## Example

```python
page.open("https://example.com/login")
page.find_by_label("Username").fill("user")
page.find_by_label("Password").fill("secret")
page.find_by_role("button", name="Sign in").click()
page.find_by_text("Welcome back").expect_visible()

# locating by data attributes, CSS and XPath
page.find_by_attribute("data-test-id", "submit-button").click()
page.find_by_css("form > button.primary").expect_enabled()
page.find_by_xpath("//button[@type='submit']").expect_visible()

# scroll scenarios
page.scroll_down(600)
page.find_by_text("Footer").expect_visible()

cards = page.find_by_role("list", name="Recommendations")
page.scroll_container_down(cards, 400)
page.find_by_text("Fifth card").expect_visible()

snapshot = page.aria_snapshot()
```

## Rules

- One browser process per test: each test owns its browser through its runtime; contexts stay isolated
- Every call executes in the library's driver thread and returns when done: driving is strictly sequential, and the calling thread never adopts the Playwright event loop — hand-written step code stays safe in interactive hosts (IPython, Jupyter)
- Auto-wait everywhere: no time.sleep, no fixed delays in step code — including around scrolls: the scrolled state is awaited through locators and expectations
- Never put secrets into step actions — step texts and code land in the repository cache
```

---

### Cell 5: `prettyplay/engine` — MODIFIED

**Дельта:** Usages-ключ `generation_prompt` → **`system_prompt`** (содержимое: +строка входа USER INSTRUCTIONS, +правило Rules про attribute/CSS/XPath); аннотации — переименование ссылок, +строка про границы инструкций, «per run»→«per test»; `StepGenerator` — generate шаг 3 и regenerate шаг 1 несут инструкции, `config`-описание дополняет «the generation instructions», `budgets` — «per-test»; `StepHealer` — одна строка (`budgets` — «per-test»); практика `healing.md` — одна строка (run-scoped → per-test registry). `run_step_code`, `classify_step_failure` — дословно.

**CODEMANIFEST** (`prettyplay/engine/CODEMANIFEST`), полное содержимое:

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
      - FailureVerdict
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
  system_prompt: |
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
  classification_prompt: |
    You classify a failure of a web UI test step.

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
  Use `system_prompt` as the system prompt of every code generation request.
  Use `classification_prompt` as the system prompt of every failure classification request.
  Use `facade` from Imports as the single source of the page API surface for generation requests.

  The fixed form of step code: one function receiving exactly one argument — the `PageFacade` of the test; the function body works only through `PageFacade` and the LocatorFacade element API.
  Every attempt — generation or healing — consumes the shared per-step budget of the test; exhaustion is the incurable failure, never an infinite loop.
  Healing never masks a product defect: a classified product_defect fails the test loudly; a healed step is reported loudly and written back to the cache.
  Every terminal failure carries a verdict — a `FailureVerdict` of category, explanation, recommendation — fully present in the exception message, the verdict hook event and the log; an unavailable LLM skips the verdict quietly with a WARNING, the failure itself is never delayed or distorted — the quiet skip applies to verdicts enriching an already-decided failure; the classification driving the healing decision surfaces as the infrastructure failure.
  A failed check of a candidate stops the generation retries: a check that executed and did not hold is classified, not regenerated.
  The page API surface listing sent to the provider mirrors `facade` from Imports exactly — the listing and the practice change together.
  The user instructions of the project settings — the generation_prompt field of `Config` — reach generation and regeneration requests only; classification requests never carry them; the instructions take no part in the step address: a cached step never regenerates because the instructions changed.

---

"StepGenerator(config: Config, provider: LlmProvider, cache: StepCache, budgets: RunBudgets, reporter: StepReporter)":
  location: generator.py
  annotations: |
    The generation engine: produce working step code for an unknown step, executing candidates against the live page.

    `config`: project settings — the screenshot flag and the generation instructions.
    `provider`: the LLM port.
    `cache`: the step cache — a generated step is stored on success.
    `budgets`: the per-test attempt registry.
    `reporter`: the visibility point.
  methods:
    "generate(identity: StepIdentity, step_text: str, previous_steps: list[str], page: PageFacade) -> step: CachedStep": |
      Generate and store a new step.

      Algorithm:
      1. Ask the budgets registry try_generation for the step identity; a refused attempt is the incurable failure
      2. Collect the request inputs: the page accessibility snapshot, the step sentence, `previous_steps`, and the page API surface from `facade`; add the page screenshot when the project settings enable screenshots
      3. Request step code from the provider port generate_step_code passing `system_prompt` as the system prompt, the page API surface listing taken from `facade`, and the user instructions — the effective config generation_prompt — when non-empty
      4. Execute the candidate with `run_step_code` against `page`
      5. On success: build `CachedStep`, save it to the cache, return it
      6. On a candidate failure that is an AssertionError — a check that executed and did not hold: stop the retries immediately and classify via `classify_step_failure`; a product_defect verdict raises `ProductDefectError` carrying the verdict, any other verdict raises `IncurableStepError` carrying it — the reason names the failed candidate check; provider unavailability at this classification is skipped quietly with a WARNING — `IncurableStepError` is raised without a verdict, the reason naming the failed candidate check (the failed check is the primary signal, the verdict is enrichment)
      7. On any other candidate failure: repeat from step 1 with the fresh failure description and the fresh snapshot, while attempts remain
      8. On budget exhaustion: classify the last candidate via `classify_step_failure` and raise `IncurableStepError` carrying the verdict — the reason names the exhausted pool and the last candidate failure; provider unavailability at this classification is skipped quietly with a WARNING, the failure raises without a verdict
      9. Report on_generation_started for every attempt

      Requirements:
      - Every generation request carries the exact page API surface taken from `facade` from Imports: the model always sees the precise list of calls it may use
      - Provider unavailability of a generation request surfaces as `LlmUnavailableError` immediately — no retry on it
      - Provider unavailability of a failed-check classification is skipped quietly with a WARNING: the failure raises without a verdict — the failed check itself is the primary signal
      - Exactly one failed check stops the retries: the attempt budget is never spent on a legitimately failing assertion
      - A verdict requested on this path fully reaches the raised error
    "regenerate(identity: StepIdentity, step_text: str, previous_steps: list[str], page: PageFacade, existing_code: str, error: str) -> step: CachedStep": |
      Regenerate a failed step for healing.

      Algorithm:
      1. The same loop as the generate method with three additions: every provider request carries `existing_code` and `error` and the user instructions — the effective config generation_prompt — when non-empty; attempts consume the healing budget via try_healing; a budget exhaustion raises `IncurableStepError` without classification — the healer attaches the verdict of its own classification, no extra LLM request is made (the failed-check classification of the generate loop applies on both pools)

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

"classify_step_failure(config: Config, provider: LlmProvider, step_text: str, code: str, error: str, page: PageFacade) -> classification: FailureClassification":
  location: classification.py
  annotations: |
    Classify a step failure: collect the page state and ask the provider — the single classification call for both engines.

    `config`: project settings — the screenshot flag.
    `provider`: the LLM port.
    `step_text`: the sentence of the failed step.
    `code`: the step code that failed.
    `error`: the human-readable failure description.
    `page`: the page facade of the current test.
    `classification`: the `FailureClassification` verdict.

    Algorithm:
    1. Collect the classification inputs: the step sentence, the failed code, the `error` text, the fresh page snapshot — plus the screenshot when enabled
    2. Ask the provider port classify_failure passing `classification_prompt` as the system prompt
    3. Return the verdict

    Constraints:
    - Provider unavailability propagates to the caller: this routine never swallows it — the calling path decides whether it is a terminal infrastructure failure or a quiet verdict skip

"StepHealer(config: Config, provider: LlmProvider, generator: StepGenerator, cache: StepCache, budgets: RunBudgets, reporter: StepReporter)":
  location: healer.py
  annotations: |
    The healing engine: classify a failed cached step, regenerate rot, never mask a defect.

    `config`: project settings — the screenshot flag.
    `provider`: the LLM port for classification.
    `generator`: the regeneration engine.
    `cache`: the step cache for the healed write-back.
    `budgets`: the per-test attempt registry.
    `reporter`: the visibility point.
  methods:
    "heal(step: CachedStep, error: str, previous_steps: list[str], page: PageFacade) -> step: CachedStep": |
      Classify and heal a failed cached step.

      `previous_steps`: the sentences of the previous steps of the test, in execution order — scenario context for regeneration.

      Algorithm:
      1. Classify the failure via `classify_step_failure` — the verdict is a `FailureClassification`
      2. Report on_healing_started with the category
      3. product_defect: raise `ProductDefectError` carrying the verdict built from the classification — the message states what was expected against what was observed; the recommendation reaches the error through the verdict
      4. incurable: raise `IncurableStepError` carrying the verdict; the reason names the classification explanation of incurability
      5. rot: regenerate via the generator regenerate — its loop executes the candidate and stores the healed step on success; report on_healed with the explanation of what was rot and what changed, return the healed step
      6. A regeneration budget exhaustion inside step 5 surfaces as `IncurableStepError` carrying the verdict of the step 1 classification — the reason names the exhausted pool; no extra LLM request is made
      7. Provider unavailability of the classification surfaces as `LlmUnavailableError` — an explicit infrastructure failure

      Requirements:
      - Anti-masking: healing may only turn a rot-failed step green; a classified product defect always fails the test
      - The healed code replaces the cached code only after a successful execution
      - Every verdict produced on the paths of this method fully reaches the raised error

---

Author: Goga
CreatedAt: 07/09/26
Description: |
  The agent engine of prettyplay: step code generation with execution in the loop and failed-check classification, the fixed-form execution routine, the shared classification call, and healing with anti-masking and verdicts on terminal failures.
```

**.usages** — `prettyplay/engine/.usages/healing.md`, дельта (одна строка в Rules):

```md
- Generation and healing attempts live in one per-test registry — owned by the runtime of the test — with separate per-step limits (default 3 and 2)
```

(было: «…in one run-scoped registry…»; остальной файл без изменений)

**.usages** — `prettyplay/engine/.usages/generation.md`, полное содержимое:

```md
# Step generation

Domain: generating executable code for an unknown step. Audience: library internals and engineers debugging a first run.

## Generate a step

```python
step = generator.generate(
    identity=identity,
    step_text="click the «Sign in» button",
    previous_steps=["open the login page", "enter the login and password"],
    page=page,
)
```

- The loop: request code → execute against the live page → on failure re-request with the fresh error and snapshot
- A non-empty generation_prompt setting adds a USER INSTRUCTIONS block to every generation and regeneration request — the project's code style guidance (e.g. prefer data-test-id attributes); classification requests never carry it; changing the instructions never invalidates the cache — cached steps run as stored
- A failed check of a candidate (an assertion that executed and did not hold) stops the retries at once: the failure goes to classification — product_defect raises ProductDefectError with the verdict, anything else raises IncurableStepError with it; when the LLM is unavailable at this classification the verdict is skipped quietly (WARNING in the log) and IncurableStepError raises without it; one failed check is spent, never the whole budget
- Other candidate failures (element not found, timeouts) retry with the fresh error and snapshot
- Attempts are budgeted per step per test (default 3); exhaustion raises IncurableStepError carrying the classification verdict of the last candidate — when the LLM is unavailable the verdict is skipped quietly (WARNING in the log) and the failure raises without it
- A success stores the step in the cache and returns it
- Provider unavailability of a generation request raises LlmUnavailableError immediately — no retry on it

## Classification call

Both engines classify through one routine:

```python
from prettyplay.engine import classify_step_failure

classification = classify_step_failure(
    config=config, provider=provider,
    step_text="click the «Sign in» button", code=step_code,
    error="element not found: button «Sign in»", page=page,
)
```

The routine collects the fresh page snapshot (plus the screenshot when enabled) and calls the provider with the engine classification prompt. Provider unavailability propagates: the calling path decides whether it is a terminal infrastructure failure or a quiet verdict skip.

## The fixed form

Generated code is one function receiving exactly one argument — the page facade — and working only through the facade surface: page.find_by_role(...).click(), page.find_by_attribute("data-test-id", "submit").click(), page.find_by_css("form > button.primary"), page.find_by_xpath("//button[@type='submit']"), element.expect_visible(), page.scroll_down(600) and alike. No provider constructs, no direct driver imports, no fixed delays.
```

---

### Cell 6: `prettyplay` (корень) — MODIFIED

**Дельта:** Imports — `Config AS PrettyConfig`; глобальная аннотация +строка про re-export; Body — +embedding `->PrettyConfig: {}`, `PrettyTest` (+`config`, собственный рантайм, новая семантика close), `PrettyplayRuntime` (per-test, atexit), `StepExecutor` (аннотация budgets), **−`get_runtime`**; Description футера «run-scoped»→«per-test».

**CODEMANIFEST** (`prettyplay/CODEMANIFEST`), полное содержимое:

```yaml
Imports:
  - Types:
      - Config AS PrettyConfig
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
      - PrettyplayError
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
  `PrettyConfig` — the public name of the settings model — is re-exported by this facade (see the embedding).

---

->PrettyConfig: {}

"PrettyTest(cache_key: str, cache_path: str | None, config: PrettyConfig | None)":
  location: scenario.py
  annotations: |
    The main integrator object — one instance per test. Owns the cache addressing and the isolated browser context of the test; the step cycle is delegated to `StepExecutor`.

    `cache_key`: the mandatory explicit context key — part of the step address; equal keys in the shared root reuse steps across tests.
    `cache_path`: the optional cache subdirectory — part of the address; steps never leak across subdirectories.
    `config`: per-test overrides — the same full model; explicitly set values win, unset/empty fields resolve from pyproject+env; None — everything resolves from pyproject+env, as before.

    Supports the context manager protocol: exit closes the test.

    Algorithm:
    1. Resolve the effective config: `load_config` with overrides = config
    2. Build the own `PrettyplayRuntime` with the effective config — no process-wide singleton exists
    3. Construct the per-test reporter: `StepReporter` with an empty hooks list; add_hooks appends to it
    4. Construct the per-test `StepCache` from the runtime config, `cache_path` and the reporter
    5. Construct `StepGenerator` and `StepHealer` from the runtime config, provider and budgets, the step cache and the reporter
    6. Construct `StepExecutor` with `cache_key`, the cache, the engines, the runtime budgets and the reporter
    7. The test page opens lazily on the first step via the runtime open_page

    Requirements:
    - Construction is cheap: the browser starts lazily on the first step; no LLM credentials are required to construct
    - The instance holds no cross-test state: identical outcomes regardless of execution order
  properties:
    "cache_key -> str": |
      The explicit context key, exposed for diagnostics.
  methods:
    "action(text: str)": |
      Execute the action step `text`.

      Delegates to the executor execute with the step type action, the sentence and the test page; failures propagate by kind — `ProductDefectError`, `IncurableStepError`, `LlmUnavailableError` (see `taxonomy`).
      A `PrettyplayError` leaving this method carries its traceback folded to the library boundary: internal library frames — engine, healing, provider — do not appear in what the runner shows.
    "assertion(text: str)": |
      Execute the assertion step `text` — a legitimately failed expectation surfaces as the product defect failure.

      Delegates to the executor execute with the step type assertion; failures propagate by kind — `ProductDefectError`, `IncurableStepError`, `LlmUnavailableError` (see `taxonomy`).
      A `PrettyplayError` leaving this method carries its traceback folded to the library boundary: internal library frames — engine, healing, provider — do not appear in what the runner shows.
    "get_screenshot() -> image: bytes": |
      Return a full-page PNG image of the current state of the test page — uniform with the facade screenshot.

      `image`: the full-page PNG bytes.

      Requirements:
      - Requires an opened test page: calling before the first step raises a loud actionable `PrettyplayError` telling to run a step first
      - No screenshot is taken automatically on step failures: the decision to capture belongs to the test author
    "save_screenshot(filepath: str)": |
      Write a full-page PNG image of the current state of the test page to `filepath`.

      `filepath`: the explicit destination path chosen by the user — any directory, any filename; no default directory is imposed.

      Requirements:
      - Requires an opened test page: calling before the first step raises a loud actionable `PrettyplayError` telling to run a step first
      - A write failure — e.g. a missing parent directory — surfaces as a loud actionable `PrettyplayError`; nothing is created silently
    "add_hooks(hooks: StepHooks)": |
      Register a callback implementation (see `hooks`); applies to the steps of this test.
    "close()": |
      Close the test page context and stop the whole runtime of this test — the browser process, the Playwright driver and the driver thread; idempotent; the context manager exit does the same.

"StepExecutor(cache_key: str, cache: StepCache, generator: StepGenerator, healer: StepHealer, budgets: RunBudgets, reporter: StepReporter)":
  location: executor.py
  annotations: |
    The owner of the step cycle: cache hit — execute; cache miss — generate and store; cached failure — heal.

    `cache_key`: the context key of the owning test object.
    `cache`: the step cache of the test.
    `generator` and `healer`: the engines (see `generation` and `healing` from Imports).
    `budgets`: the per-test attempt registry.
    `reporter`: the visibility point.
  methods:
    "execute(step_text: str, step_type: str, page: PageFacade)": |
      Run one step through the full cycle.

      Algorithm:
      1. Report on_step_started with the sentence and the step type
      2. Build the step identity: `normalize_step_text`, then `StepIdentity` with the test cache key and the step type
      3. Load the cached step: a hit executes its code with `run_step_code` against `page`
      4. On a hit execution failure: delegate to the healer heal with the failure description and the scenario context — a healed step is already re-executed and stored by the engine
      5. On a miss: the generator generate — the engine stores the step on success
      6. Append the sentence to the scenario context of the test — the previous step texts feed the next generation
      7. Report on_step_passed; on a failed step report on_step_failed with the sentence, the step type and the short error description — then, when the terminal failure carries a verdict, report on_step_verdict with the sentence and the three verdict fields; finally raise by kind — `ProductDefectError`, `IncurableStepError`, `LlmUnavailableError` (see `taxonomy`)

      Requirements:
      - The scenario context lives per test: steps of different tests never mix
      - A cached step executes with no LLM involvement whatsoever
      - An assertion step surfaces a legitimately failed expectation as the product defect failure

"PrettyplayRuntime(config: PrettyConfig)":
  location: runtime.py
  annotations: |
    The per-test composition root: one instance per test, owning everything the steps of that test share.

    `config`: the effective settings of the test.

    Requirements:
    - One instance serves exactly one test: construction starts nothing expensive — the browser, the provider and the budgets belong to this test alone
  properties:
    "config -> PrettyConfig": |
      The effective settings of the test.
    "driver -> DriverSession": |
      The browser process of this test, created lazily.
    "budgets -> RunBudgets": |
      The attempt registry of the test — one budget per step within the test.
    "provider -> LlmProvider": |
      The LLM provider instance, created lazily on first access via `create_provider`.

      Requirements:
      - Constructing the runtime never requires LLM credentials: a missing key surfaces as the infrastructure failure on the first generation or classification request
  methods:
    "open_page() -> page: PageFacade": |
      Open a fresh isolated browser context and return its page facade — one per test.
    "close()": |
      Stop the browser, the Playwright driver and the driver thread of this test; safe when nothing was started.

      Requirements:
      - Every instance registers its own close with atexit, so the driver stops synchronously before the process exits even when no test closes the runtime explicitly; manual calls stay valid and idempotent

---

Author: Goga
CreatedAt: 07/09/26
Description: |
  The facade of prettyplay: the per-test scenario object with screenshot abilities, the step cycle executor with verdict reporting, and the per-test composition root.
```

**.usages** — `prettyplay/.usages/lifecycle.md`, полное содержимое:

```md
# Run lifecycle

Domain: how a run is composed — runtimes, contexts, hooks, failures. Audience: integrators wiring the library into a runner and CI.

## Composition

One runtime per test: each PrettyTest builds its own runtime — its own configuration, browser process, LLM provider and attempt budgets. Tests never share browser state or budgets through the library; outcomes do not depend on the execution order. Constructing a test is cheap and requires no LLM credentials: the browser starts lazily on the first step. A config passed to the test overrides only the explicitly set values — everything else resolves from pyproject+env. When the process exits, every runtime stops its browser and driver synchronously before returning control to the terminal — scripts never leave browser processes behind.

## Wiring into a framework

The library is framework-agnostic: no plugins, no base classes. Construct the object in your test, call the step methods, let failures propagate — the runner counts them as ordinary test failures. A few lines of glue are enough; the suite runs by the standard runner command.

## Hooks

Implement the StepHooks callback contract and register the implementation with add_hooks before the first step — step, generation, healing, cache and verdict events reach the handler synchronously. on_step_verdict fires after on_step_failed whenever the terminal failure carries an LLM verdict.

## Failures

Four kinds reach the runner:

| Kind | Meaning | Reaction |
|---|---|---|
| ProductDefectError | a real regression — also an AssertionError: runners show a failure, not an error; the traceback is folded to the library boundary | treat as a bug — this failure is the value of the suite |
| IncurableStepError | the step cannot be generated or healed | follow the carried recommendation |
| LlmUnavailableError | the LLM is down | only generation and healing are blocked; cached steps keep running |
| ConfigurationError | the settings are invalid | fix the named setting — the message lists the allowed values |

ProductDefectError and IncurableStepError carry the LLM verdict — category, explanation, recommendation — in the exception message, the on_step_verdict hook event and the log. When the LLM is unavailable the verdict is skipped quietly; the failure itself never waits for it.

## Team workflow

Generate locally where the LLM is reachable, commit the cache directory, run CI fully from the cache with no LLM keys.

## Interactive sessions (IPython, Jupyter)

The Playwright session lives in a background driver thread owned by the library: the thread that executes the steps never holds a running asyncio loop, so interactive hosts that drive their own prompt through asyncio (IPython, Jupyter) keep working after every step — passed or failed.

Each test owns its browser process: it starts on the first step of the test and stops when the test closes. In scripts every runtime stops automatically at process exit through its atexit hook. In an interactive session the process keeps living between cells, so close the test object explicitly when the interactive exploration is over:

```python
from prettyplay import PrettyTest

test = PrettyTest("login-flow")
test.action("open the login page")
test.action("enter the login and password")
test.assertion("the «Welcome back» message appears")
test.close()  # stops this test's browser and driver thread
```

Generation of the step cache remains a batch workflow: prefer a plain script or a pytest run over a REPL when generating many steps.
```

---

## Dependency Map

```
prettyplay/failures (—) ──(PrettyplayError, taxonomy)──────────> prettyplay/config (✚)
prettyplay/reporting (—) ─(StepReporter, hooks)────────────────> prettyplay/cache (✚)
prettyplay/config (✚) ────(Config)────────────────────────────> prettyplay/cache (✚)
prettyplay/config (✚) ────(Config)────────────────────────────> prettyplay/llm (✚)
prettyplay/failures (—) ──(LlmUnavailableError)───────────────> prettyplay/llm (✚)
prettyplay/config (✚) ────(Config)────────────────────────────> prettyplay/driver (✚)
prettyplay/reporting (—) ─(StepReporter)──────────────────────> prettyplay/engine (✚)
prettyplay/failures (—) ───(4 ошибки)─────────────────────────> prettyplay/engine (✚)
prettyplay/driver (✚) ─────(PageFacade, facade)───────────────> prettyplay/engine (✚)
prettyplay/cache (✚) ──────(StepCache, StepIdentity, CachedStep, RunBudgets)──> prettyplay/engine (✚)
prettyplay/llm (✚) ────────(LlmProvider, classification)──────> prettyplay/engine (✚)
prettyplay/config (✚) ────(Config AS PrettyConfig, load_config)──> prettyplay (✚)
prettyplay/reporting (—) ─(StepHooks, StepReporter, hooks)───> prettyplay (✚)
prettyplay/failures (—) ───(4 ошибки, taxonomy)───────────────> prettyplay (✚)
prettyplay/driver (✚) ─────(DriverSession, PageFacade)────────> prettyplay (✚)
prettyplay/cache (✚) ──────(StepCache, StepIdentity, normalize_step_text, RunBudgets)──> prettyplay (✚)
prettyplay/llm (✚) ────────(LlmProvider, create_provider)────> prettyplay (✚)
prettyplay/engine (✚) ─────(StepGenerator, StepHealer, run_step_code, generation, healing)──> prettyplay (✚)
```

Циклов нет. Порядок: failures, reporting → config → {cache, llm, driver} → engine → prettyplay.

## Verification Checklist

| Артефакт | Проверка после реализации |
|---|---|
| `prettyplay/config/CODEMANIFEST` | `goga lint` зелёный; поля `generation_prompt`/`browser_endpoint` с пустыми дефолтами; валидация ws/wss; env `PRETTYPLAY_GENERATION_PROMPT`/`PRETTYPLAY_BROWSER_ENDPOINT`; `load_config(None, None)` ≡ текущее поведение; слияние: `base_url`/`model` только из файла выживают при переданном конфиге; фасад клетки экспортирует `Config`; корневой фасад ре-экспортирует его как `PrettyConfig` (embedding/`__all__` корня) |
| `prettyplay/config/.usages/configuration.md` | таблица env полна (13 строк); пример слияния работает как описано |
| `prettyplay/cache/CODEMANIFEST` + `budgets.md` | пер-тестовая семантика в текстах; адресация/хранилище не тронуты; `goga lint` зелёный |
| `prettyplay/llm/CODEMANIFEST` | `user_instructions` вторым параметром; блок USER INSTRUCTIONS у обоих провайдеров в одном месте контента; `classify_failure` без изменений; паритет реализаций |
| `prettyplay/driver/CODEMANIFEST` + `facade.md` | 3 новых локатора в манифесте и в Surface практики; ветвление launch/connect; headless игнорируется при connect; только расширение (обратная совместимость); `goga lint` зелёный |
| `prettyplay/engine/CODEMANIFEST` + `generation.md` + `healing.md` | ключ `system_prompt` (ссылок на старое имя нет); USER INSTRUCTIONS в generate/regenerate; классификация без них; дефолтный приоритет role → text → label сохранён; листинг поверхности синхронен `facade.md`; пер-тестовые формулировки бюджетов во всех текстах (включая `StepHealer.budgets` и Rules практики healing) |
| `prettyplay/CODEMANIFEST` + `lifecycle.md` | embedding `->PrettyConfig: {}`; `get_runtime` отсутствует в манифесте и `__all__`; `PrettyConfig` в `__all__`; `PrettyTest(cache_key, cache_path, config)`; atexit per-runtime; интерактивный пример с `test.close()` (включая assertion) |
| Вся библиотека | `ruff check` зелёный; `pytest tests/ -x` зелёный; Python 3.10+; два `PrettyTest` изолированы; смена `generation_prompt` не инвалидирует кэш; remote-тесты через моки + `pytest.mark.skipif` |

**Вне артефактов плана** (готовые входы, обновлены на стадии формулировки): `.goga/usages/cooks/playwright.md`, `.goga/usages/cooks/pydantic.md`.
