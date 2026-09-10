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
