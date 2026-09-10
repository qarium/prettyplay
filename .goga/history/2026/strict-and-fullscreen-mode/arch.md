# Architecture Plan: strict-and-fullscreen-mode

## Topic

- Short name: **strict-and-fullscreen-mode** — strict replay-only mode, browser screen modes, structured failure messages, classification instructions
- Plan path: `.goga/history/2026/strict-and-fullscreen-mode/arch.md`
- Source task: `.goga/history/2026/strict-and-fullscreen-mode/task.md` (ADR 2026-09-10)
- All artifacts below are **current state** (not changelogs). Each carries a change summary line.

## Implementation Order

| # | Cell | Status | Rationale |
|---|---|---|---|
| 1 | `prettyplay/failures` | modified | Leaf — no Imports; the structured render and the error-field contract are consumed by every upper cell |
| 2 | `prettyplay/reporting` | modified | Leaf — no Imports; on_step_failed payload semantics |
| 3 | `prettyplay/config` | modified | Depends on failures (PrettyplayError); provides `BrowserConfig`, `strict`, `classification_prompt` to driver/llm/engine/root |
| 4 | `prettyplay/driver` | modified | Depends on config (`Config` with the nested browser group); resolves `screen` |
| 5 | `prettyplay/llm` | modified | Depends on config, failures (`LLMUnavailableError`); classification user instructions |
| 6 | `prettyplay/cache` | **unchanged** | No contract change — strict-mode budget non-consumption is caller behavior |
| 7 | `prettyplay/engine` | modified | Depends on config, reporting, failures, driver, cache, llm; classification instructions + error-field cascade |
| 8 | `prettyplay` (root) | modified | Depends on all; strict execution path; imports and embeds `BrowserConfig` |

## Artifacts

### 1. Cell: prettyplay/failures (modified)

Change summary: NEW routine `render_terminal_message`; `FailureVerdict.render()` re-templated (column-aligned, category dropped); `ProductDefectError`/`IncurableStepError` gain the `error` field and compose their message through the render routine; type renamed `LlmUnavailableError` → `LLMUnavailableError`.

**File: `prettyplay/failures/CODEMANIFEST`**

```yaml
Usages:
  conventions: .goga/usages/conventions.md

Annotations: |
  Use `conventions` for code writing rules and testing.

  The failure taxonomy of the library: three distinct, user-distinguishable step failure kinds plus the shared verdict type; every failure carries an actionable message.
  All failure types derive from the single library base `PrettyplayError`; ProductDefectError additionally derives from AssertionError — the failed check is a failure, never an error, in any runner.
  The rendered message of a terminal failure follows the single structured template: the primary reason alone on the first line — no kind label and no internal colons, the exception type prefix rendered by the runner supplies the kind; then --- separated blocks.
  One render — produced at exception construction through `render_terminal_message` — feeds the exception message, the log record and the on_step_failed hook payload; consumers never re-compose.
  Reason texts authored by the engines and the executor are written without colons — the first-line contract of the render.

---

"PrettyplayError(message: str)":
  location: errors.py
  annotations: |
    The common base of every library failure. Exists for one consumer need: catch any prettyplay failure with a single except clause at the test-suite boundary.

    `message`: the failure description.

"render_terminal_message(reason: str, step_text: str, error: str, verdict: FailureVerdict | None) -> text: str":
  location: errors.py
  annotations: |
    Compose the single structured render of a terminal failure — the one text used by the exception message, the log record and the on_step_failed hook payload.

    `reason`: the primary reason — the first line of the render; authored without colons.
    `step_text`: the sentence of the failed step; empty — no step line.
    `error`: the full underlying error text of the failed step code, locator details included; for failed checks passed without the AssertionError prefix — the exception type already carries the assertion semantics; empty — no error line.
    `verdict`: the optional `FailureVerdict`; None or an empty render — no verdict block.
    `text`: the rendered message.

    Algorithm:
    1. First line: `reason` verbatim
    2. When `step_text` or `error` is non-empty: append the --- separator, then the step: line for a non-empty `step_text` and the error: line for a non-empty `error`
    3. When `verdict` renders non-empty: append the --- separator, then the verdict block render
    4. Join the lines

    Requirements:
    - The block order is fixed: reason, step/error, verdict
    - Both step and error empty — the whole middle block is omitted, no bare separator
    - The render ends without a trailing separator

    Constraints:
    - Never embed the step code — it lives in the cache and the log

"FailureVerdict(category: str, explanation: str, recommendation: str)":
  location: errors.py
  annotations: |
    The verdict of a terminal step failure: what the LLM saw on the page at the moment of the failure and what the engineer should do next.

    `category`: the classification label: rot, product_defect or incurable — travels in structured fields only, never in the render.
    `explanation`: what happened on the page — one short sentence.
    `recommendation`: the recommended engineer action — one short sentence.

    Requirements:
    - Built by the engines and the strict-mode executor from the failure classification; the failure types never request it themselves
  properties:
    "category -> str": |
      The classification label: rot, product_defect or incurable.
    "explanation -> str": |
      What happened on the page at the moment of the failure.
    "recommendation -> str": |
      The recommended engineer action.
  methods:
    "render() -> text: str": |
      Render the verdict block of the structured terminal message — the aligned explanation and recommendation lines.

      `text`: the rendered verdict block; empty when both fields are empty.

      Algorithm:
      1. Build one line per non-empty field: explanation: and recommendation: — the values start at one column, aligned after the longest label; multi-line continuations indent to the same value column
      2. Join the lines

      Requirements:
      - The category line is dropped: the category travels in the structured fields of the on_step_verdict event, never in the render
      - Labels are stable lowercase words — integrators parse them

"PrettyplayError::ProductDefectError(step_text: str, message: str, error: str, verdict: FailureVerdict | None)":
  location: errors.py
  annotations: |
    A real functional product defect: the expectation of an assertion step legitimately did not hold against the current application state. This is the signal the test suite exists for.

    `step_text`: the sentence of the failed step.
    `message`: what exactly was expected and what was observed — the primary reason.
    `error`: the full underlying error text of the failed step code, locator details included; for failed checks carried without the AssertionError prefix; empty — the render carries no error line.
    `verdict`: the optional `FailureVerdict`; absent when the LLM was unavailable — the failure never waits for it.

    Requirements:
    - Derives from `PrettyplayError` and AssertionError: catchable as any library failure and as an assertion failure in the same except clauses
    - The rendered message is composed through `render_terminal_message` from `message`, `step_text`, `error` and `verdict`
    - The traceback a runner sees starts at the library boundary — internal library frames are folded away
    - Propagates to the test runner as a failing test: no retry, no healing

    Constraints:
    - The library facade stays framework-agnostic: the runner alignment is done by the type itself, never by a runner plugin or integration
  properties:
    "step_text -> str": |
      The sentence of the failed step.
    "message -> str": |
      What exactly was expected and what was observed.
    "error -> str": |
      The full underlying error text of the failed step code; empty means no underlying code error.
    "verdict -> FailureVerdict | None": |
      The optional failure verdict; None — the explicit absence when the LLM was unavailable.

"PrettyplayError::IncurableStepError(step_text: str, reason: str, error: str, verdict: FailureVerdict | None)":
  location: errors.py
  annotations: |
    An incurable step: regeneration cannot produce working code — the attempt budget is exhausted, the step text no longer matches the application reality, the intent is ambiguous, or strict mode forbids generation.

    `step_text`: the sentence of the failed step.
    `reason`: the specific incurability cause — the primary reason of the rendered message; authored without colons.
    `error`: the full underlying error text of the failed step code, locator details included; empty — the render carries no error line.
    `verdict`: the optional `FailureVerdict` — reused from a classification that already happened or requested at budget exhaustion; absent when the LLM was unavailable.

    Requirements:
    - The recommendation is carried by `verdict`; the recommendation property derives from it, falling back to the built-in path guidance when the verdict is absent
    - The rendered message is composed through `render_terminal_message` from `reason`, `step_text`, `error` and `verdict`; the fallback recommendation keeps the message actionable without a verdict
    - An execution failure, not a failed check: derives from `PrettyplayError` only, never from AssertionError
  properties:
    "step_text -> str": |
      The sentence of the failed step.
    "reason -> str": |
      The specific incurability cause.
    "error -> str": |
      The full underlying error text of the failed step code; empty means no underlying code error.
    "recommendation -> str": |
      The recommended engineer action: verdict recommendation when present, the built-in path guidance otherwise.
    "verdict -> FailureVerdict | None": |
      The optional failure verdict; None — the explicit absence when the LLM was unavailable.

"PrettyplayError::LLMUnavailableError(message: str)":
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
CreatedAt: 10/09/26
Description: |
  The failure taxonomy of prettyplay: product defect, incurable step, LLM infrastructure — mutations of one library base — the shared verdict of a terminal failure, and the single structured render of its message.
```

