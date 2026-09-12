# Architecture Plan: Playwright-parity driver facade

Topic: **Playwright-parity driver facade**
Plan path: `.goga/history/2026/add-actions/arch.md`
Task: `.goga/history/2026/add-actions/task.md` · ADR: `.goga/history/2026/add-actions/adr.md` (accepted 2026-09-11; wins on conflict)

The driver facade moves from the curated surface to full parity with the Playwright sync API at page/locator
level: mirror names 1:1 (`open` → `goto`, `find_by_*` → `get_by_*`), the full interaction/navigation/expectation/wait
contour, dialogs, iframes and popups/tabs. Backward compatibility is retired; the parity principle replaces it.
The browser group of the config gains the dialog auto-accept switch. The engine system prompt mirrors the new
surface; the PAGE API listing keeps mirroring the `facade` practice verbatim. One atomic change.

## Implementation Order

1. **`prettyplay/config`** (modified) — leaves-first: depends only on `prettyplay/failures` (untouched). The
   `accept_dialogs` setting must exist in `BrowserConfig`/`load_config` before the driver reads it.
2. **`prettyplay/driver`** (modified) — depends on `prettyplay/config` (Types `Config`; the import grows the
   `configuration` practice). The facade rebuild: renames, the mirror surface, `DialogFacade`, `FrameFacade`,
   dialog routing in `DriverSession`.
3. **`prettyplay/engine`** (modified, header-only) — depends on `prettyplay/driver` (`PageFacade` + the `facade`
   practice). The `system_prompt` inline practice changes to mirror the new surface; no type changes.
4. Ride-along, after the cells and outside this plan's artifact set: MkDocs pages
   (`docs/reference/driver-facade.md`, `docs/guides/writing-steps.md`, `docs/configuration.md` and mentions in
   `index.md`, `getting-started.md`, `browser-setup.md`) sync to the new surface in the same change.

No cells are created anew; no cells are removed. The top-level `prettyplay` cell needs no contract change.

---

## Artifacts

### Cell: `prettyplay/config` — modified

Change list:
- CHANGE global Annotations: the flat env list grows `PRETTYPLAY_BROWSER_ACCEPT_DIALOGS`
- CHANGE `BrowserConfig`: signature gains `accept_dialogs: bool`; the param description and the
  `accept_dialogs` property are added
- CHANGE `Config`: the `browser` param description names the dialog auto-accept switch (the model itself is
  unchanged)
- CHANGE `load_config`: Algorithm step 5 names `PRETTYPLAY_BROWSER_ACCEPT_DIALOGS`; Requirements say five
  `PRETTYPLAY_BROWSER_*` variables
- CHANGE footer Description: the browser group now names the dialog auto-accept
- UNCHANGED: `ConfigurationError`, `Config`, every other annotation

Full target content of `prettyplay/config/CODEMANIFEST`:

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
  The browser settings form the nested browser group of `BrowserConfig` inside `Config` (see `pydantic`): fields inside the group carry no browser_ prefix — the group name scopes them. Env overrides stay flat: PRETTYPLAY_BROWSER_NAME, PRETTYPLAY_BROWSER_SCREEN, PRETTYPLAY_BROWSER_HEADLESS, PRETTYPLAY_BROWSER_ENDPOINT, PRETTYPLAY_BROWSER_ACCEPT_DIALOGS.
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

"BrowserConfig(name: str, screen: str, headless: bool, endpoint: str, accept_dialogs: bool)":
  location: models.py
  annotations: |
    The nested browser group of the project settings: engine, screen mode, window visibility, the remote endpoint and the dialog auto-accept switch of the browser.

    `name`: browser of the {chromium, firefox, webkit, chrome, msedge} set; chrome and msedge launch the locally installed browser through the driver channel mechanism; default chromium.
    `screen`: the single size setting; empty — Playwright default; WxH — fixed viewport; fullscreen — maximized window on a local headed launch, fixed 1920x1080 under headless and remote connects; any other value — a Playwright device name applied as the full descriptor (see `pydantic`).
    `headless`: run the browser without a visible window of a local launch; default True.
    `endpoint`: ws endpoint of a remote browser; empty — local launch; default empty.
    `accept_dialogs`: automatically accept dialogs that no step-captured `expect_dialog` block claims; False — the Playwright dismiss default stands; default False (neutral — the pre-setting behavior).

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
    "accept_dialogs -> bool": |
      Whether dialogs outside a captured `expect_dialog` block are accepted automatically; False keeps the dismiss default.

