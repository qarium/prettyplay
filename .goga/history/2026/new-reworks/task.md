# Insecure TLS switch, site base URL, and the shared step scope

## Current State

The task area is the prettyplay package (the Playwright-driven step-scenario
library). Derived from the code analysis:

- **TLS switch.** `BrowserConfig` (`prettyplay/config/models.py`) carries
  name/screen/headless/endpoint/accept_dialogs/speed/timeout — there is no
  `ignore_https_errors` field. `DriverSession.open_context`
  (`prettyplay/driver/session.py`) passes only the screen-mode parameters to
  `new_context`; pages behind self-signed or invalid certificates (staging
  grids, CI) fail to open in every start mode — local launch, ws/wss connect
  (Playwright protocol), http/https connect (CDP).
- **Site base URL.** `PrettyConfig` has no `site` group; the top-level
  `base_url` is the LLM API endpoint, so no name collision exists. The address
  of the environment under test is hardcoded inside step sentences of every
  test; the facade `PrettyPlay` exposes no `site_base_url` property.
- **Step scope.** A step is addressed by
  `StepIdentity(cache_key, step_type, normalized_text)`
  (`prettyplay/cache/models.py`); the file name is the sha256 of the triple,
  stored under `root/<cache_path>/`. The same step phrase under two cache keys
  is generated twice — page objects cannot share generated step code across
  tests. `PrettyPlay.step/expect` and `PrettyPlay.group` accept no `_scope`.
  The close-time sweep (`StepCache.sweep_untouched`) filters files by the
  `CACHE_KEY` header of the metadata; `_validated_subdir` already rejects
  absolute paths and `..` segments.

The authoritative input is the ADR at `.goga/history/2026/new-reworks/adr.md`.

## Description

Three decisions of the new-reworks line, implemented together:

1. **D1 — `browser.ignore_https_errors`.** A boolean of the browser group
   (default `false`). Full configuration surface — TOML
   `[tool.prettyplay.browser]`, env `PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS`,
   programmatic config — participating in the layered merge like every
   browser-group field. Applied as a **context parameter** (`new_context(
   ignore_https_errors=True)`), never a launch argument, which makes every
   start mode identical: local launch, ws/wss remote connect, http/https CDP.
   Enabling is silent — no WARNING is logged.

2. **D2 — `site.base_url`.** A new nested `site` group holding the single
   `base_url` field — the root URL of the environment under test. TOML
   `[tool.prettyplay.site]`, env `PRETTYPLAY_SITE_BASE_URL`, programmatic
   config. The layered merge is symmetric to the browser group: an explicitly
   passed value wins, an empty field never overwrites the file layer.
   Validation: a non-empty value must be an http/https URL (scheme + netloc)
   or the loud `ConfigurationError` fires; empty means unset. The value is
   kept verbatim — no trailing-slash normalization; the author composes URL
   strings. Tests read it through the facade property `site_base_url`. No
   implicit Playwright wiring: `new_context(base_url=...)` is out of scope.

