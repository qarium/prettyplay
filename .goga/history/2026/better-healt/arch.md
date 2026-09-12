# [ARCHITECTURE_PLAN]

## Topic

Actionable failure verdicts for prettyplay: the `fixable` category, the uniform decision table, verdict-carrying
regeneration, honest settle polling, and interactive steering.

Plan path: `.goga/history/2026/better-healt/arch.md`

## Implementation Order

Cells ordered leaves → root; each cell's imports resolve before the cell is touched.

| # | Cell | Status | Order rationale |
|---|---|---|---|
| 1 | `prettyplay/failures` | modify | No Imports; the verdict label set and the terminal-error code field are consumed by everything below |
| 2 | `prettyplay/reporting` | modify | No Imports; `on_step_finished` and the four-label payloads are consumed by engines, steering and the facade |
| 3 | `prettyplay/config` | modify | Depends only on `failures` (existing); the three new settings are consumed by polling, steering, executor |
| 4 | `prettyplay/driver` | modify | Depends on `config` (existing); the pollable map is consumed by `engine/polling` |
| 5 | `prettyplay/llm` | modify | Depends on `config`, `failures` (existing); `FailureClassification` + new request inputs are consumed by `engine` and `engine/steering` |
| 6 | `prettyplay/cache` | usage-only | Depends on `config`, `reporting` (existing); only `budgets.md` semantics are extended — no CODEMANIFEST change |
| 7 | `prettyplay/engine/polling` | **create** | Depends on `driver` only; imported by `engine` and the facade |
| 8 | `prettyplay/engine` | modify | Depends on `engine/polling` (created at step 7) plus existing imports; provides `run_step_code` to steering |
| 9 | `prettyplay/engine/steering` | **create** | Depends on `engine` (modified at step 8) plus `llm`, `cache`, `driver`, `config`, `failures`, `reporting` |
| 10 | `prettyplay` (facade) | modify | Depends on `engine`, `engine/polling`, `engine/steering` and all lower cells (re-exports) |

Shared project artifact created at step 8 (before `engine/steering` references it): `.goga/usages/prompts/generation.md`.

## Artifacts

---

### 1. `prettyplay/failures` — CODEMANIFEST (modify)

Diff against the current manifest:

**REPLACE** (global `Annotations:` block) — add two sentences to the end of the block:

```
  The verdict category label set is four: rot, product_defect, fixable, incurable — the fixable label names the world state where the step code is at fault (an ambiguous or wrong locator or strategy) while the intent stays satisfiable and regeneration for the same intent can help; rot keeps its pure meaning: the UI changed.
  IncurableStepError additionally carries the failed step code — empty when unknown; a field for programmatic consumers only: never rendered, never carried by hook or log payloads.
```

**REPLACE** `FailureVerdict` type annotation line for `category`:

```
`category`: the classification label: rot, product_defect, fixable or incurable — travels in structured fields only, never in the render.
```

**REPLACE** `FailureVerdict` property:

```yaml
    "category -> str": |
      The classification label: rot, product_defect, fixable or incurable.
```

**REPLACE** `IncurableStepError` signature (add `code` before `verdict`):

```yaml
"PrettyplayError::IncurableStepError(step_text: str, reason: str, error: str, code: str, verdict: FailureVerdict | None)":
```

**ADD** to `IncurableStepError` type annotation after the `error` param line:

```
`code`: the step code that terminally failed; filled by the raiser — the cached step code on the healing and strict failure paths, the last candidate code on the generation path; empty — unknown (the strict cache miss carries none).
```

**ADD** to `IncurableStepError` Constraints:

```
- `code` is a field for programmatic consumers only — never rendered, never carried by hook or log payloads; the code lives in the cache and the log
```

**ADD** `IncurableStepError` property (after `error -> str`):

```yaml
    "code -> str": |
      The step code that terminally failed; empty means unknown.
```

**UNCHANGED**: `PrettyplayError`, `render_terminal_message`, `ProductDefectError`, `LLMUnavailableError`, header `Usages`, footer.

#### `prettyplay/failures/.usages/taxonomy.md` (update — full content)

```md
# Failure taxonomy

Domain: failure kinds of prettyplay. Audience: integrators wiring library failures into runner and CI reporting.

Every step failure is one of three distinct kinds; all derive from `PrettyplayError`, so one except clause catches any
prettyplay failure. A fourth kind — the configuration error — joins the base from the config cell.

| Exception | Meaning | When it happens | Recommended reaction |
|---|---|---|---|
| ProductDefectError | real product regression | an assertion expectation legitimately failed | treat as a bug: file it, fix the product — this failure is the value of the suite |
| IncurableStepError | the step cannot be (re)generated | attempt budget exhausted, step text no longer matches reality, ambiguity, strict mode forbids generation | follow the verdict `recommendation`: reword the step or refresh the cache |
| LLMUnavailableError | LLM infrastructure down | generation or healing ran while the provider was unavailable | restore provider access or keys; cached steps are unaffected |
| ConfigurationError | settings are invalid | the first library use loaded an invalid [tool.prettyplay] section | fix the named setting — the message lists the allowed values |

## Verdict categories

ProductDefectError and IncurableStepError may carry a verdict with a category — the classification label the LLM
assigned to the failure. The label set is four:

| Category | Meaning | Consequence inside the library |
|---|---|---|
| rot | the UI changed: selectors, texts, structure | the step is regenerated from the current page |
| product_defect | the expectation legitimately failed | the test fails loudly — never healed green |
| fixable | the step code is at fault (ambiguous or wrong locator/strategy); the intent is satisfiable | the step is regenerated for the same intent, the request carrying the classification recommendation |
| incurable | regeneration cannot help: budget exhausted, text no longer matches reality, ambiguity | the incurable failure carries step, reason, recommendation |

The category travels in the structured fields of the `on_step_verdict` hook event — never in the rendered message.

## The structured failure message

ProductDefectError and IncurableStepError render one structured message — the same text reaches the exception message,
the log record and the `error` field of the `on_step_failed` hook event:

```text
ProductDefectError: кнопка «Войти» осталась невидимой после отправки формы
---
step: Проверить появление кнопки «Войти»
error: Locator expected to be visible
---
explanation:    на странице нет элемента с ролью button и именем «Войти»
recommendation: проверить селектор или текст кнопки в приложении
```

- The first line is the primary reason only — no kind label, no colons; the exception type prefix (rendered by the
  runner) supplies the kind
- The `step:`/`error:` block carries the step sentence and the full underlying error of the failed step code, locator
  details included; for failed checks the `error:` text never carries an AssertionError prefix — the exception type
  already carries the assertion semantics; the block is omitted entirely when both are empty
- The verdict block shows column-aligned `explanation:` and `recommendation:` values — multi-line continuations indent
  to the same value column; the `category:` line is gone — the category travels in the structured fields of
  `on_step_verdict`, never in the render
- Empty blocks are omitted entirely: no verdict → no verdict block; no underlying error → no `error:` line
- The failed step's code is never included — it lives in the cache and the log

## Verdicts on terminal failures

ProductDefectError and IncurableStepError carry an optional verdict: category, explanation, recommendation. When the
LLM is unavailable the verdict is skipped quietly (WARNING in the log) — the failure itself is never delayed or
distorted.

```python
import pytest

from prettyplay.failures import IncurableStepError


def test_reports_only_library_failures():
    with pytest.raises(IncurableStepError) as info:
        ...
    assert info.value.recommendation
    # info.value.verdict may be None when the LLM was unavailable
    # info.value.error carries the full underlying error text ("" when none)
    # info.value.code carries the failed step code ("" when unknown) — programmatic
    # consumers only: never rendered, never in hook or log payloads
```

## Assertion semantics

ProductDefectError is also an AssertionError: unittest reports the failed check as a failure (not an error), pytest
shows it as an ordinary assertion failure, the traceback is folded to the library boundary. Catch it with
`except PrettyplayError` or `except AssertionError` — both work.

## Rules

- Every failure message is actionable: what happened, on which step, what to do next
- A healed run never turns a ProductDefectError into a green test
- LLMUnavailableError never occurs on the cached path — a cached suite runs without any LLM
- One render per terminal failure: integrators parsing messages parse the structured template above; the category
  comes from the `on_step_verdict` event fields, never from the message
```

---

### 2. `prettyplay/reporting` — CODEMANIFEST (modify)

Diff against the current manifest:

**REPLACE** (global `Annotations:`) — two lines change/add:

```
  Step lifecycle events — including the verdict event and the closing finished event — are logged at INFO; a skipped cache write and a failed hook call — WARNING.
  Hook events fire per step or per LLM attempt — never per execution retry: settle re-executions of the same code emit no hook events, their visibility is log-only.
```

**REPLACE** `on_step_verdict` annotation `category` line:

```
`category`: the verdict label — rot, product_defect, fixable or incurable.
```

**ADD** method to `StepHooks` (after `on_step_verdict`):

```yaml
    "on_step_finished(step_text: str, step_type: str, outcome: str)": |
      The step ended — the closing event of every step, fired exactly once regardless of outcome.

      `step_text`: the sentence of the step.
      `step_type`: action or assertion.
      `outcome`: passed or failed.

      Requirements:
      - Fired after on_step_passed, or after on_step_failed — and after on_step_verdict whenever the verdict exists
      - Covers every terminal kind: the step, generation, healing and infrastructure failures alike — a step ends exactly once
```