"Config(provider: str, browser: BrowserConfig, model: str, generation_model: str, classification_model: str, base_url: str, cache_root: str, generation_prompt: str, classification_prompt: str, strict: bool, generation_attempts: int, healing_attempts: int, send_screenshots: bool)":
  location: models.py
  annotations: |
    Validated project settings — the single source of the immutable configuration part.

    `provider`: the LLM provider of the {openai, anthropic} set; default openai.
    `browser`: the nested browser group — a `BrowserConfig` with the engine, the screen mode, the window visibility, the remote endpoint and the dialog auto-accept switch.
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
    - provider validated against {openai, anthropic}; the name inside `browser` against the five-value set; invalid values — loud actionable error
    - attempts are positive integers
    - a non-empty endpoint inside `browser` is a valid ws/wss URL — otherwise a loud actionable error
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
    4. Reject the removed legacy env name: PRETTYPLAY_BROWSER set in the environment raises `ConfigurationError` before merging — the message names PRETTYPLAY_BROWSER_NAME as the replacement
    5. Apply environment overrides: each setting is overridden by PRETTYPLAY_<SETTING_UPPERCASE> when the variable is set; the browser group reads PRETTYPLAY_BROWSER_NAME, PRETTYPLAY_BROWSER_SCREEN, PRETTYPLAY_BROWSER_HEADLESS, PRETTYPLAY_BROWSER_ENDPOINT, PRETTYPLAY_BROWSER_ACCEPT_DIALOGS; strict reads PRETTYPLAY_STRICT; classification_prompt reads PRETTYPLAY_CLASSIFICATION_PROMPT
    6. Reject the removed old flat keys: browser, headless or browser_endpoint present at the [tool.prettyplay] level raise `ConfigurationError` immediately — one line per key naming its new home inside [tool.prettyplay.browser] (browser → name, headless → headless, browser_endpoint → endpoint)
    7. Construct `Config`; on a validation failure render the actionable text — one line per invalid setting: the setting name, the received value, the allowed values — and raise `ConfigurationError` with the original ValidationError chained
    8. `overrides` is None — return the file layer as is
    9. Overlay the explicitly set fields of `overrides` onto the file layer (the model with empty defaults, model_copy — see `pydantic`): a field participates when it was passed at construction and is non-empty for strings; the merge reaches inside the browser group — explicitly set fields of a passed `BrowserConfig` win over the file layer, untouched group defaults never overwrite file values; strict participates when passed explicitly — an explicit False overrides too
    10. Return the effective `Config`

    Requirements:
    - An env override exists for every setting of `Config` (including PRETTYPLAY_STRICT, PRETTYPLAY_CLASSIFICATION_PROMPT and the five PRETTYPLAY_BROWSER_* variables)
    - The removed legacy env name PRETTYPLAY_BROWSER fails loudly before merging: it belongs to the same pre-1.0 hard break as the old flat keys
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
  Project settings of prettyplay: the validated [tool.prettyplay] schema with the nested browser group (engine, screen mode, headless, endpoint, dialog auto-accept), the strict replay-only switch, the generation and classification instructions, and the loader with flat env overrides for the group, the removed-flat-key rejection, explicit per-test merging that reaches inside the group and the actionable configuration error.
```

**File:** `prettyplay/config/.usages/configuration.md` — modified. Full target content:

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
        browser=BrowserConfig(screen="fullscreen", headless=False),
    ),
)
```

- An explicitly set field wins over pyproject+env; a field left at its default falls back to the file layer
- The merge reaches inside the nested group: explicitly set fields of a passed BrowserConfig win over the file layer; untouched group defaults never overwrite file values — set only `screen` and the file's `name`, `headless`, `endpoint`, `accept_dialogs` keep working
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

## Dialogs

`accept_dialogs` of the browser group controls the automatic dialog handling of the driver:

- `true` — every dialog that no step-captured `expect_dialog` block claims is accepted automatically
- `false` (default) — unclaimed dialogs are dismissed (the Playwright default; nothing blocks)
- A dialog captured by a step's `expect_dialog` block is accepted or dismissed by the step itself — the setting does not apply to captured dialogs

## Strict mode

