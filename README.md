# prettyplay

UI tests written as plain sentences. Each step sentence is turned into executable
code once — by an LLM, against the live page — and cached in the repository.
Every later run replays the cached code with no LLM involvement at all.

## Installation

```bash
pip install prettyplay
playwright install            # browser binaries for the driver
```

Requires Python 3.10+.

Full documentation: <https://qarium.github.io/prettyplay/>

A complete pytest project — Allure reporting hooks included — lives in the
`example/` directory of the repository; it additionally requires
`allure-pytest` (`pip install allure-pytest`), which the core package does
not depend on.

## Quick start

```python
from prettyplay import PrettyPlay


def test_login():
    t = PrettyPlay("login-flow")
    t.step("open the login page")
    t.step("enter the login and password")
    t.step("click the Sign in button")
    t.expect("the Welcome message appears")
    t.close()
```

Or with the context manager:

```python
with PrettyPlay("login-flow") as t:
    t.step("open the login page")
```

Each `PrettyPlay` is fully self-contained: it owns its settings, its attempt
budgets and its own browser session. `close()` (or leaving the `with` block)
closes the page and stops the whole browser of that test, and every test
starts with fresh attempt budgets. The old process-wide
`prettyplay.get_runtime()` singleton was removed — build
`prettyplay.PrettyplayRuntime(config)` directly if you composed objects over
it.

The constructor arguments form the cache address: `cache_key` (mandatory) and
`cache_path` (optional subdirectory). Equal keys in the shared root reuse one
cached step across tests; a different language, step type or key is a
different step.

The third argument overrides settings per test — only the fields you pass
count: explicitly set values win over pyproject.toml and the environment,
everything else resolves from the file layer as before. Browser settings form
the nested `BrowserConfig` group; an empty string inside the group means unset,
untouched group defaults never overwrite the file values:

```python
from prettyplay import BrowserConfig, PrettyConfig

t = PrettyPlay("login-flow", config=PrettyConfig(browser=BrowserConfig(name="firefox")))
```

Screenshots belong to the author — nothing is captured automatically. Both
methods need a step to have run (the page opens lazily):

```python
png = t.get_screenshot()  # full-page PNG bytes
t.save_screenshot("artifacts/home.png")  # write full-page PNG to a file
```

Stateful page actions excluded from generated code — `page.route`,
`page.clock`, `add_init_script`, tracing, HAR, CDP — are the author's
explicit tools through the escape hatch, which runs inside the driver
worker thread against the genuine page (a step must have run first):

```python
t.run_on_page(lambda page: page.route("**/api/config", lambda r: r.fulfill(json={"mode": "demo"})))
title = t.run_on_page(lambda page: page.title())
```

The action must use the page API only: calling back into the test object
(`t.step`, screenshots, a nested `t.run_on_page`) marshals into the same
worker thread the action runs on — the worker rejects the re-entrant
crossing with a loud error instead of a deadlock.

## What happens on a step