**REPLACE** `on_generation_started` annotation:

```yaml
    "on_generation_started(step_text: str, attempt: int)": |
      A code generation attempt started; `attempt` is the 1-based attempt number of the LLM request — settle re-executions of the same candidate do not count as attempts.
```

**REPLACE** `on_healing_started` annotation `category` sentence:

```
Healing of a failed cached step started; `category` is the classification label: rot, product_defect, fixable, incurable.
```

**REPLACE** `on_healed` annotation last clause:

```
The step was healed and the cache updated; `explanation` says why it failed and what changed — an interactively healed step reports here too.
```

**UNCHANGED**: `StepReporter`, header `Usages`, footer.

#### `prettyplay/reporting/.usages/hooks.md` (update — full content)

```md
# Step and healing hooks

Domain: event callbacks of prettyplay. Audience: integrators building custom reporting, metrics or CI reactions on top of step execution.

StepHooks is a thin callback contract. The library calls the matching method synchronously while a step executes. The base implementation of every method is a no-op — override only the events you need. Hook implementations are registered on the main library object at the start of a test.

## Events

| Method | When | Payload |
|---|---|---|
| on_step_started | a step started executing | step_text, step_type (action or assertion) |
| on_step_passed | the step finished successfully | step_text, step_type |
| on_step_failed | the step failed | step_text, step_type, error — the **full rendered failure message** (see below) |
| on_step_verdict | the terminal failure carried a verdict (fires after on_step_failed) | step_text, category (rot, product_defect, fixable, incurable), explanation, recommendation |
| on_step_finished | the step ended — always the last step event, regardless of outcome | step_text, step_type, outcome (passed or failed) |
| on_generation_started | a generation attempt started | step_text, attempt (1-based, one per LLM request) |
| on_healing_started | healing of a failed cached step started | step_text, category (rot, product_defect, fixable, incurable) |
| on_healed | the step healed, cache updated | step_text, explanation (why it failed, what changed — interactive healings report here too) |
| on_cache_saved | step code written to the cache | step_text, filename |
| on_cache_skipped | cache write skipped | step_text, reason (e.g. read-only cache) |

## The error payload of on_step_failed

`error` carries the full structured render of the terminal failure — the same multi-line text the raised exception carries and the log record writes: the primary reason line, the `---` separated step/error block and the column-aligned verdict block. Display it verbatim in reports; do not parse it — structured data arrives through on_step_verdict fields. In strict mode on_generation_started and on_healing_started never fire: classification is the only LLM call.

## Attempt semantics

Hook events fire per step or per LLM attempt — never per execution retry. Settle re-executions of the same step code (transient failure absorption) emit no hook events: they are visible only as settle_retry log records. on_step_finished closes every step exactly once, passed or failed.

## Example

```python
from prettyplay.reporting import StepHooks


class FailureMonitor(StepHooks):
    def on_step_failed(self, step_text: str, step_type: str, error: str) -> None:
        print(f"failed [{step_type}]: {step_text}\n{error}")  # the full render, verbatim

    def on_step_verdict(self, step_text: str, category: str, explanation: str, recommendation: str) -> None:
        print(f"verdict [{category}]: {step_text} — {explanation} → {recommendation}")

    def on_step_finished(self, step_text: str, step_type: str, outcome: str) -> None:
        print(f"finished [{outcome}]: {step_text}")

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
```

---

### 3. `prettyplay/config` — CODEMANIFEST (modify)

Diff against the current manifest:

**REPLACE** `Config` signature (three fields inserted after `strict: bool`):

```yaml
"Config(provider: str, browser: BrowserConfig, model: str, generation_model: str, classification_model: str, base_url: str, cache_root: str, generation_prompt: str, classification_prompt: str, strict: bool, polling_timeout: float | None, polling_delay: float, interactive: bool, generation_attempts: int, healing_attempts: int, send_screenshots: bool)":
```

**ADD** to `Config` type annotation after the `strict` param line:

```
`polling_timeout`: the total settle horizon of one step execution in seconds, measured from the first execution of the step code — the facade's internal waits count inside; None — polling disabled (default); 0 — an explicit disable, equivalent to None; positive — the settle window.
`polling_delay`: the pause between re-executions of the same step code in seconds; default 0.5; 0 — re-execute without a pause.
`interactive`: the opt-in interactive steering switch; True — the terminal REPL opens at a terminally stuck step; default False — an accidentally enabled REPL must never hang CI.
```

**ADD** to `Config` Requirements:

```
- polling_timeout is None or a non-negative number — a negative value fails loudly with the received value; polling_delay is non-negative (0 allowed)
- polling_timeout, polling_delay and interactive participate in the layered merge of `load_config` like every other setting — an explicit False or 0.0 overrides the file layer too
```

**ADD** to `Config` Constraints:

```
- A programmatically passed polling_timeout of None is indistinguishable from unset — disable polling per-test with 0.0
```

**ADD** `Config` properties (after `strict -> bool`):

```yaml
    "polling_timeout -> float | None": |
      The total settle horizon of one step execution; None means polling disabled, 0 an explicit disable.
    "polling_delay -> float": |
      The pause between re-executions of the same step code in seconds.
    "interactive -> bool": |
      Whether the interactive steering REPL is enabled; False keeps runs non-interactive.
```

**REPLACE** `load_config` Algorithm step 6 — append:

```
polling_timeout reads PRETTYPLAY_POLLING_TIMEOUT (a decimal float; 0 — an explicit disable), polling_delay reads PRETTYPLAY_POLLING_DELAY, interactive reads PRETTYPLAY_INTERACTIVE
```

**ADD** to `load_config` Requirements:

```
- The three polling and interactive settings parse by the field type: floats parse as decimal floats, the boolean accepts true/false/1/0 case-insensitively; an unparseable value raises the loud actionable `ConfigurationError` naming the setting, the received value and the accepted form
```

**UNCHANGED**: header, `ConfigurationError`, `BrowserConfig`, footer.

#### `prettyplay/config/.usages/configuration.md` (update — full content)

```md
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
cache_root = ""            # empty -> <cwd>/.prettyplay/cache/
generation_attempts = 3
healing_attempts = 2
send_screenshots = false
strict = false             # replay-only mode; default false
polling_timeout = 6.0      # None (default) — polling off; 0 — explicit disable; >0 — settle window seconds
polling_delay = 0.5        # pause between re-executions, seconds
interactive = false        # opt-in steering REPL; default false
generation_prompt = ""     # user instructions for generation requests; empty -> no block
classification_prompt = "" # user instructions for classification requests; empty -> no block

[tool.prettyplay.browser]
name = "chromium"          # chromium | firefox | webkit | chrome | msedge
screen = ""                # "" | WxH | fullscreen | Playwright device name
headless = true            # false — run with a visible window
endpoint = ""              # ws endpoint of a remote browser; empty -> local launch
accept_dialogs = false     # true — automatically accept dialogs outside step-captured dialogs
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
| browser.accept_dialogs | PRETTYPLAY_BROWSER_ACCEPT_DIALOGS |
| model | PRETTYPLAY_MODEL |
| generation_model | PRETTYPLAY_GENERATION_MODEL |
| classification_model | PRETTYPLAY_CLASSIFICATION_MODEL |
| base_url | PRETTYPLAY_BASE_URL |
| cache_root | PRETTYPLAY_CACHE_ROOT |
| generation_attempts | PRETTYPLAY_GENERATION_ATTEMPTS |
| healing_attempts | PRETTYPLAY_HEALING_ATTEMPTS |
| send_screenshots | PRETTYPLAY_SEND_SCREENSHOTS |
| strict | PRETTYPLAY_STRICT |
| polling_timeout | PRETTYPLAY_POLLING_TIMEOUT |
| polling_delay | PRETTYPLAY_POLLING_DELAY |
| interactive | PRETTYPLAY_INTERACTIVE |
| generation_prompt | PRETTYPLAY_GENERATION_PROMPT |
| classification_prompt | PRETTYPLAY_CLASSIFICATION_PROMPT |

## Old flat keys are gone — hard break

`browser`, `headless` and `browser_endpoint` at the [tool.prettyplay] level no longer exist (pre-1.0 break). A config carrying them fails loudly at load: the error names each old key and its new home — `browser` → `[tool.prettyplay.browser] name`, `headless` → `[tool.prettyplay.browser] headless`, `browser_endpoint` → `[tool.prettyplay.browser] endpoint`. Migrate before upgrading.

## Per-test overrides — layered merge

PrettyConfig is the public name of the full settings model. A config passed to the test object carries only the explicitly set values; everything else resolves from pyproject+env:

```python
from prettyplay import PrettyPlay, PrettyConfig, BrowserConfig

test = PrettyPlay(
    cache_key="login-flow",
    config=PrettyConfig(
        strict=True,
        polling_timeout=8.0,
        interactive=True,
        browser=BrowserConfig(screen="fullscreen", headless=False),
    ),
)
```