`strict = true` (env PRETTYPLAY_STRICT, per-test override) switches the run to replay-only: cached code executes honestly and nothing is ever (re)generated. A cache miss fails as an incurable step; a failed cached step is at most classified — never regenerated. Classification is the only LLM call strict mode makes; without LLM access the failure raises immediately by step type.

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
print(config.browser.name, config.browser.accept_dialogs, config.strict, config.classification_prompt)
```
````

---

### Cell: `prettyplay/driver` — modified (body rebuild)

Change list:
- CHANGE Imports: the config import grows `Usages: [configuration]`
- CHANGE global Annotations: the `playwright` line extends to the new contour; the backward-compatibility line is
  REMOVED and replaced by the parity principle; a NEW excluded-capabilities line; the thread-marshaling statement
  extends to every facade kind
- CHANGE `DriverSession.open_context`: NEW algorithm step 4 (dialog routing handler); the wrap step becomes step 5;
  the Constraints line extends to `DialogFacade` and `FrameFacade`
- CHANGE `PageFacade`: rebuilt surface — navigation, waits, page expectations, the mirror locator family + `locator`,
  `expect_dialog`, `expect_popup`, `bring_to_front`, `pages`, `frame_locator`; the scroll family and `close` stay
  verbatim; `open`/`find_by_*` are REMOVED
- CHANGE `LocatorFacade`: rebuilt surface — the full interaction set and the full `expect_*` family
- ADD `DialogFacade`; ADD `FrameFacade`
- CHANGE footer Description
- UNCHANGED: the launch/screen/thread lines of the global annotations; `DriverSession` signature and `close`

Full target content of `prettyplay/driver/CODEMANIFEST`:

```yaml
Imports:
  - Types:
      - Config
    Usages:
      - configuration
    From: prettyplay/config

Usages:
  conventions: .goga/usages/conventions.md
  playwright: .goga/usages/cooks/playwright.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `playwright` for the sync API lifecycle, locators, auto-wait, the accessibility snapshot, browser channels, remote connects, the screen modes, the scroll primitives, the interaction set, dialogs, popups and tabs, frames, the expectation set and the waits.
  Use `configuration` from Imports for the browser-group settings the session reads, accept_dialogs included.

  The driver is Playwright sync-only: the async API is out of scope.
  The whole Playwright session — start, browser, contexts, pages — lives in one dedicated driver thread owned by the library: the sync API parks its private event loop on its starting thread, so the thread executing the steps never holds a running asyncio loop (interactive hosts such as IPython and Jupyter keep working between steps).
  Driver-thread calls are strictly sequential: one facade call runs at a time; concurrent driving is out of scope.
  One browser process per test: the session is owned by the test's runtime — no state is shared between tests through the library.
  The start mode branches on the endpoint setting of the browser group of `Config`: empty — local launch with headless and the channel for chrome/msedge; set — connect over the Playwright ws endpoint: headless is ignored, channels do not apply, the name setting selects the engine (see `playwright`).
  The screen setting of the browser group resolves at context creation (see `playwright`): the empty value keeps the Playwright default; WxH and device descriptors apply in every launch mode; fullscreen follows the window on a local headed launch and pins to a fixed 1920x1080 viewport where no window exists. Device names resolve against the devices registry of the running Playwright — the package never hard-codes a device list.
  All waits go through locators and expectations; fixed delays (time.sleep and similar) are forbidden.
  The facade surface mirrors the Playwright sync API 1:1 at page/locator level under the parity principle: a facade member exists exactly when its Playwright counterpart exists at this level, under the mirror name. Declared non-mirror families: the prettyplay scroll extras under their own names and the method-style expect_* expectation names replacing the chained to_be_* model. Future Playwright capabilities land as mirror extensions; renaming or removing a mirror member happens only together with a Playwright-level re-mapping.
  The excluded capabilities stay absent from the surface: no route/request interception, no evaluate, no CDP, no clock, no HAR, no tracing — the page-state model behind failure classification and healing must stay honest.
  The thread-marshaling boundary covers every facade kind — pages, popup pages, frame-scoped locators, dialogs: no raw Playwright object crosses the facade boundary.

---

