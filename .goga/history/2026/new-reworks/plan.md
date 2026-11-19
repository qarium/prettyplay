# Plan: `new-reworks-tls-site-scope`

Compiled from `.goga/history/2026/new-reworks/design.md` (verified by the design-review stage) and the five
affected `CODEMANIFEST` contracts into a ralphex-executable task sequence.

## Purpose

Materialize three contract amendments across five existing cells — no new cells, no cell boundary changes:

- **D1 — insecure TLS**: `BrowserConfig.ignore_https_errors` applied by `DriverSession.open_context` as a
  Playwright context parameter (one `new_context` surface, every start mode, silent).
- **D2 — site base URL**: the nested `site` group (`SiteConfig.base_url`) through the layered merge of
  `load_config` and the facade property `PrettyPlay.site_base_url` — verbatim, `""` when unset.
- **D3 — the step scope**: `_scope` on `step`/`expect`/`group`; two validation rings (`validate_step_scope`);
  scoped addressing (`StepIdentity.scope`/`address_key`); scoped file routing (`root/<scope>/`); sweep immunity;
  per-test budgets; scope preservation through the group recovery row re-addressing.

Strategy: implement leaf → root (`prettyplay/config` → `prettyplay/cache` → `prettyplay/driver` →
`prettyplay/engine/groups` → `prettyplay`), each cell complete before the next, every coding task following the
TDD workflow (contract tests → implementation → interface verification → logic tests → debugging →
contract re-verification → lint). Unscoped cache addresses must not change — digest byte-stability is a hard
compatibility guarantee.

## Context

### Contract Surface

#### Cell: `prettyplay/config`

**Entity: `SiteConfig(base_url: str)`** — NEW
- Type: class (Entity — properties, no methods)
- Declared `location`: `models.py`
- Facade obligation: importable from `prettyplay.config`; re-exported by `prettyplay` (see Re-exports)
- Properties: `base_url -> str` — the root URL of the environment under test; empty means unset; verbatim,
  no trailing-slash normalization
- Semantic requirements: the nested site group of `PrettyConfig`, symmetric to `BrowserConfig`; kw_only
  construction, empty default; a non-empty `base_url` must carry an http/https scheme and a non-empty netloc
  (`urlparse`) — anything else fails loudly naming the setting, the received value and the allowed form; no
  collision with the top-level `base_url` (the LLM endpoint) — the group scopes the field
- Imported dependencies: `PrettyplayError` (via `ConfigurationError` mutation), `taxonomy` usage
- Annotation context: global annotations — pydantic v2, kw_only=True, empty defaults; one place of validation

**Entity: `BrowserConfig` (+`ignore_https_errors: bool`)** — CHANGED
- Type: class; `location`: `models.py`
- New field `ignore_https_errors: bool = False` (kw_only, no dedicated validator — pydantic rejects
  non-booleans through the existing validation wrap); property `ignore_https_errors -> bool`
- Semantics: open pages behind self-signed or otherwise invalid certificates; the driver cell applies it as a
  context parameter at context creation — never a launch argument; default False keeps Playwright's certificate
  checking untouched; enabling is silent

**Entity: `PrettyConfig` (+`site: SiteConfig`)** — CHANGED
- Type: class; `location`: `models.py`
- New field `site: SiteConfig` (default `SiteConfig()`); property `site -> SiteConfig`
- Semantics: participates in the layered merge of `load_config` symmetrically to `browser` — explicitly set
  fields of a passed `SiteConfig` win over the file layer, untouched group defaults never overwrite file values

**Routine: `load_config`** — CHANGED
- `location`: `loader.py`
- Changes: `_ENV_NAMES` gains `browser.ignore_https_errors` (boolean parse: true/false/1/0
  case-insensitively; unparseable raises `ConfigurationError` naming the setting, the received value and the
  accepted form) and `site.base_url` (a string, taken verbatim); the dotted env merge generalizes from
  browser-only to per-group (`browser.*` → browser section, `site.*` → site section); `_apply_overrides`
  handles both group models through one isinstance branch
- Env semantics: `PRETTYPLAY_SITE_BASE_URL=""` (set but empty) clears the file value — symmetric to
  `PRETTYPLAY_MODEL=""`; the string-empty guard applies to the programmatic layer only

#### Cell: `prettyplay/cache`

**Routine: `validate_step_scope(scope: str)`** — NEW
- Declared `location`: `models.py`
- Facade obligation: importable from `prettyplay.cache`
- Semantics: the one scope charset rule serving both validation rings; pure function (no I/O, no state, no
  normalization); a violation raises the loud actionable `PrettyplayError` naming the parameter `_scope`, the
  received value and the allowed form (one render); accepted values pass verbatim

**Entity: `StepIdentity` (+`scope`, +`address_key`)** — CHANGED
- `location`: `models.py`
- New field `scope: str = ""` (kw_only; the default keeps every existing construction unscoped — do NOT make
  it required); new property `address_key -> str` (`scope` when non-empty, otherwise `cache_key`); `filename`
  digest built from `address_key` — unscoped digests byte-identical to before
- The record holds no validation — the rings own the rule

**Entity: `CachedStep`** — CHANGED (metadata contract only, no signature change)
- The file metadata contract now keys `CACHE_KEY` on `identity.address_key`: the writer (`save`) and the
  reader (`load`) agree on `identity.address_key` as the CACHE_KEY value

**Entity: `StepCache`** — CHANGED
- `location`: `store.py`
- `load`/`save` gain ring-2 scope validation (a non-empty identity scope validates through
  `validate_step_scope` before any path is composed) and scoped routing (`root/<scope>/`; the store
  subdirectory never applies to scoped steps; `mkdir(parents=True, exist_ok=True)` on save inside the
  OSError-guarded skip path)
- `sweep_untouched` gains scoped immunity (existing key filter plus the `entry.is_file()` guard in the
  candidate enumeration)

**Entity: `RunBudgets`** — unchanged in code; the scoped-identity economics are pinned by a new test (budgets
key by `identity.filename` → scoped identities draw their own pools automatically)

#### Cell: `prettyplay/driver`

**Entity: `DriverSession.open_context`** — CHANGED
- `location`: `session.py`
- The resolved context parameters now include `ignore_https_errors` from the browser group:
  `params = {**self._screen_context_params(), "ignore_https_errors": self._config.browser.ignore_https_errors}`
  — one surface at `browser.new_context(**params)` (session.py:181–182 today); never a launch argument, so
  local launch, ws/wss connect and http/https CDP connect are identical; enabling is silent — no log record

#### Cell: `prettyplay/engine/groups`

**Entity: `GroupStepOutcome`** — CHANGED (documentation; no signature change)
- `location`: `outcome.py`
- `identity` documented as carrying both address parts (cache_key AND scope) — the row mechanics take both

**Entity: `GroupRecovery.recover`** — CHANGED
- `location`: `recovery.py`
- Row step 5 builds every fresh row identity with the trace identity's `cache_key` AND `scope`
  (recovery.py:344 today omits `scope`); a scoped group's rows re-address under the group's scope; record 0
  (`self._cache.load(trace.identity)`) already uses the scoped trace identity — no change needed there

#### Cell: `prettyplay` (facade)

**Entity: `PrettyPlay`** — CHANGED
- `location`: `scenario.py`
- `step`/`expect` gain the keyword-only `_scope: str | None` (ring-1 validation before `_ensure_page()`, before
  any render or execution; the delegation carries `scope=_scope`); `group` gains `_scope` validated at entry
  (before `StepGroup` construction — `on_group_started` can never fire for an invalid scope); new property
  `site_base_url -> str` (`self._runtime.config.site.base_url` — verbatim, `""` when unset); `cache_path`
  documented as never applying to scoped steps

**Entity: `StepGroup`** — CHANGED
- `location`: `groups.py`
- Constructor +`scope: str | None` (carried from the facade after ring-1 validation; update the
  "five-parameter" comment at scenario.py:367); +property `scope -> str | None`; `step`/`expect` +`_scope`
  parameter **rejected** when non-None (the scope is set once per block — `group(..., _scope=...)`); the
  delegation carries the group's scope (`scope=self._scope`); the rejection fires before the pause and the
  page opener

**Entity: `StepExecutor.execute`** — CHANGED
- `location`: `executor.py`
- +`scope: str | None`; the step identity is built with the scope (`None` becomes the empty scope of the
  record: `scope=scope or ""`); no validation of its own — the rings own the rule

### Re-exports

- `->SiteConfig: {}` in `prettyplay/CODEMANIFEST` — source: `Imports` from `prettyplay/config`; facade
  obligation: `from prettyplay import SiteConfig` must work; uniform with `PrettyConfig`/`BrowserConfig`