- An explicitly set field wins over pyproject+env; a field left at its default falls back to the file layer
- The merge reaches inside the nested group: explicitly set fields of a passed BrowserConfig win over the file layer; untouched group defaults never overwrite file values
- `strict` and `interactive` participate when passed explicitly — an explicit False overrides the file value too
- `polling_timeout` passed as None is indistinguishable from unset — disable polling for one test with `0.0`
- File values you did not touch survive: base_url and model set only in pyproject.toml keep working when a config is passed
- One model — one place of validation: file and programmatic values validate identically

## Settle polling

`polling_timeout` is the total settle horizon of one step execution — the window starts with the first execution of
the step's code (cached or candidate); the facade's internal waits count inside it. A transient failure of a pollable
kind with time remaining re-executes the same code after `polling_delay` until success or window end — no LLM budget
is consumed, attempts are visible as settle_retry log records. Locator ambiguity and Python-level errors of the step
code never poll. Polling is opt-in: the default `None` (and `0`) keeps it off; polling applies in strict replay too —
re-executing cached code is execution, not generation.

## Interactive steering

`interactive` (default false, env PRETTYPLAY_INTERACTIVE, per-test override) enables the steering REPL: when a step
terminally fails with IncurableStepError on a non-strict run, a terminal dialog opens showing the step, the failed
code, the error and the verdict; each engineer message drives one regeneration executed against the live page. Opt-in
by design — an accidentally enabled REPL must never hang CI. This is the steering dialog of a stuck step; it is
unrelated to interactive hosts (IPython, Jupyter) — see the library lifecycle docs. The REPL never opens on
product_defect, in strict replay, or when the LLM is unavailable; quit/EOF/SIGINT raises the original terminal
failure.

## Browsers

The browser matrix: chromium, firefox, webkit (Playwright-bundled engines) plus chrome and msedge — channels that launch the locally installed browser through the chromium engine. A channel requires the real browser installed on the machine; a missing browser fails loudly with an actionable message.

## Screen modes

The `screen` field of the browser group is the single size setting:

| Value | Meaning |
|---|---|
| "" | Playwright default — the current behavior |
| 1280x720 | fixed viewport WxH — pinned in every launch mode |
| fullscreen | the viewport follows the window on a local headed launch — the chromium-family engines (chromium, chrome, msedge) start maximized via `--start-maximized`; firefox and webkit keep the plain window; a fixed 1920x1080 viewport under headless and remote connects (no window exists there) |
| iPhone 13 | a Playwright device name — mobile emulation via the full descriptor: viewport, user agent, touch, is_mobile, device scale factor |

- WxH and device descriptors apply in every launch mode: local headed, local headless, remote connect
- An unknown device name fails loudly with an actionable message suggesting close device names; device names resolve against the devices registry of the running Playwright — the package never hard-codes a device list
- A WxH-shaped value with non-positive numbers fails validation at load; any other string passes through as a device name

## Dialogs

`accept_dialogs` of the browser group controls the automatic dialog handling of the driver:

- `true` — every dialog that no step-captured `expect_dialog` block claims is accepted automatically
- `false` (default) — unclaimed dialogs are dismissed (the Playwright default; nothing blocks)
- A dialog captured by a step's `expect_dialog` block is accepted or dismissed by the step itself — the setting does not apply to captured dialogs

## Strict mode

`strict = true` (env PRETTYPLAY_STRICT, per-test override) switches the run to replay-only: cached code executes honestly and nothing is ever (re)generated. A cache miss fails as an incurable step; a failed cached step is at most classified — never regenerated. Settle polling applies to cached code (re-execution, not generation). Classification is the only LLM call strict mode makes; without LLM access the failure raises immediately by step type.

## Remote execution

A non-empty browser.endpoint switches the test to connecting over the Playwright ws endpoint — a Playwright Server or a hosted browser grid. The endpoint is an address, not a secret: it is valid in the config file; CI rotation goes through the env override. An empty endpoint keeps the local launch; headless does not apply to a connect — window visibility is controlled by the endpoint server.

## Rules

- LLM API keys are never stored in the config file — secrets come only from environment variables: OPENAI_API_KEY for openai, ANTHROPIC_API_KEY for anthropic
- Invalid configuration fails loudly: ConfigurationError names the setting, the received value and the allowed values; the raw pydantic error stays chained for debugging
- The provider set: openai, anthropic; the browser name set: chromium, firefox, webkit, chrome, msedge
- A non-empty browser.endpoint must be a valid ws/wss URL
- The cache root default: <cwd>/.prettyplay/cache/ — anchored at the working directory of the run, wherever the pyproject.toml was found
- polling_timeout is None or non-negative; polling_delay is non-negative — violations fail loudly at load
- generation_prompt reaches generation and regeneration requests only; classification_prompt reaches classification requests only — neither ever invalidates the cache

## Loading

```python
from prettyplay.config import load_config

config = load_config(pyproject_path=None)  # locates pyproject.toml upwards from the current directory
print(config.browser.name, config.polling_timeout, config.interactive)
```
```

---

### 4. `prettyplay/driver` — CODEMANIFEST (modify)

Diff against the current manifest:

**ADD** to global `Annotations:` (last line of the block):

```
  The driver knows its own error surface: the fixed pollable map lives in this cell — the single recognition point deciding which failed step-code exceptions a settle window may absorb (see `playwright`).
```

**ADD** type to the Body (after `FrameFacade`):

```yaml
"is_pollable_failure(exc: Exception) -> pollable: bool":
  location: errors.py
  annotations: |
    The fixed pollable map of the facade error surface: decide whether a failed step-code
    exception is a transient page state a settle window may absorb — recognition only,
    no LLM, no settings.

    `exc`: the exception raised by the failed step code.
    `pollable`: True — the kind is transient (the settle window may re-execute the same
    code); False — deterministic or unknown (straight to classification).

    Algorithm:
    1. A failed expectation — an AssertionError that is not the locator-ambiguity
       violation of step 3 — is pollable (see `playwright`): the check executed and did
       not hold; the state may catch up
    2. Recognize the driver kinds by the exception type and the message patterns
       (see `playwright`): timeout — Timeout NNNms exceeded; element state — not visible,
       not enabled, outside of the viewport, detached or stale; navigation and context —
       Execution context was destroyed, Target closed, navigation interrupted mid-flight —
       pollable
    3. Locator ambiguity — the strict mode violation, locator resolved to N elements — is
       not pollable: the elements are there; waiting will not collapse them to one
    4. A Python-level error of the step code — syntax, names, types — is not a driver
       error at all: not pollable
    5. An unrecognized kind is not pollable — the conservative default goes to classification

    Requirements:
    - Pure function: no state, no I/O, deterministic on the exception alone
    - The map is fixed in code: never configured, never asked of an LLM
```

**UNCHANGED**: header imports/usages, `DriverSession`, `PageFacade`, `LocatorFacade`, `DialogFacade`, `FrameFacade`, footer.

#### `prettyplay/driver/.usages/error_kinds.md` (create — full content)

```md
# Error kinds — the pollable map

Domain: which failed step-code exceptions the settle window may absorb. Audience: engineers tuning polling and reasoning about why a failure did or did not retry.

The driver ships a fixed map: `is_pollable_failure(exc)` returns True when the exception kind is transient page state — the settle window may re-execute the same code; False when the failure is deterministic or unknown — it goes straight to classification. Recognition is by exception type and message pattern; no LLM, no settings.

| Kind | Message signature | Pollable |
|---|---|---|
| timeout | `Timeout NNNms exceeded` — locator, action, expectation or navigation wait | yes |
| element state | `element is not visible`, `element is not enabled`, `element is outside of the viewport`, detached/stale element | yes |
| navigation / context | `Execution context was destroyed`, `Target closed`, navigation interrupted mid-flight | yes |
| failed expectation | plain `AssertionError` from an expect_* call — the check executed and did not hold | yes |
| locator ambiguity | `strict mode violation: locator resolved to N elements` | no — the elements are there; waiting will not collapse them to one |
| Python-level error | syntax, name and type errors of the step code itself | no — not a driver error at all |
| unrecognized | anything else | no — conservative default, straight to classification |

## Reading the map

- Pollable kinds typically reflect a page-state race: the previous action finished while a state transition was still in flight; re-executing the same code once the state settles is honest retrying, not masking.
- A failed expectation is pollable because the same code passing later means the state caught up — the check itself stays intact.
- Locator ambiguity is deterministic: the locator itself is at fault, the classification labels it `fixable` and regeneration produces an unambiguous locator.

## Rules

- The map is fixed in code: it never reads settings and never asks an LLM.
- The decision takes only the exception object — pure and deterministic.
```

---

### 5. `prettyplay/llm` — CODEMANIFEST (modify)

Diff against the current manifest:

**REPLACE** `generate_step_code` method — signature and annotation (full replacement):

```yaml
    "generate_step_code(prompt: str, user_instructions: str, step_text: str, previous_steps: list[str], snapshot: str, screenshot: bytes | None, page_api: str, existing_code: str | None, error: str | None, recommendation: str | None, guidance: str | None, guidance_history: list[str]) -> code: str": |
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
      `recommendation`: the diagnosis of the classification that preceded the regeneration; non-empty — rendered as a separate RECOMMENDATION block after the CODE and ERROR blocks: regeneration starts from the diagnosis, not the raw error; None — no block.
      `guidance`: the engineer guidance message of the interactive steering; non-empty — rendered as a separate USER GUIDANCE block; None — no block.
      `guidance_history`: the accumulated steering turns — each a rendered guidance-and-outcome line; non-empty — rendered as a separate HISTORY block after the USER GUIDANCE block; empty — no block.
      `code`: the generated step code of the fixed form, working only through the driver facade; the first markdown-fenced block of the answer is unwrapped — an answer with no closed fence returns verbatim.

      Requirements:
      - A provider service failure (connectivity, timeout, rate limit, authentication) raises `LLMUnavailableError` naming the provider
      - The generated code contains no provider-specific constructs
      - The block order of a regeneration request is fixed: page API, user instructions, CODE, ERROR, RECOMMENDATION, USER GUIDANCE, HISTORY — a non-empty input renders its named block, identically in both implementations
      - The new inputs take no part in step addressing: a cached step never regenerates because they changed