"DriverSession(config: Config)":
  location: session.py
  annotations: |
    Lifecycle owner of the Playwright sync driver and the browser process of one test.

    `config`: project settings; the browser group carries the engine — the name of the {chromium, firefox, webkit, chrome, msedge} set, chrome and msedge launch the locally installed browser through the channel mechanism — the screen size mode, the headless window visibility of a local launch, the endpoint switching the start to a remote connect and the dialog auto-accept switch (see `playwright` and `configuration` from Imports).

    Requirements:
    - The Playwright session lives in a dedicated driver thread owned by the session: every Playwright-touching operation of this type runs there, and the calling thread never holds a running asyncio loop after any call
  methods:
    "open_context() -> page: PageFacade": |
      Open a fresh isolated context with one page of this test's browser.

      Algorithm:
      1. Start lazily on the first call: constructing the session starts nothing — start the dedicated driver thread, then start Playwright inside it; an empty endpoint — launch the selected engine locally with headless from the browser group and the channel for the chrome/msedge values; a set endpoint — connect over the Playwright ws endpoint of the selected engine: headless is ignored and channels do not apply; a failed launch or connect stops the started driver and closes the thread, so a retry begins from a clean state
      2. Resolve the screen setting of the browser group into the context parameters, by precedence: the literal fullscreen value — a local headed launch (headless false, endpoint empty) opens the context without a fixed viewport, so the viewport follows the window: the chromium-family engines (chromium, chrome, msedge) start the window maximized through the --start-maximized launch argument; firefox and webkit keep their plain launch — the window opens at its default size (see `playwright`); headless or a remote connect — a fixed 1920x1080 viewport, no window exists there; a WxH-shaped value — the viewport dictionary of the parsed width and height, in every launch mode; any other value — a device name: present in the devices registry of the running Playwright — the full descriptor applies to the context (viewport, user_agent, touch, is_mobile, device_scale_factor) in every launch mode; absent — a loud actionable error suggesting close device names from the registry
      3. Create a fresh isolated browser context and its page inside the driver thread with the resolved parameters (see `playwright`)
      4. Register the single dialog routing handler on the page before any step code runs: an active expect_dialog capture claims the dialog — the step's `DialogFacade` controls accept and dismiss; otherwise accept when accept_dialogs of the browser group (see `configuration` from Imports) is true, else the Playwright dismiss default
      5. Wrap the page into `PageFacade` bound to the driver thread and return it

      Requirements:
      - Each result is isolated from every other context
      - A channel launch without the installed browser fails loudly with an actionable message naming the missing browser
      - A failed connect fails loudly with an actionable message naming the endpoint
      - WxH and device descriptors apply in every launch mode: local headed, local headless, remote connect
      - fullscreen is not pixel-identical across environments — a headed run follows the actual screen, headless and remote runs are pinned to 1920x1080

      Constraints:
      - `PageFacade`, `LocatorFacade`, `DialogFacade` and `FrameFacade` stay untouched by the screen modes — the changes live in context creation and dialog wiring only
    "close()": |
      Stop the browser, the Playwright driver and the driver thread; safe to call when nothing was started.