- Cell facades updated alongside their entities: `prettyplay/config/__init__.py` (+`SiteConfig` in `__all__`),
  `prettyplay/cache/__init__.py` (+`validate_step_scope` in `__all__`)

### Usages Context

- `conventions` (`.goga/usages/conventions.md`) — the mandatory project practice: Python rules, test rules,
  validation commands. Bound in all five cells ("Use `conventions` for code writing rules and testing"). Its
  rules are extracted into **Mandatory Rules** below — the plan's single normative style reference.
- `pydantic` (`.goga/usages/cooks/pydantic.md`) — data models and TOML loading practice for the config cell.
- `playwright` (`.goga/usages/cooks/playwright.md`) — the sync-API practice; the new "Insecure TLS" section
  documents `browser.new_context(ignore_https_errors=True)` — a context parameter, never a launch argument.

### Imported Usages

- `addressing` from `prettyplay/cache` (`prettyplay/cache/.usages/addressing.md`, exists, current) — imported
  by `prettyplay` (facade) and `prettyplay/engine/groups`; documents `StepIdentity(..., scope=...)`,
  `identity.address_key`, `root/<scope>/` routing
- `taxonomy` from `prettyplay/failures` (`prettyplay/failures/.usages/taxonomy.md`, exists) — imported by
  `prettyplay/cache`; the failure kinds and the loud actionable message style of `validate_step_scope`
- `configuration` from `prettyplay/config` (`prettyplay/config/.usages/configuration.md`, exists, current) —
  imported by `prettyplay/driver`; the "Insecure TLS" section documents `config.browser.ignore_https_errors`
- `hooks` from `prettyplay/reporting` — unchanged cache events (`on_cache_saved`/`on_cache_skipped`); no new
  events
- `recovery` from `prettyplay/engine/groups` (exists, current) — the re-address bullet carries the cache key
  AND the scope

### Local Usages

All cell-level `.usages/` files covered by this design are already current (updated by the apply stage):
`prettyplay/cache/.usages/{addressing,storage,budgets}.md`, `prettyplay/config/.usages/configuration.md`,
`prettyplay/.usages/{steps,lifecycle}.md`, `prettyplay/engine/groups/.usages/recovery.md`, and the
project-level `.goga/usages/cooks/playwright.md`. **No `.usages/` creation or update tasks are planned.**

### External Dependencies

- pydantic v2 (`kw_only`, `model_fields_set`, `model_copy`), Playwright sync API (`new_context` kwargs),
  pytest / pytest-cov / pytest-mock / ruff (test toolchain, `[project.optional-dependencies] test`)
- venv at `/opt/project` (outside the repo) — the conventions require all code to execute in a virtualenv,
  created if missing

### Entity Interactions (verbatim from the design)

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

**Data flows (verbatim from the design)**:

- **Flow 1 — a scoped facade step (cache miss, first test)**:
  `PrettyPlay.step(text, _scope="pages/login")` → ring 1 `validate_step_scope("pages/login")` passes →
  `_ensure_page()` (browser lazily started; context opened with `ignore_https_errors` from the browser group) →
  `StepExecutor.execute(..., scope="pages/login")` → `render_step` produces `PreparedStep` →
  `StepIdentity(cache_key, "action", normalized, "pages/login")` → `StepCache.load` (ring 2 passes; looks in
  `root/pages/login/<digest>.py`; miss → None) → generator `generate` (budget keyed by the scoped identity) →
  `StepCache.save` (ring 2; `mkdir root/pages/login`; `CACHE_KEY = "pages/login"`; atomic replace) →
  captures publish; trace/scenario records appended. A second test with the same phrase and scope hits the file
  and pays no budget.
- **Flow 2 — a scoped group block**:
  `PrettyPlay.group(prompt, _scope="pages/login_page")` → ring 1 at entry → `StepGroup(..., scope=...)` →
  each `g.step(text)` (no per-step `_scope` allowed) → `_delegate(..., scope=self._scope)` → executor as
  Flow 1 → trace records carry the scoped identity → on a row failure `GroupRecovery.recover` re-renders each
  row step and rebuilds `StepIdentity` with the trace identity's cache_key AND scope — regeneration, budget
  refresh and write-back all key on the fresh scoped identity.
- **Flow 3 — close with cleanup=True**:
  `PrettyPlay.close()` → runtime teardown → `StepCache.sweep_untouched(cache_key)` enumerates only this
  store's unscoped directory; scoped files live in `root/<scope>/` (never enumerated) and carry
  `CACHE_KEY = scope` (key filter) — doubly immune; only this test's untouched unscoped files of its key are
  deleted.
- **Flow 4 — the site base URL**:
  `load_config()` (file `[tool.prettyplay.site] base_url` + env `PRETTYPLAY_SITE_BASE_URL` + programmatic
  `SiteConfig(base_url=...)` overlay) → `PrettyConfig.site` → `PrettyplayRuntime.config` →
  `PrettyPlay.site_base_url` (verbatim, `""` when unset) → the author composes `f"{t.site_base_url}/login"`
  into a step sentence — the rendered URL becomes part of the addressing text (staging and production are
  separate cache entries; the value is never wired into Playwright navigation).
- **Flow 5 — the insecure-TLS switch**:
  `BrowserConfig(ignore_https_errors=True)` (file/env/programmatic layers alike) → `DriverSession` holds
  `config` → first `open_context()`: `params = screen params + {"ignore_https_errors": True}` →
  `browser.new_context(**params)` inside the driver thread — identical for a local launch, a ws/wss connect and
  an http/https CDP connect; silent (no log record).

**Implementation order (leaves → root)**: `prettyplay/config` → `prettyplay/cache` → `prettyplay/driver` →
`prettyplay/engine/groups` → `prettyplay` (facade).

## Facts

- Contract layer: `goga lint` — 13 cells, **0 errors**; the new import edges (`cache → failures` for
  `PrettyplayError`/`taxonomy`; `facade,groups → cache` for `addressing`) are present and the dependency graph
  is acyclic.
- Baseline of the current tree (verified in a clean venv with `-e .` + test extras): `pytest tests/ -x` —
  1562 passed, 3 skipped; `ruff check prettyplay/ tests/` — all checks passed.
- The tree is NOT globally `ruff format`-clean (pre-existing deviations in `tests/engine/test_compliance.py`
  and `.usages/*.md`) — the enforced gate is `ruff check` per the conventions table; never reformat files
  outside a task's touched files.
- `StepIdentity.filename` today joins `(cache_key, step_type, normalized_text)` with `"\x1f"`
  (`_IDENTITY_SEPARATOR`, models.py:10) — only the first join member changes to `address_key`.
- `loader.py` today: `_ENV_NAMES` (lines 22–53) lists neither new setting; the dotted env merge lands every
  dotted field into `merged["browser"]` (lines 323–327) — browser-only; `_apply_overrides` (lines 246–283)
  has an isinstance branch for `BrowserConfig` only.
- `store.py` today: `load` reads `self._target_dir() / identity.filename` (line 111); `save` creates the temp
  file in `self._target_dir()` (line 165) and `os.replace`s onto the same directory (line 182); the sweep
  candidate filter is `_STEP_FILE_NAME.fullmatch(entry.name)` without an `is_file()` guard (line 222);
  `_serialize` writes the `CACHE_KEY` literal from `identity.cache_key`.
- `session.py` today: `open_context` resolves `params = self._screen_context_params()` and calls
  `browser.new_context(**params)` at lines 181–182 — the single surface the TLS parameter joins.
- `recovery.py` today: `fresh_identity = StepIdentity(cache_key=trace.identity.cache_key, ...)` (line 344)
  without `scope`.
- Facade `__all__` today: config — `["BrowserConfig", "ConfigurationError", "PrettyConfig", "adopt_config",
  "load_config"]`; cache — `["CachedStep", "RunBudgets", "StepCache", "StepIdentity", "normalize_step_text"]`;
  root — lists `BrowserConfig`, `PrettyConfig`, … (no `SiteConfig`).
- All test files the design targets already exist (`tests/config/test_models.py`, `tests/config/test_loader.py`,
  `tests/cache/test_models.py`, `tests/cache/test_store.py`, `tests/cache/test_budgets.py`,
  `tests/driver/test_session.py`, `tests/engine/groups/test_recovery.py`, `tests/test_executor.py`,
  `tests/test_scenario.py`, `tests/test_groups_integration.py`) — scenarios are added to them, no new test
  packages needed.
- Deleted entities: none. All five cells are modifications; nothing is removed.

## Gap Analysis

- **Missing contract entities**: `SiteConfig` (config/models.py), `validate_step_scope` (cache/models.py)
- **Missing facade exposure**: `SiteConfig` on `prettyplay.config` and the `prettyplay` re-export;
  `validate_step_scope` on `prettyplay.cache`