```

**REPLACE** `FailureClassification` — annotation and `category` property:

```yaml
"FailureClassification(category: str, explanation: str, recommendation: str)":
  location: models.py
  annotations: |
    The verdict of a failure classification: what kind of failure it is and what to do about it.

    `category`: one of rot (the UI changed — regeneration is meaningful), product_defect (the expectation legitimately failed), fixable (the step code is at fault — an ambiguous or wrong locator or strategy — while the intent stays satisfiable; regeneration for the same intent can help), incurable (regeneration cannot help).
    `explanation`: why the failure got this category.
    `recommendation`: the recommended engineer action.

    Requirements:
    - `category` is always one of the four labels
    - An unrecognized label of the model answer parses to incurable — the protective fallback in both provider implementations: an unknown verdict never grants a regeneration
  properties:
    "category -> str": |
      The classification label: rot, product_defect, fixable or incurable.
    "explanation -> str": |
      Why the failure got this category.
    "recommendation -> str": |
      The recommended engineer action.
```

**REPLACE** in both `OpenAIProvider` and `AnthropicProvider` Algorithm step 1 — the regeneration rendering clause:

```
the regeneration-only blocks render in the fixed order CODE, ERROR, RECOMMENDATION, USER GUIDANCE, HISTORY — a non-empty input renders its named block, identically in both implementations
```

**UNCHANGED**: header, `LLMProvider` type header, `classify_failure`, `create_provider`, footer.

#### `prettyplay/llm/.usages/classification.md` (update — full content)

```md
# Failure classification

Domain: classifying a failed cached step before healing. Audience: engineers reasoning about healing decisions.

## Categories

| Category | Meaning | Consequence |
|---|---|---|
| rot | the UI changed: selectors, texts, structure | the step is regenerated from the current page and retried |
| product_defect | the expectation legitimately failed | the test fails loudly — never healed green |
| fixable | the step code is at fault (ambiguous or wrong locator/strategy); the intent is satisfiable | the step is regenerated for the same intent, the request carrying the classification recommendation |
| incurable | regeneration cannot help: budget exhausted, text no longer matches reality, ambiguity | the incurable failure carries step, reason, recommendation |

An unrecognized label of the model answer parses to `incurable` — the protective fallback: an unknown verdict never grants a regeneration.

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
```

#### `prettyplay/llm/.usages/providers.md` (update — full content)

```md
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

Regeneration block parity: a regeneration request may carry extra blocks after CODE and ERROR — RECOMMENDATION (the classification diagnosis), USER GUIDANCE (the engineer message of the interactive steering) and HISTORY (the accumulated steering turns), in this fixed order. Both providers render every non-empty block identically at the same position. A parity requirement, not a capability difference.

## Answer shape

generate_step_code returns step code of the fixed form. Models often answer with a fenced python block (```python … ```); the provider unwraps the first fenced block before returning, so the engine receives clean code either way — an answer with no closed fence is returned verbatim and, if unparsable, keeps failing downstream in execution.
```

---

### 6. `prettyplay/cache` — CODEMANIFEST unchanged; usage update

**CODEMANIFEST: no changes.**

#### `prettyplay/cache/.usages/budgets.md` (update — full content)

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

## Healing-funded regenerations

Two verdict-driven regenerations are paid from the healing budget via `try_healing`, exactly one each:

- generation-budget exhaustion with a rot or fixable verdict grants one extra recommendation-carrying regeneration; a repeat failure is terminal — no reclassification
- a failed candidate check (generation loop) classified rot or fixable gets one recommendation-carrying regeneration before the final terminal-kind classification

A refused `try_healing` — the healing budget already exhausted — leaves the failure terminal: no unfunded regeneration ever runs.

Settle re-executions of the same code never consume budgets — re-execution is execution, not generation. Interactive steering attempts never consume budgets either: the human in the loop is the bound.
```

---

### 7. `prettyplay/engine/polling` — CODEMANIFEST (create — full content)

```yaml
Imports:
  - Types:
      - PageFacade
      - is_pollable_failure
    From: prettyplay/driver

Usages:
  conventions: .goga/usages/conventions.md

Annotations: |
  Use `conventions` for code writing rules and testing.

  The settle policy of step-code execution: one window per step execution, created by the step executor from the polling settings, threaded into every execution of the step's code — cached code and candidates alike, replay-strict included.
  The window gates repetitions, never kills a running attempt; re-executions emit no hook events — their visibility is the settle_retry log record alone; no LLM budget is ever consumed.

---

"SettleWindow(timeout: float | None, delay: float)":
  location: window.py
  annotations: |
    The settle horizon of one step execution: when re-executing the same step code may still help and how long to pause between re-executions.

    `timeout`: the total window in seconds; None — polling disabled; 0 — an explicit disable, equivalent to None; positive — the window.
    `delay`: the pause between re-executions in seconds; 0 — re-execute without a pause.
  properties:
    "timeout -> float | None": |
      The total window in seconds; None means polling disabled.
    "delay -> float": |
      The pause between re-executions in seconds.
    "enabled -> bool": |
      Whether polling is active: a positive timeout is set.
  methods:
    "start()": |
      Mark the window start at the first execution of the step code.

      Requirements:
      - Idempotent: only the first call wins — later executions of the same step never shift the start
    "has_remaining() -> remaining: bool": |
      Whether the window still allows a repetition.

      `remaining`: True — time remains and the window is enabled and started.

      Requirements:
      - Checked only before a repetition: the window never interrupts a running attempt
      - False when disabled, not started, or expired — the first execution may consume the whole window

"settle(execute: Callable[[str, PageFacade], None], code: str, page: PageFacade, window: SettleWindow)":
  location: settle.py
  annotations: |
    Execute step code under the settle window: absorb transient page-state failures by re-executing the same code, propagate everything else as-is.

    `execute`: the step-code execution routine passed by the caller.
    `code`: the step code text.
    `page`: the page facade of the current test.
    `window`: the settle window of the current step execution.

    Algorithm:
    1. `window` start — mark the first execution
    2. Call `execute` with `code` and `page`; success — return: the step code worked
    3. On failure: `window` enabled, `is_pollable_failure` of the exception True, `window` has time remaining — pause the `window` delay, repeat from step 2
    4. Otherwise propagate the failure to the caller as-is

    Requirements:
    - Each repetition writes a settle_retry record to the logger prettyplay at INFO: the attempt counter and the failure text; no hook events are emitted
    - No LLM budget is consumed: re-execution is execution, not generation

    Constraints:
    - Never swallow, translate or retry a non-pollable failure — the classification path decides it

---

Author: Goga
CreatedAt: 12/09/26
Description: |
  The settle policy of prettyplay: the per-execution settle window and the re-execution loop absorbing transient page-state failures before any costly move.
```

#### `prettyplay/engine/polling/.usages/settle.md` (create — full content)

```md
# Settle window

Domain: how transient page-state failures are absorbed before any costly move. Audience: engineers tuning polling_timeout and reasoning about retry behavior.

## The window

One settle window per step execution: the step executor creates it from the polling settings and threads it into
every execution of the step's code — cached code and generation candidates alike, replay-strict included.

```python
from prettyplay.engine.polling import SettleWindow, settle

window = SettleWindow(timeout=config.polling_timeout, delay=config.polling_delay)
settle(execute=run_step_code, code=cached_step.code, page=page, window=window)
```

- The window starts at the first execution of the step code — never at the first failure; the facade's internal
  waits count inside it, and the first execution may consume the whole window: no repetitions follow
- The window gates repetitions, never kills a running attempt: the remaining-time check happens only before a repeat
- A failure re-executes the same code after `polling_delay` when its kind is pollable and time remains — until
  success or window end; success continues the step normally
- Everything else propagates as-is: locator ambiguity, Python-level errors, non-pollable and unknown kinds go
  straight to classification

## Visibility

Each repetition writes a `settle_retry` record to the logger prettyplay at INFO — the attempt counter and the failure
text. Re-executions emit no hook events: hook events fire per step or per LLM attempt, never per execution retry.

## Budgets

Re-executions consume no generation or healing budgets and make no LLM requests — polling is cheaper than one
regeneration attempt.

## Rules

- `polling_timeout` None (default) and 0 keep polling off — the settle call degenerates to a single execution
- `polling_delay` 0 re-executes without a pause
- The settle window never re-arms: one window per step execution, shared by every execution inside it
```

---