"PageFacade(page: Page, context: BrowserContext)":
  location: page.py
  annotations: |
    The full-parity mirror facade of a single test page — the only page API the generated step code may use.
    Wraps one isolated browser context created by `DriverSession`.

    `page`: the wrapped Playwright page object; never exposed through the facade.
    `context`: the isolated browser context owning the page; the boundary the close method closes.

    Requirements:
    - Every Playwright call runs in the driver thread of the owning session: the call blocks until it finishes, strictly one at a time, and the calling thread never adopts the Playwright event loop
    - The context-manager constructs resolve at block exit: the block performs the triggering action, the wrapped object — dialog or popup page — is usable right after it
    - A popup page is a full `PageFacade` bound to the same driver thread as its opener
    - The pages property lists every open page of the context wrapped as facades
    - Locating methods never sleep: waiting is the locator's own auto-wait behavior
    - Scroll methods never sleep: the scrolled state is awaited through locators and expectations
    - aria_snapshot and screenshot reflect the state at call time

    Constraints:
    - No method exposes raw Playwright objects — pages, dialogs and frame scopes included: the facade is the boundary generated code works against
    - The excluded capabilities of the parity principle are absent here (see the global annotations)
  properties:
    "url -> str": |
      The current page URL.
    "pages -> list[PageFacade]": |
      The open pages of this page's context, each a full `PageFacade` — popups and new tabs included.
  methods:
    "goto(url: str)": |
      Navigate to `url` and wait for the load state (see `playwright`).
    "go_back()": |
      Navigate the browser history back and wait for the load state.
    "go_forward()": |
      Navigate the browser history forward and wait for the load state.
    "reload()": |
      Reload the page and wait for the load state.
    "wait_for_url(url: str)": |
      Wait until the page URL matches the glob pattern `url` (see `playwright`).
    "wait_for_load_state(state: str)": |
      Wait for the navigation state — load, domcontentloaded or networkidle (see `playwright`).

      `state`: one of load, domcontentloaded, networkidle.
    "expect_url(url: str)": |
      Assert the page URL matches the glob pattern `url` — auto-waiting.
    "expect_title(title: str)": |
      Assert the page title contains `title` — auto-waiting.
    "get_by_role(role: str, name: str) -> element: LocatorFacade": |
      Locate one element by its aria role and accessible name; returns a `LocatorFacade`.

      `name`: the accessible name; empty — match by role alone.
    "get_by_label(label: str) -> element: LocatorFacade": |
      Locate one element by its associated label; returns a `LocatorFacade`.
    "get_by_text(text: str) -> element: LocatorFacade": |
      Locate one element by its visible text; returns a `LocatorFacade`.
    "get_by_placeholder(placeholder: str) -> element: LocatorFacade": |
      Locate one input by its placeholder text; returns a `LocatorFacade`.
    "get_by_alt_text(alt: str) -> element: LocatorFacade": |
      Locate one image by its alt text; returns a `LocatorFacade`.
    "get_by_title(title: str) -> element: LocatorFacade": |
      Locate one element by its title attribute; returns a `LocatorFacade`.
    "get_by_test_id(test_id: str) -> element: LocatorFacade": |
      Locate one element by its data-testid value; returns a `LocatorFacade`.
    "locator(selector: str) -> element: LocatorFacade": |
      Locate one element by any selector — CSS, XPath (incl. the xpath= form) and attribute selectors such as [data-test-id=value]; returns a `LocatorFacade`.
    "expect_dialog() -> dialog: DialogFacade": |
      Capture the dialog of the action performed inside the with-block; the block's variable is the `DialogFacade` of the captured dialog.

      Requirements:
      - The capture claims the dialog: the step controls accept or dismiss, the accept_dialogs setting does not apply to a captured dialog
      - The block's action firing no dialog fails loudly with an actionable timeout error naming the awaited event
    "expect_popup() -> popup: PageFacade": |
      Capture the popup or new tab opened by the action performed inside the with-block; the block's variable is the opened page as a full `PageFacade`.

      Requirements:
      - The block's action firing no popup fails loudly with an actionable timeout error naming the awaited event
    "bring_to_front()": |
      Bring this page to the front above the other pages of the context — the mirror switching primitive.
    "frame_locator(selector: str) -> frame: FrameFacade": |
      The locating scope of the iframe addressed by `selector`; returns a `FrameFacade`.
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
    "click(button: str)": |
      Click the element, waiting for actionability.

      `button`: the mouse button — empty for the left button, right for the right button, middle for the middle button.
    "dblclick()": |
      Double-click the element, waiting for actionability.
    "fill(value: str)": |
      Set the text input value of the element to `value`.
    "clear()": |
      Clear the text input value of the element.
    "press(key: str)": |
      Press a single key or a key combination on the element, waiting for actionability.

      `key`: the key name or combination, e.g. Enter or Control+A.
    "check()": |
      Check the checkbox or radio button, waiting for actionability.
    "uncheck()": |
      Uncheck the checkbox or radio button, waiting for actionability.
    "hover()": |
      Hover the element, waiting for actionability.
    "select_option(value: str)": |
      Select the option with `value` in a list or combo box.
    "drag_to(target: LocatorFacade)": |
      Drag this element onto the `target` element, auto-waiting both endpoints.

      `target`: the located drop target element.
    "set_input_files(path: str)": |
      Upload one file to the file input.

      `path`: the filesystem path of the file to upload.
    "expect_visible()": |
      Assert the element is visible.
    "expect_hidden()": |
      Assert the element is hidden.
    "expect_text(text: str)": |
      Assert the element text contains `text` (substring, whitespace-normalized).
    "expect_enabled()": |
      Assert the element is enabled.
    "expect_value(value: str)": |
      Assert the element input value equals `value`.
    "expect_checked()": |
      Assert the checkbox or radio is checked.
    "expect_count(count: int)": |
      Assert the locator resolves to exactly `count` elements.
    "expect_attribute(name: str, value: str)": |
      Assert the attribute `name` of the element equals `value`.