**File: `prettyplay/failures/.usages/taxonomy.md`**

Change summary: new section "The structured failure message"; verdict/error-field rules updated; rename applied.

````md
# Failure taxonomy

Domain: failure kinds of prettyplay. Audience: integrators wiring library failures into runner and CI reporting.

Every step failure is one of three distinct kinds; all derive from `PrettyplayError`, so one except clause catches any prettyplay failure. A fourth kind — the configuration error — joins the base from the config cell.

| Exception | Meaning | When it happens | Recommended reaction |
|---|---|---|---|
| ProductDefectError | real product regression | an assertion expectation legitimately failed | treat as a bug: file it, fix the product — this failure is the value of the suite |
| IncurableStepError | the step cannot be (re)generated | attempt budget exhausted, step text no longer matches reality, ambiguity, strict mode forbids generation | follow the verdict `recommendation`: reword the step or refresh the cache |
| LLMUnavailableError | LLM infrastructure down | generation or healing ran while the provider was unavailable | restore provider access or keys; cached steps are unaffected |
| ConfigurationError | settings are invalid | the first library use loaded an invalid [tool.prettyplay] section | fix the named setting — the message lists the allowed values |

## The structured failure message

ProductDefectError and IncurableStepError render one structured message — the same text reaches the exception message, the log record and the `error` field of the `on_step_failed` hook event:

```text
ProductDefectError: кнопка «Войти» осталась невидимой после отправки формы
---
step: Проверить появление кнопки «Войти»
error: Locator expected to be visible
---
explanation:    на странице нет элемента с ролью button и именем «Войти»
recommendation: проверить селектор или текст кнопки в приложении
```

- The first line is the primary reason only — no kind label, no colons; the exception type prefix (rendered by the runner) supplies the kind
- The `step:`/`error:` block carries the step sentence and the full underlying error of the failed step code, locator details included; for failed checks the `error:` text never carries an AssertionError prefix — the exception type already carries the assertion semantics; the block is omitted entirely when both are empty
- The verdict block shows column-aligned `explanation:` and `recommendation:` values — multi-line continuations indent to the same value column; the `category:` line is gone — the category travels in the structured fields of `on_step_verdict`, never in the render
- Empty blocks are omitted entirely: no verdict → no verdict block; no underlying error → no `error:` line
- The failed step's code is never included — it lives in the cache and the log

## Verdicts on terminal failures

ProductDefectError and IncurableStepError carry an optional verdict: category, explanation, recommendation. When the LLM is unavailable the verdict is skipped quietly (WARNING in the log) — the failure itself is never delayed or distorted.

```python
import pytest

from prettyplay.failures import IncurableStepError


def test_reports_only_library_failures():
    with pytest.raises(IncurableStepError) as info:
        ...
    assert info.value.recommendation
    # info.value.verdict may be None when the LLM was unavailable
    # info.value.error carries the full underlying error text ("" when none)
```

## Assertion semantics

ProductDefectError is also an AssertionError: unittest reports the failed check as a failure (not an error), pytest shows it as an ordinary assertion failure, the traceback is folded to the library boundary. Catch it with `except PrettyplayError` or `except AssertionError` — both work.

## Rules

- Every failure message is actionable: what happened, on which step, what to do next
- A healed run never turns a ProductDefectError into a green test
- LLMUnavailableError never occurs on the cached path — a cached suite runs without any LLM
- One render per terminal failure: integrators parsing messages parse the structured template above; the category comes from the `on_step_verdict` event fields, never from the message
````

### 2. Cell: prettyplay/reporting (modified)

Change summary: annotations only — `on_step_failed` error field carries the full structured render; `on_step_verdict` stays structured. Signatures unchanged.

**File: `prettyplay/reporting/CODEMANIFEST`**

```yaml
Usages:
  conventions: .goga/usages/conventions.md

Annotations: |
  Use `conventions` for code writing rules and testing.

  Visibility goes through the standard logging library: the logger is named prettyplay.
  Log messages: lowercase, concise operational wording, stable event names, contextual metadata attached.
  Never log secrets, credentials, tokens or personal sensitive data.
  Step lifecycle events — including the verdict event — are logged at INFO; a skipped cache write and a failed hook call — WARNING.
  The error field of the on_step_failed event and its log record carry the full structured render of the terminal failure — the same multi-line text the raised exception carries: the primary reason line, the --- separated step/error block and the verdict block; integrators display it verbatim.
  The on_step_verdict event keeps its structured fields built from the verdict object of the failure — never parsed from the render.

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
      The step failed; `error` is the full rendered failure message — the same structured text carried by the raised exception and the log record: the primary reason line, the --- separated step/error block and the verdict block; display it verbatim.
    "on_step_verdict(step_text: str, category: str, explanation: str, recommendation: str)": |
      The terminal failure of the step carried a verdict; fires after on_step_failed.

      `step_text`: the sentence of the failed step.
      `category`: the verdict label — rot, product_defect or incurable.
      `explanation`: what the LLM saw on the page at the moment of the failure.
      `recommendation`: the recommended engineer action.

      Requirements:
      - Not fired when the verdict was skipped: LLM unavailability logs a WARNING and raises no event
      - Payload values are built from the verdict object of the failure — plain strings, uniform with the other events, never parsed from the rendered `error` text
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
CreatedAt: 10/09/26
Description: |
  Visibility of prettyplay: the logger prettyplay plus the thin StepHooks callback contract; the step failure event carries the full structured render of the terminal failure.
```

**File: `prettyplay/reporting/.usages/hooks.md`**

Change summary: on_step_failed row and new payload section; example extended.

````md
# Step and healing hooks

Domain: event callbacks of prettyplay. Audience: integrators building custom reporting, metrics or CI reactions on top of step execution.

StepHooks is a thin callback contract. The library calls the matching method synchronously while a step executes. The base implementation of every method is a no-op — override only the events you need. Hook implementations are registered on the main library object at the start of a test.

## Events

| Method | When | Payload |
|---|---|---|
| on_step_started | a step started executing | step_text, step_type (action or assertion) |
| on_step_passed | the step finished successfully | step_text, step_type |
| on_step_failed | the step failed | step_text, step_type, error — the **full rendered failure message** (see below) |
| on_step_verdict | the terminal failure carried a verdict (fires after on_step_failed) | step_text, category (rot, product_defect, incurable), explanation, recommendation |
| on_generation_started | a generation attempt started | step_text, attempt (1-based) |
| on_healing_started | healing of a failed cached step started | step_text, category (rot, product_defect, incurable) |
| on_healed | the step healed, cache updated | step_text, explanation (why rot, what changed) |
| on_cache_saved | step code written to the cache | step_text, filename |
| on_cache_skipped | cache write skipped | step_text, reason (e.g. read-only cache) |

## The error payload of on_step_failed

`error` carries the full structured render of the terminal failure — the same multi-line text the raised exception carries and the log record writes: the primary reason line, the `---` separated step/error block and the column-aligned verdict block. Display it verbatim in reports; do not parse it — structured data arrives through on_step_verdict fields. In strict mode on_generation_started and on_healing_started never fire: classification is the only LLM call.

## Example

```python
from prettyplay.reporting import StepHooks


class FailureMonitor(StepHooks):
    def on_step_failed(self, step_text: str, step_type: str, error: str) -> None:
        print(f"failed [{step_type}]: {step_text}\n{error}")  # the full render, verbatim

    def on_step_verdict(self, step_text: str, category: str, explanation: str, recommendation: str) -> None:
        print(f"verdict [{category}]: {step_text} — {explanation} → {recommendation}")

    def on_healed(self, step_text: str, explanation: str) -> None:
        print(f"healed: {step_text} — {explanation}")
```

## Rules

- Handlers run synchronously inside step execution: keep them fast
- A raising handler is logged as a warning and skipped — the test run never fails because of a hook
- on_step_verdict fires only when the verdict exists: LLM unavailability skips the verdict quietly (WARNING in the log)
- The verdict payload is built from the verdict object of the failure — never parsed from the rendered `error` text
- Payload values are plain strings; the attempt counter of on_generation_started is an int
- Step texts land in logs and hooks: never put secrets or personal data into a step sentence
````

