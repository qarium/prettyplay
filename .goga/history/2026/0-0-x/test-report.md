# Test Report

## Changes Requiring Coverage

| Change | Type |
|---|---|
| `adopt_config` — verbatim adoption, no file/env access | behavior |
| `adopt_config` — empty `cache_root` → absolute `<cwd>/.prettyplay/cache` | behavior, edge |
| `adopt_config` — non-empty `cache_root` untouched | edge |
| `adopt_config` — works with no pyproject.toml anywhere (no `FileNotFoundError`) | regression |
| `PrettyPlay.__init__` — `config is None` still routes through `load_config()` (file layer) | regression |
| `PrettyPlay.__init__` — passed config taken verbatim (file values do not leak into unset fields) | behavior |
| `PrettyPlay.__init__` — `PRETTYPLAY_*` env never mutates a passed config | behavior |
| `PrettyPlay.__init__` — construction succeeds in a directory without pyproject.toml | regression |

## Tests Added

| Test Name | File | What It Validates |
|---|---|---|
| `TestAdoptConfig::test_adopt_config_takes_passed_values_verbatim` | tests/config/test_loader.py | A `[tool.prettyplay]` section in the run directory never reaches an adopted config; unset fields keep model defaults |
| `TestAdoptConfig::test_adopt_config_ignores_env_overrides` | tests/config/test_loader.py | `PRETTYPLAY_MODEL`/`PRETTYPLAY_STRICT` never touch an adopted config |
| `TestAdoptConfig::test_adopt_config_resolves_empty_cache_root_to_run_cwd_default` | tests/config/test_loader.py | Empty `cache_root` resolves to the absolute `<cwd>/.prettyplay/cache` |
| `TestAdoptConfig::test_adopt_config_keeps_non_empty_cache_root` | tests/config/test_loader.py | A set `cache_root` stays verbatim |
| `TestAdoptConfig::test_adopt_config_never_touches_the_filesystem_search` | tests/config/test_loader.py | `_find_pyproject` is never called — adoption needs no pyproject.toml |
| `TestPrettyPlayLogic::test_scenario_takes_passed_config_verbatim` | tests/test_scenario.py | A passed config is the complete effective config; the pyproject section in cwd does not back-fill unset fields; empty cache_root resolves |
| `TestPrettyPlayLogic::test_scenario_constructs_with_config_without_any_pyproject` | tests/test_scenario.py | Regression: no pyproject.toml upward — construction succeeds (the reported `FileNotFoundError`) |
| `TestPrettyPlayLogic::test_scenario_ignores_env_overrides_for_passed_config` | tests/test_scenario.py | Env overrides never mutate a programmatically passed config |

## Tests Modified

| Test Name | File | Change |
|---|---|---|
| `test_scenario_builds_own_runtime_per_test` | tests/test_scenario.py | `load_config` mock expectation `call(None, None)` → `call()` (new call shape for `config=None`) |
| `test_scenario_forwards_config_overrides_through_real_loader` → renamed `test_scenario_takes_passed_config_verbatim` | tests/test_scenario.py | Rewritten from the overlay semantics to the verbatim semantics per the approved plan |
| `test_pyproject_settings_reach_the_executor_config` | tests/test_integration.py | Mock `side_effect` follows the new `load_config()` call shape; the file-layer guarantee itself is preserved |

## Test Results

| Test Run | Status | Details |
|---|---|---|
| `pytest tests/ -q` (full suite) | PASS | 1524 passed, 1 skipped (pre-existing skip: no Playwright browser in the environment) |
| `ruff check tests/ prettyplay/` | PASS | All checks passed |
| Coverage of changed modules | PASS | `loader.py` 99% (miss: Python 3.10 `tomli` import, unreachable on 3.12), `scenario.py` 99% (pre-existing branch), `models.py` 100% |

## Coverage Gaps

| Changed Behavior | Covered? | Notes |
|---|---|---|
| `adopt_config` verbatim / cache_root / no-filesystem | yes | `TestAdoptConfig`, 5 tests |
| `PrettyPlay` verbatim branch + regressions | yes | 3 new + 1 rewritten scenario tests |
| `config=None` legacy path | yes | full existing loader suite + `test_pyproject_settings_reach_the_executor_config` |

No coverage gaps for changed behavior.

## Missing Coverage Analysis

None for the changed behavior. The two uncovered lines (`loader.py:15` — the Python 3.10 `tomli` fallback import; `scenario.py:98` — a pre-existing guard branch) are environmental/pre-existing and untouched by this change.
