# Design Document: `new-reworks-tls-site-scope`

Three contract amendments materialized by the apply stage (arch plan `.goga/history/2026/new-reworks/arch.md`),
designed here into a complete implementation specification:

- **D1 — insecure TLS**: `browser.ignore_https_errors` — a browser-group boolean applied as a Playwright
  context parameter at context creation, identical in every start mode.
- **D2 — site base URL**: the nested `site` group (`SiteConfig.base_url`) and the facade property
  `PrettyPlay.site_base_url` — the root URL of the environment under test, verbatim.
- **D3 — the step scope**: `_scope` on `step`/`expect`/`group` — the shared cache namespace of one page object,
  two validation rings (`validate_step_scope`), scoped addressing (`StepIdentity.scope`/`address_key`),
  scoped file routing (`root/<scope>/`), sweep immunity, budgets staying per test, and scope preservation
  through the group recovery row re-addressing.

Validation baseline of the contract layer: `goga lint` — 13 cells, **0 errors**; `goga schema` — the new edge
`cache → failures` present, the dependency graph acyclic, `SiteConfig` and `validate_step_scope` resolvable.

---

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/config/CODEMANIFEST`: new entity `SiteConfig`; `BrowserConfig` +`ignore_https_errors`;
  `PrettyConfig` +`site`; `load_config` env/merge/validation extensions; header/footer text.
- `prettyplay/cache/CODEMANIFEST`: new import edge to `prettyplay/failures` (`PrettyplayError`, usage `taxonomy`);
  new routine `validate_step_scope`; `StepIdentity` +`scope` +`address_key` with digest rules; `StepCache`
  ring-2 validation + scoped routing in `load`/`save`; `CachedStep`/`StepCache` scoped-metadata contract lines;
  sweep immunity requirement; header/footer text.
- `prettyplay/driver/CODEMANIFEST`: insecure-TLS header paragraph; `DriverSession` `config` inventory line;
  `open_context` step 3 + Requirements; footer.
- `prettyplay/engine/groups/CODEMANIFEST`: `addressing` usage import from cache; scope-preservation document
  annotation; `GroupStepOutcome.identity` (both address parts); `recover` step 5 + Requirements; footer.
- `prettyplay/CODEMANIFEST`: Imports +`SiteConfig`/`validate_step_scope`/usage `addressing`; `->SiteConfig: {}`
  embedding; `PrettyPlay.site_base_url` property; `_scope` on `step`/`expect`/`group`; `StepGroup` +`scope`
  (property, per-step `_scope` rejection); `StepExecutor.execute` +`scope` with scoped identity build; header/footer.

### New Entities

- `SiteConfig(base_url: str)` — `prettyplay/config/models.py`. The nested site group of the project settings:
  the root URL of the environment under test. Entity (properties, no methods) — a configuration model,
  symmetric to `BrowserConfig`.
- `validate_step_scope(scope: str)` — `prettyplay/cache/models.py`. Routine (a pure validator): the one scope
  charset rule serving both validation rings; raises `PrettyplayError` on violation.

### Changed Entities

- `BrowserConfig` — +`ignore_https_errors: bool` (default False); a plain group boolean, no dedicated validator
  (pydantic rejects non-booleans through the existing validation wrap).
- `PrettyConfig` — +`site: SiteConfig` group (default `SiteConfig()`); participates in the layered merge of
  `load_config` symmetrically to `browser`.
- `StepIdentity` — +`scope: str` (default `""`); +property `address_key -> str` (`scope` when non-empty,
  otherwise `cache_key`); `filename` digest built from `address_key` (unscoped digests byte-identical to before).
- `CachedStep` — no signature change; the file metadata contract now keys `CACHE_KEY` on `identity.address_key`.
- `StepCache` — `load`/`save` gain ring-2 scope validation and scoped routing (`root/<scope>/`, `mkdir` on save,
  store subdirectory never applied to scoped steps); `sweep_untouched` gains the scoped-immunity requirement
  (satisfied by the existing key filter plus non-recursive enumeration).
- `DriverSession.open_context` — the resolved context parameters now include `ignore_https_errors` from the
  browser group — one surface at `new_context`, every start mode.
- `GroupStepOutcome` — no signature change; `identity` documented as carrying both address parts (cache_key AND
  scope) — the row mechanics take both.
- `GroupRecovery.recover` — row step 5 builds every fresh row identity with the trace identity's `cache_key`
  AND `scope`; a scoped group's rows re-address under the group's scope.
- `PrettyPlay` — `step`/`expect`/`group` gain the keyword-only `_scope` (ring-1 validation before any render or
  execution); +property `site_base_url`; `cache_path` documented as never applying to scoped steps.
- `StepGroup` — constructor +`scope: str | None` (carried from the facade after ring-1 validation); +property
  `scope`; `step`/`expect` +`_scope` parameter that is **rejected** when non-None (the scope is set once per
  block); the delegation carries the group's scope.
- `StepExecutor.execute` — +`scope: str | None`; the step identity is built with the scope (`None` becomes the
  empty scope of the record); no validation of its own — the rings own the rule.

### Deleted Entities

None — all five cells are modifications; nothing removed.

### Usages and Annotations Changes

- `prettyplay/cache/.usages/addressing.md` — identity table +`scope` row; "The step scope" section; scoped
  `StepIdentity` example; Layout routing paragraph.
- `prettyplay/cache/.usages/storage.md` — File format paragraph (CACHE_KEY = the address key); "Shared scope
  entries" section.
- `prettyplay/cache/.usages/budgets.md` — scoped-budgets bullet (per-test budgets, no shared scope budget).
- `prettyplay/config/.usages/configuration.md` — TOML example (+browser/site groups), env table rows
  (PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS, PRETTYPLAY_SITE_BASE_URL), "Insecure TLS" and "Site base URL"
  sections, Rules line.
- `prettyplay/.usages/steps.md` — `_scope` parameter bullet, "The site base URL" and "The step scope (_scope)"
  sections.
- `prettyplay/.usages/lifecycle.md` — scoped-files-survive-sweep bullet.
- `prettyplay/engine/groups/.usages/recovery.md` — the re-address bullet carries the cache key AND the scope.
- `.goga/usages/cooks/playwright.md` — "Insecure TLS — the `ignore_https_errors` context parameter" section
  (the Playwright practice the driver annotation cites).
- New import edges for usages: facade and groups import `addressing` from `prettyplay/cache`; cache imports
  `taxonomy` from `prettyplay/failures`.

---

## Applied Fixes

### Fixed CODEMANIFEST Defects

None. The contract validation phase (DSL syntax, `goga lint` — 0 errors across 13 cells; the four consistency
dimensions below) found no defects; the apply stage had already reconciled 35 annotation-reference issues.

Consistency audit results (all passed):

1. **Interface ↔ Type** — `SiteConfig`, `validate_step_scope`, `PrettyplayError` are declared by their provider
   cells and imported where used; `StepGroup.scope -> str | None` matches the constructor parameter;
   `StepExecutor.execute(..., scope: str | None)` matches the facade delegation ("`vars` AND scope").
2. **Type ↔ Mutation** — no new mutations or embeddings except `->SiteConfig: {}`, whose type is present in
   `Imports` (embedding rule satisfied, uniform with `PrettyConfig`/`BrowserConfig`).
3. **Interface ↔ Interface** — save serializes `CACHE_KEY` from `identity.address_key` and load compares
   `CACHE_KEY` against `identity.address_key` (one contract, both sides); the executor builds the identity with
   the scope and the recovery rebuilds row identities with the trace identity's scope; the facade's ring 1
   (`_scope` non-None ⇒ validate) composes with the store's ring 2 (non-empty scope ⇒ validate) without overlap
   or gap — the executor deliberately validates nothing.
4. **Annotations ↔ Entity** — every backtick reference resolves in its document context (lint-verified);
   every connected practice is referenced (`addressing` — facade/group/executor annotations; `taxonomy` —
   cache annotations; `configuration`/`playwright` — driver annotations).

---

## Entity Interaction and Data Flow

### Interaction Diagram

```
                 integrator / page-object layer
                    │  step(text, _scope="pages/login")
                    │  group(prompt, _scope="pages/login_page")
                    ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ PrettyPlay (facade)                RING 1                    │
  │   _scope is not None → validate_step_scope(_scope)           │
  │   before _ensure_page(), before any render or execution      │
  └───────────────┬──────────────────────────────┬───────────────┘
                  │ scope: str | None            │ site_base_url -> str
                  ▼                              ▼
  ┌──────────────────────────┐        ┌───────────────────────────┐
  │ StepGroup (block scope)  │        │ PrettyplayRuntime.config  │
  │   scope property; passes │        │   .site.base_url (verbatim)│
  │   block scope down with  │        └───────────────────────────┘
  │   every step; per-step   │
  │   _scope rejected loudly │        ┌───────────────────────────┐
  └────────────┬─────────────┘        │ config: BrowserConfig     │
               │ scope=block scope    │   .ignore_https_errors    │
               ▼                      └────────────┬──────────────┘
  ┌─────────────────────────────────────────────── ▼──────────────┐
  │ StepExecutor.execute(step_text, step_type, page, group,       │
  │                       tries, delay, vars, scope)              │
  │   identity = StepIdentity(cache_key, step_type,               │
  │                normalize_step_text(addressing_text),          │
  │                scope or "")                                   │
  │   identity.address_key = scope when set, else cache_key       │
  └───────┬───────────────────────────────────────┬───────────────┘
          │ load/save(identity)                   │ recover(...) on a group failure
          ▼                                       ▼
  ┌──────────────────────────────┐   ┌────────────────────────────────────┐
  │ StepCache          RING 2    │   │ GroupRecovery.recover              │
  │  non-empty scope →           │   │  row step: fresh identity from     │
  │  validate_step_scope again   │   │  re-rendered text + trace identity │
  │  scoped: root/<scope>/       │   │  cache_key AND scope               │
  │  CACHE_KEY = address_key     │   │  (the group's scope threads        │
  │  sweep filters by cache_key  │   │   through every row identity)      │
  │  → scoped files never swept  │   └────────────────────────────────────┘
  └──────────────────────────────┘
