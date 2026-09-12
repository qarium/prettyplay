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

`browser`, `headless` and `browser_endpoint` at the [tool.prettyplay] level no longer exist (pre-1.0 break). A config carrying them fails loudly at load: the error names each old key and its new home — `browser` → `[tool.prettyplay.browser] name`, `headless` → `[tool.prettyplay.browser] headless`, `browser_endpoint` → `[tool.prettyplay.browser] endpoint`. The removed legacy env name `PRETTYPLAY_BROWSER` is rejected the same way — the error names `PRETTYPLAY_BROWSER_NAME` as its new home. Migrate both the file keys and the env name before upgrading.

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
product_defect, in strict replay, or when the LLM is unavailable; quit/EOF/SIGINT/unreadable stdin raises the
original terminal failure.

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