### 3. Cell: prettyplay/config (modified)

Change summary: NEW `BrowserConfig`; `Config` gains `browser`, `strict`, `classification_prompt`, loses flat `browser`/`headless`/`browser_endpoint`; `load_config` gains nested env overrides, the removed-flat-key rejection and group-level layered merge; `ConfigurationError` gains the old-key trigger.

**File: `prettyplay/config/CODEMANIFEST`**

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
  The browser settings form the nested browser group of `BrowserConfig` inside `Config` (see `pydantic`): fields inside the group carry no browser_ prefix — the group name scopes them. Env overrides stay flat: PRETTYPLAY_BROWSER_NAME, PRETTYPLAY_BROWSER_SCREEN, PRETTYPLAY_BROWSER_HEADLESS, PRETTYPLAY_BROWSER_ENDPOINT.
  The old flat keys browser, headless and browser_endpoint at the [tool.prettyplay] level are a hard pre-1.0 break: the loader rejects them with a loud actionable `ConfigurationError` naming the new location.
  The screen setting is validated at format level only (see `pydantic`): a WxH-shaped string must carry positive width and height; every other value — including fullscreen and Playwright device names — passes through unresolved, because the device registry belongs to the running Playwright, never to the config.

---

"PrettyplayError::ConfigurationError(message: str)":
  location: loader.py
  annotations: |
    An invalid prettyplay configuration: the loaded [tool.prettyplay] section failed validation or carries removed keys.

    `message`: the rendered actionable text — one line per invalid setting: the setting name, the received value, the allowed values or range; a removed old flat key renders one line naming the key and its new home inside [tool.prettyplay.browser].

    Requirements:
    - Raised by `load_config` with the original pydantic ValidationError chained
    - Catchable with the single library except clause: derives from `PrettyplayError` (see `taxonomy` from Imports)
    - Never carries a verdict: a configuration failure is not a step failure
  properties:
    "message -> str": |
      The rendered actionable validation text.

"BrowserConfig(name: str, screen: str, headless: bool, endpoint: str)":
  location: models.py
  annotations: |
    The nested browser group of the project settings: engine, screen mode, window visibility and the remote endpoint of the browser.

    `name`: browser of the {chromium, firefox, webkit, chrome, msedge} set; chrome and msedge launch the locally installed browser through the driver channel mechanism; default chromium.
    `screen`: the single size setting; empty — Playwright default; WxH — fixed viewport; fullscreen — maximized window on a local headed launch, fixed 1920x1080 under headless and remote connects; any other value — a Playwright device name applied as the full descriptor (see `pydantic`).
    `headless`: run the browser without a visible window of a local launch; default True.
    `endpoint`: ws endpoint of a remote browser; empty — local launch; default empty.

    Requirements:
    - kw_only construction; every field has an empty or neutral default
    - `name` validated against the five-value set; invalid value — loud actionable error
    - a non-empty `endpoint` is a valid ws/wss URL — otherwise a loud actionable error
    - `screen` is validated at format level only: a WxH-shaped value must carry positive integers; values not shaped like WxH — including fullscreen and device names — pass through unresolved

    Constraints:
    - Never resolve device names here: the devices registry belongs to the running Playwright (see `pydantic`)
  properties:
    "name -> str": |
      The browser setting of the {chromium, firefox, webkit, chrome, msedge} set.
    "screen -> str": |
      The single size setting: empty, WxH, fullscreen or a Playwright device name.
    "headless -> bool": |
      Whether the browser runs without a visible window of a local launch; ignored on a remote connect.
    "endpoint -> str": |
      The ws endpoint of a remote browser; empty means the local launch.

"Config(provider: str, browser: BrowserConfig, model: str, generation_model: str, classification_model: str, base_url: str, cache_root: str, generation_prompt: str, classification_prompt: str, strict: bool, generation_attempts: int, healing_attempts: int, send_screenshots: bool)":
  location: models.py
  annotations: |
    Validated project settings — the single source of the immutable configuration part.

    `provider`: the LLM provider of the {openai, anthropic} set; default openai.
    `browser`: the nested browser group — a `BrowserConfig` with the engine, the screen mode, the window visibility and the remote endpoint.
    `model`: main LLM model name.
    `generation_model`: optional generation override; empty — fallback to `model`.
    `classification_model`: optional classification override; empty — fallback to `model`.
    `base_url`: optional custom LLM API endpoint.
    `cache_root`: cache root; empty — default <repo root>/.prettyplay/cache/ resolved by `load_config`.
    `generation_prompt`: user instructions for generation requests; non-empty — a separate USER INSTRUCTIONS block in generation and regeneration requests; classification requests never see it; empty — no block; default empty.
    `classification_prompt`: user instructions for classification requests; non-empty — a separate USER INSTRUCTIONS block in classification requests only; generation requests never see it; takes no part in the step address; empty — no block; default empty.
    `strict`: replay-only mode; True — cached code executes honestly and nothing is ever (re)generated: a cache miss fails as incurable, a failed cached step is at most classified; default False.
    `generation_attempts`: generation attempt budget per step per test; default 3.
    `healing_attempts`: healing attempt budget per step per test; default 2.
    `send_screenshots`: optional screenshot input to the LLM; default False.

    Requirements:
    - kw_only construction; every field has an empty default
    - provider validated against {openai, anthropic}; the `name` inside `browser` against the five-value set; invalid values — loud actionable error
    - attempts are positive integers
    - a non-empty `endpoint` inside `browser` is a valid ws/wss URL — otherwise a loud actionable error
    - `strict`, `classification_prompt` and the `browser` group participate in the layered merge of `load_config` like every other setting

    Constraints:
    - No secret values in fields: LLM API keys are never stored in the config; keys come only from environment variables
  properties:
    "provider -> str": |
      The LLM provider setting: openai or anthropic.
    "browser -> BrowserConfig": |
      The nested browser settings group.
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
    "classification_prompt -> str": |
      The user instructions for classification requests; empty means no instructions block.
    "strict -> bool": |
      Whether the run is replay-only: no generation, no healing.
    "generation_attempts -> int": |
      The generation attempt budget per step per test.
    "healing_attempts -> int": |
      The healing attempt budget per step per test.
    "send_screenshots -> bool": |
      Whether screenshots are attached to LLM requests.
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
    4. Apply environment overrides: each setting is overridden by PRETTYPLAY_<SETTING_UPPERCASE> when the variable is set; the browser group reads PRETTYPLAY_BROWSER_NAME, PRETTYPLAY_BROWSER_SCREEN, PRETTYPLAY_BROWSER_HEADLESS, PRETTYPLAY_BROWSER_ENDPOINT; strict reads PRETTYPLAY_STRICT; classification_prompt reads PRETTYPLAY_CLASSIFICATION_PROMPT
    5. Reject the removed old flat keys: browser, headless or browser_endpoint present at the [tool.prettyplay] level raise `ConfigurationError` immediately — one line per key naming its new home inside [tool.prettyplay.browser] (browser → name, headless → headless, browser_endpoint → endpoint)
    6. Construct `Config`; on a validation failure render the actionable text — one line per invalid setting: the setting name, the received value, the allowed values — and raise `ConfigurationError` with the original ValidationError chained
    7. `overrides` is None — return the file layer as is
    8. Overlay the explicitly set fields of `overrides` onto the file layer (the model with empty defaults, model_copy — see `pydantic`): a field participates when it was passed at construction and is non-empty for strings; the merge reaches inside the `browser` group — explicitly set fields of a passed `BrowserConfig` win over the file layer, untouched group defaults never overwrite file values; `strict` participates when passed explicitly — an explicit False overrides too
    9. Return the effective `Config`

    Requirements:
    - An env override exists for every setting of `Config` (including PRETTYPLAY_STRICT, PRETTYPLAY_CLASSIFICATION_PROMPT and the four PRETTYPLAY_BROWSER_* variables)
    - Scalar env overrides parse by the field type: booleans accept true/false/1/0 case-insensitively, integers parse as decimal integers; an unparseable value raises the loud actionable `ConfigurationError` naming the setting, the received value and the accepted form — never a silent ignore
    - A raw pydantic.ValidationError never leaves the loader
    - The empty cache_root setting is resolved to the absolute default <repo root>/.prettyplay/cache/ at load

    Constraints:
    - Never read or store LLM API keys from any file; keys come only from environment variables
    - Python 3.10 compatibility via the tomli fallback (see `pydantic`)

---