- **cache hit** — the cached code runs; no LLM is contacted
- **cache miss** — the step code is generated (a candidate that must actually
  work on the page), then cached; only successes are cached — after the
  compliance gate (instruction compliance and step adequacy — see
  [Instructions](#instructions)). A candidate
  assertion that legitimately fails stops the retries at once and is
  classified: a real defect fails as `product_defect`; a `rot` or `fixable`
  verdict grants exactly one healing-funded regeneration carrying the
  classification recommendation
- **cached failure** — the failure is classified:
  - `rot` (the UI changed) — the step is regenerated and the cache rewritten
  - `fixable` (the step code is at fault — an ambiguous or wrong locator —
    while the intent stays satisfiable) — regenerated for the same intent,
    the request carrying the classification recommendation
  - `product_defect` — the test fails loudly; nothing is regenerated
  - `incurable` — the step fails with an explanation and a recommendation

A step authored inside a **group block** never takes this per-step path on a
non-strict run: its failure routes to the group recovery — one diagnosis of
the whole group drives a group-scoped regeneration row (see
[Step groups](#step-groups)).

Every execution of step code in the step cycle — cached code and
generation/healing candidates alike — runs under the **settle window** (see
[Settle polling](#settle-polling)): a transient page-state failure re-executes
the same code before any costly move. Steering-dialog turns are the one
exception — see [Interactive steering](#interactive-steering).

**Strict replay-only mode** (`strict = true`) never contacts the LLM for code:
a cache miss fails immediately as `IncurableStepError` ("strict mode forbids
generation — the step is missing from the cache"), and a failed cached step is
at most classified — the only LLM call strict mode ever makes — then raised by
its category (`product_defect` → `ProductDefectError`, everything else — rot
included — → `IncurableStepError`). Nothing is regenerated or healed, no
attempt budget is consumed and the cache is never written. The settle window
still applies to cached code — re-executing it is execution, not generation.
When the LLM is unavailable, the verdict is skipped with a `WARNING` and the
step type alone picks the error kind. This is the natural CI posture: generate
locally, run strict in the pipeline.

## Settle polling

`polling_timeout` (default `None` — off; `0` — explicit disable) opens one
settle window per step execution, measured from the first execution of the
step's code: a transient failure of a pollable kind — timeouts, element-state
races, navigation races, failed checks (a failed `expect(...)` chain or a
plain assert on an immediate read, like `assert videos.count() > 1`) —
re-executes the same code after `polling_delay` (default 0.5 s) until
success or window end. Attempts appear as `settle_retry` log records; no LLM
budget is consumed. Locator ambiguity and Python-level errors of the step
code (syntax, names, types) never poll. Size the window above the longest
auto-wait it must absorb (6.0 covers one exhausted 5 s expectation plus one
re-execution).

Every step also takes two keyword-only parameters: `tries` replaces the time
bound with a count bound for that step (`t.step("open the cart", tries=3)` —
at most 3 executions in total, the first included; exhaustion propagates the
failure, the step never stays green on retries alone), and `delay` is a
quiet pause in seconds before the step's code runs
(`t.expect("the total updates", delay=1.5)` — the step's `on_step_started`
event fires, then the pause, then the code). Invalid values fail loudly at
the call, before any page or LLM involvement.

## Step groups

Steps that form one coherent mini-scenario can be authored as a group with a
shared goal — the group prompt:

```python
with t.group("the checkout flow", speed=50, delay=2) as g:
    g.step("accept the cookie banner")
    g.step("fill the email field")
    g.expect("the order confirmation appears")
```

Inside the block the surface is the ordinary one — `g.step`/`g.expect` with
the `tries`/`delay` parameters — and group membership changes nothing about
addressing: a group step lands at the same cache address it would outside
the block, replays LLM-free, and steps outside the block are ordinary steps
(no ambient rerouting). What changes is failure handling on a non-strict run:
a failed group step is diagnosed once against the whole interaction — the
group prompt, every step trace and the failed step's attempt history — and
the verdict drives a group-scoped recovery row that regenerates the affected
steps forward on the current page, through the same compliance gate and
per-step cache write-back as every caching path. A diagnosed product defect
still fails the test loudly; a root outside the group ends the run honestly;
recovery cycles per group per test are capped (never an infinite loop). The
`speed`/`delay` group parameters pace the block — `delay` pauses quietly
before the first step, `speed` (0–100) inserts
`int((100 − speed) × 30)` ms between steps as a plain library wait.

See the [Groups reference](https://qarium.github.io/prettyplay/reference/groups/)
for the recovery cycle, the budgets and the log records.

## Interactive steering

`interactive = true` (default `false`) arms the steering REPL for local
generation sessions: when a step terminally fails with
`IncurableStepError`, a terminal dialog opens — step, failed code, the
terminal error render, the current page URL, screenshot path, commands —
and every engineer message drives one regeneration whose complete code is
shown for approval with `run? [y/N]` before it executes against the live
page: nothing runs unseen, and a rejected turn enters the history instead
of the page. Local commands serve the context without an LLM request:
`snapshot` (the full accessibility snapshot), `screenshot` (a full PNG
written to a temporary file, path printed), `error` and `code` (the stored
texts) and `quit`. A green turn heals the step and writes it back to the
cache — only after the compliance gate passes (a `high` finding in either
dimension — instruction or adequacy — never reaches the cache: the
violation joins the history and the prompt reopens); every completed turn
— executed, red or rejected — appends its full verbatim record (the
outcome, the URL before → after pair, the complete code, the complete
outcome) to the shared per-step attempt history of every later request;
quit, EOF, SIGINT or an unreadable stdin
raises the original terminal failure. The dialog never opens on
`product_defect`, in strict mode, or when the provider is down, and
consumes no budgets. Dialog openings, guidance lines and declines log at
info level as `steering_opened`, `steering_guidance` and
`steering_declined`. Keep it off in CI — an accidentally opened dialog
would hang the run. This is the steering dialog of a stuck step, not an
interactive host mode (IPython and Jupyter keep working as before).

## Seeing the scenario

Step sentences go to the `prettyplay` logger at info level. The library
configures no handlers — enable logging to see the scenario in the output:

```python
import logging

logging.basicConfig(level=logging.INFO)  # plain unittest runs
```

```ini
# pytest: --log-cli-level=INFO
```

## Configuration

The `[tool.prettyplay]` section of pyproject.toml:

```toml
[tool.prettyplay]
provider = "openai"              # openai | anthropic
model = "gpt-5"
generation_model = ""            # optional: empty -> model
classification_model = ""        # optional: empty -> model
base_url = ""
cache_root = ""                  # empty -> <cwd>/.prettyplay/cache/
generation_prompt = ""           # user instructions for generation; empty -> no instructions block
generation_approve = true        # the two-dimension compliance gate (instructions + step adequacy) before caching; false -> the gate never runs
classification_prompt = ""       # user instructions for classification; empty -> no instructions block
strict = false                   # true -> replay-only mode (no generation, no healing)
interactive = false              # true -> the steering dialog on a terminally stuck step (local sessions)
generation_attempts = 3
healing_attempts = 2
polling_timeout = 6.0            # settle window seconds; omit -> off, 0.0 -> explicit disable
polling_delay = 0.5              # pause between settle re-executions
send_screenshots = false

[tool.prettyplay.browser]
name = "chromium"                # chromium | firefox | webkit | chrome | msedge
screen = ""                      # "" | WxH | fullscreen | Playwright device name
headless = true                  # false -> run with a visible browser window
endpoint = ""                    # ws:// endpoint of a remote browser; empty -> local launch
accept_dialogs = false           # true -> accept (else dismiss) dialogs no in-step capture claims
speed = 100                      # pace of the run, 0-100 %; 100 -> full speed (default)
```

The old flat keys `browser`, `headless` and `browser_endpoint` at the
`[tool.prettyplay]` level are gone — a pre-1.0 hard break: the loader rejects
them with a `ConfigurationError` naming their new home inside
`[tool.prettyplay.browser]`, and the removed legacy env name `PRETTYPLAY_BROWSER`
fails the same way with a hint to use `PRETTYPLAY_BROWSER_NAME`.

`chrome` and `msedge` launch the locally installed browser through the
chromium engine; the browser must be installed on the machine.

### Screen modes

The `screen` setting of the browser group decides the context size:

- `""` — the Playwright default.
- `1280x720` (WxH) — a fixed viewport, in every launch mode.
- `fullscreen` — follows the maximized window on a local headed launch (the
  chromium family launches with `--start-maximized`; firefox/webkit keep their
  plain launch) and pins a fixed 1920x1080 viewport where no window exists —
  headless and remote connects.
- anything else — a Playwright device name (`iPhone 13`, `Pixel 7`, ...):
  the full device descriptor is applied. An unknown name fails loudly with the
  closest registry names suggested.

### Instructions

A non-empty `generation_prompt` is sent verbatim as a `USER INSTRUCTIONS`
block with every generation and regeneration request — it steers the style of
the generated code (e.g. `prefer data-test-id attributes`), never the failure
classification. The instructions are binding, not advisory: while the
compliance gate is on (`generation_approve`, default `true`),
every successfully generated candidate passes an independent compliance check
of two dimensions before it is cached — instruction compliance with these
instructions, and step adequacy (the code must match what the step sentence
says for its step type — neither falling short nor exceeding it, judged from
the verbatim per-step attempt history of what was already tried) — one extra
LLM call through the effective classification model, never the model that
wrote the candidate; a `high` finding in either dimension fails the
attempt and the retry carries the violation with the grown history,
`medium` and `low` findings pass with a `WARNING`, and a malformed verdict is
a loud `ComplianceVerdictError` (the candidate is never cached unchecked).
`generation_approve = false` (env `PRETTYPLAY_GENERATION_APPROVE`) removes the
gate entirely — the old behavior. The instructions are not part of the cache
address: changing them never invalidates cached steps — a cached step runs
unchanged and is never re-gated, so changed instructions need a manual cache
purge to take effect.

A non-empty `classification_prompt` works the same way for classification
requests only — it steers the verdict explanations (e.g. `answer in Russian`),
never generation, and never invalidates cached steps either.

### Remote browsers

A non-empty `endpoint` (e.g. `ws://ci-grid:3000/playwright/chromium`) connects
to a remote Playwright Server or browser grid instead of launching locally:
`headless` does not apply to a connect (window visibility belongs to the
endpoint server) and `chrome`/`msedge` map to the chromium engine — channels
are a local-launch concept. A non-empty endpoint must be a valid ws/wss URL
(otherwise `ConfigurationError` names the setting), and a failed connect fails
loudly with the endpoint in the message.

### Environment overrides

Every setting has a `PRETTYPLAY_<SETTING_UPPER>` environment override for CI —
including `PRETTYPLAY_STRICT` and `PRETTYPLAY_CLASSIFICATION_PROMPT` — and the
browser group reads the flat `PRETTYPLAY_BROWSER_NAME`,
`PRETTYPLAY_BROWSER_SCREEN`, `PRETTYPLAY_BROWSER_HEADLESS`,
`PRETTYPLAY_BROWSER_ENDPOINT`, `PRETTYPLAY_BROWSER_ACCEPT_DIALOGS` and
`PRETTYPLAY_BROWSER_SPEED`. Env
values parse by the field type: booleans
accept `true/false/1/0` case-insensitively, integers parse as decimals, floats
(the polling settings) parse as decimal floats, and an
unparseable value fails loudly with a `ConfigurationError` naming the setting,
the received value and the accepted form.

### Pace

`speed` of the browser group (0–100 inclusive, default 100) controls how fast
the browser executes the run: 100 — full speed, lower values slow the run
down linearly through Playwright's native `slow_mo`
(`int((100 − speed) × 30)` ms between browser operations). One value per
test, fixed at browser start in every launch mode — local headed, local
headless and remote connects alike. An out-of-range or malformed value fails
at configuration load naming `browser.speed`, the received value and the
accepted form (an integer 0-100 inclusive).

An invalid setting fails loudly with a `ConfigurationError`: one line per
setting — the name, the received value and the allowed values.

LLM API keys are never stored in the config file: they come only from the
environment — `OPENAI_API_KEY` for openai, `ANTHROPIC_API_KEY` for anthropic —
and are read lazily on the first request.

### Dialogs

`accept_dialogs` of the browser group controls how the resolver of last
resort settles unclaimed dialogs:

- `true` — every dialog that no in-step stock dialog capture claims is
  accepted
- `false` (default) — unclaimed dialogs are dismissed (the Playwright
  default outcome)
- the resolution runs at the tail of the driver-thread run unit, not at
  the moment the dialog fires: a dialog unclaimed by the step blocks the
  page until the unit ends, which can fail the remainder of the step
- a dialog claimed by a step's in-step stock capture is accepted or dismissed
  by the step itself — the setting does not apply to captured dialogs

## Failure taxonomy

Every library failure derives from `PrettyplayError`:

| Exception | Meaning | Recommended reaction |
|---|---|---|
| ProductDefectError | real product regression | treat as a bug: this failure is the value of the suite |
| IncurableStepError | the step cannot be (re)generated — budget exhausted, step text stale, or a strict-mode cache miss | follow `recommendation`: reword the step or refresh the cache |
| LLMUnavailableError | LLM infrastructure down | restore provider access; cached steps are unaffected |
| ComplianceVerdictError | the compliance gate could not obtain a usable verdict | rerun the step to retry generation; the candidate was never cached |
| ConfigurationError | invalid `[tool.prettyplay]` settings | fix the named setting — the message lists received and allowed values |

`ProductDefectError` and `IncurableStepError` render one structured terminal
message — the first line `ClassName: reason`, a `---` separated
`step:`/`error:` block (the `error:` line carries the decomposed headline
of the underlying error), a conditional `---` separated details section
(`received:`, `cause:`, `Call log:` — present only when the underlying
error carries them), and a `---` separated verdict block with
`explanation:` and `recommendation:` labels at column zero (the `category`
travels in the structured fields, never in the render). The
same single text feeds the exception message, the log record and the
`on_step_failed` hook payload — consumers never re-compose it. The verdict
fields also arrive through the `on_step_verdict` hook. `IncurableStepError`
also carries a `code` attribute — the step code that terminally failed (the
cached code on healing and strict paths, the last candidate on generation);
a field for programmatic consumers only, never rendered and never in hook
payloads.
`ProductDefectError` also derives from `AssertionError`, so any runner counts
it as a failed test, never an error. Tracebacks of library failures are folded
at the `t.step(...)` / `t.expect(...)` call site: internal engine frames
never appear in what the runner shows.

A healed run never turns a `ProductDefectError` into a green test.

## Hooks

```python
from prettyplay.reporting import StepHooks


class Reporter(StepHooks):
    def on_step_started(self, step_text: str, step_type: str) -> None: ...
    def on_step_passed(self, step_text: str, step_type: str) -> None: ...
    def on_step_failed(self, step_text: str, step_type: str, error: str) -> None: ...
    def on_step_verdict(self, step_text: str, category: str, explanation: str, recommendation: str) -> None: ...
    def on_step_finished(self, step_text: str, step_type: str, outcome: str) -> None: ...
    def on_generation_started(self, step_text: str, attempt: int) -> None: ...
    def on_healing_started(self, step_text: str, category: str) -> None: ...
    def on_healed(self, step_text: str, explanation: str) -> None: ...
    def on_cache_saved(self, step_text: str, filename: str) -> None: ...
    def on_cache_skipped(self, step_text: str, reason: str) -> None: ...


t = PrettyPlay("login-flow")
t.add_hooks(Reporter())
```

Hooks can also be wired at construction — pass the list to the keyword-only
`hooks` parameter (`PrettyPlay("login-flow", hooks=[Reporter()])`) and every
event of every step reaches them. `StepHooks` is re-exported from the package
root, so `from prettyplay import StepHooks` works too.

A raising hook never fails the run; the failure is logged. The `error` payload
of `on_step_failed` is the full structured render of the failure — multi-line,
verbatim. `on_step_verdict` fires after `on_step_failed`, only when the
terminal failure carried a real verdict (never for the render-only fallback
recommendation of a verdict-less `IncurableStepError`).

## Cache and CI workflow

The cache lives under `.prettyplay/cache/` as plain Python files — one per
step, carrying its metadata (step sentence, cache key, step type, creation
date) and the step code. The code targets the standard Playwright sync API,
so cached steps keep replaying across library upgrades — the one recorded
break is the switch to the genuine page: caches written against the retired
page facade call methods that no longer exist and fail at replay; purge the
cache directory once and regenerate when upgrading across that change.

Generate locally where the LLM is reachable → commit the cache directory →
CI runs the whole suite from the cache with no LLM keys at all — `strict = true`
turns that posture into a guarantee: a cache miss fails the run instead of
silently generating.

## Limitations

Step sentences and group prompts land in the repository cache, the logs and
the LLM requests: never put secrets or personal data into a step or a group
prompt.