### 8. `prettyplay/engine` — CODEMANIFEST (modify)

Diff against the current manifest:

**ADD** Imports entry (after the llm entry):

```yaml
  - Types:
      - SettleWindow
      - settle
    From: prettyplay/engine/polling
```

**REPLACE** `Usages.system_prompt` — from inline text to the shared file (content moves verbatim to
`.goga/usages/prompts/generation.md`, see the project artifact below):

```yaml
  system_prompt: .goga/usages/prompts/generation.md
```

**REPLACE** `Usages.classification_prompt` — the category list gains the fixable line after product_defect:

```
    - rot — the UI changed (selectors, texts, structure) and the step can be regenerated for the same intent
    - product_defect — the step works as written but the expected behavior of the application is genuinely broken
    - fixable — the step code is at fault (an ambiguous or wrong locator or strategy) while the intent stays satisfiable; regeneration for the same intent can help
    - incurable — the step sentence no longer matches reality, the intent is ambiguous, or regeneration cannot help
```

**REPLACE** in global `Annotations:` — the stale failed-check line (`A failed check of a candidate stops the generation retries: a check that executed and did not hold is classified, not regenerated.`) which contradicts the new decision table below:

```
  A failed check of a candidate stops the generation-budget retries: a check that executed and did not hold is classified first; a rot or fixable verdict grants exactly one healing-funded regeneration, a repeat failure gets the final terminal-kind classification — the attempt budget is never spent on a legitimately failing assertion beyond it.
```

**ADD** to global `Annotations:` (three sentences at the end of the block):

```
  The uniform decision table on every classification point: product_defect raises ProductDefectError — never healed; rot and fixable regenerate carrying the classification recommendation; incurable raises IncurableStepError carrying the verdict. The category decides, the path only delivers.
  Polling runs before every costly move: every execution of step code — cached code and candidates alike — runs under the settle window threaded through the calling paths; per-attempt classification inside the loops is rejected (LLM cost): an attempt failure retries with the fresh error and snapshot while budget remains.
  on_generation_started fires once per LLM attempt regardless of the settle re-executions inside it; the raised IncurableStepError carries the failed step code in the code field.
```

**REPLACE** `StepGenerator.generate` method — signature unchanged, Algorithm fully replaced, two Requirements lines added:

```yaml
    "generate(identity: StepIdentity, step_text: str, previous_steps: list[str], page: PageFacade, window: SettleWindow) -> step: CachedStep": |
      Generate and store a new step.

      Algorithm:
      1. Ask the budgets registry try_generation for the step identity; a refused attempt is the incurable failure
      2. Collect the request inputs: the page accessibility snapshot, the step sentence, `previous_steps`, and the page API surface from `facade`; add the page screenshot when the project settings enable screenshots
      3. Request step code from the provider port generate_step_code passing `system_prompt` as the system prompt, the page API surface listing taken from `facade`, and the user instructions — the effective config generation_prompt — when non-empty
      4. Execute the candidate under the settle window: `settle` with run_step_code, the candidate code, `page` and `window` — transient failures re-execute inside the window, no LLM budget consumed
      5. On success: build `CachedStep`, save it to the cache, return it
      6. On a failed check — an AssertionError that survived the settle window: classify via `classify_step_failure`; a product_defect verdict raises `ProductDefectError` carrying the verdict and the full failure description of the candidate in the error field; an incurable verdict raises `IncurableStepError` carrying them; a rot or fixable verdict grants exactly one regeneration: try_healing funds it — a refused funding leaves the failure terminal `IncurableStepError` carrying the verdict, the reason naming the exhausted healing pool; the request carries the classification recommendation — a success stores and returns the healed step; a repeat failure gets one final classification deciding only the terminal kind — product_defect raises `ProductDefectError`, anything else raises `IncurableStepError` — no further regeneration; provider unavailability at these classifications is skipped quietly with a WARNING — the failure raises without a verdict as IncurableStepError, the conservative default uniform with the unrecognized-label fallback, the reason naming the failed candidate check
      7. On any other candidate failure: repeat from step 1 with the fresh failure description and the fresh snapshot, while attempts remain
      8. On budget exhaustion: classify the last candidate via `classify_step_failure`; a rot or fixable verdict grants exactly one extra regeneration funded by try_healing and carrying the recommendation — a refused funding leaves the failure terminal `IncurableStepError` carrying the verdict, the reason naming the exhausted healing pool; a repeat failure is terminal `IncurableStepError` carrying the verdict, no reclassification; a product_defect verdict raises `ProductDefectError` carrying the verdict and the last candidate failure in the error field; an incurable verdict raises `IncurableStepError` carrying them — the reason names the exhausted pool; provider unavailability at this classification is skipped quietly with a WARNING, the failure raises without a verdict
      9. Report on_generation_started for every LLM attempt

      Requirements:
      - Every generation request carries the exact page API surface taken from `facade` from Imports: the model always sees the precise list of calls it may use
      - Provider unavailability of a generation request surfaces as `LLMUnavailableError` immediately — no retry on it
      - Provider unavailability of a classification is skipped quietly with a WARNING: the failure raises without a verdict — the failed check itself is the primary signal
      - Exactly one failed check drives the bounded healing rule; the attempt budget is never spent on a legitimately failing assertion beyond it
      - A verdict requested on this path fully reaches the raised error
      - Every verdict-preceded regeneration request carries the classification recommendation — regeneration starts from the diagnosis, not the raw error
      - The raised IncurableStepError carries the failed step code in the code field
```

**REPLACE** `StepGenerator.regenerate` method — full replacement:

```yaml
    "regenerate(identity: StepIdentity, step_text: str, previous_steps: list[str], page: PageFacade, existing_code: str, error: str, recommendation: str, window: SettleWindow) -> step: CachedStep": |
      Regenerate a failed step for healing.

      `recommendation`: the diagnosis of the classification that launched the healing; non-empty — rendered into every request as the RECOMMENDATION block.
      `window`: the settle window of the current step execution.

      Algorithm:
      1. The same loop as the generate method with four differences: every provider request carries `existing_code`, `error` and `recommendation` plus the user instructions — the effective config generation_prompt — when non-empty; attempts consume the healing budget via try_healing; candidate executions run under `settle` with `window`; a failed attempt of any kind — a failed check included — retries with the fresh failure description and the fresh snapshot while attempts remain: no per-attempt classification inside the loop (rejected: LLM cost), the entry classification already guards the anti-masking
      2. A budget exhaustion raises `IncurableStepError` without an extra classification — the verdict of the entry classification is carried, the reason names the exhausted pool
```

**REPLACE** `StepHealer.heal` method — full replacement:

```yaml
    "heal(step: CachedStep, error: str, previous_steps: list[str], page: PageFacade, window: SettleWindow) -> step: CachedStep": |
      Classify and heal a failed cached step.

      `previous_steps`: the sentences of the previous steps of the test, in execution order — scenario context for regeneration.
      `window`: the settle window of the current step execution.

      Algorithm:
      1. Classify the failure via `classify_step_failure` — the verdict is a `FailureClassification`
      2. Report on_healing_started with the category
      3. product_defect: raise `ProductDefectError` carrying the verdict built from the classification and the full underlying error in the error field — the message states what was expected against what was observed; the recommendation reaches the error through the verdict
      4. incurable: raise `IncurableStepError` carrying the verdict and the full underlying error in the error field; the reason names the classification explanation of incurability
      5. rot and fixable: regenerate via the generator regenerate — the request carries the classification recommendation, the loop executes the candidate under the settle window and stores the healed step on success; report on_healed with the explanation of what failed and what changed, return the healed step
      6. A regeneration budget exhaustion inside step 5 surfaces as `IncurableStepError` carrying the verdict of the step 1 classification — the reason names the exhausted pool; no extra LLM request is made
      7. Provider unavailability of the classification surfaces as `LLMUnavailableError` — an explicit infrastructure failure

      Requirements:
      - Anti-masking: healing may only turn a rot- or fixable-failed step green; a classified product defect always fails the test
      - The healed code replaces the cached code only after a successful execution
      - Every verdict produced on the paths of this method fully reaches the raised error; the raised IncurableStepError carries the failed step code in the code field
```

**UNCHANGED**: `format_step_error`, `run_step_code`, `classify_step_failure`, type headers of `StepGenerator`/`StepHealer`, footer.

#### Project artifact `.goga/usages/prompts/generation.md` (create — full content: the current inline `system_prompt` text of the engine cell plus the RECOMMENDATION / USER GUIDANCE / HISTORY input lines and the guidance-following rule)