Author: Goga
CreatedAt: 10/09/26
Description: |
  Project settings of prettyplay: the validated [tool.prettyplay] schema with the nested browser group (engine, screen mode, headless, endpoint), the strict replay-only switch, the generation and classification instructions, and the loader with flat env overrides for the group, the removed-flat-key rejection, explicit per-test merging that reaches inside the group and the actionable configuration error.
```

**File: `prettyplay/config/.usages/configuration.md`**

Change summary: new TOML schema with the browser group; extended env table; hard-break section; nested-group layered merge; screen modes table; strict mode section.

````md
# Project configuration

Domain: prettyplay settings. Audience: integrators configuring a test project and CI.

The immutable part of the settings lives in the [tool.prettyplay] section of pyproject.toml. Load it once per test; a test can additionally override specific values programmatically through PrettyConfig.

```toml
[tool.prettyplay]
provider = "openai"
model = "gpt-5"
generation_model = ""      # optional: empty -> model
classification_model = ""  # optional: empty -> model
base_url = ""
cache_root = ""            # empty -> <repo>/.prettyplay/cache/
generation_attempts = 3
healing_attempts = 2
send_screenshots = false
strict = false             # replay-only mode; default false
generation_prompt = ""     # user instructions for generation requests; empty -> no block
classification_prompt = "" # user instructions for classification requests; empty -> no block

[tool.prettyplay.browser]
name = "chromium"          # chromium | firefox | webkit | chrome | msedge
screen = ""                # "" | WxH | fullscreen | Playwright device name
headless = true            # false — run with a visible window
endpoint = ""              # ws endpoint of a remote browser; empty -> local launch
```

## Environment overrides

Every setting has an override for CI — env variable PRETTYPLAY_<SETTING> in upper case; the browser group keeps flat env names:

| Setting | Env override |
|---|---|
| provider | PRETTYPLAY_PROVIDER |
| browser.name | PRETTYPLAY_BROWSER_NAME |
| browser.screen | PRETTYPLAY_BROWSER_SCREEN |
| browser.headless | PRETTYPLAY_BROWSER_HEADLESS |
| browser.endpoint | PRETTYPLAY_BROWSER_ENDPOINT |
| model | PRETTYPLAY_MODEL |
| generation_model | PRETTYPLAY_GENERATION_MODEL |
| classification_model | PRETTYPLAY_CLASSIFICATION_MODEL |
| base_url | PRETTYPLAY_BASE_URL |
| cache_root | PRETTYPLAY_CACHE_ROOT |
| generation_attempts | PRETTYPLAY_GENERATION_ATTEMPTS |
| healing_attempts | PRETTYPLAY_HEALING_ATTEMPTS |
| send_screenshots | PRETTYPLAY_SEND_SCREENSHOTS |
| strict | PRETTYPLAY_STRICT |
| generation_prompt | PRETTYPLAY_GENERATION_PROMPT |
| classification_prompt | PRETTYPLAY_CLASSIFICATION_PROMPT |

## Old flat keys are gone — hard break

`browser`, `headless` and `browser_endpoint` at the `[tool.prettyplay]` level no longer exist (pre-1.0 break). A config carrying them fails loudly at load: the error names each old key and its new home — `browser` → `[tool.prettyplay.browser] name`, `headless` → `[tool.prettyplay.browser] headless`, `browser_endpoint` → `[tool.prettyplay.browser] endpoint`. Migrate before upgrading.

## Per-test overrides — layered merge

PrettyConfig is the public name of the full settings model. A config passed to the test object carries only the explicitly set values; everything else resolves from pyproject+env:

```python
from prettyplay import PrettyTest, PrettyConfig, BrowserConfig

test = PrettyTest(
    cache_key="login-flow",
    config=PrettyConfig(
        strict=True,
        browser=BrowserConfig(screen="fullscreen", headless=False),
    ),
)
```

- An explicitly set field wins over pyproject+env; a field left at its default falls back to the file layer
- The merge reaches inside the nested group: explicitly set fields of a passed BrowserConfig win over the file layer; untouched group defaults never overwrite file values — set only `screen` and the file's `name`, `headless`, `endpoint` keep working
- `strict` participates when passed explicitly — an explicit False overrides the file value too
- File values you did not touch survive: base_url and model set only in pyproject.toml keep working when a config is passed
- One model — one place of validation: file and programmatic values validate identically

## Browsers

The browser matrix: chromium, firefox, webkit (Playwright-bundled engines) plus chrome and msedge — channels that launch the locally installed browser through the chromium engine. A channel requires the real browser installed on the machine; a missing browser fails loudly with an actionable message.

## Screen modes

The `screen` field of the browser group is the single size setting:

| Value | Meaning |
|---|---|
| "" | Playwright default — the current behavior |
| 1280x720 | fixed viewport WxH — pinned in every launch mode |
| fullscreen | a maximized window with the viewport following it on a local headed launch; a fixed 1920x1080 viewport under headless and remote connects (no window exists there) |
| iPhone 13 | a Playwright device name — mobile emulation via the full descriptor: viewport, user agent, touch, is_mobile, device scale factor |

- WxH and device descriptors apply in every launch mode: local headed, local headless, remote connect
- An unknown device name fails loudly with an actionable message suggesting close device names; device names resolve against the devices registry of the running Playwright — the package never hard-codes a device list
- A WxH-shaped value with non-positive numbers fails validation at load; any other string passes through as a device name

## Strict mode

`strict = true` (env PRETTYPLAY_STRICT, per-test override) switches the run to replay-only: cached code executes honestly and nothing is ever (re)generated. A cache miss fails as an incurable step; a failed cached step is at most classified — never regenerated. Classification is the only LLM call strict mode makes; without LLM access the failure raises immediately by step type (see the failures taxonomy).

## Remote execution

A non-empty browser.endpoint switches the test to connecting over the Playwright ws endpoint — a Playwright Server or a hosted browser grid. The endpoint is an address, not a secret: it is valid in the config file; CI rotation goes through the env override. An empty endpoint keeps the local launch; headless does not apply to a connect — window visibility is controlled by the endpoint server.

## Rules

- LLM API keys are never stored in the config file — secrets come only from environment variables: OPENAI_API_KEY for openai, ANTHROPIC_API_KEY for anthropic
- Invalid configuration fails loudly: ConfigurationError names the setting, the received value and the allowed values; the raw pydantic error stays chained for debugging
- The provider set: openai, anthropic; the browser name set: chromium, firefox, webkit, chrome, msedge
- A non-empty browser.endpoint must be a valid ws/wss URL
- The cache root default: <repo root>/.prettyplay/cache/ — resolved from the located pyproject.toml
- generation_prompt reaches generation and regeneration requests only; classification_prompt reaches classification requests only — neither ever invalidates the cache

## Loading

```python
from prettyplay.config import load_config

