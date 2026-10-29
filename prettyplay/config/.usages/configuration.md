# Project configuration

Domain: prettyplay settings. Audience: integrators configuring a test project and CI.

The immutable part of the settings lives in the [tool.prettyplay] section of pyproject.toml. Load it once per test (the `config` parameter left `None`); a test can instead take a programmatically assembled PrettyConfig verbatim — the file layer never loads for it.

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
probe_timeout = 0          # candidate probe bound, seconds; 0 -> off (the page default applies)
llm_request_attempts = 3  # total sends per LLM request; 1 disables request retries
send_screenshots = false
strict = false             # replay-only mode; default false
polling_timeout = 6.0      # None (default) — polling off; 0 — explicit disable; >0 — settle window seconds
polling_delay = 0.5        # pause between re-executions, seconds
interactive = false        # opt-in steering REPL; default false
generation_prompt = ""     # user instructions for generation requests; empty -> no block
generation_approve = true  # the instruction compliance gate before caching; false -> never runs (the old behavior)
classification_prompt = "" # user instructions for classification requests; empty -> no block

[tool.prettyplay.browser]
name = "chromium"          # chromium | firefox | webkit | chrome | msedge
screen = ""                # "" | WxH | fullscreen | Playwright device name
headless = true            # false — run with a visible window
endpoint = ""              # ws endpoint of a remote browser; empty -> local launch
accept_dialogs = false     # true — accept (else dismiss) dialogs no in-step capture claims, at the run-unit tail
speed = 100            # pace of the run: 0–100 %, 100 — full speed (default)
timeout = 30           # page default action timeout, seconds; explicitly applied at page creation; 0 disables the timeout, not auto-wait
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
| browser.speed | PRETTYPLAY_BROWSER_SPEED |
| browser.timeout | PRETTYPLAY_BROWSER_TIMEOUT |
| model | PRETTYPLAY_MODEL |
| generation_model | PRETTYPLAY_GENERATION_MODEL |
| classification_model | PRETTYPLAY_CLASSIFICATION_MODEL |
| base_url | PRETTYPLAY_BASE_URL |
| cache_root | PRETTYPLAY_CACHE_ROOT |
| generation_attempts | PRETTYPLAY_GENERATION_ATTEMPTS |
| healing_attempts | PRETTYPLAY_HEALING_ATTEMPTS |
| probe_timeout | PRETTYPLAY_PROBE_TIMEOUT |
| llm_request_attempts | PRETTYPLAY_LLM_REQUEST_ATTEMPTS |
| send_screenshots | PRETTYPLAY_SEND_SCREENSHOTS |
| strict | PRETTYPLAY_STRICT |
| polling_timeout | PRETTYPLAY_POLLING_TIMEOUT |
| polling_delay | PRETTYPLAY_POLLING_DELAY |
| interactive | PRETTYPLAY_INTERACTIVE |
| generation_prompt | PRETTYPLAY_GENERATION_PROMPT |
| generation_approve | PRETTYPLAY_GENERATION_APPROVE |
| classification_prompt | PRETTYPLAY_CLASSIFICATION_PROMPT |

## Old flat keys are gone — hard break

`browser`, `headless` and `browser_endpoint` at the [tool.prettyplay] level no longer exist (pre-1.0 break). A config carrying them fails loudly at load: the error names each old key and its new home — `browser` → `[tool.prettyplay.browser] name`, `headless` → `[tool.prettyplay.browser] headless`, `browser_endpoint` → `[tool.prettyplay.browser] endpoint`. The removed legacy env name `PRETTYPLAY_BROWSER` is rejected the same way — the error names `PRETTYPLAY_BROWSER_NAME` as its new home. Migrate both the file keys and the env name before upgrading.

## The programmatic configuration

PrettyConfig is the public name of the full settings model. A config passed to the test object is the complete effective configuration — taken verbatim; pyproject.toml and the PRETTYPLAY_* environment never load for it, and fields left at their defaults keep the model defaults:

```python
from prettyplay import PrettyPlay, PrettyConfig, BrowserConfig

test = PrettyPlay(
    cache_key="login-flow",
    config=PrettyConfig(
        model="gpt-5",
        strict=True,
        polling_timeout=8.0,
        interactive=True,
        browser=BrowserConfig(screen="fullscreen", headless=False),
    ),
)
```

- A passed config needs no pyproject.toml anywhere — construction never searches the filesystem and never raises FileNotFoundError
- Every field of the passed model is the effective value; unset fields keep the model defaults (empty strings, 0, False, None) — nothing back-fills from pyproject or env
- The file layer is the `config=None` path: everything resolves from pyproject+env, as before
- `polling_timeout=None` means polling off; disable it explicitly per test with `0.0` — the same values as in the file layer
- One model — one place of validation: the constructor validates the assembled model exactly like the loaded one; an invalid value fails loudly at construction

## Settle polling

`polling_timeout` is the total settle horizon of one step execution — the window starts with the first execution of
the step's code (cached or candidate); the step code's own auto-waits count inside it. A transient failure of a pollable
kind with time remaining re-executes the same code after `polling_delay` until success or window end — no LLM budget
is consumed, attempts are visible as settle_retry log records. Locator ambiguity and Python-level errors of the step
code never poll. Polling is opt-in: the default `None` (and `0`) keeps it off; polling applies in strict replay too —
re-executing cached code is execution, not generation.

## Request retries of the LLM port

`llm_request_attempts` (default 3, env PRETTYPLAY_LLM_REQUEST_ATTEMPTS, programmatically assembled config) caps
the physical sends of one LLM request — generation, failure classification, group diagnosis and
the compliance verdict alike: the initial request included, retries of transient provider
failures (connection, timeout, 408/429, 5xx) happen inside the request with fixed delays and
never consume generation or healing budgets.

```python
from prettyplay import PrettyConfig, PrettyPlay

test = PrettyPlay(
    cache_key="flaky-ci",
    config=PrettyConfig(llm_request_attempts=5),  # tolerate a longer provider outage
)
```

- `1` disables request retries — fully the old single-send behavior
- a value below `1` fails loudly at configuration load — never a silent ignore
- the retry delays are fixed policy (1–10 s with jitter; a Retry-After above 10 s terminates
  the request instead of waiting) — not configurable; only the attempt count is

## Pace

`speed` of the browser group (a percentage, 0–100 inclusive, default 100) controls how fast the
browser executes the run: 100 — full speed, exactly the default behavior; lower values slow the
run down linearly — 0 is the slowest supported pace. It is an ordinary setting of every layer — the
file, the env (PRETTYPLAY_BROWSER_SPEED) and a programmatically assembled config:

```python
from prettyplay import BrowserConfig, PrettyConfig, PrettyPlay

test = PrettyPlay(
    cache_key="demo",
    config=PrettyConfig(browser=BrowserConfig(speed=40)),
)
```

- One value per test, fixed for the whole run — it applies at browser start in every launch mode
  (local headed, local headless, remote connect); replays and strict runs take it identically
- An out-of-range or malformed value fails at configuration load — the error names the setting,
  the received value and the allowed range; never a silent ignore

## Page action timeout and the probe bound

`timeout` of the browser group (seconds, int or float, default 30) is the default action timeout
of the page — explicitly applied at the creation of every page; the default 30 mirrors the
Playwright library default made visible, 0 disables the timeout without disabling auto-wait: an unready action can wait indefinitely. It is the baseline every probe restores to: a positive
`probe_timeout` setting (seconds, int or float, default 0) shortens the default action timeout
of every candidate execution inside the generation and healing loops — a wrong locator fails in
the probe bound instead of burning the page default — and after every candidate the page default
restores to the configured baseline.

