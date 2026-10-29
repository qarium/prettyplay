# Change Plan

## Task Classification

Type: **bugfix** (behavioral contract fix). The reported defect — a pre-assembled `PrettyConfig` passed to `PrettyPlay` is still merged over the pyproject+env file layer instead of being taken verbatim — is a contract design gap; the fix changes the `config` parameter semantics to "pre-assembled, taken as-is".

## Affected Cells

| Cell | Files to Modify | What Changes |
|---|---|---|
| `prettyplay/config` | `loader.py` | New routine `adopt_config(config) -> PrettyConfig`: takes a pre-assembled config as the single layer; resolves an empty `cache_root` to the absolute `<cwd>/.prettyplay/cache` default; no file/env access |
| `prettyplay/config` | `__init__.py` | Export `adopt_config` in `__all__` |
| `prettyplay/config` | `CODEMANIFEST` | Declare the `adopt_config` routine (signature, annotations); keep `load_config` unchanged |
| `prettyplay/config` | `.usages/configuration.md` | Rewrite the "Per-test overrides — layered merge" section: a passed config is the complete configuration; `None` keeps the file layer |
| `prettyplay` (root) | `scenario.py` | `PrettyPlay.__init__`: `effective = load_config() if config is None else adopt_config(config)` |
| `prettyplay` (root) | `CODEMANIFEST` | Update `PrettyPlay` `config` parameter annotation + Algorithm step 1 |
| `prettyplay` (root) | `.usages/lifecycle.md` | Update the construction paragraph (line 7) to the verbatim semantics |

## Root Cause Analysis

No "pre-assembled config" path exists. `PrettyPlay.__init__` (scenario.py:181) routes every passed config through `load_config(None, config)`, which by manifest and by code always loads pyproject+env first and back-fills every unset/`None`/empty field from that layer (loader.py:303-340). Without a pyproject.toml upward from cwd the construction dies with `FileNotFoundError`; `PRETTYPLAY_*` env vars mutate fields left at defaults.

## Trace Summary

`PrettyPlay.__init__` → `load_config(None, config)` → `_find_pyproject` → env collect → `PrettyConfig(file)` → `_apply_overrides` (drops unset/None/empty) → effective. New path: `PrettyPlay.__init__` → `adopt_config(config)` → effective (single layer).

## Change Strategy

1. Add `adopt_config` to `prettyplay/config/loader.py`: docstring per conventions; resolve empty `cache_root` to `str(Path.cwd() / ".prettyplay" / "cache")`; return the model as-is otherwise (already validated by pydantic at construction).
2. Export it from `prettyplay/config/__init__.py` (`__all__`); root facade stays unchanged (it does not re-export config loaders).
3. Rewire `scenario.py:181` to the `None`-check branch.
4. Update both CODEMANIFESTs — current state, not changelogs.
5. Update the usage files.
6. Update/add tests; run the full suite in the external venv.

## Specification Impact

- `prettyplay/config/CODEMANIFEST` — add Routine `adopt_config` (location `loader.py`) with purpose, `Algorithm`, `Requirements`, `Constraints`; header directive about verbatim adoption; `load_config` block stays verbatim.
- `prettyplay/CODEMANIFEST` — `PrettyPlay` `config` annotation and Algorithm step 1 updated; `adopt_config` added to `Imports`.

## Usage Impact

- `prettyplay/config/.usages/configuration.md` — "Per-test overrides — layered merge" → "The programmatic configuration"; `adopt_config` recipe under "Loading"; wording unified.
- `prettyplay/.usages/lifecycle.md` — composition paragraph and strict/interactive wording.
- `README.md`, `docs/**` — public statements of the removed overlay updated; migration note added.

## Compatibility Verification

**NOT fully backward compatible — BREAKING CHANGE, user-approved.** Same arguments (`PrettyPlay(cache_key, config=partial)`) now yield a different effective config: unset fields keep model defaults instead of pyproject/env values. Mitigations: `config=None` unchanged; `load_config` unchanged; models unchanged. User override recorded at the planning checkpoint (question q2) and in `escalation.md`.

## Test Strategy

New `TestAdoptConfig` (5 tests) + 3 new scenario tests + 1 rewritten scenario test + 2 call-shape fixes; full suite and ruff in the external venv.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Integrators relying on file-layer back-fill of partial configs | medium | high | User-approved semantics; documented loudly; `config=None` path unchanged |
| Hidden env dependence in existing tests | low | medium | Tests delenv; suite green in a clean venv shell |
| Docs drift | low | medium | README + docs updated in this change |

---

# Change Execution Report

## Summary

The user reported that passing an already-assembled `PrettyConfig` to prettyplay still triggers a full configuration load instead of honoring the ready instance. The goga-change pipeline located the root cause (no verbatim adoption path existed — every passed config was routed through `load_config`), planned a fix, and implemented it as a user-approved breaking contract change: a passed config is now the complete effective configuration (`adopt_config`), while `config=None` keeps the pyproject+env file layer unchanged. Manifests, cell usages and public docs were reconciled; the suite is green.

## Root Cause

`PrettyPlay.__init__` unconditionally called `load_config(None, config)` (scenario.py:181); by contract and code that loader always reads pyproject.toml upward from cwd plus `PRETTYPLAY_*` env and back-fills every unset/`None`/empty field of the passed config from that layer. Consequences: `FileNotFoundError` without a pyproject anywhere; env/file values silently mutating an assembled config; intentionally empty fields ignored.

