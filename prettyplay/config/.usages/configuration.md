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
from prettyplay import PrettyPlay, PrettyConfig, BrowserConfig

test = PrettyPlay(
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
| fullscreen | the viewport follows the window on a local headed launch — the chromium-family engines (chromium, chrome, msedge) start maximized via `--start-maximized`; firefox and webkit keep the plain window; a fixed 1920x1080 viewport under headless and remote connects (no window exists there) |
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