config = load_config(pyproject_path=None)  # locates pyproject.toml upwards from the current directory
print(config.browser.name, config.browser.screen, config.strict, config.classification_prompt)
```
````

### 4. Cell: prettyplay/driver (modified)

Change summary: `DriverSession.open_context` resolves `screen` (empty / WxH / fullscreen per launch mode / device descriptor with close-name suggestions); global annotations describe the browser group; `PageFacade`/`LocatorFacade` untouched.

**File: `prettyplay/driver/CODEMANIFEST`**

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
  Use `playwright` for the sync API lifecycle, locators, auto-wait, the accessibility snapshot, browser channels, remote connects, the screen modes and the scroll primitives.

  The driver is Playwright sync-only: the async API is out of scope.
  The whole Playwright session — start, browser, contexts, pages — lives in one dedicated driver thread owned by the library: the sync API parks its private event loop on its starting thread, so the thread executing the steps never holds a running asyncio loop (interactive hosts such as IPython and Jupyter keep working between steps).
  Driver-thread calls are strictly sequential: one facade call runs at a time; concurrent driving is out of scope.
  One browser process per test: the session is owned by the test's runtime — no state is shared between tests through the library.
  The start mode branches on the endpoint setting of the browser group of `Config`: empty — local launch with headless and the channel for chrome/msedge; set — connect over the Playwright ws endpoint: headless is ignored, channels do not apply, the `name` setting selects the engine (see `playwright`).
  The screen setting of the browser group resolves at context creation (see `playwright`): the empty value keeps the Playwright default; WxH and device descriptors apply in every launch mode; fullscreen follows the window on a local headed launch and pins to a fixed 1920x1080 viewport where no window exists. Device names resolve against the devices registry of the running Playwright — the package never hard-codes a device list.
  All waits go through locators and expectations; fixed delays (time.sleep and similar) are forbidden.
  The facade surface is a backward-compatibility contract: generated step code works only through `PageFacade` and LocatorFacade, so the existing method set must not break across library releases — extend, never rename or remove.

---

"DriverSession(config: Config)":
  location: session.py
  annotations: |
    Lifecycle owner of the Playwright sync driver and the browser process of one test.

    `config`: project settings; the browser group carries the engine — the `name` of the {chromium, firefox, webkit, chrome, msedge} set, chrome and msedge launch the locally installed browser through the channel mechanism — the `screen` size mode, the `headless` window visibility of a local launch and the `endpoint` switching the start to a remote connect (see `playwright`).

    Requirements:
    - The Playwright session lives in a dedicated driver thread owned by the session: every Playwright-touching operation of this type runs there, and the calling thread never holds a running asyncio loop after any call
  methods:
    "open_context() -> page: PageFacade": |
      Open a fresh isolated context with one page of this test's browser.

      Algorithm:
      1. Start lazily on the first call: constructing the session starts nothing — start the dedicated driver thread, then start Playwright inside it; an empty endpoint — launch the selected engine locally with headless from the browser group and the channel for the chrome/msedge values; a set endpoint — connect over the Playwright ws endpoint of the selected engine: headless is ignored and channels do not apply; a failed launch or connect stops the started driver and closes the thread, so a retry begins from a clean state
      2. Resolve the `screen` setting of the browser group into the context parameters, by precedence: the literal fullscreen value — a local headed launch (headless false, endpoint empty) starts the window maximized through the engine launch arguments and opens the context without a fixed viewport, so the viewport follows the window (see `playwright`); headless or a remote connect — a fixed 1920x1080 viewport, no window exists there; a WxH-shaped value — the viewport dictionary of the parsed width and height, in every launch mode; any other value — a device name: present in the devices registry of the running Playwright — the full descriptor applies to the context (viewport, user_agent, touch, is_mobile, device_scale_factor) in every launch mode; absent — a loud actionable error suggesting close device names from the registry
      3. Create a fresh isolated browser context and its page inside the driver thread with the resolved parameters (see `playwright`)
      4. Wrap the page into `PageFacade` bound to the driver thread and return it

      Requirements:
      - Each result is isolated from every other context
      - A channel launch without the installed browser fails loudly with an actionable message naming the missing browser
      - A failed connect fails loudly with an actionable message naming the endpoint
      - WxH and device descriptors apply in every launch mode: local headed, local headless, remote connect
      - fullscreen is not pixel-identical across environments — a headed run follows the actual screen, headless and remote runs are pinned to 1920x1080

      Constraints:
      - `PageFacade` and `LocatorFacade` stay untouched by the screen modes — the changes live in context creation only
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
CreatedAt: 10/09/26
Description: |
  The Playwright sync driver of prettyplay: the per-test session with local launches, remote ws connects and the screen modes — fixed viewport, device emulation, fullscreen — and the narrow backward-compatible page facade with universal locators and scroll abilities for generated step code.
```

**File: `prettyplay/driver/.usages/facade.md`**

Change summary: minimal extension — intro sentence and one rule about screen modes; surface and example unchanged.

````md
# Driver facade

Domain: the browser facade of prettyplay. Audience: consumers of the page API — the step generation engine and engineers reading or hand-writing step code.

The facade wraps the Playwright sync API. Step code receives a `PageFacade` and works only through it and `LocatorFacade` — never through raw Playwright objects. The method set is a backward-compatibility contract: cached step code keeps working across library upgrades. Each context opens with the screen mode configured in the browser group — the facade surface itself is identical in every mode.

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
- The screen mode of the browser group (empty, WxH, fullscreen, device name) changes only how the context opens — never the facade surface; step code is identical in every mode
- Never put secrets into step actions — step texts and code land in the repository cache
````

### 5. Cell: prettyplay/llm (modified)

Change summary: `classify_failure` gains `user_instructions`; both providers render the classification USER INSTRUCTIONS block as the final block of user content; parity extended; types renamed `LlmProvider` → `LLMProvider` and `OpenAiProvider` → `OpenAIProvider` (LLM initialism convention, uniform with `LLMUnavailableError`); file names unchanged.

**File: `prettyplay/llm/CODEMANIFEST`**

```yaml
Imports:
  - Types:
      - Config
    From: prettyplay/config
  - Types:
      - LLMUnavailableError
    From: prettyplay/failures

Usages:
  conventions: .goga/usages/conventions.md
  openai: .goga/usages/cooks/openai.md
  anthropic: .goga/usages/cooks/anthropic.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `openai` and `anthropic` for the SDK call patterns and the error mapping of the two providers.

  Provider parity is absolute: both providers expose the same operations, accept the same inputs, return the same output shapes and map failures to the same taxonomy; the provider choice is a configuration decision, never a capability difference.
  The user instructions input participates in both provider implementations with identical semantics: generation requests render the generation instructions, classification requests render the classification instructions — each verbatim as a separate USER INSTRUCTIONS block; classification requests never carry the generation instructions and generation requests never carry the classification instructions; a parity requirement, not a capability difference.
  API keys come only from environment variables; never log keys or payloads containing secrets.
  One completion request per attempt: attempt budgets are owned by the calling engine, never by a provider.
  Cached step code never depends on the provider: the provider serves generation and classification only.

---

"LLMProvider()":
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
      - A provider service failure (connectivity, timeout, rate limit, authentication) raises `LLMUnavailableError` naming the provider
      - The generated code contains no provider-specific constructs
    "classify_failure(prompt: str, user_instructions: str, step_text: str, code: str, error: str, snapshot: str, screenshot: bytes | None) -> classification: FailureClassification": |
      Classify a failed cached step.

      `prompt`: the system prompt text supplied by the calling engine — applied verbatim as the system message.
      `user_instructions`: the project's classification instructions supplied by the calling engine from the classification_prompt setting; empty — the request carries no instructions block; non-empty — rendered by the provider implementations verbatim as a separate USER INSTRUCTIONS block of the user content, identically in both.
      `step_text`: the sentence of the failed step.
      `code`: the existing step code that failed.
      `error`: the human-readable description of the failure.
      `snapshot`: the accessibility snapshot of the current page.
      `screenshot`: an optional PNG image of the page; passed only when the project enables screenshots.
      `classification`: the `FailureClassification` verdict.

      Requirements:
      - A provider service failure raises `LLMUnavailableError` naming the provider

"LLMProvider::OpenAIProvider(config: Config)":
  location: openai_provider.py
  annotations: |
    The openai SDK implementation of `LLMProvider` (see `openai`).

    `config`: project settings; the generation model is the effective_generation_model of `config`, the classification model is the effective_classification_model of `config`; the base_url setting of `config` overrides the endpoint when set.

    Algorithm (both operations):
    1. Build the request: the prompt text as the system message, the user content carrying the inputs — a non-empty user_instructions of a generation request renders as a separate USER INSTRUCTIONS block placed after the page API block, before the regeneration-only blocks (CODE, ERROR); a non-empty user_instructions of a classification request renders as the separate USER INSTRUCTIONS block placed last in the user content, after all classification inputs (STEP, CODE, ERROR, PAGE SNAPSHOT)
    2. Send one completion request via the SDK
    3. Extract the text answer; a generation answer unwraps its first markdown-fenced block — an unfenced answer passes through verbatim
    4. An SDK error maps to `LLMUnavailableError` (see `openai`)

"LLMProvider::AnthropicProvider(config: Config)":
  location: anthropic_provider.py
  annotations: |
    The anthropic SDK implementation of `LLMProvider` (see `anthropic`); full parity with the openai implementation.

    `config`: the same settings semantics as the openai implementation.

    Algorithm (both operations):
    1. Build the request: the prompt text as the system message, the user content carrying the inputs — a non-empty user_instructions of a generation request renders as a separate USER INSTRUCTIONS block placed after the page API block, before the regeneration-only blocks (CODE, ERROR); a non-empty user_instructions of a classification request renders as the separate USER INSTRUCTIONS block placed last in the user content, after all classification inputs (STEP, CODE, ERROR, PAGE SNAPSHOT)
    2. Send one message request via the SDK
    3. Extract the text answer; a generation answer unwraps its first markdown-fenced block — an unfenced answer passes through verbatim
    4. An SDK error maps to `LLMUnavailableError` (see `anthropic`)

"create_provider(config: Config) -> provider: LLMProvider":
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
CreatedAt: 10/09/26
Description: |
  The LLM port of prettyplay: one contract, the openai and anthropic SDK implementations in full parity — generation and classification user instructions with identical semantics — and the failure classification verdict.
```