- **API mismatches (contract vs code)**:
  - `BrowserConfig` lacks `ignore_https_errors`; `PrettyConfig` lacks `site`
  - `StepIdentity` lacks `scope` and `address_key`; the digest uses `cache_key` as the first join member
  - `StepCache.load/save` lack ring-2 validation and scoped routing; `save` lacks the scoped `mkdir`;
    `_serialize` keys `CACHE_KEY` on `cache_key`; the sweep candidate filter lacks `is_file()`
  - `_ENV_NAMES` lacks `browser.ignore_https_errors` and `site.base_url`; the dotted env merge is
    browser-only; `_apply_overrides` handles `BrowserConfig` only
  - `DriverSession.open_context` params lack `ignore_https_errors`
  - `GroupRecovery.recover` builds `fresh_identity` without the trace scope
  - `PrettyPlay.step/expect/group` lack `_scope`; `PrettyPlay` lacks `site_base_url`; `StepExecutor.execute`
    lacks `scope`; `StepGroup` lacks the constructor/property/delegation scope and the per-step rejection
- **Behavioral mismatches**: none in existing behavior — unscoped addressing, sweep, budgets and the team
  workflow must behave exactly as before (compatibility guarantee)
- **Existing code to reuse**: the writability probe, `mkstemp` + `os.replace` + Windows-busy retry path, the
  touched set, `_STEP_FILE_NAME`, the loader validation wrap (`_render_validation`), `_raise_folded`,
  `_validate_tries`/`_validate_delay`/`_validate_vars` (the message style to match), the existing session test
  doubles (fake browser recording `new_context` kwargs), the executor/recovery test harnesses
- **Test coverage gaps**: the 29 test scenarios of the design's Test Stack Trace (none exist today)
- **`.usages/` gaps**: none — all files already current

---

## Mandatory Rules

Extracted from the project convention `.goga/usages/conventions.md` (the `conventions` practice bound by all
five cells) and the repo configuration. **These rules are mandatory for every task in this plan.** Where a
rule and a contract conflict, the contract wins (conventions' precedence: contract → facade obligations →
project conventions → language idioms).

### R1. Coding style (from `conventions` — Development)

1. Python **3.10+ only**; all configuration lives in `pyproject.toml`.
2. **All code executes in the virtualenv at `/opt/project`** (outside the repository) — create it if missing
   (the Task 1 fallback venv path applies when `/opt` is not writable and no elevation is available); never a
   repo-local venv, never the system interpreter.
3. **Imports**: relative imports for ALL intra-package references (`from .models import SiteConfig`);
   absolute imports only for stdlib and third-party. Absolute imports of `prettyplay.*` inside the package are
   forbidden.
4. **Data models**: pydantic for all data models; every model class uses `kw_only=True`; every field gets an
   empty/neutral default (`""`, `0`, `False`); `None` only for fields representing the explicit absence of a
   value.
5. **Logging**: the `logging` library (`logger = logging.getLogger(__name__)`); structured output with
   contextual metadata (`extra={...}`); lowercase, concise, stable event names; levels per the convention
   (DEBUG diagnostics, INFO lifecycle, WARNING recoverable abnormality, ERROR operation cannot complete,
   CRITICAL immediate intervention); **no secrets, credentials, tokens or personal data in any log output**.
   This plan adds no new log records anywhere.
6. **Formatting**: inside function and method bodies, logical blocks are separated by **one blank line** —
   initialization vs conditions/loops, data preparation vs processing, processing vs return.
7. **Docstrings**: Google style, mandatory for all public functions, methods and classes; first line starts
   with a capital letter and ends with a period; `Args`/`Returns`/`Raises` sections as applicable; brief,
   professional, one point per comment. Production docstring rules MUST NOT be applied to test code (see R2.4).
8. **Dependencies**: every third-party library in `pyproject.toml` with a minimum version; test libraries
   under `[project.optional-dependencies]` → `test`. This plan adds no new dependencies.
9. **Type hints mandatory**; no `*args`/`**kwargs`; generics always parameterized (`list[str]`, not `list`)
   — the cell contracts forbid them.
10. **Naming**: PascalCase classes; snake_case functions, methods, properties — consistent with the existing
    project vocabulary.

### R2. Test writing rules (from `conventions` — Testing)

1. **pytest** runs the tests; **ruff** lints test code; **pytest-cov** measures coverage. Test code is
   Python 3.10+ compatible and runs in the `/opt/project` venv.
2. **Structure mirrors the source directly**: `<src>/module/file.py` → `tests/module/test_file.py`; every
   test directory has `__init__.py`; local fixtures in `tests/<package>/conftest.py`, shared fixtures in
   `tests/conftest.py`; integration tests covering multiple packages live directly in `tests/`. The design's
   Source File Registry fixes the placement of this plan's scenarios — follow it.
3. **Naming**: files `test_<module>.py`; functions `test_<what>_<scenario>`
   (e.g. `test_complexity_with_empty_input`); grouping `class Test<Component>:` where the existing file uses
   classes; a good name communicates what is tested, under what condition, and what should happen.
4. **Test docstrings**: intent must be clear from a self-documenting name or a brief single-line scenario
   description; self-documenting tests MAY omit docstrings — missing docstrings alone are never a violation;
   `Args`/`Returns`/`Raises` are optional in test code; never restate implementation details.
5. **Test types**: unit tests for every public function/method/class (main scenario, typical data); edge
   cases — empty inputs (`None`, `""`, `[]`, `{}`), boundary values (`0`, negative, very large), invalid
   types, expected exceptions via `pytest.raises`; integration tests only for interactions between
   modules/packages. Integration tests never replace contract or logic tests.
6. **Boundary tests**: for thresholds, ranges and state transitions use `@pytest.mark.parametrize` with a
   table of values including each boundary (this plan's validator scenarios are parametrized).
7. **Mocks**: only at external boundaries — pure logic tests without mocks; file I/O exclusively through the
   `tmp_path` fixture; subprocesses via `mock.patch` of the call; external dependencies via `mock.patch` at
   the import point. Business-logic tests stay mock-free. The driver context tests mock the worker/browser
   boundary as the existing `test_session.py` does; cache tests use `tmp_path` exclusively for the store root.
8. Unavailable external dependencies are skipped via `pytest.mark.skipif`; comments in tests stay minimal.

### R3. Linter and formatter enforcement (convention + `pyproject.toml`)

1. **ruff is the project linter and formatter**, configured in `pyproject.toml` (`target-version = "py310"`,
   `line-length = 120`, rule set E/W/F/I/N/UP/B/SIM/PL/PLR/C4/DTZ/PT/ARG/RUF/PTH/C90, `max-complexity = 10`,
   per-file ignores for tests; format: double quotes, LF, space indent).
2. **`ruff check prettyplay/ tests/` must pass with zero errors at the end of EVERY task** (the LINT step of
   each task) — fix violations in the task's own code; decompose if `C901`/`PLR` limits are hit.
3. Format code the task writes or edits with `ruff format <touched files>`; the enforced gate is
   `ruff check` — the tree is not globally format-clean and files outside a task's touched set are never
   reformatted.
4. **Local commit discipline**: a local commit is allowed only when all gates are green —
   `ruff check prettyplay/ tests/`, `pytest tests/ -x`, and the facade import checks. One commit per completed
   task, after review approval. Never commit with failing or skipped-new tests.
5. The contract layer stays untouched: `goga lint` must keep reporting 13 cells / 0 errors after every task.

### R4. REPL cycle workflow (continuous evaluation → hot reloading → migration to source)

The workflow of every coding task is structured around short REPL cycles, not batch writing:

1. **Continuous interactive evaluation**: implement one unit at a time; BEFORE writing a unit into its source
   file, evaluate it interactively in the `/opt/project` venv (`/opt/project/bin/python` REPL,
   `/opt/project/bin/python - <<'PY'` heredocs, or `/opt/project/bin/python -c "..."`): construct the models,
   call the validators, exercise the task's edge inputs (the exact values from its test scenarios). Only
   behavior verified in the REPL migrates into the `location` file.
2. **Hot reloading**: after every source edit, immediately re-evaluate in a fresh interpreter
   (`python -c "from prettyplay.… import …; …"` or `importlib.reload` in a kept session) and re-run the
   focused test file (`/opt/project/bin/pytest tests/<path> -v`). The feedback loop is seconds — never
   "write everything, then run once". Contract tests written in STEP 1 are exercised the same way before
   implementation exists (they fail — expected — and their import surface is verified live).
3. **Code migration to source files**: the REPL is scratch space — verified snippets migrate verbatim into
   the declared `location` files; no durable implementation lives in REPL history, notebooks or scratch files;
   scratch files live outside the repo only. Migrated code must pass `ruff` and the task's tests in the same
   cycle.
4. **REPL-first debugging** (STEP 5): reproduce any failure in the REPL with the minimal input, fix the
   source file, re-run the focused test, then the full suite. Test code is never edited to make a failing
   implementation pass.
5. The cycle repeats per unit until the task's contract tests, logic tests, `ruff` and the facade imports are
   green — then, and only then, the task's checkboxes are marked complete and the commit gate (R3.4) applies.

---

## Tasks

> **Package ordering rule**: coding tasks for each package are completed before starting the next. Within
> each coding task, contract tests are written first (TDD workflow). Every task obeys the **Mandatory Rules**
> (R1–R4) — they apply to all tasks below and are not restated per task.

### Task 1: Development environment bootstrap and baseline (infrastructure)

All implementation and tests of this plan execute in a virtualenv at `/opt/project` — outside the repository,
per the project convention (R1.2). The venv does not necessarily exist in the execution environment; this task
creates it when missing, installs the project editable with its test extras, and pins the baseline every later
task compares against: the full suite green, the linter green, the facade importable, the contract layer at 13
cells / 0 errors. No product code is written here.

**Usages relevant to this task:**
- `conventions`: "Execute all code within a virtualenv environment — create it if missing"; validation
  commands table (`pytest tests/ -x`, `ruff check <src>/`, `python -c "from package import Entity"`).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] Create the venv if missing: `python3 -m venv /opt/project` (skip when `/opt/project/bin/python` exists). When
      `/opt/project` cannot be created (no write permission on `/opt` and no elevation available), bootstrap the
      venv at a user-writable location OUTSIDE the repository — `/opt/goga/project` (the writable `/opt/goga`
      subtree) — and use that interpreter path consistently in every command of this plan; record the chosen venv
      path once and substitute it wherever `/opt/project/bin/...` appears
      (done: `/opt` root-owned and not writable — venv created at `/opt/goga/project`, Python 3.12.16; path recorded
      in the progress log and substituted in all commands)