```md
# Generation system prompt

The system prompt of every step-code generation and regeneration request of prettyplay — referenced by the engine
and steering cells as the `system_prompt` practice. Content is the single source; both referencing cells render it
verbatim as the system message.

---

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
- RECOMMENDATION: the diagnosis of the classification that preceded this regeneration, when present
- USER GUIDANCE: the engineer guidance message of the interactive steering, when present
- HISTORY: the accumulated steering turns, when present

Output exactly one Python code block with one function of the fixed form:

def step(page) -> None:
    ...

Rules:
- The function receives exactly one argument: the page facade — the Playwright-mirroring page API. Never import anything, never use other libraries
- Work only through the page API: the request carries the exact surface listing of the page facade — call nothing outside it
- For an assertion sentence end with an expectation call; for an action sentence perform the actions
- Locating by role and accessible name is preferred; by visible text next; by label or placeholder for form fields
- get_by_test_id and locator(selector) exist for elements without accessible names — the accessibility-first priority stands unless USER INSTRUCTIONS say otherwise
- Dialogs: when the step verifies or steers a dialog, capture it — with page.expect_dialog() as dialog: — perform the triggering action inside the block, read dialog.message and dialog.type, then dialog.accept() or dialog.dismiss()
- Popups and new tabs: capture the opened page — with page.expect_popup() as popup: — trigger the opening action inside the block, work through the popup facade; bring_to_front() raises a page above the others
- Content inside an iframe goes through page.frame_locator(selector) — locate elements within the returned frame
- Scroll abilities exist for scenario scrolling: bring an element into view, scroll by an amount, to the page end or start, inside a scrollable container
- No fixed delays, no sleeps, no explicit waits — the facade waits itself
- RECOMMENDATION and USER GUIDANCE carry the diagnosis and the engineer's intent — follow them when they conflict with your first instinct
- The step must complete exactly what STEP says — nothing more, nothing less
- Output only the code block, no explanations
```

#### `prettyplay/engine/.usages/generation.md` (update — full content)

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
    window=window,
)
```

- The loop: request code → execute against the live page → on failure re-request with the fresh error and snapshot
- Every candidate execution runs under the settle window: transient failures re-execute the same code inside the window (settle_retry log records), no LLM budget consumed; deterministic failures go to the next request or classification
- A non-empty generation_prompt setting adds a USER INSTRUCTIONS block to every generation and regeneration request; classification requests never carry it; changing the instructions never invalidates the cache — cached steps run as stored
- A non-empty classification_prompt setting adds a USER INSTRUCTIONS block to classification requests only; generation requests never carry it

## The decision table

Every classification verdict drives the same table — the category decides, the path only delivers:

| Verdict | Action |
|---|---|
| product_defect | ProductDefectError carrying the verdict — loud, never healed |
| rot, fixable | regeneration carrying the classification recommendation |
| incurable | IncurableStepError carrying the verdict |

## Failed candidate check (bounded healing)

A failed check — an assertion that executed and did not hold, survived the settle window — is classified, then:

- product_defect → ProductDefectError with the verdict; one failed check is spent, never the whole budget
- rot or fixable → exactly one regeneration funded from the healing budget, the request carrying the recommendation as a RECOMMENDATION block; success stores the healed step; a repeat failure gets one final classification deciding only the terminal kind — product_defect → ProductDefectError, anything else → IncurableStepError; no further regeneration
- incurable → IncurableStepError with the verdict
- LLM unavailable at the classification → the verdict is skipped quietly (WARNING in the log) and IncurableStepError raises without it

## Budget exhaustion

Exhaustion of the generation attempts classifies the last candidate: rot or fixable grants exactly one extra
recommendation-carrying regeneration funded from the healing budget — a repeat failure is terminal
IncurableStepError without reclassification; any other verdict is terminal as before. LLM unavailability at this
classification skips the verdict quietly.

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

The routine collects the fresh page snapshot (plus the screenshot when enabled) and calls the provider with the engine classification prompt; a non-empty classification_prompt setting of the config reaches the request as a USER INSTRUCTIONS block. The category set is four: rot, product_defect, fixable, incurable. Provider unavailability propagates: the calling path decides whether it is a terminal infrastructure failure or a quiet verdict skip.

## The fixed form

Generated code is one function receiving exactly one argument — the page facade — and working only through the facade surface: `page.get_by_role(...).click()`, `page.get_by_test_id("submit").click()`, `page.locator("form > button.primary")`, `page.locator("//button[@type='submit']")`, `element.expect_visible()`, `element.press("Enter")`, `with page.expect_dialog() as dialog: ...`, `with page.expect_popup() as popup: ...`, `page.frame_locator("#checkout").get_by_role("button", name="Pay").click()`, `page.scroll_down(600)` and alike. No provider constructs, no direct driver imports, no fixed delays.
```

#### `prettyplay/engine/.usages/healing.md` (update — full content)

```md
# Step healing

Domain: healing a failed cached step. Audience: library internals and engineers reasoning about healed runs.

## Heal

```python
healed = healer.heal(
    step=failed_step, error="element not found: button «Sign in»", previous_steps=["open the login page"], page=page, window=window
)
```

The classification verdict decides the path — the uniform decision table:

| Category | Path |
|---|---|
| rot, fixable | regenerate from the current page within the healing budget (default 2), the request carrying the classification recommendation as a RECOMMENDATION block; execute under the settle window, save back to the cache on success, report loudly |
| product_defect | raise ProductDefectError carrying the verdict — category, explanation and recommendation all reach the exception message, the on_step_verdict hook and the log |
| incurable | raise IncurableStepError carrying the verdict; the reason names the incurability cause |

## Rules

- Anti-masking: healing never turns a product defect into a green test
- The healed code replaces the cached code only after a successful execution
- Generation and healing attempts live in one per-test registry — owned by the runtime of the test — with separate per-step limits (default 3 and 2)
- Inside the regeneration loop no per-attempt classification happens (rejected: LLM cost): a failed attempt of any kind — a failed check included — retries with the fresh error and snapshot while budget remains; the entry classification guards the anti-masking
- A regeneration budget exhaustion raises IncurableStepError carrying the verdict of the original classification — no extra LLM request
- Provider unavailability during the classification raises LLMUnavailableError — an explicit infrastructure failure
- Healing never runs in strict mode: a failed cached step is at most classified, never regenerated
- Interactive steering attempts are separate from healing: they consume no budgets and report their own healings

## Verdicts

Every terminal failure carries its verdict in full and the full underlying error in the error field: the exception message is the structured render — the primary reason, the `---` separated step/error block, the column-aligned verdict block; the same text reaches on_step_verdict (structured fields) and the log record. The terminal errors also carry the failed step code in the code field — a programmatic field, never rendered.
```

---

### 9. `prettyplay/engine/steering` — CODEMANIFEST (create — full content)

```yaml
Imports:
  - Types:
      - IncurableStepError
    From: prettyplay/failures
  - Types:
      - Config
    From: prettyplay/config
  - Types:
      - LLMProvider
    From: prettyplay/llm
  - Types:
      - StepCache
      - CachedStep
      - StepIdentity
    From: prettyplay/cache
  - Types:
      - StepReporter
    From: prettyplay/reporting
  - Types:
      - PageFacade
    Usages:
      - facade
    From: prettyplay/driver
  - Types:
      - run_step_code
    From: prettyplay/engine

Usages:
  conventions: .goga/usages/conventions.md
  system_prompt: .goga/usages/prompts/generation.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `system_prompt` as the system prompt of every guided regeneration request.
  Use `facade` from Imports as the single source of the page API surface for regeneration requests.

  The opt-in human-in-the-loop escape hatch of a terminally stuck step: opened by the step executor exactly at the moment an IncurableStepError would propagate — never on product_defect, never in replay-strict, never when the LLM is unavailable.
  Every guidance turn is a regeneration request carrying a USER GUIDANCE block plus the conversation history; the result executes against the live page — every turn has a measurable green or red outcome; no free-form conversation.
  Interactive attempts consume no generation or healing budgets — the human in the loop is the bound; the settle window never re-arms inside the dialog: a failed execution returns to the guidance prompt immediately.
  The guidance is one-shot: logged, never persisted. Nothing hangs: quit, EOF and SIGINT end the dialog and the original terminal failure propagates.

---

"StepSteering(config: Config, provider: LLMProvider, cache: StepCache, reporter: StepReporter | None)":
  location: steering.py
  annotations: |
    The interactive steering dialog of a terminally stuck step: show the full failure context, take engineer guidance, regenerate with it, execute against the live page, heal or decline.

    `config`: the effective settings of the test — the generation instructions of the config join every request.
    `provider`: the LLM port for guided regeneration requests.
    `cache`: the step cache for the healed write-back.
    `reporter`: the visibility point — the healed step is reported loudly; omitted — the hook-less default reporter.
  methods:
    "steer(failure: IncurableStepError, identity: StepIdentity, previous_steps: list[str], page: PageFacade) -> healed: CachedStep | None": |
      Run the steering dialog over a terminal failure.

      `failure`: the terminal failure about to propagate — the source of the step sentence, the failed code, the underlying error and the verdict.
      `identity`: the address of the stuck step — the healed step is written back under it.
      `previous_steps`: the sentences of the previous steps of the test — scenario context for regeneration.
      `page`: the live page facade of the test.
      `healed`: the healed cached step on a successful guided execution; None — the dialog declined or died: the caller propagates the original failure.

      Algorithm:
      1. Render the context banner: the step sentence, the failed code, the underlying error, the verdict (explanation and recommendation), a fragment of the fresh accessibility snapshot, a screenshot path
      2. Read the guidance line; quit, EOF or SIGINT — return None
      3. A local command runs without the LLM: snapshot — the full accessibility snapshot; screenshot — a full PNG written to a temporary file with the path printed; error and code — the stored texts; back to step 2
      4. A guidance message builds one regeneration request via the provider: `system_prompt` as the system prompt, the page API surface from `facade`, the step sentence of `failure` and `previous_steps` as the scenario context, the fresh accessibility snapshot plus the screenshot when the project settings enable screenshots, the user instructions — the effective config generation_prompt — when non-empty, existing_code from the failed code of `failure`, error from its underlying error, the message as the guidance and the accumulated turns as the guidance history
      5. Execute the regenerated code via `run_step_code` against `page`
      6. Success: build `CachedStep` with `identity`, save it to the cache, report on_healed with an explanation naming the interactive healing, return the healed step
      7. A failed execution: show the outcome, append the turn to the history, return to step 2 — no re-execution of the same code, the settle window never re-arms
      8. Provider unavailability of the request: the dialog ends, return None

      Requirements:
      - The write-back happens only after a successful execution
      - No generation or healing budget is consumed; no polling applies
      - The dialog never outlives the failure: every exit path either heals or returns None

      Constraints:
      - Never persist the guidance into the cache file

---

Author: Goga
CreatedAt: 12/09/26
Description: |
  The interactive steering of prettyplay: the opt-in terminal REPL taking engineer guidance over a terminally stuck step — guided regeneration, live execution, healed write-back or honest decline.
```

