# Browser setup

Engines, screen modes and remote browsers of the `[tool.prettyplay.browser]`
group. For integrators choosing how the test browser launches.

The whole Playwright session — start, browser, contexts, pages — lives in one
dedicated driver thread owned by the library: the thread executing the steps
never holds a running asyncio loop, so interactive hosts such as IPython and
Jupyter keep working between steps. One browser process per test: the session
is owned by the test's runtime — no state is shared between tests through the
library.

## Engines

```toml
[tool.prettyplay.browser]
name = "chromium"    # chromium | firefox | webkit | chrome | msedge
```

The browser matrix: `chromium`, `firefox`, `webkit` (Playwright-bundled
engines) plus `chrome` and `msedge` — channels that launch the locally
installed browser through the chromium engine. A channel requires the real
browser installed on the machine; a missing browser fails loudly with an
actionable message.

## Screen modes

The `screen` field is the single size setting:

| Value | Meaning |
|---|---|
| `""` | Playwright default |
| `1280x720` | fixed viewport WxH — pinned in every launch mode |
| `fullscreen` | the viewport follows the window on a local headed launch — the chromium-family engines (chromium, chrome, msedge) start maximized via `--start-maximized`; firefox and webkit keep the plain window; a fixed 1920x1080 viewport under headless and remote connects (no window exists there) |
| `iPhone 13` | a Playwright device name — mobile emulation via the full descriptor: viewport, user agent, touch, is_mobile, device scale factor |

- WxH and device descriptors apply in every launch mode: local headed, local
  headless, remote connect
- An unknown device name fails loudly with an actionable message suggesting
  close device names; device names resolve against the devices registry of the
  running Playwright — the package never hard-codes a device list
- A WxH-shaped value with non-positive numbers fails validation at load; any
  other string passes through as a device name

The screen mode changes only how the context opens — never the facade surface
the step code uses; step code is identical in every mode (see
[Driver facade](../reference/driver-facade.md)).

## Headless

```toml
[tool.prettyplay.browser]
headless = true    # false -> run with a visible browser window
```

`headless` applies to local launches only. To watch a test drive a real
window: `headless = false` (optionally with `screen = "fullscreen"` — the
chromium family then launches maximized).

## Remote browsers

```toml
[tool.prettyplay.browser]
endpoint = "ws://ci-grid:3000/playwright/chromium"
```

A non-empty `endpoint` connects to a remote Playwright Server or browser grid
instead of launching locally:

- `headless` does not apply to a connect — window visibility belongs to the
  endpoint server
- `chrome`/`msedge` map to the chromium engine — channels are a local-launch
  concept
- A non-empty endpoint must be a valid ws/wss URL (otherwise
  `ConfigurationError` names the setting); a failed connect fails loudly with
  the endpoint in the message
- The endpoint is an address, not a secret: it is valid in the config file;
  CI rotation goes through the `PRETTYPLAY_BROWSER_ENDPOINT` env override

## Per-test overrides

Browser settings can be overridden per test through the nested `BrowserConfig`
group — explicitly set fields win, untouched group defaults never overwrite
the file values:

```python
from prettyplay import BrowserConfig, PrettyConfig, PrettyPlay

test = PrettyPlay(
    cache_key="login-flow",
    config=PrettyConfig(browser=BrowserConfig(name="firefox", headless=False)),
)
```

See [Configuration](../configuration.md#per-test-overrides-layered-merge).