**File: `prettyplay/llm/.usages/classification.md`**

Change summary: call example gains `user_instructions`; USER INSTRUCTIONS placement paragraph.

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
    user_instructions="",  # the classification instructions from the classification_prompt setting; empty — no block
    step_text="click the «Sign in» button",
    code=step_code,
    error="element not found: button «Sign in»",
    snapshot=snapshot_text,
    screenshot=None,
)
print(classification.category, classification.explanation, classification.recommendation)
```

A non-empty `user_instructions` renders as a separate USER INSTRUCTIONS block in the request — the final block of the user content, after all classification inputs. It comes from the classification_prompt setting of the project; generation requests never see it, and classification requests never see the generation instructions.
````

**File: `prettyplay/llm/.usages/providers.md`**

Change summary: user-instructions parity paragraph; rename applied.

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

Both providers expose the same two operations — generate_step_code and classify_failure — with identical inputs, identical output shapes and the identical failure taxonomy: a provider service failure raises LLMUnavailableError; cached step code never depends on the provider. One request per attempt; attempt budgets belong to the calling engine.

User instructions parity: each operation carries its own instructions — generation requests render the generation_prompt setting, classification requests render the classification_prompt setting — as a verbatim USER INSTRUCTIONS block with identical placement semantics in both providers. A parity requirement, not a capability difference.

## Answer shape

generate_step_code returns step code of the fixed form. Models often answer with a fenced python block (```python … ```); the provider unwraps the first fenced block before returning, so the engine receives clean code either way — an answer with no closed fence is returned verbatim and, if unparsable, keeps failing downstream in execution.
````

### 6. Cell: prettyplay/cache — UNCHANGED

No contract change. Strict-mode budget non-consumption is executor behavior; the existing CODEMANIFEST and `.usages/` files (addressing.md, budgets.md, storage.md) stay as is.

### 7. Cell: prettyplay/engine (modified)

Change summary: `classify_step_failure` passes the classification user instructions; annotation cascade — engines pass the `error` field when raising terminal failures and author colon-free reasons; global instructions line covers both prompt settings; inline `classification_prompt` practice documents the USER INSTRUCTIONS input; renames applied (`LLMUnavailableError`, `LLMProvider`, `OpenAIProvider`).

**File: `prettyplay/engine/CODEMANIFEST`**

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
      - LLMUnavailableError
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
      - LLMProvider
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
    - USER INSTRUCTIONS: the project's classification guidance, when configured

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
  The user instructions of the project settings reach their own requests only: the generation_prompt field of `Config` reaches generation and regeneration requests, the classification_prompt field reaches classification requests; neither crosses to the other kind; the instructions take no part in the step address: a cached step never regenerates because the instructions changed.
  The terminal failures raised by the engines carry the full underlying error of the failed code in the error field; reason and message texts are authored without colons — the first line of the rendered message is the primary reason alone.

---

"StepGenerator(config: Config, provider: LLMProvider, cache: StepCache, budgets: RunBudgets, reporter: StepReporter)":
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
      6. On a candidate failure that is an AssertionError — a check that executed and did not hold: stop the retries immediately and classify via `classify_step_failure`; a product_defect verdict raises `ProductDefectError` carrying the verdict and the full failure description of the candidate in the error field, any other verdict raises `IncurableStepError` carrying them — the reason names the failed candidate check; provider unavailability at this classification is skipped quietly with a WARNING — `IncurableStepError` is raised without a verdict, the reason naming the failed candidate check and the error field carrying the full failure description (the failed check is the primary signal, the verdict is enrichment)
      7. On any other candidate failure: repeat from step 1 with the fresh failure description and the fresh snapshot, while attempts remain
      8. On budget exhaustion: classify the last candidate via `classify_step_failure` and raise `IncurableStepError` carrying the verdict and the last candidate failure in the error field — the reason names the exhausted pool; provider unavailability at this classification is skipped quietly with a WARNING, the failure raises without a verdict
      9. Report on_generation_started for every attempt

      Requirements:
      - Every generation request carries the exact page API surface taken from `facade` from Imports: the model always sees the precise list of calls it may use
      - Provider unavailability of a generation request surfaces as `LLMUnavailableError` immediately — no retry on it
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

"classify_step_failure(config: Config, provider: LLMProvider, step_text: str, code: str, error: str, page: PageFacade) -> classification: FailureClassification":
  location: classification.py
  annotations: |
    Classify a step failure: collect the page state and ask the provider — the single classification call for both engines.

    `config`: project settings — the screenshot flag and the classification instructions.
    `provider`: the LLM port.
    `step_text`: the sentence of the failed step.
    `code`: the step code that failed.
    `error`: the human-readable failure description.
    `page`: the page facade of the current test.
    `classification`: the `FailureClassification` verdict.

    Algorithm:
    1. Collect the classification inputs: the step sentence, the failed code, the `error` text, the fresh page snapshot — plus the screenshot when enabled
    2. Ask the provider port classify_failure passing `classification_prompt` as the system prompt and the user instructions — the effective config classification_prompt — when non-empty
    3. Return the verdict

    Constraints:
    - Provider unavailability propagates to the caller: this routine never swallows it — the calling path decides whether it is a terminal infrastructure failure or a quiet verdict skip

"StepHealer(config: Config, provider: LLMProvider, generator: StepGenerator, cache: StepCache, budgets: RunBudgets, reporter: StepReporter)":
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
      3. product_defect: raise `ProductDefectError` carrying the verdict built from the classification and the full underlying error in the error field — the message states what was expected against what was observed; the recommendation reaches the error through the verdict
      4. incurable: raise `IncurableStepError` carrying the verdict and the full underlying error in the error field; the reason names the classification explanation of incurability
      5. rot: regenerate via the generator regenerate — its loop executes the candidate and stores the healed step on success; report on_healed with the explanation of what was rot and what changed, return the healed step
      6. A regeneration budget exhaustion inside step 5 surfaces as `IncurableStepError` carrying the verdict of the step 1 classification — the reason names the exhausted pool; no extra LLM request is made
      7. Provider unavailability of the classification surfaces as `LLMUnavailableError` — an explicit infrastructure failure

      Requirements:
      - Anti-masking: healing may only turn a rot-failed step green; a classified product defect always fails the test
      - The healed code replaces the cached code only after a successful execution
      - Every verdict produced on the paths of this method fully reaches the raised error

---

Author: Goga
CreatedAt: 10/09/26
Description: |
  The agent engine of prettyplay: step code generation with execution in the loop and failed-check classification, the fixed-form execution routine, the shared classification call carrying the classification user instructions, and healing with anti-masking and verdicts on terminal failures.
```

**File: `prettyplay/engine/.usages/generation.md`**

Change summary: classification_prompt bullet; error-field bullet; classification call paragraph; rename applied.

````md
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
- A non-empty classification_prompt setting adds a USER INSTRUCTIONS block to classification requests only — the project's steering for verdict explanations (e.g. answer in a specific language); generation requests never carry it
- A failed check of a candidate (an assertion that executed and did not hold) stops the retries at once: the failure goes to classification — product_defect raises ProductDefectError with the verdict, anything else raises IncurableStepError with it; when the LLM is unavailable at this classification the verdict is skipped quietly (WARNING in the log) and IncurableStepError raises without it; one failed check is spent, never the whole budget
- Other candidate failures (element not found, timeouts) retry with the fresh error and snapshot
- Attempts are budgeted per step per test (default 3); exhaustion raises IncurableStepError carrying the classification verdict of the last candidate — when the LLM is unavailable the verdict is skipped quietly (WARNING in the log) and the failure raises without it
- Raised terminal failures carry the full failure description of the candidate in their error field
- A success stores the step in the cache and returns it
- Provider unavailability of a generation request raises LLMUnavailableError immediately — no retry on it

## Classification call

Both engines classify through one routine:

```python
from prettyplay.engine import classify_step_failure

classification = classify_step_failure(
    config=config,
    provider=provider,
    step_text="click the «Sign in» button",
    code=step_code,
    error="element not found: button «Sign in»",
    page=page,
)
```

The routine collects the fresh page snapshot (plus the screenshot when enabled) and calls the provider with the engine classification prompt; a non-empty classification_prompt setting of the config reaches the request as a USER INSTRUCTIONS block. Provider unavailability propagates: the calling path decides whether it is a terminal infrastructure failure or a quiet verdict skip.