"DialogFacade(dialog: Dialog)":
  location: page.py
  annotations: |
    The wrapped dialog captured by expect_dialog — step-controlled handling.

    `dialog`: the wrapped Playwright dialog object; never exposed through the facade.

    Requirements:
    - Every call runs in the driver thread inherited from the page facade that captured the dialog
    - accept and dismiss resolve the dialog exactly once

    Constraints:
    - No raw Playwright objects exposed
  properties:
    "type -> str": |
      The dialog kind: alert, confirm, prompt or beforeunload.
    "message -> str": |
      The message text of the dialog.
    "default_value -> str": |
      The pre-filled answer of a prompt dialog; empty for the other kinds.
  methods:
    "accept(prompt_text: str)": |
      Accept the dialog.

      `prompt_text`: the answer to send for a prompt dialog; empty — accept without an answer.
    "dismiss()": |
      Dismiss the dialog.

"FrameFacade(frame_locator: FrameLocator)":
  location: page.py
  annotations: |
    The frame-scoped locator factory — locating inside one iframe; nested frames chain.

    `frame_locator`: the wrapped Playwright frame locator object; never exposed through the facade.

    Requirements:
    - Every action of a located element runs in the driver thread inherited from the page facade that created the scope

    Constraints:
    - No raw Playwright objects exposed
  methods:
    "get_by_role(role: str, name: str) -> element: LocatorFacade": |
      Locate one element inside the frame by its aria role and accessible name; empty name matches by role alone.
    "get_by_label(label: str) -> element: LocatorFacade": |
      Locate one element inside the frame by its associated label.
    "get_by_text(text: str) -> element: LocatorFacade": |
      Locate one element inside the frame by its visible text.
    "get_by_placeholder(placeholder: str) -> element: LocatorFacade": |
      Locate one input inside the frame by its placeholder text.
    "get_by_alt_text(alt: str) -> element: LocatorFacade": |
      Locate one image inside the frame by its alt text.
    "get_by_title(title: str) -> element: LocatorFacade": |
      Locate one element inside the frame by its title attribute.
    "get_by_test_id(test_id: str) -> element: LocatorFacade": |
      Locate one element inside the frame by its data-testid value.
    "locator(selector: str) -> element: LocatorFacade": |
      Locate one element inside the frame by any selector — CSS, XPath and attribute selectors.
    "frame_locator(selector: str) -> frame: FrameFacade": |
      The locating scope of a nested iframe inside this frame.

---

Author: Goga
CreatedAt: 10/09/26
Description: |
  The Playwright sync driver of prettyplay: the per-test session with local launches, remote ws connects, the screen modes and the dialog routing — and the full Playwright-parity page facade: mirror locators, interactions, expectations, waits, dialogs, popups and tabs, frames, with the prettyplay scroll extras, for generated step code.
