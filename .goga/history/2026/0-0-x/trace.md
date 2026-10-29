# Trace Report

## Call Flow

```
integrator
  └─ PrettyPlay(cache_key, cache_path?, cleanup?, hooks?, config=PrettyConfig(...))   [scenario.py:150]
       └─ load_config(None, config)                                                    [scenario.py:181]
            ├─ _find_pyproject()            # ALWAYS walks cwd upward for pyproject.toml
            ├─ tomllib.load(path)           # ALWAYS parses the file layer
            ├─ _collect_env_overrides()     # ALWAYS applies PRETTYPLAY_* env vars
            ├─ PrettyConfig(**merged)       # file+env layer constructed
            └─ _apply_overrides(file_config, config)  # overlay of explicitly set fields only
       └─ PrettyplayRuntime(effective)      [runtime.py:23]
```

`load_config` is imported once at `prettyplay/scenario.py:16` (`from .config import PrettyConfig, load_config`) — the single resolution point; no other production call site exists.

## Data Flow

`PrettyConfig` instance (programmatic layer) → passed as `overrides` into `load_config` → merged over the pyproject+env layer via `model_copy` → effective config → `PrettyplayRuntime` → all engines (driver, llm, cache, engine/*).

Critical data-loss points in `_apply_overrides` (loader.py:239-276) when the passed config is pre-assembled:
- fields not in `model_fields_set` are dropped (file/env value survives)
- `None` values dropped (`polling_timeout=None` indistinguishable from unset)
- empty strings dropped (`""` never overrides the file layer)
- the `browser` group merges field-by-field the same way

## Manifest Algorithm Mapping

| CODEMANIFEST step (`load_config`) | Code path | Match |
|---|---|---|
| 1. Resolve pyproject path (explicit or upward search) | loader.py:303, `_find_pyproject` :117 | yes — runs unconditionally, even when `overrides` is a full config |
| 2–3. Parse TOML, extract section | loader.py:305-307 | yes — unconditional |
| 4–5. Legacy env/flat-key rejection | loader.py:309-312 | yes — unconditional |
| 6. Env overrides | loader.py:314, `_collect_env_overrides` :173 | yes — unconditional |
| 7. Default cache_root | loader.py:329-330 | yes — anchored at cwd |
| 9. `overrides is None` → return file layer | loader.py:337-338 | yes |
| 10–11. Overlay explicit fields | loader.py:340, `_apply_overrides` :239 | yes |

Root-cell manifest `PrettyPlay` Algorithm step 1 (`Resolve the effective config: load_config with overrides = config`) maps to scenario.py:181 — the manifest itself prescribes the always-load behavior. The contract text explicitly says: "`config`: per-test overrides … unset/empty fields resolve from pyproject+env".

## Cross-Cell Traversals

| Source Cell | Target Cell | Type | Path |
|---|---|---|---|
| prettyplay (root) | prettyplay/config | call | scenario.py:181 → loader.py:279 `load_config` |
| prettyplay (root) | prettyplay/config | data | `PrettyConfig` programmatic layer → effective config |
| prettyplay/config | prettyplay/failures | type | `ConfigurationError(PrettyplayError)` loader.py:108 |
| prettyplay (root) | prettyplay (runtime) | data | effective config → `PrettyplayRuntime.__init__` runtime.py:23 |

## Inconsistencies

| Type | Location | Expected | Actual |
|---|---|---|---|
| Design gap | scenario.py:181 + config/CODEMANIFEST `load_config` Algorithm | a way to pass a pre-assembled config taken verbatim | no such path exists: the file+env layer always loads and back-fills unset/empty fields; without a pyproject.toml upward the call dies with `FileNotFoundError` |
| Usage vs behavior | `.usages/configuration.md` "Per-test overrides — layered merge" | documents only the overlay semantics | consistent today, but documents no pre-assembled path either — same gap |

## Trace Graph

```
[pyproject.toml] ──parse──┐
[PRETTYPLAY_* env] ───────┼──► merged file layer ──► PrettyConfig(file)
                           │                              │
integrator ──PrettyConfig(ready)──► PrettyPlay.__init__   │
                                       │                  │
                                       └─ load_config(None, config)
                                            └─ _apply_overrides(file, ready)
                                                 └─ effective = file ⊕ explicit(ready)
                                                        ▲
                    ready.ready_fields NOT set / None / "" — LOST, file wins
```