- [x] Install the project and the test toolchain from the repository root:
      `/opt/project/bin/pip install -e ".[test]"`
      (done via `/opt/goga/project/bin/pip install -e ".[test]"`)
- [x] Baseline tests: `/opt/project/bin/pytest tests/ -x` — all pass (baseline: 1562 passed, 3 skipped)
      (done: 1562 passed, 3 skipped — exact match)
- [x] Baseline lint: `/opt/project/bin/ruff check prettyplay/ tests/` — zero errors (all checks passed)
- [x] Baseline facades: `/opt/project/bin/python -c "from prettyplay import PrettyPlay, PrettyConfig, BrowserConfig"` and
      `/opt/project/bin/python -c "from prettyplay.config import PrettyConfig; from prettyplay.cache import StepIdentity"` — both import cleanly
- [x] Contract baseline: `goga lint` — 13 cells, 0 errors

### Task 2: `SiteConfig`, `BrowserConfig.ignore_https_errors`, `PrettyConfig.site` (models)

The config cell's model layer gains the D2 site group and the D1 boolean. Covers three contract entities in
one `location` (`prettyplay/config/models.py`): the NEW `SiteConfig(base_url: str)` (Entity — property
`base_url -> str`), the `BrowserConfig` field `ignore_https_errors: bool = False` with its property, and the
`PrettyConfig` field `site: SiteConfig` (default `SiteConfig()`) with its property. All models pydantic v2,
`kw_only=True`, `extra="forbid"`, empty defaults (R1.4). `SiteConfig` validates `base_url` at format level:
empty passes verbatim (unset); non-empty requires `urlparse(value).scheme in {"http", "https"}` and a
non-empty `netloc` — the `ValueError` surfaces as the ordinary pydantic `ValidationError` from the constructor
and through `_render_validation` as `ConfigurationError` from the loader (one place of validation; the loader
wrap is unchanged — Task 3 covers the loader). Facade obligation: `SiteConfig` importable from
`prettyplay.config`. Algorithm (verbatim from the design):

```
1. pydantic model: kw_only=True, extra="forbid"; field base_url: str = ""
2. field_validator("base_url"):
   IF value == "": accept verbatim (unset)
   parsed = urlparse(value)
   IF parsed.scheme not in {"http", "https"} OR parsed.netloc == "":
       raise ValueError("must be an http/https URL with a host")
   accept verbatim — no trailing-slash normalization, no path checks
```

Edge cases: `""` → unset, valid; `"https://"` (no netloc), `"example.com"` (no scheme), `"ftp://example.com"`
→ loud rejection; `"https://example.com/"` → kept verbatim including the trailing slash;
`ignore_https_errors` — none beyond the boolean parse (true/false/1/0 case-insensitive; env layer, Task 3).

**Usages relevant to this task:**
- `pydantic`: data-model practice of the config cell — kw_only groups with neutral defaults, field validators.
- `conventions`: R1.3 relative import of `SiteConfig` inside the package; R1.7 Google docstrings.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (expected to fail now): in `tests/config/test_models.py` — `from prettyplay.config import SiteConfig` (facade); `SiteConfig(base_url=...)` constructs kw_only and exposes property `base_url`; `BrowserConfig()` exposes `ignore_https_errors` (bool) and `PrettyConfig()` exposes `site` (a `SiteConfig`)
- [ ] **Code**: add `SiteConfig` to `prettyplay/config/models.py` per the algorithm above (field + `field_validator("base_url")`, verbatim keeping, no dedicated error type — plain `ValueError` through pydantic)
- [ ] **Code**: add `ignore_https_errors: bool = False` + property to `BrowserConfig` (no dedicated validator) and `site: SiteConfig = SiteConfig()`-style default group + property to `PrettyConfig` — symmetric to `browser`
- [ ] **Code**: export `SiteConfig` from `prettyplay/config/__init__.py` (relative import; `__all__` sorted per the existing listing)
- [ ] **Interface verification**: `/opt/project/bin/pytest tests/config/test_models.py -v` — contract tests pass; `/opt/project/bin/python -c "from prettyplay.config import SiteConfig"`
- [ ] **Logic tests** in `tests/config/test_models.py` (design scenarios, verbatim assertions):
      `test_site_config_accepts_http_url` — asserts `PrettyConfig(site=SiteConfig(base_url="https://staging.example.com")).site.base_url == "https://staging.example.com"` (the group reachable inside the model) and `SiteConfig().base_url == ""` (the empty default);
      `test_browser_config_has_ignore_https_errors_default` — `BrowserConfig().ignore_https_errors is False`, `BrowserConfig(ignore_https_errors=True).ignore_https_errors is True`;
      negative `test_site_config_rejects_non_http_url` — parametrized `["example.com", "ftp://example.com", "https://", "http:///path"]`, `pytest.raises(ValidationError)`
- [ ] **Debugging**: `/opt/project/bin/pytest tests/config/ -v` — fix implementation (never tests) until green
- [ ] **Contract re-verification**: facade (`from prettyplay.config import SiteConfig`), API shape (three fields/properties match the contract signatures), behavior (empty default, verbatim keeping, loud rejection)
- [ ] **Lint**: `/opt/project/bin/ruff check prettyplay/ tests/` — fix formatting of touched files if necessary

### Task 3: `load_config` — env names, per-group env merge, group-aware `_apply_overrides`