#### `prettyplay/engine/steering/.usages/steering.md` (create — full content)

```md
# Interactive steering

Domain: the opt-in REPL that rescues a terminally stuck step with engineer guidance. Audience: engineers running generation sessions locally.

## When the dialog opens

The step executor opens the dialog at the exact moment an `IncurableStepError` would propagate — budget exhausted,
incurable verdict, failed-check final classification — when `interactive` is on and the run is not strict. It never
opens on `product_defect` (a dialog must never repaint a red test green), never in replay-strict, and never when the
LLM is unavailable.

## The dialog

```text
── step "click Checkout" — about to raise IncurableStepError ──────────
intent:   click the checkout button
code:     page.get_by_text("Checkout").click()
error:    TimeoutError: Timeout 10000ms exceeded ... element is not visible
verdict:  fixable — the button is behind the "Terms" modal;
          recommendation: dismiss the modal first, then click.

commands: snapshot | screenshot | error | code | quit
guidance> the modal has id=terms — close it via
          page.get_by_label("Close").click() first
⟳ regenerating with USER GUIDANCE … executing against the live page …
✓ step green — healed step written to the cache
```

- Local commands answer without the LLM: `snapshot` prints the full accessibility snapshot, `screenshot` writes a
  full PNG to a temporary file and prints the path, `error` and `code` reprint the stored texts
- Every other line is guidance: one regeneration request carrying a USER GUIDANCE block plus the conversation
  history — the result executes against the live page, every turn ends green or red
- A red turn shows the outcome and returns to the guidance prompt immediately — no re-execution loop, the settle
  window does not re-arms inside the dialog
- `quit`, EOF (Ctrl+D) and SIGINT (Ctrl+C) end the dialog and the original terminal failure propagates — nothing hangs

## Effects

- A green turn writes the healed step back to the cache — only after the successful execution — and reports
  on_healed; the test continues
- Guidance is one-shot: it lands in the log, never in the cache file
- Interactive attempts consume no generation or healing budgets — the human in the loop is the bound

## Rules

- Opt-in by design: `interactive` defaults to false; PRETTYPLAY_INTERACTIVE must never leak into CI environments
- The dialog is a v1 terminal surface: no chat mode, no manual code paste — every turn must have a measurable outcome
```

---

### 10. `prettyplay` (facade) — CODEMANIFEST (modify)

Diff against the current manifest:

**ADD** two Imports entries (after the engine entry):

```yaml
  - Types:
      - SettleWindow
      - settle
    From: prettyplay/engine/polling
  - Types:
      - StepSteering
    From: prettyplay/engine/steering
```

**ADD** to global `Annotations:` (one sentence at the end of the block):

```
  The interactive gate lives in the executor: the steering dialog opens exactly at a caught IncurableStepError on a non-strict interactive run — never on product_defect, never in replay-strict, never when the LLM is unavailable.
```

**REPLACE** `StepExecutor` signature (insert `steering: StepSteering` after `healer: StepHealer`) and add the param doc line:

```yaml
"StepExecutor(cache_key: str, cache: StepCache, generator: StepGenerator, healer: StepHealer, steering: StepSteering, budgets: RunBudgets, reporter: StepReporter, config: PrettyConfig, provider: LLMProvider)":
```

```
    `steering`: the interactive steering of terminally stuck steps — invoked only on a non-strict interactive run; never in strict mode.
```

**REPLACE** `StepExecutor.execute` method — full replacement:

```yaml
    "execute(step_text: str, step_type: str, page: PageFacade)": |
      Run one step through the full cycle.

      Algorithm:
      1. Report on_step_started with the sentence and the step type
      2. Build the step identity: `normalize_step_text`, then `StepIdentity` with the test cache key and the step type; create a `SettleWindow` of this step execution from the polling settings of the effective config
      3. Load the cached step. Strict mode and a miss: raise `IncurableStepError` — the reason states that strict mode forbids generation and names the cache miss, the error field empty, the verdict absent; no generation request is made, no budget consumed. A hit: execute its code under the settle window — `settle` with `run_step_code`, the cached code, `page` and the window; replay-strict included: re-executing cached code is execution, not generation
      4. On a hit execution failure. Strict mode — classification only: classify via `classify_step_failure` passing the full underlying error; a product_defect classification raises `ProductDefectError` carrying the verdict and the full underlying error; a rot, fixable or incurable classification raises `IncurableStepError` carrying them — the reason names the classification explanation; both authored colon-free; never regenerated: the healer is not invoked, the healing budget stays untouched, on_healing_started never fires; an unavailable LLM at this classification is skipped quietly with a WARNING and the failure raises immediately by step type without a verdict — colon-free. Otherwise: delegate to the healer heal with the failure description, the scenario context and the window — a healed step is already re-executed and stored by the engine
      5. Otherwise on a miss: the generator generate with the window — the engine stores the step on success
      6. Steering intercept — wrap the engine paths of steps 4 and 5: a raised `IncurableStepError` on a non-strict interactive run goes to the steering steer with the failure, the identity, the scenario context and `page` before it propagates; a healed return continues as success — the cache write-back already happened inside the dialog; None — the original failure propagates unchanged. The intercept never triggers on `ProductDefectError`, on `LLMUnavailableError`, in strict mode or when interactive is off
      7. Append the sentence to the scenario context of the test — the previous step texts feed the next generation
      8. Report on_step_passed; on a failed step report on_step_failed with the sentence, the step type and the full render — the rendered message of the raised error, never re-composed; then, when the terminal failure carries a verdict, report on_step_verdict with the sentence and the three verdict fields taken from the verdict object; finally raise by kind — `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError` (see `taxonomy`)
      9. Report on_step_finished with the sentence, the step type and the outcome — passed or failed — exactly once at the very end of every step, after every other event, regardless of outcome

      Requirements:
      - The scenario context lives per test: steps of different tests never mix
      - A cached step executes with no LLM involvement whatsoever
      - An assertion step surfaces a legitimately failed expectation as the product defect failure
      - Strict mode: the only LLM calls are classifications; the generation and healing budgets are never consumed; the engines are never invoked; the settle window still applies to the cached code
      - The error text carried by the raised failures: for failed checks — without the AssertionError prefix, the exception type already carries the assertion semantics; for action steps — the full underlying error text with its type; formatted by `format_step_error`
      - One render per terminal failure: the exception message, the on_step_failed error payload and the log record carry the same rendered text
      - One settle window per step execution: created in step 2, threaded into every engine call; the first execution marks its start
      - on_step_finished fires exactly once per step — the closing event of the cycle
```

**REPLACE** `PrettyPlay` Algorithm steps 5–6:

```
5. Construct `StepGenerator`, `StepHealer` and `StepSteering` from the runtime config, provider, budgets, the step cache and the reporter
6. Construct `StepExecutor` with `cache_key`, the cache, the engines, the steering, the runtime budgets, the reporter, the runtime config and the runtime provider
```

**UNCHANGED**: header `Usages`, embeddings, `PrettyPlay` methods and properties, `PrettyplayRuntime`, footer.

#### `prettyplay/.usages/steps.md` (update — full content)

```md
# Writing steps

Domain: authoring UI tests as plain sentences. Audience: engineers writing tests and integrators wiring the library into a test framework.

## A test as a scenario

```python
from prettyplay import PrettyPlay


def test_login():
    t = PrettyPlay("login-flow")
    t.step("open the login page")
    t.step("enter the login and password")
    t.step("click the «Sign in» button")
    t.expect("the «Welcome back» message appears")
    t.close()
```

Or with the context manager:

```python
with PrettyPlay("login-flow") as t:
    t.step("open the login page")
```

## Step kinds

- step(text) — performs what the sentence says
- expect(text) — verifies what the sentence says; a legitimately failed expectation fails the test as a product defect

## Screenshots

Two author-facing abilities on the test object:

```python
with PrettyPlay("login-flow") as t:
    t.step("open the login page")
    png = t.get_screenshot()  # full-page PNG bytes of the current state
    t.save_screenshot("artifacts/home.png")  # write full-page PNG to an explicit path
