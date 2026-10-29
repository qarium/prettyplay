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
2. Export it from `prettyplay/config/__init__.py` (`__all__`); export stays out of the root facade unless the facade re-exports config symbols today (verify: root `prettyplay/__init__.py` does not re-export `load_config` — then no root export).
3. Rewire `scenario.py:181` to the `None`-check branch.
4. Update both CODEMANIFESTs (see Specification Impact) — current state, not changelogs.
5. Update the two usage files (see Usage Impact).
6. Update/add tests (see Test Strategy); run the full suite in the `/opt/project` venv.

## Specification Impact

- `prettyplay/config/CODEMANIFEST` — add Routine `"adopt_config(config: PrettyConfig) -> config: PrettyConfig"` (location `loader.py`): purpose, `config` param, `Algorithm` (empty-cache_root resolution only), `Requirements` (no file or env reads; never raises ConfigurationError — the model is pre-validated), `Constraints` (no layered merge). `load_config` block stays verbatim — its overlay branch remains available for direct library consumers.
- `prettyplay/CODEMANIFEST` — `PrettyPlay` `config` annotation: "the pre-assembled configuration, keyword-only — taken verbatim as the effective config (an empty cache_root resolves to the cwd default); None — everything resolves from pyproject+env via load_config". Algorithm step 1: branch `config is None → load_config(); otherwise → adopt_config(config)`.

## Usage Impact

- `prettyplay/config/.usages/configuration.md` — replace the "Per-test overrides — layered merge" section with "The programmatic configuration": a passed `PrettyConfig` is the complete effective config — pyproject/env never load for it; the file layer is only for `config=None`; keep examples rebuilt around the verbatim semantics; drop claims about the merge reaching inside the browser group.
- `prettyplay/.usages/lifecycle.md` — line 7: replace "A config passed to the test overrides only the explicitly set values — everything else resolves from pyproject+env" with the verbatim statement.
- `.goga/usages/conventions.md` — no change (rules, not recipes).

## Compatibility Verification

**NOT fully backward compatible — BREAKING CHANGE (user decision required).**
- `PrettyPlay(cache_key, config=partial_config)` today back-fills unset fields from pyproject+env; after the fix those fields stay at model defaults ("" / 0 / False / None). Same arguments → different effective config → the documented overlay guarantee changes (root CODEMANIFEST `config` annotation; configuration.md; test_scenario.py:545 pins it).
- Mitigations that limit the blast radius: `config=None` keeps today's file behavior unchanged; `load_config` public API unchanged; the pydantic model unchanged.
- Per the pipeline policy the STOP stands unless the user explicitly approves this breaking shape.

## Test Strategy

- `tests/config/test_loader.py`: new `TestAdoptConfig` — verbatim adoption (no pyproject present in `tmp_path`, no env influence), empty `cache_root` → absolute cwd default, non-empty `cache_root` untouched, returned model is the passed instance semantics (same values).
- `tests/test_scenario.py`:
  - update `test_scenario_forwards_config_overrides_through_real_loader` → becomes "a passed config is taken verbatim: file values do not leak, unset fields stay at defaults" (run inside `tmp_path` without pyproject).
  - update `test_scenario_builds_own_runtime_per_test` — `load_config` mock still sees `call(None, None)` for `config=None` (unchanged); add a companion assertion for the verbatim branch.
  - new: construction with a config succeeds in a directory with no pyproject.toml upward (the `FileNotFoundError` regression).
- Full suite `pytest tests/ -x` in the venv; `ruff check prettyplay/`.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Integrators relying on file-layer back-fill of partial configs | medium | high | Semantics is the user's explicit request; documented loudly in both usages; `config=None` path unchanged |
| Hidden env dependence in existing tests (PRETTYPLAY_* set in the test environment) | low | medium | Tests delenv today; run the suite in a clean venv shell |
| Facade/API expectation that `adopt_config` appears in the root `__all__` | low | low | Root facade does not re-export config loaders today; keep parity |
| Usage docs drift from the new semantics | low | medium | Both files updated in this change; drift analysis step validates |