The loader layer of the config cell: `prettyplay/config/loader.py` only. Three coupled changes: (1)
`_ENV_NAMES` gains `"browser.ignore_https_errors"` (add to `_BOOL_ENV_SETTINGS` — true/false/1/0
case-insensitively; unparseable raises `ConfigurationError` naming the setting, the received value and the
accepted form through the existing `_parse_env_scalar` rule) and `"site.base_url"` (a string, taken verbatim —
no parse set); (2) the dotted env merge generalizes from browser-only to per-group — every dotted setting
splits into `(group, field)` and each group's env fields merge into `merged[group] = {**section.get(group, {}),
**env_fields}`; `site` appears as its own nested section beside `browser`; (3) `_apply_overrides`'s isinstance
branch covers both group models through ONE branch (`isinstance(value, BrowserConfig | SiteConfig)`) — do not
special-case `site` in a second code path. `adopt_config` needs no change. Algorithm (verbatim from the
design):

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

Edge cases: `PRETTYPLAY_SITE_BASE_URL=""` (set but empty) is collected as a set override and lands in
`merged["site"]["base_url"] = ""` — the file value is replaced by unset, symmetric to `PRETTYPLAY_MODEL=""`;
the string-empty guard applies to the programmatic layer only. `PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS=maybe`
raises the loud `ConfigurationError`. A passed `SiteConfig()` with nothing explicitly set → the file group
survives untouched.

**Usages relevant to this task:**
- `pydantic`: TOML loading and the layered-merge practice (`model_fields_set`, `model_copy`).
- `conventions`: R1.6 blank-line block separation inside the reworked merge; R1.7 docstrings on the touched
  functions.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (expected to fail now): in `tests/config/test_loader.py` — a pyproject with `[tool.prettyplay.site] base_url` and `[tool.prettyplay.browser] ignore_https_errors` loads through `load_config` into the effective model; env names `PRETTYPLAY_SITE_BASE_URL` / `PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS` override the file layer
- [ ] **Code**: extend `_ENV_NAMES` and `_BOOL_ENV_SETTINGS` per the algorithm
- [ ] **Code**: generalize the dotted env merge to per-group prefixes (replace the browser-only `group_env` block at loader.py:323–327)
- [ ] **Code**: widen `_apply_overrides`'s isinstance branch to `BrowserConfig | SiteConfig` — one branch, both group models
- [ ] **Interface verification**: `/opt/project/bin/pytest tests/config/test_loader.py -v` — contract tests pass
- [ ] **Logic tests** in `tests/config/test_loader.py` (design scenarios):
      `test_load_config_reads_site_group_and_tls_switch` — file layer only (monkeypatched env without PRETTYPLAY_*); asserts `config.site.base_url == "https://staging.example.com"`, `config.browser.ignore_https_errors is True`;
      `test_load_config_env_overrides_site_and_tls` — file `https://file.example.com`/`false` + env `PRETTYPLAY_SITE_BASE_URL=https://env.example.com`, `PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS=1`; asserts the env values win (`"1"` parses to True);
      `test_load_config_env_empty_site_base_url_clears_file_value` — env `PRETTYPLAY_SITE_BASE_URL=""` set-but-empty; asserts `config.site.base_url == ""` (pins "a set-but-empty env variable clears the file layer");
      `test_apply_overrides_site_group_merge` — `overrides=PrettyConfig(site=SiteConfig(base_url="https://prod.example.com"))` wins; `overrides=PrettyConfig(site=SiteConfig())` leaves the file value `https://staging.example.com` untouched;
      negative `test_load_config_env_invalid_tls_boolean_fails_loudly` — env `PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS=maybe`; `pytest.raises(ConfigurationError)` with `"browser.ignore_https_errors"` and `"maybe"` in the message
- [ ] **Debugging**: `/opt/project/bin/pytest tests/config/ -v` then `/opt/project/bin/pytest tests/ -x` — fix implementation until green
- [ ] **Contract re-verification**: no raw `pydantic.ValidationError` leaves the loader; the existing browser merge behavior is unchanged (existing loader tests still pass)
- [ ] **Lint**: `/opt/project/bin/ruff check prettyplay/ tests/`

### Task 4: `validate_step_scope` — the one rule of both rings

The cache cell's NEW routine in `prettyplay/cache/models.py`: `validate_step_scope(scope: str) -> None`. A
pure validator (no I/O, no state, no normalization — a valid value passes verbatim); a violation raises the
loud actionable `PrettyplayError` (imported from `prettyplay/failures` — the new contract edge) naming the
parameter `_scope`, the received value and the allowed form — one render, deterministic, matching the message
style of `_validate_tries`/`_validate_delay`. Facade obligation: importable from `prettyplay.cache`.
Algorithm (verbatim from the design):

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

Edge cases — rejected: `""`, `"/pages"`, `"pages/"`, `"pages//login"`, `".."`, `"a/../b"`, `"pages\login"`,
`"C:/pages"`, `"pages login"`, `"страница"`, `"pages:login"`; accepted: `"pages/login_page"`, `"a"`,
`"v1.2.config-x"`, `"pages/nested/deep"`, and the `"."`-only segments (`"."`, `"pages/."`, `"..."`) — the dot
is a legal segment character, only `".."` is banned; they route nowhere special (`root / Path(".")` is the
root itself) — document nothing extra, they are simply accepted.

**Usages relevant to this task:**
- `taxonomy` from Imports (`prettyplay/failures/.usages/taxonomy.md`): the failure kinds and the loud
  actionable message style — `PrettyplayError`, an authoring error, no structured verdict.
- `conventions`: R1.7 Google docstring on the routine; R2.6 parametrized boundary tests.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (expected to fail now): in `tests/cache/test_models.py` — `from prettyplay.cache import validate_step_scope` (facade); called with a valid scope returns `None`
- [ ] **Code**: implement `validate_step_scope` in `prettyplay/cache/models.py` per the algorithm (module-level compiled `_SCOPE_SEGMENT`; keep it beside `StepIdentity` — pure function)
- [ ] **Code**: export `validate_step_scope` from `prettyplay/cache/__init__.py` (relative import; `__all__` sorted)
- [ ] **Interface verification**: `/opt/project/bin/pytest tests/cache/test_models.py -v` — contract tests pass; `/opt/project/bin/python -c "from prettyplay.cache import validate_step_scope"`
- [ ] **Logic tests** in `tests/cache/test_models.py` (design scenarios):
      `test_validate_step_scope_accepts_valid_scopes` — parametrized `["pages/login_page", "a", "v1.2.config-x", "pages/nested/deep"]`, each returns `None`;
      negative `test_validate_step_scope_rejects_invalid_scopes` — parametrized `["", "/pages", "pages/", "pages//login", "..", "a/../b", "pages\login", "C:/pages", "pages login", "страница", "pages:login"]`, `pytest.raises(PrettyplayError)` — the message names `_scope`, the received value and the allowed form
- [ ] **Debugging**: `/opt/project/bin/pytest tests/cache/ -v` — fix implementation until green
- [ ] **Contract re-verification**: pure function (verify in the REPL: same input → same outcome, no filesystem access); facade importable
- [ ] **Lint**: `/opt/project/bin/ruff check prettyplay/ tests/`

### Task 5: `StepIdentity` — `scope`, `address_key`, digest rule

The address record of the cache cell: `prettyplay/cache/models.py`, `StepIdentity` only. Adds the kw_only
field `scope: str = ""` (the default keeps every existing construction unscoped — tests, the recovery record-0
load, usage examples; do NOT make it required), the property `address_key -> str`
(`self.scope if self.scope else self.cache_key`), and rebuilds `filename` on `address_key` — the digest
separator (`_IDENTITY_SEPARATOR = "\x1f"`) and sha256 hashing stay exactly as today; only the first join
member changes. The record holds no validation. Algorithm (verbatim from the design):

```
1. field scope: str = ""   (kw_only; the default keeps existing constructions unscoped)
2. property address_key: scope if scope != "" else cache_key
3. property filename:
       identity_string = "\x1f".join((address_key, step_type, normalized_text))
       return f"{sha256(identity_string.encode('utf-8')).hexdigest()}.py"
```

Edge case: `scope == cache_key` → one address space is preserved — identical digests and identical metadata
keys; coherent by construction, never a collision bug. Hard guarantee: with an empty scope the digest input is
byte-identical to the pre-change triple — no unscoped address changes.

**Usages relevant to this task:**
- `addressing` (cell-local `.usages/addressing.md`): the identity model with the scope row — the consumer
 -facing pattern `StepIdentity(..., scope=...)` and `identity.address_key`.
- `conventions`: R1.4 kw_only with an empty default; R1.7 docstring updates on the model.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (expected to fail now): in `tests/cache/test_models.py` — `StepIdentity` accepts `scope` kwarg with default `""`; exposes properties `scope` and `address_key`; existing construction sites (no `scope`) still valid
- [ ] **Code**: add the `scope` field and the `address_key` property; rebase `filename` onto `address_key` (models.py:37 today joins `cache_key` first)
- [ ] **Interface verification**: `/opt/project/bin/pytest tests/cache/test_models.py -v` — contract tests pass; REPL-verify an unscoped digest equals the pre-change value
- [ ] **Logic tests** in `tests/cache/test_models.py` (design scenarios, verbatim assertions):
      `test_step_identity_scoped_address_key_and_filename` — `StepIdentity(cache_key="login-flow", step_type="action", normalized_text="open the dashboard", scope="pages/dashboard")`; asserts `address_key == "pages/dashboard"`, `filename == f"{hashlib.sha256('\x1f'.join(('pages/dashboard', 'action', 'open the dashboard')).encode()).hexdigest()}.py"`, `scope == "pages/dashboard"`;
      `test_step_identity_unscoped_digest_unchanged` — asserts `address_key == "login-flow"`, `filename` equals the inline-computed pre-change digest of `("login-flow", "action", "open the dashboard")`, and `StepIdentity(..., scope="").filename == StepIdentity(...).filename`;
      edge `test_scoped_identity_and_equal_cache_key_share_one_address` — `a` with `cache_key="pages/login", scope=""` and `b` with `cache_key="k", scope="pages/login"`; asserts `a.filename == b.filename` (one address space)
- [ ] **Debugging**: `/opt/project/bin/pytest tests/cache/ -v` — fix implementation until green
- [ ] **Contract re-verification**: unscoped digests byte-stable; the record performs no validation
- [ ] **Lint**: `/opt/project/bin/ruff check prettyplay/ tests/`