```

### Data Flows

**Flow 1 — a scoped facade step (cache miss, first test)**:
`PrettyPlay.step(text, _scope="pages/login")` → ring 1 `validate_step_scope("pages/login")` passes →
`_ensure_page()` (browser lazily started; context opened with `ignore_https_errors` from the browser group) →
`StepExecutor.execute(..., scope="pages/login")` → `render_step` produces `PreparedStep` →
`StepIdentity(cache_key, "action", normalized, "pages/login")` → `StepCache.load` (ring 2 passes; looks in
`root/pages/login/<digest>.py`; miss → None) → generator `generate` (budget keyed by the scoped identity) →
`StepCache.save` (ring 2; `mkdir root/pages/login`; `CACHE_KEY = "pages/login"`; atomic replace) →
captures publish; trace/scenario records appended. A second test with the same phrase and scope hits the file
and pays no budget.

**Flow 2 — a scoped group block**:
`PrettyPlay.group(prompt, _scope="pages/login_page")` → ring 1 at entry → `StepGroup(..., scope=...)` →
each `g.step(text)` (no per-step `_scope` allowed) → `_delegate(..., scope=self._scope)` → executor as Flow 1 →
trace records carry the scoped identity → on a row failure `GroupRecovery.recover` re-renders each row step and
rebuilds `StepIdentity` with the trace identity's cache_key AND scope — regeneration, budget refresh and
write-back all key on the fresh scoped identity.

**Flow 3 — close with cleanup=True**:
`PrettyPlay.close()` → runtime teardown → `StepCache.sweep_untouched(cache_key)` enumerates only this store's
unscoped directory; scoped files live in `root/<scope>/` (never enumerated) and carry `CACHE_KEY = scope`
(key filter) — doubly immune; only this test's untouched unscoped files of its key are deleted.

**Flow 4 — the site base URL**:
`load_config()` (file `[tool.prettyplay.site] base_url` + env `PRETTYPLAY_SITE_BASE_URL` + programmatic
`SiteConfig(base_url=...)` overlay) → `PrettyConfig.site` → `PrettyplayRuntime.config` →
`PrettyPlay.site_base_url` (verbatim, `""` when unset) → the author composes `f"{t.site_base_url}/login"` into a
step sentence — the rendered URL becomes part of the addressing text (staging and production are separate
cache entries; the value is never wired into Playwright navigation).

**Flow 5 — the insecure-TLS switch**:
`BrowserConfig(ignore_https_errors=True)` (file/env/programmatic layers alike) → `DriverSession` holds
`config` → first `open_context()`: `params = screen params + {"ignore_https_errors": True}` →
`browser.new_context(**params)` inside the driver thread — identical for a local launch, a ws/wss connect and
an http/https CDP connect; silent (no log record).

### Entity Dependencies

Implementation order (leaves → root, matching the plan):

1. `prettyplay/config` — no new provider dependencies (`failures` unchanged); everything else consumes it.
2. `prettyplay/cache` — after config; gains the `failures` edge (acyclic: failures imports nothing).
3. `prettyplay/driver` — after config; independent of the cache changes.
4. `prettyplay/engine/groups` — after cache (row re-addressing uses the scoped `StepIdentity`).
5. `prettyplay` (facade) — last: imports `SiteConfig` from config, `validate_step_scope` + `addressing` from
   cache; re-exports `SiteConfig`.

Package facades to update alongside: `prettyplay/config/__init__.py` (+`SiteConfig`),
`prettyplay/cache/__init__.py` (+`validate_step_scope`), `prettyplay/__init__.py` (+`SiteConfig` re-export).

---

## Code Stack Trace

### Trace: `SiteConfig` construction (validation path)

#### Chain
1. **Input**: `SiteConfig(base_url="https://staging.example.com")` — programmatic layer; or pydantic
   constructing the group inside `PrettyConfig(**merged)` from the file+env layer.
2. **Step**: pydantic `kw_only`, `extra="forbid"`, `base_url: str = ""` → checkpoint: empty default per
   conventions ✓.
3. **Step**: `field_validator("base_url")` — empty passes verbatim (unset); non-empty parsed with
   `urlparse(value)`; requires `scheme in {"http", "https"}` and non-empty `netloc`; anything else raises
   `ValueError("must be an http/https URL with a host")` → checkpoint: rule matches the contract exactly
   (scheme + netloc; no trailing-slash normalization, no path restrictions) ✓.
4. **Step**: a `ValueError` from the programmatic path surfaces as the ordinary pydantic `ValidationError`
   (the constructor validates like the loader — one place of validation); from the loader path it is wrapped by
   `_render_validation` into `ConfigurationError` naming the setting, the received value and the allowed form,
   the original chained → checkpoint: matches "fails loudly through the existing validation wrap" ✓.
5. **Output**: a frozen-behavior pydantic model instance; `base_url` verbatim.

#### Checkpoint Summary
- Empty value passes and means unset: passed.
- Non-http(s) schemes (`ftp://x`, `example.com` with no scheme) and empty-host forms (`https://`) rejected:
  passed.
- No collision with the top-level `base_url` (the LLM endpoint): the group scopes the field name — pydantic
  nests it under `site.`: passed.

### Trace: `load_config` (site group + TLS boolean through the layered merge)

#### Chain
1. **Input**: `load_config(pyproject_path=None, overrides=None)`; pyproject carries
   `[tool.prettyplay.site] base_url = "https://staging.example.com"` and
   `[tool.prettyplay.browser] ignore_https_errors = true`; env carries `PRETTYPLAY_SITE_BASE_URL`;
   `overrides` carries `PrettyConfig(site=SiteConfig(base_url="https://prod.example.com"))`.
2. **Step**: legacy rejection and flat-key rejection unchanged → checkpoint: no interaction with the new
   fields ✓.
3. **Step**: `_collect_env_overrides()` — `_ENV_NAMES` now includes `"browser.ignore_https_errors"` (parsed by
   `_parse_env_scalar` through `_BOOL_ENV_SETTINGS` — true/false/1/0 case-insensitive, unparseable raises
   `ConfigurationError` naming the setting) and `"site.base_url"` (a string, taken verbatim — no parse set)
   → checkpoint: boolean parse reuses the existing rule; the string stays verbatim ✓.
4. **Step**: the dotted env merge generalizes from browser-only to per-group: every dotted setting splits into
   `(group, field)`; each group's env fields merge into `merged[group] = {**section.get(group, {}), **env}`;
   `site` appears as its own nested section beside `browser` → checkpoint: `site.base_url` from env lands in
   `merged["site"]["base_url"]`, never as a flat `site_base_url` key ✓.
5. **Step**: `PrettyConfig(**merged)` validates — `site` constructs `SiteConfig` (Flow: SiteConfig trace);
   `browser` constructs `BrowserConfig` with the boolean (pydantic rejects a non-boolean with the standard
   wrap) → checkpoint: one model, one place of validation ✓.
6. **Step**: `overrides is None` → return. Else `_apply_overrides` — the group-merge branch now covers both
   group models: an explicitly set field of a passed `SiteConfig`/`BrowserConfig` (`model_fields_set`,
   non-empty for strings) wins over the file group; untouched group defaults never overwrite;
   `update[name] = getattr(file_config, name).model_copy(update=group_update)` → checkpoint: symmetric to the
   browser group, exactly the contract line ✓.
7. **Output**: the effective `PrettyConfig` with `site` and `browser.ignore_https_errors` resolved.

#### Checkpoint Summary
- `PRETTYPLAY_SITE_BASE_URL=""` (empty, but set) is collected as a set override and lands in
  `merged["site"]["base_url"] = ""` — the file value is replaced by unset, symmetric to
  `PRETTYPLAY_MODEL=""` (the string-empty guard applies to the programmatic layer only): passed.
- `PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS=maybe` raises the loud `ConfigurationError` (boolean parse rule):
  passed.
- `adopt_config` needs no change — an empty `cache_root` resolution only; the site group adopts verbatim:
  passed.

### Trace: `PrettyPlay.site_base_url`

#### Chain
1. **Input**: the property read on the constructed test object.
2. **Step**: `return self._runtime.config.site.base_url` — the effective config (loaded or adopted) holds the
   group → checkpoint: the facade already retains `self._runtime`; no new state ✓.
3. **Output**: `str` — verbatim, `""` when unset; no normalization, no page interaction.

#### Checkpoint Summary
- Type matches the contract property `site_base_url -> str`: passed.

### Trace: `validate_step_scope`

#### Chain
1. **Input**: `validate_step_scope("pages/login_page")` (ring 1 — facade `_scope` non-None; ring 2 — store,
   non-empty identity scope).
2. **Step**: `segments = scope.split("/")` → checkpoint: `""` yields `[""]` — no valid segments ✓.
3. **Step**: every segment must `re.fullmatch(r"[A-Za-z0-9._-]+", segment)` — at least one character of ASCII
   letters, digits, dot, underscore, hyphen → checkpoint: spaces, backslashes, colons (`C:`), non-ASCII and
   empty segments (leading `/`, trailing `/`, double `/`) all fail here ✓. The dot is a legal character
   inside a segment — harmless there; traversal is `".."` only, banned by the separate rule of step 4.