```

- Both require an opened page: call them after the first step of the test
- Nothing is captured automatically on failures — attaching screenshots to reports is the author's decision

## Addressing

The constructor arguments form the cache address: cache_key (mandatory) and cache_path (optional subdirectory). Equal cache keys in the shared root reuse one cached step across tests; a different language, step type or key is a different step. User instructions (generation_prompt, classification_prompt) take no part in the address — a cached step never regenerates because the instructions changed.

## What you see

Step sentences go to the logger prettyplay at info level — the suite output reads as a plain-language scenario. A failed step renders one structured message — the primary reason, the step and the full underlying error, the verdict — identical in the runner output, the log and the on_step_failed hook. Every step ends with one closing on_step_finished event (passed or failed). Healing, cache writes and skipped writes are reported loudly through the same logger. Transient failures absorbed by the settle window appear as settle_retry records — the step itself stays green.

## Limitations

Step sentences land in the repository cache, the logs and the LLM requests: never put secrets or personal data into a step.
```

#### `prettyplay/.usages/lifecycle.md` (update — full content)

```md
# Run lifecycle

Domain: how a run is composed — runtimes, contexts, hooks, failures, strict mode, polling, steering. Audience: integrators wiring the library into a runner and CI.

## Composition

One runtime per test: each PrettyPlay builds its own runtime — its own configuration, browser process, LLM provider and attempt budgets. Tests never share browser state or budgets through the library; outcomes do not depend on the execution order. Constructing a test is cheap and requires no LLM credentials: the browser starts lazily on the first step. A config passed to the test overrides only the explicitly set values — everything else resolves from pyproject+env; the override reaches inside the nested browser group. When the process exits, every runtime stops its browser and driver synchronously before returning control to the terminal — scripts never leave browser processes behind.

```python
from prettyplay import BrowserConfig, PrettyConfig, PrettyPlay

# a strict run with a fullscreen browser
test = PrettyPlay(
    cache_key="login",
    config=PrettyConfig(
        strict=True,
        browser=BrowserConfig(screen="fullscreen", headless=False),
    ),
)

# a local generation session with polling and steering
test = PrettyPlay(
    cache_key="login",
    config=PrettyConfig(polling_timeout=8.0, interactive=True),
)
```

## Wiring into a framework

The library is framework-agnostic: no plugins, no base classes. Construct the object in your test, call the step methods, let failures propagate — the runner counts them as ordinary test failures. A few lines of glue are enough; the suite runs by the standard runner command.

## Strict mode — replay-only CI runs

`strict = true` (env PRETTYPLAY_STRICT, per-test override) turns the run into an honest replay: cached code executes exactly as stored and nothing is ever (re)generated. Settle polling still applies to cached code — re-executing it is execution, not generation.

- A cache miss fails the step as IncurableStepError stating that strict mode forbids generation — an expected CI signal: generating a step is a deliberate non-strict act
- A failed cached step is classified when LLM access is configured: product_defect raises ProductDefectError, rot/fixable/incurable raises IncurableStepError — never regenerated
- Without LLM access the failure raises immediately by step type — an assertion step raises ProductDefectError, an action step raises IncurableStepError — each carrying the full underlying error; a WARNING is logged
- Classifications are the only LLM calls; generation and healing budgets are never consumed

Team workflow: generate locally where the LLM is reachable, commit the cache directory, run CI fully from the cache with no LLM keys — optionally with strict=true for guaranteed replay-only behavior.

## Settle polling

`polling_timeout` (default None — off; 0 — explicit disable) opens one settle window per step execution, measured
from the first execution of the step's code: a transient failure of a pollable kind re-executes the same code after
`polling_delay` (default 0.5 s) until success or window end. Attempts appear as settle_retry log records; no LLM
budget is consumed. Locator ambiguity and Python-level errors of the step code never poll.

## Interactive steering

`interactive = true` (env PRETTYPLAY_INTERACTIVE, per-test override) arms the steering REPL for local generation
sessions: when a step terminally fails with IncurableStepError, a terminal dialog opens — step, failed code, error,
verdict, snapshot fragment, screenshot path — and every engineer message drives one regeneration executed against the
live page. A green turn heals the step and writes it back to the cache; quit/EOF/SIGINT raises the original terminal
failure. The dialog never opens on product_defect, in strict mode, or without LLM access, and consumes no budgets.
Keep it off in CI — an accidentally opened dialog would hang the run.

## Hooks

Implement the StepHooks callback contract and register the implementation — either pass the list to the keyword-only constructor parameter `hooks` (events are captured from the very construction) or call add_hooks before the first step. Step, generation, healing, cache and verdict events reach the handler synchronously. on_step_failed carries the full rendered failure message; on_step_verdict fires after it whenever the terminal failure carries an LLM verdict; on_step_finished closes every step exactly once, passed or failed. In strict mode generation and healing events never fire.

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
from prettyplay import PrettyPlay

test = PrettyPlay("login-flow")
test.step("open the login page")
test.step("enter the login and password")
test.expect("the «Welcome back» message appears")
test.close()  # stops this test's browser and driver thread
```

Generation of the step cache remains a batch workflow: prefer a plain script or a pytest run over a REPL when generating many steps. The `interactive` setting of the previous section is a different thing entirely: it is the steering dialog of a stuck step, not a host mode.
```

---

## Dependency Map

```
failures ◀── config ◀── driver ◀── engine/polling ◀── engine ◀── engine/steering ◀── prettyplay (facade)
   ▲           ▲           ▲              ▲              ▲                ▲                  ▲
   │           │           │              │              │                │                  │
   ├───────────┼───────────┼──────────────┼──────────────┼────────────────┼──────────────────┤
   │           │           └── llm ───────┼──────────────┼─── llm ────────┼──────────────────┤
   ├── llm ────┘               ▲          │              │                │                  │
   │                           │          │              │                │                  │
   ├── engine, steering, facade│          │              │                │                  │
   │                           │          │              │                │                  │
reporting ◀── cache ◀──────────┼──────────┼──────────────┼── cache ───────┼──────────────────┤
   ▲                          │          │              │                │                  │
   ├── engine, steering, facade           │              ├── driver ──────┼── driver ────────┤
   │                                      │              ├── config ──────┼── config, llm ──┤
   └──────────────────────────────────────┴──────────────┴────────────────┴──────────────────┘
```

Edge list (source imports from target):

| Source | Imports from |
|---|---|
| `prettyplay/config` | failures |
| `prettyplay/driver` | config |
| `prettyplay/llm` | config, failures |
| `prettyplay/cache` | config, reporting |
| `prettyplay/engine/polling` | driver |
| `prettyplay/engine` | engine/polling, driver, config, failures, llm, cache, reporting |
| `prettyplay/engine/steering` | engine, llm, cache, driver, config, failures, reporting |
| `prettyplay` (facade) | engine, engine/polling, engine/steering, config, failures, driver, cache, llm, reporting |

No cycles: `engine → engine/polling` and `engine/steering → engine` are different subcells; nothing imports
`engine/steering` except the facade.

## Verification Checklist

After implementing each artifact, verify:

- [ ] `goga lint` passes with zero errors across all 10 cells (nested subcells included)
- [ ] `goga schema` shows `prettyplay/engine/polling` and `prettyplay/engine/steering` as children of `prettyplay/engine` with correct dependencies
- [ ] failures: `FailureVerdict.category` accepts and documents four labels; `IncurableStepError.code` round-trips; the structured render never embeds the code
- [ ] reporting: `on_step_finished` exists on `StepHooks`, fires once per step in the executor, INFO level; verdict/healing payloads carry `fixable`
- [ ] config: the three settings load from pyproject, respond to `PRETTYPLAY_POLLING_TIMEOUT` / `PRETTYPLAY_POLLING_DELAY` / `PRETTYPLAY_INTERACTIVE`, merge in per-test overrides (explicit `0.0`/`False` override too); negative `polling_timeout` fails loudly
- [ ] driver: `is_pollable_failure` matches every kind of the error-kinds table; ambiguity and Python-level errors return False; pure function
- [ ] llm: `generate_step_code` renders RECOMMENDATION / USER GUIDANCE / HISTORY blocks in the fixed order, identically in both providers; unknown classification labels parse to `incurable`
- [ ] engine/polling: window starts at first execution; `has_remaining` gates repetitions only; disabled window degenerates to a single execution; settle_retry logged at INFO; no hook calls
- [ ] engine: generate step 6 bounded rule (one healing-funded regeneration + final terminal-kind classification); step 8 exhaustion rule (one regeneration, terminal without reclassification); regenerate carries recommendation, no per-attempt classification; heal routes rot AND fixable to regeneration with recommendation; terminal errors carry `code`
- [ ] engine/steering: banner renders full context; local commands answer without LLM; quit/EOF/SIGINT return None; success writes back and reports on_healed; no budgets consumed; no polling inside
- [ ] facade: executor creates one window per step, threads it everywhere, strict path settles but never regenerates, intercept catches only `IncurableStepError` on non-strict interactive runs, `on_step_finished` closes every step
- [ ] Usages: every new/updated usage file referenced in its CODEMANIFEST resolves on disk; `system_prompt` file referenced by both engine and steering
- [ ] `pytest tests/ -x` green; `ruff check` clean — per `.goga/usages/conventions.md`