```

**File:** `prettyplay/driver/.usages/facade.md` — rewritten. Full target content:

````md
# Driver facade

Domain: the browser facade of prettyplay. Audience: consumers of the page API — the step generation engine and engineers reading or hand-writing step code.

The facade mirrors the Playwright sync API at page/locator level. Every member name is its Playwright counterpart 1:1, with two declared non-mirror families: the prettyplay scroll extras (kept under their own names) and the method-style expect_* expectation names (replacing Playwright's chained expect(locator).to_be_*() model). Step code receives a PageFacade and works only through it, LocatorFacade, FrameFacade and DialogFacade — never through raw Playwright objects. Each context opens with the screen mode configured in the browser group — the facade surface itself is identical in every mode.

## Surface — page

| Call | Purpose |
|---|---|
| page.goto(url) | navigate and wait for the load state |
| page.go_back() | browser-history back |
| page.go_forward() | browser-history forward |
| page.reload() | reload and wait for the load state |
| page.wait_for_url(url) | wait until the URL matches a glob pattern |
| page.wait_for_load_state(state) | wait for load, domcontentloaded or networkidle |
| page.expect_url(url) | assert the URL matches a glob pattern |
| page.expect_title(title) | assert the title contains |
| page.get_by_role(role, name) | element by aria role and accessible name |
| page.get_by_label(label) | element by associated label |
| page.get_by_text(text) | element by visible text |
| page.get_by_placeholder(placeholder) | input by placeholder text |
| page.get_by_alt_text(alt) | image by alt text |
| page.get_by_title(title) | element by title attribute |
| page.get_by_test_id(test_id) | element by data-testid |
| page.locator(selector) | element by any selector — CSS, XPath, attribute |
| page.expect_dialog() | context manager — the block performs the triggering action; yields the DialogFacade |
| page.expect_popup() | context manager — the block performs the opening action; yields the popup as a full PageFacade |
| page.bring_to_front() | raise this page above the others — the switching primitive |
| page.pages | the open pages of the context, each a full PageFacade |
| page.frame_locator(selector) | the locating scope of one iframe — yields a FrameFacade |
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
| page.close() | close this page's isolated context |

## Surface — dialog

| Call | Purpose |
|---|---|
| dialog.accept(prompt_text) | accept; prompt_text answers a prompt dialog (empty — no answer) |
| dialog.dismiss() | dismiss |
| dialog.type | alert, confirm, prompt or beforeunload |
| dialog.message | the dialog message |
| dialog.default_value | the prompt prefill of a prompt dialog |

## Surface — frame

| Call | Purpose |
|---|---|
| frame.get_by_role(role, name) — and the whole get_by_* family | locate inside the iframe |
| frame.locator(selector) | any selector inside the iframe |
| frame.frame_locator(selector) | the scope of a nested iframe |

## Surface — element

| Call | Purpose |
|---|---|
| element.click(button) | click; empty button = left, "right" = right button |
| element.dblclick() | double click |
| element.fill(value) | set input text |
| element.clear() | clear the input |
| element.press(key) | press a key or combination, e.g. "Enter", "Control+A" |
| element.check() | check a checkbox or radio |
| element.uncheck() | uncheck |
| element.hover() | hover |
| element.select_option(value) | choose an option |
| element.drag_to(target) | drag onto another element |
| element.set_input_files(path) | upload one file by filesystem path |
| element.expect_visible() | assert visible |
| element.expect_hidden() | assert hidden |
| element.expect_text(text) | assert text contains (substring, whitespace-normalized) |
| element.expect_enabled() | assert enabled |
| element.expect_value(value) | assert the input value |
| element.expect_checked() | assert the checkbox/radio state |
| element.expect_count(count) | assert the matched element count |
| element.expect_attribute(name, value) | assert the attribute value |

## Example

```python
page.goto("https://example.com/login")
page.get_by_label("Username").fill("user")
page.get_by_role("button", name="Sign in").click()
page.get_by_role("textbox", name="Search").press("Enter")
page.expect_url("**/dashboard")
```

Locating without accessible names:

```python
page.get_by_test_id("submit-button").click()
page.locator("form > button.primary").expect_enabled()
page.locator("//button[@type='submit']").expect_visible()
page.locator("[data-qa='row'] > input").fill("text")
```

Dialogs:

```python
with page.expect_dialog() as dialog:
    page.get_by_role("button", name="Delete").click()
assert dialog.type == "confirm"
assert dialog.message == "Delete the item?"
dialog.accept()
```

A captured dialog is step-controlled — the accept_dialogs setting does not apply to it; dialogs outside a capture follow the setting (accept when on, dismiss when off).

Popups and new tabs:

```python
with page.expect_popup() as docs:
    page.get_by_role("link", name="Open docs").click()
docs.bring_to_front()
docs.get_by_role("heading", name="Documentation").expect_visible()
page.bring_to_front()
```

Iframes:

```python
checkout = page.frame_locator("#checkout")
checkout.get_by_role("button", name="Pay").click()

inner = page.frame_locator("#outer").frame_locator("#inner")
inner.get_by_text("Nested").expect_visible()
```

Interactions:

```python
page.get_by_role("checkbox", name="Subscribe").check()
page.get_by_role("img", name="Product").drag_to(page.get_by_role("list", name="Cart"))
page.get_by_label("Avatar").set_input_files("avatar.png")
page.get_by_role("button", name="Options").click(button="right")
```

Scroll scenarios:

```python
page.scroll_down(600)
page.get_by_text("Footer").expect_visible()

cards = page.get_by_role("list", name="Recommendations")
page.scroll_container_down(cards, 400)
page.get_by_text("Fifth card").expect_visible()