### Task 6: `StepCache` — ring 2, scoped routing, address-key metadata, sweep guard

The store of the cache cell: `prettyplay/cache/store.py` (`load`, `save`, `sweep_untouched`, `_serialize`; a
new private `_step_dir(identity)` helper shared by load and save). Ring 2 lives in the directory resolution —
once, before any path is composed; a violation raises the same `PrettyplayError` (the address never escapes
the cache root even when the facade was bypassed). Scoped routing: `root/<scope>/` (the store subdirectory
never applies to scoped steps); the scoped directory is created at save time only, inside the
OSError-guarded skip path. `_serialize` writes the `CACHE_KEY` literal from `identity.address_key`. The sweep
candidate filter gains the `entry.is_file()` guard. Algorithms (verbatim from the design):

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

sweep candidates:
candidates = (entry for entry in scope.iterdir()
              if entry.is_file() and _STEP_FILE_NAME.fullmatch(entry.name))
```

Unscoped reads/writes keep the exact pre-change behavior (`address_key == cache_key`). Errors: a scope
violation raises `PrettyplayError` (ring 2); every I/O failure degrades to the existing skip path — a save
never fails the run. Edge cases: the temp file is created IN the resolved scoped directory (same filesystem as
the replace); a `path="checkout"` store never composes with a scope; a scope literally named `<64 hex>.py`
creates a directory matching the digest pattern — the `is_file()` guard keeps it out of the candidates.

**Usages relevant to this task:**
- `hooks` from Imports: the payload contract of the existing cache events — `on_cache_saved`/`on_cache_skipped`
  ride unchanged; no new events.
- `taxonomy` from Imports: the `PrettyplayError` of ring 2.
- `addressing`: the scoped `root/<scope>/` routing and `CACHE_KEY = address_key` header contract.
- `conventions`: R2.7 — `tmp_path` exclusively for the store root.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (expected to fail now): in `tests/cache/test_store.py` — `StepCache.load`/`save` accept scoped identities: a scoped save stores under `<root>/<scope>/` and a scoped load finds it; unscoped roundtrip unchanged
- [ ] **Code**: add `_step_dir(identity)` (ring 2 + scoped routing) and route `load` (store.py:111) and `save` (store.py:165, 182) through it
- [ ] **Code**: `_serialize` — the `CACHE_KEY` literal from `step.identity.address_key`; `load` verifies `CACHE_KEY == identity.address_key`
- [ ] **Code**: the scoped `mkdir(parents=True, exist_ok=True)` inside the OSError-guarded skip path (a failure reports `on_cache_skipped` with the reason "cache target busy" and returns False — never raising)
- [ ] **Code**: add `entry.is_file()` to the sweep candidate filter (store.py:222)
- [ ] **Interface verification**: `/opt/project/bin/pytest tests/cache/test_store.py -v` — contract tests pass; the existing unscoped store tests stay green
- [ ] **Logic tests** in `tests/cache/test_store.py` (design scenarios):
      `test_store_save_and_load_scoped_step_roundtrip` — setup `StepCache(config=PrettyConfig(cache_root=str(tmp_path / "cache")), reporter=StepReporter(hooks=[]))`, identity with `scope="pages/dashboard"`; asserts `stored is True`, `loaded is not None`, `loaded.code == step.code`, `loaded.addressing_text == "open the dashboard"`, `(tmp_path / "cache" / "pages" / "dashboard").is_dir()`, the routed `*.py` file exists, its text contains `CACHE_KEY = 'pages/dashboard'`, and the unscoped address (`scope=""`) is a miss (`None`);
      `test_store_sweep_never_deletes_scoped_files` — a scoped step plus an untouched unscoped step of key `"login-flow"`; `sweep_untouched("login-flow")` asserts `removed == [<unscoped digest>.py]` and the scoped file still exists;
      negative `test_store_ring2_rejects_invalid_scope_on_load_and_save` — `bad = StepIdentity(cache_key="k", step_type="action", normalized_text="x", scope="../escape")` constructed directly; `pytest.raises(PrettyplayError)` on load AND on save; nothing read or written outside the root;
      edge `test_store_scoped_step_with_store_subdirectory_ignores_it` — `StepCache(..., path="checkout")` with a scoped save; asserts the file exists at `<root>/pages/dashboard/<digest>.py`, `(<root>/checkout/pages/dashboard)` does not exist, `(<root>/checkout/<digest>.py)` does not exist;
      edge `test_store_scoped_dir_matching_digest_name_not_swept` — a scope of exactly `<64 hex>.py`; `sweep_untouched("k")` leaves the digest-named directory existing and `removed` contains only the unscoped file
- [ ] **Debugging**: `/opt/project/bin/pytest tests/cache/ -v` then `/opt/project/bin/pytest tests/ -x` — fix implementation until green
- [ ] **Contract re-verification**: ring-2 ordering (validation before path composition) in both `load` and `save`; unscoped behavior byte-identical; a save never raises on I/O failure
- [ ] **Lint**: `/opt/project/bin/ruff check prettyplay/ tests/`

### Task 7: Integration tests — scoped cache economics (two writers, per-test budgets)

Cross-entity scenarios of the cache package that span instances and modules: the concurrent-writers property
of a shared scoped address (two `StepCache` instances over one root — `StepCache` × `StepCache` × the
deterministic address) and the budget economics of a scoped identity (`RunBudgets` × `StepIdentity` — budgets
key by `identity.filename`, so scoped identities draw their own per-test pools). No production code is written
here; these tests pin contract properties the unit tests argue only analytically.

**Usages relevant to this task:**
- `addressing`: the shared-scope entries and scoped-budgets bullets — the documented economics.
- `hooks`: the unchanged cache events both writer instances emit.
- `conventions`: R2.7 `tmp_path` exclusively; R2.8 integration scenarios for cross-instance interaction.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] Create/extend the scenarios in `tests/cache/test_store.py` and `tests/cache/test_budgets.py`
- [ ] `test_store_two_writers_same_scoped_step_reader_accepts_either` (test_store.py) — two stores over one `tmp_path` root; `identity_a` (cache_key `"a"`) and `identity_b` (cache_key `"b"`) with identical `step_type`, `normalized_text`, `scope="pages/login"` — identical `address_key`, identical digest; two `CachedStep`s with identical code, different `created_at`; save a then b, load through both; asserts `stored_a is True and stored_b is True`, `loaded_by_a is not None and loaded_by_b is not None`, `loaded_by_a.code == loaded_by_b.code == step_b.code` (last writer wins, valid for every reader), `len(list((tmp_path / "cache" / "pages" / "login").glob("*.py"))) == 1` (one address ⇒ one file)
- [ ] `test_budgets_scoped_step_pays_per_test` (test_budgets.py) — `RunBudgets(generation_limit=1, healing_limit=1)` and a scoped identity; registry A: `a.try_generation(identity) is True` then `is False`; fresh registry B: `b.try_generation(identity) is True` — per-test budgets, no shared scope budget
- [ ] Run validation: `/opt/project/bin/pytest tests/cache/ -v`

### Task 8: `DriverSession.open_context` — the insecure-TLS context parameter

The driver cell's single change: `prettyplay/driver/session.py`, `open_context` (the `open_isolated` body,
session.py:181–182 today). The resolved context parameters gain `ignore_https_errors` from the browser group —
one surface at the same `new_context` call as the screen modes; never a launch argument, so the local launch,
the ws/wss connect and the http/https CDP connect are identical (the `_launch` branching is finished before
`open_context` runs). Enabling is silent — no log record at any level. Algorithm (verbatim from the design):

```
inside open_isolated (driver thread):
    params = {**self._screen_context_params(),
              "ignore_https_errors": self._config.browser.ignore_https_errors}
    context = browser.new_context(**params)
    ... dialog router, new_page, set_default_timeout — unchanged