## Modified Cells

| Cell | Files Modified |
|---|---|
| `prettyplay/config` | `loader.py`, `__init__.py`, `CODEMANIFEST`, `.usages/configuration.md` |
| `prettyplay` (root) | `scenario.py`, `CODEMANIFEST`, `.usages/lifecycle.md` |
| public documentation | `README.md`, `docs/configuration.md`, `docs/getting-started.md`, `docs/guides/browser-setup.md`, `docs/reference/interactive-steering.md` |
| tests | `tests/config/test_loader.py`, `tests/test_scenario.py`, `tests/test_integration.py` |

## Implemented Changes

| Change | File | Description |
|---|---|---|
| Verbatim adoption routine | `prettyplay/config/loader.py` | `adopt_config(config) -> PrettyConfig`: resolves only an empty `cache_root` to the absolute `<cwd>/.prettyplay/cache`; no pyproject/env reads |
| Cell facade export | `prettyplay/config/__init__.py` | `adopt_config` in `__all__` |
| Construction branch | `prettyplay/scenario.py` | `effective = load_config() if config is None else adopt_config(config)`; parameter docstring updated |
| Config contract | `prettyplay/config/CODEMANIFEST` | New routine `adopt_config`; header verbatim-adoption directive; footer Description |
| Facade contract | `prettyplay/CODEMANIFEST` | `Imports` += `adopt_config`; `PrettyPlay.config` annotation; Algorithm step 1 |
| Cell usages | `configuration.md`, `lifecycle.md` | Verbatim semantics documented; `adopt_config` recipe |
| Public docs | `README.md`, `docs/**` | Overlay statements replaced; migration note added |
| Tests | `tests/**` | 8 new tests, 1 rewritten, 2 call-shape updates |

## Tests Added

| Test | File | What It Validates |
|---|---|---|
| `test_adopt_config_takes_passed_values_verbatim` | tests/config/test_loader.py | A `[tool.prettyplay]` section in the run dir never reaches an adopted config |
| `test_adopt_config_ignores_env_overrides` | tests/config/test_loader.py | `PRETTYPLAY_*` never mutates an adopted config |
| `test_adopt_config_resolves_empty_cache_root_to_run_cwd_default` | tests/config/test_loader.py | Empty `cache_root` → absolute `<cwd>/.prettyplay/cache` |
| `test_adopt_config_keeps_non_empty_cache_root` | tests/config/test_loader.py | A set `cache_root` stays verbatim |
| `test_adopt_config_never_touches_the_filesystem_search` | tests/config/test_loader.py | `_find_pyproject` never called — works with no pyproject |
| `test_scenario_takes_passed_config_verbatim` | tests/test_scenario.py | The passed config is the complete effective config (rewritten from the overlay pin) |
| `test_scenario_constructs_with_config_without_any_pyproject` | tests/test_scenario.py | Regression: no pyproject upward — construction succeeds |
| `test_scenario_ignores_env_overrides_for_passed_config` | tests/test_scenario.py | Env never mutates a programmatically passed config |

## Specification Updates

| Cell | CODEMANIFEST Changes | Usage Changes |
|---|---|---|
| `prettyplay/config` | + Routine `adopt_config`; header directive; Description | `configuration.md` rewritten programmatic-configuration section + Loading recipe |
| `prettyplay` | `Imports` += `adopt_config`; `PrettyPlay.config` + Algorithm step 1 | `lifecycle.md` composition + wording |

## Validation Results

**VERIFIED.** `pytest tests/ -q` — 1524 passed, 1 pre-existing skip; `ruff check prettyplay/ tests/` — clean; `goga lint` — 13 cells, 0 errors; coverage of changed modules 99–100%; facade smoke check passes (construction with a passed config in a pyproject-free directory).

## Compatibility Status

BREAKING (user-approved): `PrettyPlay(cache_key, config=partial_config)` no longer back-fills unset fields from pyproject+env — they keep model defaults. Preserved: `load_config` API/algorithm, `config=None` behavior, models, facade exports. Override recorded in `compatibility.md` and `escalation.md`.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Integrators relying on overlay back-fill | high | Migration note in docs; `config=None` path unchanged; loud documentation |
| Undocumented consumer expecting `FileNotFoundError` | low | That behavior was the defect; nothing in-repo relied on it (suite green) |
| Docs drift | low | All statements reconciled in this change; drift analysis clean |

## Updated Files

- prettyplay/config/loader.py
- prettyplay/config/__init__.py
- prettyplay/config/CODEMANIFEST
- prettyplay/config/.usages/configuration.md
- prettyplay/scenario.py
- prettyplay/CODEMANIFEST
- prettyplay/.usages/lifecycle.md
- README.md
- docs/configuration.md
- docs/getting-started.md
- docs/guides/browser-setup.md
- docs/reference/interactive-steering.md
- tests/config/test_loader.py
- tests/test_scenario.py
- tests/test_integration.py
- .goga/history/2026/0-0-x/{scope-resolution,trace,investigation,plan,compatibility,escalation,test-report,manifest-reconciliation,usage-reconciliation,drift-analysis,validation}.md