4. **Step**: `".." in segments` → rejected → checkpoint: parent traversal banned ✓.
5. **Step**: any rejection raises `PrettyplayError` with the loud actionable message naming the parameter
   `_scope`, the received value and the allowed form (one render, deterministic) → checkpoint: pure function,
   no I/O, no normalization of accepted values ✓.
6. **Output**: `None` on acceptance — the value passes verbatim.

#### Checkpoint Summary
- One rule serves both rings — the same function object, never a re-implementation: passed.
- Absolute forms (`/pages`, `\pages`, `C:/pages`) rejected by the charset/empty-segment rules alone: passed.

### Trace: `StepIdentity.address_key` / `StepIdentity.filename`

#### Chain
1. **Input**: `StepIdentity(cache_key="login-flow", step_type="action", normalized_text="open the dashboard",
   scope="pages/dashboard")` — built by the executor (or the recovery row mechanics).
2. **Step**: `scope: str = ""` — the default keeps every existing construction unscoped → checkpoint:
   `tests`, `storage.md` examples and the recovery record-0 path construct without `scope` and stay
   unscoped ✓.
3. **Step**: `address_key` property returns `self.scope if self.scope else self.cache_key` → checkpoint: the
   digest, the metadata key and the sweep filter key on this one value, as the contract states ✓.
4. **Step**: `filename` builds `_IDENTITY_SEPARATOR.join((self.address_key, self.step_type,
   self.normalized_text))` → sha256 → `<hexdigest>.py` → checkpoint: with an empty scope the digest input is
   byte-identical to the pre-change triple — no unscoped address changes; the routing path never enters the
   digest ✓.
5. **Output**: the deterministic file name; a scoped step and an unscoped step with the same phrase and step
   type produce different digests whenever `scope != cache_key` (and when they are equal the addresses are
   genuinely the same address — coherent by construction).

#### Checkpoint Summary
- Unscoped digest stability (repository compatibility): passed.
- The record holds no validation (pure data — the rings own the rule): passed.

### Trace: `StepCache.load` (scoped)

#### Chain
1. **Input**: `load(identity)` with `identity.scope = "pages/login"`.
2. **Step**: ring 2 first — `if identity.scope: validate_step_scope(identity.scope)` before any path is
   composed; a violation raises `PrettyplayError` (the address never escapes the cache root even when the
   facade was bypassed) → checkpoint: the check precedes `_step_dir`/`filename` use ✓.
3. **Step**: resolve the target directory — scoped: `self._root / Path(identity.scope)` (the store's
   subdirectory never applies); unscoped: `self._target_dir()` (root + subdirectory, as before) →
   checkpoint: routing matches the contract ✓.
4. **Step**: a missing file returns `None`. On a hit: parse the header; verify `fields["CACHE_KEY"] ==
   identity.address_key` (the scope of a scoped step, the cache key otherwise — unchanged behavior for
   unscoped reads), `STEP_TYPE` equality, `STEP_TEXT` normalizing to `identity.normalized_text`; reconstruct
   `CachedStep` with the stored `STEP_TEXT` as `addressing_text`; record the file name in the touched set →
   checkpoint: the scoped reader accepts either concurrent writer's file — both wrote the same address
   (same `address_key`, same digest) ✓.
5. **Output**: `CachedStep | None`; structural damage is a miss, never a failure.

#### Checkpoint Summary
- Ring-2 ordering (validation before path composition): passed.
- Unscoped reads keep the exact pre-change behavior (`address_key == cache_key`): passed.

### Trace: `StepCache.save` (scoped)

#### Chain
1. **Input**: `save(step)` with `step.identity.scope = "pages/login"`.
2. **Step**: ring 2 first — validate the non-empty scope before any path is composed → checkpoint: identical
   rule, identical ordering as `load` ✓.
3. **Step**: writability check — the existing lazy probe of the store's directory; a read-only cache skips the
   write with `on_cache_skipped("read-only cache")` → checkpoint: unchanged ✓.
4. **Step**: `_serialize(step)` — the header literal `CACHE_KEY = repr(step.identity.address_key)` (the scope
   of a scoped file); `STEP_TEXT` from `addressing_text`; sentinel; code → checkpoint: identical bytes
   whichever test wrote the file ✓.
5. **Step**: resolve the target directory — scoped: `root/<scope>/`, `mkdir(parents=True, exist_ok=True)`
   before the temp write; unscoped: the effective root plus the subdirectory, as before → checkpoint: the
   temp file is created **in the target directory** (same filesystem as the replace) ✓.
6. **Step**: `tempfile.mkstemp(dir=target_dir)` → write + fsync → `os.replace` (atomic; Windows-busy retry
   path unchanged — last writer wins, a partial file never becomes visible) → checkpoint: two tests missing
   the same scope both generate on their own budgets and both files are valid for every reader ✓.
7. **Step**: `on_cache_saved` with the file name; the touched set records the file name → checkpoint: the
   touched set and the digest names share one key space ✓.
8. **Output**: `stored: bool`.

#### Checkpoint Summary
- A `mkdir`/`mkstemp` OSError degrades to the existing skip path (`on_cache_skipped`, never raising): passed.
- Scoped metadata key = the scope → the sweep key filter can never match a sweeping test's cache key: passed.

### Trace: `StepCache.sweep_untouched` (scoped immunity)