```

Edge cases: none — the parameter rides an existing call in every start mode; `False` (default) passes
Playwright's untouched certificate checking.

**Usages relevant to this task:**
- `playwright` (`.goga/usages/cooks/playwright.md`, section "Insecure TLS"):
  `browser.new_context(ignore_https_errors=True)` — a context parameter, never a launch argument.
- `configuration` from Imports: `config.browser.ignore_https_errors` — the browser-group field the session
  reads (documented in the usage's "Insecure TLS" section).
- `conventions`: R1.5 no new log records.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (expected to fail now): in `tests/driver/test_session.py` — `open_context` passes `ignore_https_errors` into `new_context` (recorded by the existing fake-browser double pattern of the file)
- [ ] **Code**: extend the `params` dict per the algorithm (session.py:181) — one line joining the screen params; nothing else in the unit changes
- [ ] **Interface verification**: `/opt/project/bin/pytest tests/driver/test_session.py -v` — contract tests pass; the existing session tests stay green
- [ ] **Logic tests** in `tests/driver/test_session.py` (design scenario):
      `test_open_context_passes_ignore_https_errors` — the existing session test double (a fake browser recording `new_context` kwargs), `config = PrettyConfig(browser=BrowserConfig(ignore_https_errors=True))` (screen empty); asserts `recorded_kwargs.get("ignore_https_errors") is True`; and with the default `ignore_https_errors=False`: `recorded_kwargs.get("ignore_https_errors") is False`
- [ ] **Debugging**: `/opt/project/bin/pytest tests/driver/ -v` — fix implementation until green
- [ ] **Contract re-verification**: one `new_context` surface; silent enablement (no new log records — grep the diff for logging calls)
- [ ] **Lint**: `/opt/project/bin/ruff check prettyplay/ tests/`

### Task 9: `GroupRecovery.recover` row re-addressing + `GroupStepOutcome.identity` documentation

The groups cell: `prettyplay/engine/groups/recovery.py` (row step 5) and `prettyplay/engine/groups/outcome.py`
(docstring only). The row mechanics build every fresh row identity from the re-rendered text PLUS the trace
identity's `cache_key` AND `scope` — a scoped group's rows re-address under the group's scope; regeneration,
budget refresh and the cache write-back all key on the fresh scoped identity. `GroupStepOutcome` has no
signature change — its `identity` docstring/annotation gains "both address parts" (the record change is
`StepIdentity`, Task 5). Record 0 (`self._cache.load(trace.identity)`, recovery.py:413) already uses the scoped
trace identity — no change there. Algorithm (verbatim from the design):

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

Edge case: a scoped group whose row re-render produces changed memory → a new normalized text under the same
scope → a new address with a fresh budget — the designed semantics.

**Usages relevant to this task:**
- `addressing` from Imports: the scoped identity pattern of the row mechanics.
- `recovery` (cell-local `.usages/recovery.md`): the re-address bullet carries the cache key AND the scope.
- `rendering`, `memory`, `validation` from Imports: the unchanged row re-render, publication and acceptance
  mechanics this change threads through.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (expected to fail now): in `tests/engine/groups/test_recovery.py` — a row step's `regenerate` receives an identity carrying the trace identity's `scope`
- [ ] **Code**: add `scope=trace.identity.scope` to the `fresh_identity` construction (recovery.py:344)
- [ ] **Code**: update the `GroupStepOutcome.identity` documentation in `outcome.py` — "both address parts (cache_key, scope); the row re-render derives a fresh address — this record keeps the execution fact"
- [ ] **Interface verification**: `/opt/project/bin/pytest tests/engine/groups/ -v` — contract tests pass; the existing recovery tests stay green
- [ ] **Logic tests** in `tests/engine/groups/test_recovery.py` (design scenario, verbatim assertions): `test_recovery_row_readdresses_under_group_scope` — the existing recovery harness with a scoped trace identity (`StepIdentity(cache_key="k", step_type="action", normalized_text="fill the login field", scope="pages/login")`), a diagnosis verdict naming the earliest row step, a generator double recording the `identity` of `regenerate`; asserts `recorded_identity.scope == "pages/login"`, `recorded_identity.cache_key == "k"`, `recorded_identity.normalized_text == normalize_step_text(fresh.addressing_text)`
- [ ] **Debugging**: `/opt/project/bin/pytest tests/engine/groups/ -v` — fix implementation until green
- [ ] **Contract re-verification**: the write-back never lands under a stale or scope-less trace identity; unscoped groups behave exactly as before
- [ ] **Lint**: `/opt/project/bin/ruff check prettyplay/ tests/`

### Task 10: `StepExecutor.execute` — the `scope` parameter and the scoped identity build

The facade cell's execution layer: `prettyplay/executor.py`, `execute` (signature at executor.py:116 with the
existing `noqa PLR0913, PLR0917, C901, PLR0912` — keep it). Adds `scope: str | None = None` (keyword in the
delegation); the step identity is built with the scope — `None` becomes the empty scope of the record; no
validation of its own (the rings own the rule); the scope never enters the rendered sentence or any LLM
request (it is addressing data only). Everything downstream (strict mode, healing, steering, the recovery
delegation, budgets via `identity.filename`) keys by the identity as today and receives the scoped identity
unchanged. Algorithm (verbatim from the design):

```
execute(..., scope: str | None = None):
    ... delay, render, on_step_started ...
    identity = StepIdentity(cache_key=self.cache_key, step_type=step_type,
                            normalized_text=normalize_step_text(prepared.addressing_text),
                            scope=scope or "")
    ... the cycle unchanged, keyed by the identity ...
