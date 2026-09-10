# Architecture Plan — prettyplay more-usability

## Topic

**Short name:** prettyplay more-usability — a single usability release (7 ADRs) in the existing cells
**Plan path:** `.goga/history/2026/more-usability/arch.md`
**Input:** ADR `.goga/history/2026/more-usability/adr.md` (approved 08.09.2026), task `.goga/history/2026/more-usability/task.md`

**Scope summary:** 6 cells change, 2 are untouched (`llm`, `cache`); there are no new cells. New types: `FailureVerdict` (failures), `PrettyplayError::ConfigurationError` (config), `classify_step_failure` (engine). New dependency edge: `config → failures`. User decisions beyond the ADRs: the recommendation lives only in the verdict (the `IncurableStepError.recommendation` property — derived with a fallback); the browser env rename is clean, without a hint of the old name; a shared classification Routine in engine.

**Contract rules applied:** CODEMANIFESTs and usage files describe only the current state (no changelog-style wording); examples in usage files are in English.

## Implementation Order

| # | Cell | Rationale |
|---|---|---|
| 1 | `prettyplay/failures` | Leaf — no Imports; supplies FailureVerdict, the error verdict fields and the PrettyplayError base for the ConfigurationError mutation |
| 2 | `prettyplay/reporting` | Leaf — no Imports; supplies the on_step_verdict event referenced by the executor |
| 3 | `prettyplay/config` | Depends only on failures (the new edge); supplies headless/channels and ConfigurationError |
| 4 | `prettyplay/driver` | Depends on config; supplies launch with headless/channel and the facade scrolls; `.usages/facade.md` — the mirror source for engine |
| 5 | `prettyplay/engine` | Depends on failures, reporting, config, driver, cache, llm; supplies classify_step_failure, ADR-3 and the verdicts |
| 6 | `prettyplay` (root) | Depends on all; author screenshots, traceback collapsing, on_step_verdict dispatch |

`prettyplay/llm` and `prettyplay/cache` — unchanged: the `FailureClassification` contract is reused as is; the cache is untouched.

## Artifacts

### 1. Cell: prettyplay/failures — MODIFY