3. **D3 — `_scope`.** Steps gain the keyword-only service parameter `_scope` —
   the shared cache namespace of one page object (the integrator layer). It is
   accepted per step on the facade `step`/`expect`, and once per block on
   `PrettyPlay.group(..., _scope=...)`, inherited by every step of the group;
   it is **not** accepted per step inside a group. A scope is a relative
   subdirectory of the cache root (`pages/login_page`); for the scoped step it
   replaces exactly two things: the test cache key inside the address
   (key = the scope) and the file routing (`root/<scope>/`). The full address
   stays (key, step_type, normalized_text after NFC+trim) — the same phrase as
   an action and as an assertion remains two entries even under one scope.
   The routing path never enters the digest file name: the scope already
   addresses the step, the path only routes. One step phrase under one scope
   is one cache entry for all tests; unscoped steps address exactly as before.
   The metadata key of a scoped file is the scope itself, so the close-time
   sweep of any test never touches scoped files. Budgets follow the runtime:
   the generating test pays from its own budget, a reusing test pays nothing;
   there is no shared scope budget. A scoped-address miss in strict mode is
   the same loud "generation forbidden" failure. A recovery row is
   re-addressed by the re-rendered text under the group's scope — the row
   identity carries both address parts. Parallel generation of the same scope
   by two tests keeps the write atomic (mkstemp + `os.replace`); last writer
   wins and the file stays valid for both (the read checks CACHE_KEY/STEP_TYPE
   and the digest name).

   **Validation — two rings.** Ring 1 at the call site, before any render or
   execution: the loud authoring `PrettyplayError` naming the parameter, the
   received value and the allowed form. The rule: 1..N segments of
   `[A-Za-z0-9._-]+` joined by exactly one `/`; forbidden — the empty string,
   leading/trailing `/`, empty segments, any `..` segment, absolute forms
   (leading `/`, `\`, `C:`), and every other character (spaces, non-ASCII).
   Ring 2 re-enforces the same forbidden set in cache addressing, so the
   address cannot escape the cache root even by bypassing the facade; it must
   reject exactly the same set as ring 1 and may not be softer than the
   structural bans already present (`_validated_subdir`: absolute paths and
   `..` segments). The existing `cache_path` is not tightened retroactively —
   the strict charset applies to the scope from birth only.

### Target API (usage examples)

D1 — configuration:

```toml
[tool.prettyplay.browser]
ignore_https_errors = true
```

D2 — configuration and the facade property:

```toml
[tool.prettyplay.site]
base_url = "https://staging.example.com"
```

```python
pp = PrettyPlay("test_login")
pp.step(f"open the page {pp.site_base_url}/login")
```

D3 — the page-object layer (the integrator):

```python
class LoginPage:
    def __init__(self, pp: PrettyPlay):
        self._group = pp.group("the user signs in", _scope="pages/login_page")

    def login(self, user: str):
        self._group.step("fill the login field with {{ vars.user }}", vars={"user": user})
        self._group.step("click the sign-in button")

# a per-step scope on the facade, outside any group
pp.step("open the dashboard", _scope="pages/dashboard")
```

Forbidden scope values rejected by ring 1 with `PrettyplayError`:
`""`, `"/pages"`, `"pages/"`, `"pages//login"`, `"pages/../login"`, `".."`,
`"\\pages"`, `"C:pages"`, `"pages/login page"`, `"страницы"`.

## Scope

**In scope:**
- `BrowserConfig.ignore_https_errors` (bool, default `false`) with the full
  layered-merge surface (TOML, env `PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS`,
  programmatic overlay) and the context-parameter application in
  `DriverSession.open_context` for every start mode; silent enable
- The nested `SiteConfig` group (`site.base_url`) with the browser-symmetric
  merge (explicit wins, empty never overwrites the file layer), http/https
  validation with the loud `ConfigurationError`, verbatim value adoption, and
  the facade property `PrettyPlay.site_base_url`
- The keyword-only `_scope` on `PrettyPlay.step`/`PrettyPlay.expect` and on
  `PrettyPlay.group(...)` (inherited by the group's steps; rejected per step
  inside a group)
- Ring 1 scope validation at the call site (`PrettyplayError` naming the
  parameter, the received value, the allowed form)
- Scoped addressing in the cache: the scope as the address key, routing to
  `root/<scope>/`, the routing path excluded from the digest file name, the
  metadata key of a scoped file equal to the scope
- Ring 2 validation in cache addressing — the same forbidden set as ring 1,
  never softer than `_validated_subdir`
- Sweep immunity of scoped files; budgets unchanged (per test); strict-mode
  behavior unchanged (loud miss); group recovery re-addressing under the
  group's scope
- Tests for every item above, including the recovery re-addressing pin and
  the parallel-generation atomicity

**Out of scope:**
- Wiring `site.base_url` into `new_context(base_url=...)` (relative
  navigation in generated code, shared cache entries across environments) — a
  separate large task recorded in the ADR
- Retroactive tightening of the existing `cache_path` charset — the strict
  charset applies to the scope only, from birth
- Any shared "scope budget" concept
- The exact contract placement of ring 2 inside the cache cell — left to the
  design stages, bound by the constraint above

## Acceptance Criteria

- Configuration tests: `ignore_https_errors` and `site.base_url` parse from
  TOML, env and the programmatic overlay; the merge is symmetric (an explicit
  value wins, an empty field never overwrites the file layer); an invalid
  `site.base_url` (non-http/https or no netloc) raises the loud
  `ConfigurationError`; an empty value means unset
- Driver tests: `new_context` receives `ignore_https_errors=True` when the
  setting is on — in the local launch, the ws/wss connect and the CDP connect
  paths; the default `false` changes nothing; no WARNING is logged on enable
- Facade tests: `pp.site_base_url` returns the verbatim configured value
  (no trailing-slash normalization)
- Ring 1 tests (parametrized): every forbidden value of the charset rule
  raises `PrettyplayError` naming `_scope`, the received value and the allowed
  form — on `step`, `expect` and `group`; `StepGroup.step/expect` reject
  `_scope` (not accepted per step inside a group)
- Ring 2 tests: cache addressing rejects the same forbidden set; it is never
  softer than `_validated_subdir` (absolute paths, `..` segments)
- Addressing tests: a scoped step addresses by (scope, step_type,
  normalized_text); the file routes to `root/<scope>/`; the digest file name
  excludes the routing path; the same phrase as an action and as an assertion
  under one scope remains two entries; unscoped steps address exactly as
  before — no collisions
- Sweep tests: the close-time sweep of a test never deletes scoped files
  (metadata key = scope); untouched unscoped files of the test's cache key are
  still swept
- Budget tests: the generating test pays from its own attempt budgets; a test
  hitting the shared file pays nothing
- Strict mode: a scoped-address miss fails loudly (generation forbidden),
  nothing scope-specific
- Recovery: a group recovery row is re-addressed by the re-rendered text under
  the group's scope — pinned with a test
- Parallel generation: two tests missing the same scope both generate on their
  own budgets; the atomic write keeps the file valid for both readers
- `pytest tests/ -x` green; `ruff check prettyplay/` clean

## Stack

- **Frameworks:** none new — Python 3.10+, configured through `pyproject.toml`
- **Libraries:** pydantic (config models and validators), Playwright sync API
  (the `ignore_https_errors` context parameter)
- **Infrastructure:** none

## External Dependencies

| Component  | Usage file                        | Status  |
|------------|-----------------------------------|---------|
| playwright | `.goga/usages/cooks/playwright.md` | updated |
| pydantic   | `.goga/usages/cooks/pydantic.md`   | existing |

Synced usage files are managed by `goga usages sync` — reference them read-only, never create or update them in the task.

## Risks and Constraints

- Ring 2 must reject exactly the same forbidden set as ring 1 (binding ADR
  constraint); its exact placement inside the cache cell is a design-stage
  decision
- The scoped address change must not collide with unscoped entries or change
  any unscoped address
- Sweep immunity relies on the metadata key of a scoped file being the scope
  itself — the header contract must stay consistent between writer and reader
- Project conventions bind the implementation: Python 3.10+, relative
  intra-package imports, pydantic models with `kw_only=True` and empty
  defaults, Google-style docstrings, no fixed delays, structured logging with
  lowercase event names

## Scope Estimate

Single task — all three ADR decisions (D1, D2, D3) implemented together,
per the user's decision during formulation. No decomposition, no additional
topics.

## Existing Architecture

Affected cells (per `goga schema`):

- `prettyplay/config` — `BrowserConfig` gains `ignore_https_errors`; the new
  `SiteConfig` group joins `PrettyConfig`; `load_config` extends the layered
  merge and the flat env overrides (`PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS`,
  `PRETTYPLAY_SITE_BASE_URL`)
- `prettyplay/driver` — `DriverSession.open_context` applies the context
  parameter in every start mode
- `prettyplay` (facade) — `PrettyPlay.site_base_url` property; `_scope` on
  `step`/`expect`/`group`; ring 1 validation; `StepExecutor` threads the scope
  into the identity; `StepGroup` passes its scope down
- `prettyplay/cache` — `StepIdentity` carries the scope as the address key;
  `StepCache` routes `root/<scope>/`, writes the scope as the metadata key,
  enforces ring 2; the sweep stays key-filtered
- `prettyplay/engine/groups` — the group recovery row identity carries both
  address parts (the scope) for re-addressing

No new imports between cells are expected beyond the existing dependency
directions.

## Notes

- The ADR (`.goga/history/2026/new-reworks/adr.md`) is the authoritative
  source; the glossary terms **step scope** (`_scope`), **cache scope** (the
  pre-existing cache root + subdirectory boundary), **site base URL** and
  **integrator** keep their ADR meanings throughout the implementation
- Consequence of the accepted D2 option: the absolute URL rendered into a
  sentence becomes part of the cache address — staging and production keep
  separate cache entries (the "rendered values are data" principle)
- Group membership changes neither a step's scope nor its address — the group
  only passes its scope down
