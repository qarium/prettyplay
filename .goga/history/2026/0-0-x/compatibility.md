# Compatibility Report

## Checklist Results

### API Compatibility
| Question | Answer | Evidence |
|----------|--------|----------|
| Function signature unchanged for existing callers? | YES | `load_config` untouched; `PrettyPlay.__init__` keeps the same parameter list (`config: PrettyConfig \| None`, keyword-only); only the internal resolution branch changes |
| Return type unchanged? | YES | `load_config -> PrettyConfig`, `PrettyPlay.__init__ -> None`, new `adopt_config -> PrettyConfig` is an addition |
| Default parameter values preserved? | YES | `config=None` default preserved; `pyproject_path=None` preserved |

### Semantic Compatibility
| Question | Answer | Evidence |
|----------|--------|----------|
| Same arguments produce same behavior? | **NO** | `PrettyPlay(cache_key, config=PrettyConfig(...partial...))` today back-fills unset fields from pyproject+env; after the fix those fields keep model defaults. Pinned today by test_scenario.py:545 |
| Output format unchanged? | YES | The effective object stays a validated `PrettyConfig`; no structure/format change — only which layer fills unset fields |
| File paths unchanged? | YES | No file path constants change; the file layer is simply not read when a config is passed (the fix itself) |
| Error messages and codes unchanged? | YES | `load_config` error rendering untouched; the `FileNotFoundError` for "config passed but no pyproject" disappears — that is the defect being fixed, not a guarantee |

### Algorithmic Compatibility
| Question | Answer | Evidence |
|----------|--------|----------|
| Manifest-defined algorithm steps preserved? | **NO** | `PrettyPlay` Algorithm step 1 changes from "load_config with overrides = config" to the branch "`None` → `load_config()`, passed → `adopt_config(config)`"; `load_config` own algorithm preserved verbatim; both manifests updated in the same change per the approved plan |
| Execution order unchanged? | YES | For `config=None` the order is byte-identical; the passed-config branch replaces the tail of the same step |
| Side effects unchanged? | **NO** | With a config passed, pyproject.toml reading and `PRETTYPLAY_*` env collection no longer happen — the requested defect fix |

### Consumer Compatibility
| Question | Answer | Evidence |
|----------|--------|----------|
| Existing tests pass without modification? | **NO** | test_scenario.py:545 pins the file-layer back-fill; test_scenario.py:533-540 (`call(None, None)` for `config=None`) keeps passing |
| Usage recipes remain valid? | **NO** | `configuration.md` "Per-test overrides — layered merge" and `lifecycle.md` line 7 recipes change to verbatim semantics; both updated in this change |
| Downstream consumers unaffected? | **NO** | Integrators passing partial configs relying on pyproject/env back-fill are affected; `config=None` consumers unaffected |

## Verdict

**BREAKING** — failed checkboxes: Semantic (same arguments → same behavior), Algorithmic (manifest algorithm steps, side effects), Consumer (existing tests, usage recipes, downstream consumers).

## Breaking Change Details

1. **`config` parameter semantics** (`PrettyPlay.__init__`): a passed `PrettyConfig` becomes the complete effective configuration taken verbatim; pyproject.toml and `PRETTYPLAY_*` env are no longer consulted for it; unset/empty fields keep model defaults instead of file-layer values. Unaffected: `config=None` behavior, the `load_config` public API, the `PrettyConfig` model.
2. **Manifest text**: root CODEMANIFEST `PrettyPlay` `config` annotation and Algorithm step 1 change; config cell gains the `adopt_config` routine. `load_config` contract stays verbatim.
3. **Documentation/recipes**: the layered-merge per-test override recipes in `configuration.md` and `lifecycle.md` become invalid — both rewritten in this change.
4. **Tests pinning old behavior**: `test_scenario_forwards_config_overrides_through_real_loader` and the construction assumptions it encodes — rewritten in this change.

**User override recorded**: at the planning checkpoint (question q2 of this run) the user explicitly selected "Утверждаю план с breaking-семантикой: config передан — берётся дословно (рекомендуется)". Per the pipeline Breaking Change Policy ("Only user can override a STOP"), the STOP is overridden and the pipeline proceeds with the approved breaking shape.