**Diff against the current CODEMANIFEST:**
- ADD: type `FailureVerdict(category, explanation, recommendation)` with a `render()` method (location errors.py)
- CHANGE: `ProductDefectError` — signature `+ verdict: FailureVerdict | None`; Requirements on the double AssertionError inheritance, rendering from the reason, traceback collapsing; the `verdict` property
- CHANGE: `IncurableStepError` — signature `- recommendation: str`, `+ verdict: FailureVerdict | None`; the `recommendation` property becomes derived (the verdict or the path's built-in default); the `verdict` property
- CHANGE: global Annotations (+3 lines) and Description
- UNCHANGED: `PrettyplayError`, `LlmUnavailableError`

**CODEMANIFEST (full target content):**

```yaml
Usages:
  conventions: .goga/usages/conventions.md

Annotations: |
  Use `conventions` for code writing rules and testing.

  The failure taxonomy of the library: three distinct, user-distinguishable step failure kinds plus the shared verdict type; every failure carries an actionable message.
  All failure types derive from the single library base `PrettyplayError`; ProductDefectError additionally derives from AssertionError — the failed check is a failure, never an error, in any runner.
  The rendered message of a terminal failure starts with its primary reason; the verdict render is appended, never interleaved.

---

"PrettyplayError(message: str)":
  location: errors.py
  annotations: |
    The common base of every library failure. Exists for one consumer need: catch any prettyplay failure with a single except clause at the test-suite boundary.

    `message`: the failure description.

"FailureVerdict(category: str, explanation: str, recommendation: str)":
  location: errors.py
  annotations: |
    The verdict of a terminal step failure: what the LLM saw on the page at the moment of the failure and what the engineer should do next.

    `category`: the classification label: rot, product_defect or incurable.
    `explanation`: what happened on the page — one short sentence.
    `recommendation`: the recommended engineer action — one short sentence.

    Requirements:
    - Built by the engines from the failure classification; the failure types never request it themselves
  properties:
    "category -> str": |
      The classification label: rot, product_defect or incurable.
    "explanation -> str": |
      What happened on the page at the moment of the failure.
    "recommendation -> str": |
      The recommended engineer action.
  methods:
    "render() -> text: str": |
      Render the verdict as stable labelled lines — the single render used by the exception message tail, the hook event payload and the log record.

      `text`: the rendered verdict.

      Algorithm:
      1. Build one line per non-empty field: category:, explanation:, recommendation:
      2. Join the lines

      Requirements:
      - Labels are stable lowercase words — integrators parse them

"PrettyplayError::ProductDefectError(step_text: str, message: str, verdict: FailureVerdict | None)":
  location: errors.py
  annotations: |
    A real functional product defect: the expectation of an assertion step legitimately did not hold against the current application state. This is the signal the test suite exists for.

    `step_text`: the sentence of the failed step.
    `message`: what exactly was expected and what was observed — the primary reason.
    `verdict`: the optional `FailureVerdict`; absent when the LLM was unavailable — the failure never waits for it.

    Requirements:
    - Derives from `PrettyplayError` and AssertionError: catchable as any library failure and as an assertion failure in the same except clauses
    - The rendered message starts with `message`; the `verdict` render is appended when present
    - The traceback a runner sees starts at the library boundary — internal library frames are folded away
    - Propagates to the test runner as a failing test: no retry, no healing

    Constraints:
    - The library facade stays framework-agnostic: the runner alignment is done by the type itself, never by a runner plugin or integration
  properties:
    "step_text -> str": |
      The sentence of the failed step.
    "message -> str": |
      What exactly was expected and what was observed.
    "verdict -> FailureVerdict | None": |
      The optional failure verdict; None — the explicit absence when the LLM was unavailable.

"PrettyplayError::IncurableStepError(step_text: str, reason: str, verdict: FailureVerdict | None)":
  location: errors.py
  annotations: |
    An incurable step: regeneration cannot produce working code — the attempt budget is exhausted, the step text no longer matches the application reality, or the intent is ambiguous.

    `step_text`: the sentence of the failed step.
    `reason`: the specific incurability cause — the primary reason of the rendered message.
    `verdict`: the optional `FailureVerdict` — reused from a classification that already happened or requested at budget exhaustion; absent when the LLM was unavailable.

    Requirements:
    - The recommendation is carried by `verdict`; the recommendation property derives from it, falling back to the built-in path guidance when the verdict is absent
    - The rendered message starts with `reason`, then appends the `verdict` render when present; the fallback recommendation keeps the message actionable without a verdict
    - An execution failure, not a failed check: derives from `PrettyplayError` only, never from AssertionError
  properties:
    "step_text -> str": |
      The sentence of the failed step.
    "reason -> str": |
      The specific incurability cause.
    "recommendation -> str": |
      The recommended engineer action: `verdict` recommendation when present, the built-in path guidance otherwise.
    "verdict -> FailureVerdict | None": |
      The optional failure verdict; None — the explicit absence when the LLM was unavailable.

"PrettyplayError::LlmUnavailableError(message: str)":
  location: errors.py
  annotations: |
    LLM infrastructure failure: the provider service is unreachable, times out, rate-limits or rejects authentication. Blocks only code generation and healing; cached steps keep running.

    `message`: the failure description naming the provider.

    Requirements:
    - Raised only on generation or healing paths; never on a cached step execution path
  properties:
    "message -> str": |
      The failure description naming the provider.

---

Author: Goga
CreatedAt: 07/09/26
Description: |
  The failure taxonomy of prettyplay: product defect, incurable step, LLM infrastructure — mutations of one library base — and the shared verdict of a terminal failure.
```

**.usages file: `prettyplay/failures/.usages/taxonomy.md` — MODIFY (full content):**

```md
# Failure taxonomy

Domain: failure kinds of prettyplay. Audience: integrators wiring library failures into runner and CI reporting.

Every step failure is one of three distinct kinds; all derive from `PrettyplayError`, so one except clause catches any prettyplay failure. A fourth kind — the configuration error — joins the base from the config cell.

| Exception | Meaning | When it happens | Recommended reaction |
|---|---|---|---|
| ProductDefectError | real product regression | an assertion expectation legitimately failed | treat as a bug: file it, fix the product — this failure is the value of the suite |
| IncurableStepError | the step cannot be (re)generated | attempt budget exhausted, step text no longer matches reality, ambiguity | follow `recommendation`: reword the step or refresh the cache |
| LlmUnavailableError | LLM infrastructure down | generation or healing ran while the provider was unavailable | restore provider access or keys; cached steps are unaffected |
| ConfigurationError | settings are invalid | the first library use loaded an invalid [tool.prettyplay] section | fix the named setting — the message lists the allowed values |

## Verdicts on terminal failures

ProductDefectError and IncurableStepError carry an optional verdict: category, explanation, recommendation. It is fully present in the exception message, the on_step_verdict hook event and the log. When the LLM is unavailable the verdict is skipped quietly (WARNING in the log) — the failure itself is never delayed or distorted.

```python
import pytest

from prettyplay.failures import IncurableStepError


def test_reports_only_library_failures():
    with pytest.raises(IncurableStepError) as info:
        ...
    assert info.value.recommendation
    # info.value.verdict may be None when the LLM was unavailable
```

## Assertion semantics

ProductDefectError is also an AssertionError: unittest reports the failed check as a failure (not an error), pytest shows it as an ordinary assertion failure, the traceback is folded to the library boundary. Catch it with `except PrettyplayError` or `except AssertionError` — both work.

## Rules

- Every failure message is actionable: what happened, on which step, what to do next
- A healed run never turns a ProductDefectError into a green test
- LlmUnavailableError never occurs on the cached path — a cached suite runs without any LLM
- The verdict explanation never replaces the primary failure — it is appended
```

### 2. Cell: prettyplay/reporting — MODIFY

**Diff:** ADD the `on_step_verdict` method on StepHooks; CHANGE one line of the global Annotations (the INFO level of step events including the verdict); UNCHANGED StepReporter.

**CODEMANIFEST (full target content):**

```yaml
Usages:
  conventions: .goga/usages/conventions.md

Annotations: |
  Use `conventions` for code writing rules and testing.

  Visibility goes through the standard logging library: the logger is named prettyplay.
  Log messages: lowercase, concise operational wording, stable event names, contextual metadata attached.
  Never log secrets, credentials, tokens or personal sensitive data.
  Step lifecycle events — including the verdict event — are logged at INFO; a skipped cache write and a failed hook call — WARNING.

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
    "on_step_verdict(step_text: str, category: str, explanation: str, recommendation: str)": |
      The terminal failure of the step carried a verdict; fires after on_step_failed.

      `step_text`: the sentence of the failed step.
      `category`: the verdict label — rot, product_defect or incurable.
      `explanation`: what the LLM saw on the page at the moment of the failure.
      `recommendation`: the recommended engineer action.

      Requirements:
      - Not fired when the verdict was skipped: LLM unavailability logs a WARNING and raises no event
      - Payload values are plain strings, uniform with the other events
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
    "emit(event: str, payload: dict[str, str | int])": |
      Dispatch one event.

      `event`: the event name — equals a `StepHooks` method name exactly.
      `payload`: the payload fields of the event; values are strings, the attempt counter is an int.

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

**.usages file: `prettyplay/reporting/.usages/hooks.md` — MODIFY (full content):**

```md
# Step and healing hooks

Domain: event callbacks of prettyplay. Audience: integrators building custom reporting, metrics or CI reactions on top of step execution.

StepHooks is a thin callback contract. The library calls the matching method synchronously while a step executes. The base implementation of every method is a no-op — override only the events you need. Hook implementations are registered on the main library object at the start of a test.

## Events

| Method | When | Payload |
|---|---|---|
| on_step_started | a step started executing | step_text, step_type (action or assertion) |
| on_step_passed | the step finished successfully | step_text, step_type |
| on_step_failed | the step failed | step_text, step_type, error (short description) |
| on_step_verdict | the terminal failure carried a verdict (fires after on_step_failed) | step_text, category (rot, product_defect, incurable), explanation, recommendation |
| on_generation_started | a generation attempt started | step_text, attempt (1-based) |
| on_healing_started | healing of a failed cached step started | step_text, category (rot, product_defect, incurable) |
| on_healed | the step healed, cache updated | step_text, explanation (why rot, what changed) |
| on_cache_saved | step code written to the cache | step_text, filename |
| on_cache_skipped | cache write skipped | step_text, reason (e.g. read-only cache) |

## Example

```python
from prettyplay.reporting import StepHooks


class HealingMonitor(StepHooks):
    def on_step_verdict(self, step_text: str, category: str, explanation: str, recommendation: str) -> None:
        print(f"verdict [{category}]: {step_text} — {explanation} → {recommendation}")

    def on_healed(self, step_text: str, explanation: str) -> None:
        print(f"healed: {step_text} — {explanation}")
```

## Rules

- Handlers run synchronously inside step execution: keep them fast
- A raising handler is logged as a warning and skipped — the test run never fails because of a hook
- on_step_verdict fires only when the verdict exists: LLM unavailability skips the verdict quietly (WARNING in the log)
- Payload values are plain strings; the attempt counter of on_generation_started is an int
- Step texts land in logs and hooks: never put secrets or personal data into a step sentence
```

### 3. Cell: prettyplay/config — MODIFY

**Diff:** ADD Imports from `prettyplay/failures` (PrettyplayError + the `taxonomy` usage); ADD the `PrettyplayError::ConfigurationError` type (location loader.py); CHANGE `Config` — the `headless` field, the `headless` property, the browser texts (5 values); CHANGE `load_config` — the algorithm (PRETTYPLAY_BROWSER_NAME / PRETTYPLAY_BROWSER_HEADLESS, ValidationError wrapping); CHANGE global Annotations (+2 lines) and Description.

**CODEMANIFEST (full target content):**

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

"Config(provider: str, browser: str, model: str, generation_model: str, classification_model: str, base_url: str, cache_root: str, generation_attempts: int, healing_attempts: int, send_screenshots: bool, headless: bool)":
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
    `generation_attempts`: generation attempt budget per step per run; default 3.
    `healing_attempts`: healing attempt budget per step per run; default 2.
    `send_screenshots`: optional screenshot input to the LLM; default False.
    `headless`: run the browser without a visible window; default True.

    Requirements:
    - kw_only construction; every field has an empty default
    - provider validated against {openai, anthropic}; browser against the five-value set; invalid value — loud actionable error
    - attempts are positive integers

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
    "generation_attempts -> int": |
      The generation attempt budget per step per run.
    "healing_attempts -> int": |
      The healing attempt budget per step per run.
    "send_screenshots -> bool": |
      Whether screenshots are attached to LLM requests.
    "headless -> bool": |
      Whether the browser runs without a visible window.
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
    4. Apply environment overrides: each setting is overridden by PRETTYPLAY_<SETTING_UPPERCASE> when the variable is set; the browser override is PRETTYPLAY_BROWSER_NAME, the headless override is PRETTYPLAY_BROWSER_HEADLESS
    5. Construct `Config`; on a validation failure render the actionable text — one line per invalid setting: the setting name, the received value, the allowed values — and raise `ConfigurationError` with the original ValidationError chained

    Requirements:
    - An env override exists for every setting of `Config`
    - A raw pydantic.ValidationError never leaves the loader
    - The empty cache_root setting is resolved to the absolute default <repo root>/.prettyplay/cache/ at load

    Constraints:
    - Never read or store LLM API keys from any file; keys come only from environment variables
    - Python 3.10 compatibility via the tomli fallback (see `pydantic`)

---

Author: Goga
CreatedAt: 07/09/26
Description: |
  Project settings of prettyplay: the validated [tool.prettyplay] schema with the browser channels and headless mode, and the loader with environment overrides and the actionable configuration error.
```

**.usages file: `prettyplay/config/.usages/configuration.md` — MODIFY (full content):**

```md
# Project configuration

Domain: prettyplay settings. Audience: integrators configuring a test project and CI.

The immutable part of the settings lives in the [tool.prettyplay] section of pyproject.toml. Load it once per run; every run reads the same values.

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

## Browsers

The browser matrix: chromium, firefox, webkit (Playwright-bundled engines) plus chrome and msedge — channels that launch the locally installed browser through the chromium engine. A channel requires the real browser installed on the machine; a missing browser fails loudly with an actionable message.

## Rules

- LLM API keys are never stored in the config file — secrets come only from environment variables: OPENAI_API_KEY for openai, ANTHROPIC_API_KEY for anthropic
- Invalid configuration fails loudly: ConfigurationError names the setting, the received value and the allowed values; the raw pydantic error stays chained for debugging
- The provider set: openai, anthropic
- The cache root default: <repo root>/.prettyplay/cache/ — resolved from the located pyproject.toml

## Loading

```python
from prettyplay.config import load_config

config = load_config(pyproject_path=None)  # locates pyproject.toml upwards from the current directory
print(config.browser, config.headless, config.generation_attempts)
```
```

### 4. Cell: prettyplay/driver — MODIFY

**Diff:** CHANGE `DriverSession` — the config annotation (headless/channels), step 1 of the open_context algorithm, the requirement of a loud failure when the installed browser is absent; CHANGE `PageFacade` — 8 scroll methods, the Requirements line about scrolls without delays; CHANGE the `playwright` line in the global Annotations and Description; UNCHANGED `LocatorFacade` and the existing surface.

**CODEMANIFEST (full target content):**

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
  Use `playwright` for the sync API lifecycle, locators, auto-wait, the accessibility snapshot, browser channels and the scroll primitives.

  The driver is Playwright sync-only: the async API is out of scope.
  The whole Playwright session — start, browser, contexts, pages — lives in one dedicated driver thread owned by the library: the sync API parks its private event loop on its starting thread, so the thread executing the steps never holds a running asyncio loop (interactive hosts such as IPython and Jupyter keep working between steps).
  Driver-thread calls are strictly sequential: one facade call runs at a time; concurrent driving is out of scope.
  One browser process serves the whole run; every test gets its own isolated browser context — no state is shared between tests through the library.
  All waits go through locators and expectations; fixed delays (time.sleep and similar) are forbidden.
  The facade surface is a backward-compatibility contract: generated step code works only through `PageFacade` and LocatorFacade, so the existing method set must not break across library releases — extend, never rename or remove.

---

"DriverSession(config: Config)":
  location: session.py
  annotations: |
    Lifecycle owner of the Playwright sync driver and the browser process for the whole run.

    `config`: project settings; the browser setting selects the browser of the {chromium, firefox, webkit, chrome, msedge} set — chrome and msedge launch the locally installed browser through the channel mechanism; headless controls the window visibility (see `playwright`).

    Requirements:
    - The Playwright session lives in a dedicated driver thread owned by the session: every Playwright-touching operation of this type runs there, and the calling thread never holds a running asyncio loop after any call
  methods:
    "open_context() -> page: PageFacade": |
      Open a fresh isolated context with one page.

      Algorithm:
      1. Launch lazily on the first call: constructing the session starts nothing — start the dedicated driver thread, then start Playwright and launch the browser engine inside it with headless from the project settings and the channel for the chrome/msedge values; a failed launch stops the started driver and closes the thread, so a retry begins from a clean state
      2. Create a fresh isolated browser context and its page inside the driver thread (see `playwright`)
      3. Wrap the page into `PageFacade` bound to the driver thread and return it

      Requirements:
      - Each result is isolated from every other context of the run
      - A channel launch without the installed browser fails loudly with an actionable message naming the missing browser
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
  The Playwright sync driver of prettyplay: the run-scoped session with headless and channel launches, and the narrow backward-compatible page facade with scroll abilities for generated step code.
```

**.usages file: `prettyplay/driver/.usages/facade.md` — MODIFY (full content):**

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

# scroll scenarios
page.scroll_down(600)
page.find_by_text("Footer").expect_visible()

cards = page.find_by_role("list", name="Recommendations")
page.scroll_container_down(cards, 400)
page.find_by_text("Fifth card").expect_visible()

snapshot = page.aria_snapshot()
```

## Rules

- Contexts are isolated per test; the browser process is shared per run
- Every call executes in the library's driver thread and returns when done: driving is strictly sequential, and the calling thread never adopts the Playwright event loop — hand-written step code stays safe in interactive hosts (IPython, Jupyter)
- Auto-wait everywhere: no time.sleep, no fixed delays in step code — including around scrolls: the scrolled state is awaited through locators and expectations
- Never put secrets into step actions — step texts and code land in the repository cache
```

### 5. Cell: prettyplay/engine — MODIFY

**Diff:** ADD Routine `classify_step_failure` (location classification.py); CHANGE `classification_prompt` (the first line without "cached"); ADD a line about scroll abilities in `generation_prompt` (Rules); CHANGE `StepGenerator.generate` — steps 6-8 (AssertionError → stop retries + classification; the verdict on exhaustion with a silent skip; LLM unavailability in generation-path classifications — a silent skip with WARNING, the failure without a verdict) and Requirements; CHANGE `StepHealer.heal` — steps 1, 3, 4, 6 (classification through the routine; verdicts before errors) and Requirements; CHANGE global Annotations (+3 lines, distinguishing the silent skip from the infrastructure failure) and Description; UNCHANGED `run_step_code`, the engine signatures.

**CODEMANIFEST (full target content):**

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
  Use `generation_prompt` as the system prompt of every code generation request.
  Use `classification_prompt` as the system prompt of every failure classification request.
  Use `facade` from Imports as the single source of the page API surface for generation requests.

  The fixed form of step code: one function receiving exactly one argument — the `PageFacade` of the test; the function body works only through `PageFacade` and the LocatorFacade element API.
  Every attempt — generation or healing — consumes the shared per-step budget of the run; exhaustion is the incurable failure, never an infinite loop.
  Healing never masks a product defect: a classified product_defect fails the test loudly; a healed step is reported loudly and written back to the cache.
  Every terminal failure carries a verdict — category, explanation, recommendation — fully present in the exception message, the verdict hook event and the log; an unavailable LLM skips the verdict quietly with a WARNING, the failure itself is never delayed or distorted — the quiet skip applies to verdicts enriching an already-decided failure; the classification driving the healing decision surfaces as the infrastructure failure.
  A failed check of a candidate stops the generation retries: a check that executed and did not hold is classified, not regenerated.
  The page API surface listing sent to the provider mirrors `facade` from Imports exactly — the listing and the practice change together.

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

**Implementation note (not a contract):** the page API listing string sent to the provider is derived from the Surface table of `prettyplay/driver/.usages/facade.md`; both copies change only together (the mirroring requirement is fixed in the global Annotations).

**.usages file: `prettyplay/engine/.usages/generation.md` — MODIFY (full content):**

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
- A failed check of a candidate (an assertion that executed and did not hold) stops the retries at once: the failure goes to classification — product_defect raises ProductDefectError with the verdict, anything else raises IncurableStepError with it; when the LLM is unavailable at this classification the verdict is skipped quietly (WARNING in the log) and IncurableStepError raises without it; one failed check is spent, never the whole budget
- Other candidate failures (element not found, timeouts) retry with the fresh error and snapshot
- Attempts are budgeted per step per run (default 3); exhaustion raises IncurableStepError carrying the classification verdict of the last candidate — when the LLM is unavailable the verdict is skipped quietly (WARNING in the log) and the failure raises without it
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

Generated code is one function receiving exactly one argument — the page facade — and working only through the facade surface: page.find_by_role(...).click(), element.expect_visible(), page.scroll_down(600) and alike. No provider constructs, no direct driver imports, no fixed delays.
```

**.usages file: `prettyplay/engine/.usages/healing.md` — MODIFY (full content):**

```md
# Step healing

Domain: healing a failed cached step. Audience: library internals and engineers reasoning about healed runs.

## Heal

```python
healed = healer.heal(
    step=failed_step, error="element not found: button «Sign in»", previous_steps=["open the login page"], page=page
)
```

The classification verdict decides the path:

| Category | Path |
|---|---|
| rot | regenerate from the current page within the healing budget (default 2), execute, save back to the cache, report loudly |
| product_defect | raise ProductDefectError carrying the verdict — category, explanation and recommendation all reach the exception message, the on_step_verdict hook and the log |
| incurable | raise IncurableStepError carrying the verdict; the reason names the incurability cause |

## Rules

- Anti-masking: healing never turns a product defect into a green test
- The healed code replaces the cached code only after a successful execution
- Generation and healing attempts live in one run-scoped registry with separate per-step limits (default 3 and 2)
- A regeneration budget exhaustion after rot raises IncurableStepError carrying the verdict of the original rot classification — no extra LLM request
- Provider unavailability during the classification raises LlmUnavailableError — an explicit infrastructure failure

## Verdicts

Every terminal failure carries its verdict in full: the exception message starts with the primary reason and appends the verdict render; the same three fields reach on_step_verdict and the structured log record.
```

### 6. Cell: prettyplay — MODIFY (root facade)

**Diff:** ADD the `get_screenshot`/`save_screenshot` methods on PrettyTest; CHANGE `action`/`assertion` — the line about traceback collapsing; CHANGE `execute` step 7 — on_step_verdict; CHANGE Description; UNCHANGED PrettyplayRuntime, get_runtime, signatures.

**CODEMANIFEST (full target content):**

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
      A terminal failure leaves this method with its traceback folded to the library boundary: internal library frames — engine, healing, provider — do not appear in what the runner shows.
    "assertion(text: str)": |
      Execute the assertion step `text` — a legitimately failed expectation surfaces as the product defect failure.

      Delegates to the executor execute with the step type assertion; failures propagate by kind — `ProductDefectError`, `IncurableStepError`, `LlmUnavailableError` (see `taxonomy`).
      A terminal failure leaves this method with its traceback folded to the library boundary: internal library frames — engine, healing, provider — do not appear in what the runner shows.
    "get_screenshot() -> image: bytes": |
      Return a full-page PNG image of the current state of the test page — uniform with the facade screenshot.

      `image`: the full-page PNG bytes.

      Requirements:
      - Requires an opened test page: calling before the first step raises a loud actionable library failure telling to run a step first
      - No screenshot is taken automatically on step failures: the decision to capture belongs to the test author
    "save_screenshot(filepath: str)": |
      Write a full-page PNG image of the current state of the test page to `filepath`.

      `filepath`: the explicit destination path chosen by the user — any directory, any filename; no default directory is imposed.

      Requirements:
      - Requires an opened test page: calling before the first step raises a loud actionable library failure telling to run a step first
      - A write failure — e.g. a missing parent directory — surfaces as a loud actionable failure; nothing is created silently
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
      4. On a hit execution failure: delegate to the healer heal with the failure description and the scenario context — a healed step is already re-executed and stored by the engine
      5. On a miss: the generator generate — the engine stores the step on success
      6. Append the sentence to the scenario context of the test — the previous step texts feed the next generation
      7. Report on_step_passed; on a failed step report on_step_failed with the sentence, the step type and the short error description — then, when the terminal failure carries a verdict, report on_step_verdict with the sentence and the three verdict fields; finally raise by kind — `ProductDefectError`, `IncurableStepError`, `LlmUnavailableError` (see `taxonomy`)

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
  The facade of prettyplay: the per-test scenario object with screenshot abilities, the step cycle executor with verdict reporting, and the run-scoped composition root.
```

**.usages file: `prettyplay/.usages/steps.md` — MODIFY (full content):**

```md
# Writing steps

Domain: authoring UI tests as plain sentences. Audience: engineers writing tests and integrators wiring the library into a test framework.

## A test as a scenario

```python
from prettyplay import PrettyTest


def test_login():
    t = PrettyTest("login-flow")
    t.action("open the login page")
    t.action("enter the login and password")
    t.action("click the «Sign in» button")
    t.assertion("the «Welcome back» message appears")
    t.close()
```

Or with the context manager:

```python
with PrettyTest("login-flow") as t:
    t.action("open the login page")
```

## Step kinds

- action(text) — performs what the sentence says
- assertion(text) — verifies what the sentence says; a legitimately failed expectation fails the test as a product defect

## Screenshots

Two author-facing abilities on the test object:

```python
with PrettyTest("login-flow") as t:
    t.action("open the login page")
    png = t.get_screenshot()                 # full-page PNG bytes of the current state
    t.save_screenshot("artifacts/home.png")  # write full-page PNG to an explicit path
```

- Both require an opened page: call them after the first step of the test
- Nothing is captured automatically on failures — attaching screenshots to reports is the author's decision

## Addressing

The constructor arguments form the cache address: cache_key (mandatory) and cache_path (optional subdirectory). Equal cache keys in the shared root reuse one cached step across tests; a different language, step type or key is a different step.

## What you see

Step sentences go to the logger prettyplay at info level — the suite output reads as a plain-language scenario. Healing, cache writes and skipped writes are reported loudly through the same logger.

## Limitations

Step sentences land in the repository cache, the logs and the LLM requests: never put secrets or personal data into a step.
```

**.usages file: `prettyplay/.usages/lifecycle.md` — MODIFY (full content):**

```md
# Run lifecycle

Domain: how a run is composed — runtime, contexts, hooks, failures. Audience: integrators wiring the library into a runner and CI.

## Composition

One process-wide runtime per run: the configuration, the browser process, the LLM provider and the attempt budgets are created once and shared by every test. Each PrettyTest opens its own isolated browser context and closes it on close(). Tests normally never touch the runtime directly — constructing PrettyTest is enough.

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

The browser process stays alive for the whole session once the first step has run. Release it explicitly when interactive exploration is over:

```python
from prettyplay import get_runtime

get_runtime().close()  # stops the browser and the driver thread
```

Generation of the step cache remains a batch workflow: prefer a plain script or a pytest run over a REPL when generating many steps.
```

## Dependency Map

```
failures (leaf)
  ├─ PrettyplayError, taxonomy ──────────> config          [release edge]
  ├─ ProductDefectError, IncurableStepError, LlmUnavailableError ──> engine, prettyplay
reporting (leaf)
  └─ StepHooks, StepReporter ─────────────> cache, engine, prettyplay
config
  └─ Config, load_config ─────────────────> llm, driver, cache, engine, prettyplay
llm
  └─ LlmProvider, FailureClassification, classification ──> engine, prettyplay
driver
  └─ DriverSession, PageFacade, facade ───> engine, prettyplay        [facade — mirror source]
cache
  └─ StepCache, StepIdentity, CachedStep, RunBudgets ──> engine, prettyplay
engine
  └─ StepGenerator, StepHealer, run_step_code, generation, healing ──> prettyplay
prettyplay (root)
```

Implementation order: failures → {reporting, config} → {llm, driver, cache} → engine → prettyplay. There are no cyclic dependencies (config→failures is the only new edge; failures is a leaf).

## Verification Checklist

After applying the plan (`goga lint` + inspection):

1. **All cells:** `goga lint` passes without DSL errors; `goga schema` reflects the new types (FailureVerdict in failures; ConfigurationError in config; classify_step_failure in engine) and the new config→failures edge; there are no cross-imports.
2. **failures:** ProductDefectError as a mutation of PrettyplayError with the verdict field; IncurableStepError without the recommendation parameter, the property derived; FailureVerdict with render(); taxonomy.md describes 4 kinds and the verdicts; the texts carry no changelog-style wording.
3. **reporting:** on_step_verdict in StepHooks with 4 string parameters; the hooks.md table contains the event row; the event is not called when the verdict is skipped.
4. **config:** Imports from failures with taxonomy; ConfigurationError — a PrettyplayError mutation; headless in Config (default True) and in the configuration.md env table as PRETTYPLAY_BROWSER_HEADLESS; the browser matrix of 5 values; load_config raises ConfigurationError with the chained ValidationError; not a single mention of the old env name.
5. **driver:** PageFacade extended only (8 scroll methods, variant A signatures); the existing 12 surface calls untouched; DriverSession open_context — headless/channel and a loud failure; facade.md Surface = 21 calls, examples in English.
6. **engine:** classify_step_failure in classification.py; generate — steps 6-8 (AssertionError → stop retries + classification; LLM unavailability in generation-path classifications — a silent skip with WARNING, the failure without a verdict; exhaustion → the verdict); heal — verdicts before errors, reuse of the verdict on exhaustion after rot; classification_prompt without "cached"; the page API listing string mirrors the facade.md Surface.
7. **prettyplay:** get_screenshot/save_screenshot with the open-page requirement; action/assertion — traceback collapsing; execute step 7 — on_step_verdict after on_step_failed; the steps.md Screenshots section; lifecycle.md — 4 failure kinds.
8. **Untouched:** the llm and cache CODEMANIFESTs and their .usages are unchanged.
9. **The task's acceptance criteria** are covered by the contract (see CELL_ASSEMBLY_REPORT); deviation: the old env name hint is absent by the user's decision.