```

Edge cases: `""` and `None` are equivalent (unscoped); scoped and unscoped steps share one code path — only
the identity differs.

**Usages relevant to this task:**
- `addressing` from Imports: `StepIdentity(..., scope=...)` and `identity.address_key` — for a scoped step
  the scope is the address key.
- `conventions`: R1.10 keyword-only parameter style consistent with the facade delegation.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (expected to fail now): in `tests/test_executor.py` — `execute` accepts `scope` (a cache double records the loaded identity)
- [ ] **Code**: add the `scope` parameter and the identity build change per the algorithm (executor.py:182)
- [ ] **Interface verification**: `/opt/project/bin/pytest tests/test_executor.py -v` — contract tests pass; the existing executor tests stay green
- [ ] **Logic tests** in `tests/test_executor.py` (design scenario, verbatim assertions): edge `test_executor_none_scope_becomes_empty_scope` — the existing executor harness; `executor.execute("plain sentence", "action", page, scope=None)`; asserts `recorded_identity.scope == ""` and `recorded_identity.address_key == executor.cache_key`
- [ ] **Debugging**: `/opt/project/bin/pytest tests/test_executor.py -v` — fix implementation until green
- [ ] **Contract re-verification**: the executor adds no validation; the recovery delegation carries the scoped identity unchanged
- [ ] **Lint**: `/opt/project/bin/ruff check prettyplay/ tests/`

### Task 11: `StepGroup` — the block scope

The facade cell's group layer: `prettyplay/groups.py` (`__init__`, `step`, `expect`, `_delegate`) and the
constructor call site in `prettyplay/scenario.py` (Task 12 owns the rest of scenario.py; the constructor
signature change belongs here with its call-site fix — coordinate: this task adds the parameter with a default
`None`, so scenario.py keeps working until Task 12 passes the validated scope). The constructor gains
`scope: str | None` (fourth parameter, after `delay` and before `executor` — carried from the facade after
ring-1 validation); the
property `scope -> str | None`; `step`/`expect` gain the keyword-only `_scope: str | None = None` that is
REJECTED when non-None — the scope is set once per block (`group(..., _scope=...)`), never per step; the
rejection fires before the entry/between-step pause and before the page opener; `_delegate` passes
`scope=self._scope` to `executor.execute`. Algorithm (verbatim from the design):

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

Edge cases: a per-step `_scope=None` inside a group is accepted (no override attempt) — only a non-None value
is rejected; `None` — the group's steps address unscoped (executor receives `scope=None`); group membership
changes neither a step's scope nor its address — the group only passes its scope down.

**Usages relevant to this task:**
- `addressing` from Imports: the block-scope pattern — the group passes its scope down with every step.
- `taxonomy` from Imports: the loud actionable `PrettyplayError` of the per-step rejection.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (expected to fail now): in `tests/test_groups_integration.py` — `StepGroup` exposes `scope`; `g.step(..., _scope="x")` raises `PrettyplayError` naming the parameter and the remedy
- [ ] **Code**: extend `StepGroup.__init__` (groups.py:108) with `scope` and store `self._scope`; add the `scope` property; update the "five-parameter" comment at scenario.py:367 and the constructor call to pass `_scope` positionally-after-`delay` (the facade still sends `None` until Task 12)
- [ ] **Code**: add the `_scope` rejection to `step`/`expect` BEFORE the pause and page opener; thread `scope=self._scope` through `_delegate`
- [ ] **Interface verification**: `/opt/project/bin/pytest tests/test_groups_integration.py -v` — contract tests pass; the existing group tests stay green
- [ ] **Logic tests** in `tests/test_groups_integration.py` (design scenario): negative `test_group_step_rejects_per_step_scope` — an opened group block `g = t.group("the user signs in", _scope="pages/login_page")` (after Task 12; until then construct via the harness used by the existing file) — `g.step("fill the login field", _scope="pages/other")`; `pytest.raises(PrettyplayError)` with the remedy naming `group(..., _scope=...)`; no pause, no page open, no delegation
- [ ] **Debugging**: `/opt/project/bin/pytest tests/test_groups_integration.py -v` — fix implementation until green
- [ ] **Contract re-verification**: the rejection precedes the delegation, the pause and the page opener; `g.scope` matches the constructor value
- [ ] **Lint**: `/opt/project/bin/ruff check prettyplay/ tests/`

### Task 12: `PrettyPlay` — ring 1, `site_base_url`, the `SiteConfig` re-export

The facade surface: `prettyplay/scenario.py` (`step`, `expect`, `group`, the new property, the `cache_path`
docstring) and `prettyplay/__init__.py` (the `SiteConfig` re-export). Ring 1 lives beside the existing parameter validations:
`if _scope is not None: validate_step_scope(_scope)` — on `step`/`expect` BEFORE `_ensure_page()` (no browser
starts for an invalid scope), on `group` at entry BEFORE `StepGroup` construction (so `on_group_started` can
never fire for an invalid scope); a violation raises the loud actionable `PrettyplayError` naming `_scope`,
the received value and the allowed form, the traceback folded to the library boundary (`_raise_folded`) — the
existing guarantee. The delegation carries the validated scope (`scope=_scope`). The property
`site_base_url -> str` returns `self._runtime.config.site.base_url` — verbatim, `""` when unset; no new state
(the facade already retains `self._runtime`). The re-export: `from .config import …, SiteConfig` and
`__all__` gains `SiteConfig` (uniform with `PrettyConfig`/`BrowserConfig`). Algorithm (verbatim from the
design):

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

Edge cases: `_scope=None` everywhere — exactly the pre-change behavior; `t.site_base_url == ""` when unset;
`_scope=""` is rejected at ring 1 (empty yields no valid segments).

**Usages relevant to this task:**
- `addressing` from Imports: the facade's `_scope` surface and the scoped identity the delegation produces.
- `taxonomy` from Imports: the failure kinds the step methods propagate.
- `conventions`: R1.3 relative imports for the re-export; facade `__all__` discipline.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (expected to fail now): in `tests/test_scenario.py` — `from prettyplay import SiteConfig` (facade re-export); `PrettyPlay` exposes `site_base_url`; `step`/`expect`/`group` accept keyword-only `_scope`
- [ ] **Code**: add `_scope` + ring-1 validation + `scope=_scope` delegation to `step`/`expect` (scenario.py:248, 294) and `group` (scenario.py:333); pass `_scope` into the `StepGroup` construction
- [ ] **Code**: add the `site_base_url` property (`self._runtime.config.site.base_url`)
- [ ] **Code**: update the `cache_path` constructor docstring in `scenario.py` — a scoped step routes by its
      `_scope` instead; this subdirectory never applies to it (the contract's parameter description)
- [ ] **Code**: re-export `SiteConfig` from `prettyplay/__init__.py` (relative import, `__all__` per the facade listing order)
- [ ] **Interface verification**: `/opt/project/bin/pytest tests/test_scenario.py -v`; `/opt/project/bin/python -c "from prettyplay import SiteConfig"`
- [ ] **Logic tests** (design scenarios, verbatim assertions) in `tests/test_scenario.py`:
      `test_scenario_site_base_url_property` — `t = PrettyPlay("k", config=PrettyConfig(site=SiteConfig(base_url="https://staging.example.com")))`; asserts `t.site_base_url == "https://staging.example.com"` and `PrettyPlay("k2", config=PrettyConfig()).site_base_url == ""`;
      `test_scenario_step_scope_ring1_validates_before_execution` — `t = PrettyPlay("k", config=PrettyConfig(strict=True))` (no page opened, no browser started); `t.step("open the dashboard", _scope="pages/../escape")`; `pytest.raises(PrettyplayError)` — the message names `_scope`, the received value `"pages/../escape"` and the allowed form; `t._page is None` (the validation preceded everything);
      negative `test_scenario_group_invalid_scope_rejected_at_entry` — `t.group("the user signs in", _scope="bad scope")`; `pytest.raises(PrettyplayError)` — before `StepGroup` construction, `on_group_started` never fires
- [ ] **Debugging**: `/opt/project/bin/pytest tests/test_scenario.py -v` then `/opt/project/bin/pytest tests/ -x` — fix implementation until green
- [ ] **Contract re-verification**: facade (`SiteConfig`, `site_base_url`, `_scope` surfaces); ring-1 ordering (before `_ensure_page()`, before the block opens); the traceback folding guarantee
- [ ] **Lint**: `/opt/project/bin/ruff check prettyplay/ tests/`

### Task 13: Integration tests — the scoped group block end to end

The facade cell's cross-entity scenarios in `tests/test_groups_integration.py` (existing harness patterns of
the file): the group scope threading from the facade ring 1 through `StepGroup`/`StepExecutor` into the store
routing (Flow 2), and the isolation property that the scope addresses and routes only — it never leaks into
the rendered sentence or any LLM request. These close the D3 page-object story on top of the unit tasks.

**Usages relevant to this task:**
- `addressing`: the scoped block pattern — `group(prompt, _scope=...)` addresses every step of the block.
- `recovery` from Imports: the trace records carry the scoped identity the recovery re-addresses under.
- `conventions`: R2.7 — mock only at the LLM/generator boundary; reuse the file's established fake-page
  harness.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] Extend `tests/test_groups_integration.py` with the two scenarios
- [ ] `test_scenario_group_scope_threads_to_executor` — `with t.group("the user signs in", _scope="pages/login_page") as g: g.step("fill the login field")`, the executor identity build observed (spy on `StepCache.save`/`load` identity or the executor call, per the file's established pattern); asserts `g.scope == "pages/login_page"`, the saved/loaded `identity.scope == "pages/login_page"`, the file landed under `<cache root>/pages/login_page/`
- [ ] `test_scenario_scope_never_enters_sentence_or_request` — an integration run with `_scope` set; the generator/LLM boundary doubled, capturing the rendered instruction; asserts `"pages/dashboard" not in captured_instruction` and `"pages/dashboard" not in prepared.addressing_text` (a cache miss — generation runs)
- [ ] Run validation: `/opt/project/bin/pytest tests/test_groups_integration.py -v` then `/opt/project/bin/pytest tests/ -x`

---

## Validation Commands

All commands run in the `/opt/project` venv (create per Task 1 if missing; when that path is not creatable, the
Task 1 fallback venv path substitutes for `/opt/project` in every command below). Run from the repository root.

- `/opt/project/bin/pytest tests/ -x`: Run all tests (conventions' run-all command)
- `/opt/project/bin/pytest tests/<path>.py -v`: Run a specific test file (focused REPL-cycle feedback)
- `/opt/project/bin/ruff check prettyplay/ tests/`: Lint check — zero errors required (conventions' lint command; the enforced gate)
- `/opt/project/bin/ruff format <touched files>`: Format the files a task wrote or edited (the tree is not globally format-clean — never reformat untouched files)
- `/opt/project/bin/python -c "from prettyplay import PrettyPlay, PrettyConfig, BrowserConfig, SiteConfig"`: Facade check — every re-export importable
- `/opt/project/bin/python -c "from prettyplay.config import SiteConfig; from prettyplay.cache import validate_step_scope"`: Cell facade check
- `goga lint`: Contract layer unchanged — 13 cells, 0 errors after every task

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location` (`models.py`/`loader.py`/`store.py`/`session.py`/`outcome.py`/`recovery.py`/`scenario.py`/`groups.py`/`executor.py`)
- [ ] Every contract entity is accessible from its facade (`SiteConfig`, `validate_step_scope`, the `prettyplay` re-export)
- [ ] Properties and methods match the declared API (`site_base_url`, `address_key`, `scope`, `_scope` surfaces, `execute(..., scope)`)
- [ ] Descriptions are reflected in behavior (two rings, scoped routing, sweep immunity, silent TLS, verbatim base URL, digest stability)
- [ ] Contract dependencies are met (`cache → failures` for `PrettyplayError`; `facade`, `groups → cache` for `addressing`)
- [ ] Re-exports are accessible from the facade (`from prettyplay import SiteConfig`)
- [ ] Every coding task followed the TDD workflow (contract tests → code → verification → logic tests → debugging → re-verification → lint)
- [ ] Contract tests and logic tests cover facade, API, and behavior within each coding task — all 29 design test scenarios exist and pass
- [ ] Integration tests exist for the cross-entity scenarios (Tasks 7 and 13)
- [ ] No package boundary was expanded; no new cells; no `.usages/` files changed (already current)
- [ ] `CODEMANIFEST` files were not modified (contract is read-only); `goga lint` still 13 cells / 0 errors
- [ ] The Mandatory Rules were followed: conventions-extracted style (R1), test rules (R2), ruff enforcement at every task and every local commit (R3), the REPL-cycle workflow (R4)
- [ ] All validation commands pass; unscoped cache digests byte-identical to the pre-change values (compatibility test green)
