# Architecture Plan — new-reworks-tls-site-scope

Three ADR decisions of the new-reworks line implemented together in prettyplay:
D1 `browser.ignore_https_errors`, D2 `site.base_url` + `PrettyPlay.site_base_url`,
D3 the shared step scope `_scope` with two validation rings and scoped cache addressing.

## Topic

**new-reworks-tls-site-scope** — plan file: `.goga/history/2026/new-reworks/arch.md`
(authoritative inputs: `task.md`, `adr.md` in the same directory).

All five cells are **modifications** of existing cells; no cell is created, no artifact is deleted.

## Implementation Order

Leaves to root — every cell is implemented after its providers:

1. **`prettyplay/config`** — modified. No new imports (its provider `prettyplay/failures` is unchanged).
   Provides `SiteConfig`, the extended `BrowserConfig`/`PrettyConfig`/`load_config` that every other cell consumes.
2. **`prettyplay/cache`** — modified. Depends on `prettyplay/config` (existing) and gains `prettyplay/failures`
   (new edge, acyclic — failures imports nothing). Provides `validate_step_scope`, the scoped `StepIdentity`
   and the scoped `StepCache` routing that the facade and engine/groups consume.
3. **`prettyplay/driver`** — modified. Depends on `prettyplay/config` only (existing).
   Applies the D1 context parameter; independent of the cache changes.