```python
from prettyplay import BrowserConfig, PrettyConfig, PrettyPlay

test = PrettyPlay(
    cache_key="demo",
    config=PrettyConfig(
        probe_timeout=3,  # candidates fail fast on a wrong locator
        browser=BrowserConfig(timeout=60),  # the page baseline every probe restores to
    ),
)
```

- Replayed cached code and steering always run under the baseline — a probe never leaks its
  bound onto later executions
- Navigations keep their own default timeout — neither setting touches `set_default_navigation_timeout`
- Negative or non-finite values of either setting fail at configuration load — the error names
  the setting, the received value and the allowed range; never a silent ignore

## Interactive steering

`interactive` (default false, env PRETTYPLAY_INTERACTIVE, programmatically assembled config) enables the steering REPL: when a step
terminally fails with IncurableStepError on a non-strict run, a terminal dialog opens showing the step, the failed
code, the error and the verdict; each engineer message drives one regeneration executed against the live page. Opt-in
by design — an accidentally enabled REPL must never hang CI. This is the steering dialog of a stuck step; it is
unrelated to interactive hosts (IPython, Jupyter) — see the library lifecycle docs. The REPL never opens on
product_defect, in strict replay, or when the LLM is unavailable; quit/EOF/SIGINT/unreadable stdin raises the
original terminal failure.

## The instruction compliance gate

The user instructions of `generation_prompt` are binding for generated step code: every
successfully executed candidate passes an independent compliance check before it is
cached. The gate is the default; switch it off consciously when the extra LLM call per
successful generation matters more than the enforcement.

```toml
[tool.prettyplay]
generation_prompt = "Prefer id attributes for locating elements"
generation_approve = true   # default; false -> the gate never runs (the old behavior)
```

Env override (booleans: true/false/1/0, case-insensitive; anything else fails loudly):

```bash
export PRETTYPLAY_GENERATION_APPROVE=false
```

In a programmatically assembled config the passed switch is the effective one — the file layer never loads:

```python
config = PrettyConfig(generation_approve=False, model="gpt-5")
scenario = PrettyPlay(cache_key="smoke", config=config)
```

Notes for the engineer:
- while the gate is on, every successful generation costs one extra LLM call (the verdict
  request) through the effective classification model
- a `high` finding fails the attempt and the retry carries the violation text — loud
  errors instead of silent ignoring
- changing `generation_prompt` does not invalidate cached steps: the step address stays
  instruction-free, so purge the cache manually after changing instructions — replayed
  cached code is never re-gated
- the gate never runs when `generation_prompt` is empty, regardless of the switch

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

`accept_dialogs` of the browser group controls how the resolver of last resort settles unclaimed dialogs:

- `true` — every dialog that no in-step stock dialog capture claims is accepted
- `false` (default) — unclaimed dialogs are dismissed (the Playwright default outcome)
- The resolution runs at the tail of the driver-thread run unit, not at the moment the dialog fires: a dialog unclaimed by the step blocks the page until the unit ends, which can fail the remainder of the step
- A dialog claimed by a step's in-step stock capture is accepted or dismissed by the step itself — the setting does not apply to captured dialogs

## Strict mode

`strict = true` (env PRETTYPLAY_STRICT, programmatically assembled config) switches the run to replay-only: cached code executes honestly and nothing is ever (re)generated. A cache miss fails as an incurable step; a failed cached step is at most classified — never regenerated. Settle polling applies to cached code (re-execution, not generation). Classification is the only LLM call strict mode makes; without LLM access the failure raises immediately by step type.

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

A programmatically assembled config adopts verbatim — the file layer never loads:

```python
from prettyplay.config import PrettyConfig, adopt_config

adopted = adopt_config(PrettyConfig(model="gpt-5"))
# the passed values; the empty cache_root resolved to <cwd>/.prettyplay/cache
print(adopted.browser.name, adopted.cache_root)
```

- `adopt_config` never reads pyproject.toml and never reads PRETTYPLAY_* — it works with no pyproject anywhere
- The test object calls it automatically for every passed config; call it directly only when you assemble a config outside a test