## The fixed form

Generated code is one function receiving exactly one argument — the page facade — and working only through the facade surface: page.find_by_role(...).click(), page.find_by_attribute("data-test-id", "submit").click(), page.find_by_css("form > button.primary"), page.find_by_xpath("//button[@type='submit']"), element.expect_visible(), page.scroll_down(600) and alike. No provider constructs, no direct driver imports, no fixed delays.
````

**File: `prettyplay/engine/.usages/healing.md`**

Change summary: strict-mode rule; verdicts section rewritten.

````md
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
- Generation and healing attempts live in one per-test registry — owned by the runtime of the test — with separate per-step limits (default 3 and 2)
- A regeneration budget exhaustion after rot raises IncurableStepError carrying the verdict of the original rot classification — no extra LLM request
- Provider unavailability during the classification raises LLMUnavailableError — an explicit infrastructure failure
- Healing never runs in strict mode: a failed cached step is at most classified, never regenerated

## Verdicts

Every terminal failure carries its verdict in full and the full underlying error in the error field: the exception message is the structured render — the primary reason, the `---` separated step/error block, the column-aligned verdict block; the same text reaches on_step_verdict (structured fields) and the log record.
````

### 8. Cell: prettyplay (root, modified)

Change summary: NEW imports — `BrowserConfig` (config, for the embedding re-export), `classify_step_failure` (engine, for the strict classification-only path) and `FailureVerdict` (failures, for building verdicts from classifications on the strict path); embedding `->BrowserConfig: {}`; `StepExecutor` gains `config` and the strict execution path with one-render reporting; global annotations cover the re-export and strict mode; renames applied (`LLMUnavailableError`, `LLMProvider`, `OpenAIProvider`).

**File: `prettyplay/CODEMANIFEST`**

```yaml
Imports:
  - Types:
      - Config AS PrettyConfig
      - BrowserConfig
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
      - LLMUnavailableError
      - PrettyplayError
      - FailureVerdict
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
      - LLMProvider
      - create_provider
    From: prettyplay/llm
  - Types:
      - StepGenerator
      - StepHealer
      - run_step_code
      - classify_step_failure
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
  `BrowserConfig` — the public name of the browser settings group — is re-exported by this facade (see the embedding), uniform with `PrettyConfig`.
  Strict mode — the strict field of the effective config — makes the step cycle replay-only: cached code executes honestly, nothing is ever (re)generated. A cache miss is the incurable failure stating that strict forbids generation; a failed cached step is at most classified — never regenerated; without LLM access the failure raises immediately by step type. Classifications are the only LLM calls of a strict run; the generation and healing budgets are never consumed.

---

->PrettyConfig: {}

->BrowserConfig: {}

"PrettyTest(cache_key: str, cache_path: str | None, config: PrettyConfig | None)":
  location: scenario.py
  annotations: |
    The main integrator object — one instance per test. Owns the cache addressing and the isolated browser context of the test; the step cycle is delegated to `StepExecutor`.

    `cache_key`: the mandatory explicit context key — part of the step address; equal keys in the shared root reuse steps across tests.
    `cache_path`: the optional cache subdirectory — part of the address; steps never leak across subdirectories.
    `config`: per-test overrides — the same full model, the nested `BrowserConfig` group and the strict switch included; explicitly set values win, unset/empty fields resolve from pyproject+env; None — everything resolves from pyproject+env, as before.

    Supports the context manager protocol: exit closes the test.

    Algorithm:
    1. Resolve the effective config: `load_config` with overrides = config
    2. Build the own `PrettyplayRuntime` with the effective config — no process-wide singleton exists
    3. Construct the per-test reporter: `StepReporter` with an empty hooks list; add_hooks appends to it
    4. Construct the per-test `StepCache` from the runtime config, `cache_path` and the reporter
    5. Construct `StepGenerator` and `StepHealer` from the runtime config, provider and budgets, the step cache and the reporter
    6. Construct `StepExecutor` with `cache_key`, the cache, the engines, the runtime budgets, the reporter and the runtime config
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

      Delegates to the executor execute with the step type action, the sentence and the test page; failures propagate by kind — `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError` (see `taxonomy`).
      A `PrettyplayError` leaving this method carries its traceback folded to the library boundary: internal library frames — engine, healing, provider — do not appear in what the runner shows.
    "assertion(text: str)": |
      Execute the assertion step `text` — a legitimately failed expectation surfaces as the product defect failure.

      Delegates to the executor execute with the step type assertion; failures propagate by kind — `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError` (see `taxonomy`).
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

"StepExecutor(cache_key: str, cache: StepCache, generator: StepGenerator, healer: StepHealer, budgets: RunBudgets, reporter: StepReporter, config: PrettyConfig)":
  location: executor.py
  annotations: |
    The owner of the step cycle: cache hit — execute; cache miss — generate and store; cached failure — heal. In strict mode the cycle is replay-only: nothing is ever (re)generated.

    `cache_key`: the context key of the owning test object.
    `cache`: the step cache of the test.
    `generator` and `healer`: the engines (see `generation` and `healing` from Imports) — never invoked in strict mode.
    `budgets`: the per-test attempt registry — never consumed in strict mode.
    `reporter`: the visibility point.
    `config`: the effective settings of the test — the source of the strict switch.
  methods:
    "execute(step_text: str, step_type: str, page: PageFacade)": |
      Run one step through the full cycle.

      Algorithm:
      1. Report on_step_started with the sentence and the step type
      2. Build the step identity: `normalize_step_text`, then `StepIdentity` with the test cache key and the step type
      3. Load the cached step. Strict mode and a miss: raise `IncurableStepError` — the reason states that strict mode forbids generation and names the cache miss, the error field empty, the verdict absent; no generation request is made, no budget consumed. A hit: execute its code with `run_step_code` against `page`
      4. On a hit execution failure. Strict mode — classification only: classify via `classify_step_failure` passing the full underlying error; a product_defect classification raises `ProductDefectError` carrying the verdict and the full underlying error — the message names what was expected against what was observed per the classification explanation; a rot or incurable classification raises `IncurableStepError` carrying them — the reason names the classification explanation; both authored colon-free; never regenerated: the healer is not invoked, the healing budget stays untouched, on_healing_started never fires; an unavailable LLM at this classification is skipped quietly with a WARNING and the failure raises immediately by step type without a verdict — an assertion step raises `ProductDefectError`, an action step raises `IncurableStepError`, each carrying the full underlying error, the message/reason stating that the step failed in strict mode without an LLM verdict — colon-free. Otherwise: delegate to the healer heal with the failure description and the scenario context — a healed step is already re-executed and stored by the engine
      5. Otherwise on a miss: the generator generate — the engine stores the step on success
      6. Append the sentence to the scenario context of the test — the previous step texts feed the next generation
      7. Report on_step_passed; on a failed step report on_step_failed with the sentence, the step type and the full render — the rendered message of the raised error, never re-composed; then, when the terminal failure carries a verdict, report on_step_verdict with the sentence and the three verdict fields taken from the verdict object; finally raise by kind — `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError` (see `taxonomy`)

      Requirements:
      - The scenario context lives per test: steps of different tests never mix
      - A cached step executes with no LLM involvement whatsoever
      - An assertion step surfaces a legitimately failed expectation as the product defect failure
      - Strict mode: the only LLM calls are classifications; the generation and healing budgets are never consumed; the engines are never invoked
      - The error text carried by the raised failures: for failed checks — without the AssertionError prefix, the exception type already carries the assertion semantics; for action steps — the full underlying error text with its type
      - One render per terminal failure: the exception message, the on_step_failed error payload and the log record carry the same rendered text

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
    "provider -> LLMProvider": |
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
CreatedAt: 10/09/26
Description: |
  The facade of prettyplay: the per-test scenario object with screenshot abilities, the step cycle executor with the strict replay-only path and verdict reporting, the per-test composition root, and the re-exported settings models — PrettyConfig and BrowserConfig.
```

**File: `prettyplay/.usages/lifecycle.md`**

Change summary: strict mode section; BrowserConfig example; structured render in failures; rename applied.

````md
# Run lifecycle

Domain: how a run is composed — runtimes, contexts, hooks, failures, strict mode. Audience: integrators wiring the library into a runner and CI.

## Composition