4. **`prettyplay/engine/groups`** — modified. Depends on the extended cache types (row re-addressing under the
   group's scope); implemented after the cache.
5. **`prettyplay` (facade)** — modified. The root: imports `validate_step_scope` + `addressing` from the cache
   and `SiteConfig` from config; implemented last.

## Artifacts

For every artifact below: **ADD** inserts new text at the stated anchor, **CHANGE** replaces the stated existing
text, **REPLACE-SECTION** replaces a whole named section. All existing text not named stays verbatim.

---

### Cell 1 — `prettyplay/config` (modified)

#### CODEMANIFEST `prettyplay/config/CODEMANIFEST`

**Header — Annotations**

- **CHANGE** — in the existing browser-group env enumeration paragraph, extend the flat env list with
  `PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS` (after `PRETTYPLAY_BROWSER_TIMEOUT`).
- **ADD** — two paragraphs at the end of `Annotations:`:

```yaml
  The site settings form the nested site group of `SiteConfig` inside `PrettyConfig`, symmetric to the browser
  group (see `pydantic`): fields inside the group carry no site_ prefix — the group name scopes them; the env
  override stays flat: PRETTYPLAY_SITE_BASE_URL.
  The insecure-TLS switch is an ordinary browser-group boolean participating in the layered merge like every
  group field; its application as a context parameter belongs to the driver cell — the config stores the value
  only, and enabling is silent: an explicit configuration is not a suspicious state, no WARNING is logged.
```

**Body**

- **ADD** — new declaration between `BrowserConfig` and `PrettyConfig`:

```yaml
"SiteConfig(base_url: str)":
  location: models.py
  annotations: |
    The nested site group of the project settings: the root URL of the environment under test, set once instead
    of being hardcoded in step sentences.

    `base_url`: the root http(s) URL of the environment under test; empty — unset (the default); a non-empty
    value must be an http/https URL — scheme and netloc present — otherwise the loud actionable error fires;
    adopted verbatim — no trailing-slash normalization, the author composes URL strings.

    Requirements:
    - kw_only construction; the field has an empty default
    - a non-empty `base_url` carries an http or https scheme and a non-empty netloc — any other non-empty value
      fails loudly naming the setting, the received value and the allowed form (see `pydantic`)
    - no collision with the top-level `base_url` (the LLM API endpoint): the group scopes the field, exactly as
      the browser group scopes `name`
  properties:
    "base_url -> str": |
      The root URL of the environment under test; empty means unset; verbatim — no trailing-slash normalization.
```

- **CHANGE** — `BrowserConfig` signature:

```yaml
"BrowserConfig(name: str, screen: str, headless: bool, endpoint: str, accept_dialogs: bool, speed: int, timeout: float, ignore_https_errors: bool)":
```

  **ADD** — param line after the `timeout` line of the annotation:

```
    `ignore_https_errors`: open pages behind self-signed or otherwise invalid certificates (staging grids, CI);
    the driver cell applies it as a context parameter at context creation — never a launch argument — which
    makes every start mode identical; default False keeps Playwright's certificate checking untouched; enabling
    is silent.
```

  **ADD** — property after `timeout -> float`:

```yaml
    "ignore_https_errors -> bool": |
      Whether contexts open behind invalid certificates; False keeps Playwright's certificate checking untouched.
```

- **CHANGE** — `PrettyConfig` signature: insert `site: SiteConfig` after `browser: BrowserConfig`:

```yaml
"PrettyConfig(provider: str, browser: BrowserConfig, site: SiteConfig, model: str, generation_model: str, classification_model: str, base_url: str, cache_root: str, generation_prompt: str, classification_prompt: str, strict: bool, polling_timeout: float | None, polling_delay: float, interactive: bool, generation_attempts: int, healing_attempts: int, llm_request_attempts: int, request_max_tokens: int, send_screenshots: bool, send_structure: bool, generation_approve: bool, probe_timeout: float)"
```

  **ADD** — param line after the `browser` line:

```
    `site`: the nested site group — a `SiteConfig` with the root URL of the environment under test.
```

  **ADD** — Requirements line (after the browser-group merge line):

```
    - the site group participates in the layered merge of `load_config` symmetrically to the browser group — the
      merge reaches inside the group: explicitly set fields of a passed `SiteConfig` win over the file layer,
      untouched group defaults never overwrite file values
```

  **ADD** — property after `browser -> BrowserConfig`:

```yaml
    "site -> SiteConfig": |
      The nested site settings group.
```

- **CHANGE** — `load_config` Algorithm step 6: extend the browser-group env sentence with the two new overrides
  (insert after the `browser.timeout reads PRETTYPLAY_BROWSER_TIMEOUT under the same rule` clause):

```
       the browser group also reads PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS (a boolean — true/false/1/0
       case-insensitively under the existing parse rule; an unparseable value raises the loud actionable
       ConfigurationError naming the setting, the received value and the accepted form); the site group reads
       PRETTYPLAY_SITE_BASE_URL (a string, taken verbatim)
```

- **CHANGE** — `load_config` Algorithm step 10: extend the browser-group overlay sentence with
  `the overlay reaches inside the site group exactly as inside the browser group — explicitly set fields of a passed SiteConfig win, empty fields never overwrite the file layer`.
- **ADD** — `load_config` Requirements lines:

```
    - an env override exists for each new setting: PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS (boolean) and
      PRETTYPLAY_SITE_BASE_URL (string, verbatim)
    - an invalid non-empty site.base_url — not an http/https URL or no netloc — fails loudly through the
      existing validation wrap: the message names the setting, the received value and the allowed form
```

**Footer**

- **CHANGE** — `Description:` updated to the current state: the browser-group inventory gains
  “the insecure-TLS switch”; the description gains “the nested site group (site.base_url — the root URL of the
  environment under test)”. `Author`/`CreatedAt` unchanged.

#### `.usages` — `prettyplay/config/.usages/configuration.md` (modified)

- **REPLACE-SECTION** “the TOML example block at the top”:

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
request_max_tokens = 16384 # anthropic completion cap (max_tokens); sized so a reasoning model never truncates
send_screenshots = false
send_structure = true     # structural element registry (PAGE STRUCTURE block) in LLM requests
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
endpoint = ""              # remote browser endpoint; ws/wss -> Playwright server, http/https -> CDP (chromium family); empty -> local launch
accept_dialogs = false     # true — accept (else dismiss) dialogs no in-step capture claims, at the run-unit tail
speed = 100            # pace of the run: 0–100 %, 100 — full speed (default)
timeout = 30           # page default action timeout, seconds; explicitly applied at page creation; 0 disables the timeout, not auto-wait
ignore_https_errors = false  # true — open pages behind self-signed/invalid certificates; a context parameter in every start mode

[tool.prettyplay.site]
base_url = ""              # root URL of the environment under test; empty — unset; http/https with a host, kept verbatim
```

- **ADD** — two rows to the env override table after `| browser.timeout | PRETTYPLAY_BROWSER_TIMEOUT |`:

```
| browser.ignore_https_errors | PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS |
| site.base_url | PRETTYPLAY_SITE_BASE_URL |
```

- **ADD** — new section after “Dialogs”:

```md
## Insecure TLS

`ignore_https_errors` of the browser group (default false, env PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS,
programmatically assembled config) opens pages behind self-signed or otherwise invalid certificates — staging
grids and CI:

```toml
[tool.prettyplay.browser]
ignore_https_errors = true
```

- The switch applies as a Playwright **context parameter** in every start mode identically — local launch, ws/wss
  remote connect (the Playwright protocol), http/https remote connect (CDP); never a launch argument
- `false` (the default) keeps Playwright's certificate checking untouched
- Enabling is silent — an explicit configuration is not a suspicious state, nothing is logged
- Booleans parse true/false/1/0 case-insensitively; anything else fails loudly naming the setting, the received
  value and the accepted form
```

- **ADD** — new section after “Insecure TLS”:

```md
## Site base URL

The nested `site` group holds the single `base_url` field — the root URL of the environment under test, set once
instead of being hardcoded in every step sentence:

```toml
[tool.prettyplay.site]
base_url = "https://staging.example.com"
```

```python
from prettyplay import PrettyPlay, PrettyConfig, SiteConfig

test = PrettyPlay(
    cache_key="login-flow",
    config=PrettyConfig(site=SiteConfig(base_url="https://staging.example.com")),
)
test.step(f"open the page {test.site_base_url}/login")
```

- The layered merge is symmetric to the browser group: an explicitly passed value wins, an empty field never
  overwrites the file layer; the env override is PRETTYPLAY_SITE_BASE_URL
- A non-empty value must be an http/https URL — scheme and host present; anything else fails loudly at load
  naming the setting, the received value and the allowed form; an empty value means unset
- The value is kept verbatim — no trailing-slash normalization; the author composes URL strings
- Tests read it through the facade property `site_base_url` — an empty string when unset
- No collision with the top-level `base_url` (the LLM API endpoint): the group scopes the field, exactly as the
  browser group scopes `name`
- The URL is not wired into Playwright navigation: rendering it into a sentence makes it part of the step
  address — staging and production keep separate cache entries (rendered values are data)
```

- **ADD** — one line to the “Rules” section:
  `- A non-empty site.base_url is an http/https URL with a host — violations fail loudly at load`.

---

### Cell 2 — `prettyplay/cache` (modified)

#### CODEMANIFEST `prettyplay/cache/CODEMANIFEST`

**Header**

- **ADD** — new Imports entry (first in the list):

```yaml
  - Types:
      - PrettyplayError
    Usages:
      - taxonomy
    From: prettyplay/failures
```

- **ADD** — four paragraphs at the end of `Annotations:`:

```yaml
  A step scope is the shared cache namespace of one page object: for a scoped step it replaces exactly two
  things — the address key inside the address (key = the scope) and the file routing (`root/<scope>/`); the full
  address stays (key, step_type, normalized_text) — the same phrase as an action and as an assertion remains two
  entries even under one scope. Do not confuse it with the pre-existing cache scope (the cache root plus the
  subdirectory of the store — the sweep boundary).
  The scope charset rule lives here once and serves two rings: the facade validates at the call site (ring 1)
  through `validate_step_scope`, the store re-enforces it at addressing (ring 2) — the same forbidden set, never
  softer than the structural bans; the store's existing subdirectory argument (`path`) is not tightened
  retroactively — the strict charset applies to the scope only, from birth.
  The metadata key of a scoped file is the scope itself: the close-time sweep of any test — filtering by its own
  cache key — never touches scoped files; shared entries survive every sweep.
  Budgets follow the runtime, addressing follows the scope: budgets stay per test; the generating test pays from
  its own budget, a test hitting the shared file pays nothing; there is no shared scope budget.
```

**Body**

- **ADD** — new declaration after `normalize_step_text`, before `StepIdentity`:

```yaml
"validate_step_scope(scope: str)":
  location: models.py
  annotations: |
    Validate a step scope — the one rule of both validation rings (see the document annotations).

    `scope`: the candidate scope value.

    Algorithm:
    1. Split `scope` into segments on the `/` separator — an empty `scope` yields no valid segments and is
       rejected
    2. Every segment must match `[A-Za-z0-9._-]+` — at least one character: ASCII letters, digits, dot,
       underscore, hyphen only; every other character (spaces, backslashes, colons, non-ASCII) fails here,
       which also covers the absolute forms (a leading `/`, `\`, `C:`) and the empty segments of
       leading/trailing/double slashes
    3. No segment may equal `..`
    4. 1..N surviving segments joined by exactly one `/` is the accepted form; any rejection raises the loud
       error

    Requirements:
    - Pure function: no I/O, no state, deterministic on `scope` alone
    - A violation raises the loud actionable `PrettyplayError` (see `taxonomy` from Imports) naming the
      parameter `_scope`, the received value and the allowed form — one render
    - One rule serves both rings: the facade (ring 1) and the store (ring 2) reject the same values through
      this one implementation — never two

    Constraints:
    - No normalization: a valid value passes verbatim, nothing is rewritten
    - No filesystem access: the rule never touches the directory itself
```

- **CHANGE** — `StepIdentity` signature and annotation. New signature:

```yaml
"StepIdentity(cache_key: str, step_type: str, normalized_text: str, scope: str)":
```

  **ADD** — param line after `normalized_text`:

```
    `scope`: the step scope — the shared cache namespace of one page object; empty — unscoped, the address is
    exactly as before; non-empty — it becomes the address key (see `address_key`) and routes the file to
    `root/<scope>/` (the routing itself belongs to `StepCache`).
```

  **ADD** — Requirements lines:

```
    - An identity with an empty `scope` addresses byte-identically to the pre-scope triple: the same cache key,
    step type and normalized text always yield the same file name as before — no unscoped address changes
    - A scoped identity (a non-empty `scope`) addresses by (scope, step_type, normalized_text): the scope is
    the key part; the routing path never enters the digest — the scope already addresses the step, the path
    only routes
    - The record holds no validation: the scope rule lives in `validate_step_scope`, enforced by the facade and
    the store — the record stays pure data
```

  **ADD** — properties after `normalized_text -> str`:

```yaml
    "scope -> str": |
      The step scope; empty — the step is unscoped and addresses by `cache_key`.
    "address_key -> str": |
      The key part of the address: `scope` when set, otherwise `cache_key`. The digest file name, the metadata
      key of the cache file and the sweep filter all key on this one value.
```

  **CHANGE** — `filename -> str` property: Algorithm step 1 becomes
  `Build the identity string: address_key, step_type and normalized_text joined with an unambiguous separator`;
  **ADD** — Requirements lines:

```
      - Unscoped identities keep the exact pre-scope digests (address_key = cache_key)
      - The routing path (the scope directory, the store subdirectory) never enters the digest
```

- **ADD** — `StepCache` annotation, the `path` param line appends: `; a scoped step routes by its scope — this
  subdirectory never applies to scoped steps`.

- **CHANGE** — `StepCache.load` Algorithm: insert two steps at the head and adjust the resolution/validation:

```
      1. Ring 2 first: validate a non-empty `identity.scope` through `validate_step_scope` — before any path is
      composed; a violation raises the loud `PrettyplayError`, the address never escapes the cache root even by
      bypassing the facade
      2. Resolve the target directory: a scoped identity routes to root/<scope>/ — the store's subdirectory
      never applies to scoped steps; an unscoped identity keeps the effective root plus the store's
      subdirectory, as before
      3. (existing) a missing file returns None; read the module; validate the metadata: CACHE_KEY equals
      `identity.address_key` (the scope of a scoped step, the cache key otherwise — unchanged behavior for
      unscoped reads), STEP_TYPE equals the identity's step type, STEP_TEXT normalizes to
      identity.normalized_text; the touched set as before
```

- **CHANGE** — `StepCache.save` Algorithm: insert the ring-2 step at the head; serialize `CACHE_KEY` from
  `identity.address_key`; scoped target directory `root/<scope>/` created when missing (unscoped as before);
  the temp file, atomic replace, Windows-busy retry and reporting unchanged. **ADD** — Requirements lines:

```
      - Concurrent writers on one scoped step never corrupt the file: two tests missing the same scope both
      generate on their own budgets, the atomic replace keeps the file valid for both — last writer wins, and
      the reader's CACHE_KEY/STEP_TYPE/digest checks accept either writer's file (both wrote the same address)
      - The metadata key of a scoped file is the scope itself — identical bytes whichever test wrote it
```

- **ADD** — `StepCache.sweep_untouched` Requirements line:

```
      - Scoped files are immune: their metadata key is the scope, never the sweeping test's cache key — the key
      filter skips them; the sweep concerns the test's unscoped steps only
```

- **ADD** — `CachedStep` Requirements line:

```
    - The metadata key of a scoped file is the scope itself: the writer (save) and the reader (load) agree on
    `identity.address_key` as the CACHE_KEY value — the header contract stays consistent between them; this is
    what makes scoped files survive every close-time sweep
```

**Footer**

- **CHANGE** — `Description:` gains the step scope (the shared cache namespace, the scoped routing, the two
  validation rings). `Author`/`CreatedAt` unchanged.

#### `.usages` — `prettyplay/cache/.usages/addressing.md` (modified)

- **REPLACE-SECTION** “Identity triple” table:

```
| Component | Source | Effect on identity |
|---|---|---|
| cache_key | the main object constructor argument | a different key — a different step; replaced by the scope for a scoped step (see below) |
| step type | action vs assertion | the same sentence as action and as assertion — two steps |
| normalized sentence | the addressing text — the rendered sentence — after NFC + trim | «Click Sign in» and «click  sign in » are different steps; a plain sentence and a template producing the exact same text are one step |
| scope | the `_scope` of the step call or the group block | non-empty — the shared cache namespace of one page object: the scope becomes the key part of the address and routes the file to root/<scope>/; empty — unscoped, exactly the old triple |
```

- **ADD** — new section after “The addressing text”:

```md
## The step scope

A scope is the shared cache namespace of one page object — the integrator layer sets it once per block:

```python
t.step("open the dashboard", _scope="pages/dashboard")          # per step on the facade
g = t.group("the user signs in", _scope="pages/login_page")     # once per block — inherited by every step
```

- For a scoped step the scope replaces exactly two things: the key part of the address (key = the scope) and
  the file routing (`root/<scope>/`); the full address stays (key, step type, normalized sentence)
- One step phrase under one scope is one cache entry for all tests: the first test generates through the LLM,
  the rest reuse the file without a model call; unscoped steps address exactly as before — no collisions
- The same phrase as an action and as an assertion remains two entries even under one scope
- The scope never enters the rendered sentence or the LLM requests — it addresses and routes only
- The routing path never enters the digest file name: the scope already addresses the step, the path only routes
- Form: 1..N segments of `[A-Za-z0-9._-]+` joined by exactly one `/` (e.g. `pages/login_page`); an invalid
  value fails loudly at the call naming `_scope`, the received value and the allowed form — the store
  re-enforces the same rule at addressing
```

- **CHANGE** — the “Normalize and address” example body becomes:

```python
from prettyplay.cache import StepIdentity, normalize_step_text

normalized = normalize_step_text("  Click Sign In ")
identity = StepIdentity(
    cache_key="login-flow",
    step_type="action",
    normalized_text=normalized,
    scope="pages/login",  # empty — unscoped (the default); non-empty — the scope IS the address key
)
# identity.address_key — "pages/login" here, the cache key otherwise: the digest and the file metadata key on it
# identity.filename — the deterministic digest of (address_key, step_type, normalized_text)
```

- **ADD** — to the “Layout” section:

```
A scoped step routes to `root/<scope>/` — a subdirectory of the cache root; the optional subdirectory argument
of the store never applies to scoped steps. Unscoped steps keep the old layout: the root plus the store
subdirectory.
```

#### `.usages` — `prettyplay/cache/.usages/storage.md` (modified)

- **CHANGE** — the “File format” paragraph becomes:

```
Each file carries the metadata fields (the step's addressing text — the rendered sentence with actual values —
the cache key — the address key: the scope of a scoped file, the cache key otherwise — the step type, the
creation date), then the `# --- step code ---` sentinel line, then the generated step code — top-level imports
when present, then the fixed-form `def step` function, restored verbatim on load. Files carry no library
version and are never invalidated by a library upgrade.
```

- **ADD** — new section after “The per-test working set”:

```md
## Shared scope entries

A scoped step (a step executed with a non-empty `_scope`) writes to `root/<scope>/` with the metadata key equal to the scope itself:

- Identical bytes whichever test wrote it — two tests missing the same scope both generate on their own budgets;
  the atomic write (temp file + replace) keeps the file valid for both readers; last writer wins
- A load verifies CACHE_KEY/STEP_TYPE and the digest name against the identity — both writers' files pass,
  being the same address
- The close-time sweep never deletes scoped files: it filters by the sweeping test's cache key, and a scoped
  file's metadata key is the scope — cleanup concerns the test's unscoped steps only
- Budgets stay per test: the generating test pays from its own attempt budgets; a test that hits the shared
  file pays nothing — there is no shared scope budget
```

#### `.usages` — `prettyplay/cache/.usages/budgets.md` (modified)

- **ADD** — one bullet to the “Semantics” section:

```
- A scoped step draws budgets per test exactly like an unscoped one: the identity key carries the scope, the
  registry stays per test — the generating test pays, a test reusing the shared file pays nothing (a cache hit
  never consumes budgets); there is no shared scope budget
```

---

### Cell 3 — `prettyplay/driver` (modified)

#### CODEMANIFEST `prettyplay/driver/CODEMANIFEST`

**Header**

- **ADD** — one paragraph at the end of `Annotations:`:

```yaml
  The insecure-TLS switch rides the context creation: the ignore_https_errors setting of the browser group (see
  `configuration` from Imports) applies as a context parameter on the same new_context call as the screen modes —
  never a launch argument — which makes every start mode identical (see `playwright`); enabling is silent: an
  explicit configuration is not a suspicious state, no WARNING is logged.
```

**Body**

- **CHANGE** — `DriverSession` annotation, the `config` param line: the browser-group inventory gains
  “the insecure-TLS switch” (…the dialog auto-accept switch, **the insecure-TLS switch** and the page action
  timeout baseline…).
- **CHANGE** — `open_context` Algorithm step 3 becomes:

```
      3. Create a fresh isolated browser context and its page inside the driver thread with the resolved
      parameters, which now include ignore_https_errors from the browser group as a context parameter (see
      `playwright`) — one surface at context creation, identical in every start mode: local launch, ws/wss
      remote connect (the Playwright protocol), http/https remote connect (CDP); the timeout setting of the
      browser group sets the page default action timeout on the created page — seconds converted to
      milliseconds, once per page, explicit on every page (the default 30 mirrors the Playwright library
      default; 0 disables the timeout without disabling auto-wait), the baseline the probe bound of the engine
      loops restores to (see `configuration` from Imports)
```

- **ADD** — `open_context` Requirements lines:

```
      - The insecure-TLS switch applies identically in every start mode — a context parameter, never a launch
      argument; the default False keeps Playwright's certificate checking untouched
      - Enabling the switch is silent — no WARNING is logged
```

**Footer**

- **CHANGE** — `Description:` gains “the insecure-TLS context switch” in the session inventory.

**.usages** — no changes (`plumbing.md`, `error_kinds.md` untouched; the behavior is documented in the
project-level `playwright` cook, already updated, read-only).

---

### Cell 4 — `prettyplay/engine/groups` (modified)

#### CODEMANIFEST `prettyplay/engine/groups/CODEMANIFEST`

**Header**

- **CHANGE** — the `prettyplay/cache` Imports entry gains:

```yaml
    Usages:
      - addressing
```

- **ADD** — one paragraph at the end of `Annotations:`:

```yaml
  The recovery preserves the step scope: a group step's trace record carries both address parts — the cache key
  and the scope — and every row step's fresh identity is rebuilt with them; a scoped group's rows re-address
  under the group's scope (see `addressing` from Imports). Group membership changes neither a step's scope nor
  its address — the group only passes its scope down.
```

**Body**

- **CHANGE** — `GroupStepOutcome` annotation, the `identity` param line becomes:

```
    `identity`: the cache address of the step at its execution — recorded by the executor when the trace is
    appended; the row mechanics take the cache_key AND the scope from it and re-derive the address from the
    re-rendered addressing text; never rendered into the GROUP STEPS block.
```

- **CHANGE** — the `identity -> StepIdentity` property becomes:

```yaml
    "identity -> StepIdentity": |
      The cache address recorded at the step's execution — both address parts (cache_key, scope); the row
      re-render derives a fresh address — this record keeps the execution fact. Never rendered.
```

- **CHANGE** — `GroupRecovery.recover` Algorithm step 5: the identity-build clause becomes:

```
      build the fresh identity from the fresh render's addressing text — `normalize_step_text`, then
      `StepIdentity` with the trace identity's cache_key AND scope and the step type — a scoped group's rows
      re-address under the group's scope (see `addressing` from Imports)
```

- **CHANGE** — `GroupRecovery.recover` Requirements line extends to:

```
      - A row step's re-rendered identity is the address of its regeneration and write-back — the recovery
      never writes a row step under a stale trace identity; the trace identity's scope threads into every fresh
      identity — a group recovery row is re-addressed by the re-rendered text under the group's scope
```

**Footer**

- **CHANGE** — `Description:` gains “with the step scope preserved through the row re-addressing”.

#### `.usages` — `prettyplay/engine/groups/.usages/recovery.md` (modified)

- **CHANGE** — the closing bullet of “Memory and re-render” becomes:

```
- The re-rendered addressing text re-addresses every row step: the regeneration, the healing-counter refresh
  and the cache write-back key on the fresh identity — built from the re-rendered text with the trace record's
  cache key AND scope: a scoped group's rows re-address under the group's scope; a row step re-rendered against
  changed memory is a new address with a fresh budget
```

---

### Cell 5 — `prettyplay` (facade, modified)

#### CODEMANIFEST `prettyplay/CODEMANIFEST`

**Header**

- **CHANGE** — the `prettyplay/config` Imports entry: add `- SiteConfig` to its Types list.
- **CHANGE** — the `prettyplay/cache` Imports entry: add `- validate_step_scope` to its Types list and:

```yaml
    Usages:
      - addressing
```

- **ADD** — four paragraphs at the end of `Annotations:`:

```yaml
  `SiteConfig` — the public name of the site settings group — is re-exported by this facade (see the
  embedding), uniform with `PrettyConfig` and `BrowserConfig`.
  The site base URL reaches the author through the `site_base_url` property of the main object: the verbatim
  `site.base_url` of the effective config — an empty string when unset; no normalization, the author composes
  URL strings.
  The step scope is the authoring surface of the integrator layer: `step` and `expect` accept the keyword-only
  `_scope` per step, `group` accepts it once per block — inherited by every step of the group and rejected per
  step inside a group; the page-object layer sets it at group creation. A scope replaces exactly two things
  for a scoped step — the address key and the file routing (see `addressing` from Imports); it never enters
  the rendered sentence or any LLM request.
  Ring 1 lives at the call site: a non-None `_scope` validates through `validate_step_scope` from Imports
  before any render or execution — the loud actionable `PrettyplayError` names the parameter, the received
  value and the allowed form; the store re-enforces the same rule at addressing (ring 2).
```

**Body**

- **CHANGE** — `PrettyPlay` annotation, the `cache_path` param line appends: `; a scoped step routes by its
  `_scope` instead — this subdirectory never applies to it`.

- **ADD** — embedding after `->BrowserConfig: {}`:

```yaml
->SiteConfig: {}
```

- **CHANGE** — `PrettyPlay` methods. `step` signature:

```yaml
    "step(text: str, tries: int | None, delay: float | None, vars: dict[str, str] | None, _scope: str | None)": |
```

  **ADD** — param line after `vars`:

```
      `_scope`: keyword-only — the step scope: the shared cache namespace of one page object; None — unscoped
      (the default), the step addresses exactly as before; a non-None value validates through
      `validate_step_scope` from Imports BEFORE any render or execution — ring 1: the loud actionable
      `PrettyplayError` names `_scope`, the received value and the allowed form.
```

  **CHANGE** — the delegation sentence gains `AND \`scope\``.

- **CHANGE** — `expect` signature mirrors `step`; its annotation’s parameter list reference becomes “(the same
  keyword-only `tries`, `delay`, `vars` AND `_scope` parameters and the same validation as step)”.
- **CHANGE** — `group` signature:

```yaml
    "group(prompt: str, speed: int | None, delay: float | None, _scope: str | None) -> g: StepGroup": |
```

  **ADD** — param line after `delay`:

```
      `_scope`: keyword-only — the block's scope, set once per group: validated through `validate_step_scope`
      from Imports at entry — before the block opens; inherited by every step of the group; None — the group's
      steps address unscoped.
```

  **CHANGE** — the `g` description gains: “carries the block's scope and passes it down to every step; a
  per-step `_scope` inside the group is rejected (see `StepGroup`)”.

- **ADD** — `PrettyPlay` property after `cache_key -> str`:

```yaml
    "site_base_url -> str": |
      The root URL of the environment under test — the verbatim `site.base_url` of the effective config; an
      empty string when unset; no trailing-slash normalization.
```

- **CHANGE** — `StepGroup` signature:

```yaml
"StepGroup(prompt: str, speed: int | None, delay: float | None, scope: str | None, executor: StepExecutor, reporter: StepReporter)":
```

  **ADD** — param line after `delay`:

```
    `scope`: the block's step scope — carried from the facade `group` call (its `_scope` after ring-1
    validation) and passed down to the executor with every step; None — the group's steps address unscoped.
```

  **ADD** — property after `prompt -> str`:

```yaml
    "scope -> str | None": |
      The block's shared cache namespace; None — the group's steps address unscoped.
```

  **CHANGE** — `StepGroup.step`/`expect` signatures gain `, _scope: str | None`; **ADD** — param line:

```
      `_scope`: keyword-only, NOT accepted per step inside a group: a passed non-None value raises the loud
      actionable `PrettyplayError` naming the parameter and the remedy — the scope is set once on the group
      (`group(..., _scope=...)`), never per step; the delegation carries the group's `scope` instead.
```

  **ADD** — `StepGroup` Requirements line:

```
    - The group's scope governs every step of the block; group membership changes neither a step's scope nor
    its address — the group only passes its scope down
```

- **CHANGE** — `StepExecutor.execute` signature:

```yaml
    "execute(step_text: str, step_type: str, page: PageFacade, group: StepGroup | None, tries: int | None, delay: float | None, vars: dict[str, str] | None, scope: str | None)": |
```

  **ADD** — param line after `vars`:

```
      `scope`: the step scope of the call — None or empty — unscoped; passed by the facade methods (their
      `_scope` after ring-1 validation) or the group (its block scope); the executor adds no validation of its
      own — the rings own the rule.
```

  **CHANGE** — Algorithm step 2: the identity-build clause becomes:

```
      build the step identity from the render product's addressing text: `normalize_step_text` on the
      addressing text, then `StepIdentity` with the test cache key, the step type AND `scope` — None becomes
      the empty scope of the record; for a scoped step the scope is the address key (see `addressing` from
      Imports)
```

  **ADD** — Requirements lines:

```
      - A scoped step addresses by (scope, step_type, normalized_text); unscoped steps address exactly as
      before
      - The recovery delegation carries the scoped identity unchanged — the row mechanics re-address under the
      group's scope (see `recovery` from Imports)
```

**Footer**

- **CHANGE** — `Description:` gains “the site base URL property and the step scope authoring surface (`_scope`
  on step/expect/group with the two validation rings)”.

#### `.usages` — `prettyplay/.usages/steps.md` (modified)

- **ADD** — one bullet to “Step parameters”:

```
- step(text, _scope="pages/login") — the step scope: the shared cache namespace of one page object;
  keyword-only, None — unscoped; see "The step scope (_scope)"
```

- **ADD** — new section after “A test as a scenario”:

```md
## The site base URL

The root URL of the environment under test — configured once, read through the property:

```python
with PrettyPlay("login-flow") as t:
    t.step(f"open the page {t.site_base_url}/login")
```

- The value comes from `[tool.prettyplay.site] base_url` (env PRETTYPLAY_SITE_BASE_URL, programmatic
  `SiteConfig(base_url=...)`) — an http/https URL with a host, kept verbatim, empty when unset
- It is not wired into Playwright navigation: the URL the author renders into a sentence becomes part of the
  step address — staging and production keep separate cache entries
```

- **ADD** — new section after “Groups”:

```md
## The step scope (_scope)

A scope is the shared cache namespace of one page object: the same step phrase under one scope is one cache
entry for all tests — the first test generates it, the rest replay it without a model call. The integrator
layer sets it, per step or once per group:

```python
# per step on the facade, outside any group
t.step("open the dashboard", _scope="pages/dashboard")

# once per block — inherited by every step of the group
class LoginPage:
    def __init__(self, t: PrettyPlay):
        self._group = t.group("the user signs in", _scope="pages/login_page")

    def login(self, user: str):
        with self._group as g:
            g.step("fill the login field with {{ vars.user }}", vars={"user": user})
            g.step("click the sign-in button")
```

- `_scope` is keyword-only; None (the default) — unscoped, the step addresses exactly as before
- Inside a group the scope is set once at creation — a per-step `_scope` on the group object is rejected with
  a loud error naming the remedy
- Form: 1..N segments of `[A-Za-z0-9._-]+` joined by exactly one `/` (e.g. `pages/login_page`); an invalid
  value fails loudly at the call naming `_scope`, the received value and the allowed form — before anything
  renders or executes
- The scope replaces exactly two things: the key part of the step address and the file routing
  (`<cache root>/<scope>/`); the same phrase as an action and as an assertion remains two entries
- Scoped files survive every close-time sweep — cleanup concerns the test's unscoped steps only; budgets stay
  per test: the generating test pays, a reusing test pays nothing
- The scope never enters the rendered sentence or any LLM request
```

#### `.usages` — `prettyplay/.usages/lifecycle.md` (modified)

- **ADD** — one bullet to “Cache lifecycle on close”:

```
- scoped files (a step written under a `_scope`) are never swept: their metadata key is the scope, not the
  test's cache key — cleanup concerns the test's unscoped steps only
```

---

## Dependency Map

```
failures (unchanged)
   │  └──────────────────────────────┐ (NEW EDGE: PrettyplayError + taxonomy → cache, ring 2)
   │ (existing: PrettyplayError → config)
   ▼                                 ▼
config MOD ──(PrettyConfig)──► driver MOD        cache MOD ──(StepIdentity, StepCache,
   │                                                        validate_step_scope, RunBudgets,
   │ (existing: PrettyConfig,                                 normalize_step_text, addressing)──►
   │  BrowserConfig, SiteConfig NEW,                                               │
   │  load_config, adopt_config)                                                   │
   ▼                                                                               ▼
   ├──────────────────────► engine/groups MOD (trace identity scope, row re-address)
   │                                    │
   ▼                                    ▼
facade MOD  ◄──── (recovery: GroupRecovery, GroupStepOutcome — existing)
```

Leaf → root: `failures` → `config` → `{driver, cache}` → `engine/groups` → `prettyplay` (facade).
New edges: `cache ← failures` (PrettyplayError + taxonomy), `facade ← cache` (`validate_step_scope` +
`addressing`), `facade ← config` (`SiteConfig`), `groups ← cache` (`addressing` usage). All downward; no cycles.

## Verification Checklist

After implementing each artifact (all commands in the project venv, Python 3.10+):

**Per CODEMANIFEST (5):**

- `goga lint` passes for the modified manifest (DSL syntax: quoted signatures, flat `location` filenames,
  Imports/From correctness, embedding `->SiteConfig: {}`)
- `goga schema` reflects: `SiteConfig` and the new `validate_step_scope` in the type lists; the new
  dependency edges (cache→failures; the new Imports.Usages: `addressing` for groups and facade)
- Every backtick reference resolves inside its document (`validate_step_scope`, `addressing`, `taxonomy`,
  `SiteConfig`, `scope`, `_scope`, `address_key`, …)
- No annotation duplicates another level; no implementation details in annotations

**Per `.usages` file (7 updated):**

- The file renders as the current state (no changelog voice); every contract name matches the CODEMANIFEST
  signatures (`StepIdentity(..., scope=...)`, `_scope`, `site_base_url`)
- Practices are self-contained — no cross-references to other practices

**Behavior gates (the acceptance criteria of the task file, verified by the implementation's tests):**

1. Config: TOML/env/programmatic parse of `ignore_https_errors` and `site.base_url`; symmetric merge (explicit
   wins, empty never overwrites); invalid `site.base_url` → loud `ConfigurationError`; empty = unset
2. Driver: `new_context` receives `ignore_https_errors=True` in local, ws/wss and CDP paths; default false
   changes nothing; no WARNING on enable
3. Facade: `pp.site_base_url` verbatim (no trailing-slash normalization)
4. Ring 1 (parametrized with the task file's forbidden list `""`, `"/pages"`, `"pages/"`, `"pages//login"`,
   `"pages/../login"`, `".."`, `"\\pages"`, `"C:pages"`, `"pages/login page"`, `"страницы"`): loud
   `PrettyplayError` naming `_scope`, the value, the form — on `step`, `expect`, `group`; `StepGroup.step/expect`
   reject `_scope`
5. Ring 2: cache addressing rejects the same set; never softer than the existing structural bans
6. Addressing: (scope, step_type, normalized_text) address; `root/<scope>/` routing; digest excludes the
   routing path; action vs assertion = two entries under one scope; unscoped addresses unchanged
7. Sweep: scoped files survive every close-time sweep; untouched unscoped files still swept
8. Budgets: generating test pays, reusing test pays nothing
9. Strict mode: scoped-address miss fails loudly — nothing scope-specific
10. Recovery: row re-addressed under the group's scope — pinned with a test
11. Parallel generation: both tests generate on own budgets; atomic write keeps the file valid
12. `pytest tests/ -x` green; `ruff check prettyplay/` clean