#### Chain
1. **Input**: `sweep_untouched(cache_key="login-flow")` at close, `cleanup=True`.
2. **Step**: enumerate `self._target_dir()` (the store's unscoped directory) — entries filtered by
   `_STEP_FILE_NAME` **and being a file** (a scope directory named like a digest — legal by the charset — must
   not produce a spurious unreadable-metadata WARNING) → checkpoint: scoped step files live in
   `root/<scope>/` and are never enumerated ✓.
3. **Step**: the metadata key filter (`fields["CACHE_KEY"] != cache_key → skip silently`) — a scoped file's
   key is its scope, never the sweeping test's cache key → checkpoint: defense in depth exactly as the
   contract requires ✓.
4. **Output**: `removed` — untouched unscoped files of this key only; best-effort, never raising, idempotent.

#### Checkpoint Summary
- "Scoped files are immune" holds by two independent mechanisms (non-recursive enumeration + key filter):
  passed.

### Trace: `DriverSession.open_context` (insecure TLS)

#### Chain
1. **Input**: the first `_ensure_page()` of the test; `config.browser.ignore_https_errors = True`;
   `config.browser.endpoint` selects the start mode (already resolved by `_launch`).
2. **Step**: inside `open_isolated` (driver thread): `params = {**self._screen_context_params(),
   "ignore_https_errors": self._config.browser.ignore_https_errors}` → checkpoint: one surface — the same
   `new_context` call as the screen modes; never a launch argument, so local launch, ws/wss connect and
   http/https CDP connect are identical ✓ (verified against `.goga/usages/cooks/playwright.md`:
   `browser.new_context(ignore_https_errors=True)`).
3. **Step**: `browser.new_context(**params)`; dialog router registration, `new_page`, the page default action
   timeout — all unchanged → checkpoint: no ordering interaction with the new parameter ✓.
4. **Step**: `False` (default) passes Playwright's untouched certificate checking; enabling is silent — no
   log record at any level → checkpoint: the contract's "no WARNING" line ✓.
5. **Output**: `PageFacade` of the fresh isolated context.

#### Checkpoint Summary
- The context parameter applies in every start mode because `_launch` branching is finished before
  `open_context` runs: passed.

### Trace: `PrettyPlay.step(text, _scope=...)` / `expect` (ring 1)

#### Chain
1. **Input**: `t.step("open the dashboard", _scope="pages/dashboard")`.
2. **Step**: the existing parameter validation block (`_validate_tries`, `_validate_delay`, `_validate_vars`)
   → then `if _scope is not None: validate_step_scope(_scope)` — ring 1 → checkpoint: fires **before**
   `_ensure_page()` (no browser starts for an invalid scope), before any render or execution ✓.
3. **Step**: a violation raises `PrettyplayError` naming `_scope`, the received value and the allowed form;
   the traceback folds to the library boundary (`_raise_folded`) — the existing guarantee ✓.
4. **Step**: `self._executor.execute(text, "action", self._ensure_page(), tries=tries, delay=delay,
   vars=vars, scope=_scope)` → checkpoint: the validated scope (a `str` or `None`) crosses as `scope` ✓.
5. **Output**: `None`; failures propagate by kind (`ProductDefectError`, `IncurableStepError`,
   `LLMUnavailableError`); `expect` is the same surface with `"assertion"`.

#### Checkpoint Summary
- `_scope=""` is rejected at ring 1 (empty yields no valid segments) — the executor's "None or empty —
  unscoped" is defensive internal normalization only: passed.

### Trace: `PrettyPlay.group(prompt, _scope=...)`

#### Chain
1. **Input**: `t.group("the user signs in", _scope="pages/login_page")`.
2. **Step**: prompt/speed/delay validation → `if _scope is not None: validate_step_scope(_scope)` at entry —
   before the block opens → checkpoint: an invalid scope raises before `StepGroup` construction and before
   `on_group_started` can ever fire ✓.
3. **Step**: `StepGroup(prompt, speed, delay, _scope, self._executor, self._reporter)`; the lazy page opener
   binding unchanged → checkpoint: the constructor grows the `scope` parameter in its documented position ✓.
4. **Output**: the `StepGroup` block object carrying the validated scope.

#### Checkpoint Summary
- `None` — the group's steps address unscoped: passed (executor receives `scope=None`).

### Trace: `StepGroup.step` / `expect` (inheritance + per-step rejection)

#### Chain
1. **Input**: `g.step("fill the login field", vars={...})` inside the block; or `g.step("...", _scope="x")`.
2. **Step**: existing validations; then `if _scope is not None: raise PrettyplayError(...)` naming the
   parameter and the remedy — the scope is set once on the group (`group(..., _scope=...)`), never per step →
   checkpoint: the rejection precedes the delegation, the pause and the page opener ✓.
3. **Step**: `_delegate` passes `scope=self._scope` (the block scope) to `executor.execute` → checkpoint:
   group membership changes neither a step's scope nor its address — the group only passes its scope down ✓.
4. **Output**: the ordinary step surface with the group context; the trace record's identity carries the
   scoped address.

#### Checkpoint Summary
- A per-step `_scope=None` inside a group is accepted (no override attempt) — only a non-None value is
  rejected: passed.

### Trace: `StepExecutor.execute` (scoped identity build)

#### Chain
1. **Input**: `execute(step_text, step_type, page, group, tries, delay, vars, scope="pages/login")`.
2. **Step**: the quiet delay; `render_step`; `on_step_started` with the ready layer — unchanged order →
   checkpoint: authoring errors still precede addressing ✓.
3. **Step**: `identity = StepIdentity(cache_key=self.cache_key, step_type=step_type,
   normalized_text=normalize_step_text(prepared.addressing_text), scope=scope or "")` — `None` becomes the
   empty scope of the record; the executor adds no validation of its own → checkpoint: for a scoped step the
   scope is the address key (`StepIdentity.address_key`); the scope never enters the rendered sentence or any
   LLM request (it is addressing data only) ✓.
4. **Step**: the settle window, the attempt history, the cache load/execute paths — all keyed by the identity
   as today; strict mode, healing, steering and the recovery delegation receive the scoped identity
   unchanged → checkpoint: the recovery delegation carries the scoped identity — the row mechanics re-address
   under the group's scope ✓.
5. **Output**: the step cycle outcome; `ScenarioStep` records unchanged in shape.

#### Checkpoint Summary
- Scoped and unscoped steps share one code path — only the identity differs: passed.

### Trace: `GroupRecovery.recover` (row re-addressing under the group's scope)

#### Chain
1. **Input**: `recover(group_prompt, traces, prepared, step_type, previous_steps, identity, attempt_history,
   page, window, memory)` — `identity` is the scoped execution-fact identity of the failed step.
2. **Step**: diagnosis, row matching — unchanged; `_ActiveFailure` keeps the scoped identity ✓.
3. **Step**: per row step — the declared delay, `render_step(trace.sentence, trace.step_type, memory,
   trace.vars)` → the fresh `PreparedStep` → checkpoint: re-render against the current context, unchanged ✓.
4. **Step**: `fresh_identity = StepIdentity(cache_key=trace.identity.cache_key,
   scope=trace.identity.scope, step_type=trace.step_type,
   normalized_text=normalize_step_text(fresh.addressing_text))` — the trace identity contributes its
   cache_key AND scope, the execution facts; the address itself is re-derived from the re-rendered text →
   checkpoint: a scoped group's rows re-address under the group's scope; a row step re-rendered against
   changed memory is a new address with a fresh budget ✓.
5. **Step**: `refresh_healing(fresh_identity)`; `regenerate(identity=fresh_identity, ...)`; the compliance
   gate; capture publication; the cache write-back under the fresh identity — all keyed consistently →
   checkpoint: the write-back never lands under a stale trace identity ✓.
6. **Output**: the healed `CachedStep` of the originally failed step on full row success; the failure cycle
   otherwise.

#### Checkpoint Summary
- Record 0 (`self._cache.load(trace.identity)`) already uses the scoped trace identity — no change needed
  there: passed.

---

## Algorithm Design

### `SiteConfig`

**Responsibility**: the nested site group of `PrettyConfig` — the root URL of the environment under test,
set once instead of being hardcoded in step sentences.

**Algorithm**:
```
1. pydantic model: kw_only=True, extra="forbid"; field base_url: str = ""
2. field_validator("base_url"):
   IF value == "": accept verbatim (unset)
   parsed = urlparse(value)
   IF parsed.scheme not in {"http", "https"} OR parsed.netloc == "":
       raise ValueError("must be an http/https URL with a host")
   accept verbatim — no trailing-slash normalization, no path checks
```

**Errors**:
- `pydantic.ValidationError` (programmatic construction) / `ConfigurationError` via the loader wrap
  (file+env layer) → the message names the setting (`site.base_url`), the received value and the allowed form.

**Edge Cases**:
- `""` → unset, valid (the default).
- `"https://"` (no netloc), `"example.com"` (no scheme), `"ftp://example.com"` → loud rejection.
- `"https://example.com/"` → kept verbatim including the trailing slash.

### `BrowserConfig` (+`ignore_https_errors`)

**Responsibility**: the browser group gains the insecure-TLS boolean.

**Algorithm**:
```
1. field ignore_https_errors: bool = False (kw_only, no dedicated validator)
2. non-boolean input (file layer, env parse aside) → the standard pydantic rejection through the loader wrap
```

**Errors**: as above — one place of validation.

**Edge Cases**: none beyond the boolean parse (env) — true/false/1/0 case-insensitive; anything else fails
loudly naming `browser.ignore_https_errors`.

### `load_config` / `_apply_overrides` (site group + TLS boolean)

**Responsibility**: the layered resolution extended symmetrically to the site group.

**Algorithm**:
```
_ENV_NAMES += {"browser.ignore_https_errors", "site.base_url"}
_BOOL_ENV_SETTINGS += {"browser.ignore_https_errors"}

load_config:
1..5. unchanged (pyproject discovery, legacy/flat-key rejection)
6. env overrides:
     parse each setting per its kind (_parse_env_scalar)
     group the dotted settings by prefix: browser.* → browser section, site.* → site section
     merged[g] = {**(merged.get(g) or {}), **fields_of_g}   for g in {"browser", "site"}
7. cache_root default — unchanged
8. PrettyConfig(**merged) → site/base_url validation inside the model; wrap ValidationError
9..10. _apply_overrides:
     for each explicitly set field of overrides (model_fields_set, non-None, non-empty for strings):
         IF the value is a group model (BrowserConfig or SiteConfig):
             group_update = its explicitly set fields (non-empty for strings)
             update[name] = getattr(file_config, name).model_copy(update=group_update)
         ELSE update[name] = value
11. return the effective PrettyConfig
```

**Errors**: `ConfigurationError` — the existing single wrap; one line per invalid setting.

**Edge Cases**:
- `PRETTYPLAY_SITE_BASE_URL` set but empty string → the env layer treats a set variable as an override with
  an empty value: the string guard of the overlay applies to the *programmatic* layer; for the env layer an
  empty override lands in `merged["site"]["base_url"] = ""` — which is the valid unset value, so the file
  value is replaced by unset. This matches the existing behavior of every string setting (e.g.
  `PRETTYPLAY_MODEL=""` clears the model) — symmetric, no special case.
- A passed `SiteConfig()` with no explicitly set fields → the file group survives untouched.

### `validate_step_scope`

**Responsibility**: the one scope rule of both validation rings.

**Algorithm**:
```
_SCOPE_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")

validate_step_scope(scope: str) -> None:
1. segments = scope.split("/")
2. IF scope == "" OR any(not _SCOPE_SEGMENT.fullmatch(s) for s in segments) OR ".." in segments:
       raise PrettyplayError(
           "invalid _scope {scope!r} — 1..N segments of ASCII letters, digits, dot, "
           "underscore or hyphen joined by single / characters, keyword-only"
       )
3. return None  (accepted verbatim — no normalization)
```

**Errors**:
- `PrettyplayError` → ring 1 (facade `step`/`expect`/`group` — traceback folded to the library boundary) and
  ring 2 (store `load`/`save` — surfaces to the caller of the store; through the facade it is unreachable for
  validated scopes by construction).

**Edge Cases**:
- `""`, `"/pages"`, `"pages/"`, `"pages//login"`, `".."`, `"a/../b"`, `"pages\\login"`, `"C:/pages"`,
  `"страница"` → all rejected by the two rules alone.
- `"pages/login_page"`, `"a"`, `"v1.2.config-x"` → accepted.
- `"."`-only segments (`"."`, `"pages/."`, `"..."`) are accepted by the charset rule — the dot is a legal
  segment character; they route nowhere special (`root / Path(".")` is the root itself, no traversal) and
  stay coherent under the one-address-space argument; only `".."` is banned, exactly as the contract states.

### `StepIdentity` (+`scope`, +`address_key`)

**Responsibility**: the address record — the triple plus the scope, pure data.

**Algorithm**:
```
1. field scope: str = ""   (kw_only; the default keeps existing constructions unscoped)
2. property address_key: scope if scope != "" else cache_key
3. property filename:
       identity_string = "\x1f".join((address_key, step_type, normalized_text))
       return f"{sha256(identity_string.encode('utf-8')).hexdigest()}.py"
```

**Errors**: none — the record holds no validation (the rings own the rule).

**Edge Cases**:
- `scope == cache_key` (e.g. an unscoped key that happens to equal a scope string) → one address space is
  preserved: identical digests and identical metadata keys — coherent by construction.

### `StepCache.load` / `StepCache.save` (scoped routing)

**Responsibility**: ring 2 and the scoped repository routing.

**Algorithm**:
```
_step_dir(identity) -> Path:
    IF identity.scope:
        validate_step_scope(identity.scope)          # ring 2 — before any path is composed
        return self._root / Path(identity.scope)     # the subdirectory never applies
    return self._target_dir()                        # root + the store subdirectory, as before

load(identity):
1. dir = _step_dir(identity)                         # ring 2 fires here
2. target = dir / identity.filename; missing → None
3. parse the header; verify CACHE_KEY == identity.address_key, STEP_TYPE == identity.step_type,
   normalize_step_text(STEP_TEXT) == identity.normalized_text; reconstruct CachedStep;
   touched += filename

save(step):
1. dir = _step_dir(step.identity)                    # ring 2 fires here
2. read-only probe → skip with on_cache_skipped
3. body = _serialize(step)                           # CACHE_KEY literal = identity.address_key
4. IF step.identity.scope: create the scoped directory — dir.mkdir(parents=True, exist_ok=True)
   inside the same OSError-guarded skip path as the temp write (an OSError here — e.g. a file
   occupying the scope path, or a missing create permission — reports on_cache_skipped with the
   reason "cache target busy" and returns False, never raising)
5. mkstemp(dir=dir) → write + fsync → os.replace → Windows-busy retry path unchanged
6. on_cache_saved; touched += filename
```

**Errors**: a scope violation raises `PrettyplayError` (ring 2); every I/O failure degrades to the existing
skip path — a save never fails the run.

**Edge Cases**:
- Two tests writing the same scoped address concurrently → identical bytes (same `address_key`, same code
  address), atomic replace, last writer wins — both readers accept either file.
- The store's `path` argument and a step's scope never compose — a scoped step in a `path="checkout"` store
  still routes to `root/<scope>/`.

### `StepCache.sweep_untouched` (immunity guard)

**Algorithm**:
```
candidates = (entry for entry in scope.iterdir()
              if entry.is_file() and _STEP_FILE_NAME.fullmatch(entry.name))
```
(the `is_file()` guard joins the existing name filter — scope directories are never step files).

**Edge Cases**: a scope literally named `<64 hex>.py` creates a directory matching the digest pattern — the
`is_file()` guard keeps it out of the candidates (no spurious WARNING); even without the guard the key filter
and the OSError path would keep the sweep safe.

### `DriverSession.open_context` (TLS parameter)

**Algorithm**:
```
inside open_isolated (driver thread):
    params = {**self._screen_context_params(),
              "ignore_https_errors": self._config.browser.ignore_https_errors}
    context = browser.new_context(**params)
    ... dialog router, new_page, set_default_timeout — unchanged
```

**Edge Cases**: none — the parameter rides an existing call in every start mode; enabling is silent.

### `GroupStepOutcome` / `GroupRecovery.recover` (scope threading)

**Algorithm**:
```
row step (recover, step 5):
    fresh = render_step(trace.sentence, trace.step_type, memory, trace.vars)
    fresh_identity = StepIdentity(
        cache_key=trace.identity.cache_key,     # the execution fact
        scope=trace.identity.scope,             # the execution fact — NEW
        step_type=trace.step_type,
        normalized_text=normalize_step_text(fresh.addressing_text),
    )
```
The `GroupStepOutcome` model itself is unchanged (its `identity: StepIdentity` carries the scope by the record
change); the docstring gains "both address parts".

**Edge Cases**: a scoped group whose row re-render produces changed memory → a new normalized text under the
same scope → a new address with a fresh budget — the designed semantics.

### `PrettyPlay` (ring 1, `site_base_url`)

**Algorithm**:
```
step(text, *, tries=None, delay=None, vars=None, _scope=None):
    _validate_tries/delay/vars
    IF _scope is not None: validate_step_scope(_scope)     # ring 1 — before _ensure_page()
    executor.execute(text, "action", self._ensure_page(), tries=..., delay=..., vars=..., scope=_scope)

expect(...): the same with "assertion"

group(prompt, *, speed=None, delay=None, _scope=None):
    prompt/speed/delay validation
    IF _scope is not None: validate_step_scope(_scope)     # ring 1 — before the block opens
    block = StepGroup(prompt, speed, delay, _scope, executor, reporter)

site_base_url -> str: self._runtime.config.site.base_url
```

**Errors**: `PrettyplayError` (folded) for every authoring/validation failure; the step-cycle failures
propagate by kind.

**Edge Cases**: `_scope=None` everywhere — exactly the pre-change behavior (scope `""` in the identity).

### `StepGroup` (block scope)

**Algorithm**:
```
__init__(prompt, speed, delay, scope, executor, reporter): self._scope = scope
scope -> str | None: self._scope
step/expect(text, *, tries, delay, vars, _scope=None):
    IF _scope is not None:
        raise PrettyplayError("the _scope is set once on the group — group(..., _scope=...), never per step")
    ... validations, pauses ...
    executor.execute(text, step_type, self._open_page(), group=self, tries=..., delay=..., vars=...,
                     scope=self._scope)
```

**Edge Cases**: the rejection fires before the entry/between-step pause and before the page opener — an
invalid per-step scope never opens a browser.

### `StepExecutor.execute` (+`scope`)

**Algorithm**:
```
execute(..., scope: str | None = None):
    ... delay, render, on_step_started ...
    identity = StepIdentity(cache_key=self.cache_key, step_type=step_type,
                            normalized_text=normalize_step_text(prepared.addressing_text),
                            scope=scope or "")
    ... the cycle unchanged, keyed by the identity ...
```

**Edge Cases**: no validation added — the rings own the rule; `""` and `None` are equivalent (unscoped).

---

## Cross-cutting Concerns

- **Error handling**: the loud actionable `PrettyplayError` style with the folded traceback covers the new
  authoring surface (`_scope`); ring 2 raises the same error type from the store; the configuration path keeps
  its single `ConfigurationError` wrap. Nothing new propagates raw.
- **Validation**: ring 1 at the facade call sites (`step`/`expect`/`group` — before any render, execution or
  page opening); ring 2 at the store addressing (`load`/`save` — before any path composition); the executor
  deliberately validates nothing. The config validation extends one model, one place.
- **Logging**: no new log records. Enabling the TLS switch is silent by contract; scoped saves/skips ride the
  existing cache events; the sweep keeps its per-deletion records. (The `is_file()` sweep guard *removes* a
  potential spurious WARNING rather than adding output.)
- **Caching**: the scope changes addressing only — digest stability for unscoped entries is a hard guarantee;
  scoped entries are shared (sweep-immune), atomic-replace safe for concurrent writers, and budget-free for
  reusing tests.
- **Concurrency**: one `PrettyplayRuntime` per test remains the isolation unit; scoped files are the only
  cross-test shared artifact and are safe by identical bytes + atomic replace. Budgets stay per test — no
  shared scope budget exists. The driver-thread model is untouched.
- **Compatibility**: no unscoped address changes (digest and metadata identical); the touched set, the sweep
  and the team workflow (committed caches, `cleanup=False`) behave exactly as before for unscoped steps.

---

## Usages Analysis

### `conventions` (project-level, `.goga/usages/conventions.md`)
- **What it provides**: Python rules — pydantic `kw_only` + empty defaults, relative imports, Google
  docstrings, log levels, test structure/mirroring, ruff/pytest validation commands.
- **Where used**: every changed file; the new tests.
- **Why chosen**: the mandatory project practice.
- **How exactly**: `SiteConfig`/`BrowserConfig` fields follow kw_only + neutral defaults; tests mirror
  `tests/<package>/test_<module>.py`; venv in `/opt/project`.

### `playwright` (project-level, `.goga/usages/cooks/playwright.md`)
- **What it provides**: the sync-API practice — lifecycle, screen modes at `new_context`, remote connects, the
  new "Insecure TLS" section.
- **Where used**: `DriverSession.open_context` (the only driver change).
- **Why chosen**: the driver cell's declared library practice.
- **How exactly**: `browser.new_context(ignore_https_errors=...)` — a context parameter, never a launch
  argument; verified in the cook, section "Insecure TLS".

### `configuration` (imported from `prettyplay/config/.usages/configuration.md`)
- **What it provides**: the settings surface as consumed by other cells.
- **Where used**: `DriverSession` (reads the browser group incl. `ignore_https_errors`).
- **How exactly**: `config.browser.ignore_https_errors` — documented in the "Insecure TLS" section of the
  usage file.

### `taxonomy` (imported from `prettyplay/failures/.usages/taxonomy.md`)
- **What it provides**: the failure kinds and the loud actionable message style.
- **Where used**: `validate_step_scope` (raises `PrettyplayError`); the cache cell's new import edge.
- **How exactly**: `PrettyplayError` with the parameter/value/allowed-form message — no structured verdict,
  an authoring error.

### `addressing` (imported from `prettyplay/cache/.usages/addressing.md`)
- **What it provides**: the identity model — now with the scope row, the scope form and the scoped routing.
- **Where used**: the facade annotations (`step`/`expect`/`group`/executor), the groups recovery annotations.
- **Why chosen**: the bridging practice for the cross-cell scope semantics — the facade and the recovery route
  their addressing through it.
- **How exactly**: `StepIdentity(..., scope=...)`, `identity.address_key`, `root/<scope>/` routing — the file
  documents the exact consumer-facing patterns.

### `hooks` (imported from `prettyplay/reporting/.usages/hooks.md`)
- **Where used**: unchanged cache events (`on_cache_saved`/`on_cache_skipped`) — no new events; referenced
  where the contract already referenced them.

### Imported Usages — traceable cross-cell links
- `addressing` from `prettyplay/cache` — imported by `prettyplay` (facade) and `prettyplay/engine/groups`;
  path `prettyplay/cache/.usages/addressing.md` (exists).
- `taxonomy` from `prettyplay/failures` — imported by `prettyplay/cache`; path
  `prettyplay/failures/.usages/taxonomy.md` (exists).
- `configuration` from `prettyplay/config` — imported by `prettyplay/driver`; path exists.
- `recovery` from `prettyplay/engine/groups` — imported by the facade; carries the re-address-with-scope line.

---

## `.usages/` Update

### Cell: `prettyplay/config`
- **`configuration.md`** → current (the apply stage added the TOML groups, both env rows, "Insecure TLS",
  "Site base URL", the Rules line). Additions needed: none. Updates needed: none.

### Cell: `prettyplay/cache`
- **`addressing.md`** → current (scope row, scope section, scoped example, layout routing).
- **`storage.md`** → current (file format with the address-key CACHE_KEY, "Shared scope entries").
- **`budgets.md`** → current (the scoped-budgets bullet). No new file needed — all changes live inside the
  existing domains (addressing, storage, budgets).

### Cell: `prettyplay/engine/groups`
- **`recovery.md`** → current (the re-address bullet carries cache key AND scope). No new file.

### Cell: `prettyplay` (facade)
- **`steps.md`** → current (`_scope` bullet, "The step scope (_scope)", "The site base URL").
- **`lifecycle.md`** → current (scoped-files-survive-sweep). No new file.

### Cell: `prettyplay/driver`
- No `.usages/` directory exists — skipped (the driver consumes `configuration` from config; the TLS practice
  lives in the project-level playwright cook, already updated).

---

## Test Stack Trace

### General Setup

- venv at `/opt/project` (outside the repo); `pytest tests/ -x`, `ruff check prettyplay/`.
- Cache tests use `tmp_path` exclusively for the store root (`PrettyConfig(cache_root=str(tmp_path / "cache"))`).
- Facade ring-1 tests construct `PrettyPlay` with `config=PrettyConfig(strict=True, ...)` where a constructed
  object is needed and assert the raised `PrettyplayError` **before** any browser involvement (no Playwright
  required); driver context tests mock the worker/browser boundary as the existing `test_session.py` does.
- The full `PrettyPlay` integration paths (scoped step through executor/store) reuse the existing
  `tests/conftest.py` harness patterns (`test_scenario.py`, `test_groups_integration.py`).

### Source File Registry

- `prettyplay/config/models.py` — `SiteConfig`, `BrowserConfig`, `PrettyConfig`
- `prettyplay/config/loader.py` — `_ENV_NAMES`, `_BOOL_ENV_SETTINGS`, the group env merge, `_apply_overrides`
- `prettyplay/cache/models.py` — `validate_step_scope`, `StepIdentity`
- `prettyplay/cache/store.py` — `StepCache.load/save/sweep_untouched`, `_serialize`
- `prettyplay/driver/session.py` — `DriverSession.open_context`
- `prettyplay/engine/groups/outcome.py`, `prettyplay/engine/groups/recovery.py`
- `prettyplay/scenario.py`, `prettyplay/groups.py`, `prettyplay/executor.py`
- `prettyplay/config/__init__.py`, `prettyplay/cache/__init__.py`, `prettyplay/__init__.py`

---

### Positive Tests

#### `test_site_config_accepts_http_url` (tests/config/test_models.py)

**Setup**: none (pure model construction).

**Input**: `SiteConfig(base_url="https://staging.example.com")`

**Trace**:
```
SiteConfig(base_url=...)
  → pydantic kw_only construction
  → _validate_base_url("https://staging.example.com")
    → urlparse: scheme "https", netloc "staging.example.com"
    returns: value verbatim
  → model instance
```

**Assertions**:
```
config.site.base_url == "https://staging.example.com"   # via PrettyConfig default group
SiteConfig().base_url == ""                             # the empty default
```

**Sufficiency**: pins the group's existence, the empty default and verbatim keeping — the base of the D2
surface.

#### `test_browser_config_has_ignore_https_errors_default` (tests/config/test_models.py)

**Setup**: none.

**Input**: `BrowserConfig()`

**Trace**:
```
BrowserConfig()
  → pydantic construction with the new field
  → default False
```

**Assertions**:
```
BrowserConfig().ignore_https_errors is False
BrowserConfig(ignore_https_errors=True).ignore_https_errors is True
```

**Sufficiency**: the D1 default must keep Playwright's certificate checking untouched.

#### `test_load_config_reads_site_group_and_tls_switch` (tests/config/test_loader.py)

**Setup**: `tmp_path` pyproject.toml:
```toml
[tool.prettyplay]
model = "gpt-5"
[tool.prettyplay.browser]
ignore_https_errors = true
[tool.prettyplay.site]
base_url = "https://staging.example.com"
```
monkeypatched env without PRETTYPLAY_* variables; `load_config(pyproject_path=...)`.

**Input**: the file above.

**Trace**:
```
load_config(pyproject_path=...)
  → tomllib load; no legacy names
  → _collect_env_overrides() → {} (no PRETTYPLAY_* set)
  → merged = section (site nested dict preserved)
  → PrettyConfig(**merged)
    → BrowserConfig(ignore_https_errors=True) ✓
    → SiteConfig(base_url="https://staging.example.com") ✓ (urlparse passes)
  returns: PrettyConfig
```

**Assertions**:
```
config.site.base_url == "https://staging.example.com"
config.browser.ignore_https_errors is True
```

**Sufficiency**: the file layer of both new settings through the real loader.

#### `test_load_config_env_overrides_site_and_tls` (tests/config/test_loader.py)

**Setup**: a pyproject with `base_url = "https://file.example.com"` in the site group and
`ignore_https_errors = false`; monkeypatch env `PRETTYPLAY_SITE_BASE_URL=https://env.example.com`,
`PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS=1`.

**Input**: `load_config(pyproject_path=...)`.

**Trace**:
```
load_config(...)
  → _collect_env_overrides()
    → "site.base_url": "https://env.example.com" (verbatim string)
    → "browser.ignore_https_errors": _parse_env_scalar bool "1" → True
  → group merge: merged["site"]["base_url"] = "https://env.example.com";
    merged["browser"]["ignore_https_errors"] = True
  → PrettyConfig(**merged) validates
```

**Assertions**:
```
config.site.base_url == "https://env.example.com"
config.browser.ignore_https_errors is True
```

**Sufficiency**: both new env names, the boolean parse rule and the generalized per-group env merge.

#### `test_load_config_env_empty_site_base_url_clears_file_value` (tests/config/test_loader.py)

**Setup**: a pyproject with `base_url = "https://file.example.com"` in the site group; monkeypatch env
`PRETTYPLAY_SITE_BASE_URL=""` (set to the empty string).

**Input**: `load_config(pyproject_path=...)`.

**Trace**:
```
load_config(...)
  → _collect_env_overrides()
    → "site.base_url": "" (a set variable — collected; the string parses verbatim)
  → group merge: merged["site"]["base_url"] = ""   # replaces the file value
  → PrettyConfig(**merged) → SiteConfig(base_url="") — valid (empty = unset)
```

**Assertions**:
```
config.site.base_url == ""      # the set-but-empty env override clears the file layer
```

**Sufficiency**: pins the semantics "a set-but-empty env variable clears the file layer" — symmetric with
`PRETTYPLAY_MODEL=""`; guards the generalized per-group env merge against a defensive refactor that would
drop empty env values.

#### `test_apply_overrides_site_group_merge` (tests/config/test_loader.py)

**Setup**: file layer site `base_url = "https://staging.example.com"`.

**Input**: `load_config(pyproject_path=..., overrides=PrettyConfig(site=SiteConfig(base_url="https://prod.example.com")))`
and separately `overrides=PrettyConfig(site=SiteConfig())` (nothing explicitly set).

**Trace**:
```
_apply_overrides(file_config, overrides)
  → "site" in overrides.model_fields_set; value is a group model
  → group_update = {"base_url": ...} when explicitly set, else {}
  → update["site"] = file_config.site.model_copy(update=group_update)
```

**Assertions**:
```
explicit: config.site.base_url == "https://prod.example.com"
untouched group: config.site.base_url == "https://staging.example.com"
```

**Sufficiency**: the symmetric layered merge — untouched group defaults never overwrite the file layer.

#### `test_validate_step_scope_accepts_valid_scopes` (tests/cache/test_models.py)

**Setup**: none.

**Input**: `["pages/login_page", "a", "v1.2.config-x", "pages/nested/deep"]` — parametrized.

**Trace**:
```
validate_step_scope(scope)
  → split("/") → segments all match [A-Za-z0-9._-]+, no ".."
  returns: None
```

**Assertions**:
```
validate_step_scope(value) is None   # each value, no exception
```

**Sufficiency**: the accepted form — 1..N segments joined by exactly one `/`.

#### `test_step_identity_scoped_address_key_and_filename` (tests/cache/test_models.py)

**Setup**: none.

**Input**: `StepIdentity(cache_key="login-flow", step_type="action",
normalized_text="open the dashboard", scope="pages/dashboard")`.

**Trace**:
```
identity.address_key
  → scope non-empty → "pages/dashboard"
identity.filename
  → "\x1f".join(("pages/dashboard", "action", "open the dashboard")) → sha256 → hex + ".py"
```

**Assertions**:
```
identity.address_key == "pages/dashboard"
identity.filename == f"{hashlib.sha256('\x1f'.join(('pages/dashboard', 'action', 'open the dashboard')).encode()).hexdigest()}.py"
identity.scope == "pages/dashboard"
```

**Sufficiency**: the address key and the digest rule for scoped identities.

#### `test_step_identity_unscoped_digest_unchanged` (tests/cache/test_models.py)

**Setup**: none.

**Input**: `StepIdentity(cache_key="login-flow", step_type="action", normalized_text="open the dashboard")`
(no scope) and the same with `scope=""`.

**Trace**:
```
identity.address_key → cache_key ("login-flow")
identity.filename → digest of ("login-flow", "action", "open the dashboard")
```

**Assertions**:
```
identity.address_key == "login-flow"
identity.filename == <the pre-change digest>  # sha256 of the same triple — computed inline in the test
StepIdentity(..., scope="").filename == StepIdentity(...).filename
```

**Sufficiency**: the hard compatibility guarantee — no unscoped address changes (existing repositories stay
valid).

#### `test_store_save_and_load_scoped_step_roundtrip` (tests/cache/test_store.py)

**Setup**: `cache = StepCache(config=PrettyConfig(cache_root=str(tmp_path / "cache")), reporter=StepReporter(hooks=[]))`;
`identity = StepIdentity(cache_key="login-flow", step_type="action",
normalized_text=normalize_step_text("open the dashboard"), scope="pages/dashboard")`;
`step = CachedStep(identity=identity, addressing_text="open the dashboard", code="def step(page):\n    ...",
created_at="2026-11-19")`.

**Input**: `cache.save(step)` then `cache.load(identity)`.

**Trace**:
```
cache.save(step)
  → ring 2: validate_step_scope("pages/dashboard") ✓
  → _serialize: CACHE_KEY = "pages/dashboard" (address_key), STEP_TEXT, STEP_TYPE, CREATED_AT, sentinel, code
  → target dir root/pages/dashboard — mkdir(parents=True)
  → mkstemp in that dir → os.replace → on_cache_saved; touched += filename
cache.load(identity)
  → ring 2 ✓ → dir root/pages/dashboard → file <digest>.py found
  → header parse: CACHE_KEY == address_key ✓, STEP_TYPE ✓, STEP_TEXT normalizes ✓
  → touched already holds the name
  returns: CachedStep
```

**Assertions**:
```
stored is True
loaded is not None
loaded.code == step.code
loaded.addressing_text == "open the dashboard"
(tmp_path / "cache" / "pages" / "dashboard").is_dir()
list((tmp_path / "cache" / "pages" / "dashboard").glob("*.py")) != []   # the routed file
text of the file contains 'CACHE_KEY = 'pages/dashboard''                 # the metadata key is the scope
cache.load(StepIdentity(cache_key="login-flow", step_type="action",
                        normalized_text=..., scope="")) is None          # the unscoped address is a miss
```

**Sufficiency**: the whole D3 storage contract — routing, metadata key, roundtrip, and the separation of the
scoped and unscoped address spaces.

#### `test_store_sweep_never_deletes_scoped_files` (tests/cache/test_store.py)

**Setup**: shared root store (`path=None`); save a scoped step (scope="pages/dashboard", its own test budget)
and an untouched unscoped step of cache_key "login-flow".

**Input**: `cache.sweep_untouched("login-flow")`.

**Trace**:
```
sweep_untouched("login-flow")
  → enumerate root (files only) → the untouched unscoped file of this key
  → the scoped file lives in root/pages/dashboard/ — never enumerated; its CACHE_KEY is the scope anyway
  → delete the unscoped untouched file
```

**Assertions**:
```
removed == [<unscoped digest>.py]            # exactly the unscoped untouched file
the scoped file still exists
```

**Sufficiency**: the sweep immunity of shared scope entries — the property the page-object sharing model
stands on.

#### `test_open_context_passes_ignore_https_errors` (tests/driver/test_session.py)

**Setup**: the existing session test double pattern — a fake browser object recording `new_context` kwargs;
`config = PrettyConfig(browser=BrowserConfig(ignore_https_errors=True))` (screen empty).

**Input**: `session.open_context()`.

**Trace**:
```
open_context()
  → _launch() (local, headless) → fake browser
  → open_isolated in the worker thread:
      params = {**_screen_context_params(), "ignore_https_errors": True}
      browser.new_context(**params)          # recorded by the fake
  → dialog router, new_page, set_default_timeout
```

**Assertions**:
```
recorded_kwargs.get("ignore_https_errors") is True
```
and with `ignore_https_errors=False` (default): `recorded_kwargs.get("ignore_https_errors") is False`.

**Sufficiency**: D1 — the switch rides the context creation as a parameter, in the default start mode.

#### `test_scenario_site_base_url_property` (tests/test_scenario.py)

**Setup**: `t = PrettyPlay("k", config=PrettyConfig(site=SiteConfig(base_url="https://staging.example.com")))`.

**Input**: `t.site_base_url`.

**Trace**:
```
PrettyPlay.__init__ → adopt_config(PrettyConfig(...)) verbatim → runtime.config
t.site_base_url → runtime.config.site.base_url
```

**Assertions**:
```
t.site_base_url == "https://staging.example.com"
PrettyPlay("k2", config=PrettyConfig()).site_base_url == ""   # unset → empty string
```

**Sufficiency**: the D2 read surface — verbatim, empty when unset.

#### `test_scenario_step_scope_ring1_validates_before_execution` (tests/test_scenario.py)

**Setup**: `t = PrettyPlay("k", config=PrettyConfig(strict=True))` — no page opened, no browser started
(construction is lazy and requires no credentials).

**Input**: `t.step("open the dashboard", _scope="pages/../escape")`.

**Trace**:
```
t.step(text, _scope=...)
  → _validate_tries/delay/vars (None defaults pass)
  → ring 1: validate_step_scope("pages/../escape")
    → segments ["pages", "..", "escape"] contain ".." → raise PrettyplayError
  → _raise_folded → the traceback folded to the library boundary
```

**Assertions**:
```
pytest.raises(PrettyplayError) — message names "_scope", the received value "pages/../escape" and the allowed form
t._page is None          # no page was opened — the validation preceded everything
```

**Sufficiency**: ring 1 fires before any render or execution — the earliest, cheapest rejection.

#### `test_scenario_group_scope_threads_to_executor` (tests/test_groups_integration.py)

**Setup**: the existing integration harness (fake or real page per the file's established pattern); a group
block is opened with `_scope="pages/login_page"`.

**Input**: `with t.group("the user signs in", _scope="pages/login_page") as g: g.step("fill the login field")`
with the executor's identity build observed (spy on `StepCache.save`/`load` identity or the executor call).

**Trace**:
```
t.group(prompt, _scope="pages/login_page")
  → ring 1 ✓ → StepGroup(..., scope="pages/login_page")
g.step("fill the login field")
  → _scope None → no rejection
  → _delegate(..., scope="pages/login_page") → executor.execute(..., scope="pages/login_page")
  → StepIdentity(cache_key="k", "action", normalized, scope="pages/login_page")
  → store: root/pages/login_page/<digest>.py, CACHE_KEY = "pages/login_page"
```

**Assertions**:
```
g.scope == "pages/login_page"
the saved/loaded identity.scope == "pages/login_page"
the file landed under <cache root>/pages/login_page/
```

**Sufficiency**: the page-object layer's core scenario — the scope set once per block addresses every step of
the block.

#### `test_recovery_row_readdresses_under_group_scope` (tests/engine/groups/test_recovery.py)

**Setup**: the existing recovery test harness — a scoped trace identity
(`StepIdentity(cache_key="k", step_type="action", normalized_text="fill the login field", scope="pages/login")`),
a diagnosis verdict naming the earliest row step, a generator double recording the `identity` of
`regenerate`.

**Input**: `recovery.recover(...)` reaching the row loop.

**Trace**:
```
recover(...)
  → row match → row step re-render → fresh.addressing_text
  → fresh_identity = StepIdentity(cache_key="k", scope="pages/login", step_type=...,
                                   normalized_text=normalize_step_text(fresh.addressing_text))
  → budgets.refresh_healing(fresh_identity)
  → generator.regenerate(identity=fresh_identity, ...)
```

**Assertions**:
```
recorded_identity.scope == "pages/login"          # the fresh identity carries the group's scope
recorded_identity.cache_key == "k"                # and the execution-fact cache key
recorded_identity.normalized_text == normalize_step_text(fresh.addressing_text)
```

**Sufficiency**: the recovery never writes a row step under a stale or scope-less address — regeneration,
budget and write-back stay coherent for scoped groups.

---

### Negative Tests

#### `test_site_config_rejects_non_http_url` (tests/config/test_models.py)

**Setup**: none.

**Input**: parametrized `["example.com", "ftp://example.com", "https://", "http:///path"]`.

**Trace**:
```
SiteConfig(base_url=value)
  → urlparse: scheme missing / not http(s) / netloc empty → ValueError
```

**Assertions**:
```
pytest.raises(ValidationError)   # the programmatic layer; through load_config it renders ConfigurationError
```

**Sufficiency**: a non-empty base_url must be an http/https URL with a host — never a silent pass-through.

#### `test_load_config_env_invalid_tls_boolean_fails_loudly` (tests/config/test_loader.py)

**Setup**: pyproject (any valid); monkeypatch `PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS=maybe`.

**Input**: `load_config(pyproject_path=...)`.

**Trace**:
```
_parse_env_scalar("browser.ignore_https_errors", "maybe")
  → boolean settings rule: true/false/1/0 case-insensitive → failure
  → raise ConfigurationError naming the setting, the received value and the accepted form
```

**Assertions**:
```
pytest.raises(ConfigurationError); "browser.ignore_https_errors" in str(excinfo.value); "maybe" in str(...)
```

**Sufficiency**: the boolean env rule — never a silent ignore.

#### `test_validate_step_scope_rejects_invalid_scopes` (tests/cache/test_models.py)

**Setup**: none.

**Input**: parametrized
`["", "/pages", "pages/", "pages//login", "..", "a/../b", "pages\\login", "C:/pages", "pages login", "страница", "pages:login"]`.

**Trace**:
```
validate_step_scope(scope)
  → split → an empty segment / a forbidden character / ".." → raise PrettyplayError
```

**Assertions**:
```
pytest.raises(PrettyplayError) — the message names _scope, the received value and the allowed form
```

**Sufficiency**: the one rule of both rings — absolute forms, traversal, empty segments, charset.

#### `test_store_ring2_rejects_invalid_scope_on_load_and_save` (tests/cache/test_store.py)

**Setup**: a store over `tmp_path`; `bad = StepIdentity(cache_key="k", step_type="action",
normalized_text="x", scope="../escape")` — constructed directly, bypassing the facade (the ring-2 threat
model).

**Input**: `cache.load(bad)` and `cache.save(CachedStep(identity=bad, addressing_text="x", code="def step(page):\n    ...", created_at="2026-11-19"))`.

**Trace**:
```
load/save
  → _step_dir: identity.scope non-empty → validate_step_scope("../escape") → PrettyplayError
  → raised before any path is composed — nothing is read or written under tmp_path's parent
```

**Assertions**:
```
pytest.raises(PrettyplayError) on load; pytest.raises(PrettyplayError) on save
(tmp_path / "cache").exists() is False or contains nothing outside the root   # no escape
```

**Sufficiency**: the address never escapes the cache root even when the facade is bypassed — the defense the
second ring exists for.

#### `test_group_step_rejects_per_step_scope` (tests/test_groups_integration.py)

**Setup**: an opened group block `g = t.group("the user signs in", _scope="pages/login_page")`.

**Input**: `g.step("fill the login field", _scope="pages/other")`.

**Trace**:
```
StepGroup.step(text, _scope="pages/other")
  → _scope is not None → raise PrettyplayError naming the parameter and the remedy
  → no pause, no page open, no delegation
```

**Assertions**:
```
pytest.raises(PrettyplayError); "group(" in str(excinfo.value) or the remedy names group(..., _scope=...)
```

**Sufficiency**: the scope is set once per block — a per-step scope inside a group is an authoring error, not
an override.

#### `test_scenario_group_invalid_scope_rejected_at_entry` (tests/test_scenario.py)

**Setup**: `t = PrettyPlay("k", config=PrettyConfig(strict=True))`.

**Input**: `t.group("the user signs in", _scope="bad scope")`.

**Trace**:
```
t.group(prompt, _scope="bad scope")
  → ring 1: the segment "bad scope" contains a space → PrettyplayError
  → raised before StepGroup construction — on_group_started can never fire for an invalid scope
```

**Assertions**:
```
pytest.raises(PrettyplayError)
```

**Sufficiency**: ring 1 at group entry — before the block opens.

---

### Edge Case Tests

#### `test_store_scoped_step_with_store_subdirectory_ignores_it` (tests/cache/test_store.py)

**Setup**: `cache = StepCache(config=..., path="checkout", ...)`; a scoped step saved.

**Input**: `cache.save(scoped_step)` with `identity.scope = "pages/dashboard"`.

**Trace**:
```
save → _step_dir: scoped → root/pages/dashboard/   (path="checkout" never applied)
```

**Assertions**:
```
the file exists at <root>/pages/dashboard/<digest>.py
not (<root>/checkout/pages/dashboard).exists()
not (<root>/checkout/<digest>.py).exists()
```

**Sufficiency**: the store subdirectory never applies to scoped steps — two independent routing dimensions.

#### `test_store_scoped_dir_matching_digest_name_not_swept` (tests/cache/test_store.py)

**Setup**: a scope of exactly `<64 hex>.py` (charset-legal) creates a directory matching the step-file name
pattern; an untouched unscoped file of the key exists too.

**Input**: `cache.sweep_untouched("k")`.

**Trace**:
```
sweep → iterdir → the digest-named entry fails entry.is_file() → not a candidate
```

**Assertions**:
```
the digest-named directory still exists
no WARNING-recorded failure for it (removed list contains only the unscoped file)
```

**Sufficiency**: the enumeration guards itself against scope directories named like digests.

#### `test_store_two_writers_same_scoped_step_reader_accepts_either` (tests/cache/test_store.py)

**Setup**: one shared root (`tmp_path / "cache"`); `store_a = StepCache(config=..., reporter=...)` and
`store_b = StepCache(config=..., reporter=...)` — two independent instances (two "tests"); the same
scoped address: `identity_a = StepIdentity(cache_key="a", ...)` and `identity_b =
StepIdentity(cache_key="b", ...)` with identical `step_type`, `normalized_text` and `scope="pages/login"`
— identical `address_key`, hence identical digest; two `CachedStep`s with identical code and different
`created_at` (the writer order stays distinguishable).

**Input**: `store_a.save(step_a)` then `store_b.save(step_b)` (a sequential emulation of the race; last
writer — b); then `store_a.load(identity_a)` and `store_b.load(identity_b)`.

**Trace**:
```
both saves → ring 2 ✓ → the same scoped dir (mkdir exist_ok) → two mkstemp + os.replace onto the
same target name → one file, content of writer b; both loads → header parse: CACHE_KEY == address_key
(equal), STEP_TYPE ✓, STEP_TEXT normalizes equal → both readers get a valid CachedStep with writer b's code
```

**Assertions**:
```
stored_a is True and stored_b is True
loaded_by_a is not None and loaded_by_b is not None
loaded_by_a.code == loaded_by_b.code == step_b.code       # last writer wins, identical for every reader
len(list((tmp_path / "cache" / "pages" / "login").glob("*.py"))) == 1   # exactly one file
```

**Sufficiency**: pins the concurrent-writers contract property of the scoped address deterministically:
one address ⇒ one file ⇒ every reader valid; catches a load/save routing desynchronization and any
nondeterministic component sneaking into the serialization.

#### `test_scoped_identity_and_equal_cache_key_share_one_address` (tests/cache/test_models.py)

**Setup**: none.

**Input**: `a = StepIdentity(cache_key="pages/login", step_type="action", normalized_text="x", scope="")`
and `b = StepIdentity(cache_key="k", step_type="action", normalized_text="x", scope="pages/login")`.

**Trace**:
```
a.address_key == "pages/login"; b.address_key == "pages/login" → identical digests
```

**Assertions**:
```
a.filename == b.filename     # one address space: the scope replaces the key part
```

**Sufficiency**: documents the coherence of the address space — when the key part equals the scope the
addresses are the same by construction, never a collision bug.

#### `test_executor_none_scope_becomes_empty_scope` (tests/test_executor.py)

**Setup**: the existing executor harness (cache double recording the loaded identity).

**Input**: `executor.execute("plain sentence", "action", page, scope=None)`.

**Trace**:
```
execute → StepIdentity(..., scope=None or "") → scope == ""
```

**Assertions**:
```
recorded_identity.scope == ""
recorded_identity.address_key == executor.cache_key
```

**Sufficiency**: `None` and empty are equivalent unscoped — the executor's normalization contract.

#### `test_scenario_scope_never_enters_sentence_or_request` (tests/test_groups_integration.py)

**Setup**: an integration run with `_scope` set; the generator/LLM boundary doubled, capturing the rendered
instruction.

**Input**: `t.step("open the dashboard", _scope="pages/dashboard")` (a cache miss — generation runs).

**Trace**:
```
render → PreparedStep (sentence + instruction) — the scope is not a render input
generate(request) — the request carries the prepared instruction only
```

**Assertions**:
```
"pages/dashboard" not in captured_instruction
"pages/dashboard" not in prepared.addressing_text
```

**Sufficiency**: the scope addresses and routes only — it never leaks into the sentence or any LLM request.

#### `test_budgets_scoped_step_pays_per_test` (tests/cache/test_budgets.py)

**Setup**: `budgets = RunBudgets(generation_limit=1, healing_limit=1)`; a scoped identity.

**Input**: `budgets.try_generation(scoped_identity)` from "test A"; then the same identity through a second
registry instance ("test B").

**Trace**:
```
registry A: the scoped identity consumes its generation pool → False on the second call
registry B (a fresh per-test registry): the same identity draws a fresh pool → True
```

**Assertions**:
```
a.try_generation(identity) is True; a.try_generation(identity) is False
b.try_generation(identity) is True          # per-test budgets — no shared scope budget
```

**Sufficiency**: budgets follow the runtime, addressing follows the scope — the sharing economics of D3.

---

## Additional Instructions for the Implementation Agent

- Implement in the plan's leaf→root order: config → cache → driver → engine/groups → facade; update the three
  package `__init__.py` exports (`SiteConfig`, `validate_step_scope`, the facade re-export) together with
  their cells.
- `StepIdentity.scope` gets the default `""` — every existing construction site (tests, the recovery record-0
  load, usage examples) stays valid and unscoped; do not make it required.
- The digest separator and hashing stay exactly as today — only the first join member changes to
  `address_key`; verify unscoped digests against pre-change values in the compatibility test.
- Ring 2 lives in the store's directory resolution (once, shared by `load` and `save`) — before any path is
  composed; ring 1 lives in the facade methods beside the existing parameter validations, before
  `_ensure_page()`. The executor adds no validation.
- The scoped temp file for `save` is created in the resolved scoped directory (same filesystem as the
  replace); the scoped directory is created with `mkdir(parents=True, exist_ok=True)` at save time only,
  inside the OSError-guarded skip path — an OSError on it skips the write like any other I/O failure,
  never raising.
- Add the `entry.is_file()` guard to the sweep candidate filter — a charset-legal scope can be named like a
  digest file.
- Keep `validate_step_scope` in `prettyplay/cache/models.py` a pure function (no I/O, no state); the error
  message names `_scope`, the received value and the allowed form — one render, matching the existing loud
  actionable style of `_validate_tries`/`_validate_delay`.
- The site group env merge generalizes the dotted-setting grouping per group prefix — do not special-case
  `site` in a second code path; `_apply_overrides` handles both group models through one isinstance branch.
- No new log records anywhere: enabling the TLS switch is silent; scoped saves/skips ride the existing cache
  events.
- Follow `conventions` throughout (kw_only pydantic groups with neutral defaults, relative intra-package
  imports, Google docstrings, the blank-line block separation); run `pytest tests/ -x` and
  `ruff check prettyplay/ tests/` in the `/opt/project` venv before finishing.