snapshot = page.aria_snapshot()
```

## Rules

- One browser process per test: each test owns its browser through its runtime; contexts stay isolated
- Every call executes in the library's driver thread and returns when done: driving is strictly sequential, and the calling thread never adopts the Playwright event loop — hand-written step code stays safe in interactive hosts (IPython, Jupyter)
- Auto-wait everywhere: no time.sleep, no fixed delays in step code — including around scrolls: the scrolled state is awaited through locators and expectations
- The screen mode of the browser group (empty, WxH, fullscreen, device name) changes only how the context opens — never the facade surface; step code is identical in every mode
- Parity, not exposure: mirroring Playwright never means exposing raw Playwright objects — every interaction stays a facade call marshaled through the driver thread, popup pages and frame scopes included
- No network interception, no evaluate, no CDP, no clock, no HAR, no tracing — these stay outside the facade
- Dialogs: an expect_dialog capture claims its dialog; dialogs outside a capture follow the accept_dialogs browser setting
- Never put secrets into step actions — step texts and code land in the repository cache
````

---

### Cell: `prettyplay/engine` — modified (header-only)

Change list:
- CHANGE the inline usage `system_prompt`: the Rules mirror the new surface (the Playwright-mirroring page API,
  `get_by_test_id`/`locator` for elements without accessible names, dialogs via `expect_dialog`, popups via
  `expect_popup` + `bring_to_front`, iframes via `frame_locator`; the scroll line and the no-delays rule stay)
- UNCHANGED: Imports (incl. `facade` from `prettyplay/driver`), `classification_prompt`, all Annotations, the whole
  body (`StepGenerator`, `StepHealer`, `run_step_code`, `classify_step_failure`), the footer

Full target content of the `system_prompt` value inside `prettyplay/engine/CODEMANIFEST` (everything else verbatim
from the current file):

```yaml
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
  - The step must complete exactly what STEP says — nothing more, nothing less
  - Output only the code block, no explanations
```

**File:** `prettyplay/engine/.usages/generation.md` — modified. Only the last section changes; the full target
content of that section:

```md
## The fixed form

Generated code is one function receiving exactly one argument — the page facade — and working only through the facade surface: `page.get_by_role(...).click()`, `page.get_by_test_id("submit").click()`, `page.locator("form > button.primary")`, `page.locator("//button[@type='submit']")`, `element.expect_visible()`, `element.press("Enter")`, `with page.expect_dialog() as dialog: ...`, `with page.expect_popup() as popup: ...`, `page.frame_locator("#checkout").get_by_role("button", name="Pay").click()`, `page.scroll_down(600)` and alike. No provider constructs, no direct driver imports, no fixed delays.
```

(The "Generate a step" and "Classification call" sections of the file stay verbatim.)

---

## Dependency Map

```
prettyplay/failures ──(PrettyplayError, taxonomy)──> prettyplay/config
prettyplay/config ───(Config; NEW: configuration practice)──> prettyplay/driver
prettyplay/driver ───(PageFacade; facade practice)──> prettyplay/engine
prettyplay/driver ───(DriverSession, PageFacade)────> prettyplay (root, unchanged)
prettyplay/config ───(Config AS PrettyConfig, BrowserConfig, load_config)──> prettyplay (root, unchanged)
```

Order: config → driver → engine. No cycles. The engine PAGE API listing continues to mirror the `facade` practice
of the driver — the listing changes with the practice, in one move.

## Verification Checklist

After each artifact lands (and once more after the whole atomic change):

1. `goga lint` passes on all three CODEMANIFESTs — no DSL errors
2. `goga schema` shows `DialogFacade` and `FrameFacade` under `prettyplay/driver`; the driver's dependency on
   `prettyplay/config` now includes the `configuration` usage
3. The `facade.md` surface tables match the driver CODEMANIFEST members 1:1 — every page/dialog/frame/element row
   resolves to a declared member; no retired name (`open`, `find_by_*`) remains anywhere in the cells, practices
   or the system prompt
4. No excluded capability appears in any artifact: route/request interception, evaluate, CDP, clock, HAR, tracing
5. `BrowserConfig` carries `accept_dialogs` with the neutral False default; `load_config` reads
   `PRETTYPLAY_BROWSER_ACCEPT_DIALOGS` (bool: true/false/1/0) and merges it inside the browser group like every
   group field
6. The engine `system_prompt` rules reference only existing surface names; the PAGE API listing sent to providers
   is regenerated from the new `facade.md` (verbatim mirror, never a hand-curated subset)
7. Implementation-stage gates: tests mirror the source structure per `conventions`; `ruff check` passes;
   Python 3.10+ compatibility; no new dependency in `pyproject.toml`
8. Acceptance: re-check the ten acceptance criteria of `task.md` (mirror coverage, contour completeness, excluded
   absence, scroll family intact, listing/prompt mirror, config setting, thread marshaling incl. popups/frames/
   dialogs, docs consistency, conventions, accepted AttributeError cost)
9. Docs ride-along verified: `docs/reference/driver-facade.md`, `docs/guides/writing-steps.md`,
   `docs/configuration.md` and the mentions in `index.md`, `getting-started.md`, `browser-setup.md` carry the new
   surface without contradictions
```