One runtime per test: each PrettyTest builds its own runtime — its own configuration, browser process, LLM provider and attempt budgets. Tests never share browser state or budgets through the library; outcomes do not depend on the execution order. Constructing a test is cheap and requires no LLM credentials: the browser starts lazily on the first step. A config passed to the test overrides only the explicitly set values — everything else resolves from pyproject+env; the override reaches inside the nested browser group. When the process exits, every runtime stops its browser and driver synchronously before returning control to the terminal — scripts never leave browser processes behind.

```python
from prettyplay import BrowserConfig, PrettyConfig, PrettyTest

# a strict run with a fullscreen browser
test = PrettyTest(
    cache_key="login",
    config=PrettyConfig(
        strict=True,
        browser=BrowserConfig(screen="fullscreen", headless=False),
    ),
)
```

## Wiring into a framework

The library is framework-agnostic: no plugins, no base classes. Construct the object in your test, call the step methods, let failures propagate — the runner counts them as ordinary test failures. A few lines of glue are enough; the suite runs by the standard runner command.

## Strict mode — replay-only CI runs

`strict = true` (env PRETTYPLAY_STRICT, per-test override) turns the run into an honest replay: cached code executes exactly as stored and nothing is ever (re)generated.

- A cache miss fails the step as IncurableStepError stating that strict mode forbids generation — an expected CI signal: generating a step is a deliberate non-strict act
- A failed cached step is classified when LLM access is configured: product_defect raises ProductDefectError, rot/incurable raises IncurableStepError — never regenerated
- Without LLM access the failure raises immediately by step type — an assertion step raises ProductDefectError, an action step raises IncurableStepError — each carrying the full underlying error; a WARNING is logged
- Classifications are the only LLM calls; generation and healing budgets are never consumed

Team workflow: generate locally where the LLM is reachable, commit the cache directory, run CI fully from the cache with no LLM keys — optionally with strict=true for guaranteed replay-only behavior.

## Hooks

Implement the StepHooks callback contract and register the implementation with add_hooks before the first step — step, generation, healing, cache and verdict events reach the handler synchronously. on_step_failed carries the full rendered failure message; on_step_verdict fires after it whenever the terminal failure carries an LLM verdict. In strict mode generation and healing events never fire.

## Failures

Four kinds reach the runner:

| Kind | Meaning | Reaction |
|---|---|---|
| ProductDefectError | a real regression — also an AssertionError: runners show a failure, not an error; the traceback is folded to the library boundary | treat as a bug — this failure is the value of the suite |
| IncurableStepError | the step cannot be generated or healed — in strict mode also: the cache miss | follow the carried recommendation |
| LLMUnavailableError | the LLM is down | only generation and healing are blocked; cached steps keep running |
| ConfigurationError | the settings are invalid | fix the named setting — the message lists the allowed values |

ProductDefectError and IncurableStepError render one structured message — the primary reason line, the `---` separated step/error block with the full underlying error, the column-aligned verdict block — and the same text reaches the exception message, the on_step_failed hook event and the log. When the LLM is unavailable the verdict is skipped quietly; the failure itself never waits for it.

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
````

**File: `prettyplay/.usages/steps.md`**

Change summary: addressing — instructions take no part; what you see — one structured render.

````md
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
    png = t.get_screenshot()  # full-page PNG bytes of the current state
    t.save_screenshot("artifacts/home.png")  # write full-page PNG to an explicit path
```

- Both require an opened page: call them after the first step of the test
- Nothing is captured automatically on failures — attaching screenshots to reports is the author's decision

## Addressing

The constructor arguments form the cache address: cache_key (mandatory) and cache_path (optional subdirectory). Equal cache keys in the shared root reuse one cached step across tests; a different language, step type or key is a different step. User instructions (generation_prompt, classification_prompt) take no part in the address — a cached step never regenerates because the instructions changed.

## What you see

Step sentences go to the logger prettyplay at info level — the suite output reads as a plain-language scenario. A failed step renders one structured message — the primary reason, the step and the full underlying error, the verdict — identical in the runner output, the log and the on_step_failed hook. Healing, cache writes and skipped writes are reported loudly through the same logger.

## Limitations

Step sentences land in the repository cache, the logs and the LLM requests: never put secrets or personal data into a step.
````

## Dependency Map

```
prettyplay/failures (leaf) ── PrettyplayError ─────────────▶ prettyplay/config
prettyplay/failures ── LLMUnavailableError ────────────────▶ prettyplay/llm
prettyplay/failures ── Product/Incurable/LLMUnavailable, FailureVerdict ▶ prettyplay/engine
prettyplay/failures ── Product/Incurable/LLMUnavailable, PrettyplayError, FailureVerdict ▶ prettyplay (root)
prettyplay/config ── Config ──────────────────────────────▶ prettyplay/driver
prettyplay/config ── Config ──────────────────────────────▶ prettyplay/llm
prettyplay/config ── Config ──────────────────────────────▶ prettyplay/engine
prettyplay/config ── Config AS PrettyConfig, BrowserConfig (NEW edge), load_config ▶ prettyplay (root)
prettyplay/reporting (leaf) ── StepReporter (+hooks usage) ▶ prettyplay/cache, prettyplay/engine, prettyplay (root)
prettyplay/driver ── PageFacade (+facade usage) ──────────▶ prettyplay/engine
prettyplay/cache ── StepCache, StepIdentity, CachedStep, RunBudgets ▶ prettyplay/engine
prettyplay/cache ── StepCache, StepIdentity, normalize_step_text, RunBudgets ▶ prettyplay (root)
prettyplay/llm ── LLMProvider, create_provider ───────────▶ prettyplay (root)
prettyplay/llm ── LLMProvider, FailureClassification (+classification usage) ▶ prettyplay/engine
prettyplay/engine ── StepGenerator, StepHealer, run_step_code, classify_step_failure (+generation, healing usages) ▶ prettyplay (root)
```

No cycles. The only new edge is root ← `BrowserConfig` (config). prettyplay/cache is unchanged.

## Verification Checklist

After implementing each artifact:

1. **prettyplay/failures**
   - `render_terminal_message` composes: reason-only first line (no colons), `---` + step:/error: block (omitted when both empty), `---` + column-aligned verdict block (omitted without verdict); no trailing separator; step code never included
   - `FailureVerdict.render()` aligns explanation/recommendation values to one column; multi-line continuations indent to the value column; category line absent
   - Both error types expose the `error` property; message composed via the render routine; failed-check errors carry no AssertionError prefix in `error`
   - `LLMUnavailableError` name applies everywhere (imports of llm/engine/root updated)
2. **prettyplay/reporting**
   - `on_step_failed` payload and its log record carry the full render; `on_step_verdict` fires with structured fields only
3. **prettyplay/config**
   - `[tool.prettyplay.browser]` validates as the nested group; each old flat key raises a loud actionable `ConfigurationError` naming the new location
   - Env overrides: PRETTYPLAY_BROWSER_{NAME|SCREEN|HEADLESS|ENDPOINT}, PRETTYPLAY_STRICT, PRETTYPLAY_CLASSIFICATION_PROMPT
   - Layered merge reaches inside the group; explicit BrowserConfig fields win; untouched defaults never overwrite file values; explicit False for strict overrides
   - WxH-shaped screen values validate positively; device names and fullscreen pass through
4. **prettyplay/driver**
   - screen="1280x720" pins the viewport in every launch mode; a valid device name applies the full descriptor; an unknown name fails loudly with close-name suggestions from the running registry; fullscreen on a local headed launch = maximized window + viewport following; headless/remote = 1920x1080
   - PageFacade/LocatorFacade surface unchanged (facade check: `python -c "from prettyplay import PageFacade"`)
5. **prettyplay/llm**
   - Non-empty classification instructions render as USER INSTRUCTIONS in classification requests of both providers, never in generation; placement last in user content, identical semantics
6. **prettyplay/engine**
   - classify_step_failure passes the instructions from config.classification_prompt; raised terminal failures carry the error field; reasons colon-free
7. **prettyplay (root)**
   - `from prettyplay import BrowserConfig, PrettyConfig, PrettyTest` works
   - Strict run with cache miss raises IncurableStepError (no generation request, no budget consumption); failed cached step with LLM raises by classification without regeneration; without LLM raises by step type with full underlying error and a WARNING; no generation/healing requests in strict mode
   - One render feeds exception message, log record and on_step_failed error field; traceback folding unchanged
8. **All cells**
   - `goga lint` passes; `goga schema` shows BrowserConfig in prettyplay/config and the root embedding
   - `pytest tests/ -x` passes; `ruff check prettyplay/` clean (per `conventions`)
